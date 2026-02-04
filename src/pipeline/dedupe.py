"""
Storage and deduplication pipeline - JSONL-based storage with duplicate detection.

Simple storage using JSON Lines format with primary URL-based
and secondary title+date hash-based duplicate detection.
"""

import json
import hashlib
from pathlib import Path
from typing import List, Optional, Set, Tuple
from datetime import datetime
from urllib.parse import urlparse, urlencode, parse_qs

from src.models import TrendItem


class TrendItemStorage:
    """
    JSONL-based storage for TrendItems with built-in deduplication.

    Uses JSON Lines format for simple, append-friendly storage.
    Implements two-tier deduplication:
    1. Primary: source_url uniqueness
    2. Secondary: normalized title+date hash
    """

    def __init__(self, storage_path: Optional[str] = None):
        """
        Initialize storage.

        Args:
            storage_path: Path to JSONL file (defaults to data/trend_items.jsonl)
        """
        if storage_path is None:
            data_dir = Path(__file__).parent.parent.parent / "data"
            storage_path = str(data_dir / "trend_items.jsonl")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # In-memory cache of URLs and hashes for fast duplicate detection
        self._url_cache: Set[str] = set()
        self._hash_cache: Set[str] = set()
        self._load_caches()

    def _load_caches(self):
        """Load URL and hash caches from existing storage file."""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, 'r') as f:
                for line in f:
                    if line.strip():
                        item_dict = json.loads(line)
                        url = item_dict.get('source_url')
                        if url:
                            self._url_cache.add(self._normalize_url(url))

                        # Recreate hash from stored data
                        title = item_dict.get('title', '')
                        pub_date = item_dict.get('publication_date')
                        if title and pub_date:
                            hash_val = self._compute_title_date_hash(title, pub_date)
                            self._hash_cache.add(hash_val)

        except Exception as e:
            print(f"Warning: Failed to load caches: {e}")

    # Query parameter names that are tracking-only and safe to strip
    _TRACKING_PARAMS = frozenset({
        'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
        'gclid', 'fbclid', 'ref', 'ref_src', 'ref_url',
        'mc_cid', 'mc_eid',  # Mailchimp
        'yclid',  # Yandex
        'msclkid',  # Microsoft Ads
        '_ga', '_gl',  # Google Analytics
    })

    @staticmethod
    def _normalize_url(url: str) -> str:
        """
        Normalize URL for comparison.

        - Lowercases and strips whitespace
        - Drops fragment (#...)
        - Normalizes trailing slash on path
        - Drops tracking query params (utm_*, gclid, fbclid, ref, etc.)
        - Preserves meaningful query params (id, page, article, etc.)

        Args:
            url: URL string

        Returns:
            Normalized URL
        """
        url = str(url).strip()
        parsed = urlparse(url)

        # Lowercase scheme and host; preserve path casing then lowercase
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.lower()

        # Normalize trailing slash on path
        if path != '/' and path.endswith('/'):
            path = path[:-1]

        # Filter query params: drop tracking, keep meaningful
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        filtered = {}
        for key, values in query_params.items():
            key_lower = key.lower()
            if key_lower not in TrendItemStorage._TRACKING_PARAMS:
                filtered[key_lower] = values

        # Rebuild query string with sorted keys for determinism
        query_string = urlencode(
            sorted(filtered.items()),
            doseq=True,
        )

        # Rebuild URL without fragment
        normalized = f"{scheme}://{netloc}{path}"
        if query_string:
            normalized += f"?{query_string}"

        return normalized

    @staticmethod
    def generate_item_id(source_url: str) -> str:
        """
        Generate a stable, deterministic item ID from source URL.

        Uses SHA256 hash of normalized URL, truncated to 16 characters.
        Same URL always produces the same ID.

        Args:
            source_url: The source URL of the item

        Returns:
            16-character hex string ID
        """
        normalized = TrendItemStorage._normalize_url(source_url)
        hash_obj = hashlib.sha256(normalized.encode('utf-8'))
        return hash_obj.hexdigest()[:16]

    @staticmethod
    def _compute_title_date_hash(title: str, publication_date: str) -> str:
        """
        Compute hash from normalized title and date.

        Args:
            title: Article title
            publication_date: ISO format date string

        Returns:
            SHA256 hash (first 16 chars)
        """
        # Normalize title: lowercase, remove extra whitespace
        normalized_title = ' '.join(title.lower().strip().split())

        # Extract just the date part (ignore time)
        try:
            if isinstance(publication_date, str):
                date_part = publication_date.split('T')[0]
            else:
                date_part = str(publication_date).split('T')[0]
        except Exception:
            date_part = str(publication_date)

        # Combine and hash
        combined = f"{normalized_title}|{date_part}"
        hash_obj = hashlib.sha256(combined.encode('utf-8'))
        return hash_obj.hexdigest()[:16]

    def is_duplicate(self, item: TrendItem) -> Tuple[bool, Optional[str]]:
        """
        Check if item is a duplicate.

        Uses two-tier detection:
        1. Primary: Check if source_url already exists
        2. Secondary: Check if title+date hash already exists

        Args:
            item: TrendItem to check

        Returns:
            Tuple of (is_duplicate: bool, reason: str or None)
        """
        # Primary check: URL
        normalized_url = self._normalize_url(str(item.source_url))
        if normalized_url in self._url_cache:
            return (True, f"Duplicate URL: {item.source_url}")

        # Secondary check: Title+Date hash
        if item.title and item.publication_date:
            pub_date_str = item.publication_date.isoformat()
            hash_val = self._compute_title_date_hash(item.title, pub_date_str)
            if hash_val in self._hash_cache:
                return (True, f"Duplicate content (same title+date): {item.title}")

        return (False, None)

    def save(self, item: TrendItem, skip_duplicates: bool = True) -> bool:
        """
        Save TrendItem to storage.

        Auto-assigns a stable ID based on source_url if item.id is None.

        Args:
            item: TrendItem to save
            skip_duplicates: If True, skip saving duplicates (default)

        Returns:
            True if saved, False if skipped (duplicate)
        """
        # Check for duplicates
        if skip_duplicates:
            is_dup, reason = self.is_duplicate(item)
            if is_dup:
                print(f"  ⊘ Skipping duplicate: {reason}")
                return False

        # Auto-assign ID if not set (ensures ID is written to JSONL)
        if item.id is None:
            item.id = self.generate_item_id(str(item.source_url))

        # Convert to dict and save
        item_dict = item.model_dump(mode='json')

        with open(self.storage_path, 'a') as f:
            f.write(json.dumps(item_dict) + '\n')

        # Update caches
        normalized_url = self._normalize_url(str(item.source_url))
        self._url_cache.add(normalized_url)

        if item.title and item.publication_date:
            pub_date_str = item.publication_date.isoformat()
            hash_val = self._compute_title_date_hash(item.title, pub_date_str)
            self._hash_cache.add(hash_val)

        return True

    def save_batch(
        self,
        items: List[TrendItem],
        skip_duplicates: bool = True
    ) -> Tuple[int, int]:
        """
        Save multiple TrendItems to storage.

        Args:
            items: List of TrendItems to save
            skip_duplicates: If True, skip saving duplicates

        Returns:
            Tuple of (saved_count, skipped_count)
        """
        saved = 0
        skipped = 0

        for item in items:
            if self.save(item, skip_duplicates=skip_duplicates):
                saved += 1
            else:
                skipped += 1

        return (saved, skipped)

    def load_all(self) -> List[TrendItem]:
        """
        Load all TrendItems from storage.

        Lazily backfills ID for legacy items that don't have one.
        The ID is computed in memory; the file is not rewritten.

        Returns:
            List of TrendItems
        """
        if not self.storage_path.exists():
            return []

        items = []
        with open(self.storage_path, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        item_dict = json.loads(line)
                        item = TrendItem(**item_dict)
                        # Lazy backfill: assign ID if missing (legacy items)
                        if item.id is None:
                            item.id = self.generate_item_id(str(item.source_url))
                        items.append(item)
                    except Exception as e:
                        print(f"Warning: Failed to parse line: {e}")
                        continue

        return items

    def get_stats(self) -> dict:
        """
        Get storage statistics.

        Returns:
            Dictionary with stats
        """
        items = self.load_all()

        return {
            "total_items": len(items),
            "unique_urls": len(self._url_cache),
            "storage_path": str(self.storage_path),
            "file_exists": self.storage_path.exists(),
            "file_size_bytes": self.storage_path.stat().st_size if self.storage_path.exists() else 0
        }


# Convenience functions
def save_item(item: TrendItem, skip_duplicates: bool = True) -> bool:
    """Convenience function to save a single item."""
    storage = TrendItemStorage()
    return storage.save(item, skip_duplicates=skip_duplicates)


def save_items(items: List[TrendItem], skip_duplicates: bool = True) -> Tuple[int, int]:
    """Convenience function to save multiple items."""
    storage = TrendItemStorage()
    return storage.save_batch(items, skip_duplicates=skip_duplicates)


def load_all_items() -> List[TrendItem]:
    """Convenience function to load all items."""
    storage = TrendItemStorage()
    return storage.load_all()


# CLI functionality for testing
if __name__ == "__main__":
    print("\n=== TrendItemStorage Test ===\n")

    storage = TrendItemStorage()
    stats = storage.get_stats()

    print("Storage Statistics:")
    print(f"  Path: {stats['storage_path']}")
    print(f"  Exists: {stats['file_exists']}")
    print(f"  Total items: {stats['total_items']}")
    print(f"  Unique URLs: {stats['unique_urls']}")
    print(f"  File size: {stats['file_size_bytes']} bytes")

    if stats['total_items'] > 0:
        print(f"\n=== Sample Items ===")
        items = storage.load_all()
        for i, item in enumerate(items[:3], 1):
            print(f"\n{i}. {item.title}")
            print(f"   Category: {item.category.value} | Impact: {item.impact_level.value}")
            print(f"   URL: {item.source_url}")
