"""`python -m jarvis setup` (fill in .env by answering questions) and
`python -m jarvis check` (see what's working)."""
from __future__ import annotations

import getpass

from .config import ENV_FILE, Config, read_env_file

FIELDS = [
    ("ANTHROPIC_API_KEY", "Claude", "Your Anthropic API key (starts with sk-ant-). From console.anthropic.com.", True),
    ("JARVIS_TELEGRAM_TOKEN", "Telegram", "Bot token from @BotFather in Telegram (looks like 123456:ABC...).", True),
    ("JARVIS_TELEGRAM_CHAT_ID", "Telegram", "Your chat ID. Leave blank now; your bot tells you it the first time you message it.", False),
    ("TWILIO_ACCOUNT_SID", "Phone", "Twilio Account SID (starts with AC). From console.twilio.com.", False),
    ("TWILIO_AUTH_TOKEN", "Phone", "Twilio Auth Token. Same page as the SID.", True),
    ("TWILIO_PHONE_NUMBER", "Phone", "The Twilio number you bought, with country code, e.g. +441234567890.", False),
    ("JARVIS_MY_PHONE_NUMBER", "Phone", "YOUR mobile number with country code, e.g. +447700900123. Only this number can use Jarvis.", False),
    ("JARVIS_PUBLIC_URL", "Phone", "Public https address for this computer, e.g. your ngrok address. Needed to call or text Jarvis.", False),
]

TEMPLATE_EXTRAS = """
# Optional settings
JARVIS_MODEL={JARVIS_MODEL}
JARVIS_VOICE={JARVIS_VOICE}
JARVIS_VOICE_LANGUAGE={JARVIS_VOICE_LANGUAGE}
JARVIS_PORT={JARVIS_PORT}
"""


def _mask(value: str, secret: bool) -> str:
    if not value:
        return "not set"
    return value[:4] + "..." + value[-3:] if secret and len(value) > 10 else value


def run_setup() -> int:
    values = read_env_file(ENV_FILE)
    print("Jarvis setup. Press Enter to keep the current value, or type '-' to clear it.")
    print("Everything is optional: with nothing filled in, Jarvis runs offline in the terminal.\n")
    section = None
    for key, sect, help_text, secret in FIELDS:
        if sect != section:
            section = sect
            print(f"--- {sect} ---")
        current = values.get(key, "")
        print(help_text)
        prompt = f"{key} [{_mask(current, secret)}]: "
        try:
            answer = (getpass.getpass(prompt) if secret else input(prompt)).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSetup cancelled; nothing saved.")
            return 1
        if answer == "-":
            values[key] = ""
        elif answer:
            values[key] = answer.rstrip("/") if key == "JARVIS_PUBLIC_URL" else answer
        print()

    defaults = {"JARVIS_MODEL": "claude-sonnet-5-5", "JARVIS_VOICE": "Polly.Brian",
                "JARVIS_VOICE_LANGUAGE": "en-GB", "JARVIS_PORT": "8080"}
    extras = {k: values.get(k) or v for k, v in defaults.items()}
    lines = ["# Jarvis settings. Keep this file private; it holds your keys."]
    section = None
    for key, sect, _, _ in FIELDS:
        if sect != section:
            section = sect
            lines.append(f"\n# {sect}")
        lines.append(f"{key}={values.get(key, '')}")
    known = {f[0] for f in FIELDS} | set(defaults)
    others = {k: v for k, v in values.items() if k not in known}
    text = "\n".join(lines) + "\n" + TEMPLATE_EXTRAS.format(**extras)
    text += "".join(f"{k}={v}\n" for k, v in others.items())
    ENV_FILE.write_text(text)
    try:
        ENV_FILE.chmod(0o600)
    except OSError:
        pass
    print(f"Saved to {ENV_FILE}. Next: python -m jarvis check")
    return 0


def run_check(cfg: Config) -> int:
    ok, todo = "OK  ", "--  "
    print("Jarvis setup check\n")
    if cfg.api_key:
        try:
            import anthropic  # noqa: F401
            print(f"{ok}Brain: Claude ({cfg.model})")
        except ImportError:
            print(f"{todo}Brain: API key found, but run: pip install -r requirements.txt")
    else:
        print(f"{todo}Brain: offline mode. Add ANTHROPIC_API_KEY to use Claude.")
        example = ENV_FILE.with_name(".env.example")
        if not ENV_FILE.exists() and read_env_file(example).get("ANTHROPIC_API_KEY"):
            print("    Your key is in .env.example, but Jarvis only reads .env.")
            print("    Rename .env.example to .env (right-click it in VS Code, Rename).")

    if not cfg.telegram_token:
        print(f"{todo}Telegram messaging: add JARVIS_TELEGRAM_TOKEN (README step 3).")
    else:
        try:
            from .telegram import TelegramClient
            me = TelegramClient(cfg.telegram_token).get_me()
            name = f"@{me.get('username')}"
        except Exception as exc:
            name = f"(couldn't reach Telegram: {exc})"
        if cfg.telegram_chat_id:
            print(f"{ok}Telegram messaging: bot {name}, locked to chat {cfg.telegram_chat_id}")
        else:
            print(f"{todo}Telegram: bot {name} found. Run `python -m jarvis serve`, message the bot, "
                  "and put the chat ID it sends you into JARVIS_TELEGRAM_CHAT_ID.")

    missing = [k for k, v in [("TWILIO_ACCOUNT_SID", cfg.twilio_sid), ("TWILIO_AUTH_TOKEN", cfg.twilio_token),
                              ("TWILIO_PHONE_NUMBER", cfg.twilio_number),
                              ("JARVIS_MY_PHONE_NUMBER", cfg.my_phone)] if not v]
    if missing:
        print(f"{todo}Jarvis calls you: add {', '.join(missing)} (README step 4).")
    else:
        print(f"{ok}Jarvis calls you: from {cfg.twilio_number} to {cfg.my_phone}")
    if cfg.phone_server_ready:
        print(f"{ok}You call / text Jarvis: webhooks at {cfg.public_url}")
    else:
        print(f"{todo}You call / text Jarvis: needs Twilio plus JARVIS_PUBLIC_URL (README step 5).")
    print("\nWhen something is set up, start Jarvis for your phone with: python -m jarvis serve")
    return 0
