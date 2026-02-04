# Financial Services Trend Monitor

An agentic AI system that monitors financial services sources (regulatory bodies, payments industry), extracts structured intelligence via LLM, and delivers prioritized digests. Recipients can mark items as relevant, creating a feedback loop that improves future ranking.

## Architecture

- **ReAct agent** — LLM-driven reasoning loop that dynamically selects tools each step, with step-limit and timeout guardrails (`config/agent_limits.yaml`)
- **Deterministic pipeline** — collect → extract → dedupe → digest, each stage single-responsibility and independently runnable
- **Two-tier deduplication** — normalized URL matching + title-date content hashing, with tracking-parameter stripping
- **Feedback loop** — "Relevant" clicks in digest emails feed back into a per-recipient relevance store; boosted items rank higher in subsequent digests
- **HIGH-impact alerting** — scans for critical items within a configurable lookback window and sends immediate email alerts

## Quickstart

### Prerequisites

```
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set at minimum:

```
OPENAI_API_KEY=...
FIRECRAWL_API_KEY=...
SMTP_HOST=...
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
EMAIL_FROM=...
EMAIL_TO=...
```

### Run

```bash
# Collect from all configured sources, extract trend items, store with dedup
python -m src.scheduler.cron_entrypoints collect

# Generate a digest from the last 7 days (--dry-run skips email delivery)
python -m src.scheduler.cron_entrypoints digest --days 7 --dry-run

# Alert on HIGH-impact items from the last 24 hours
python -m src.scheduler.cron_entrypoints alert --hours 24
```

### Tests

```bash
python -m pytest tests/ -q
```

## Examples

- [`examples/agent-execution-trace.md`](examples/agent-execution-trace.md) — ReAct loop decision flow
- [`examples/relevant-feedback-behavior.md`](examples/relevant-feedback-behavior.md) — feedback loop walkthrough
- [`examples/example-run.md`](examples/example-run.md) — CLI command reference
