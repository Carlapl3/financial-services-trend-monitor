"""
Firecrawl API client wrapper for web scraping.

Firecrawl is a web scraping service that converts web pages to clean markdown.
This module provides a simple wrapper around the Firecrawl API.
"""

import os
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class FirecrawlClient:
    """
    Client for interacting with the Firecrawl API.

    Firecrawl provides two main capabilities:
    1. scrape_url: Scrape a single URL and return markdown content
    2. search: Search the web and return multiple results as markdown
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Firecrawl client.

        Args:
            api_key: Firecrawl API key (defaults to FIRECRAWL_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("FIRECRAWL_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Firecrawl API key not found. Set FIRECRAWL_API_KEY environment variable "
                "or pass api_key to constructor."
            )

        # Import firecrawl library (will be installed via requirements.txt)
        try:
            from firecrawl import Firecrawl
            self.app = Firecrawl(api_key=self.api_key)
        except ImportError:
            raise ImportError(
                "firecrawl library not installed. "
                "Install it with: pip install firecrawl"
            )

    def scrape_url(
        self,
        url: str,
        formats: List[str] = None,
        only_main_content: bool = True,
        include_tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
        timeout: int = 30000
    ) -> Dict[str, Any]:
        """
        Scrape a single URL and return markdown content.

        Args:
            url: The URL to scrape
            formats: List of output formats (default: ["markdown"])
            only_main_content: Extract only main content, skip headers/footers/nav
            include_tags: HTML tags to include (e.g., ["article", "main"])
            exclude_tags: HTML tags to exclude (e.g., ["nav", "footer"])
            timeout: Request timeout in milliseconds

        Returns:
            Dictionary with keys:
                - success: bool
                - markdown: str (the extracted content)
                - metadata: dict (title, description, etc.)
                - error: str (if success=False)

        Example:
            >>> client = FirecrawlClient()
            >>> result = client.scrape_url("https://example.com/article")
            >>> if result["success"]:
            ...     print(result["markdown"])
        """
        if formats is None:
            formats = ["markdown"]

        try:
            # Build kwargs for v2 API
            kwargs = {
                "formats": formats,
                "only_main_content": only_main_content,
                "timeout": timeout
            }

            if include_tags:
                kwargs["include_tags"] = include_tags
            if exclude_tags:
                kwargs["exclude_tags"] = exclude_tags

            response = self.app.scrape(url, **kwargs)

            # v2 API returns a Document object, not a dict
            return {
                "success": True,
                "markdown": getattr(response, "markdown", ""),
                "metadata": getattr(response, "metadata", {}),
                "url": url
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "url": url
            }

    def search(
        self,
        query: str,
        limit: int = 10,
        formats: List[str] = None
    ) -> Dict[str, Any]:
        """
        Search the web and return results as markdown.

        Args:
            query: Search query string
            limit: Maximum number of results to return
            formats: List of output formats (default: ["markdown"])

        Returns:
            Dictionary with keys:
                - success: bool
                - results: list of dicts (each with markdown, url, metadata)
                - error: str (if success=False)

        Example:
            >>> client = FirecrawlClient()
            >>> results = client.search("ECB digital euro", limit=5)
            >>> for item in results["results"]:
            ...     print(f"{item['metadata']['title']}: {item['url']}")
        """
        if formats is None:
            formats = ["markdown"]

        try:
            response = self.app.search(
                query,
                limit=limit,
                formats=formats
            )

            # v2 API returns a SearchResponse object
            results = getattr(response, "data", [])
            return {
                "success": True,
                "results": results,
                "query": query
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "results": []
            }


# Convenience functions for quick usage
def scrape_url(url: str, **kwargs) -> Dict[str, Any]:
    """Convenience function to scrape a URL without instantiating client."""
    client = FirecrawlClient()
    return client.scrape_url(url, **kwargs)


def search(query: str, **kwargs) -> Dict[str, Any]:
    """Convenience function to search without instantiating client."""
    client = FirecrawlClient()
    return client.search(query, **kwargs)
