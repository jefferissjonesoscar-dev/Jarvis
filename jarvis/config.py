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
    data_dir: Path
    log_dir: Path
    port: int = 8765
    max_steps: int = 8

    @property
    def brain_mode(self) -> str:
        return "claude" if self.api_key else "offline"


def remove_example_files(root: Path = ROOT) -> None:
    """Jarvis keeps all settings in .env only, so tidy away any .env.example.
    If there's no .env yet, the example becomes the .env so nothing is lost."""
    for example in [root / ".env.example", *root.glob("archive/*/.env.example")]:
        try:
            if example.parent == root and not (root / ".env").exists():
                example.rename(root / ".env")
            elif example.exists():
                example.unlink()
        except OSError:
            pass


def load_config(env_file: Path | None = None) -> Config:
    if env_file is None:
        remove_example_files()
    _load_dotenv(env_file or ENV_FILE)
    return Config(
        api_key=_get("ANTHROPIC_API_KEY"),
        model=_get("JARVIS_MODEL", "claude-sonnet-5-5"),
        data_dir=Path(_get("JARVIS_DATA_DIR", str(ROOT / "data"))),
        log_dir=Path(_get("JARVIS_LOG_DIR", str(ROOT / "logs"))),
        port=int(_get("JARVIS_PORT", "8765")),
    )
