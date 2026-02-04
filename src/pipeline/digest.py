"""
Digest generation pipeline - prioritize and render email digests.

Implements prioritization (impact level + recency), item selection, and
rendering to both plain text and lightweight HTML formats.
"""

from typing import List, Optional, Set
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
import os

import yaml

from src.models import TrendItem, ImpactLevel


def _load_relevance_boost(default: float = 0.5) -> float:
    """Load RELEVANCE_BOOST from config/feedback.yaml with fallback to *default*."""
    config_path = Path(__file__).parent.parent.parent / "config" / "feedback.yaml"
    try:
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
        return float(cfg["boost"]["per_click"])
    except Exception:
        return default


class DigestGenerator:
    """
    Generates email digests from TrendItems.

    Prioritizes items by impact level (High→Medium→Low) then recency,
    selects top items from past week, and renders to text/HTML formats.
    """

    # Impact level priority order (higher number = higher priority)
    IMPACT_PRIORITY = {
        ImpactLevel.HIGH: 3,
        ImpactLevel.MEDIUM: 2,
        ImpactLevel.LOW: 1
    }

    RELEVANCE_BOOST = _load_relevance_boost()

    def __init__(
        self,
        days_lookback: int = 7,
        max_items: int = 20,
        min_items: int = 10,
        recipient_email: Optional[str] = None,
    ):
        self.days_lookback = days_lookback
        self.max_items = max_items
        self.min_items = min_items
        self.recipient_email = recipient_email

        # Load relevance data if recipient is known
        self._relevant_ids: Set[str] = set()
        if recipient_email:
            try:
                from src.feedback.relevance_store import RelevanceStore
                store = RelevanceStore()
                self._relevant_ids = store.get_relevant_item_ids(recipient_email)
            except Exception:
                pass  # graceful degradation

    def prioritize_items(self, items: List[TrendItem]) -> List[TrendItem]:
        """
        Prioritize items by total score (impact + relevance boost) then recency.

        Relevance boost: +0.5 (binary) when item.id is in the recipient's
        relevant set.  When no recipient is configured the boost is always 0,
        preserving default behaviour.
        """
        def _score(item: TrendItem) -> tuple:
            base = self.IMPACT_PRIORITY.get(item.impact_level, 0)
            boost = (
                self.RELEVANCE_BOOST
                if item.id and item.id in self._relevant_ids
                else 0
            )
            return (-base - boost, -item.publication_date.timestamp())

        return sorted(items, key=_score)

    def select_items(
        self,
        items: List[TrendItem],
        cutoff_date: Optional[datetime] = None
    ) -> List[TrendItem]:
        """
        Select top items from recent period.

        Args:
            items: List of all available TrendItems
            cutoff_date: Only include items after this date (defaults to days_lookback)

        Returns:
            Filtered and prioritized list (top 10-20 items)
        """
        if cutoff_date is None:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.days_lookback)

        # Filter by date — normalise both sides to aware-UTC before comparing.
        # Naive datetimes are assumed to be UTC.
        recent_items = []
        compare_date = (
            cutoff_date
            if cutoff_date.tzinfo is not None
            else cutoff_date.replace(tzinfo=timezone.utc)
        )
        for item in items:
            if item.publication_date:
                item_date = item.publication_date
                if item_date.tzinfo is None:
                    item_date = item_date.replace(tzinfo=timezone.utc)

                if item_date >= compare_date:
                    recent_items.append(item)

        # Prioritize
        prioritized = self.prioritize_items(recent_items)

        # Select top items (between min and max)
        if len(prioritized) > self.max_items:
            return prioritized[:self.max_items]
        elif len(prioritized) >= self.min_items:
            return prioritized
        else:
            # If fewer than min_items, return what we have
            return prioritized

    def render_text(
        self,
        items: List[TrendItem],
        title: str = "Financial Services Trend Digest"
    ) -> str:
        """
        Render digest as plain text format.

        Args:
            items: Prioritized list of TrendItems
            title: Digest title

        Returns:
            Plain text formatted digest
        """
        lines = []

        # Header
        lines.append("=" * 70)
        lines.append(title.upper())
        lines.append("=" * 70)
        lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append(f"Items: {len(items)}")
        lines.append("=" * 70)
        lines.append("")

        # Group by impact level
        high_impact = [i for i in items if i.impact_level == ImpactLevel.HIGH]
        medium_impact = [i for i in items if i.impact_level == ImpactLevel.MEDIUM]
        low_impact = [i for i in items if i.impact_level == ImpactLevel.LOW]

        # High impact section
        if high_impact:
            lines.append("🔴 HIGH IMPACT")
            lines.append("-" * 70)
            for idx, item in enumerate(high_impact, 1):
                lines.extend(self._format_item_text(idx, item))
            lines.append("")

        # Medium impact section
        if medium_impact:
            lines.append("🟡 MEDIUM IMPACT")
            lines.append("-" * 70)
            for idx, item in enumerate(medium_impact, len(high_impact) + 1):
                lines.extend(self._format_item_text(idx, item))
            lines.append("")

        # Low impact section
        if low_impact:
            lines.append("🟢 LOW IMPACT")
            lines.append("-" * 70)
            for idx, item in enumerate(low_impact, len(high_impact) + len(medium_impact) + 1):
                lines.extend(self._format_item_text(idx, item))
            lines.append("")

        # Footer
        lines.append("=" * 70)
        lines.append("End of digest")
        lines.append("=" * 70)

        return "\n".join(lines)

    def _format_item_text(self, idx: int, item: TrendItem) -> List[str]:
        """Format a single item for text output."""
        lines = []
        lines.append(f"\n{idx}. {item.title}")
        lines.append(f"   Category: {item.category.value}")
        lines.append(f"   Date: {item.publication_date.strftime('%Y-%m-%d')}")
        lines.append(f"   Source: {item.source_url}")
        lines.append("")
        lines.append(f"   Summary:")
        lines.append(f"   {item.summary}")
        lines.append("")
        lines.append(f"   Why it matters:")
        lines.append(f"   {item.why_it_matters}")
        lines.append("")

        return lines

    def render_html(
        self,
        items: List[TrendItem],
        title: str = "Financial Services Trend Digest",
        run_id: Optional[str] = None,
    ) -> str:
        """
        Render digest as lightweight HTML format.

        Args:
            items: Prioritized list of TrendItems
            title: Digest title
            run_id: Digest run identifier (passed to feedback links)

        Returns:
            HTML formatted digest (mobile-friendly, scannable)
        """
        html_parts = []

        # HTML header with inline CSS for mobile-friendliness
        html_parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>""" + title + """</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 {
            color: #1a1a1a;
            border-bottom: 3px solid #0066cc;
            padding-bottom: 10px;
            margin-top: 0;
        }
        .meta {
            color: #666;
            font-size: 14px;
            margin-bottom: 30px;
        }
        .section {
            margin-bottom: 40px;
        }
        .section-header {
            font-size: 20px;
            font-weight: bold;
            margin-bottom: 20px;
            padding: 10px;
            border-radius: 4px;
        }
        .high-impact { background-color: #ffe6e6; color: #cc0000; }
        .medium-impact { background-color: #fff4e6; color: #cc6600; }
        .low-impact { background-color: #e6f7ff; color: #0066cc; }
        .item {
            margin-bottom: 30px;
            padding: 20px;
            background-color: #fafafa;
            border-left: 4px solid #0066cc;
            border-radius: 4px;
        }
        .item-title {
            font-size: 18px;
            font-weight: bold;
            color: #1a1a1a;
            margin-bottom: 10px;
        }
        .item-meta {
            font-size: 14px;
            color: #666;
            margin-bottom: 15px;
        }
        .badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
            margin-right: 8px;
        }
        .badge-payments { background-color: #e6f7ff; color: #0066cc; }
        .badge-regulatory { background-color: #f0e6ff; color: #6600cc; }
        .summary {
            margin-bottom: 15px;
            line-height: 1.7;
        }
        .why-matters {
            background-color: #fffbf0;
            border-left: 3px solid #ffcc00;
            padding: 12px;
            font-style: italic;
            margin-top: 15px;
        }
        .source-link {
            color: #0066cc;
            text-decoration: none;
            font-size: 14px;
        }
        .source-link:hover {
            text-decoration: underline;
        }
        @media (max-width: 600px) {
            body { padding: 10px; }
            .container { padding: 15px; }
            .item-title { font-size: 16px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>""" + title + """</h1>
        <div class="meta">
            Generated: """ + datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC') + """<br>
            Items included: """ + str(len(items)) + """
        </div>
""")

        # Group by impact level
        high_impact = [i for i in items if i.impact_level == ImpactLevel.HIGH]
        medium_impact = [i for i in items if i.impact_level == ImpactLevel.MEDIUM]
        low_impact = [i for i in items if i.impact_level == ImpactLevel.LOW]

        # High impact section
        if high_impact:
            html_parts.append('        <div class="section">')
            html_parts.append('            <div class="section-header high-impact">🔴 High Impact</div>')
            for item in high_impact:
                html_parts.append(self._format_item_html(item, run_id=run_id))
            html_parts.append('        </div>')

        # Medium impact section
        if medium_impact:
            html_parts.append('        <div class="section">')
            html_parts.append('            <div class="section-header medium-impact">🟡 Medium Impact</div>')
            for item in medium_impact:
                html_parts.append(self._format_item_html(item, run_id=run_id))
            html_parts.append('        </div>')

        # Low impact section
        if low_impact:
            html_parts.append('        <div class="section">')
            html_parts.append('            <div class="section-header low-impact">🟢 Low Impact</div>')
            for item in low_impact:
                html_parts.append(self._format_item_html(item, run_id=run_id))
            html_parts.append('        </div>')

        # Footer
        html_parts.append("""
    </div>
</body>
</html>""")

        return "\n".join(html_parts)

    def _format_item_html(self, item: TrendItem, run_id: Optional[str] = None) -> str:
        """Format a single item for HTML output, optionally with feedback link."""
        category_badge_class = "badge-payments" if item.category.value == "Payments" else "badge-regulatory"

        feedback_link = ""
        base_url = os.environ.get("FEEDBACK_BASE_URL")
        if base_url and item.id and self.recipient_email:
            # Guardrail: feedback email must be a single address (no commas/semicolons)
            import re
            safe_email = re.split(r"[,;]", self.recipient_email)[0].strip()
            params = {"item_id": item.id, "email": safe_email}
            if run_id:
                params["run_id"] = run_id
            url = f"{base_url.rstrip('/')}/feedback/relevant?{urlencode(params)}"
            feedback_link = (
                f'  <a href="{url}" style="color:#0a0;text-decoration:none;'
                f'font-size:14px;margin-left:12px">Relevant ✓</a>'
            )

        return f"""            <div class="item">
                <div class="item-title">{item.title}</div>
                <div class="item-meta">
                    <span class="badge {category_badge_class}">{item.category.value}</span>
                    <span>{item.publication_date.strftime('%B %d, %Y')}</span>
                </div>
                <div class="summary">{item.summary}</div>
                <div class="why-matters">
                    <strong>Why it matters:</strong> {item.why_it_matters}
                </div>
                <div style="margin-top: 12px;">
                    <a href="{item.source_url}" class="source-link">Read more →</a>{feedback_link}
                </div>
            </div>
"""

    def generate(
        self,
        items: List[TrendItem],
        format: str = "both",
        run_id: Optional[str] = None,
    ) -> dict:
        """
        Generate digest in specified format(s).

        Args:
            items: List of all available TrendItems
            format: "text", "html", or "both" (default)
            run_id: Digest run identifier (passed to feedback links)

        Returns:
            Dictionary with keys "text" and/or "html" containing rendered digests
        """
        # Select and prioritize items
        selected_items = self.select_items(items)

        result = {}

        if format in ["text", "both"]:
            result["text"] = self.render_text(selected_items)

        if format in ["html", "both"]:
            result["html"] = self.render_html(selected_items, run_id=run_id)

        result["items_included"] = len(selected_items)
        result["total_items"] = len(items)

        return result


# CLI functionality for testing
if __name__ == "__main__":
    print("\n=== DigestGenerator Test ===\n")

    from src.models import Category, ImpactLevel
    from datetime import datetime, timedelta

    # Create sample items for testing
    now = datetime.now(timezone.utc)
    sample_items = [
        TrendItem(
            title="ECB Launches Digital Euro Pilot",
            publication_date=now - timedelta(days=1),
            source_url="https://ecb.europa.eu/digital-euro",
            summary="The European Central Bank announced a two-year pilot program for the digital euro.",
            category=Category.PAYMENTS,
            impact_level=ImpactLevel.HIGH,
            why_it_matters="Banks need to prepare for digital euro integration."
        ),
        TrendItem(
            title="EBA Updates Capital Requirements",
            publication_date=now - timedelta(days=2),
            source_url="https://eba.europa.eu/capital-2024",
            summary="New guidelines on ICAAP effective January 2025.",
            category=Category.REGULATORY,
            impact_level=ImpactLevel.HIGH,
            why_it_matters="Clients must update capital planning frameworks immediately."
        ),
        TrendItem(
            title="Instant Payment Regulation Enters Force",
            publication_date=now - timedelta(days=3),
            source_url="https://ec.europa.eu/instant-payments",
            summary="All EU PSPs must support instant payments within 12 months.",
            category=Category.PAYMENTS,
            impact_level=ImpactLevel.MEDIUM,
            why_it_matters="Affects payment infrastructure and fraud prevention systems."
        ),
    ]

    generator = DigestGenerator()
    digest = generator.generate(sample_items, format="text")

    print(digest["text"])
    print(f"\n\nGenerated digest with {digest['items_included']} items")
