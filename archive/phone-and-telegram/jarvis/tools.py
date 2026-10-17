"""The allowlist: the only things Jarvis can do.

Each tool is a plain Python function registered with @tool. The model never
gets a shell; it can only call what is registered here. Tools marked
confirm=True ask you for a yes before they run.
"""
from __future__ import annotations

import ast
import json
import operator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    func: Callable[..., Any]
    confirm: bool = False

    def spec(self) -> dict:
        """The tool definition sent to Claude."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def specs(self) -> list[dict]:
        return [t.spec() for t in self.tools.values()]

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)


# --- Safe calculator (no eval) -------------------------------------------

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        if isinstance(node.op, ast.Pow) and abs(_safe_eval(node.right)) > 100:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("only numbers and + - * / // % ** are allowed")


def calculate(expression: str) -> str:
    expr = expression.replace("^", "**").replace("x", "*").replace("×", "*")
    result = _safe_eval(ast.parse(expr, mode="eval"))
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return f"{expression} = {result}"


# --- Default toolset -------------------------------------------------------

def build_default_tools(data_dir: Path, reach=None, reminders=None) -> ToolRegistry:
    """The allowlist. Add new capabilities here, one function each.

    reach (jarvis.reach.Reach) enables messaging and calling you; reminders
    (jarvis.reach.ReminderStore) enables reminders.
    """
    notes_file = data_dir / "notes.json"

    def _read_notes() -> list[dict]:
        if notes_file.exists():
            return json.loads(notes_file.read_text())
        return []

    def _write_notes(notes: list[dict]) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        notes_file.write_text(json.dumps(notes, indent=2))

    def get_time() -> str:
        return datetime.now().strftime("It's %H:%M on %A %d %B %Y.")

    def add_note(text: str) -> str:
        notes = _read_notes()
        notes.append({"text": text, "at": datetime.now().isoformat(timespec="seconds")})
        _write_notes(notes)
        return f"Saved note #{len(notes)}: {text}"

    def list_notes() -> str:
        notes = _read_notes()
        if not notes:
            return "You have no notes."
        return "\n".join(f"{i}. {n['text']}" for i, n in enumerate(notes, 1))

    def clear_notes() -> str:
        count = len(_read_notes())
        _write_notes([])
        return f"Deleted {count} note(s)."

    reg = ToolRegistry()
    reg.register(Tool(
        "get_time", "Get the current local date and time.",
        {"type": "object", "properties": {}}, get_time))
    reg.register(Tool(
        "calculate", "Evaluate a basic arithmetic expression, e.g. '12 * (3 + 4)'.",
        {"type": "object", "properties": {"expression": {"type": "string"}},
         "required": ["expression"]}, calculate))
    reg.register(Tool(
        "add_note", "Save a short note or reminder for the user.",
        {"type": "object", "properties": {"text": {"type": "string"}},
         "required": ["text"]}, add_note))
    reg.register(Tool(
        "list_notes", "List all of the user's saved notes.",
        {"type": "object", "properties": {}}, list_notes))
    reg.register(Tool(
        "clear_notes", "Delete ALL saved notes. Destructive; the user is asked to confirm.",
        {"type": "object", "properties": {}}, clear_notes, confirm=True))

    if reach is not None:
        _add_reach_tools(reg, reach)
    if reminders is not None:
        _add_reminder_tools(reg, reminders)
    return reg


def _add_reach_tools(reg: ToolRegistry, reach) -> None:
    def send_me_message(text: str) -> str:
        return reach.message(text)

    def call_me(message: str, question: str = "") -> str:
        return reach.call(message, question or None)

    reg.register(Tool(
        "send_me_message",
        "Send the user a message on their phone (Telegram, or SMS if that's what is set up). "
        "Use when they ask you to text or message them something.",
        {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        send_me_message))
    reg.register(Tool(
        "call_me",
        "Phone the user and speak a message. If 'question' is given, ask it on the call and "
        "return their spoken answer. Use only when they ask to be called or something is urgent.",
        {"type": "object", "properties": {
            "message": {"type": "string", "description": "What to say when they pick up."},
            "question": {"type": "string", "description": "Optional question to ask and wait for."}},
         "required": ["message"]},
        call_me))


def _add_reminder_tools(reg: ToolRegistry, store) -> None:
    from .reach import parse_when

    def set_reminder(when: str, message: str, method: str = "message") -> str:
        at = parse_when(when)
        method = "call" if method == "call" else "message"
        item = store.add(at, message, method)
        how = "call you" if method == "call" else "message you"
        return f"Reminder {item['id']} set: I'll {how} at {at:%H:%M on %a %d %b} about: {message}"

    def list_reminders() -> str:
        items = store.pending()
        if not items:
            return "No reminders set."
        return "\n".join(f"{r['id']}: {r['when'].replace('T', ' ')} ({r['method']}) {r['message']}"
                         for r in items)

    def cancel_reminder(reminder_id: str) -> str:
        return "Cancelled." if store.cancel(reminder_id) else f"No reminder with id {reminder_id}."

    reg.register(Tool(
        "set_reminder",
        "Set a reminder that messages or phones the user later. Reminders are delivered while "
        "Jarvis is running.",
        {"type": "object", "properties": {
            "when": {"type": "string", "description":
                     "Local time: 'in 20 minutes', '17:30', 'tomorrow 08:00' or 'YYYY-MM-DD HH:MM'."},
            "message": {"type": "string"},
            "method": {"type": "string", "enum": ["message", "call"],
                       "description": "'call' phones the user; default 'message'."}},
         "required": ["when", "message"]},
        set_reminder))
    reg.register(Tool(
        "list_reminders", "List reminders that haven't gone off yet.",
        {"type": "object", "properties": {}}, list_reminders))
    reg.register(Tool(
        "cancel_reminder", "Cancel a reminder by its id.",
        {"type": "object", "properties": {"reminder_id": {"type": "string"}},
         "required": ["reminder_id"]}, cancel_reminder))


ASK_HUMAN_SPEC = {
    "name": "ask_human",
    "description": (
        "Ask the user a question and wait for their answer. Use this when you "
        "need a decision or missing information you cannot work out yourself."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
    },
}
