"""The brain decides what to do next.

Both brains speak the same message format (the Anthropic Messages format), so
the agent loop doesn't care which one is running:

    respond(messages, tools) -> list of content blocks
        {"type": "text", "text": ...}
        {"type": "tool_use", "id": ..., "name": ..., "input": {...}}

OfflineBrain is a small rule-based stand-in so everything runs without an API
key. ClaudeBrain is the real thing and switches on when ANTHROPIC_API_KEY is set.
"""
from __future__ import annotations

import itertools
import re
from datetime import datetime
from typing import Protocol

SYSTEM_PROMPT = (
    "You are Jarvis, a concise personal assistant running on the user's own "
    "computer. Use the provided tools when they help; you cannot do anything "
    "a tool doesn't offer, so say so plainly if asked. If you need a decision "
    "or missing information, call ask_human rather than guessing. Keep spoken "
    "replies short: one to three sentences."
)


class Brain(Protocol):
    name: str

    def respond(self, messages: list[dict], tools: list[dict]) -> list[dict]: ...


def _last_user_text(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg["role"] != "user":
            continue
        content = msg["content"]
        if isinstance(content, str):
            return content
        texts = [b["text"] for b in content if b.get("type") == "text"]
        if texts:
            return " ".join(texts)
    return ""


class OfflineBrain:
    """Keyword rules that mimic tool calling. Good enough to exercise the loop."""

    name = "offline"
    _ids = itertools.count(1)

    HELP = (
        "I'm running in offline mode, so I only understand a few things: "
        "'what time is it', 'calculate 12 * 7', 'note buy milk', 'list my notes', "
        "'clear my notes', 'remind me in 10 minutes to stretch', 'list reminders', "
        "'text me hello', 'call me' and 'ask me something'. "
        "Add your Anthropic API key to switch on the full Claude brain."
    )

    def _call(self, name: str, **inputs) -> list[dict]:
        return [{"type": "tool_use", "id": f"offline_{next(self._ids)}",
                 "name": name, "input": inputs}]

    def respond(self, messages: list[dict], tools: list[dict]) -> list[dict]:
        last = messages[-1]
        # A tool just ran: report its result back to the user.
        if last["role"] == "user" and isinstance(last["content"], list) and any(
            b.get("type") == "tool_result" for b in last["content"]
        ):
            results = [b for b in last["content"] if b.get("type") == "tool_result"]
            text = " ".join(str(b["content"]) for b in results)
            if any(b.get("_tool") == "ask_human" for b in results):
                text = f"Got it, you said: {text}"
            return [{"type": "text", "text": text}]

        text = _last_user_text(messages).strip()
        low = text.lower()
        available = {t["name"] for t in tools}

        def has(name: str) -> bool:
            return name in available

        if has("get_time") and re.search(r"\b(time|date|day is it)\b", low):
            return self._call("get_time")
        m = re.search(r"(?:calculate|calc|what is|what's)\s+([-\d\s.+*/%()^x×]+)$", low)
        if has("calculate") and m and re.search(r"\d", m.group(1)):
            return self._call("calculate", expression=m.group(1).strip())
        if has("clear_notes") and re.search(r"\b(clear|delete|remove)\b.*\bnotes?\b", low):
            return self._call("clear_notes")
        if has("list_notes") and re.search(r"\b(list|show|read)\b.*\bnotes?\b|^notes\??$", low):
            return self._call("list_notes")
        m = re.match(r"^remind me (in \d+ \w+|at \d{1,2}:\d{2}|tomorrow at \d{1,2}:\d{2}) (?:to|about) (.+)$",
                     text, re.I)
        if has("set_reminder") and m:
            when = m.group(1)[3:] if m.group(1).lower().startswith("at ") else m.group(1)
            return self._call("set_reminder", when=when, message=m.group(2).strip())
        if has("list_reminders") and re.search(r"\b(list|show|what are)\b.*\breminders?\b", low):
            return self._call("list_reminders")
        m = re.match(r"^(?:text|message) me[:\s]+(.+)$", text, re.I)
        if has("send_me_message") and m:
            return self._call("send_me_message", text=m.group(1).strip())
        if has("call_me") and re.search(r"\bcall me\b", low):
            return self._call("call_me", message="Hello, this is Jarvis. You asked me to call you.")
        m = re.match(r"^(?:note|remember|remind me to)[:\s]+(.+)$", text, re.I)
        if has("add_note") and m:
            return self._call("add_note", text=m.group(1).strip())
        if has("ask_human") and re.search(r"\bask me\b", low):
            return self._call("ask_human", question="What would you like me to focus on today?")
        if re.search(r"^(hi|hello|hey)\b", low):
            return [{"type": "text", "text": "Hello. " + self.HELP}]
        return [{"type": "text", "text": self.HELP}]


class ClaudeBrain:
    name = "claude"

    def __init__(self, api_key: str, model: str, max_tokens: int = 1024):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on install
            raise RuntimeError(
                "ANTHROPIC_API_KEY is set but the 'anthropic' package isn't "
                "installed. Run: pip install -r requirements.txt"
            ) from exc
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    def respond(self, messages: list[dict], tools: list[dict]) -> list[dict]:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT + datetime.now().strftime(" The current local time is %A %d %B %Y, %H:%M."),
            tools=tools,
            messages=_strip_private_keys(messages),
        )
        blocks: list[dict] = []
        for block in resp.content:
            if block.type == "text":
                blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                blocks.append({"type": "tool_use", "id": block.id,
                               "name": block.name, "input": block.input})
        return blocks


def _strip_private_keys(messages: list[dict]) -> list[dict]:
    """Remove our own bookkeeping keys (prefixed '_') before sending to the API."""
    out = []
    for msg in messages:
        content = msg["content"]
        if isinstance(content, list):
            content = [{k: v for k, v in b.items() if not k.startswith("_")} for b in content]
        out.append({"role": msg["role"], "content": content})
    return out


def make_brain(api_key: str | None, model: str) -> Brain:
    if api_key:
        return ClaudeBrain(api_key, model)
    return OfflineBrain()
