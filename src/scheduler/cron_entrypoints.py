"""
CLI entrypoints for pipeline jobs.

Provides command-line interfaces for:
- Content collection
- Digest generation and delivery
"""

from src.models import ImpactLevel
from src.email.send_email import EmailDelivery
from src.pipeline.digest import DigestGenerator
from src.pipeline.dedupe import TrendItemStorage
from src.pipeline.extract import TrendExtractor
from src.pipeline.collect import SourceCollector
from src.agent.controller import AgentController
from src.agent.tools import TOOL_REGISTRY
from src.agent.llm_callback import make_llm_callback
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

_AGENT_DEFAULT_GOAL = (
    "Collect content from all configured sources, extract trend items, "
    "check for duplicates, and render a digest of financial services trends."
)


def run_collection():
    """
    Content collection job.

    Pipeline:
    1. Collect raw items from sources (Firecrawl)
    2. Extract structured TrendItems (LLM)
    3. Store with deduplication (JSONL)
    4. Log run statistics
    """
    print("\n" + "="*70)
    print("CONTENT COLLECTION")
    print("="*70)
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("="*70 + "\n")

    try:
        # Step 1: Collect raw items
        print("Step 1: Collecting from sources...")
        collector = SourceCollector()
        raw_items = collector.collect_all(priority_filter="must-have")

        successful_raw = [item for item in raw_items if item.get('success')]
        print(
            f"\n✓ Collection complete: {len(successful_raw)}/{len(raw_items)} successful\n")

        if not successful_raw:
            print("⚠ No items collected. Exiting.")
            return {
                "status": "completed",
                "items_collected": 0,
                "items_extracted": 0,
                "items_stored": 0,
                "message": "No items collected"
            }

        # Step 2: Extract structured data
        print("Step 2: Extracting structured data with LLM...")
        extractor = TrendExtractor()
        trend_items = extractor.extract_batch(successful_raw)

        print(f"\n✓ Extraction complete: {len(trend_items)} items\n")

        # Step 3: Store with deduplication
        print("Step 3: Storing items with deduplication...")
        storage = TrendItemStorage()
        saved, skipped = storage.save_batch(trend_items, skip_duplicates=True)

        print(
            f"\n✓ Storage complete: {saved} saved, {skipped} duplicates skipped\n")

        # Summary
        result = {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "items_collected": len(successful_raw),
            "items_extracted": len(trend_items),
            "items_stored": saved,
            "items_skipped": skipped
        }

        print("="*70)
        print("COLLECTION SUMMARY")
        print("="*70)
        print(f"Collected: {result['items_collected']}")
        print(f"Extracted: {result['items_extracted']}")
        print(f"Stored: {result['items_stored']} (new)")
        print(f"Skipped: {result['items_skipped']} (duplicates)")
        print("="*70 + "\n")

        return result

    except Exception as e:
        print(f"\n✗ Error during collection: {e}")
        import traceback
        traceback.print_exc()

        return {
            "status": "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e)
        }


def run_digest(
    recipient_email: str = None,
    subject: str = "Financial Services Trend Digest",
    days_lookback: int = 7,
    dry_run: bool = False,
):
    """
    Digest generation and delivery job.

    Pipeline:
    1. Load stored TrendItems
    2. Generate digest (text + HTML)
    3. Send email
    4. Log delivery

    Args:
        recipient_email: Email address to send to (defaults to EMAIL_TO env var)
        subject: Email subject line
        days_lookback: Number of days to look back for items (default: 7)
    """
    print("\n" + "="*70)
    print("DIGEST GENERATION & DELIVERY")
    print("="*70)
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("="*70 + "\n")

    try:
        # Get recipient from env if not provided
        if recipient_email is None:
            recipient_email = os.getenv("EMAIL_TO")
            if not recipient_email:
                raise ValueError(
                    "Recipient email not specified. "
                    "Set EMAIL_TO environment variable or pass --to parameter."
                )

        # Parse EMAIL_TO into a list for delivery (supports comma/semicolon)
        import re
        recipients_list = [
            addr.strip()
            for addr in re.split(r"[,;]", recipient_email)
            if addr.strip()
        ]
        if not recipients_list:
            raise ValueError("No valid email addresses found in EMAIL_TO.")

        # Single email for feedback links: prefer FEEDBACK_RECIPIENT_EMAIL, else first parsed
        feedback_recipient = (
            os.getenv("FEEDBACK_RECIPIENT_EMAIL") or recipients_list[0]
        )

        # For delivery, pass the full comma-separated list; for digest, single email
        delivery_to = ", ".join(recipients_list)

        # Step 1: Load stored items
        print("Step 1: Loading stored trend items...")
        storage = TrendItemStorage()
        all_items = storage.load_all()

        print(f"✓ Loaded {len(all_items)} items from storage\n")

        if not all_items:
            print("⚠ No items in storage. Exiting.")
            return {
                "status": "completed",
                "items_total": 0,
                "items_included": 0,
                "message": "No items available for digest"
            }

        # Step 2: Generate digest
        run_id = f"digest-{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M')}"
        print(
            f"Step 2: Generating digest (text + HTML, {days_lookback} days lookback, run_id={run_id})...")
        generator = DigestGenerator(
            days_lookback=days_lookback,
            max_items=20,
            recipient_email=feedback_recipient,
        )
        digest = generator.generate(all_items, format="both", run_id=run_id)

        print(
            f"✓ Digest generated: {digest['items_included']}/{digest['total_items']} items included\n")

        if digest['items_included'] == 0:
            print("⚠ No recent items for digest. Exiting.")
            return {
                "status": "completed",
                "items_total": digest['total_items'],
                "items_included": 0,
                "message": "No recent items for digest"
            }

        # Step 3: Send email (or skip in dry-run mode)
        if dry_run:
            print("Step 3: DRY RUN — skipping email delivery\n")
            print("="*70)
            print("DIGEST SUMMARY (DRY RUN)")
            print("="*70)
            print(f"Total items in storage: {digest['total_items']}")
            print(f"Items included in digest: {digest['items_included']}")
            print(f"Recipient: {delivery_to or '(not set)'}")
            print(f"Run ID: {run_id}")
            print("="*70 + "\n")
            result = {
                "status": "success",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "items_total": digest['total_items'],
                "items_included": digest['items_included'],
                "recipient": delivery_to,
                "delivery_status": "dry_run",
                "dry_run": True,
            }
        else:
            print(f"Step 3: Sending digest to {delivery_to}...")
            email_delivery = EmailDelivery()
            delivery_result = email_delivery.send_digest(
                to_email=delivery_to,
                subject=subject,
                text_content=digest['text'],
                html_content=digest['html'],
                items_count=digest['items_included'],
                run_id=run_id,
            )

            print(f"✓ Email sent successfully\n")

            result = {
                "status": "success",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "items_total": digest['total_items'],
                "items_included": digest['items_included'],
                "recipient": delivery_to,
                "delivery_status": delivery_result['status'],
            }

            print("="*70)
            print("DIGEST SUMMARY")
            print("="*70)
            print(f"Total items in storage: {result['items_total']}")
            print(f"Items included in digest: {result['items_included']}")
            print(f"Recipient: {result['recipient']}")
            print(f"Delivery status: {result['delivery_status']}")
            print("="*70 + "\n")

        return result

    except Exception as e:
        print(f"\n✗ Error during digest generation: {e}")
        import traceback
        traceback.print_exc()

        return {
            "status": "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e)
        }


def check_high_impact_alerts(recipient_email=None, lookback_hours=24):
    """
    Check for new HIGH-impact items and send email alerts.

    Args:
        recipient_email: Alert recipient (defaults to ALERT_EMAIL_TO or EMAIL_TO env)
        lookback_hours: Only alert on items collected within this window (default: 24)

    Returns:
        Dictionary with status and alert details
    """
    print("\n" + "="*70)
    print("HIGH-IMPACT ALERT CHECK")
    print("="*70)
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print(f"Lookback: {lookback_hours} hours")
    print("="*70 + "\n")

    try:
        # Resolve recipient
        recipient = (
            recipient_email
            or os.getenv("ALERT_EMAIL_TO")
            or os.getenv("EMAIL_TO")
        )
        if not recipient:
            raise ValueError(
                "No alert recipient configured. "
                "Set ALERT_EMAIL_TO or EMAIL_TO environment variable."
            )

        # Load items and filter for HIGH impact within lookback window
        storage = TrendItemStorage()
        items = storage.load_all()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

        high_items = []
        for item in items:
            if item.impact_level != ImpactLevel.HIGH:
                continue
            ts = getattr(item, 'collected_at', None) or getattr(item, 'created_at', None)
            if ts is None:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                high_items.append(item)

        if not high_items:
            print("No HIGH-impact items in lookback window.")
            return {"status": "no_new_alerts", "items_checked": len(items)}

        # Load already-alerted IDs
        state_path = Path(os.getenv("ALERT_STATE_PATH", "/tmp/alerted_item_ids.txt"))
        alerted_ids = set()
        if state_path.exists():
            alerted_ids = {
                line.strip() for line in state_path.read_text().splitlines()
                if line.strip()
            }

        new_high = [item for item in high_items if item.id and item.id not in alerted_ids]

        if not new_high:
            print(f"All {len(high_items)} HIGH-impact items already alerted.")
            return {
                "status": "no_new_alerts",
                "items_checked": len(items),
                "already_alerted": len(high_items),
            }

        # Render alert body
        lines = [f"{len(new_high)} HIGH-Impact Item(s) Detected\n"]
        for item in new_high:
            lines.append(f"  {item.title}")
            lines.append(f"  Impact: {item.impact_level.value} | {item.category.value}")
            lines.append(f"  {item.summary}")
            lines.append(f"  Source: {item.source_url}")
            lines.append("")
        text_content = "\n".join(lines)

        # Send alert
        print(f"Sending alert for {len(new_high)} item(s) to {recipient}...")
        delivery = EmailDelivery()
        delivery_result = delivery.send_digest(
            to_email=recipient,
            subject=f"HIGH-Impact Alert: {len(new_high)} new item(s)",
            text_content=text_content,
            items_count=len(new_high),
        )

        # Record alerted IDs on success
        if delivery_result.get("status") == "success":
            state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(state_path, "a") as f:
                for item in new_high:
                    f.write(f"{item.id}\n")

        result = {
            "status": "alerts_sent",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "items_alerted": len(new_high),
            "delivery": delivery_result.get("status"),
        }

        print("\n" + "="*70)
        print("ALERT SUMMARY")
        print("="*70)
        print(f"Items alerted: {result['items_alerted']}")
        print(f"Delivery: {result['delivery']}")
        print("="*70 + "\n")

        return result

    except Exception as e:
        print(f"\n✗ Error during alert check: {e}")
        import traceback
        traceback.print_exc()

        return {
            "status": "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Financial Services Trend Monitoring - Pipeline Jobs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run agent (default when no subcommand given)
  python -m src.scheduler.cron_entrypoints

  # Run collection
  python -m src.scheduler.cron_entrypoints collect

  # Run digest
  python -m src.scheduler.cron_entrypoints digest --to user@example.com

  # Check for HIGH-impact alerts
  python -m src.scheduler.cron_entrypoints alert --to user@example.com

  # Test with custom subject
  python -m src.scheduler.cron_entrypoints digest --to test@example.com --subject "Test Digest"
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Collection command
    collect_parser = subparsers.add_parser(
        'collect',
        help='Run content collection'
    )

    # Digest command
    digest_parser = subparsers.add_parser(
        'digest',
        help='Run digest generation and delivery'
    )
    digest_parser.add_argument(
        '--to',
        help='Recipient email address (defaults to EMAIL_TO env var)'
    )
    digest_parser.add_argument(
        '--subject',
        default='Financial Services Trend Digest',
        help='Email subject line'
    )
    digest_parser.add_argument(
        '--days',
        type=int,
        default=7,
        help='Number of days to look back for items (default: 7)'
    )
    digest_parser.add_argument(
        '--dry-run',
        action='store_true',
        default=False,
        help='Generate digest and print summary without sending email'
    )

    # Alert command
    alert_parser = subparsers.add_parser(
        'alert',
        help='Send alerts for new HIGH-impact items'
    )
    alert_parser.add_argument(
        '--to',
        help='Recipient email (defaults to ALERT_EMAIL_TO or EMAIL_TO env var)'
    )
    alert_parser.add_argument(
        '--hours',
        type=int,
        default=24,
        help='Lookback window in hours (default: 24)'
    )

    args = parser.parse_args()

    if args.command == 'collect':
        result = run_collection()
        sys.exit(0 if result.get('status') != 'failed' else 1)

    elif args.command == 'digest':
        result = run_digest(
            recipient_email=args.to,
            subject=args.subject,
            days_lookback=args.days,
            dry_run=args.dry_run,
        )
        sys.exit(0 if result.get('status') != 'failed' else 1)

    elif args.command == 'alert':
        result = check_high_impact_alerts(
            recipient_email=args.to,
            lookback_hours=args.hours,
        )
        sys.exit(0 if result.get('status') != 'failed' else 1)

    else:
        # Default: run the agent loop
        print("\n" + "="*70)
        print("AGENT MODE")
        print("="*70)
        print(f"Started: {datetime.now(timezone.utc).isoformat()}")
        print("="*70 + "\n")

        agent = AgentController(tools=TOOL_REGISTRY)
        callback = make_llm_callback(tool_schemas=agent.get_tool_schemas())
        result = agent.run(goal=_AGENT_DEFAULT_GOAL, llm_callback=callback)

        print("\n" + "="*70)
        print("AGENT RESULT")
        print("="*70)
        print(f"Success: {result['success']}")
        print(f"Stop reason: {result['stop_reason']}")
        print(f"Steps taken: {result['steps_taken']}")
        print(f"Elapsed: {result.get('elapsed_time', 0):.1f}s")
        if result.get('final_answer'):
            print(f"Answer: {result['final_answer'][:500]}")
        print("="*70 + "\n")

        sys.exit(0 if result.get('success') else 1)


if __name__ == "__main__":
    main()
