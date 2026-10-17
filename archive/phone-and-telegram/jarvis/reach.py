"""Reach: how Jarvis contacts you on its own (messages, calls, reminders)."""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .phone import TwilioClient, Voice, twiml

log = logging.getLogger("jarvis.reach")


class Reach:
    def __init__(self, telegram=None, chat_id: int | None = None,
                 twilio: TwilioClient | None = None, my_number: str | None = None,
                 voice: Voice | None = None, fallback: Callable[[str], None] | None = None):
        self.telegram, self.chat_id = telegram, chat_id
        self.twilio, self.my_number = twilio, my_number
        self.voice = voice or Voice()
        self.fallback = fallback
        self.phone_server = None  # set when the phone server is running

    @property
    def can_message(self) -> bool:
        return bool((self.telegram and self.chat_id) or (self.twilio and self.my_number))

    @property
    def can_call(self) -> bool:
        return bool(self.twilio and self.my_number)

    def message(self, text: str) -> str:
        if self.telegram and self.chat_id:
            self.telegram.send(self.chat_id, text)
            return "Sent you a Telegram message."
        if self.twilio and self.my_number:
            self.twilio.sms(self.my_number, text)
            return "Sent you a text message."
        if self.fallback:
            self.fallback(text)
            return "Shown on screen (no phone messaging is set up yet)."
        raise RuntimeError("No way to message the user is set up. Add Telegram to .env (see README).")

    def call(self, message: str, question: str | None = None) -> str:
        if not self.can_call:
            raise RuntimeError("Phone calls aren't set up. Add Twilio details to .env (see README).")
        if question:
            if not self.phone_server:
                raise RuntimeError("To hear the user's answer on a call, run `python -m jarvis serve` "
                                   "with JARVIS_PUBLIC_URL set.")
            answer = self.phone_server.ask_by_call(question, intro=message)
            return f"The user answered: {answer}" if answer else "The user didn't answer the call."
        self.twilio.call(self.my_number, twiml(self.voice.say(message), '<Pause length="1"/>',
                                               self.voice.say(message)))
        return "Calling the user now with that message."


# --- Reminders --------------------------------------------------------------

_UNITS = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600, "day": 86400}


def parse_when(text: str, now: datetime | None = None) -> datetime:
    """Accepts 'in 20 minutes', 'in 2 hours', '17:30', 'tomorrow 08:00',
    '2026-10-20 09:00' or '2026-10-20T09:00'. Times are local."""
    now = now or datetime.now()
    t = text.strip().lower()
    m = re.fullmatch(r"in\s+(\d+(?:\.\d+)?)\s*(second|sec|minute|min|hour|hr|day)s?", t)
    if m:
        return now + timedelta(seconds=float(m.group(1)) * _UNITS[m.group(2)])
    m = re.fullmatch(r"(tomorrow\s+(?:at\s+)?)?(?:at\s+)?(\d{1,2}):(\d{2})", t)
    if m:
        when = now.replace(hour=int(m.group(2)), minute=int(m.group(3)), second=0, microsecond=0)
        if m.group(1) or when <= now:
            when += timedelta(days=1)
        return when
    try:
        return datetime.fromisoformat(t.replace(" ", "T"))
    except ValueError:
        raise ValueError(f"Couldn't understand the time '{text}'. Use 'in 20 minutes', "
                         "'17:30' or 'YYYY-MM-DD HH:MM'.") from None


class ReminderStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def _read(self) -> list[dict]:
        return json.loads(self.path.read_text()) if self.path.exists() else []

    def _write(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(items, indent=2))

    def add(self, when: datetime, message: str, method: str = "message") -> dict:
        item = {"id": uuid.uuid4().hex[:6], "when": when.isoformat(timespec="seconds"),
                "message": message, "method": method, "done": False}
        with self.lock:
            items = self._read()
            items.append(item)
            self._write(items)
        return item

    def pending(self) -> list[dict]:
        with self.lock:
            return [r for r in self._read() if not r["done"]]

    def cancel(self, reminder_id: str) -> bool:
        with self.lock:
            items = self._read()
            keep = [r for r in items if r["id"] != reminder_id]
            self._write(keep)
            return len(keep) != len(items)

    def take_due(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now()
        with self.lock:
            items = self._read()
            due = [r for r in items if not r["done"] and datetime.fromisoformat(r["when"]) <= now]
            for r in due:
                r["done"] = True
            if due:
                self._write(items)
        return due


class ReminderScheduler(threading.Thread):
    def __init__(self, store: ReminderStore, reach: Reach, interval_s: float = 15):
        super().__init__(daemon=True)
        self.store, self.reach, self.interval_s = store, reach, interval_s
        self.stop_event = threading.Event()

    def deliver_due(self, now: datetime | None = None) -> int:
        due = self.store.take_due(now)
        for r in due:
            text = f"Reminder: {r['message']}"
            try:
                if r["method"] == "call" and self.reach.can_call:
                    self.reach.call(text)
                else:
                    self.reach.message(text)
                log.info("Delivered reminder %s by %s", r["id"], r["method"])
            except Exception:
                log.exception("Failed to deliver reminder %s", r["id"])
        return len(due)

    def run(self) -> None:
        while not self.stop_event.wait(self.interval_s):
            self.deliver_due()
