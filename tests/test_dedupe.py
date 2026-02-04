"""
Unit tests for deduplication and storage pipeline.

Tests TrendItemStorage with various duplicate scenarios:
- Same URL
- Slightly different URLs
- Same title+date (different URLs)
"""

import tempfile
from pathlib import Path
from datetime import datetime

from src.pipeline.dedupe import TrendItemStorage
from src.models import TrendItem, Category, ImpactLevel


def create_sample_item(
    title: str = "Test Article",
    url: str = "https://example.com/article",
    pub_date: datetime = None
) -> TrendItem:
    """Create a sample TrendItem for testing."""
    if pub_date is None:
        pub_date = datetime(2024, 1, 15, 10, 30)

    return TrendItem(
        title=title,
        publication_date=pub_date,
        source_url=url,
        summary="This is a test summary for the article.",
        category=Category.PAYMENTS,
        impact_level=ImpactLevel.MEDIUM,
        why_it_matters="This is important for testing purposes."
    )


def test_exact_url_duplicate():
    """Test that exact same URL is detected as duplicate."""
    print("\n" + "="*60)
    print("TEST 1: Exact URL Duplicate")
    print("="*60)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        storage_path = f.name

    try:
        storage = TrendItemStorage(storage_path)

        # Save first item
        item1 = create_sample_item(
            title="First Article",
            url="https://example.com/article-123"
        )
        result1 = storage.save(item1)
        assert result1 == True, "First item should be saved"
        print(f"✓ Saved first item: {item1.source_url}")

        # Try to save exact duplicate URL
        item2 = create_sample_item(
            title="Different Title",  # Different title
            url="https://example.com/article-123"  # Same URL
        )
        result2 = storage.save(item2)
        assert result2 == False, "Exact URL duplicate should be rejected"
        print(f"✓ Rejected duplicate URL: {item2.source_url}")

        # Verify only one item in storage
        all_items = storage.load_all()
        assert len(all_items) == 1, "Should only have one item"
        print(f"✓ Storage contains 1 item (duplicate correctly rejected)")

    finally:
        Path(storage_path).unlink(missing_ok=True)

    print("\n✓ Test passed: Exact URL duplicates detected")


def test_normalized_url_variations():
    """Test that URL variations are normalized and detected as duplicates."""
    print("\n" + "="*60)
    print("TEST 2: Normalized URL Variations")
    print("="*60)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        storage_path = f.name

    try:
        storage = TrendItemStorage(storage_path)

        # Save base URL
        item1 = create_sample_item(url="https://example.com/article")
        storage.save(item1)
        print(f"✓ Saved: {item1.source_url}")

        # Test variations that should be considered duplicates
        variations = [
            "https://example.com/article/",  # Trailing slash
            "https://example.com/article#section",  # With anchor
            "https://Example.com/Article",  # Different case
            "https://example.com/article?utm_source=twitter",  # Tracking param
        ]

        for url in variations:
            item = create_sample_item(url=url, title=f"Article from {url}")
            result = storage.save(item)
            if result:
                print(f"  ✗ FAILED: Should reject {url}")
                assert False, f"URL variation should be duplicate: {url}"
            else:
                print(f"  ✓ Correctly rejected variation: {url}")

        # Verify only one item in storage
        all_items = storage.load_all()
        assert len(all_items) == 1, f"Should only have 1 item, got {len(all_items)}"

    finally:
        Path(storage_path).unlink(missing_ok=True)

    print("\n✓ Test passed: URL normalization working")


def test_title_date_hash_duplicate():
    """Test that same title+date combination is detected as duplicate."""
    print("\n" + "="*60)
    print("TEST 3: Title+Date Hash Duplicate")
    print("="*60)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        storage_path = f.name

    try:
        storage = TrendItemStorage(storage_path)

        pub_date = datetime(2024, 1, 15, 10, 30)

        # Save first item
        item1 = create_sample_item(
            title="ECB Announces Digital Euro Pilot",
            url="https://ecb.europa.eu/press/pr/2024/html/pr240115.en.html",
            pub_date=pub_date
        )
        storage.save(item1)
        print(f"✓ Saved: '{item1.title}' from {item1.source_url}")

        # Different URL but same title and date
        item2 = create_sample_item(
            title="ECB Announces Digital Euro Pilot",  # Exact same title
            url="https://reuters.com/article/ecb-digital-euro",  # Different URL
            pub_date=pub_date  # Same date
        )
        result = storage.save(item2)
        assert result == False, "Same title+date should be duplicate"
        print(f"✓ Rejected duplicate (same title+date): {item2.source_url}")

        # Different title, same URL should also be rejected (URL check)
        item3 = create_sample_item(
            title="Different Title Here",
            url="https://ecb.europa.eu/press/pr/2024/html/pr240115.en.html",
            pub_date=pub_date
        )
        result3 = storage.save(item3)
        assert result3 == False, "Same URL should be duplicate"
        print(f"✓ Rejected duplicate (same URL): {item3.source_url}")

        # Verify only one item in storage
        all_items = storage.load_all()
        assert len(all_items) == 1, "Should only have one item"

    finally:
        Path(storage_path).unlink(missing_ok=True)

    print("\n✓ Test passed: Title+date hash duplicates detected")


def test_non_duplicates_allowed():
    """Test that genuinely different items are not flagged as duplicates."""
    print("\n" + "="*60)
    print("TEST 4: Non-Duplicates Correctly Saved")
    print("="*60)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        storage_path = f.name

    try:
        storage = TrendItemStorage(storage_path)

        # Three genuinely different items
        items = [
            create_sample_item(
                title="ECB Digital Euro Launch",
                url="https://ecb.europa.eu/digital-euro",
                pub_date=datetime(2024, 1, 15)
            ),
            create_sample_item(
                title="EBA Capital Guidelines Updated",
                url="https://eba.europa.eu/guidelines-2024",
                pub_date=datetime(2024, 1, 16)
            ),
            create_sample_item(
                title="ECB Digital Euro Launch",  # Same title as #1
                url="https://reuters.com/ecb-euro",  # Different URL
                pub_date=datetime(2024, 1, 16)  # Different date!
            ),
        ]

        saved_count = 0
        for i, item in enumerate(items, 1):
            result = storage.save(item)
            if result:
                saved_count += 1
                print(f"✓ Item {i} saved: {item.title[:40]}...")
            else:
                print(f"✗ Item {i} rejected (unexpected!)")

        assert saved_count == 3, f"All 3 items should be saved, got {saved_count}"

        # Verify all items in storage
        all_items = storage.load_all()
        assert len(all_items) == 3, f"Should have 3 items, got {len(all_items)}"

    finally:
        Path(storage_path).unlink(missing_ok=True)

    print("\n✓ Test passed: Non-duplicates correctly saved")


def test_batch_save_with_duplicates():
    """Test batch save functionality with mixed duplicates and new items."""
    print("\n" + "="*60)
    print("TEST 5: Batch Save with Mixed Duplicates")
    print("="*60)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        storage_path = f.name

    try:
        storage = TrendItemStorage(storage_path)

        # First batch: 2 unique items
        batch1 = [
            create_sample_item(title="Article 1", url="https://example.com/1"),
            create_sample_item(title="Article 2", url="https://example.com/2"),
        ]
        saved, skipped = storage.save_batch(batch1)
        assert saved == 2 and skipped == 0, f"Expected 2 saved, 0 skipped. Got {saved}/{skipped}"
        print(f"✓ Batch 1: Saved {saved}, Skipped {skipped}")

        # Second batch: 1 duplicate, 2 new
        batch2 = [
            create_sample_item(title="Article 1", url="https://example.com/1"),  # Duplicate URL
            create_sample_item(title="Article 3", url="https://example.com/3"),  # New
            create_sample_item(title="Article 4", url="https://example.com/4"),  # New
        ]
        saved, skipped = storage.save_batch(batch2)
        assert saved == 2 and skipped == 1, f"Expected 2 saved, 1 skipped. Got {saved}/{skipped}"
        print(f"✓ Batch 2: Saved {saved}, Skipped {skipped}")

        # Verify total count
        all_items = storage.load_all()
        assert len(all_items) == 4, f"Should have 4 unique items, got {len(all_items)}"

    finally:
        Path(storage_path).unlink(missing_ok=True)

    print("\n✓ Test passed: Batch save with deduplication working")
