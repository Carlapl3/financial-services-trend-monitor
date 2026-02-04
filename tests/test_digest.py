"""
Unit tests for digest generation pipeline.

Tests DigestGenerator prioritization, selection, and rendering.
"""

from datetime import datetime, timedelta, timezone

from src.pipeline.digest import DigestGenerator
from src.models import TrendItem, Category, ImpactLevel


def create_test_items() -> list[TrendItem]:
    """Create a diverse set of test items."""
    now = datetime.now(timezone.utc)  # Use current time for date filtering to work

    return [
        # High impact, recent
        TrendItem(
            title="ECB Digital Euro Launch",
            publication_date=now - timedelta(days=1),
            source_url="https://ecb.europa.eu/1",
            summary="Major announcement",
            category=Category.PAYMENTS,
            impact_level=ImpactLevel.HIGH,
            why_it_matters="Critical for Swedish banks"
        ),
        # High impact, less recent
        TrendItem(
            title="EBA Capital Guidelines",
            publication_date=now - timedelta(days=3),
            source_url="https://eba.europa.eu/2",
            summary="New requirements",
            category=Category.REGULATORY,
            impact_level=ImpactLevel.HIGH,
            why_it_matters="Immediate compliance needed"
        ),
        # Medium impact, very recent
        TrendItem(
            title="Payment Regulation Update",
            publication_date=now - timedelta(hours=12),
            source_url="https://ec.europa.eu/3",
            summary="New instant payment rules",
            category=Category.PAYMENTS,
            impact_level=ImpactLevel.MEDIUM,
            why_it_matters="Infrastructure changes required"
        ),
        # Medium impact, older
        TrendItem(
            title="Basel Committee Report",
            publication_date=now - timedelta(days=5),
            source_url="https://bis.org/4",
            summary="International standards update",
            category=Category.REGULATORY,
            impact_level=ImpactLevel.MEDIUM,
            why_it_matters="Long-term planning impact"
        ),
        # Low impact, recent
        TrendItem(
            title="Industry Survey Results",
            publication_date=now - timedelta(days=2),
            source_url="https://example.com/5",
            summary="Market sentiment data",
            category=Category.PAYMENTS,
            impact_level=ImpactLevel.LOW,
            why_it_matters="Background context for discussions"
        ),
        # Old item (should be filtered out with 7-day lookback)
        TrendItem(
            title="Old News Article",
            publication_date=now - timedelta(days=10),
            source_url="https://example.com/old",
            summary="Outdated information",
            category=Category.REGULATORY,
            impact_level=ImpactLevel.HIGH,
            why_it_matters="No longer relevant"
        ),
    ]


def test_prioritization():
    """Test that items are prioritized correctly (impact then recency)."""
    print("\n" + "="*60)
    print("TEST 1: Prioritization (Impact → Recency)")
    print("="*60)

    items = create_test_items()
    generator = DigestGenerator()

    # Prioritize items
    prioritized = generator.prioritize_items(items)

    print(f"\nPrioritized order:")
    now = datetime.now(timezone.utc)
    for i, item in enumerate(prioritized, 1):
        days_ago = (now - item.publication_date).days
        print(f"  {i}. [{item.impact_level.value:6}] {item.title[:40]:40} ({days_ago}d ago)")

    # Assertions
    # First two should be HIGH impact
    assert prioritized[0].impact_level == ImpactLevel.HIGH
    assert prioritized[1].impact_level == ImpactLevel.HIGH

    # Within HIGH impact, more recent should come first
    assert prioritized[0].publication_date > prioritized[1].publication_date, \
        "Within same impact level, more recent should be first"

    # High should come before Medium
    high_indices = [i for i, item in enumerate(prioritized) if item.impact_level == ImpactLevel.HIGH]
    medium_indices = [i for i, item in enumerate(prioritized) if item.impact_level == ImpactLevel.MEDIUM]
    if high_indices and medium_indices:
        assert max(high_indices) < min(medium_indices), \
            "All HIGH impact should come before MEDIUM"

    print("\n✓ Test passed: Prioritization working correctly")


def test_item_selection():
    """Test that items are selected based on date range."""
    print("\n" + "="*60)
    print("TEST 2: Item Selection (7-day lookback)")
    print("="*60)

    items = create_test_items()
    generator = DigestGenerator(days_lookback=7, max_items=20)

    # Select items
    selected = generator.select_items(items)

    print(f"\nTotal items: {len(items)}")
    print(f"Selected items: {len(selected)}")

    # Old item (10 days ago) should be filtered out
    old_titles = [item.title for item in selected]
    assert "Old News Article" not in old_titles, \
        "Items older than 7 days should be excluded"

    # All other items should be included
    assert len(selected) == 5, f"Should have 5 items (excluding old one), got {len(selected)}"

    print("\n✓ Test passed: Date filtering working correctly")


def test_max_items_limit():
    """Test that max_items limit is respected."""
    print("\n" + "="*60)
    print("TEST 3: Max Items Limit")
    print("="*60)

    # Create many items
    now = datetime.now(timezone.utc)
    many_items = [
        TrendItem(
            title=f"Article {i}",
            publication_date=now - timedelta(days=i % 7),  # Within 7 days
            source_url=f"https://example.com/{i}",
            summary=f"Summary {i}",
            category=Category.PAYMENTS if i % 2 == 0 else Category.REGULATORY,
            impact_level=ImpactLevel.HIGH if i < 10 else ImpactLevel.MEDIUM,
            why_it_matters=f"Reason {i}"
        )
        for i in range(30)
    ]

    generator = DigestGenerator(max_items=15)
    selected = generator.select_items(many_items)

    print(f"\nTotal items: {len(many_items)}")
    print(f"Max limit: 15")
    print(f"Selected: {len(selected)}")

    assert len(selected) == 15, f"Should limit to 15 items, got {len(selected)}"

    print("\n✓ Test passed: Max items limit respected")


def test_text_rendering():
    """Test plain text digest rendering."""
    print("\n" + "="*60)
    print("TEST 4: Plain Text Rendering")
    print("="*60)

    items = create_test_items()[:3]  # Use first 3 items
    generator = DigestGenerator()

    text = generator.render_text(items)

    # Check key elements
    assert "FINANCIAL SERVICES TREND DIGEST" in text
    assert "HIGH IMPACT" in text
    assert "ECB Digital Euro Launch" in text
    assert "Why it matters:" in text
    assert "Category:" in text
    assert "Source:" in text

    print(f"\nGenerated text digest ({len(text)} chars)")
    print("\nFirst 500 chars:")
    print(text[:500])

    print("\n✓ Test passed: Text rendering includes all key elements")


def test_html_rendering():
    """Test HTML digest rendering."""
    print("\n" + "="*60)
    print("TEST 5: HTML Rendering")
    print("="*60)

    items = create_test_items()[:3]
    generator = DigestGenerator()

    html = generator.render_html(items)

    # Check HTML structure
    assert "<!DOCTYPE html>" in html
    assert "<html" in html
    assert "viewport" in html, "Should be mobile-friendly"
    assert "<style>" in html, "Should include inline CSS"
    assert "High Impact" in html
    assert "ECB Digital Euro Launch" in html
    assert "Why it matters:" in html
    assert 'class="badge' in html, "Should have category badges"
    assert "Read more" in html

    # Check mobile-friendly meta tag
    assert 'name="viewport"' in html

    print(f"\nGenerated HTML digest ({len(html)} chars)")
    print("\nHTML structure:")
    print("  ✓ DOCTYPE declaration")
    print("  ✓ Mobile viewport meta tag")
    print("  ✓ Inline CSS for styling")
    print("  ✓ Responsive design")
    print("  ✓ Impact level sections")
    print("  ✓ Category badges")
    print("  ✓ Source links")

    print("\n✓ Test passed: HTML rendering complete and mobile-friendly")


def test_generate_both_formats():
    """Test generating both text and HTML formats."""
    print("\n" + "="*60)
    print("TEST 6: Generate Both Formats")
    print("="*60)

    items = create_test_items()
    generator = DigestGenerator()

    result = generator.generate(items, format="both")

    # Check result structure
    assert "text" in result, "Should include text format"
    assert "html" in result, "Should include HTML format"
    assert "items_included" in result
    assert "total_items" in result

    print(f"\nGeneration results:")
    print(f"  Total items: {result['total_items']}")
    print(f"  Items included: {result['items_included']}")
    print(f"  Text format: {len(result['text'])} chars")
    print(f"  HTML format: {len(result['html'])} chars")

    # Both formats should be non-empty
    assert len(result["text"]) > 100
    assert len(result["html"]) > 100

    # Should only include recent items (not the 10-day-old one)
    assert result["items_included"] == 5

    print("\n✓ Test passed: Both formats generated successfully")


##############################################################################
# feedback integration tests
##############################################################################

import os
from unittest.mock import patch


def _item_with_id(item_id, impact=ImpactLevel.MEDIUM, days_ago=1):
    """Helper: create a TrendItem with a specific id."""
    now = datetime.now(timezone.utc)
    return TrendItem(
        id=item_id,
        title=f"Item {item_id}",
        publication_date=now - timedelta(days=days_ago),
        source_url=f"https://example.com/{item_id}",
        summary="Test summary",
        category=Category.PAYMENTS,
        impact_level=impact,
        why_it_matters="Test insight",
    )


def test_relevant_link_rendered_when_env_set():
    """Relevant link appears when FEEDBACK_BASE_URL is set and item has id."""
    item = _item_with_id("abc123")
    gen = DigestGenerator(recipient_email="user@test.com")

    with patch.dict(os.environ, {"FEEDBACK_BASE_URL": "https://fb.example.com"}):
        html = gen._format_item_html(item, run_id="digest-2026-01-29-0800")

    assert "Relevant" in html
    assert "item_id=abc123" in html
    assert "email=user%40test.com" in html
    assert "run_id=digest-2026-01-29-0800" in html
    assert "fb.example.com/feedback/relevant" in html


def test_no_link_without_env():
    """No feedback link when FEEDBACK_BASE_URL is not set."""
    item = _item_with_id("abc123")
    gen = DigestGenerator(recipient_email="user@test.com")

    with patch.dict(os.environ, {}, clear=True):
        # Ensure FEEDBACK_BASE_URL is absent
        os.environ.pop("FEEDBACK_BASE_URL", None)
        html = gen._format_item_html(item, run_id="run1")

    assert "Relevant" not in html


def test_no_link_without_item_id():
    """No feedback link when item has no id."""
    now = datetime.now(timezone.utc)
    item = TrendItem(
        title="No-ID item",
        publication_date=now - timedelta(days=1),
        source_url="https://example.com/noid",
        summary="Summary",
        category=Category.PAYMENTS,
        impact_level=ImpactLevel.MEDIUM,
        why_it_matters="Insight",
    )
    gen = DigestGenerator(recipient_email="user@test.com")

    with patch.dict(os.environ, {"FEEDBACK_BASE_URL": "https://fb.example.com"}):
        html = gen._format_item_html(item, run_id="run1")

    assert "Relevant" not in html


def test_no_link_without_recipient():
    """No feedback link when recipient_email is not provided."""
    item = _item_with_id("abc123")
    gen = DigestGenerator()  # no recipient

    with patch.dict(os.environ, {"FEEDBACK_BASE_URL": "https://fb.example.com"}):
        html = gen._format_item_html(item, run_id="run1")

    assert "Relevant" not in html


def test_relevance_boost_prioritization():
    """Item with relevance boost sorts above same-impact item without boost."""
    boosted = _item_with_id("boosted", impact=ImpactLevel.MEDIUM, days_ago=2)
    normal = _item_with_id("normal", impact=ImpactLevel.MEDIUM, days_ago=1)

    gen = DigestGenerator()
    gen._relevant_ids = {"boosted"}

    prioritized = gen.prioritize_items([normal, boosted])

    assert prioritized[0].id == "boosted", (
        "Boosted item should sort first despite being older"
    )
    assert prioritized[1].id == "normal"


def test_no_boost_without_recipient():
    """Without recipient, prioritization uses only impact+recency (default behavior)."""
    older = _item_with_id("older", impact=ImpactLevel.MEDIUM, days_ago=3)
    newer = _item_with_id("newer", impact=ImpactLevel.MEDIUM, days_ago=1)

    gen = DigestGenerator()  # no recipient → _relevant_ids is empty

    prioritized = gen.prioritize_items([older, newer])
    assert prioritized[0].id == "newer", "Without boost, recency wins"


def test_generate_passes_run_id_to_html():
    """run_id flows from generate() through to the rendered HTML."""
    item = _item_with_id("abc123")
    gen = DigestGenerator(recipient_email="user@test.com")

    with patch.dict(os.environ, {"FEEDBACK_BASE_URL": "https://fb.example.com"}):
        result = gen.generate(
            [item], format="html", run_id="digest-2026-01-29-0800"
        )

    assert "run_id=digest-2026-01-29-0800" in result["html"]


def test_select_items_handles_naive_datetimes():
    """Items with naive (no tz) datetimes are handled without exception."""
    naive_now = datetime(2026, 1, 28, 12, 0, 0)  # no tzinfo
    item = TrendItem(
        title="Naive Date Item",
        publication_date=naive_now,
        source_url="https://example.com/naive",
        summary="Summary",
        category=Category.PAYMENTS,
        impact_level=ImpactLevel.MEDIUM,
        why_it_matters="Insight",
    )
    gen = DigestGenerator(days_lookback=7)
    # Pass an aware cutoff — should still work with naive item dates
    cutoff = datetime(2026, 1, 21, 0, 0, 0, tzinfo=timezone.utc)
    result = gen.select_items([item], cutoff_date=cutoff)
    assert len(result) == 1


def test_select_items_handles_aware_datetimes():
    """Items with aware UTC datetimes are handled without exception."""
    aware_now = datetime(2026, 1, 28, 12, 0, 0, tzinfo=timezone.utc)
    item = TrendItem(
        title="Aware Date Item",
        publication_date=aware_now,
        source_url="https://example.com/aware",
        summary="Summary",
        category=Category.PAYMENTS,
        impact_level=ImpactLevel.MEDIUM,
        why_it_matters="Insight",
    )
    gen = DigestGenerator(days_lookback=7)
    cutoff = datetime(2026, 1, 21, 0, 0, 0, tzinfo=timezone.utc)
    result = gen.select_items([item], cutoff_date=cutoff)
    assert len(result) == 1


def test_relevance_boost_loaded_from_config():
    """RELEVANCE_BOOST is loaded from config/feedback.yaml."""
    from src.pipeline.digest import _load_relevance_boost
    # Should load the real config value (0.5 per the YAML)
    boost = _load_relevance_boost()
    assert isinstance(boost, float)
    assert boost > 0


def test_relevance_boost_fallback_on_missing_config():
    """Falls back to default when config file is missing."""
    from src.pipeline.digest import _load_relevance_boost
    from unittest.mock import patch
    import builtins

    original_open = builtins.open

    def _fail_open(path, *a, **kw):
        if "feedback.yaml" in str(path):
            raise FileNotFoundError("mocked")
        return original_open(path, *a, **kw)

    with patch("builtins.open", side_effect=_fail_open):
        boost = _load_relevance_boost(default=0.99)
    assert boost == 0.99
