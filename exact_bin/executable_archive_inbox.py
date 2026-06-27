#!/usr/bin/env python3
"""Archive documents from Gmail, link downloads, portals, and local inbox.

Sources:
  - Gmail attachments (rules match sender/subject)
  - Link-based PDF downloads (extract URL from email body)
  - Manual portal downloads (prompt user, scan ~/Downloads)
  - Unknown senders (prompt to save + auto-add a rule, or ignore the sender)
  - Local inbox scanning (classify files by PDF text content)

Usage:
    python3 archive_inbox.py gmail                     # download & archive
    python3 archive_inbox.py gmail --rule "Office Club" # one rule only
    python3 archive_inbox.py gmail --since 2026-03-01   # override start date
    python3 archive_inbox.py gmail --folder ~/my/archive # custom working folder
    python3 archive_inbox.py gmail --force              # ignore stored state
    python3 archive_inbox.py gmail --no-discover        # skip unknown-sender prompts
    python3 archive_inbox.py list-rules                 # show all rules
    python3 archive_inbox.py folder                     # classify inbox files
    python3 archive_inbox.py folder --move              # classify and move
    python3 archive_inbox.py folder ~/path              # custom inbox folder
"""

import argparse
import base64
import concurrent.futures
import io
import json
import threading
import os
import re
import shutil
import subprocess
import sys
import tempfile
import termios
import tty
import urllib.request
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime, parseaddr
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_FOLDER = Path.home() / "Documents" / "Archiwum"
ARCHIVE_LABEL_NAME = "Stored"  # Gmail label applied after archiving
DEFAULT_SINCE_DAYS = 45  # look back ~6 weeks on first run

CONFIG_DIR = Path.home() / ".config" / "archive-inbox"
CONFIG_FILE = CONFIG_DIR / "rules.json"

VERBOSE = False
DEBUG = False

# Per-thread log sink: buffers verbose output during parallel triage so each
# rule's output can be flushed in order afterward.
_tls = threading.local()


def _log_stream():
    """Return the current verbose log stream (thread-local buffer or stderr)."""
    return getattr(_tls, "buffer", None) or sys.stderr


def _shlex_join(cmd: list[str]) -> str:
    import shlex

    return " ".join(shlex.quote(c) for c in cmd)


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Run a subprocess, logging the command and output when VERBOSE or DEBUG."""
    out = _log_stream()
    if VERBOSE or DEBUG:
        print(f"  $ {_shlex_join(cmd)}", file=out)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if DEBUG:
        print(f"  → exit={result.returncode}", file=out)
        if result.stdout:
            for line in result.stdout.rstrip("\n").split("\n"):
                print(f"    stdout: {line}", file=out)
        if result.stderr:
            for line in result.stderr.rstrip("\n").split("\n"):
                print(f"    stderr: {line}", file=out)
    elif VERBOSE:
        if result.returncode != 0:
            print(f"  → exit={result.returncode}", file=out)
            if result.stdout:
                for line in result.stdout.rstrip("\n").split("\n"):
                    print(f"    stdout: {line}", file=out)
            if result.stderr:
                for line in result.stderr.rstrip("\n").split("\n"):
                    print(f"    stderr: {line}", file=out)
    return result


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


def _get_filename_rules() -> list[dict]:
    """Return filename_rules from config: [{pattern, destination}, ...]."""
    return _load_config().get("filename_rules", [])


def _get_ignore_senders() -> list[str]:
    """Return ignore_senders: From substrings skipped during discovery."""
    return _load_config().get("ignore_senders", [])


def _save_config(config: dict) -> None:
    """Write the full config back to rules.json, preserving non-ASCII text."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------------------
# Gmail API wrappers (via gws CLI)
# ---------------------------------------------------------------------------


def gws_check_auth():
    """Verify gws Gmail authentication works. Attempt to login if not authenticated."""
    cmd = [
        "gws",
        "gmail",
        "users",
        "labels",
        "list",
        "--params",
        json.dumps({"userId": "me"}),
    ]
    result = _run(cmd, timeout=30)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        print(f"gws authentication failed. Running 'gws auth login'...")
        if stderr:
            print(f"  {stderr}")
        # Inherit stdio so the user can interact with scope selection and the
        # browser-auth URL prompt. capture_output would hide both.
        login_rc = subprocess.run(["gws", "auth", "login"]).returncode
        if login_rc != 0:
            print(f"ERROR: gws auth login failed (exit {login_rc}).")
            sys.exit(1)
        print("gws auth login completed. Retrying...")
        result = _run(cmd, timeout=30)
        if result.returncode != 0:
            print(f"ERROR: gws authentication still failed after login.")
            print(f"  {result.stderr.strip()}")
            sys.exit(1)


def gws_triage(query: str, max_results: int = 100) -> list[dict]:
    """Run gws gmail +triage and return list of {id, from, subject, date}."""
    cmd = [
        "gws",
        "gmail",
        "+triage",
        "--query",
        query,
        "--max",
        str(max_results),
        "--format",
        "json",
    ]
    result = _run(cmd, timeout=120)
    if result.returncode != 0:
        return []

    if not result.stdout.strip():
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        if VERBOSE:
            print(
                f"  WARNING: gws +triage returned non-JSON output (first 200 chars): {result.stdout[:200]}",
                file=_log_stream(),
            )
        return []
    items = data if isinstance(data, list) else data.get("messages", [])
    return [
        {
            "date": str(item.get("date", "")).strip(),
            "from": str(item.get("from", "")).strip(),
            "id": str(item.get("id", "")).strip(),
            "subject": str(item.get("subject", "")).strip(),
        }
        for item in items
        if item.get("id")
    ]


def gws_get_message(msg_id: str) -> dict:
    """Get full message JSON including attachment metadata."""
    cmd = [
        "gws",
        "gmail",
        "users",
        "messages",
        "get",
        "--params",
        json.dumps({"userId": "me", "id": msg_id}),
        "--format",
        "json",
    ]
    result = _run(cmd, timeout=60)
    if result.returncode != 0:
        print(f"  ERROR: Failed to get message {msg_id}: {result.stderr.strip()}")
        return {}
    return json.loads(result.stdout)


def gws_get_attachment(msg_id: str, attachment_id: str) -> bytes | None:
    """Download attachment and return raw bytes."""
    cmd = [
        "gws",
        "gmail",
        "users",
        "messages",
        "attachments",
        "get",
        "--params",
        json.dumps(
            {
                "userId": "me",
                "messageId": msg_id,
                "id": attachment_id,
            }
        ),
        "--format",
        "json",
    ]
    result = _run(cmd, timeout=120)
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
        "gws",
        "gmail",
        "users",
        "messages",
        "modify",
        "--params",
        json.dumps({"userId": "me", "id": msg_id}),
        "--json",
        json.dumps(body),
        "--format",
        "json",
    ]
    result = _run(cmd, timeout=30)
    if result.returncode != 0:
        print(f"  ERROR: Failed to modify message {msg_id}: {result.stderr.strip()}")
        return False
    data = json.loads(result.stdout)
    got = set(data.get("labelIds", []))
    expected_add = set(add_labels or [])
    expected_remove = set(remove_labels or [])
    missing = expected_add - got
    if missing:
        print(
            f"  WARNING: modify returned OK but addLabelIds {missing} not in labelIds {got}"
        )
        return False
    still_present = expected_remove & got
    if still_present:
        print(
            f"  WARNING: modify returned OK but removeLabelIds {still_present} still in labelIds {got}"
        )
        return False
    return True


def gws_create_label(label_name: str) -> str | None:
    """Create a Gmail label and return its ID."""
    cmd = [
        "gws",
        "gmail",
        "users",
        "labels",
        "create",
        "--params",
        json.dumps({"userId": "me"}),
        "--json",
        json.dumps(
            {
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            }
        ),
        "--format",
        "json",
    ]
    result = _run(cmd, timeout=30)
    if result.returncode != 0:
        print(
            f"  ERROR: Failed to create label '{label_name}': {result.stderr.strip()}"
        )
        return None
    data = json.loads(result.stdout)
    return data.get("id")


def gws_find_label_id(label_name: str) -> str | None:
    """Find a label ID by name, creating it if it doesn't exist."""
    cmd = [
        "gws",
        "gmail",
        "users",
        "labels",
        "list",
        "--params",
        json.dumps({"userId": "me"}),
        "--format",
        "json",
    ]
    result = _run(cmd, timeout=30)
    if result.returncode != 0:
        print(f"  ERROR: Failed to list labels: {result.stderr.strip()}")
        return None

    data = json.loads(result.stdout)
    for label in data.get("labels", []):
        if label.get("name") == label_name:
            return label["id"]

    # Label doesn't exist — create it
    return gws_create_label(label_name)


def download_url(url: str) -> bytes | None:
    """Download a file from a URL and return raw bytes."""
    out = _log_stream()
    if VERBOSE:
        print(f"  GET {url}", file=out)
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        if VERBOSE:
            print(f"  → status=200 bytes={len(data):,}", file=out)
        return data
    except Exception as e:
        if VERBOSE:
            print(f"  → error: {e}", file=out)
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
        attachments.append(
            {
                "filename": filename,
                "attachmentId": attachment_id,
                "mimeType": payload.get("mimeType", ""),
            }
        )
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


def _from_matches(rule: dict, msg_from: str) -> bool:
    """True if From matches the rule's sender criteria (subject ignored)."""
    # 'from': substring match on the email address.
    if "from" in rule and rule["from"].lower() not in msg_from.lower():
        return False

    # 'from_contains': regex or list of regexes, OR logic.
    if "from_contains" in rule:
        patterns = rule["from_contains"]
        if isinstance(patterns, str):
            patterns = [patterns]
        if not any(re.search(p, msg_from, re.IGNORECASE) for p in patterns):
            return False

    return True


def matches_rule(rule: dict, msg_from: str, msg_subject: str) -> bool:
    """Check if a message matches a rule's from/subject criteria."""
    if not _from_matches(rule, msg_from):
        return False

    # Check 'subject_regex' (None means match any).
    # Case-insensitive regex applied to the full subject.
    if rule.get("subject_regex") is not None:
        if not re.search(rule["subject_regex"], msg_subject, re.IGNORECASE):
            return False

    return True


def _bare_email(msg_from: str) -> str:
    """Extract the bare, lowercased email address from a From header."""
    return parseaddr(msg_from)[1].strip().lower()


def _is_ignored(msg_from: str, ignore_senders: list[str]) -> bool:
    """True if any ignore entry is a substring of the From header."""
    low = msg_from.lower()
    return any(ig.lower() in low for ig in ignore_senders if ig)


def _derive_rule_name(msg_from: str, existing_names: set[str]) -> str:
    """Pick a unique, human-readable rule name from a From header."""
    real, addr = parseaddr(msg_from)
    base = real.strip()
    if not base and "@" in addr:
        base = addr.split("@")[1].split(".")[0]
    base = re.sub(r"[^\w .&-]", "", base).strip()[:30] or "Unknown"
    name = base
    n = 2
    while name in existing_names:
        name = f"{base} {n}"
        n += 1
    return name


def build_gmail_query(rule: dict, since: str, force: bool = False) -> str:
    """Build a Gmail search query for a rule.

    Note: subject_regex is used for post-filtering only (not in Gmail query),
    because Gmail's subject: operator requires exact phrase matching which is
    too strict for subjects like "Office Club | Your invoice".
    """
    parts = [f"after:{since}"]
    if not rule.get("link_download") and not rule.get("manual_portal"):
        parts.append("has:attachment")

    if "from" in rule:
        parts.append(f"from:{rule['from']}")
    elif "from_contains" in rule and isinstance(rule["from_contains"], str):
        parts.append(f"from:{rule['from_contains']}")

    # Exclude already-archived messages (server-side filtering).
    # With --force, don't exclude so we can reprocess.
    if not force:
        parts.append(f"-label:{ARCHIVE_LABEL_NAME}")

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
            state = json.load(f)
    else:
        state = {}
    state.setdefault("processed_ids", [])
    state.setdefault("last_run", None)
    # pending: list of {"msg_id": ..., "date": "YYYY-MM-DD"} entries for
    # messages that had a transient failure and should be retried.
    state.setdefault("pending", [])
    return state


def _msg_date_iso(msg_date: str) -> str | None:
    """Parse an RFC2822 Date header into YYYY-MM-DD, or None on failure."""
    try:
        return parsedate_to_datetime(msg_date).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _add_pending(state: dict, msg_id: str, msg_date: str) -> None:
    """Record a message as pending retry. Deduped by msg_id."""
    date_iso = _msg_date_iso(msg_date) or datetime.now().strftime("%Y-%m-%d")
    state["pending"] = [
        p for p in state.get("pending", []) if p.get("msg_id") != msg_id
    ]
    state["pending"].append({"msg_id": msg_id, "date": date_iso})


def _clear_pending(state: dict, msg_id: str) -> None:
    """Remove a message from the pending-retry list, if present."""
    if not state.get("pending"):
        return
    state["pending"] = [p for p in state["pending"] if p.get("msg_id") != msg_id]


def _oldest_pending_date(state: dict) -> str | None:
    """Return the earliest pending date as YYYY/MM/DD, or None."""
    pending = state.get("pending") or []
    dates = [p.get("date") for p in pending if p.get("date")]
    if not dates:
        return None
    return min(dates).replace("-", "/")


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


def _scan_downloads_recent(
    extensions: tuple = (".pdf",), max_age_minutes: int = 90
) -> list[dict]:
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
        created = datetime.fromtimestamp(getattr(stat, "st_birthtime", stat.st_mtime))
        if created >= cutoff:
            candidates.append(
                {
                    "path": f,
                    "created": created,
                    "size": stat.st_size,
                }
            )

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


def _process_attachment_download(
    rule: dict, full_msg: dict, msg_id: str, subject: str, dest_dir: Path, execute: bool
) -> tuple[int, bool]:
    """Download attachments from a Gmail message.

    Returns ``(count, may_archive)`` where ``may_archive`` is False when a
    transient failure (e.g. Gmail API returned no data) should leave the
    message in the inbox for a retry next run.
    """
    attachments = extract_attachments(full_msg.get("payload", {}))
    att_filter = rule.get("attachment_filter", r"\.pdf$")
    matched = [
        a for a in attachments if re.search(att_filter, a["filename"], re.IGNORECASE)
    ]

    if not matched:
        print("    No matching attachments found.")
        return 0, True  # nothing to do — archive so we don't keep revisiting

    count = 0
    any_failed = False
    for att in matched:
        filename = compute_filename(rule, att["filename"], subject)
        dest_path = dest_dir / filename

        print(f"    Attachment: {att['filename']}", end="")
        if filename != att["filename"]:
            print(f" → {filename}", end="")
        print()
        print(f"    Destination: {dest_path}")

        if execute:
            if not _ensure_dest_dir(rule, dest_dir):
                any_failed = True
                continue
            data = gws_get_attachment(msg_id, att["attachmentId"])
            if data is None:
                print("    ERROR: Failed to download attachment")
                any_failed = True
                continue
            existed = dest_path.exists()
            with open(dest_path, "wb") as f:
                f.write(data)
            verb = "OVERWROTE" if existed else "SAVED"
            print(f"    {verb}: {dest_path} ({len(data):,} bytes)")
            count += 1
        else:
            print(
                f"    DRY-RUN: Would download and save ({att.get('mimeType', 'unknown')})"
            )
            count += 1
    return count, not any_failed


def _get_html_body(payload: dict) -> str:
    """Extract HTML body from Gmail message payload."""
    mime = payload.get("mimeType", "")
    if mime == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode(
                "utf-8", errors="replace"
            )
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
            return base64.urlsafe_b64decode(data + "==").decode(
                "utf-8", errors="replace"
            )
    for part in payload.get("parts", []):
        result = _get_text_body(part)
        if result:
            return result
    return ""


def _process_link_download(
    rule: dict,
    full_msg: dict,
    msg_id: str,
    subject: str,
    dest_dir: Path,
    execute: bool,
    state: dict,
) -> tuple[int, bool]:
    """Download PDF via link found in email body.

    Returns ``(count, may_archive)`` — ``may_archive`` is False when the
    download failed transiently (e.g. connection refused) so the message
    stays in the inbox for a retry.
    """
    html_body = _get_html_body(full_msg.get("payload", {}))
    text_body = _get_text_body(full_msg.get("payload", {}))

    # Find the download URL in HTML body. `link_pattern` may be a single
    # regex string or a list of regexes tried in order (first match wins).
    patterns = rule.get("link_pattern", "")
    if isinstance(patterns, str):
        patterns = [patterns]
    urls = []
    for pat in patterns:
        if not pat:
            continue
        urls = re.findall(pat, html_body)
        if urls:
            break
    if not urls:
        print("    No download link found in email.")
        return 0, True  # permanent — no link will ever appear, archive it

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

    if execute:
        if not _ensure_dest_dir(rule, dest_dir):
            return 0, False  # filesystem error — retry later
        data = download_url(pdf_url)
        if data is None:
            return 0, False  # network failure — retry later
        existed = dest_path.exists()
        with open(dest_path, "wb") as f:
            f.write(data)
        verb = "OVERWROTE" if existed else "SAVED"
        print(f"    {verb}: {dest_path} ({len(data):,} bytes)")
        return 1, True
    else:
        print(f"    DRY-RUN: Would download PDF from link")
        return 1, True


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------


def process_rule(
    rule: dict,
    since: str,
    execute: bool,
    state: dict,
    archive_label_id: str | None,
    base_dir: Path,
    manual_pending: list | None = None,
    force: bool = False,
    messages: list[dict] | None = None,
) -> int:
    """Process a single rule. Returns number of attachments handled.

    If ``messages`` is provided (e.g. pre-fetched in parallel), the triage
    query is skipped.
    """
    if messages is None:
        query = build_gmail_query(rule, since, force=force)
        if VERBOSE:
            print(f"  Query: {query}")
        messages = gws_triage(query)

    # Post-filter: triage query is broad (no subject), so apply subject_regex
    # and from filters here. Do it before the count print so the reported
    # number reflects what will actually be processed.
    filtered = [m for m in messages if matches_rule(rule, m["from"], m["subject"])]

    # Triage truncates long from fields with … at the end.  Collect messages
    # that didn't match due to truncation — they will be resolved later using
    # the full From header from the fetched message.
    uncertain = []
    if "from_contains" in rule:
        uncertain = [m for m in messages if m not in filtered and "…" in m["from"]]
    uncertain_ids = {m["id"] for m in uncertain}

    dropped = len(messages) - len(filtered) - len(uncertain)
    dropped_note = f" ({dropped} not matched)" if dropped else ""

    if not filtered and not uncertain:
        print(f"── {rule['name']}: no messages{dropped_note}")
        if dropped and VERBOSE:
            for m in messages:
                print(f"    not matched [{m['from'][:40]}]: {m['subject'][:60]}")
        return 0

    nc = len(filtered)
    label = f"{nc} message(s)" + (f" + {len(uncertain)} truncated" if uncertain else "")
    print(f"── {rule['name']}: {label}{dropped_note}")
    if dropped and VERBOSE:
        all_ids = {m["id"] for m in filtered} | uncertain_ids
        for m in messages:
            if m["id"] not in all_ids:
                print(f"    not matched [{m['from'][:40]}]: {m['subject'][:60]}")
    count = 0
    dest_dir = base_dir / rule["destination"]
    pending_ids = {p["msg_id"] for p in state.get("pending", [])}

    for msg in filtered + uncertain:
        msg_id = msg["id"]

        # Skip already processed (unless --force or queued for retry).
        # Pending retries take priority — they were left in inbox on purpose.
        if not force and msg_id in state["processed_ids"] and msg_id not in pending_ids:
            if VERBOSE:
                print(f"    skipped (already processed): {msg['subject'][:60]}")
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

        # Resolve uncertain messages: triage from was truncated so recheck
        # against the full From header from the fetched message.
        if msg_id in uncertain_ids:
            full_from = get_header(full_msg, "From")
            if not matches_rule(rule, full_from, subject):
                if VERBOSE:
                    print(f"    not matched (full header): {full_from[:60]}")
                continue
            if VERBOSE:
                print(f"    resolved via full header: {full_from[:60]}")

        if rule.get("manual_portal"):
            # --- Manual portal: collect for end-of-run summary ---
            manual_pending.append(
                {
                    "rule_name": rule["name"],
                    "portal_url": rule.get("portal_url", ""),
                    "destination": rule["destination"],
                    "subject": subject,
                    "date": msg["date"],
                    "msg_id": msg_id,
                }
            )
            print(f"    Portal login required — will prompt at end of run")
            continue  # skip label/archive until user confirms
        elif rule.get("link_download"):
            # --- Link-based download: extract URL from HTML email body ---
            msg_count, may_archive = _process_link_download(
                rule,
                full_msg,
                msg_id,
                subject,
                dest_dir,
                execute,
                state,
            )
        else:
            # --- Standard attachment download ---
            msg_count, may_archive = _process_attachment_download(
                rule,
                full_msg,
                msg_id,
                subject,
                dest_dir,
                execute,
            )
        count += msg_count

        # Transient failure: leave the message in the inbox and record it
        # as pending so the next run rolls `since` back to include it.
        if execute and not may_archive:
            _add_pending(state, msg_id, msg["date"])
            print(f"    PENDING: left in inbox, will retry next run")
            continue

        # Label + archive + mark as read
        if execute and archive_label_id:
            if gws_modify_message(msg_id, [archive_label_id], ["INBOX", "UNREAD"]):
                print(f"    Labeled + archived + marked as read")
            else:
                print(f"    WARNING: Failed to label/archive email")

        # Mark as processed (only in execute mode)
        if execute:
            _clear_pending(state, msg_id)
            if msg_id not in state["processed_ids"]:
                state["processed_ids"].append(msg_id)

    return count


def cmd_list_rules():
    """List all rules and exit."""
    print(
        "Matches Gmail messages by sender/subject and save attachments or linked PDFs."
    )
    print(f"{'#':<3} {'Name':<35} {'Destination':<40}")
    print(f"{'-' * 3} {'-' * 35} {'-' * 40}")
    sorted_rules = sorted(_get_rules(), key=lambda r: r["name"].lower())
    for i, rule in enumerate(sorted_rules, 1):
        print(f"{i:<3} {rule['name']:<35} {rule['destination']:<40}")

    folder_keywords = _get_folder_keywords()
    if folder_keywords:
        print(
            "\nRoute files from \"folder\" to a destination when the extracted text contains any keyword."
        )
        print(f"{'#':<3} {'Keywords':<35} {'Destination':<40}")
        print(f"{'-' * 3} {'-' * 35} {'-' * 40}")
        sorted_fk = sorted(folder_keywords.items(), key=lambda kv: kv[0].lower())
        for i, (dest, kws) in enumerate(sorted_fk, 1):
            kw_str = ", ".join(kws)
            if len(kw_str) > 35:
                kw_str = kw_str[:32] + "..."
            print(f"{i:<3} {kw_str:<35} {dest:<40}")

    filename_rules = _get_filename_rules()
    if filename_rules:
        print(
            "\nRoutes files from \"folder\" to a destination when the filename matches the regex (checked before keywords)."
        )
        print(f"{'#':<3} {'Pattern':<35} {'Destination':<40}")
        print(f"{'-' * 3} {'-' * 35} {'-' * 40}")
        sorted_fn = sorted(filename_rules, key=lambda r: r["pattern"].lower())
        for i, rule in enumerate(sorted_fn, 1):
            print(f"{i:<3} {rule['pattern']:<35} {rule['destination']:<40}")

    ignore_senders = _get_ignore_senders()
    if ignore_senders:
        print("\nSenders skipped during unknown-sender discovery.")
        for s in sorted(ignore_senders):
            print(f"  {s}")


# ---------------------------------------------------------------------------
# Inbox scanner — classify files by PDF text content
# ---------------------------------------------------------------------------

INBOX_DEFAULT = Path.home() / "Documents" / "Archiwum dokumentów" / "### Inbox"
SUPPORTED_EXTENSIONS = {".pdf", ".csv"}


def extract_pdf_text(path: Path, max_pages: int = 2) -> str:
    """Extract text from the first pages of a PDF using pdftotext."""
    try:
        result = _run(
            ["pdftotext", "-l", str(max_pages), str(path), "-"],
            timeout=10,
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
        return bool(re.search(r"\b" + re.escape(kw_lower) + r"\b", text_lower))
    return kw_lower in text_lower


def _extract_year(text: str, filename: str) -> str | None:
    """Extract a 4-digit year from PDF text or filename."""
    # Try common date patterns in text: DD.MM.YYYY, YYYY-MM-DD, Month YYYY
    for pattern in [
        r"\b(\d{4})-\d{2}-\d{2}\b",
        r"\b\d{2}\.\d{2}\.(\d{4})\b",
        r"\b(?:Jan|Feb|Mär|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez)\w*\s+(\d{4})\b",
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*[\s-](\d{4})\b",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1)
    # Fallback: year from filename
    m = re.search(r"(\d{4})", filename)
    return m.group(1) if m else None


def classify_file(
    path: Path,
    keyword_index: list[tuple[str, list[str]]],
) -> list[tuple[str, int, list[str]]]:
    """Score a file against all keyword sets.

    Returns list of (destination, score, matched_keywords) sorted by score desc.
    Destinations containing <YEAR> are resolved from the PDF content or filename.
    """
    text = extract_pdf_text(path)
    if not text:
        return []

    text_lower = text.lower()
    year = None
    matches = []
    for dest, keywords in keyword_index:
        matched = [kw for kw in keywords if _keyword_matches(kw, text_lower)]
        if matched:
            resolved_dest = dest
            if "<YEAR>" in dest:
                if year is None:
                    year = _extract_year(text, path.name) or "unknown"
                resolved_dest = dest.replace("<YEAR>", year)
            matches.append((resolved_dest, len(matched), matched))

    matches.sort(key=lambda m: m[1], reverse=True)
    return matches


def classify_path(
    path: Path,
    filename_rules: list[dict],
    keyword_index: list[tuple[str, list[str]]],
) -> list[tuple[str, int, list[str]]]:
    """Classify a file: filename-pattern rules first, then content keywords.

    Filename rules win (score 99) and short-circuit content scanning.
    Returns the same (destination, score, reasons) list as ``classify_file``.
    """
    for rule in filename_rules:
        if re.match(rule["pattern"], path.name):
            return [(rule["destination"], 99, ["filename:" + rule["pattern"]])]
    return classify_file(path, keyword_index)


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

    filename_rules = _get_filename_rules()
    keyword_index = _build_keyword_index()
    print(
        f"Loaded {len(filename_rules)} filename rules, {len(keyword_index)} keyword targets\n"
    )

    # Collect files (skip directories)
    files = sorted(
        f
        for f in inbox.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    other_files = sorted(
        f
        for f in inbox.iterdir()
        if f.is_file() and f.suffix.lower() not in SUPPORTED_EXTENSIONS
    )

    if not files:
        print("No supported files found in inbox.")
        if other_files:
            print(f"\nSkipped {len(other_files)} unsupported file(s):")
            for f in other_files:
                print(f"  {f.name}")
        return

    matched_files = []
    unmatched_files = []

    for f in files:
        results = classify_path(f, filename_rules, keyword_index)
        if results:
            matched_files.append((f, results))
        else:
            unmatched_files.append(f)

    # Show matched files
    if matched_files:
        print(f"{'=' * 60}")
        print(f"MATCHED ({len(matched_files)} files)")
        print(f"{'=' * 60}")

        for f, results in matched_files:
            best_dest, best_score, best_kws = results[0]
            confidence = "HIGH" if best_score >= 2 else "LOW"
            print(f"\n  {f.name}")
            print(
                f"    → {best_dest}  [{confidence}, {best_score} keyword(s): {', '.join(best_kws)}]"
            )

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
        print(f"\n{'=' * 60}")
        print(f"UNMATCHED ({len(unmatched_files)} files)")
        print(f"{'=' * 60}")
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


def discover_unknown_senders(
    config: dict,
    since: str,
    state: dict,
    archive_label_id: str | None,
    base_dir: Path,
    state_file: Path,
) -> int:
    """Interactively handle inbox attachments from senders no rule covers.

    For each unknown sender's PDF: classify it by content (the same keyword /
    filename rules used elsewhere) to suggest a destination, then either save
    it — auto-adding a permanent rule for that sender — or add the sender to
    the ignore list so it is skipped on future runs. Returns count saved.
    """
    rules = config["rules"]
    ignore_senders = config.setdefault("ignore_senders", [])
    filename_rules = _get_filename_rules()
    keyword_index = _build_keyword_index()

    query = f"after:{since} in:inbox has:attachment -label:{ARCHIVE_LABEL_NAME}"
    if VERBOSE:
        print(f"  Discover query: {query}")
    messages = gws_triage(query)

    def _seen(msg_from: str) -> bool:
        return _is_ignored(msg_from, ignore_senders) or any(
            _from_matches(r, msg_from) for r in rules
        )

    # Cheap pre-filter on the (possibly truncated) triage `from`. Triage may
    # truncate long senders with "…", so keep those for a definitive recheck
    # against the full From header after fetching the message.
    candidates = [
        m
        for m in messages
        if m["id"] not in state["processed_ids"]
        and ("…" in m["from"] or not _seen(m["from"]))
    ]
    if not candidates:
        return 0

    existing_names = {r["name"] for r in rules}
    saved = 0
    header_shown = False
    tmpdir = Path(tempfile.mkdtemp(prefix="archive-inbox-"))
    try:
        for msg in candidates:
            msg_id = msg["id"]
            full_msg = gws_get_message(msg_id)
            if not full_msg:
                continue
            full_from = get_header(full_msg, "From")
            subject = get_header(full_msg, "Subject")

            # Definitive recheck with the full (untruncated) From header.
            if _seen(full_from):
                continue

            atts = [
                a
                for a in extract_attachments(full_msg.get("payload", {}))
                if re.search(r"\.pdf$", a["filename"], re.IGNORECASE)
            ]
            if not atts:
                continue

            if not header_shown:
                print(f"\n{'=' * 60}")
                print("UNKNOWN SENDERS")
                print(f"{'=' * 60}")
                header_shown = True

            sender_email = _bare_email(full_from)
            print(f"\n  {subject[:70]}")
            print(f"    From: {full_from[:70]}")
            print(f"    Date: {msg['date']}")
            print(f"    Attachment(s): {', '.join(a['filename'] for a in atts)}")

            # Download the first PDF and classify it by content — same keyword
            # and filename rules used by the folder/portal classifier.
            data = gws_get_attachment(msg_id, atts[0]["attachmentId"])
            if data is None:
                print("    ERROR: could not download to classify — skipped")
                continue
            tmp_path = tmpdir / atts[0]["filename"]
            with open(tmp_path, "wb") as fh:
                fh.write(data)

            results = classify_path(tmp_path, filename_rules, keyword_index)
            suggested = results[0][0] if results else None
            if results:
                _, score, kws = results[0]
                print(
                    f"    Suggested: {suggested}  [{score} keyword(s): {', '.join(kws)}]"
                )
            else:
                first_lines = [
                    l.strip()
                    for l in extract_pdf_text(tmp_path).split("\n")
                    if l.strip()
                ][:2]
                for line in first_lines:
                    print(f"    | {line[:80]}")

            if suggested:
                sys.stdout.write(
                    "    Save? [Y=dest / d=other / i=ignore / s=skip / q=quit] "
                )
            else:
                sys.stdout.write(
                    "    No keyword match. [d=dest / i=ignore / s=skip / q=quit] "
                )
            sys.stdout.flush()
            ch = _read_single_key()
            print(ch)

            if ch == "q":
                break
            if ch == "s":
                continue
            if ch in ("i", "n"):
                if sender_email and sender_email not in ignore_senders:
                    ignore_senders.append(sender_email)
                    _save_config(config)
                    print(f"    Ignored sender: {sender_email}")
                continue

            # Default (Y/Enter) uses the suggestion; 'd' or no suggestion asks.
            dest_rel = suggested
            if ch == "d" or not suggested:
                sys.stdout.write(f"    Destination (relative to {base_dir}): ")
                sys.stdout.flush()
                dest_rel = input().strip()
                if not dest_rel:
                    print("    No destination — skipped")
                    continue

            dest_dir = base_dir / dest_rel
            dest_dir.mkdir(parents=True, exist_ok=True)
            for i, a in enumerate(atts):
                blob = data if i == 0 else gws_get_attachment(msg_id, a["attachmentId"])
                if blob is None:
                    print(f"    ERROR: failed to download {a['filename']}")
                    continue
                dest_path = dest_dir / a["filename"]
                existed = dest_path.exists()
                with open(dest_path, "wb") as fh:
                    fh.write(blob)
                verb = "OVERWROTE" if existed else "SAVED"
                print(f"    {verb}: {dest_path} ({len(blob):,} bytes)")

            # Confirmed save -> always add a rule so this sender is automatic next time.
            name = _derive_rule_name(full_from, existing_names)
            existing_names.add(name)
            rules.append(
                {
                    "name": name,
                    "from": sender_email,
                    "destination": dest_rel,
                    "attachment_filter": r"\.pdf$",
                    "subject_regex": None,
                }
            )
            _save_config(config)
            print(f"    Added rule '{name}': {sender_email} → {dest_rel}")

            # Label + archive + mark as read, same as a normal rule match.
            if archive_label_id and gws_modify_message(
                msg_id, [archive_label_id], ["INBOX", "UNREAD"]
            ):
                print("    Labeled + archived + marked as read")
            if msg_id not in state["processed_ids"]:
                state["processed_ids"].append(msg_id)
            save_state(state, state_file)
            saved += 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return saved


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
        since = (datetime.now() - timedelta(days=DEFAULT_SINCE_DAYS)).strftime(
            "%Y/%m/%d"
        )

    # Roll `since` back if there are older pending retries — ensures the
    # Gmail triage query still covers any message left over from last run.
    pending_since = _oldest_pending_date(state)
    if pending_since and pending_since < since:
        print(
            f"Rolling since back to {pending_since} for {len(state['pending'])} pending retry(s)"
        )
        since = pending_since

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
            print(
                f"ERROR: No rule named '{args.rule}'. Use 'list-rules' to see available rules."
            )
            sys.exit(1)

    # Pre-fetch triage results in parallel for non-manual_portal rules.
    # Manual portal rules stay sequential (they prompt the user).
    prefetch_targets = [r for r in rules if not r.get("manual_portal")]
    prefetched: dict[str, list[dict]] = {}
    if prefetch_targets:

        def _triage_one(rule):
            _tls.buffer = io.StringIO()
            try:
                q = build_gmail_query(rule, since, force=args.force)
                if VERBOSE:
                    print(f"  Query: {q}", file=_tls.buffer)
                msgs = gws_triage(q)
                return rule["name"], msgs, _tls.buffer.getvalue()
            finally:
                _tls.buffer = None

        max_workers = min(8, len(prefetch_targets))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            for name, msgs, log in ex.map(_triage_one, prefetch_targets):
                prefetched[name] = msgs
                if log and VERBOSE:
                    sys.stderr.write(f"── {name}\n")
                    sys.stderr.write(log)

    # Process each rule sequentially (per-message work is serial)
    total = 0
    manual_pending = []
    for rule in rules:
        total += process_rule(
            rule,
            since,
            True,
            state,
            archive_label_id,
            base_dir,
            manual_pending,
            force=args.force,
            messages=prefetched.get(rule["name"]),
        )

    # Save state
    save_state(state, state_file)
    print(f"\nState saved to {state_file}")

    print(f"\n{'=' * 60}")
    print(f"Total attachments processed: {total}")
    print(f"{'=' * 60}")

    # Manual portal summary
    if manual_pending:
        # Portal pages serve mixed document types (e.g. Gothaer serves both
        # Leistungsabrechnungen and contract docs), so classify each download
        # and route per-file instead of dumping all into the rule destination.
        filename_rules = _get_filename_rules()
        keyword_index = _build_keyword_index()

        # Group by portal
        portals: dict[str, list] = {}
        for item in manual_pending:
            key = item["rule_name"]
            portals.setdefault(key, []).append(item)

        print(f"\n{'=' * 60}")
        print(f"MANUAL DOWNLOADS NEEDED")
        print(f"{'=' * 60}")

        for portal_name, items in portals.items():
            url = items[0]["portal_url"]
            default_dest = items[0]["destination"]
            print(f"\n  {portal_name} ({len(items)} new)")
            print(f"  Login: {url}")
            print(f"  Dest:  {base_dir / default_dest} (default; auto-classified per file)")
            for item in items:
                print(f"    - {item['date']}: {item['subject'][:60]}")

            # Ask user to download from portal first
            sys.stdout.write(
                f"\n  Download from {portal_name} now, press any key when done (s to skip): "
            )
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
                    print(
                        f"    [{i + 1}] {c['path'].name}  ({created_str}, {size_kb:,.0f} KB)"
                    )

                    # Classify each file; fall back to the rule destination.
                    results = classify_path(c["path"], filename_rules, keyword_index)
                    dest_rel = results[0][0] if results else default_dest
                    file_dest_dir = base_dir / dest_rel

                    sys.stdout.write(f'        Move to "{dest_rel}"? [Y/n/d(est)] ')
                    sys.stdout.flush()
                    ch = _read_single_key()
                    print(ch)

                    if ch == "d":
                        sys.stdout.write(f"        Destination (relative to {base_dir}): ")
                        sys.stdout.flush()
                        custom = input().strip()
                        if custom:
                            file_dest_dir = base_dir / custom
                        do_move = True
                    else:
                        do_move = ch != "n"

                    if do_move:
                        file_dest_dir.mkdir(parents=True, exist_ok=True)
                        dest_path = file_dest_dir / c["path"].name
                        shutil.move(str(c["path"]), str(dest_path))
                        print(f"        MOVED → {dest_path}")
                        moved_any = True

                if moved_any:
                    for item in items:
                        msg_id = item["msg_id"]
                        if archive_label_id:
                            gws_modify_message(
                                msg_id, [archive_label_id], ["INBOX", "UNREAD"]
                            )
                        if msg_id not in state["processed_ids"]:
                            state["processed_ids"].append(msg_id)
                    print(f"    Marked {len(items)} email(s) as Stored")
                    save_state(state, state_file)
                else:
                    print(f"    No files moved — will prompt again next run")
            else:
                print(
                    f"    No recent PDFs found in ~/Downloads — will prompt again next run"
                )

    # Discover attachments from senders that no rule covers (interactive):
    # save (auto-adding a rule) or add the sender to the ignore list.
    if not args.rule and not args.no_discover:
        config = _load_config()
        n = discover_unknown_senders(
            config, since, state, archive_label_id, base_dir, state_file
        )
        if n:
            save_state(state, state_file)
            print(f"\nDiscovered and saved {n} new sender(s)")


def main():
    parser = argparse.ArgumentParser(
        description="Gmail Attachment Auto-Archiver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print each external command and its output (to stderr)",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Print everything including stdout and stderr",
    )

    # Shared options — allow --verbose after the subcommand too
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-v",
        "--verbose",
        dest="verbose_sub",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    common.add_argument(
        "-d",
        "--debug",
        dest="debug_sub",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    subparsers = parser.add_subparsers(dest="command")

    # gmail
    run_parser = subparsers.add_parser(
        "gmail", parents=[common], help="Download attachments and archive emails"
    )
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
    run_parser.add_argument(
        "--no-discover",
        action="store_true",
        help="Skip the interactive unknown-sender discovery step",
    )

    # list-rules
    subparsers.add_parser("list-rules", parents=[common], help="List all rules")

    # folder
    scan_parser = subparsers.add_parser(
        "folder", parents=[common], help="Classify inbox files by content"
    )
    scan_parser.add_argument(
        "inbox",
        nargs="?",
        default=None,
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

    global VERBOSE, DEBUG
    VERBOSE = args.verbose or getattr(args, "verbose_sub", False)
    DEBUG = args.debug or getattr(args, "debug_sub", False)

    if args.command == "gmail":
        cmd_run(args)
    elif args.command == "list-rules":
        cmd_list_rules()
    elif args.command == "folder":
        cmd_scan_inbox(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
