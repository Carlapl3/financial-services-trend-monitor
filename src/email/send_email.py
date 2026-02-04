"""
Email delivery module - send digest emails via SMTP.

Email delivery using SMTP with both plain text and HTML alternatives,
plus delivery logging.
"""

import os
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class EmailDelivery:
    """
    Email delivery service using SMTP.

    Supports both plain text and HTML email formats with delivery logging.
    Works with any SMTP-compatible email provider (Gmail, Outlook, etc.).
    """

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        email_from: Optional[str] = None,
        log_path: Optional[str] = None
    ):
        """
        Initialize email delivery service.

        Args:
            smtp_host: SMTP server hostname (defaults to SMTP_HOST env var)
            smtp_port: SMTP server port (defaults to SMTP_PORT env var or 587)
            smtp_user: SMTP username (defaults to SMTP_USER env var)
            smtp_password: SMTP password (defaults to SMTP_PASSWORD env var)
            email_from: Sender email address (defaults to EMAIL_FROM env var)
            log_path: Path to delivery log file (defaults to logs/run_log.jsonl)
        """
        self.smtp_host = smtp_host or os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = smtp_user or os.getenv("SMTP_USER")
        self.smtp_password = smtp_password or os.getenv("SMTP_PASSWORD")
        self.email_from = email_from or os.getenv("EMAIL_FROM")

        # Validate required configuration
        if not all([self.smtp_user, self.smtp_password, self.email_from]):
            raise ValueError(
                "Email configuration incomplete. Required: SMTP_USER, SMTP_PASSWORD, EMAIL_FROM. "
                "Set via environment variables or constructor parameters."
            )

        # Set up logging
        if log_path is None:
            logs_dir = Path(__file__).parent.parent.parent / "logs"
            log_path = str(logs_dir / "run_log.jsonl")

        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _parse_recipients(self, to_email: str) -> list[str]:
        """
        Parse recipient string into a list of email addresses.

        Supports comma and semicolon separation, strips whitespace, drops empties.

        Args:
            to_email: Recipient string (may contain multiple addresses)

        Returns:
            List of individual email addresses
        """
        if not to_email:
            return []

        # Split on commas and semicolons, strip whitespace, drop empties
        recipients = []
        for separator in [',', ';']:
            if separator in to_email:
                recipients = [addr.strip()
                              for addr in to_email.split(separator)]
                break
        else:
            # No separators found, treat as single address
            recipients = [to_email.strip()]

        # Filter out empty strings
        return [addr for addr in recipients if addr]

    def send_digest(
        self,
        to_email: str,
        subject: str,
        text_content: str,
        html_content: Optional[str] = None,
        items_count: int = 0,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send digest email with both text and HTML versions.

        Args:
            to_email: Recipient email address
            subject: Email subject line
            text_content: Plain text version of email
            html_content: HTML version of email (optional)
            items_count: Number of items included in digest (for logging)

        Returns:
            Dictionary with delivery status and details
        """
        try:
            # Parse recipients
            recipients = self._parse_recipients(to_email)
            if not recipients:
                raise ValueError("No valid recipient email addresses found")

            # Create multipart message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.email_from
            # Format header as comma-separated
            msg['To'] = ', '.join(recipients)

            # Attach text version
            text_part = MIMEText(text_content, 'plain', 'utf-8')
            msg.attach(text_part)

            # Attach HTML version if provided
            if html_content:
                html_part = MIMEText(html_content, 'html', 'utf-8')
                msg.attach(html_part)

            # Send email to all recipients
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()  # Enable TLS
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg, to_addrs=recipients)

            # Log successful delivery
            result = {
                "status": "success",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_id": run_id,
                "to": to_email,
                "subject": subject,
                "items_count": items_count,
                "has_html": html_content is not None
            }

            self._log_delivery(result)

            return result

        except smtplib.SMTPAuthenticationError as e:
            error_result = {
                "status": "failed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_id": run_id,
                "to": to_email,
                "subject": subject,
                "items_count": items_count,
                "error": "Authentication failed. Check SMTP credentials.",
                "error_details": str(e)
            }
            self._log_delivery(error_result)
            raise

        except smtplib.SMTPException as e:
            error_result = {
                "status": "failed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_id": run_id,
                "to": to_email,
                "subject": subject,
                "items_count": items_count,
                "error": "SMTP error occurred",
                "error_details": str(e)
            }
            self._log_delivery(error_result)
            raise

        except Exception as e:
            error_result = {
                "status": "failed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_id": run_id,
                "to": to_email,
                "subject": subject,
                "items_count": items_count,
                "error": "Unexpected error",
                "error_details": str(e)
            }
            self._log_delivery(error_result)
            raise

    def _log_delivery(self, result: Dict[str, Any]):
        """
        Log delivery event to JSONL file.

        Args:
            result: Delivery result dictionary
        """
        try:
            with open(self.log_path, 'a') as f:
                f.write(json.dumps(result) + '\n')
        except Exception as e:
            print(f"Warning: Failed to write delivery log: {e}")

    def get_delivery_stats(self) -> Dict[str, Any]:
        """
        Get delivery statistics from log file.

        Returns:
            Dictionary with delivery statistics
        """
        if not self.log_path.exists():
            return {
                "total_deliveries": 0,
                "successful": 0,
                "failed": 0,
                "log_path": str(self.log_path)
            }

        total = 0
        successful = 0
        failed = 0

        try:
            with open(self.log_path, 'r') as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)
                        total += 1
                        if entry.get("status") == "success":
                            successful += 1
                        elif entry.get("status") == "failed":
                            failed += 1
        except Exception as e:
            print(f"Warning: Failed to read delivery log: {e}")

        return {
            "total_deliveries": total,
            "successful": successful,
            "failed": failed,
            "success_rate": f"{(successful/total*100):.1f}%" if total > 0 else "N/A",
            "log_path": str(self.log_path)
        }


# Convenience function
def send_digest_email(
    to_email: str,
    subject: str,
    text_content: str,
    html_content: Optional[str] = None,
    items_count: int = 0
) -> Dict[str, Any]:
    """
    Convenience function to send digest email without instantiating EmailDelivery.

    Args:
        to_email: Recipient email address
        subject: Email subject line
        text_content: Plain text version
        html_content: HTML version (optional)
        items_count: Number of items in digest

    Returns:
        Delivery result dictionary
    """
    delivery = EmailDelivery()
    return delivery.send_digest(
        to_email=to_email,
        subject=subject,
        text_content=text_content,
        html_content=html_content,
        items_count=items_count
    )


# CLI functionality for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test email delivery")
    parser.add_argument("--to", required=True, help="Recipient email address")
    parser.add_argument("--subject", default="Test Digest",
                        help="Email subject")
    parser.add_argument("--test-mode", action="store_true",
                        help="Send test email with sample content")

    args = parser.parse_args()

    if args.test_mode:
        # Create test content
        text_content = """
Financial Services Trend Digest - Test Email
=============================================

This is a test email from the Financial Services Trend Monitoring system.

If you received this email, the email delivery system is working correctly!

Test item:
- Title: ECB Digital Euro Pilot
- Summary: The European Central Bank announced a pilot program.
- Why it matters: Banks need to prepare for integration.

---
End of test digest
        """.strip()

        html_content = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <h1 style="color: #0066cc;">Financial Services Trend Digest</h1>
    <p style="color: #666;">Test Email</p>
    <hr>
    <p>This is a test email from the Financial Services Trend Monitoring system.</p>
    <p><strong>If you received this email, the email delivery system is working correctly!</strong></p>
    <div style="background-color: #f5f5f5; padding: 15px; margin: 20px 0; border-left: 4px solid #0066cc;">
        <h3 style="margin-top: 0;">Test Item: ECB Digital Euro Pilot</h3>
        <p><strong>Summary:</strong> The European Central Bank announced a pilot program.</p>
        <p><strong>Why it matters:</strong> Banks need to prepare for integration.</p>
    </div>
    <hr>
    <p style="color: #666; font-size: 12px;">End of test digest</p>
</body>
</html>
        """

        print(f"\n=== Sending test email to {args.to} ===\n")

        try:
            delivery = EmailDelivery()
            result = delivery.send_digest(
                to_email=args.to,
                subject=args.subject,
                text_content=text_content,
                html_content=html_content,
                items_count=1
            )

            print(f"✓ Email sent successfully!")
            print(f"  Status: {result['status']}")
            print(f"  Timestamp: {result['timestamp']}")
            print(f"  To: {result['to']}")
            print(f"  Subject: {result['subject']}")

            # Show stats
            stats = delivery.get_delivery_stats()
            print(f"\n=== Delivery Statistics ===")
            print(f"  Total deliveries: {stats['total_deliveries']}")
            print(f"  Successful: {stats['successful']}")
            print(f"  Failed: {stats['failed']}")
            print(f"  Success rate: {stats['success_rate']}")

        except Exception as e:
            print(f"✗ Email delivery failed: {e}")
            import traceback
            traceback.print_exc()

    else:
        print("Use --test-mode flag to send a test email")
        print(f"Example: python send_email.py --to your@email.com --test-mode")
