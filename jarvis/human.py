"""How Jarvis asks you something when it needs an answer.

Every channel has the same shape: ask(question) -> answer or None.
The terminal one is here; the chat screen's one lives in web.py.
"""
from __future__ import annotations

import logging
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
