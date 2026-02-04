"""
Full-flow integration tests for feedback loop.

Verifies the end-to-end cycle:
  1. Digest renders "Relevant ✓" links
  2. Clicking link stores relevance feedback
  3. Subsequent digest boosts the clicked item
  4. System behaves correctly when feedback is absent
"""

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.feedback.relevance_store import RelevanceStore
from src.feedback.server import create_app
from src.models import Category, ImpactLevel, TrendItem
from src.pipeline.digest import DigestGenerator


def _make_item(item_id: str, impact: ImpactLevel = ImpactLevel.MEDIUM, days_ago: int = 1) -> TrendItem:
    """Create a TrendItem with explicit id for testing."""
    now = datetime.now(timezone.utc)
    return TrendItem(
        id=item_id,
        title=f"Item {item_id}",
        publication_date=now - timedelta(days=days_ago),
        source_url=f"https://example.com/{item_id}",
        summary=f"Summary for {item_id}",
        category=Category.PAYMENTS,
        impact_level=impact,
        why_it_matters=f"Insight for {item_id}",
    )


RECIPIENT = "user@example.com"
FEEDBACK_BASE = "https://feedback.example.com"


def test_feedback_loop_end_to_end():
    """Exercise the complete feedback cycle in-process.

    Steps:
      1. Generate a digest → assert "Relevant ✓" links present
      2. Simulate click via TestClient → assert feedback stored
      3. Generate a second digest with same store → assert boosted ordering
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        store_path = str(Path(tmpdir) / "relevance.jsonl")
        store = RelevanceStore(storage_path=store_path)

        id_a = "aaaa1111aaaa1111"
        id_b = "bbbb2222bbbb2222"
        item_a = _make_item(id_a, impact=ImpactLevel.MEDIUM, days_ago=2)
        item_b = _make_item(id_b, impact=ImpactLevel.MEDIUM, days_ago=1)
        items = [item_a, item_b]

        # ── Step 1: First digest renders "Relevant ✓" links ──────────────
        env = {"FEEDBACK_BASE_URL": FEEDBACK_BASE}
        with patch.dict(os.environ, env):
            # Patch RelevanceStore where DigestGenerator imports it (local
            # import inside __init__) so it returns our tmpdir-backed store.
            with patch(
                "src.feedback.relevance_store.RelevanceStore",
                return_value=store,
            ):
                gen1 = DigestGenerator(recipient_email=RECIPIENT)
                result1 = gen1.generate(items, format="html", run_id="run-001")

        html1 = result1["html"]
        assert "Relevant" in html1, "First digest must contain 'Relevant' link text"
        assert f"item_id={id_a}" in html1, "Link must include item_a's id"
        assert f"item_id={id_b}" in html1, "Link must include item_b's id"
        assert f"email={RECIPIENT.replace('@', '%40')}" in html1, (
            "Link must include URL-encoded recipient email"
        )
        assert "run_id=run-001" in html1

        # ── Step 2: Simulate clicking the link for item_a ────────────────
        client = TestClient(create_app(store=store))
        resp = client.get(
            "/feedback/relevant",
            params={"item_id": id_a, "email": RECIPIENT},
        )
        assert resp.status_code == 200, f"Feedback endpoint returned {resp.status_code}"
        assert "Thanks" in resp.text

        # Verify persistence
        assert store.get_relevant_item_ids(RECIPIENT) == {id_a}

        # ── Step 3: Second digest boosts the clicked item ────────────────
        with patch.dict(os.environ, env):
            with patch(
                "src.feedback.relevance_store.RelevanceStore",
                return_value=store,
            ):
                gen2 = DigestGenerator(recipient_email=RECIPIENT)
                result2 = gen2.generate(items, format="html", run_id="run-002")

        # item_a (clicked → boosted) should appear before item_b even though
        # item_b is more recent and both have the same impact level.
        html2 = result2["html"]
        pos_a = html2.index(id_a)
        pos_b = html2.index(id_b)
        assert pos_a < pos_b, (
            "Boosted item_a must appear before non-boosted item_b in second digest"
        )


def test_v2_unchanged_without_feedback():
    """Without recipient / FEEDBACK_BASE_URL the system uses default prioritization.

    Specifically:
      - No "Relevant" link in rendered HTML
      - Ordering is purely impact + recency (no boost)
    """
    id_older = "cccc3333cccc3333"
    id_newer = "dddd4444dddd4444"
    older = _make_item(id_older, impact=ImpactLevel.MEDIUM, days_ago=3)
    newer = _make_item(id_newer, impact=ImpactLevel.MEDIUM, days_ago=1)

    # Ensure FEEDBACK_BASE_URL is absent
    env_clear = {k: v for k, v in os.environ.items() if k != "FEEDBACK_BASE_URL"}
    with patch.dict(os.environ, env_clear, clear=True):
        gen = DigestGenerator()  # no recipient_email
        result = gen.generate([older, newer], format="html")

    html = result["html"]

    # No feedback links
    assert "Relevant" not in html, (
        "default mode must not render 'Relevant' links"
    )

    # Recency wins (newer before older) since no boost is active
    pos_newer = html.index(id_newer)
    pos_older = html.index(id_older)
    assert pos_newer < pos_older, (
        "Without boost, more recent item must appear first"
    )


# ── E3 edge-case tests ───────────────────────────────────────────────


def test_tracking_vs_meaningful_url_dedupe():
    """Two URLs differing only by tracking params are deduped; meaningful params are not."""
    from src.pipeline.dedupe import TrendItemStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = str(Path(tmpdir) / "items.jsonl")
        storage = TrendItemStorage(storage_path)

        now = datetime.now(timezone.utc)
        base_item = TrendItem(
            title="Payments Update",
            publication_date=now,
            source_url="https://example.com/article?id=100",
            summary="Summary A",
            category=Category.PAYMENTS,
            impact_level=ImpactLevel.HIGH,
            why_it_matters="Insight A",
        )
        tracking_item = TrendItem(
            title="Payments Update (tracking)",
            publication_date=now,
            source_url="https://example.com/article?id=100&utm_source=newsletter",
            summary="Summary B",
            category=Category.PAYMENTS,
            impact_level=ImpactLevel.HIGH,
            why_it_matters="Insight B",
        )
        different_id_item = TrendItem(
            title="Different Article",
            publication_date=now,
            source_url="https://example.com/article?id=200",
            summary="Summary C",
            category=Category.PAYMENTS,
            impact_level=ImpactLevel.MEDIUM,
            why_it_matters="Insight C",
        )

        assert storage.save(base_item) is True, "First save should succeed"
        assert storage.save(tracking_item) is False, "Tracking-only difference should be deduped"
        assert storage.save(different_id_item) is True, "Different meaningful param should save"

        all_items = storage.load_all()
        assert len(all_items) == 2, f"Expected 2 stored items, got {len(all_items)}"


def test_item_ids_consistent_across_tracking_variants():
    """IDs generated from tracking vs clean URLs match."""
    from src.pipeline.dedupe import TrendItemStorage

    url_clean = "https://example.com/news?article=42"
    url_tracking = "https://example.com/news?article=42&utm_campaign=weekly&fbclid=xyz"

    id_clean = TrendItemStorage.generate_item_id(url_clean)
    id_tracking = TrendItemStorage.generate_item_id(url_tracking)
    assert id_clean == id_tracking, "IDs should match when only tracking params differ"


def test_relevance_boost_only_exact_item_id():
    """Relevance click on item_a must not boost item_b."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store_path = str(Path(tmpdir) / "relevance.jsonl")
        store = RelevanceStore(storage_path=store_path)

        id_a = "aaaa1111aaaa1111"
        id_b = "bbbb2222bbbb2222"
        item_a = _make_item(id_a, impact=ImpactLevel.MEDIUM, days_ago=2)
        item_b = _make_item(id_b, impact=ImpactLevel.MEDIUM, days_ago=1)

        # Record relevance for item_a only
        store.save_relevant(email=RECIPIENT, item_id=id_a)

        gen = DigestGenerator(days_lookback=7)
        gen._relevant_ids = store.get_relevant_item_ids(RECIPIENT)

        prioritized = gen.prioritize_items([item_a, item_b])

        # item_a is boosted → should come first despite being older
        assert prioritized[0].id == id_a, "Only the exact clicked item should be boosted"
        assert prioritized[1].id == id_b, "Non-clicked item should not be boosted"
