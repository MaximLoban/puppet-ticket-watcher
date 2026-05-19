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
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

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
    resp = requests.get(URL, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (compatible; ticket-watcher/1.0)"
    })
    resp.raise_for_status()

    dates = parse_dates(resp.text)
    if not dates:
        print("No dates parsed — site layout may have changed.", file=sys.stderr)
        return 1

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

    if first_run or new_date_appeared:
        state["latest_date"] = latest.isoformat()
        state["last_checked"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        save_state(state)
    else:
        state["last_checked"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        save_state(state)

    return 0


if __name__ == "__main__":
    sys.exit(main())
