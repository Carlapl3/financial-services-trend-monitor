"""
Feedback server — FastAPI app for capturing relevance signals from email digests.

Endpoints:
  GET /feedback/health    — health check
  GET /feedback/relevant  — record that a recipient found an item relevant

CLI entry: python -m src.feedback.server
"""

import hashlib
import logging
import re
import time
from collections import defaultdict
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse

from src.feedback.relevance_store import RelevanceStore

logger = logging.getLogger(__name__)


def _email_hash(email: str) -> str:
    """Return a short, non-reversible hash of an email for logging (no PII)."""
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()[:8]


class _RateLimiter:
    """Simple in-memory rate limiter per IP.

    Best-effort protection only — not a substitute for a proper WAF or
    reverse-proxy rate limit. Suitable for an internal / small-audience
    endpoint.

    Limits: ``max_requests`` per ``window_seconds`` per client IP.
    """

    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, ip: str) -> bool:
        now = time.monotonic()
        window_start = now - self.window_seconds
        # Prune old entries
        self._hits[ip] = [t for t in self._hits[ip] if t > window_start]
        if len(self._hits[ip]) >= self.max_requests:
            return False
        self._hits[ip].append(now)
        return True


def _html_page(title: str, message: str, status_code: int = 200) -> HTMLResponse:
    """Return a simple, mobile-friendly HTML page."""
    html = (
        "<html><body style=\"font-family:sans-serif;text-align:center;padding:2em\">"
        f"<h2>{title}</h2><p>{message}</p>"
        "</body></html>"
    )
    return HTMLResponse(content=html, status_code=status_code)


def create_app(store: Optional[RelevanceStore] = None) -> FastAPI:
    """
    Create the feedback FastAPI application.

    Args:
        store: Optional RelevanceStore instance (defaults to production path).
               Pass a custom instance for testing.
    """
    if store is None:
        store = RelevanceStore()

    app = FastAPI(title="Feedback Server", docs_url=None, redoc_url=None)
    rate_limiter = _RateLimiter(max_requests=30, window_seconds=60)

    @app.get("/feedback/health", response_class=HTMLResponse)
    async def health():
        return _html_page("OK", "Feedback server is running.")

    _ITEM_ID_RE = re.compile(r"^[0-9a-f]{16}$")

    @app.get("/feedback/relevant", response_class=HTMLResponse)
    async def record_relevant(
        request: Request,
        item_id: str = Query(..., min_length=1),
        email: str = Query(..., min_length=1),
        run_id: Optional[str] = Query(None),
    ):
        client_ip = request.client.host if request.client else "unknown"
        if not rate_limiter.is_allowed(client_ip):
            logger.warning("outcome=rate_limited ip=%s", client_ip)
            return _html_page("Too many requests.", "Please try again later.", 429)

        eh = _email_hash(email)

        if not _ITEM_ID_RE.match(item_id):
            logger.warning("outcome=invalid item_id=%s email_hash=%s", item_id, eh)
            return _html_page("Invalid request.", "item_id must be exactly 16 hex characters.", 400)

        try:
            is_new = store.save_relevant(email=email, item_id=item_id, run_id=run_id)
        except ValueError:
            logger.warning("outcome=invalid_email item_id=%s email_hash=%s", item_id, eh)
            return _html_page("Invalid request.", "Please check the link and try again.", 400)
        except Exception:
            logger.exception("outcome=error item_id=%s email_hash=%s run_id=%s", item_id, eh, run_id)
            return _html_page("Something went wrong.", "Please try again later.", 500)

        if is_new:
            logger.info("outcome=new item_id=%s email_hash=%s run_id=%s", item_id, eh, run_id)
            return _html_page("Thanks! Noted.", "Your feedback has been recorded.")
        else:
            logger.info("outcome=duplicate item_id=%s email_hash=%s run_id=%s", item_id, eh, run_id)
            return _html_page("Already noted.", "We already have your feedback for this item.")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.feedback.server:app", host="0.0.0.0", port=8000, reload=True)
