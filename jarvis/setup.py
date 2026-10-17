"""`python -m jarvis setup` (save your Claude key into .env) and
`python -m jarvis check` (see what's working)."""
from __future__ import annotations

import getpass

from .config import ENV_FILE, Config, read_env_file

DEFAULTS = {"JARVIS_MODEL": "claude-sonnet-5-5", "JARVIS_PORT": "8765"}


def _mask(value: str) -> str:
    if not value:
        return "not set"
    return value[:7] + "..." + value[-3:] if len(value) > 12 else "set"


def run_setup() -> int:
    values = read_env_file(ENV_FILE)
    print("Jarvis setup. Paste your Anthropic API key (it starts with sk-ant-),")
    print("from console.anthropic.com > API Keys. Nothing shows while you paste; that's normal.")
    print("Press Enter to keep the current key, or type '-' to remove it.\n")
    current = values.get("ANTHROPIC_API_KEY", "")
    try:
        answer = getpass.getpass(f"ANTHROPIC_API_KEY [{_mask(current)}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled; nothing saved.")
        return 1
    if answer == "-":
        values["ANTHROPIC_API_KEY"] = ""
    elif answer:
        values["ANTHROPIC_API_KEY"] = answer

    lines = ["# Jarvis settings. Keep this file private; it holds your key.",
             "", "# Claude (the brain). Blank = offline mode.",
             f"ANTHROPIC_API_KEY={values.get('ANTHROPIC_API_KEY', '')}", "", "# Optional settings"]
    lines += [f"{k}={values.get(k) or v}" for k, v in DEFAULTS.items()]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        ENV_FILE.chmod(0o600)
    except OSError:
        pass
    print(f"\nSaved to {ENV_FILE}. Next: run Jarvis: check")
    return 0


def run_check(cfg: Config) -> int:
    ok, todo = "OK  ", "--  "
    print("Jarvis setup check\n")
    if cfg.api_key:
        try:
            import anthropic  # noqa: F401
            print(f"{ok}Brain: Claude ({cfg.model})")
        except ImportError:
            print(f"{todo}Brain: API key found, but run: .venv\\Scripts\\python -m pip install -r requirements.txt")
            return 0
        if not cfg.api_key.startswith("sk-ant-api"):
            print("    Note: Claude API keys usually start with sk-ant-api. If Jarvis says the key")
            print("    is invalid, make a new one at console.anthropic.com > API Keys.")
    else:
        print(f"{todo}Brain: offline mode. Add ANTHROPIC_API_KEY to use Claude.")
    print("\nThis was only a check; Jarvis is not running yet.")
    print("To start it, pick Run Jarvis in VS Code's Run list and press F5.")
    print("Your browser then opens the chat screen by itself. Keep VS Code open while you use it.")
    return 0
