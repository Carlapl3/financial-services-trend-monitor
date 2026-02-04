"""
Tests that feedback-driven prioritization works through the agent tool path.

Verifies that tool_render_digest() applies relevance boosts when
FEEDBACK_RECIPIENT_EMAIL is configured, closing the gap between
the agent execution path and the digest subcommand.
"""

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from src.feedback.relevance_store import RelevanceStore
from src.models import Category, ImpactLevel, TrendItem
from src.pipeline.dedupe import TrendItemStorage


RECIPIENT = "agent-test@example.com"


def _make_item(item_id: str, impact: ImpactLevel, days_ago: int) -> TrendItem:
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


def test_agent_render_digest_applies_feedback_boost():
    """tool_render_digest must boost items marked relevant by the feedback recipient."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Set up storage with two items: older item_a, newer item_b, same impact
        storage_path = str(Path(tmpdir) / "items.jsonl")
        feedback_path = str(Path(tmpdir) / "relevance.jsonl")

        id_a = "aaaa1111aaaa1111"
        id_b = "bbbb2222bbbb2222"
        item_a = _make_item(id_a, ImpactLevel.MEDIUM, days_ago=2)
        item_b = _make_item(id_b, ImpactLevel.MEDIUM, days_ago=1)

        storage = TrendItemStorage(storage_path)
        storage.save(item_a)
        storage.save(item_b)

        # Record feedback: item_a is relevant
        feedback_store = RelevanceStore(storage_path=feedback_path)
        feedback_store.save_relevant(email=RECIPIENT, item_id=id_a)

        # Call tool_render_digest with FEEDBACK_RECIPIENT_EMAIL set
        env = {"FEEDBACK_RECIPIENT_EMAIL": RECIPIENT}
        with patch.dict(os.environ, env), \
             patch("src.agent.tools.TrendItemStorage", return_value=storage), \
             patch("src.feedback.relevance_store.RelevanceStore", return_value=feedback_store):

            from src.agent.tools import tool_render_digest
            result = tool_render_digest(days_lookback=7, max_items=20, format="text")

        assert result["success"] is True
        assert result["items_included"] == 2

        # item_a (boosted) must appear before item_b (not boosted) in output
        digest = result["digest"]
        pos_a = digest.index(id_a)
        pos_b = digest.index(id_b)
        assert pos_a < pos_b, (
            "Boosted item_a must appear before non-boosted item_b in agent digest"
        )


def test_agent_render_digest_no_boost_without_env():
    """Without FEEDBACK_RECIPIENT_EMAIL, newer items appear first (no boost)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = str(Path(tmpdir) / "items.jsonl")

        id_a = "aaaa1111aaaa1111"
        id_b = "bbbb2222bbbb2222"
        item_a = _make_item(id_a, ImpactLevel.MEDIUM, days_ago=2)
        item_b = _make_item(id_b, ImpactLevel.MEDIUM, days_ago=1)

        storage = TrendItemStorage(storage_path)
        storage.save(item_a)
        storage.save(item_b)

        # No FEEDBACK_RECIPIENT_EMAIL or EMAIL_TO set
        env_clear = {
            k: v for k, v in os.environ.items()
            if k not in ("FEEDBACK_RECIPIENT_EMAIL", "EMAIL_TO")
        }
        with patch.dict(os.environ, env_clear, clear=True), \
             patch("src.agent.tools.TrendItemStorage", return_value=storage):

            from src.agent.tools import tool_render_digest
            result = tool_render_digest(days_lookback=7, max_items=20, format="text")

        assert result["success"] is True

        # Without boost, newer item_b should appear first
        digest = result["digest"]
        pos_a = digest.index(id_a)
        pos_b = digest.index(id_b)
        assert pos_b < pos_a, (
            "Without feedback, newer item_b should appear before older item_a"
        )
