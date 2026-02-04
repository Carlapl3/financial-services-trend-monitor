"""
Tests for feedback server.

Tests cover:
- Health endpoint
- Valid feedback submission
- Idempotent duplicate handling
- Input validation (email, item_id)
- Cross-email independence
"""

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.feedback.relevance_store import RelevanceStore
from src.feedback.server import create_app


def _make_client(tmpdir: str) -> tuple[TestClient, str]:
    """Create a TestClient backed by a temp-dir RelevanceStore."""
    path = str(Path(tmpdir) / "feedback.jsonl")
    store = RelevanceStore(storage_path=path)
    app = create_app(store=store)
    return TestClient(app), path


class TestHealth:
    """Tests for /feedback/health endpoint."""

    def test_health_returns_200(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client, _ = _make_client(tmpdir)
            resp = client.get("/feedback/health")
            assert resp.status_code == 200
            assert "OK" in resp.text


class TestFeedbackEndpoint:
    """Tests for valid feedback submissions."""

    def test_valid_submission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client, _ = _make_client(tmpdir)
            resp = client.get(
                "/feedback/relevant",
                params={"email": "user@example.com", "item_id": "abc123def456abcd"},
            )
            assert resp.status_code == 200
            assert "Thanks" in resp.text

    def test_idempotent_second_click(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client, _ = _make_client(tmpdir)
            params = {"email": "user@example.com", "item_id": "abc123def456abcd"}

            first = client.get("/feedback/relevant", params=params)
            second = client.get("/feedback/relevant", params=params)

            assert first.status_code == 200
            assert "Thanks" in first.text
            assert second.status_code == 200
            assert "Already noted" in second.text

    def test_run_id_passed_through(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client, path = _make_client(tmpdir)
            client.get(
                "/feedback/relevant",
                params={
                    "email": "user@example.com",
                    "item_id": "abc123def456abcd",
                    "run_id": "digest-2024-01-15-0700",
                },
            )

            with open(path, "r") as f:
                record = json.loads(f.readline())
            assert record["run_id"] == "digest-2024-01-15-0700"


class TestValidation:
    """Tests for input validation."""

    def test_missing_email(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client, _ = _make_client(tmpdir)
            resp = client.get(
                "/feedback/relevant", params={"item_id": "abc123def456abcd"}
            )
            assert resp.status_code == 422

    def test_invalid_email(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client, _ = _make_client(tmpdir)
            resp = client.get(
                "/feedback/relevant",
                params={"email": "not-an-email", "item_id": "abc123def456abcd"},
            )
            assert resp.status_code == 400
            assert "Invalid" in resp.text

    def test_missing_item_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client, _ = _make_client(tmpdir)
            resp = client.get(
                "/feedback/relevant", params={"email": "user@example.com"}
            )
            assert resp.status_code == 422

    def test_empty_item_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            client, _ = _make_client(tmpdir)
            resp = client.get(
                "/feedback/relevant",
                params={"email": "user@example.com", "item_id": ""},
            )
            assert resp.status_code == 422


class TestIdempotentBehavior:
    """Tests for cross-email independence."""

    def test_different_emails_same_item(self):
        """Two different emails clicking same item should both get 'Thanks'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client, _ = _make_client(tmpdir)

            resp_alice = client.get(
                "/feedback/relevant",
                params={"email": "alice@example.com", "item_id": "abcd1234abcd1234"},
            )
            resp_bob = client.get(
                "/feedback/relevant",
                params={"email": "bob@example.com", "item_id": "abcd1234abcd1234"},
            )

            assert resp_alice.status_code == 200
            assert "Thanks" in resp_alice.text
            assert resp_bob.status_code == 200
            assert "Thanks" in resp_bob.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
