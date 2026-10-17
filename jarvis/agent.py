"""The core loop: listen -> think -> act -> repeat.

After every tool runs, its result goes back to the brain, which decides
whether it is done or needs another step.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from .brains import Brain
from .human import HumanChannel
from .tools import ASK_HUMAN_SPEC, ToolRegistry

log = logging.getLogger("jarvis.agent")

YES = {"y", "yes", "yeah", "yep", "ok", "okay", "sure", "go ahead", "do it"}


class Agent:
    def __init__(self, brain: Brain, tools: ToolRegistry, human: HumanChannel,
                 log_dir: Path, max_steps: int = 8):
        self.brain = brain
        self.tools = tools
        self.human = human
        self.max_steps = max_steps
        self.messages: list[dict] = []
        self.max_history = 40  # messages kept as conversation memory
        self._lock = threading.Lock()
        log_dir.mkdir(parents=True, exist_ok=True)
        self.audit_file = log_dir / "tool_calls.jsonl"

    def tool_specs(self) -> list[dict]:
        return self.tools.specs() + [ASK_HUMAN_SPEC]

    def run(self, user_text: str) -> str:
        """Handle one thing the user said and return Jarvis's reply."""
        with self._lock:
            try:
                return self._run(user_text)
            finally:
                self._trim_history()

    def _trim_history(self) -> None:
        """Forget old turns so costs don't grow forever. Always cut at a plain
        user message so tool calls and their results stay paired."""
        if len(self.messages) <= self.max_history:
            return
        start = len(self.messages) - self.max_history
        for i in range(start, len(self.messages)):
            m = self.messages[i]
            if m["role"] == "user" and isinstance(m["content"], str):
                self.messages = self.messages[i:]
                return
        self.messages = []

    def _run(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        for step in range(self.max_steps):
            blocks = self.brain.respond(self.messages, self.tool_specs())
            self.messages.append({"role": "assistant", "content": blocks})
            tool_uses = [b for b in blocks if b["type"] == "tool_use"]
            if not tool_uses:
                return " ".join(b["text"] for b in blocks if b["type"] == "text").strip()
            results = [self._execute(b) for b in tool_uses]
            self.messages.append({"role": "user", "content": results})
        log.warning("Stopped after %d steps without a final answer", self.max_steps)
        return "I stopped because that was taking too many steps. Try asking a simpler way."

    def _execute(self, call: dict) -> dict:
        name, args = call["name"], call.get("input") or {}
        is_error = False
        if name == "ask_human":
            answer = self.human.ask(args.get("question", ""))
            output = answer if answer else "The user did not answer."
        elif (tool := self.tools.get(name)) is None:
            output, is_error = f"Tool '{name}' is not on the allowlist.", True
        elif tool.confirm and not self._confirmed(name, args):
            output = "The user declined, so nothing was done."
        else:
            try:
                output = str(tool.func(**args))
            except Exception as exc:  # report errors to the brain, don't crash
                output, is_error = f"Error: {exc}", True
        self._audit(name, args, output, is_error)
        result = {"type": "tool_result", "tool_use_id": call["id"],
                  "content": output, "_tool": name}
        if is_error:
            result["is_error"] = True
        return result

    def _confirmed(self, name: str, args: dict) -> bool:
        detail = f" with {json.dumps(args)}" if args else ""
        answer = self.human.ask(f"I'd like to run '{name}'{detail}. Allow it? (yes/no)")
        return bool(answer) and answer.strip().lower().rstrip(".!") in YES

    def _audit(self, name: str, args: dict, output: str, is_error: bool) -> None:
        log.info("tool %s(%s) -> %s", name, args, output[:200])
        record = {"at": datetime.now().isoformat(timespec="seconds"), "tool": name,
                  "input": args, "output": output, "error": is_error,
                  "brain": self.brain.name}
        with self.audit_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
