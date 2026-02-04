"""
Content collection pipeline - fetch raw items from configured sources.

This module reads source configuration and uses Firecrawl to scrape content,
emitting "raw items" with URL, title/date (if available), and markdown content.
"""

import yaml
import feedparser
import requests
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from io import BytesIO

from src.scrape.firecrawl_client import FirecrawlClient


class SourceCollector:
    """
    Collects raw content from configured sources.

    Reads sources.yaml and scrapes each source URL to produce raw items
    containing markdown content and basic metadata.
    """

    def __init__(self, sources_config_path: Optional[str] = None):
        """
        Initialize collector with source configuration.

        Args:
            sources_config_path: Path to sources.yaml (defaults to src/config/sources.yaml)
        """
        if sources_config_path is None:
            config_dir = Path(__file__).parent.parent / "config"
            sources_config_path = str(config_dir / "sources.yaml")

        self.sources_config_path = sources_config_path
        self.sources = self._load_sources()
        self.firecrawl = FirecrawlClient()

    def _load_sources(self) -> List[Dict[str, Any]]:
        """
        Load source configuration from YAML file.

        Returns:
            List of source configuration dictionaries
        """
        try:
            with open(self.sources_config_path, 'r') as f:
                config = yaml.safe_load(f)
                return config.get('sources', [])
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Sources configuration not found at: {self.sources_config_path}"
            )
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in sources configuration: {e}")

    def collect_from_rss(
        self,
        source: Dict[str, Any],
        max_entries: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Collect content from an RSS feed source.

        Args:
            source: Source configuration dictionary
            max_entries: Maximum number of feed entries to process

        Returns:
            List of raw item dictionaries (one per feed entry)
        """
        url = source.get('url')
        source_name = source.get('name', 'Unknown')

        print(f"Collecting from RSS feed: {source_name} ({url})")

        try:
            # Fetch RSS feed with requests (better SSL handling)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            # Parse RSS feed from response content
            feed = feedparser.parse(BytesIO(response.content))

            if not feed.entries:
                print(f"  ✗ No entries found in RSS feed")
                return [{
                    "source_name": source_name,
                    "source_url": url,
                    "category": source.get('category'),
                    "priority": source.get('priority'),
                    "success": False,
                    "error": "No entries found in RSS feed",
                    "collected_at": datetime.now(timezone.utc)
                }]

            print(f"  Found {len(feed.entries)} entries, processing top {min(len(feed.entries), max_entries)}...")

            raw_items = []
            entries_to_process = feed.entries[:max_entries]

            for i, entry in enumerate(entries_to_process, 1):
                entry_url = entry.get('link', entry.get('id', ''))
                if not entry_url:
                    print(f"  [{i}/{len(entries_to_process)}] ✗ No URL found for entry")
                    continue

                entry_title = entry.get('title', 'Untitled')
                print(f"  [{i}/{len(entries_to_process)}] Scraping: {entry_title[:50]}...")

                # Scrape the individual article
                result = self.firecrawl.scrape_url(entry_url)

                if not result.get('success'):
                    error_msg = result.get('error', 'Unknown error')
                    print(f"      ✗ Failed: {error_msg}")
                    raw_items.append({
                        "source_name": source_name,
                        "source_url": entry_url,  # Use article URL, not feed URL
                        "category": source.get('category'),
                        "priority": source.get('priority'),
                        "success": False,
                        "error": error_msg,
                        "collected_at": datetime.now(timezone.utc)
                    })
                    continue

                metadata = result.get('metadata', {})
                markdown = result.get('markdown', '')

                # Extract title and date from RSS entry
                title = entry.get('title', entry_title)

                # Parse publication date from RSS entry
                publication_date = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        from time import struct_time
                        publication_date = datetime(*entry.published_parsed[:6])
                    except Exception:
                        pass
                elif hasattr(entry, 'published'):
                    try:
                        publication_date = parsedate_to_datetime(entry.published)
                    except Exception:
                        pass

                raw_item = {
                    "source_name": source_name,
                    "source_url": entry_url,  # CRITICAL: Use article URL, not feed URL
                    "category": source.get('category'),
                    "priority": source.get('priority'),
                    "title": title,
                    "publication_date": publication_date,
                    "raw_markdown": markdown,
                    "collected_at": datetime.now(timezone.utc),
                    "success": True,
                    "metadata": metadata,
                    "rss_entry": {
                        "summary": entry.get('summary', ''),
                        "author": entry.get('author', ''),
                    }
                }

                print(f"      ✓ Collected: {len(markdown)} chars")
                raw_items.append(raw_item)

            successful = len([i for i in raw_items if i.get('success')])
            print(f"  ✓ RSS collection complete: {successful}/{len(raw_items)} successful")

            return raw_items

        except Exception as e:
            print(f"  ✗ RSS feed error: {e}")
            return [{
                "source_name": source_name,
                "source_url": url,
                "category": source.get('category'),
                "priority": source.get('priority'),
                "success": False,
                "error": f"RSS feed error: {str(e)}",
                "collected_at": datetime.now(timezone.utc)
            }]

    def collect_from_source(self, source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Collect content from a single source.

        Args:
            source: Source configuration dictionary

        Returns:
            Raw item dictionary with keys:
                - source_name: Name of the source
                - source_url: URL scraped
                - category: Source category (Payments/Regulatory)
                - priority: Source priority (must-have/nice-to-have)
                - title: Page title (from metadata)
                - publication_date: Publication date if available (None otherwise)
                - raw_markdown: Scraped markdown content
                - collected_at: Timestamp when collected
                - success: Boolean indicating success
                - error: Error message if success=False

        Returns None if scraping fails.
        """
        url = source.get('url')
        source_name = source.get('name', 'Unknown')

        print(f"Collecting from: {source_name} ({url})")

        result = self.firecrawl.scrape_url(url)

        if not result.get('success'):
            error_msg = result.get('error', 'Unknown error')
            print(f"  ✗ Failed: {error_msg}")
            return {
                "source_name": source_name,
                "source_url": url,
                "category": source.get('category'),
                "priority": source.get('priority'),
                "success": False,
                "error": error_msg,
                "collected_at": datetime.now(timezone.utc)
            }

        metadata = result.get('metadata', {})
        markdown = result.get('markdown', '')

        # Extract title from metadata (handle both dict and Pydantic object)
        is_dict = isinstance(metadata, dict)

        if is_dict:
            # Dictionary
            title = metadata.get('title', metadata.get('ogTitle', source_name))
            published_time = metadata.get('publishedTime')
        else:
            # Pydantic object
            title = getattr(metadata, 'title', None) or getattr(metadata, 'ogTitle', None) or source_name
            published_time = getattr(metadata, 'publishedTime', None)

        # Try to extract publication date from metadata (may not always be available)
        publication_date = None
        if published_time:
            try:
                publication_date = datetime.fromisoformat(published_time)
            except (ValueError, TypeError):
                pass

        raw_item = {
            "source_name": source_name,
            "source_url": url,
            "category": source.get('category'),
            "priority": source.get('priority'),
            "title": title,
            "publication_date": publication_date,
            "raw_markdown": markdown,
            "collected_at": datetime.now(timezone.utc),
            "success": True,
            "metadata": metadata  # Keep full metadata for potential later use
        }

        print(f"  ✓ Collected: {len(markdown)} chars")
        return raw_item

    def collect_all(
        self,
        priority_filter: Optional[str] = None,
        category_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Collect content from all configured sources.

        Args:
            priority_filter: Only collect from sources with this priority
                           (e.g., "must-have", "nice-to-have")
            category_filter: Only collect from sources in this category
                           (e.g., "Payments", "Regulatory")

        Returns:
            List of raw item dictionaries (includes both successful and failed items)

        Example:
            >>> collector = SourceCollector()
            >>> # Collect only must-have sources
            >>> items = collector.collect_all(priority_filter="must-have")
            >>> successful = [i for i in items if i['success']]
            >>> print(f"Collected {len(successful)} items")
        """
        filtered_sources = self.sources

        # Apply filters
        if priority_filter:
            filtered_sources = [
                s for s in filtered_sources
                if s.get('priority') == priority_filter
            ]

        if category_filter:
            filtered_sources = [
                s for s in filtered_sources
                if s.get('category') == category_filter
            ]

        print(f"\n=== Collecting from {len(filtered_sources)} sources ===\n")

        raw_items = []
        for source in filtered_sources:
            source_type = source.get('type', 'html')

            if source_type == 'rss':
                # RSS sources return multiple items (one per feed entry)
                rss_items = self.collect_from_rss(source)
                raw_items.extend(rss_items)
            else:
                # HTML sources return one item
                raw_item = self.collect_from_source(source)
                if raw_item:
                    raw_items.append(raw_item)

        successful = [i for i in raw_items if i.get('success')]
        failed = [i for i in raw_items if not i.get('success')]

        print(f"\n=== Collection complete ===")
        print(f"Total sources: {len(filtered_sources)}")
        print(f"Total items collected: {len(raw_items)}")
        print(f"Successful: {len(successful)}")
        print(f"Failed: {len(failed)}")

        return raw_items

    def collect_must_have_only(self) -> List[Dict[str, Any]]:
        """Convenience method to collect only must-have sources."""
        return self.collect_all(priority_filter="must-have")


# CLI functionality for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Collect content from configured sources")
    parser.add_argument(
        "--priority",
        choices=["must-have", "nice-to-have"],
        help="Filter by source priority"
    )
    parser.add_argument(
        "--category",
        choices=["Payments", "Regulatory"],
        help="Filter by source category"
    )

    args = parser.parse_args()

    collector = SourceCollector()
    items = collector.collect_all(
        priority_filter=args.priority,
        category_filter=args.category
    )

    print(f"\n=== Sample collected item ===")
    if items and items[0].get('success'):
        sample = items[0]
        print(f"Source: {sample['source_name']}")
        print(f"Title: {sample['title']}")
        print(f"Category: {sample['category']}")
        print(f"Markdown length: {len(sample.get('raw_markdown', ''))} chars")
        print(f"First 200 chars:\n{sample.get('raw_markdown', '')[:200]}...")
