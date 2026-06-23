"""
Watcher for puppet-minsk.by — "Записки юного врача".
Polls the page, detects when a date later than the last-known one appears,
and triggers a Twilio voice call so the phone rings.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def fetch_html(url: str, max_attempts: int = 3) -> str | None:
    """Fetch with retries. Returns None on persistent WAF/network failure."""
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(url, timeout=30, headers=BROWSER_HEADERS)
            if resp.status_code == 200:
                return resp.text
            print(
                f"Attempt {attempt}/{max_attempts}: HTTP {resp.status_code}",
                file=sys.stderr,
            )
        except requests.RequestException as e:
            print(f"Attempt {attempt}/{max_attempts}: {e}", file=sys.stderr)
        if attempt < max_attempts:
            time.sleep(5 * attempt)
    return None

URL = "https://puppet-minsk.by/spektakli/spektakli-dlya-vzroslykh/item/217-zapiski-yunogo-vracha"
STATE_FILE = Path(__file__).parent / "state.json"

RU_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

DATE_RE = re.compile(
    r"(\d{1,2})\s+([А-Яа-яёЁ]+),\s*[А-Яа-яёЁ]+,\s*(\d{1,2}):(\d{2})"
)

# After this many consecutive failed runs (10 min apart = 1 hour),
# call the phone with a "watcher is broken" alert. The streak resets
# on the next successful parse.
WATCHDOG_THRESHOLD = 6


def utcnow_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def handle_soft_failure(reason: str) -> None:
    """Record a soft failure, alert via Twilio if streak hits threshold."""
    state = load_state()
    streak = state.get("consecutive_failures", 0) + 1
    state["consecutive_failures"] = streak
    state["last_failure_reason"] = reason
    state["last_failure_at"] = utcnow_iso()
    save_state(state)
    print(f"Soft failure #{streak}: {reason}", file=sys.stderr)

    if streak == WATCHDOG_THRESHOLD:
        print(f"Watchdog: {streak} failures in a row — alerting via phone.",
              file=sys.stderr)
        try:
            trigger_call(
                "Внимание! Сторож билетов уже целый час не может обработать "
                "сайт театра. Проверь логи на GitHub."
            )
        except Exception:
            import traceback
            traceback.print_exc(file=sys.stderr)


def parse_dates(html: str) -> list[date]:
    soup = BeautifulSoup(html, "html.parser")
    dates: list[date] = []
    for item in soup.select("div.date-item div.date-time p"):
        text = item.get_text(strip=True)
        m = DATE_RE.search(text)
        if not m:
            continue
        day = int(m.group(1))
        month = RU_MONTHS.get(m.group(2).lower())
        if month is None:
            continue
        year = guess_year(month)
        try:
            dates.append(date(year, month, day))
        except ValueError:
            continue
    return dates


def guess_year(month: int) -> int:
    """Site lists day+month without year. Pick the closest future year."""
    today = date.today()
    candidate = today.year
    if month < today.month - 1:
        candidate += 1
    return candidate


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def trigger_call(message: str) -> None:
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_ = os.environ.get("TWILIO_FROM")
    to = os.environ.get("TWILIO_TO")
    if not all([sid, token, from_, to]):
        print("Twilio creds missing — skipping call.", file=sys.stderr)
        return

    from twilio.rest import Client

    twiml = (
        f'<Response>'
        f'<Say language="ru-RU" voice="Polly.Tatyana">{message}</Say>'
        f'<Pause length="1"/>'
        f'<Say language="ru-RU" voice="Polly.Tatyana">{message}</Say>'
        f'<Pause length="1"/>'
        f'<Say language="ru-RU" voice="Polly.Tatyana">{message}</Say>'
        f'</Response>'
    )
    client = Client(sid, token)
    call = client.calls.create(twiml=twiml, to=to, from_=from_)
    print(f"Call initiated: SID={call.sid}")


def main() -> int:
    html = fetch_html(URL)
    if html is None:
        handle_soft_failure("fetch failed after retries")
        return 0

    dates = parse_dates(html)
    if not dates:
        handle_soft_failure("no dates parsed from page")
        return 0

    latest = max(dates)
    state = load_state()
    prev_iso = state.get("latest_date")
    prev = date.fromisoformat(prev_iso) if prev_iso else None

    print(f"Found {len(dates)} dates. Latest on site: {latest.isoformat()}. "
          f"Previously known: {prev_iso}.")

    first_run = prev is None
    new_date_appeared = prev is not None and latest > prev

    if new_date_appeared:
        msg = (
            "Внимание! На сайте Минского театра кукол появилась новая дата "
            "спектакля Записки юного врача. Открой сайт и купи билеты!"
        )
        print(f"NEW DATE detected: {latest.isoformat()} > {prev_iso}. Calling…")
        trigger_call(msg)

    # Success — reset failure tracking
    prior_failures = state.get("consecutive_failures", 0)
    if prior_failures:
        print(f"Recovered after {prior_failures} consecutive failures.",
              file=sys.stderr)
    state["consecutive_failures"] = 0
    state.pop("last_failure_reason", None)
    state.pop("last_failure_at", None)

    if first_run or new_date_appeared:
        state["latest_date"] = latest.isoformat()
    state["last_checked"] = utcnow_iso()
    save_state(state)

    return 0


if __name__ == "__main__":
    # Never let an unexpected error fail the workflow — that just spams
    # email notifications. The phone call is the source of truth for both
    # new dates AND a broken watcher (watchdog after 1h of failures).
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc(file=sys.stderr)
        try:
            handle_soft_failure("unhandled exception in main")
        except Exception:
            traceback.print_exc(file=sys.stderr)
        sys.exit(0)
