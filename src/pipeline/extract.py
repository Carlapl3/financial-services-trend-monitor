"""
LLM-based extraction pipeline - convert raw markdown to structured TrendItem.

Uses Instructor with OpenAI API to extract structured data from markdown content,
including title, summary, category, impact level, and "why it matters" insights.
"""

import os
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import instructor
from openai import OpenAI
from dotenv import load_dotenv

from src.models import TrendItem, Category, ImpactLevel

# Load environment variables
load_dotenv()


class TrendExtractor:
    """
    Extracts structured TrendItem data from raw markdown using LLM.

    Uses Instructor library to leverage OpenAI API with structured outputs,
    ensuring extraction conforms to TrendItem Pydantic model.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize trend extractor.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: OpenAI model to use (defaults to LLM_MODEL env var or "gpt-4o-mini")
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key not found. Set OPENAI_API_KEY environment variable "
                "or pass api_key to constructor."
            )

        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")

        # Initialize Instructor-patched OpenAI client
        self.client = instructor.from_openai(OpenAI(api_key=self.api_key))

    def build_extraction_prompt(
        self,
        markdown: str,
        source_name: str,
        source_url: str,
        source_category: Optional[str] = None
    ) -> str:
        """
        Build extraction prompt for LLM.

        Args:
            markdown: Raw markdown content to extract from
            source_name: Name of the source
            source_url: URL of the source
            source_category: Optional category hint (Payments/Regulatory)

        Returns:
            Formatted prompt string
        """
        category_hint = ""
        if source_category:
            category_hint = f"\nNote: This source is primarily focused on {source_category}."

        prompt = f"""You are a financial services trend analyst helping professionals stay updated on industry developments.

Extract key information from this article to create a trend briefing for busy professionals.

SOURCE: {source_name}
URL: {source_url}{category_hint}

CONTENT:
{markdown}

---

EXTRACTION REQUIREMENTS:

1. TITLE: Extract or create a clear, informative title (if not explicit in content, create one based on main topic)

2. PUBLICATION_DATE: Extract publication date if available in the content. If not found, return None.

3. SUMMARY: Write a concise 2-3 sentence summary focusing on:
   - What happened/was announced
   - Key facts and figures
   - Primary stakeholders involved

4. CATEGORY: Classify as either "Payments" or "Regulatory" based on the primary focus:
   - Payments: Digital payments, payment systems, fintech, payment infrastructure
   - Regulatory: Financial regulations, compliance requirements, policy changes, supervisory updates

5. IMPACT_LEVEL: Assess the importance for financial services professionals:
   - High: Major regulatory changes, significant market shifts, breaking developments
   - Medium: Notable updates, important trends, moderate policy changes
   - Low: Minor updates, background information, general industry news

6. WHY_IT_MATTERS: Write 1-2 sentences explaining the practical relevance:
   - How does this affect financial institutions?
   - What should professionals be aware of?
   - What strategic implications exist for banking/fintech organizations?
   - Focus on actionable insights for decision-makers

Be specific, concise, and focus on practical value for professionals."""

        return prompt

    def extract(
        self,
        markdown: str,
        source_name: str,
        source_url: str,
        source_category: Optional[str] = None,
        fallback_title: Optional[str] = None,
        fallback_date: Optional[datetime] = None
    ) -> TrendItem:
        """
        Extract TrendItem from raw markdown content.

        Args:
            markdown: Raw markdown content
            source_name: Name of the source
            source_url: URL of the source
            source_category: Optional category hint
            fallback_title: Title to use if extraction fails
            fallback_date: Date to use if not found in content

        Returns:
            Structured TrendItem

        Raises:
            Exception: If extraction fails and no fallbacks provided
        """
        prompt = self.build_extraction_prompt(
            markdown=markdown,
            source_name=source_name,
            source_url=source_url,
            source_category=source_category
        )

        try:
            # Use Instructor to extract structured data
            item = self.client.chat.completions.create(
                model=self.model,
                response_model=TrendItem,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a financial services trend analyst. Extract structured information from articles for professionals."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            # Apply fallbacks if extraction returned None for optional fields
            if not item.publication_date and fallback_date:
                item.publication_date = fallback_date

            if not item.title or len(item.title.strip()) == 0:
                if fallback_title:
                    item.title = fallback_title
                else:
                    item.title = f"Update from {source_name}"

            # Ensure source_url is set
            item.source_url = source_url

            return item

        except Exception as e:
            # If extraction completely fails, create minimal item with fallbacks
            if not fallback_title:
                fallback_title = f"Content from {source_name}"

            if not fallback_date:
                fallback_date = datetime.now(timezone.utc)

            print(f"Warning: Extraction failed for {source_url}: {e}")
            print(f"Creating minimal item with fallbacks")

            # Create minimal trend item
            return TrendItem(
                title=fallback_title,
                publication_date=fallback_date,
                source_url=source_url,
                summary=f"Content from {source_name}. Extraction failed: {str(e)[:100]}",
                category=Category.PAYMENTS if source_category == "Payments" else Category.REGULATORY,
                impact_level=ImpactLevel.LOW,
                why_it_matters="Extraction failed. Manual review required."
            )

    def extract_batch(
        self,
        raw_items: list[Dict[str, Any]]
    ) -> list[TrendItem]:
        """
        Extract TrendItems from a batch of raw items.

        Args:
            raw_items: List of raw item dictionaries from collector

        Returns:
            List of structured TrendItems

        Example:
            >>> extractor = TrendExtractor()
            >>> raw_items = collector.collect_all()
            >>> trend_items = extractor.extract_batch(raw_items)
        """
        trend_items = []

        print(f"\n=== Extracting {len(raw_items)} items ===\n")

        for i, raw_item in enumerate(raw_items, 1):
            if not raw_item.get('success'):
                print(f"[{i}/{len(raw_items)}] Skipping failed collection: {raw_item.get('source_name')}")
                continue

            print(f"[{i}/{len(raw_items)}] Extracting: {raw_item.get('source_name')}")

            try:
                trend_item = self.extract(
                    markdown=raw_item.get('raw_markdown', ''),
                    source_name=raw_item.get('source_name', 'Unknown'),
                    source_url=raw_item.get('source_url', ''),
                    source_category=raw_item.get('category'),
                    fallback_title=raw_item.get('title'),
                    fallback_date=raw_item.get('publication_date')
                )
                trend_items.append(trend_item)
                print(f"  ✓ Extracted: {trend_item.category.value} | {trend_item.impact_level.value}")

            except Exception as e:
                print(f"  ✗ Failed: {e}")
                continue

        print(f"\n=== Extraction complete: {len(trend_items)}/{len(raw_items)} successful ===")

        return trend_items


# CLI functionality for testing
if __name__ == "__main__":
    # Example usage with sample markdown
    sample_markdown = """
    # ECB Launches Digital Euro Pilot Program

    Published: January 15, 2024

    The European Central Bank announced today the launch of a pilot program for the digital euro,
    focusing on cross-border payment infrastructure. The two-year program will involve major
    European banks including Deutsche Bank, BNP Paribas, and Santander.

    Key objectives include:
    - Testing real-time settlement mechanisms
    - Ensuring compliance with EU privacy regulations
    - Evaluating impact on monetary policy transmission

    The ECB estimates the digital euro could reduce cross-border payment costs by up to 40%.
    """

    extractor = TrendExtractor()

    print("=== Testing TrendExtractor ===\n")
    print("Sample markdown:")
    print(sample_markdown[:200] + "...\n")

    item = extractor.extract(
        markdown=sample_markdown,
        source_name="ECB Press Release",
        source_url="https://example.com/ecb-digital-euro",
        source_category="Payments"
    )

    print("\n=== Extracted TrendItem ===")
    print(f"Title: {item.title}")
    print(f"Category: {item.category.value}")
    print(f"Impact: {item.impact_level.value}")
    print(f"Summary: {item.summary}")
    print(f"Why it matters: {item.why_it_matters}")
