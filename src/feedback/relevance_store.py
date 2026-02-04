"""
Relevance feedback storage — JSONL-based store for user relevance signals.

Tracks which digest items a recipient marked as relevant via the feedback
endpoint. Used by the digest prioritization layer to boost previously-relevant
items in future digests.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Set, Tuple

from pydantic import BaseModel


class RelevanceFeedback(BaseModel):
    """Single relevance feedback record."""

    email: str
    item_id: str
    run_id: Optional[str] = None
    timestamp: datetime


class RelevanceStore:
    """
    JSONL-based storage for relevance feedback with in-memory cache.

    Idempotency: at most one record per (email, item_id) pair.
    Email is normalized to lowercase before any operation.
    """

    _EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    def __init__(self, storage_path: Optional[str] = None):
        if storage_path is None:
            data_dir = Path(__file__).parent.parent.parent / "data"
            storage_path = str(data_dir / "relevance_feedback.jsonl")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # In-memory cache: set of (email, item_id) for fast idempotency check
        self._cache: Set[Tuple[str, str]] = set()
        # Secondary index: email → set of item_ids for fast lookup
        self._email_items: dict[str, Set[str]] = {}
        self._load_cache()

    def _load_cache(self):
        """Rebuild caches from existing JSONL file."""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, "r") as f:
                for line in f:
                    if line.strip():
                        record = json.loads(line)
                        email = record.get("email", "").lower()
                        item_id = record.get("item_id", "")
                        if email and item_id:
                            self._cache.add((email, item_id))
                            self._email_items.setdefault(email, set()).add(item_id)
        except Exception as e:
            print(f"Warning: Failed to load relevance cache: {e}")

    @classmethod
    def _validate_email(cls, email: str) -> str:
        """Validate and normalize email. Raises ValueError if invalid."""
        email = email.strip().lower()
        if not cls._EMAIL_RE.match(email):
            raise ValueError("Invalid email format")
        return email

    def save_relevant(
        self, email: str, item_id: str, run_id: Optional[str] = None
    ) -> bool:
        """
        Record that a recipient marked an item as relevant.

        Args:
            email: Recipient email address
            item_id: Stable item identifier
            run_id: Optional digest run identifier

        Returns:
            True if newly saved, False if already recorded (idempotent)

        Raises:
            ValueError: If email format is invalid
        """
        email = self._validate_email(email)

        key = (email, item_id)
        if key in self._cache:
            return False

        record = RelevanceFeedback(
            email=email,
            item_id=item_id,
            run_id=run_id,
            timestamp=datetime.now(timezone.utc),
        )

        with open(self.storage_path, "a") as f:
            f.write(json.dumps(record.model_dump(mode="json")) + "\n")

        self._cache.add(key)
        self._email_items.setdefault(email, set()).add(item_id)
        return True

    def get_relevant_item_ids(self, email: str) -> Set[str]:
        """
        Get all item IDs that a recipient marked as relevant.

        Args:
            email: Recipient email address

        Returns:
            Set of item_id strings (empty set if none found)
        """
        email = email.strip().lower()
        return set(self._email_items.get(email, set()))
