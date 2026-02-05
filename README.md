# Financial Services Trend Monitor

> Agentic AI system that converts regulatory and fintech developments into prioritized executive briefings.

---

## Overview

Monitors regulatory and payments-related developments in financial services and transforms unstructured information into prioritized executive briefings.

Designed to showcase how agentic system design can shorten research cycles and support faster, higher-quality decision-making in advisory and financial services contexts.

---

## Architecture

![Architecture diagram](docs/architecture.svg)

Hybrid system combining deterministic processing with agentic orchestration.

**Deterministic pipeline**  
Sources → Collection → LLM Extraction → Deduplication → Digest → Email

**Agent controller (ReAct)**  
Dynamically orchestrates pipeline tools:

- `scrape_source` → Collection  
- `analyze_impact` → Extraction  
- `check_dupes` → Storage  
- `render_digest` → Digest  

**Feedback loop**  
Recipient relevance signals feed back into future ranking.

---

## Key Design Decisions

- Hybrid agent + pipeline architecture  
- Structured LLM extraction (typed schemas)  
- Two-tier deduplication (URL normalization + content hash)  
- Append-only storage for auditability  
- Feedback-weighted ranking  
- Constrained agent action space  

---

## Guardrails & Safety

- Agent step + timeout limits  
- Source domain allowlist enforcement  
- PII-safe feedback logging  
- Idempotent relevance storage  
- Environment-based secret handling  

---

## Tech Stack

**LLM / Agent**  
OpenAI · Instructor · ReAct controller

**Backend**  
Python · FastAPI  

**Data**  
Pydantic · JSONL storage  

**Collection**  
Firecrawl · RSS ingestion  

**Delivery**  
SMTP email  

**Testing**  
pytest (agent + pipeline + feedback)

---

## Repository Structure

- `docs/`: — Architecture diagrams and design documentation  
- `src/`: — Pipeline, agent, feedback server, email delivery  
- `config/`: — Agent limits, source allowlist, feedback tuning  
- `examples/`: — Execution traces and behavior walkthroughs  
- `tests/`: — Unit and E2E tests (agent, pipeline, feedback)
