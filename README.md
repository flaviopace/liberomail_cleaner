# liberomail_cleaner

A Python script to clean up a Libero Mail account over IMAP: it finds unread
emails older than a configurable age that look like newsletters/spam, reports
them, and (optionally) moves them to the Trash folder.

No third-party dependencies — stdlib only (`imaplib`, `email`, `argparse`, `json`).

## What it does

A message is flagged for cleanup only if **all three** conditions hold:

1. **Old** — sent before a cutoff date (default: 730 days / ~2 years ago).
2. **Unread** — the `\Seen` flag is not set (uses IMAP `UNSEEN`).
3. **Looks like a newsletter/spam**, based on headers and keywords:
   - `List-Unsubscribe`, `List-Id`, or `List-Post` header present
   - `Precedence: bulk` / `list` / `junk`
   - Sender contains keywords like `noreply`, `newsletter`, `marketing`, `info@`, etc.
   - Subject contains keywords like `unsubscribe`, `disiscriviti`, `offerta`, `sconto`, `promo`, etc.

Fetching only reads headers with `BODY.PEEK`, so scanning never marks a
message as read.

## Setup

1. Copy the credentials template and fill in your real details:
   ```bash
   cp credentials.example.json credentials.json
   ```
   Edit `credentials.json`:
   ```json
   {
     "email": "your_address@libero.it",
     "password": "your_password_or_app_password",
     "imap_server": "imapmail.libero.it",
     "imap_port": 993
   }
   ```
   `credentials.json` is gitignored — it must never be committed. Only
   `credentials.example.json` (with placeholder values) is tracked in git.

2. Find your Trash folder's exact IMAP name:
   ```bash
   python3 clean_libero.py --list-folders
   ```
   Look for the folder with the `\Trash` flag (commonly `trash` or
   `Posta eliminata`). Ignore `__liberosms/trash`, which belongs to the
   unrelated SMS module.

## Usage

### Dry run (default, read-only, changes nothing)

```bash
python3 clean_libero.py --days 730 --folder INBOX
```

Prints every matching message (uid, date, sender, subject, match reason) and
a summary count. Add `-v` / `--verbose` to also print non-matching candidates.

### Actually move matches to Trash

Only after reviewing the dry-run report:

```bash
python3 clean_libero.py --days 730 --folder INBOX --trash-folder trash --confirm
```

This copies each matched message to `--trash-folder` and expunges it from
the source folder. Without `--confirm`, nothing is ever changed.

## CLI options

| Flag | Default | Description |
|---|---|---|
| `--config` | `credentials.json` | Path to credentials JSON |
| `--folder` | `INBOX` | IMAP folder to scan |
| `--days` | `730` | Age threshold in days |
| `--trash-folder` | auto-detected | Destination folder for matches (required if auto-detect finds 0 or >1 candidate) |
| `--list-folders` | — | List IMAP folders and exit |
| `--confirm` | off | Actually move matches to trash (otherwise dry-run only) |
| `--limit` | none | Cap the number of matching emails processed |
| `-v`, `--verbose` | off | Also print non-matching candidates |

## Notes

- Matching is heuristic and conservative (it errs toward the
  `List-Unsubscribe` header, which is a strong newsletter/marketing signal).
  Review the dry-run report before using `--confirm`.
- Libero may require an app-specific password if the account has extra
  security features enabled on the web client.
