"""Text with Jarvis from your phone through a Telegram bot.

Uses the Telegram Bot API directly (no extra packages). Jarvis only answers
your own chat ID; messages from anyone else are ignored and logged.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request

log = logging.getLogger("jarvis.telegram")

MAX_LEN = 4000  # Telegram's limit is 4096 characters per message


class TelegramClient:
    def __init__(self, token: str, base: str = "https://api.telegram.org"):
        self.url = f"{base}/bot{token}"
        self.offset: int | None = None

    def _call(self, method: str, params: dict, timeout: float = 15) -> object:
        req = urllib.request.Request(
            f"{self.url}/{method}", data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {body.get('description')}")
        return body["result"]

    def get_me(self) -> dict:
        return self._call("getMe", {})  # type: ignore[return-value]

    def get_updates(self, timeout: int = 25) -> list[dict]:
        params: dict = {"timeout": timeout, "allowed_updates": ["message"]}
        if self.offset is not None:
            params["offset"] = self.offset
        updates = self._call("getUpdates", params, timeout=timeout + 10)
        if updates:
            self.offset = updates[-1]["update_id"] + 1  # type: ignore[index]
        return updates  # type: ignore[return-value]

    def send(self, chat_id: int, text: str) -> None:
        text = text or "(no reply)"
        for i in range(0, len(text), MAX_LEN):
            self._call("sendMessage", {"chat_id": chat_id, "text": text[i:i + MAX_LEN]})

    def typing(self, chat_id: int) -> None:
        try:
            self._call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        except Exception:
            pass


def _message(update: dict) -> tuple[int | None, str]:
    msg = update.get("message") or {}
    return (msg.get("chat") or {}).get("id"), (msg.get("text") or "").strip()


class TelegramHuman:
    """ask_human over Telegram: sends the question, waits for your next message."""

    def __init__(self, client: TelegramClient, chat_id: int, timeout_s: int = 600):
        self.client = client
        self.chat_id = chat_id
        self.timeout_s = timeout_s

    def ask(self, question: str) -> str | None:
        self.client.send(self.chat_id, f"❓ {question}")
        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            for update in self.client.get_updates(timeout=20):
                cid, text = _message(update)
                if cid == self.chat_id and text:
                    return text
        self.client.send(self.chat_id, "No answer, so I've carried on without one.")
        return None


def handle_update(update: dict, client: TelegramClient, agent, chat_id: int | None) -> None:
    cid, text = _message(update)
    if cid is None or not text:
        return
    if chat_id is None:
        # First-time setup: tell the user their chat ID so they can lock the bot to it.
        client.send(cid, f"Hello. Your chat ID is {cid}.\nPut JARVIS_TELEGRAM_CHAT_ID={cid} "
                         "in Jarvis's .env file (or run `python -m jarvis setup`) and restart "
                         "Jarvis. Until then I won't act on messages.")
        return
    if cid != chat_id:
        log.warning("Ignored a message from unknown chat %s", cid)
        return
    if text in ("/start", "/help"):
        client.send(cid, "Jarvis online. Just talk to me.")
        return
    client.typing(cid)
    try:
        reply = agent.run(text)
    except Exception as exc:
        log.exception("Agent failed on Telegram message")
        reply = f"Sorry, something went wrong: {exc}"
    client.send(cid, reply)


def run_bot(client: TelegramClient, agent, chat_id: int | None, stop=None) -> None:
    """Poll Telegram for messages forever (or until stop.is_set())."""
    log.info("Telegram bot polling (chat lock: %s)", chat_id)
    while not (stop and stop.is_set()):
        try:
            updates = client.get_updates()
        except Exception as exc:
            log.warning("Telegram poll failed: %s; retrying in 5s", exc)
            time.sleep(5)
            continue
        for update in updates:
            handle_update(update, client, agent, chat_id)
