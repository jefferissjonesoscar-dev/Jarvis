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

def build_default_tools(data_dir: Path) -> ToolRegistry:
    """The allowlist. Add new capabilities here, one function each."""
    notes_file = data_dir / "notes.json"

    def _read_notes() -> list[dict]:
        if notes_file.exists():
            return json.loads(notes_file.read_text(encoding="utf-8"))
        return []

    def _write_notes(notes: list[dict]) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        notes_file.write_text(json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8")

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
        "add_note", "Save a short note for the user.",
        {"type": "object", "properties": {"text": {"type": "string"}},
         "required": ["text"]}, add_note))
    reg.register(Tool(
        "list_notes", "List all of the user's saved notes.",
        {"type": "object", "properties": {}}, list_notes))
    reg.register(Tool(
        "clear_notes", "Delete ALL saved notes. Destructive; the user is asked to confirm.",
        {"type": "object", "properties": {}}, clear_notes, confirm=True))

    return reg


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
