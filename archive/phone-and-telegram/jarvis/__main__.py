"""Jarvis command line.

    python -m jarvis              chat in the terminal
    python -m jarvis "text"       say one thing and exit
    python -m jarvis setup        answer a few questions to fill in .env
    python -m jarvis check        show what's set up and what's missing
    python -m jarvis serve        run Jarvis for your phone (Telegram, calls, texts, reminders)
    python -m jarvis message "hi" send yourself a test message
    python -m jarvis call "hi"    make Jarvis phone you (test call)
"""
from __future__ import annotations

import logging
import sys
import threading

from .agent import Agent
from .brains import make_brain
from .config import Config, load_config
from .human import TerminalHuman, make_channel
from .phone import PhoneServer, TwilioClient, Voice
from .reach import Reach, ReminderScheduler, ReminderStore
from .tools import build_default_tools

COMMANDS = {"setup", "check", "serve", "message", "call", "chat"}


def setup_logging(log_dir, also_console: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(log_dir / "jarvis.log")]
    if also_console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def brain_label(cfg: Config) -> str:
    return f"Claude ({cfg.model})" if cfg.brain_mode == "claude" else "offline (no API key yet)"


def build_reach(cfg: Config, fallback=None):
    telegram = twilio = None
    if cfg.telegram_ready:
        from .telegram import TelegramClient
        telegram = TelegramClient(cfg.telegram_token)
    if cfg.twilio_ready:
        twilio = TwilioClient(cfg.twilio_sid, cfg.twilio_token, cfg.twilio_number)
    voice = Voice(cfg.voice, cfg.voice_language)
    return Reach(telegram, cfg.telegram_chat_id, twilio, cfg.my_phone, voice, fallback), telegram, twilio


def make_agent(cfg: Config, brain, reach, store, human) -> Agent:
    return Agent(brain=brain, tools=build_default_tools(cfg.data_dir, reach, store),
                 human=human, log_dir=cfg.log_dir, max_steps=cfg.max_steps)


# --- commands ---------------------------------------------------------------

def cmd_chat(cfg: Config, one_shot: str | None) -> int:
    setup_logging(cfg.log_dir)
    reach, _, _ = build_reach(cfg, fallback=lambda t: print(f"\n[Jarvis] {t}\nYou: ", end=""))
    store = ReminderStore(cfg.data_dir / "reminders.json")
    agent = make_agent(cfg, make_brain(cfg.api_key, cfg.model), reach, store,
                       make_channel(cfg.human_channel, cfg.ntfy_topic, cfg.ntfy_server))
    if one_shot:
        print(agent.run(one_shot))
        return 0
    ReminderScheduler(store, reach).start()
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


def cmd_serve(cfg: Config) -> int:
    setup_logging(cfg.log_dir, also_console=True)
    log = logging.getLogger("jarvis")
    if not (cfg.telegram_ready or cfg.twilio_ready):
        print("Nothing to serve yet: set up Telegram and/or Twilio first. Run: python -m jarvis check")
        return 1
    reach, telegram, twilio = build_reach(cfg)
    store = ReminderStore(cfg.data_dir / "reminders.json")
    brain = make_brain(cfg.api_key, cfg.model)
    log.info("Brain: %s", brain_label(cfg))

    if cfg.phone_server_ready:
        # On a call Jarvis can't stop to ask you something else, so questions and
        # confirmations are declined rather than guessed.
        no_human = type("NoHuman", (), {"ask": staticmethod(lambda q: None)})()
        server = PhoneServer(
            auth_token=cfg.twilio_token, public_url=cfg.public_url, my_number=cfg.my_phone,
            voice_agent=make_agent(cfg, brain, reach, store, no_human),
            sms_agent=make_agent(cfg, brain, reach, store, no_human),
            twilio=twilio, voice=Voice(cfg.voice, cfg.voice_language), port=cfg.port)
        server.start()
        reach.phone_server = server
        try:
            twilio.point_number_at(cfg.public_url)
            log.info("Calls and texts to %s now reach Jarvis", cfg.twilio_number)
        except Exception as exc:
            log.warning("Couldn't update the Twilio number's webhooks automatically (%s). "
                        "Set them by hand: Voice -> %s/voice/incoming, Messaging -> %s/sms",
                        exc, cfg.public_url, cfg.public_url)
    elif cfg.twilio_ready:
        log.info("Twilio is set up for Jarvis calling you. To call Jarvis or text it, "
                 "also set JARVIS_PUBLIC_URL (see README).")

    ReminderScheduler(store, reach).start()

    if telegram:
        from .telegram import TelegramHuman, run_bot
        human = TelegramHuman(telegram, cfg.telegram_chat_id) if cfg.telegram_chat_id else TerminalHuman()
        agent = make_agent(cfg, brain, reach, store, human)
        if not cfg.telegram_chat_id:
            log.info("Send your bot any message on Telegram; it will reply with your chat ID.")
        print("Jarvis is serving. Message your bot on Telegram. Press Ctrl+C to stop.")
        try:
            run_bot(telegram, agent, cfg.telegram_chat_id)
        except KeyboardInterrupt:
            pass
        return 0

    print("Jarvis is serving phone calls and texts. Press Ctrl+C to stop.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_message(cfg: Config, text: str) -> int:
    setup_logging(cfg.log_dir)
    reach, _, _ = build_reach(cfg)
    try:
        print(reach.message(text or "Hello from Jarvis."))
        return 0
    except Exception as exc:
        print(f"Couldn't send: {exc}")
        return 1


def cmd_call(cfg: Config, text: str) -> int:
    setup_logging(cfg.log_dir)
    reach, _, _ = build_reach(cfg)
    try:
        print(reach.call(text or "Hello, this is Jarvis. Your phone setup works."))
        return 0
    except Exception as exc:
        print(f"Couldn't call: {exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv and argv[0] in COMMANDS else "chat"
    rest = " ".join(argv[1:] if argv and argv[0] in COMMANDS else argv)

    if cmd == "setup":
        from .setup import run_setup
        return run_setup()
    cfg = load_config()
    if cmd == "check":
        from .setup import run_check
        return run_check(cfg)
    if cmd == "serve":
        return cmd_serve(cfg)
    if cmd == "message":
        return cmd_message(cfg, rest)
    if cmd == "call":
        return cmd_call(cfg, rest)
    return cmd_chat(cfg, rest or None)


if __name__ == "__main__":
    sys.exit(main())
