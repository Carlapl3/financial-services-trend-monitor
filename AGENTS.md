# AGENTS.md

## System

Agentic AI system that monitors financial services sources (regulatory + payments),
extracts structured intelligence via LLM, and delivers prioritized scheduled briefings.
Partner feedback signals flow back into ranking.

## Modules

src/models.py                       — Data contracts (TrendItem, enums)
src/pipeline/collect.py             — Source ingestion (Firecrawl + RSS)
src/pipeline/extract.py             — Structured LLM extraction
src/pipeline/dedupe.py              — Deduplication (URL norm + content hash)
src/pipeline/digest.py              — Prioritization + digest rendering (impact × recency × feedback)
src/agent/controller.py             — ReAct loop with step/timeout limits
src/agent/tools.py                  — Tool registry wrapping pipeline stages + URL allowlist
src/agent/llm_callback.py           — OpenAI JSON-mode structured callback
src/feedback/server.py              — FastAPI feedback endpoint (rate-limited, PII-safe)
src/feedback/relevance_store.py     — Feedback storage → digest boost
src/scheduler/cron_entrypoints.py   — CLI: collect | digest | alert (default: agent mode)
src/email/send_email.py             — SMTP delivery

## Config

config/agent_limits.yaml            — Agent guardrails (steps, timeout)
config/allowed_sources.yaml         — URL allowlist for scraping
config/feedback.yaml                — Relevance boost parameter
src/config/sources.yaml             — Source definitions (RSS + HTML)

## Plan Mode

- Make the plan extremely concise. Sacrifice grammar for the sake of concision.
- At the end of each plan, list unresolved questions (if any).
- Do not write code before plan approval.
- Verify with tests after implementation.

## Working in This Repo

- Keep pipeline stages single-responsibility; don't duplicate logic across modules.
- Agent tools wrap pipeline code; prefer updating pipeline modules over adding new branches in tools.
- All data flows through TrendItem (src/models.py).
- No hardcoded secrets; use environment variables.

## JIT Index (quick find)

- Entry points / CLI: rg -n "collect|digest|agent|argparse" src/scheduler/cron_entrypoints.py
- ReAct + guardrails: rg -n "max_steps|timeout|run\\(" src/agent
- Feedback boost wiring: rg -n "RELEVANCE_BOOST|RelevanceStore|get_relevant" src/pipeline src/feedback
- Dedup rules: rg -n "normalize_url|TRACKING|hash" src/pipeline/dedupe.py

## Tests

python -m pytest tests/ -q
