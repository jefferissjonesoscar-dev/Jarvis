"""Jarvis command line.

    python -m jarvis              open the Jarvis chat screen in your browser
    python -m jarvis terminal     chat in the terminal instead
    python -m jarvis "text"       say one thing and exit
    python -m jarvis setup        save your Claude key into .env
    python -m jarvis check        show what's set up and what's missing
"""
from __future__ import annotations

import logging
import sys

from .agent import Agent
from .brains import make_brain
from .config import Config, load_config
from .human import TerminalHuman
from .tools import build_default_tools

COMMANDS = {"setup", "check", "terminal", "web"}


def setup_logging(log_dir, also_console: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(log_dir / "jarvis.log", encoding="utf-8")]
    if also_console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def brain_label(cfg: Config) -> str:
    return f"Claude ({cfg.model})" if cfg.brain_mode == "claude" else "offline (no API key yet)"


def make_agent(cfg: Config, human) -> Agent:
    return Agent(brain=make_brain(cfg.api_key, cfg.model), tools=build_default_tools(cfg.data_dir),
                 human=human, log_dir=cfg.log_dir, max_steps=cfg.max_steps)


def cmd_terminal(cfg: Config, one_shot: str | None) -> int:
    setup_logging(cfg.log_dir)
    agent = make_agent(cfg, TerminalHuman())
    if one_shot:
        print(agent.run(one_shot))
        return 0
    print(f"Jarvis is online. Brain: {brain_label(cfg)}. Type 'quit' to exit.")
    while True:
        try:
            text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text.lower() in {"quit", "exit", "bye"}:
            break
        if text:
            try:
                print(f"Jarvis: {agent.run(text)}")
            except Exception as exc:
                logging.getLogger("jarvis").exception("Agent failed")
                print(f"Jarvis: Sorry, something went wrong: {exc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv and argv[0] in COMMANDS else ("terminal" if argv else "web")
    rest = " ".join(argv[1:] if argv and argv[0] in COMMANDS else argv)

    if cmd == "setup":
        from .setup import run_setup
        return run_setup()
    cfg = load_config()
    if cmd == "check":
        from .setup import run_check
        return run_check(cfg)
    if cmd == "web":
        from .web import serve
        setup_logging(cfg.log_dir)
        return serve(cfg, lambda human: make_agent(cfg, human), brain_label(cfg))
    return cmd_terminal(cfg, rest or None)


if __name__ == "__main__":
    sys.exit(main())
