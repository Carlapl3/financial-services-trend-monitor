# Relevant Feedback Behavior

How the relevance feedback loop works, end-to-end.

## What happens when a recipient clicks "Relevant"

Each item in the HTML digest includes a small **Relevant ✓** link. Clicking it
sends a GET request to the feedback server:

```
GET /feedback/relevant?item_id=a1b2c3d4e5f67890&email=recipient%40example.com&run_id=digest-2026-01-27-0700
```

### Server response

| Scenario | HTTP status | Message shown |
|----------|-------------|---------------|
| First click | 200 | "Thanks! Noted." |
| Duplicate click | 200 | "Already noted." |
| Invalid item_id | 400 | "item_id must be exactly 16 hex characters." |
| Rate limited | 429 | "Please try again later." |

### What it stores

An append-only JSONL line in `data/relevance.jsonl`:

```json
{"email": "recipient@example.com", "item_id": "a1b2c3d4e5f67890", "run_id": "digest-2026-01-27-0700", "timestamp": "2026-01-27T08:15:00+00:00"}
```

### How it affects the next digest

On the next digest run for the same recipient, the system:

1. Loads the set of `item_id` values that recipient previously marked relevant
2. Adds a configurable score boost (default +0.5) to those items during
   prioritization
3. Boosted items rank higher even if they are older or lower-impact than
   unboosted items

This creates a lightweight feedback loop: items similar to what the recipient
found useful rise in future digests.

### Privacy

- Server logs use a truncated SHA-256 hash of the email, never the raw address
- Rate limiting is per-IP (30 requests / 60 seconds)
