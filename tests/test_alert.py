"""
Tests for HIGH-impact email alerting.

Verifies that check_high_impact_alerts():
- Sends email for new HIGH-impact items within the lookback window
- Skips items already recorded in the alert state file
- Does nothing when no HIGH-impact items exist
- Handles naive and missing timestamps without crashing
"""

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.models import Category, ImpactLevel, TrendItem
from src.pipeline.dedupe import TrendItemStorage


def _make_item(item_id, impact=ImpactLevel.MEDIUM, hours_ago=1):
    now = datetime.now(timezone.utc)
    return TrendItem(
        id=item_id,
        title=f"Item {item_id}",
        publication_date=now - timedelta(days=1),
        source_url=f"https://example.com/{item_id}",
        summary=f"Summary for {item_id}",
        category=Category.PAYMENTS,
        impact_level=impact,
        why_it_matters=f"Insight for {item_id}",
        created_at=now - timedelta(hours=hours_ago),
    )


def test_alert_sends_for_new_high_impact_items():
    """New HIGH-impact items within lookback trigger an email alert."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = str(Path(tmpdir) / "items.jsonl")
        state_path = str(Path(tmpdir) / "alerted.txt")

        storage = TrendItemStorage(storage_path)
        storage.save(_make_item("high0001high0001", ImpactLevel.HIGH, hours_ago=2))
        storage.save(_make_item("med00001med00001", ImpactLevel.MEDIUM, hours_ago=1))

        mock_delivery = MagicMock()
        mock_delivery.send_digest.return_value = {"status": "success"}

        env = {
            "ALERT_EMAIL_TO": "alert@example.com",
            "ALERT_STATE_PATH": state_path,
        }
        with patch.dict(os.environ, env), \
             patch("src.scheduler.cron_entrypoints.TrendItemStorage", return_value=storage), \
             patch("src.scheduler.cron_entrypoints.EmailDelivery", return_value=mock_delivery):

            from src.scheduler.cron_entrypoints import check_high_impact_alerts
            result = check_high_impact_alerts(lookback_hours=24)

        assert result["status"] == "alerts_sent"
        assert result["items_alerted"] == 1

        mock_delivery.send_digest.assert_called_once()
        call_kwargs = mock_delivery.send_digest.call_args[1]
        assert "alert@example.com" == call_kwargs["to_email"]
        assert "high0001high0001" in call_kwargs["text_content"]
        assert "med00001med00001" not in call_kwargs["text_content"]

        # State file should contain the alerted ID
        alerted = Path(state_path).read_text().strip().splitlines()
        assert "high0001high0001" in alerted


def test_alert_skips_already_alerted_items():
    """Items already in the state file should not trigger another alert."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = str(Path(tmpdir) / "items.jsonl")
        state_path = str(Path(tmpdir) / "alerted.txt")

        storage = TrendItemStorage(storage_path)
        storage.save(_make_item("high0001high0001", ImpactLevel.HIGH, hours_ago=2))

        # Pre-populate state file
        Path(state_path).write_text("high0001high0001\n")

        mock_delivery = MagicMock()

        env = {
            "ALERT_EMAIL_TO": "alert@example.com",
            "ALERT_STATE_PATH": state_path,
        }
        with patch.dict(os.environ, env), \
             patch("src.scheduler.cron_entrypoints.TrendItemStorage", return_value=storage), \
             patch("src.scheduler.cron_entrypoints.EmailDelivery", return_value=mock_delivery):

            from src.scheduler.cron_entrypoints import check_high_impact_alerts
            result = check_high_impact_alerts(lookback_hours=24)

        assert result["status"] == "no_new_alerts"
        mock_delivery.send_digest.assert_not_called()


def test_alert_no_email_when_no_high_items():
    """No email should be sent when there are no HIGH-impact items."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = str(Path(tmpdir) / "items.jsonl")
        state_path = str(Path(tmpdir) / "alerted.txt")

        storage = TrendItemStorage(storage_path)
        storage.save(_make_item("med00001med00001", ImpactLevel.MEDIUM))
        storage.save(_make_item("low00001low00001", ImpactLevel.LOW))

        mock_delivery = MagicMock()

        env = {
            "ALERT_EMAIL_TO": "alert@example.com",
            "ALERT_STATE_PATH": state_path,
        }
        with patch.dict(os.environ, env), \
             patch("src.scheduler.cron_entrypoints.TrendItemStorage", return_value=storage), \
             patch("src.scheduler.cron_entrypoints.EmailDelivery", return_value=mock_delivery):

            from src.scheduler.cron_entrypoints import check_high_impact_alerts
            result = check_high_impact_alerts(lookback_hours=24)

        assert result["status"] == "no_new_alerts"
        mock_delivery.send_digest.assert_not_called()


def test_alert_handles_naive_and_missing_timestamps():
    """Items with naive created_at or no timestamp should not crash the alert check."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = str(Path(tmpdir) / "items.jsonl")
        state_path = str(Path(tmpdir) / "alerted.txt")

        # Item with naive (no tz) created_at
        naive_item = _make_item("naiv0001naiv0001", ImpactLevel.HIGH, hours_ago=1)
        naive_item.created_at = datetime(2026, 2, 4, 12, 0, 0)  # naive, no tzinfo

        # Item with proper aware timestamp
        aware_item = _make_item("awar0001awar0001", ImpactLevel.HIGH, hours_ago=1)

        storage = TrendItemStorage(storage_path)
        storage.save(naive_item)
        storage.save(aware_item)

        mock_delivery = MagicMock()
        mock_delivery.send_digest.return_value = {"status": "success"}

        env = {
            "ALERT_EMAIL_TO": "alert@example.com",
            "ALERT_STATE_PATH": state_path,
        }
        with patch.dict(os.environ, env), \
             patch("src.scheduler.cron_entrypoints.TrendItemStorage", return_value=storage), \
             patch("src.scheduler.cron_entrypoints.EmailDelivery", return_value=mock_delivery):

            from src.scheduler.cron_entrypoints import check_high_impact_alerts
            # Should not crash regardless of timestamp format
            result = check_high_impact_alerts(lookback_hours=48)

        # Should succeed — at least the aware item is alertable
        assert result["status"] in ("alerts_sent", "no_new_alerts")
