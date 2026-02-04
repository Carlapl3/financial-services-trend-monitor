"""
Agent Tools - Wraps pipeline modules for agent use.

Each tool function:
- Validates inputs
- Calls underlying pipeline modules
- Returns structured output suitable for agent observation
"""

import os
import yaml
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime, timezone

from src.pipeline.collect import SourceCollector
from src.pipeline.extract import TrendExtractor
from src.pipeline.dedupe import TrendItemStorage
from src.pipeline.digest import DigestGenerator
from src.models import TrendItem


# --- Config Loading Functions ---

def load_allowed_sources(config_path: Optional[str] = None) -> List[str]:
    """
    Load whitelist of allowed source URLs.

    Args:
        config_path: Path to allowed_sources.yaml

    Returns:
        List of allowed source URLs
    """
    if config_path is None:
        config_dir = Path(__file__).parent.parent.parent / "config"
        config_path = config_dir / "allowed_sources.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        return []

    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            return config.get('allowed_sources', [])
    except Exception:
        return []


def load_agent_limits(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load agent execution limits.

    Args:
        config_path: Path to agent_limits.yaml

    Returns:
        Dictionary with limit settings
    """
    defaults = {
        "max_steps": 6,
        "timeout": 90
    }

    if config_path is None:
        config_dir = Path(__file__).parent.parent.parent / "config"
        config_path = config_dir / "agent_limits.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        return defaults

    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            return {**defaults, **config}
    except Exception:
        return defaults


# --- Whitelist Cache ---

_allowed_sources_cache: Optional[List[str]] = None


def _get_allowed_sources() -> List[str]:
    """Get cached allowed sources list."""
    global _allowed_sources_cache
    if _allowed_sources_cache is None:
        _allowed_sources_cache = load_allowed_sources()
    return _allowed_sources_cache


def _is_url_allowed(url: str) -> bool:
    """
    Check if URL is in the whitelist.

    Args:
        url: URL to check

    Returns:
        True if allowed, False otherwise
    """
    allowed = _get_allowed_sources()
    if not allowed:
        # If no whitelist configured, allow all
        return True

    url_lower = url.lower()
    for allowed_url in allowed:
        if allowed_url.lower() in url_lower:
            return True
    return False


# --- Tool Functions ---

def tool_scrape_source(url: str, source_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Scrape content from a source URL.

    Enforces whitelist - only allowed sources can be scraped.

    Args:
        url: Source URL to scrape
        source_name: Optional name for the source

    Returns:
        Dictionary with:
            - success: bool
            - content: markdown content if successful
            - title: page title if available
            - error: error message if failed
    """
    # Enforce whitelist
    if not _is_url_allowed(url):
        return {
            "success": False,
            "error": f"URL not in allowed sources whitelist: {url}",
            "url": url
        }

    try:
        collector = SourceCollector()

        # Create source config for single URL
        source_config = {
            "name": source_name or "Agent Request",
            "url": url,
            "type": "html",
            "category": "Payments",  # Default, will be determined by extraction
            "priority": "must-have"
        }

        result = collector.collect_from_source(source_config)

        if result and result.get('success'):
            return {
                "success": True,
                "url": url,
                "title": result.get('title', 'Unknown'),
                "content": result.get('raw_markdown', ''),
                "content_length": len(result.get('raw_markdown', '')),
                "collected_at": datetime.now(timezone.utc).isoformat()
            }
        else:
            return {
                "success": False,
                "url": url,
                "error": result.get('error', 'Unknown error') if result else 'Collection returned None'
            }

    except Exception as e:
        return {
            "success": False,
            "url": url,
            "error": str(e)
        }


def tool_analyze_impact(
    content: str,
    source_url: str,
    source_name: Optional[str] = None,
    category_hint: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyze content and extract structured trend item.

    Uses LLM to extract title, summary, category, impact level, and insights.

    Args:
        content: Markdown content to analyze
        source_url: Source URL
        source_name: Optional source name
        category_hint: Optional category hint (Payments/Regulatory)

    Returns:
        Dictionary with:
            - success: bool
            - item: extracted TrendItem as dict if successful
            - error: error message if failed
    """
    try:
        extractor = TrendExtractor()

        item = extractor.extract(
            markdown=content,
            source_name=source_name or "Unknown",
            source_url=source_url,
            source_category=category_hint
        )

        return {
            "success": True,
            "item": {
                "title": item.title,
                "summary": item.summary,
                "category": item.category.value,
                "impact_level": item.impact_level.value,
                "why_it_matters": item.why_it_matters,
                "publication_date": item.publication_date.isoformat() if item.publication_date else None,
                "source_url": str(item.source_url)
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def tool_check_duplicates(
    url: Optional[str] = None,
    title: Optional[str] = None,
    item: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Check if an item is a duplicate in storage.

    Can check by URL, title, or full item.

    Args:
        url: Source URL to check
        title: Title to check
        item: Full item dict to check

    Returns:
        Dictionary with:
            - is_duplicate: bool
            - reason: explanation if duplicate
            - storage_stats: current storage statistics
    """
    try:
        storage = TrendItemStorage()

        # If full item provided, check it
        if item:
            trend_item = TrendItem(**item)
            is_dup, reason = storage.is_duplicate(trend_item)
            return {
                "is_duplicate": is_dup,
                "reason": reason,
                "storage_stats": storage.get_stats()
            }

        # Check URL directly against cache
        if url:
            normalized_url = storage._normalize_url(url)
            is_dup = normalized_url in storage._url_cache
            return {
                "is_duplicate": is_dup,
                "reason": f"URL already exists: {url}" if is_dup else None,
                "storage_stats": storage.get_stats()
            }

        # Just return stats if no specific check requested
        return {
            "is_duplicate": False,
            "reason": None,
            "storage_stats": storage.get_stats()
        }

    except Exception as e:
        return {
            "is_duplicate": False,
            "reason": None,
            "error": str(e)
        }


def tool_render_digest(
    days_lookback: int = 7,
    max_items: int = 20,
    format: str = "text"
) -> Dict[str, Any]:
    """
    Generate a digest from stored items.

    Args:
        days_lookback: Number of days to look back (default: 7)
        max_items: Maximum items to include (default: 20)
        format: Output format - "text", "html", or "both" (default: "text")

    Returns:
        Dictionary with:
            - success: bool
            - digest: rendered digest content
            - items_included: number of items in digest
            - total_items: total items in storage
    """
    try:
        storage = TrendItemStorage()
        items = storage.load_all()

        if not items:
            return {
                "success": True,
                "digest": "No items available for digest.",
                "items_included": 0,
                "total_items": 0
            }

        # Resolve feedback recipient from env (same pattern as digest subcommand)
        recipient_email = os.getenv("FEEDBACK_RECIPIENT_EMAIL")
        if not recipient_email:
            email_to = os.getenv("EMAIL_TO", "")
            first = email_to.split(",")[0].split(";")[0].strip()
            recipient_email = first or None

        generator = DigestGenerator(
            days_lookback=days_lookback,
            max_items=max_items,
            recipient_email=recipient_email,
        )

        result = generator.generate(items, format=format)

        return {
            "success": True,
            "digest": result.get("text") or result.get("html"),
            "items_included": result["items_included"],
            "total_items": result["total_items"]
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# --- Tool Registry with JSON Schema ---

TOOL_REGISTRY = {
    "scrape_source": {
        "function": tool_scrape_source,
        "schema": {
            "name": "scrape_source",
            "description": "Scrape content from a source URL. Only allowed sources in whitelist can be scraped.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The source URL to scrape"
                    },
                    "source_name": {
                        "type": "string",
                        "description": "Optional name for the source"
                    }
                },
                "required": ["url"]
            }
        }
    },
    "analyze_impact": {
        "function": tool_analyze_impact,
        "schema": {
            "name": "analyze_impact",
            "description": "Analyze content and extract structured trend item with title, summary, category, impact level, and insights.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Markdown content to analyze"
                    },
                    "source_url": {
                        "type": "string",
                        "description": "Source URL of the content"
                    },
                    "source_name": {
                        "type": "string",
                        "description": "Optional source name"
                    },
                    "category_hint": {
                        "type": "string",
                        "enum": ["Payments", "Regulatory"],
                        "description": "Optional category hint"
                    }
                },
                "required": ["content", "source_url"]
            }
        }
    },
    "check_duplicates": {
        "function": tool_check_duplicates,
        "schema": {
            "name": "check_duplicates",
            "description": "Check if an item already exists in storage (duplicate detection).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Source URL to check for duplicates"
                    },
                    "title": {
                        "type": "string",
                        "description": "Title to check for duplicates"
                    },
                    "item": {
                        "type": "object",
                        "description": "Full item dict to check"
                    }
                }
            }
        }
    },
    "render_digest": {
        "function": tool_render_digest,
        "schema": {
            "name": "render_digest",
            "description": "Generate a digest from stored trend items.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_lookback": {
                        "type": "integer",
                        "description": "Number of days to look back (default: 7)"
                    },
                    "max_items": {
                        "type": "integer",
                        "description": "Maximum items to include (default: 20)"
                    },
                    "format": {
                        "type": "string",
                        "enum": ["text", "html", "both"],
                        "description": "Output format (default: text)"
                    }
                }
            }
        }
    }
}


def get_tool_schemas() -> List[Dict[str, Any]]:
    """Get JSON schemas for all registered tools."""
    return [tool["schema"] for tool in TOOL_REGISTRY.values()]


def get_tool_function(name: str):
    """Get tool function by name."""
    tool = TOOL_REGISTRY.get(name)
    return tool["function"] if tool else None
