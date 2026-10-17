"""How Jarvis reaches you when it needs an answer (the reach-out layer).

Every channel has the same shape: ask(question) -> answer or None.
Start with the terminal. ntfy pushes the question to your phone and waits for
your reply. Telegram / Twilio channels slot in here later (see the build plan).
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Iterable, Protocol

log = logging.getLogger("jarvis.human")


class HumanChannel(Protocol):
    def ask(self, question: str) -> str | None: ...


class TerminalHuman:
    def ask(self, question: str) -> str | None:
        try:
            return input(f"\n[Jarvis asks] {question}\n> ").strip()
        except EOFError:
            return None


class ScriptedHuman:
    """Pre-set answers. Used by tests and demos."""

    def __init__(self, answers: Iterable[str]):
        self.answers = list(answers)
        self.asked: list[str] = []

    def ask(self, question: str) -> str | None:
        self.asked.append(question)
        return self.answers.pop(0) if self.answers else None


class NtfyHuman:
    """Push the question to your phone with ntfy and wait for a reply.

    Install the ntfy app and subscribe to two topics:
      <topic>        Jarvis posts questions here
      <topic>-reply  you post your answer here
    Anyone who knows the topic name can read it, so make it long and random,
    and don't send anything sensitive this way.
    """

    def __init__(self, topic: str, server: str = "https://ntfy.sh", timeout_s: int = 300):
        self.topic = topic
        self.server = server.rstrip("/")
        self.timeout_s = timeout_s

    def ask(self, question: str) -> str | None:
        reply_topic = f"{self.topic}-reply"
        since = int(time.time())
        req = urllib.request.Request(
            f"{self.server}/{self.topic}",
            data=question.encode(),
            headers={"Title": "Jarvis has a question",
                     "Tags": "robot",
                     "Actions": f"view, Reply, ntfy://{urllib.parse.urlparse(self.server).netloc}/{reply_topic}"},
        )
        urllib.request.urlopen(req, timeout=10).read()
        log.info("Sent question via ntfy; waiting up to %ss for a reply", self.timeout_s)

        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            url = f"{self.server}/{reply_topic}/json?poll=1&since={since}"
            with urllib.request.urlopen(url, timeout=15) as resp:
                for line in resp.read().decode().splitlines():
                    msg = json.loads(line)
                    if msg.get("event") == "message" and msg.get("message"):
                        return msg["message"].strip()
            time.sleep(3)
        return None


def make_channel(name: str, ntfy_topic: str | None = None,
                 ntfy_server: str = "https://ntfy.sh") -> HumanChannel:
    if name == "ntfy":
        if not ntfy_topic:
            raise ValueError("JARVIS_NTFY_TOPIC must be set to use the ntfy channel")
        return NtfyHuman(ntfy_topic, ntfy_server)
    return TerminalHuman()
