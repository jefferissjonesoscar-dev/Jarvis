# Jarvis

Your personal assistant, with its own chat screen. It runs on your computer and
opens in your browser. Type to it, or click the microphone and talk.

With no key at all, Jarvis runs in "offline mode" so you can try it straight away.
Add an Anthropic API key and it switches to the full Claude brain.

## Step 1. Install (once)

You need Python 3.10 or newer ([python.org](https://www.python.org/downloads/);
on Windows tick "Add Python to PATH"). Open this folder in VS Code by
double-clicking `Jarvis.code-workspace`, open a terminal (Terminal > New Terminal)
and run:

```
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

If `py` isn't found, use `python` instead. On Mac or Linux use
`python3 -m venv .venv` and `.venv/bin/python -m pip install -r requirements.txt`.

## Step 2. Run it

In VS Code press Ctrl+Shift+D, pick **Run Jarvis** at the top and press F5.
Your browser opens the Jarvis chat screen at http://127.0.0.1:8765. To stop
Jarvis, press the red square in VS Code (or Ctrl+C in its terminal).

On the chat screen:

- Type and press Enter, or click a quick button on the left.
- Click the microphone to talk (works in Chrome and Edge).
- Click **VOICE OFF** to switch it on, and Jarvis reads its replies out loud.

## Step 3. Add your Claude key

1. Get a key at [console.anthropic.com](https://console.anthropic.com) under API Keys.
   It starts with `sk-ant-api`.
2. In VS Code's Run list pick **Jarvis: setup (add your key)**, press F5 and paste
   the key. Nothing shows while you paste; that's normal. Press Enter.
3. Run **Jarvis: check**. It should say `Brain: Claude`.
4. Run **Jarvis** again.

All your settings live in one file called `.env` in this folder. Running setup
again rewrites it cleanly and keeps your key. Never share `.env`.

## Things you can ask

With Claude switched on, just talk normally. In offline mode it knows:

- "What time is it?"
- "calculate 12 * 7"
- "note buy milk" / "list my notes" / "clear my notes" (asks you first)
- "ask me something"

## Test it

```
.venv\Scripts\python -m unittest discover -s tests
```

It should end with `OK`. You can also use the flask icon in VS Code's sidebar.

## What's inside

```
jarvis/
  __main__.py   starts Jarvis (chat screen, terminal, setup, check)
  web.py        the chat screen's server (only reachable from this computer)
  ui/index.html the chat screen itself
  agent.py      the loop: think, use tools, repeat; confirmations; action log
  brains.py     Claude brain, plus the offline stand-in
  tools.py      the allowlist: everything Jarvis can do, one function each
  human.py      how Jarvis asks you questions in the terminal
  setup.py      setup wizard and checker
  config.py     reads .env
tests/          run with the command above
archive/        the older version with Telegram, phone calls and texts, kept for later
logs/           jarvis.log and tool_calls.jsonl (every action Jarvis took)
data/           your notes
```

## Add a new ability

Write a function in `build_default_tools` in `tools.py` and register it:

```python
def open_website(url: str) -> str:
    import webbrowser
    webbrowser.open(url)
    return f"Opened {url}"

reg.register(Tool(
    "open_website", "Open a web page in the default browser.",
    {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    open_website))
```

Add `confirm=True` for anything that deletes or spends money. Jarvis then asks you
in the chat before it runs.

## Safety built in

- Jarvis can only use the tools in `tools.py`. There is no open shell.
- Destructive tools need your yes.
- The chat screen only listens on this computer (127.0.0.1).
- Every action is logged to `logs/tool_calls.jsonl`.
- Your key lives only in `.env`.
- Old conversation is trimmed automatically so costs don't creep up.
