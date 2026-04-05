#!/usr/bin/env python3
"""Gmail Attachment Auto-Archiver.

Queries Gmail for known recurring senders, downloads attachments,
files them into the correct folder, and labels+archives the email.

Usage:
    python3 archive_gmail.py run                      # download & archive
    python3 archive_gmail.py run --rule "Office Club"  # one rule only
    python3 archive_gmail.py run --since 2026-03-01    # override start date
    python3 archive_gmail.py run --folder ~/my/archive # custom working folder
    python3 archive_gmail.py run --force               # ignore stored state
    python3 archive_gmail.py list-rules                # show all rules
    python3 archive_gmail.py scan-inbox                # classify inbox files
    python3 archive_gmail.py scan-inbox --move         # classify and move
    python3 archive_gmail.py scan-inbox --inbox ~/path # custom inbox folder
"""

import argparse
import base64
import json
import os
import re
import shutil
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

CONFIG_DIR = Path.home() / ".config" / "archive-gmail"
CONFIG_FILE = CONFIG_DIR / "rules.json"


def _load_config() -> dict:
    """Load rules from ~/.config/archive-gmail/rules.json."""
    if not CONFIG_FILE.exists():
        print(f"ERROR: Config file not found: {CONFIG_FILE}")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def _get_rules() -> list[dict]:
    return _load_config()["rules"]


def _get_folder_keywords() -> dict[str, list[str]]:
    return _load_config().get("folder_keywords", {})

# ---------------------------------------------------------------------------
# gws CLI wrappers
# ---------------------------------------------------------------------------


def gws_check_auth():
    """Verify gws Gmail authentication works. Exit with a clear message if not."""
    cmd = [
        "gws", "gmail", "users", "labels", "list",
        "--params", json.dumps({"userId": "me"}),
        "--format", "json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        print(f"ERROR: gws authentication failed.")
        print(f"  {stderr}")
        print(f"\nRun 'gws auth login' to authenticate.")
        sys.exit(1)


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


DOWNLOADS_DIR = Path.home() / "Downloads"


def _read_single_key() -> str:
    """Read a single keypress without requiring Enter."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1).lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


def _scan_downloads_recent(extensions: tuple = (".pdf",),
                           max_age_minutes: int = 90) -> list[dict]:
    """Scan ~/Downloads for recently created files.

    Returns files matching the extension created within the last max_age_minutes,
    sorted newest-first.
    """
    if not DOWNLOADS_DIR.exists():
        return []

    cutoff = datetime.now() - timedelta(minutes=max_age_minutes)
    candidates = []
    for f in DOWNLOADS_DIR.iterdir():
        if not f.is_file():
            continue
        if not any(f.name.lower().endswith(ext) for ext in extensions):
            continue
        stat = f.stat()
        created = datetime.fromtimestamp(
            getattr(stat, "st_birthtime", stat.st_mtime)
        )
        if created >= cutoff:
            candidates.append({
                "path": f,
                "created": created,
                "size": stat.st_size,
            })

    candidates.sort(key=lambda c: c["created"], reverse=True)
    return candidates


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
                 manual_pending: list | None = None,
                 force: bool = False) -> int:
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

        # Skip already processed (unless --force)
        if not force and msg_id in state["processed_ids"]:
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
                "destination": rule["destination"],
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
    for i, rule in enumerate(_get_rules(), 1):
        print(f"{i:<3} {rule['name']:<25} {rule['destination']:<40}")


# ---------------------------------------------------------------------------
# Inbox scanner — classify files by PDF text content
# ---------------------------------------------------------------------------

INBOX_DEFAULT = Path.home() / "Documents" / "Archiwum dokumentów" / "### Inbox"
SUPPORTED_EXTENSIONS = {".pdf"}


def extract_pdf_text(path: Path, max_pages: int = 2) -> str:
    """Extract text from the first pages of a PDF using pdftotext."""
    try:
        result = subprocess.run(
            ["pdftotext", "-l", str(max_pages), str(path), "-"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout if result.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _build_keyword_index() -> list[tuple[str, list[str]]]:
    """Build (destination, keywords) pairs from rules + folder_keywords."""
    seen = set()
    index = []
    for rule in _get_rules():
        kws = rule.get("keywords", [])
        if kws and rule["destination"] not in seen:
            index.append((rule["destination"], kws))
            seen.add(rule["destination"])
    for dest, kws in _get_folder_keywords().items():
        if dest not in seen:
            index.append((dest, kws))
            seen.add(dest)
    return index


def _keyword_matches(keyword: str, text_lower: str) -> bool:
    """Check if keyword matches in text. Short keywords (<=4 chars) use
    word-boundary matching to avoid substring false positives."""
    kw_lower = keyword.lower()
    if len(keyword) <= 4:
        return bool(re.search(r'\b' + re.escape(kw_lower) + r'\b', text_lower))
    return kw_lower in text_lower


def classify_file(path: Path, keyword_index: list[tuple[str, list[str]]],
                  ) -> list[tuple[str, int, list[str]]]:
    """Score a file against all keyword sets.

    Returns list of (destination, score, matched_keywords) sorted by score desc.
    """
    text = extract_pdf_text(path)
    if not text:
        return []

    text_lower = text.lower()
    matches = []
    for dest, keywords in keyword_index:
        matched = [kw for kw in keywords if _keyword_matches(kw, text_lower)]
        if matched:
            matches.append((dest, len(matched), matched))

    matches.sort(key=lambda m: m[1], reverse=True)
    return matches


def cmd_scan_inbox(args):
    """Scan inbox folder and classify files by content."""
    inbox = Path(args.inbox).expanduser().resolve() if args.inbox else INBOX_DEFAULT

    if args.folder:
        base_dir = Path(args.folder).expanduser().resolve() / "Deutschland"
    else:
        base_dir = DEFAULT_FOLDER / "Deutschland"

    if not inbox.exists():
        print(f"ERROR: Inbox folder does not exist: {inbox}")
        sys.exit(1)

    print(f"Inbox Scanner")
    print(f"Inbox: {inbox}")
    print(f"Base:  {base_dir}")

    keyword_index = _build_keyword_index()
    print(f"Loaded {len(keyword_index)} keyword targets\n")

    # Collect files (skip directories)
    files = sorted(
        f for f in inbox.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    other_files = sorted(
        f for f in inbox.iterdir()
        if f.is_file() and f.suffix.lower() not in SUPPORTED_EXTENSIONS
    )

    if not files:
        print("No supported files found in inbox.")
        if other_files:
            print(f"\nSkipped {len(other_files)} non-PDF file(s):")
            for f in other_files:
                print(f"  {f.name}")
        return

    matched_files = []
    unmatched_files = []

    for f in files:
        results = classify_file(f, keyword_index)
        if results:
            matched_files.append((f, results))
        else:
            unmatched_files.append(f)

    # Show matched files
    if matched_files:
        print(f"{'='*60}")
        print(f"MATCHED ({len(matched_files)} files)")
        print(f"{'='*60}")

        for f, results in matched_files:
            best_dest, best_score, best_kws = results[0]
            confidence = "HIGH" if best_score >= 2 else "LOW"
            print(f"\n  {f.name}")
            print(f"    → {best_dest}  [{confidence}, {best_score} keyword(s): {', '.join(best_kws)}]")

            if len(results) > 1:
                for dest, score, kws in results[1:3]:
                    print(f"      also: {dest}  [{score}: {', '.join(kws)}]")

            if args.move:
                dest_dir = base_dir / best_dest
                dest_path = dest_dir / f.name

                if confidence == "HIGH":
                    sys.stdout.write(f"    Move? [Y/n/d(est)] ")
                else:
                    sys.stdout.write(f"    Move? [y/N/d(est)] ")
                sys.stdout.flush()
                ch = _read_single_key()
                print(ch)

                if ch == "d":
                    # Let user type a custom destination
                    sys.stdout.write(f"    Destination (relative to {base_dir}): ")
                    sys.stdout.flush()
                    custom = input().strip()
                    if custom:
                        dest_dir = base_dir / custom
                        dest_path = dest_dir / f.name

                    do_move = True
                elif confidence == "HIGH":
                    do_move = ch != "n"
                else:
                    do_move = ch == "y"

                if do_move:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(f), str(dest_path))
                    print(f"    MOVED → {dest_path}")
                else:
                    print(f"    Skipped")

    # Show unmatched files
    if unmatched_files:
        print(f"\n{'='*60}")
        print(f"UNMATCHED ({len(unmatched_files)} files)")
        print(f"{'='*60}")
        for f in unmatched_files:
            text = extract_pdf_text(f)
            first_lines = [l.strip() for l in text.split("\n") if l.strip()][:3]
            print(f"\n  {f.name}")
            if first_lines:
                for line in first_lines:
                    print(f"    | {line[:80]}")
            else:
                print(f"    (no text extracted)")

            # Unmatched files are left in place — add keywords to config to match them



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

    # Verify gws is authenticated before doing any work
    gws_check_auth()

    # Get or create archive label
    archive_label_id = gws_find_label_id(ARCHIVE_LABEL_NAME)
    if archive_label_id:
        print(f"Archive label: {ARCHIVE_LABEL_NAME} (id: {archive_label_id})")
    else:
        print(f"WARNING: Could not find/create label '{ARCHIVE_LABEL_NAME}'")

    # Filter rules if --rule specified
    all_rules = _get_rules()
    rules = all_rules
    if args.rule:
        rules = [r for r in all_rules if r["name"].lower() == args.rule.lower()]
        if not rules:
            print(f"ERROR: No rule named '{args.rule}'. Use 'list-rules' to see available rules.")
            sys.exit(1)

    # Process each rule
    total = 0
    manual_pending = []
    for rule in rules:
        total += process_rule(rule, since, True, state, archive_label_id,
                              base_dir, manual_pending, force=args.force)

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
            dest_dir = base_dir / items[0]["destination"]
            print(f"\n  {portal_name} ({len(items)} new)")
            print(f"  Login: {url}")
            print(f"  Dest:  {dest_dir}")
            for item in items:
                print(f"    - {item['date']}: {item['subject'][:60]}")

            # Ask user to download from portal first
            sys.stdout.write(f"\n  Download from {portal_name} now, press any key when done (s to skip): ")
            sys.stdout.flush()
            ch = _read_single_key()
            print(ch)

            if ch == "s":
                print(f"    Skipped — will prompt again next run")
                continue

            # Scan ~/Downloads for recently created PDFs
            candidates = _scan_downloads_recent()

            if candidates:
                print(f"\n  Found {len(candidates)} recent PDF(s) in ~/Downloads:")
                moved_any = False
                for i, c in enumerate(candidates):
                    created_str = c["created"].strftime("%H:%M:%S")
                    size_kb = c["size"] / 1024
                    print(f"    [{i+1}] {c['path'].name}  ({created_str}, {size_kb:,.0f} KB)")

                    sys.stdout.write(f"        Move to \"{dest_dir}\"? [Y/n] ")
                    sys.stdout.flush()
                    ch = _read_single_key()
                    print(ch)

                    if ch != "n":
                        if not dest_dir.exists():
                            dest_dir.mkdir(parents=True, exist_ok=True)
                            print(f"        Created folder: {dest_dir}")
                        dest_path = dest_dir / c["path"].name
                        shutil.move(str(c["path"]), str(dest_path))
                        print(f"        MOVED → {dest_path}")
                        moved_any = True

                if moved_any:
                    for item in items:
                        msg_id = item["msg_id"]
                        if archive_label_id:
                            gws_modify_message(msg_id, [archive_label_id], ["INBOX", "UNREAD"])
                        if msg_id not in state["processed_ids"]:
                            state["processed_ids"].append(msg_id)
                    print(f"    Marked {len(items)} email(s) as Stored")
                    save_state(state, state_file)
                else:
                    print(f"    No files moved — will prompt again next run")
            else:
                print(f"    No recent PDFs found in ~/Downloads — will prompt again next run")


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
    run_parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore stored state — reprocess all matching messages",
    )

    # list-rules
    subparsers.add_parser("list-rules", help="List all rules")

    # scan-inbox
    scan_parser = subparsers.add_parser("scan-inbox", help="Classify inbox files by content")
    scan_parser.add_argument(
        "--inbox",
        help=f"Inbox folder to scan (default: {INBOX_DEFAULT})",
    )
    scan_parser.add_argument(
        "--folder",
        help=f"Archive working folder (default: {DEFAULT_FOLDER})",
    )
    scan_parser.add_argument(
        "--move",
        action="store_true",
        help="Interactively move matched files to destinations",
    )

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "list-rules":
        cmd_list_rules()
    elif args.command == "scan-inbox":
        cmd_scan_inbox(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
