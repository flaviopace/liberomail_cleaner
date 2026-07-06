#!/usr/bin/env python3
"""Clean up old, unread, newsletter/spam-looking emails from a Libero Mail account over IMAP.

Setup:
  1. Copy credentials.example.json to credentials.json and fill in your real
     email/password. credentials.json is gitignored and must never be committed.
  2. Run with --list-folders first to find the exact name of your Trash folder.
  3. Run without --confirm to see a dry-run report of what would be moved.
  4. Re-run with --confirm to actually move matching emails to the Trash folder.

Example:
  python clean_libero.py --list-folders
  python clean_libero.py --days 730 --folder INBOX
  python clean_libero.py --days 730 --folder INBOX --trash-folder "INBOX.Posta Eliminata" --confirm
"""

import argparse
import imaplib
import json
import re
import sys
from datetime import datetime, timedelta
from email.header import decode_header
from email.parser import BytesHeaderParser

NEWSLETTER_HEADERS = ("list-unsubscribe", "list-id", "list-post")
BULK_PRECEDENCE_VALUES = ("bulk", "list", "junk")
SENDER_KEYWORDS = (
    "noreply", "no-reply", "no.reply", "newsletter", "newsletters",
    "news@", "marketing", "notify", "notifications", "mailer",
    "campaign", "promo", "info@", "comunicazioni",
)
SUBJECT_KEYWORDS = (
    "newsletter", "unsubscribe", "disiscriviti", "cancellati",
    "offerta", "offerte", "sconto", "sconti", "promo", "saldi",
    "scopri", "novità", "novita", "iscriviti",
)
TRASH_NAME_HINTS = ("trash", "cestino", "eliminat", "deleted")


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)
    for key in ("email", "password"):
        if not config.get(key):
            sys.exit(f"credentials file '{path}' is missing required field '{key}'")
    config.setdefault("imap_server", "imapmail.libero.it")
    config.setdefault("imap_port", 993)
    return config


def decode_mime_words(value):
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for text, charset in parts:
        if isinstance(text, bytes):
            try:
                decoded.append(text.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                decoded.append(text.decode("utf-8", errors="replace"))
        else:
            decoded.append(text)
    return "".join(decoded)


def quote_mailbox(name):
    if re.fullmatch(r"[A-Za-z0-9_./\-]+", name):
        return name
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def classify(headers):
    """Return a reason string if the message looks like a newsletter/spam, else None."""
    lower_headers = {k.lower(): v for k, v in headers.items()}

    for key in NEWSLETTER_HEADERS:
        if key in lower_headers:
            return f"has {key} header"

    precedence = lower_headers.get("precedence", "").lower()
    if precedence in BULK_PRECEDENCE_VALUES:
        return f"precedence: {precedence}"

    sender = decode_mime_words(headers.get("From", "")).lower()
    for kw in SENDER_KEYWORDS:
        if kw in sender:
            return f"sender contains '{kw}'"

    subject = decode_mime_words(headers.get("Subject", "")).lower()
    for kw in SUBJECT_KEYWORDS:
        if kw in subject:
            return f"subject contains '{kw}'"

    return None


def fetch_headers(imap, uid):
    fields = "(FROM SUBJECT DATE LIST-UNSUBSCRIBE LIST-ID LIST-POST PRECEDENCE)"
    typ, data = imap.uid(
        "fetch", uid, f"(BODY.PEEK[HEADER.FIELDS {fields}])"
    )
    if typ != "OK" or not data or data[0] is None:
        return {}
    raw = data[0][1]
    return dict(BytesHeaderParser().parsebytes(raw).items())


def list_folders(imap):
    typ, data = imap.list()
    if typ != "OK":
        sys.exit("failed to list folders")
    print("Available folders:")
    for line in data:
        print(" ", line.decode("utf-8", errors="replace"))


def guess_trash_folder(imap):
    typ, data = imap.list()
    if typ != "OK":
        return None
    candidates = []
    for line in data:
        text = line.decode("utf-8", errors="replace")
        match = re.search(r'"([^"]+)"\s*$', text)
        name = match.group(1) if match else text.split()[-1]
        if any(hint in text.lower() for hint in TRASH_NAME_HINTS):
            candidates.append(name)
    if len(candidates) == 1:
        return candidates[0]
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Delete old, unread, newsletter/spam-looking emails from Libero Mail.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default="credentials.json", help="path to credentials JSON (default: credentials.json)")
    parser.add_argument("--folder", default="INBOX", help="IMAP folder to clean (default: INBOX)")
    parser.add_argument("--days", type=int, default=730, help="age threshold in days (default: 730, ~2 years)")
    parser.add_argument("--trash-folder", default=None, help="destination folder for matched emails; auto-detected if omitted")
    parser.add_argument("--list-folders", action="store_true", help="list IMAP folders and exit")
    parser.add_argument("--confirm", action="store_true", help="actually move matching emails to trash (default is dry-run report only)")
    parser.add_argument("--limit", type=int, default=None, help="max number of matching emails to process")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every candidate considered, not just matches")
    args = parser.parse_args()

    config = load_config(args.config)

    imap = imaplib.IMAP4_SSL(config["imap_server"], config["imap_port"])
    imap.login(config["email"], config["password"])

    try:
        if args.list_folders:
            list_folders(imap)
            return

        typ, _ = imap.select(quote_mailbox(args.folder), readonly=not args.confirm)
        if typ != "OK":
            sys.exit(f"failed to select folder '{args.folder}'")

        cutoff = datetime.now() - timedelta(days=args.days)
        date_str = cutoff.strftime("%d-%b-%Y")

        typ, data = imap.uid("search", None, f'(UNSEEN SENTBEFORE "{date_str}")')
        if typ != "OK":
            sys.exit("IMAP search failed")
        uids = data[0].split()
        if args.limit:
            uids = uids[: args.limit]

        print(f"{len(uids)} unread message(s) older than {args.days} days found in '{args.folder}'.")

        matched = []
        for uid in uids:
            headers = fetch_headers(imap, uid)
            reason = classify(headers)
            sender = decode_mime_words(headers.get("From", "?"))
            subject = decode_mime_words(headers.get("Subject", "?"))
            date = headers.get("Date", "?")
            if reason:
                matched.append(uid)
                print(f"[MATCH] uid={uid.decode()} date={date!r} from={sender!r} subject={subject!r} reason={reason}")
            elif args.verbose:
                print(f"[skip]  uid={uid.decode()} date={date!r} from={sender!r} subject={subject!r}")

        print(f"\n{len(matched)} of {len(uids)} candidate(s) look like newsletter/spam and would be moved to trash.")

        if not matched:
            return

        if not args.confirm:
            print("Dry run only, nothing was changed. Re-run with --confirm to move these to trash.")
            return

        trash_folder = args.trash_folder or guess_trash_folder(imap)
        if not trash_folder:
            sys.exit(
                "Could not determine trash folder automatically. "
                "Run with --list-folders to see available folders, then pass --trash-folder explicitly."
            )
        print(f"Moving {len(matched)} message(s) to '{trash_folder}'...")

        quoted_trash = quote_mailbox(trash_folder)
        moved = 0
        for uid in matched:
            typ, _ = imap.uid("copy", uid, quoted_trash)
            if typ != "OK":
                print(f"  failed to copy uid={uid.decode()} to trash, skipping delete", file=sys.stderr)
                continue
            imap.uid("store", uid, "+FLAGS", "(\\Deleted)")
            moved += 1

        imap.expunge()
        print(f"Done. Moved {moved} message(s) to '{trash_folder}'.")
    finally:
        try:
            imap.close()
        except imaplib.IMAP4.error:
            pass
        imap.logout()


if __name__ == "__main__":
    main()
