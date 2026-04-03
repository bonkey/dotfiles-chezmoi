#!/usr/bin/env python3
"""Gmail Attachment Auto-Archiver.

Queries Gmail for known recurring senders, downloads attachments,
files them into the correct folder, and labels+archives the email.

Usage:
    python3 archive_gmail.py run                      # download & archive
    python3 archive_gmail.py run --rule "Office Club"  # one rule only
    python3 archive_gmail.py run --since 2026-03-01    # override start date
    python3 archive_gmail.py run --folder ~/my/archive # custom working folder
    python3 archive_gmail.py list-rules                # show all rules
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import termios
import tty
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_FOLDER = Path.home() / "Documents" / "Archiwum dokumentów"
ARCHIVE_LABEL_NAME = "Stored"
DEFAULT_SINCE_DAYS = 45  # look back ~6 weeks on first run

RULES = [
    # -----------------------------------------------------------------------
    # Tier 1 — Monthly invoices with established naming conventions
    # -----------------------------------------------------------------------
    {
        "name": "Office Club",
        "from": "info@officeclub.com",
        "subject_contains": "Your invoice",
        "destination": "Firmen/Office Club",
        "attachment_filter": r"\.pdf$",
    },
    {
        "name": "Google Cloud",
        "from": "payments-noreply@google.com",
        "subject_contains": "Google Cloud Platform",
        "destination": "Firmen/Google",
        "attachment_filter": r"\.pdf$",
    },
    {
        "name": "Google Workspace",
        "from": "payments-noreply@google.com",
        "subject_contains": "Google Workspace",
        "destination": "Firmen/Google",
        "attachment_filter": r"\.pdf$",
    },
    {
        "name": "DNS.NET",
        "from": "service@dns-net.de",
        "subject_contains": "Rechnung Nr.",
        "destination": "Firmen/DNS.NET",
        "attachment_filter": r"\.pdf$",
    },
    {
        "name": "Telekom",
        "from": "Kundenservice.Rechnungonline@telekom.de",
        "subject_contains": "RechnungOnline",
        "destination": "Firmen/Telekom",
        "attachment_filter": r"\.pdf$",
    },
    {
        "name": "MyPlace",
        "from": "prenzlauerpromenade@myplace.de",
        "subject_contains": "Rechnung",
        "destination": "Firmen/MyPlace",
        "attachment_filter": r"\.pdf$",
    },
    {
        "name": "Natalia",
        "from": "natalia@hallozusammen.pl",
        "subject_contains": None,  # match any with attachment
        "destination": "Firmen/Natalia",
        "attachment_filter": r"faktura.*\.pdf$",
    },
    # -----------------------------------------------------------------------
    # Tier 2 — SaaS/subscription receipts (Stripe-style)
    # -----------------------------------------------------------------------
    {
        "name": "Anthropic",
        "from": "invoice+statements@mail.anthropic.com",
        "subject_contains": "receipt",
        "destination": "Firmen/Anthropic",
        "attachment_filter": r"\.pdf$",
        "create_folder": True,
        "rename_from_subject": r"#(\S+)",  # extract receipt ID
    },
    {
        "name": "Raycast",
        "from": "invoice+statements@raycast.com",
        "subject_contains": "receipt",
        "destination": "Firmen/Raycast",
        "attachment_filter": r"\.pdf$",
        "create_folder": True,
        "rename_from_subject": r"#(\S+)",
    },
    {
        "name": "Kagi",
        "from_contains": "stripe.com",
        "subject_contains": "Kagi",
        "destination": "Firmen/Kagi",
        "attachment_filter": r"\.pdf$",
        "create_folder": True,
        "rename_from_subject": r"#(\S+)",
    },
    {
        "name": "Linear",
        "from_contains": "stripe.com",
        "subject_contains": "Linear",
        "destination": "Firmen/Linear",
        "attachment_filter": r"\.pdf$",
        "create_folder": True,
        "rename_from_subject": r"#(\S+)",
    },
    {
        "name": "Midjourney",
        "from": "invoice+statements@midjourney.com",
        "subject_contains": "receipt",
        "destination": "Firmen/Midjourney",
        "attachment_filter": r"\.pdf$",
        "create_folder": True,
        "rename_from_subject": r"#(\S+)",
    },
    {
        "name": "ElevenLabs",
        "from_contains": "stripe.com",
        "subject_contains": "Eleven Labs",
        "destination": "Firmen/ElevenLabs",
        "attachment_filter": r"\.pdf$",
        "create_folder": True,
        "rename_from_subject": r"#(\S+)",
    },
    {
        "name": "Moonshot AI",
        "from_contains": "stripe.com",
        "subject_contains": "MOONSHOT",
        "destination": "Firmen/Moonshot AI",
        "attachment_filter": r"\.pdf$",
        "create_folder": True,
        "rename_from_subject": r"#(\S+)",
    },
    {
        "name": "Captions",
        "from": "invoice+statements@captions.ai",
        "subject_contains": "receipt",
        "destination": "Firmen/Captions",
        "attachment_filter": r"\.pdf$",
        "create_folder": True,
        "rename_from_subject": r"#(\S+)",
    },
    {
        "name": "Hugging Face",
        "from_contains": "stripe.com",
        "subject_contains": "Hugging Face",
        "destination": "Firmen/Hugging Face",
        "attachment_filter": r"\.pdf$",
        "create_folder": True,
        "rename_from_subject": r"#(\S+)",
    },
    {
        "name": "Vercel",
        "from": "invoice+statements@vercel.com",
        "subject_contains": "receipt",
        "destination": "Firmen/Vercel",
        "attachment_filter": r"\.pdf$",
        "create_folder": True,
        "rename_from_subject": r"#(\S+)",
    },
    {
        "name": "Paddle",
        "from": "help@paddle.com",
        "subject_contains": "receipt",
        "destination": "Firmen/Paddle",
        "attachment_filter": r"\.pdf$",
        "create_folder": True,
    },
    # -----------------------------------------------------------------------
    # Tier 3 — Periodic / as-needed
    # -----------------------------------------------------------------------
    {
        "name": "REWE eBon",
        "from": "ebon@mailing.rewe.de",
        "subject_contains": "eBon",
        "destination": "Firmen/REWE",
        "attachment_filter": r"\.pdf$",
        "create_folder": True,
        "rename_from_subject": r"vom (\d{2}\.\d{2}\.\d{4})",  # "vom 27.03.2026" → date
        "rename_template": "REWE-eBon-{}.pdf",  # REWE-eBon-27.03.2026.pdf
    },
    {
        "name": "WeWork",
        "from": "noreply@wework.com",
        "subject_contains": "payment was successfully processed",
        "destination": "Firmen/WeWork",
        "attachment_filter": r"\.pdf$",
    },
    {
        "name": "AGILA",
        "from_contains": "agila.de",
        "subject_contains": None,  # any with attachment
        "destination": "Versicherung/AGILA",
        "attachment_filter": r"\.pdf$",
        "create_folder": True,
    },
    {
        "name": "Apple Invoicing",
        "from": "EMEA_Invoicing@email.apple.com",
        "subject_contains": "Rechnungsnummer",
        "destination": "Firmen/Apple",
        "attachment_filter": r"\.pdf$",
    },
    {
        "name": "Tierarztpraxis Lenk",
        "from": "info@tierarztpraxis-lenk.de",
        "subject_contains": "Rechnung",
        "destination": "Hunde/Tierarzt Lenk",
        "attachment_filter": r"\.pdf$",
        "create_folder": True,
    },
    {
        "name": "Steuerberatung Schopp",
        "from_contains": "steuerberatung-schopp.de",
        "subject_contains": None,
        "destination": "Ämter/Finanzamt/MSchopp",
        "attachment_filter": r"\.pdf$",
    },
    {
        "name": "Grundeinkommen",
        "from_contains": "grundeinkommen.de",
        "subject_contains": "Spendenbescheinigung",
        "destination": "Geld/Grundeinkommen",
        "attachment_filter": r"\.pdf$",
    },
    {
        "name": "Starlink",
        "from": "no-reply@starlink.com",
        "subject_contains": None,
        "destination": "Firmen/Starlink",
        "attachment_filter": r"\.pdf$",
        "create_folder": True,
    },
    # -----------------------------------------------------------------------
    # Link-based downloads (no attachment, PDF link in email body)
    # -----------------------------------------------------------------------
    {
        "name": "Miles",
        "from_contains": "miles-mobility.com",
        "subject_contains": "Your invoice",
        "destination": "Firmen/Miles",
        "create_folder": True,
        "link_download": True,
        # Direct API URL in HTML email body
        "link_pattern": r'https://api\.app\.miles-mobility\.com/mobile/InvoiceServices\?asPDF=1&invoiceUUID=[0-9A-Fa-f-]+',
        # Extract invoice number from plain text body for filename
        "filename_from_body": r"Invoice nr\.: (\d+)",
        "filename_template": "Miles-{}.pdf",
    },
    # -----------------------------------------------------------------------
    # Manual portal downloads (can't automate, prompt user)
    # -----------------------------------------------------------------------
    {
        "name": "Gothaer Portal",
        "from_contains": "gothaer.de",
        "subject_contains": "Neue Nachricht",
        "manual_portal": True,
        "portal_url": "https://www.gothaer.de/meine-gothaer/portal.htm",
        "destination": "Gesundheit/Arztrechnungen",
    },
    {
        "name": "DNS.NET Portal",
        "from": "service@dns-net.de",
        "subject_contains": "Kundenportal",
        "manual_portal": True,
        "portal_url": "https://mein.dns-net.de/",
        "destination": "Firmen/DNS.NET",
    },
]

# ---------------------------------------------------------------------------
# gws CLI wrappers
# ---------------------------------------------------------------------------


def gws_triage(query: str, max_results: int = 100) -> list[dict]:
    """Run gws gmail +triage and return list of {id, from, subject, date}."""
    cmd = [
        "gws", "gmail", "+triage",
        "--query", query,
        "--max", str(max_results),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        return []

    messages = []
    for line in result.stdout.strip().split("\n"):
        # Skip header lines and separator
        if not line.strip() or line.startswith("date") or line.startswith("──"):
            continue
        # Parse the table output: columns separated by 2+ spaces
        parts = re.split(r" {2,}", line.strip())
        if len(parts) >= 4:
            messages.append({
                "date": parts[0].strip(),
                "from": parts[1].strip(),
                "id": parts[2].strip(),
                "subject": parts[3].strip(),
            })
    return messages


def gws_get_message(msg_id: str) -> dict:
    """Get full message JSON including attachment metadata."""
    cmd = [
        "gws", "gmail", "users", "messages", "get",
        "--params", json.dumps({"userId": "me", "id": msg_id}),
        "--format", "json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"  ERROR: Failed to get message {msg_id}: {result.stderr.strip()}")
        return {}
    return json.loads(result.stdout)


def gws_get_attachment(msg_id: str, attachment_id: str) -> bytes | None:
    """Download attachment and return raw bytes."""
    cmd = [
        "gws", "gmail", "users", "messages", "attachments", "get",
        "--params", json.dumps({
            "userId": "me",
            "messageId": msg_id,
            "id": attachment_id,
        }),
        "--format", "json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"  ERROR: Failed to download attachment: {result.stderr.strip()}")
        return None

    data = json.loads(result.stdout)
    b64_data = data.get("data", "")
    if not b64_data:
        return None

    # Gmail uses URL-safe base64
    return base64.urlsafe_b64decode(b64_data + "==")


def gws_modify_message(msg_id: str, add_labels: list[str], remove_labels: list[str]):
    """Add/remove labels on a message."""
    body = {}
    if add_labels:
        body["addLabelIds"] = add_labels
    if remove_labels:
        body["removeLabelIds"] = remove_labels

    cmd = [
        "gws", "gmail", "users", "messages", "modify",
        "--params", json.dumps({"userId": "me", "id": msg_id}),
        "--json", json.dumps(body),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"  ERROR: Failed to modify message {msg_id}: {result.stderr.strip()}")
        return False
    return True


def gws_create_label(label_name: str) -> str | None:
    """Create a Gmail label and return its ID."""
    cmd = [
        "gws", "gmail", "users", "labels", "create",
        "--params", json.dumps({"userId": "me"}),
        "--json", json.dumps({
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }),
        "--format", "json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"  ERROR: Failed to create label '{label_name}': {result.stderr.strip()}")
        return None
    data = json.loads(result.stdout)
    return data.get("id")


def gws_find_label_id(label_name: str) -> str | None:
    """Find a label ID by name, creating it if it doesn't exist."""
    cmd = [
        "gws", "gmail", "users", "labels", "list",
        "--params", json.dumps({"userId": "me"}),
        "--format", "json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return None

    data = json.loads(result.stdout)
    for label in data.get("labels", []):
        if label.get("name") == label_name:
            return label["id"]

    # Label doesn't exist — create it
    return gws_create_label(label_name)


def download_url(url: str) -> bytes | None:
    """Download a file from a URL and return raw bytes."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception as e:
        print(f"  ERROR: Failed to download {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# Message parsing helpers
# ---------------------------------------------------------------------------


def extract_attachments(payload: dict) -> list[dict]:
    """Recursively extract attachments from message payload.

    Returns list of {filename, attachmentId, mimeType}.
    """
    attachments = []
    filename = payload.get("filename", "")
    attachment_id = payload.get("body", {}).get("attachmentId", "")
    if filename and attachment_id:
        attachments.append({
            "filename": filename,
            "attachmentId": attachment_id,
            "mimeType": payload.get("mimeType", ""),
        })
    for part in payload.get("parts", []):
        attachments.extend(extract_attachments(part))
    return attachments


def get_header(message: dict, name: str) -> str:
    """Get a header value from a Gmail message."""
    headers = message.get("payload", {}).get("headers", [])
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------


def matches_rule(rule: dict, msg_from: str, msg_subject: str) -> bool:
    """Check if a message matches a rule's from/subject criteria."""
    # Check 'from' (exact match on email address)
    if "from" in rule:
        if rule["from"].lower() not in msg_from.lower():
            return False

    # Check 'from_contains' (partial match)
    if "from_contains" in rule:
        if rule["from_contains"].lower() not in msg_from.lower():
            return False

    # Check 'subject_contains' (None means match any)
    if rule.get("subject_contains") is not None:
        if rule["subject_contains"].lower() not in msg_subject.lower():
            return False

    return True


def build_gmail_query(rule: dict, since: str) -> str:
    """Build a Gmail search query for a rule.

    Note: subject_contains is used for post-filtering only (not in Gmail query),
    because Gmail's subject: operator requires exact phrase matching which is
    too strict for subjects like "Office Club | Your invoice".
    """
    parts = [f"after:{since}"]
    if not rule.get("link_download") and not rule.get("manual_portal"):
        parts.append("has:attachment")

    if "from" in rule:
        parts.append(f"from:{rule['from']}")
    elif "from_contains" in rule:
        parts.append(f"from:{rule['from_contains']}")

    # Don't add subject to Gmail query — use post-filtering in matches_rule()

    return " ".join(parts)


def compute_filename(rule: dict, original_filename: str, subject: str) -> str:
    """Determine the final filename for an attachment."""
    if "rename_from_subject" in rule:
        m = re.search(rule["rename_from_subject"], subject)
        if m:
            extracted = m.group(1)
            # If there's a rename_template, use it (e.g., REWE-eBon-{}.pdf)
            if "rename_template" in rule:
                return rule["rename_template"].format(extracted)
            # For Stripe receipts: prefix with receipt ID but keep Invoice/Receipt distinction
            # e.g., "Invoice-651E04EB-0018.pdf" → "2524-4832-1860-Invoice.pdf"
            #        "Receipt-2524-4832-1860.pdf" → "2524-4832-1860-Receipt.pdf"
            prefix = ""
            name_lower = original_filename.lower()
            if "invoice" in name_lower:
                prefix = "Invoice"
            elif "receipt" in name_lower:
                prefix = "Receipt"
            if prefix:
                return f"{extracted}-{prefix}.pdf"
            return f"{extracted}.pdf"

    # Otherwise keep original filename
    return original_filename


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


def load_state(state_file: Path) -> dict:
    """Load processed message IDs from state file."""
    if state_file.exists():
        with open(state_file) as f:
            return json.load(f)
    return {"processed_ids": [], "last_run": None}


def save_state(state: dict, state_file: Path):
    """Save state to file."""
    state["last_run"] = datetime.now().strftime("%Y-%m-%d")
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Download handlers
# ---------------------------------------------------------------------------


def _ensure_dest_dir(rule: dict, dest_dir: Path) -> bool:
    """Ensure destination directory exists. Returns True if OK."""
    if dest_dir.exists():
        return True
    if rule.get("create_folder"):
        dest_dir.mkdir(parents=True, exist_ok=True)
        print(f"    Created folder: {dest_dir}")
        return True
    print(f"    ERROR: Destination folder does not exist: {dest_dir}")
    return False


def _process_attachment_download(rule: dict, full_msg: dict, msg_id: str,
                                  subject: str, dest_dir: Path,
                                  execute: bool) -> int:
    """Download attachments from a Gmail message. Returns count."""
    attachments = extract_attachments(full_msg.get("payload", {}))
    att_filter = rule.get("attachment_filter", r"\.pdf$")
    matched = [a for a in attachments
               if re.search(att_filter, a["filename"], re.IGNORECASE)]

    if not matched:
        print("    No matching attachments found.")
        return 0

    count = 0
    for att in matched:
        filename = compute_filename(rule, att["filename"], subject)
        dest_path = dest_dir / filename

        print(f"    Attachment: {att['filename']}", end="")
        if filename != att["filename"]:
            print(f" → {filename}", end="")
        print()
        print(f"    Destination: {dest_path}")

        if dest_path.exists():
            print(f"    SKIP: File already exists on disk")
        elif execute:
            if not _ensure_dest_dir(rule, dest_dir):
                continue
            data = gws_get_attachment(msg_id, att["attachmentId"])
            if data is None:
                print("    ERROR: Failed to download attachment")
                continue
            with open(dest_path, "wb") as f:
                f.write(data)
            print(f"    SAVED: {dest_path} ({len(data):,} bytes)")
            count += 1
        else:
            print(f"    DRY-RUN: Would download and save ({att.get('mimeType', 'unknown')})")
            count += 1
    return count


def _get_html_body(payload: dict) -> str:
    """Extract HTML body from Gmail message payload."""
    mime = payload.get("mimeType", "")
    if mime == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = _get_html_body(part)
        if result:
            return result
    return ""


def _get_text_body(payload: dict) -> str:
    """Extract plain text body from Gmail message payload."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = _get_text_body(part)
        if result:
            return result
    return ""


def _process_link_download(rule: dict, full_msg: dict, msg_id: str,
                            subject: str, dest_dir: Path,
                            execute: bool, state: dict) -> int:
    """Download PDF via link found in email body. Returns count."""
    html_body = _get_html_body(full_msg.get("payload", {}))
    text_body = _get_text_body(full_msg.get("payload", {}))

    # Find the download URL in HTML body
    link_pattern = rule.get("link_pattern", "")
    urls = re.findall(link_pattern, html_body)
    if not urls:
        print("    No download link found in email.")
        return 0

    pdf_url = urls[0]
    print(f"    Link: {pdf_url[:80]}...")

    # Determine filename
    filename = None
    if "filename_from_body" in rule:
        # Search both text and HTML bodies
        for body in [text_body, html_body]:
            m = re.search(rule["filename_from_body"], body)
            if m:
                extracted = m.group(1)
                filename = rule.get("filename_template", "{}.pdf").format(extracted)
                break

    if not filename:
        # Fallback: use message date + rule name
        msg_date = get_header(full_msg, "Date")
        date_match = re.search(r"(\d{1,2})\s+(\w{3})\s+(\d{4})", msg_date)
        if date_match:
            filename = f"{rule['name']}-{date_match.group(3)}{date_match.group(2)}{date_match.group(1)}.pdf"
        else:
            filename = f"{rule['name']}-{msg_id}.pdf"

    dest_path = dest_dir / filename
    print(f"    Filename: {filename}")
    print(f"    Destination: {dest_path}")

    if dest_path.exists():
        print(f"    SKIP: File already exists on disk")
        return 0

    if execute:
        if not _ensure_dest_dir(rule, dest_dir):
            return 0
        data = download_url(pdf_url)
        if data is None:
            return 0
        with open(dest_path, "wb") as f:
            f.write(data)
        print(f"    SAVED: {dest_path} ({len(data):,} bytes)")
        return 1
    else:
        print(f"    DRY-RUN: Would download PDF from link")
        return 1


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------


def process_rule(rule: dict, since: str, execute: bool, state: dict,
                 archive_label_id: str | None, base_dir: Path,
                 manual_pending: list | None = None) -> int:
    """Process a single rule. Returns number of attachments handled."""
    print(f"\n{'='*60}")
    print(f"Rule: {rule['name']}")
    print(f"{'='*60}")

    query = build_gmail_query(rule, since)
    print(f"  Query: {query}")

    messages = gws_triage(query)
    if not messages:
        print("  No messages found.")
        return 0

    print(f"  Found {len(messages)} message(s)")
    count = 0
    dest_dir = base_dir / rule["destination"]

    for msg in messages:
        msg_id = msg["id"]

        # Skip already processed
        if msg_id in state["processed_ids"]:
            continue

        # Double-check rule match (triage query is broad, verify subject)
        if not matches_rule(rule, msg["from"], msg["subject"]):
            continue

        print(f"\n  Message: {msg['subject'][:70]}")
        print(f"    From: {msg['from']}")
        print(f"    Date: {msg['date']}")
        print(f"    ID:   {msg_id}")

        # Get full message
        full_msg = gws_get_message(msg_id)
        if not full_msg:
            continue

        subject = get_header(full_msg, "Subject")

        if rule.get("manual_portal"):
            # --- Manual portal: collect for end-of-run summary ---
            manual_pending.append({
                "rule_name": rule["name"],
                "portal_url": rule.get("portal_url", ""),
                "subject": subject,
                "date": msg["date"],
                "msg_id": msg_id,
            })
            print(f"    Portal login required — will prompt at end of run")
            continue  # skip label/archive until user confirms
        elif rule.get("link_download"):
            # --- Link-based download: extract URL from HTML email body ---
            count += _process_link_download(
                rule, full_msg, msg_id, subject, dest_dir, execute, state,
            )
        else:
            # --- Standard attachment download ---
            count += _process_attachment_download(
                rule, full_msg, msg_id, subject, dest_dir, execute,
            )

        # Label + archive + mark as read
        if execute and archive_label_id:
            if gws_modify_message(msg_id, [archive_label_id], ["INBOX", "UNREAD"]):
                print(f"    Labeled + archived + marked as read")
            else:
                print(f"    WARNING: Failed to label/archive email")

        # Mark as processed (only in execute mode)
        if execute and msg_id not in state["processed_ids"]:
            state["processed_ids"].append(msg_id)

    return count


def cmd_list_rules():
    """List all rules and exit."""
    print(f"{'#':<3} {'Name':<25} {'Destination':<40}")
    print(f"{'-'*3} {'-'*25} {'-'*40}")
    for i, rule in enumerate(RULES, 1):
        print(f"{i:<3} {rule['name']:<25} {rule['destination']:<40}")


def cmd_run(args):
    """Run the archiver."""
    # Determine working folder
    if args.folder:
        working_folder = Path(args.folder).expanduser().resolve()
    else:
        default = str(DEFAULT_FOLDER)
        sys.stdout.write(f"Working folder [{default}]: ")
        sys.stdout.flush()
        user_input = input().strip()
        if user_input:
            working_folder = Path(user_input).expanduser().resolve()
        else:
            working_folder = DEFAULT_FOLDER

    base_dir = working_folder / "Deutschland"
    state_file = working_folder / ".archiver-state.json"

    if not working_folder.exists():
        print(f"ERROR: Working folder does not exist: {working_folder}")
        sys.exit(1)

    # Determine since date
    state = load_state(state_file)
    if args.since:
        since = args.since.replace("-", "/")
    elif state.get("last_run"):
        since = state["last_run"].replace("-", "/")
    else:
        since = (datetime.now() - timedelta(days=DEFAULT_SINCE_DAYS)).strftime("%Y/%m/%d")

    print(f"Gmail Attachment Archiver")
    print(f"Since: {since}")
    print(f"Base:  {base_dir}")

    # Get or create archive label
    archive_label_id = gws_find_label_id(ARCHIVE_LABEL_NAME)
    if archive_label_id:
        print(f"Archive label: {ARCHIVE_LABEL_NAME} (id: {archive_label_id})")
    else:
        print(f"WARNING: Could not find/create label '{ARCHIVE_LABEL_NAME}'")

    # Filter rules if --rule specified
    rules = RULES
    if args.rule:
        rules = [r for r in RULES if r["name"].lower() == args.rule.lower()]
        if not rules:
            print(f"ERROR: No rule named '{args.rule}'. Use 'list-rules' to see available rules.")
            sys.exit(1)

    # Process each rule
    total = 0
    manual_pending = []
    for rule in rules:
        total += process_rule(rule, since, True, state, archive_label_id,
                              base_dir, manual_pending)

    # Save state
    save_state(state, state_file)
    print(f"\nState saved to {state_file}")

    print(f"\n{'='*60}")
    print(f"Total attachments processed: {total}")
    print(f"{'='*60}")

    # Manual portal summary
    if manual_pending:
        # Group by portal
        portals: dict[str, list] = {}
        for item in manual_pending:
            key = item["rule_name"]
            portals.setdefault(key, []).append(item)

        print(f"\n{'='*60}")
        print(f"MANUAL DOWNLOADS NEEDED")
        print(f"{'='*60}")

        for portal_name, items in portals.items():
            url = items[0]["portal_url"]
            print(f"\n  {portal_name} ({len(items)} new)")
            print(f"  Login: {url}")
            for item in items:
                print(f"    - {item['date']}: {item['subject'][:60]}")

            sys.stdout.write(f"\n  Fetched manually from {portal_name}? [y/N] ")
            sys.stdout.flush()
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                ch = sys.stdin.read(1).lower()
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            print(ch)  # echo the keypress
            if ch == "y":
                for item in items:
                    msg_id = item["msg_id"]
                    if archive_label_id:
                        gws_modify_message(msg_id, [archive_label_id], ["INBOX", "UNREAD"])
                    if msg_id not in state["processed_ids"]:
                        state["processed_ids"].append(msg_id)
                print(f"    Marked {len(items)} email(s) as Stored")
                save_state(state, state_file)
            else:
                print(f"    Skipped — will prompt again next run")


def main():
    parser = argparse.ArgumentParser(
        description="Gmail Attachment Auto-Archiver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    # run
    run_parser = subparsers.add_parser("run", help="Download attachments and archive emails")
    run_parser.add_argument(
        "--since",
        help="Start date in YYYY-MM-DD or YYYY/M/D format (default: from state or 45 days ago)",
    )
    run_parser.add_argument(
        "--rule",
        help="Run only this rule (by name)",
    )
    run_parser.add_argument(
        "--folder",
        help=f"Working folder (default: {DEFAULT_FOLDER})",
    )

    # list-rules
    subparsers.add_parser("list-rules", help="List all rules")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "list-rules":
        cmd_list_rules()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
