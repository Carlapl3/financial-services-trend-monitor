"""
Data models for Financial Services Trend Monitoring.

This module defines Pydantic models for trend items and operational logging.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, HttpUrl


def _utcnow() -> datetime:
    """Timezone-aware UTC now, avoiding deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc)


class Category(str, Enum):
    """
    Category classification for trend items.

    Minimum required categories per PRD:
    - Payments: Payment systems, digital payments, fintech innovations
    - Regulatory: Financial regulations, compliance, policy changes
    """
    PAYMENTS = "Payments"
    REGULATORY = "Regulatory"


class ImpactLevel(str, Enum):
    """
    Impact level assessment for trend items.

    Levels:
    - High: Critical developments requiring immediate attention
    - Medium: Important updates worth monitoring
    - Low: Informational, background awareness
    """
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class TrendItem(BaseModel):
    """
    Represents a single trend item collected from financial services sources.

    Attributes:
        id: Unique identifier (optional, assigned by storage layer)
        title: Headline or title of the trend item
        publication_date: When the item was published (ISO 8601 format)
        source_url: URL where the item was found
        summary: Short summary of the content
        category: Classification (e.g., "Payments", "Regulatory")
        impact_level: Assessed importance (High/Medium/Low)
        why_it_matters: Actionable insight on why this trend matters
        created_at: Timestamp when item was collected (auto-generated)
    """

    id: Optional[str] = None
    title: str = Field(..., min_length=1, max_length=500)
    publication_date: datetime
    source_url: HttpUrl
    summary: str = Field(..., min_length=1, max_length=2000)
    category: Category
    impact_level: ImpactLevel
    why_it_matters: str = Field(..., min_length=1, max_length=1000)
    created_at: datetime = Field(default_factory=_utcnow)

    class Config:
        """Pydantic model configuration."""
        json_schema_extra = {
            "example": {
                "title": "ECB announces new digital euro pilot program",
                "publication_date": "2024-01-15T10:30:00Z",
                "source_url": "https://example.com/ecb-digital-euro",
                "summary": "The European Central Bank has launched a pilot program for the digital euro, targeting cross-border payments.",
                "category": "Payments",
                "impact_level": "High",
                "why_it_matters": "Banks need to prepare for digital euro integration, affecting cross-border payment infrastructure and regulatory compliance strategies.",
                "created_at": "2024-01-15T14:22:00Z"
            }
        }


class RunStatus(str, Enum):
    """
    Status of a digest generation run.

    Statuses:
    - Success: Run completed successfully
    - Partial: Run completed with some errors
    - Failed: Run failed completely
    """
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class RunLog(BaseModel):
    """
    Log entry for digest generation and delivery runs.

    Per PRD requirement: "The system must log each digest generation and delivery
    event, including at minimum: timestamp, number of items included."

    Attributes:
        timestamp: When the run occurred
        items_count: Number of items included in the digest
        status: Outcome of the run (success/partial/failed)
    """

    run_id: Optional[str] = Field(default=None, description="Unique identifier for this pipeline run")
    timestamp: datetime = Field(default_factory=_utcnow)
    items_count: int = Field(..., ge=0)
    status: RunStatus

    class Config:
        """Pydantic model configuration."""
        json_schema_extra = {
            "example": {
                "run_id": "a1b2c3d4",
                "timestamp": "2024-01-15T07:00:00Z",
                "items_count": 15,
                "status": "success"
            }
        }
