"""Settings, read from environment variables (and the .env file).

Secrets never live in code. Put them in .env (git-ignored) or your shell.
Run `python -m jarvis setup` to fill .env in by answering questions.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _load_dotenv(path: Path) -> None:
    """Existing environment variables always win over the file."""
    for key, value in read_env_file(path).items():
        os.environ.setdefault(key, value)


def _get(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass
class Config:
    api_key: str | None
    model: str
    human_channel: str
    ntfy_topic: str | None
    ntfy_server: str
    data_dir: Path
    log_dir: Path
    # Telegram (two-way messaging)
    telegram_token: str | None = None
    telegram_chat_id: int | None = None
    # Twilio (phone calls and SMS)
    twilio_sid: str | None = None
    twilio_token: str | None = None
    twilio_number: str | None = None
    my_phone: str | None = None
    public_url: str | None = None
    port: int = 8080
    voice: str = "Polly.Brian"
    voice_language: str = "en-GB"
    max_steps: int = 8

    @property
    def brain_mode(self) -> str:
        return "claude" if self.api_key else "offline"

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_token)

    @property
    def twilio_ready(self) -> bool:
        return bool(self.twilio_sid and self.twilio_token and self.twilio_number and self.my_phone)

    @property
    def phone_server_ready(self) -> bool:
        return self.twilio_ready and bool(self.public_url)


def load_config(env_file: Path | None = None) -> Config:
    _load_dotenv(env_file or ENV_FILE)
    chat_id = _get("JARVIS_TELEGRAM_CHAT_ID")
    return Config(
        api_key=_get("ANTHROPIC_API_KEY"),
        model=_get("JARVIS_MODEL", "claude-sonnet-5-5"),
        human_channel=_get("JARVIS_HUMAN_CHANNEL", "terminal"),
        ntfy_topic=_get("JARVIS_NTFY_TOPIC"),
        ntfy_server=_get("JARVIS_NTFY_SERVER", "https://ntfy.sh"),
        data_dir=Path(_get("JARVIS_DATA_DIR", str(ROOT / "data"))),
        log_dir=Path(_get("JARVIS_LOG_DIR", str(ROOT / "logs"))),
        telegram_token=_get("JARVIS_TELEGRAM_TOKEN"),
        telegram_chat_id=int(chat_id) if chat_id and chat_id.lstrip("-").isdigit() else None,
        twilio_sid=_get("TWILIO_ACCOUNT_SID"),
        twilio_token=_get("TWILIO_AUTH_TOKEN"),
        twilio_number=_get("TWILIO_PHONE_NUMBER"),
        my_phone=_get("JARVIS_MY_PHONE_NUMBER"),
        public_url=(_get("JARVIS_PUBLIC_URL") or "").rstrip("/") or None,
        port=int(_get("JARVIS_PORT", "8080")),
        voice=_get("JARVIS_VOICE", "Polly.Brian"),
        voice_language=_get("JARVIS_VOICE_LANGUAGE", "en-GB"),
    )
