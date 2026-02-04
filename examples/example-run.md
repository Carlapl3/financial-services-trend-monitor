# Example Run

The pipeline exposes three CLI commands.

---

## 1. Collect

```bash
python -m src.scheduler.cron_entrypoints collect
```

Scrapes configured sources, extracts structured trend items via LLM, and stores them with deduplication.

## 2. Digest

```bash
python -m src.scheduler.cron_entrypoints digest --days 7
```

Generates a prioritized digest from items collected in the last 7 days and emails it to the recipients in `EMAIL_TO`. Add `--dry-run` to preview without sending.

## 3. Alert

```bash
python -m src.scheduler.cron_entrypoints alert --hours 24
```

Checks for HIGH-impact items collected in the last 24 hours and sends an email alert for any not yet reported.
