"""
Tests for stable item identity.

Tests cover:
- Deterministic ID generation from URLs
- URL normalization edge cases
- Auto-assign behavior in save()
- ID persistence via model_dump
- Lazy backfill in load_all()
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from src.models import TrendItem, Category, ImpactLevel
from src.pipeline.dedupe import TrendItemStorage


class TestGenerateItemId:
    """Tests for TrendItemStorage.generate_item_id()"""

    def test_returns_16_char_hex(self):
        """ID should be exactly 16 hexadecimal characters."""
        item_id = TrendItemStorage.generate_item_id("https://example.com/article")
        assert len(item_id) == 16
        assert all(c in "0123456789abcdef" for c in item_id)

    def test_deterministic_same_url(self):
        """Same URL should always produce the same ID."""
        url = "https://example.com/news/payment-trends-2024"
        id1 = TrendItemStorage.generate_item_id(url)
        id2 = TrendItemStorage.generate_item_id(url)
        id3 = TrendItemStorage.generate_item_id(url)
        assert id1 == id2 == id3

    def test_different_urls_different_ids(self):
        """Different URLs should produce different IDs."""
        id1 = TrendItemStorage.generate_item_id("https://example.com/article-1")
        id2 = TrendItemStorage.generate_item_id("https://example.com/article-2")
        assert id1 != id2

    def test_normalized_trailing_slash(self):
        """URLs with/without trailing slash should produce same ID."""
        id1 = TrendItemStorage.generate_item_id("https://example.com/article")
        id2 = TrendItemStorage.generate_item_id("https://example.com/article/")
        assert id1 == id2

    def test_normalized_case_insensitive(self):
        """URL normalization should be case-insensitive."""
        id1 = TrendItemStorage.generate_item_id("https://Example.COM/Article")
        id2 = TrendItemStorage.generate_item_id("https://example.com/article")
        assert id1 == id2

    def test_normalized_anchor_removed(self):
        """Anchor fragments should be removed before hashing."""
        id1 = TrendItemStorage.generate_item_id("https://example.com/article#section1")
        id2 = TrendItemStorage.generate_item_id("https://example.com/article")
        assert id1 == id2

    def test_normalized_tracking_params_removed(self):
        """Common tracking parameters should be removed."""
        id1 = TrendItemStorage.generate_item_id("https://example.com/article?utm_source=twitter")
        id2 = TrendItemStorage.generate_item_id("https://example.com/article")
        assert id1 == id2


class TestUrlNormalizationTrackingVsMeaningful:
    """Tests for URL normalization: tracking params removed, meaningful params preserved."""

    def test_tracking_params_removed_meaningful_preserved(self):
        """Tracking params (utm_*) are stripped; meaningful params (id) are kept."""
        url_with_both = "https://example.com/article?id=42&utm_source=twitter&utm_medium=social"
        url_clean = "https://example.com/article?id=42"
        norm1 = TrendItemStorage._normalize_url(url_with_both)
        norm2 = TrendItemStorage._normalize_url(url_clean)
        assert norm1 == norm2
        assert "id=42" in norm1
        assert "utm_" not in norm1

    def test_urls_differ_only_by_tracking_produce_same_normalized(self):
        """Two URLs differing only by tracking params produce the same normalized URL."""
        base = "https://news.example.com/2024/payments-update"
        url_a = f"{base}?utm_source=newsletter&utm_campaign=jan2024&fbclid=abc123"
        url_b = f"{base}?gclid=xyz&ref=homepage"
        norm_a = TrendItemStorage._normalize_url(url_a)
        norm_b = TrendItemStorage._normalize_url(url_b)
        norm_base = TrendItemStorage._normalize_url(base)
        assert norm_a == norm_b == norm_base

    def test_urls_differ_by_meaningful_params_produce_different_normalized(self):
        """Two URLs with different meaningful query params produce different normalized URLs."""
        url_page1 = "https://example.com/search?page=1&q=payments"
        url_page2 = "https://example.com/search?page=2&q=payments"
        norm1 = TrendItemStorage._normalize_url(url_page1)
        norm2 = TrendItemStorage._normalize_url(url_page2)
        assert norm1 != norm2

    def test_multiple_tracking_params_all_stripped(self):
        """All known tracking params are stripped, not just the first."""
        url = "https://example.com/art?utm_source=a&utm_medium=b&utm_campaign=c&gclid=d&fbclid=e&ref=f&ref_src=g"
        normalized = TrendItemStorage._normalize_url(url)
        assert "?" not in normalized  # no query params left

    def test_meaningful_article_param_preserved(self):
        """The 'article' query param is meaningful and preserved."""
        url = "https://example.com/view?article=12345&utm_source=feed"
        normalized = TrendItemStorage._normalize_url(url)
        assert "article=12345" in normalized
        assert "utm_source" not in normalized


class TestItemIdStabilityMatchesDedupe:
    """Tests that generate_item_id() uses the same normalization as dedupe URL checks."""

    def test_id_same_for_url_with_and_without_tracking(self):
        """generate_item_id(url_with_tracking) == generate_item_id(url_without_tracking)."""
        url_with = "https://example.com/news/payments?utm_source=twitter&utm_campaign=weekly&fbclid=abc"
        url_without = "https://example.com/news/payments"
        assert TrendItemStorage.generate_item_id(url_with) == TrendItemStorage.generate_item_id(url_without)

    def test_id_differs_for_meaningful_param_difference(self):
        """generate_item_id(url?id=1) != generate_item_id(url?id=2) when id is meaningful."""
        url_id1 = "https://example.com/article?id=1"
        url_id2 = "https://example.com/article?id=2"
        assert TrendItemStorage.generate_item_id(url_id1) != TrendItemStorage.generate_item_id(url_id2)


class TestSaveAutoAssignsId:
    """Tests for auto-assignment of ID in save()"""

    def create_item(self, url: str = "https://example.com/test", item_id: str = None) -> TrendItem:
        """Helper to create a TrendItem for testing."""
        return TrendItem(
            id=item_id,
            title="Test Article",
            publication_date=datetime(2024, 1, 15),
            source_url=url,
            summary="This is a test summary for the article.",
            category=Category.PAYMENTS,
            impact_level=ImpactLevel.MEDIUM,
            why_it_matters="Test insight for consulting context.",
        )

    def test_save_assigns_id_when_none(self):
        """save() should assign ID to item when item.id is None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "items.jsonl"
            storage = TrendItemStorage(str(storage_path))

            item = self.create_item(url="https://example.com/unique-article")
            assert item.id is None

            storage.save(item)

            # Item should now have an ID assigned
            assert item.id is not None
            assert len(item.id) == 16

    def test_save_preserves_existing_id(self):
        """save() should not overwrite an existing ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "items.jsonl"
            storage = TrendItemStorage(str(storage_path))

            custom_id = "custom12345678ab"
            item = self.create_item(item_id=custom_id)

            storage.save(item)

            assert item.id == custom_id

    def test_id_written_to_jsonl(self):
        """ID must be persisted in JSONL file, not only set in memory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "items.jsonl"
            storage = TrendItemStorage(str(storage_path))

            item = self.create_item(url="https://example.com/persisted")
            storage.save(item)

            # Read raw JSONL and verify id is present
            with open(storage_path, 'r') as f:
                line = f.readline()
                saved_dict = json.loads(line)

            assert "id" in saved_dict
            assert saved_dict["id"] is not None
            assert len(saved_dict["id"]) == 16

    def test_model_dump_includes_id(self):
        """model_dump() must include the id field after save."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "items.jsonl"
            storage = TrendItemStorage(str(storage_path))

            item = self.create_item()
            storage.save(item)

            dumped = item.model_dump(mode='json')
            assert "id" in dumped
            assert dumped["id"] is not None
            assert dumped["id"] == item.id


class TestLoadAllBackfillsId:
    """Tests for lazy ID backfill in load_all()"""

    def test_load_backfills_missing_id(self):
        """load_all() should assign ID to legacy items without id field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "items.jsonl"

            # Write a legacy item without id field
            legacy_item = {
                "title": "Legacy Article",
                "publication_date": "2024-01-10T00:00:00",
                "source_url": "https://legacy.example.com/old-article",
                "summary": "Legacy summary text.",
                "category": "Payments",
                "impact_level": "High",
                "why_it_matters": "Legacy insight.",
                "created_at": "2024-01-10T12:00:00",
            }
            with open(storage_path, 'w') as f:
                f.write(json.dumps(legacy_item) + '\n')

            # Load and verify ID is backfilled
            storage = TrendItemStorage(str(storage_path))
            items = storage.load_all()

            assert len(items) == 1
            assert items[0].id is not None
            assert len(items[0].id) == 16

    def test_backfilled_id_matches_generated(self):
        """Backfilled ID should match what generate_item_id would produce."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "items.jsonl"
            test_url = "https://legacy.example.com/consistent-id"

            legacy_item = {
                "title": "Legacy Article",
                "publication_date": "2024-01-10T00:00:00",
                "source_url": test_url,
                "summary": "Legacy summary.",
                "category": "Regulatory",
                "impact_level": "Medium",
                "why_it_matters": "Legacy insight.",
                "created_at": "2024-01-10T12:00:00",
            }
            with open(storage_path, 'w') as f:
                f.write(json.dumps(legacy_item) + '\n')

            storage = TrendItemStorage(str(storage_path))
            items = storage.load_all()

            expected_id = TrendItemStorage.generate_item_id(test_url)
            assert items[0].id == expected_id

    def test_load_does_not_rewrite_file(self):
        """load_all() should not modify the JSONL file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "items.jsonl"

            legacy_item = {
                "title": "Legacy Article",
                "publication_date": "2024-01-10T00:00:00",
                "source_url": "https://legacy.example.com/no-rewrite",
                "summary": "Legacy summary.",
                "category": "Payments",
                "impact_level": "Low",
                "why_it_matters": "Legacy insight.",
                "created_at": "2024-01-10T12:00:00",
            }
            with open(storage_path, 'w') as f:
                f.write(json.dumps(legacy_item) + '\n')

            # Record file state before load
            with open(storage_path, 'r') as f:
                content_before = f.read()

            storage = TrendItemStorage(str(storage_path))
            storage.load_all()

            # File should be unchanged
            with open(storage_path, 'r') as f:
                content_after = f.read()

            assert content_before == content_after

    def test_load_preserves_existing_id(self):
        """load_all() should not overwrite items that already have an id."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "items.jsonl"
            existing_id = "existingid123456"

            item_with_id = {
                "id": existing_id,
                "title": "Article With ID",
                "publication_date": "2024-01-15T00:00:00",
                "source_url": "https://example.com/has-id",
                "summary": "Summary text.",
                "category": "Payments",
                "impact_level": "High",
                "why_it_matters": "Insight.",
                "created_at": "2024-01-15T12:00:00",
            }
            with open(storage_path, 'w') as f:
                f.write(json.dumps(item_with_id) + '\n')

            storage = TrendItemStorage(str(storage_path))
            items = storage.load_all()

            assert items[0].id == existing_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
