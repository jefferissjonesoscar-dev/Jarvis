# Jarvis

Your personal assistant. Talk to it in the terminal, text it on Telegram, phone
it, and let it phone or message you with reminders and questions.

All the code is written. You only add your own keys, and every feature switches
on by itself when its keys are filled in. With no keys at all, Jarvis still runs
in "offline mode" so you can try it straight away.

| Feature | What you need | Cost |
| --- | --- | --- |
| Smart brain (Claude) | Anthropic API key | Pay per use, usually small for one person |
| Text Jarvis back and forth | A Telegram bot token | Free |
| Jarvis phones you | A Twilio account and number | About $1 to $2 a month for the number, plus about 1 to 2 cents a minute |
| You phone or SMS Jarvis | Twilio, plus a public web address (ngrok, free) | Same as above |

Prices are approximate; check each provider's site.

## Step 1. Install

You need Python 3.10 or newer ([python.org](https://www.python.org/downloads/);
on Windows tick "Add Python to PATH"). Then in a terminal, inside this `jarvis` folder:

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# Mac / Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

(On Mac/Linux, use `python3` if `python` isn't found.)

## Step 2. Add your Claude key and try it

1. Get a key at [console.anthropic.com](https://console.anthropic.com) (Settings, API keys).
2. Run the setup wizard. It asks for each key; press Enter to skip any you don't have yet.

   ```bash
   python -m jarvis setup
   ```
3. Check everything, then chat:

   ```bash
   python -m jarvis check
   python -m jarvis
   ```

The first line tells you whether the Claude brain is on. That's all you need for
the terminal version.

## Step 3. Text Jarvis on Telegram (free)

1. In Telegram, message **@BotFather**, send `/newbot`, pick a name. It gives you a token.
2. Run `python -m jarvis setup` and paste the token at `JARVIS_TELEGRAM_TOKEN`.
3. Run `python -m jarvis serve`, then send your new bot any message.
   It replies with your chat ID.
4. Run `python -m jarvis setup` again and put that number in `JARVIS_TELEGRAM_CHAT_ID`.
   This locks the bot so it only ever answers you.
5. Run `python -m jarvis serve` again. Now just chat with it.

Jarvis also uses Telegram to ask you things, ask for a yes before anything
destructive, and send your reminders.

## Step 4. Let Jarvis phone you (Twilio)

1. Sign up at [twilio.com](https://www.twilio.com) and buy a phone number with
   voice (and SMS if you want texts). Some countries ask for ID or an address first.
2. Run `python -m jarvis setup` and fill in the Account SID, Auth Token, your
   Twilio number and **your own mobile number**, both with country code (`+44...`, `+1...`).
3. Test it: `python -m jarvis call "Hello, this is Jarvis"`. Your phone should ring.

Now "call me", "call me in 30 minutes about the meeting" and urgent questions can
ring your phone. On a free Twilio trial, calls start with a short Twilio message and
can only go to numbers you've verified.

## Step 5. Phone or text Jarvis (optional)

For Twilio to reach Jarvis, your computer needs a public web address. ngrok gives
you one for free:

1. Install ngrok from [ngrok.com](https://ngrok.com/download), sign up, and claim
   your free static domain on the ngrok dashboard.
2. Start it: `ngrok http --url=YOUR-DOMAIN.ngrok-free.app 8080`
3. Run `python -m jarvis setup` and put `https://YOUR-DOMAIN.ngrok-free.app` in `JARVIS_PUBLIC_URL`.
4. Run `python -m jarvis serve`. Jarvis points your Twilio number at itself
   automatically. Ring your Twilio number and talk; say "goodbye" to hang up.
   Texts to that number get a text back.

Only calls and texts from your own number are answered, and every request is
checked against Twilio's signature, so nobody else can use your Jarvis.

## Everyday use

```bash
python -m jarvis            # chat in the terminal
python -m jarvis serve      # run for your phone (keep this running)
python -m jarvis check      # see what's set up
python -m jarvis message "hi"   # send yourself a test message
python -m jarvis call "hi"      # make Jarvis ring you
```

Jarvis only works while `serve` is running on a computer that's switched on. To
have it always available, run it on a computer that stays on, a Raspberry Pi, or a
small cloud server.

Things you can ask (with Claude switched on, just talk normally):

- "What's 15% of 240?"
- "Note that the plumber comes Tuesday" / "What are my notes?"
- "Remind me at 17:30 to call Sam" / "Call me in 20 minutes to remind me about the oven"
- "Text me the shopping list"
- "Clear my notes" (asks you first)

## What's inside

```
jarvis/
  __main__.py   the commands above
  agent.py      the loop: think, use tools, repeat; confirmations; audit log
  brains.py     Claude brain, plus the offline stand-in
  tools.py      the allowlist: everything Jarvis can do, one function each
  telegram.py   Telegram bot
  phone.py      Twilio calls, SMS and the webhook server
  reach.py      how Jarvis contacts you; reminders
  human.py      how Jarvis asks you questions in the terminal (or ntfy)
  setup.py      setup wizard and checker
  config.py     reads .env
tests/          19 tests; run with: python -m unittest discover -s tests
logs/           jarvis.log and tool_calls.jsonl (every action Jarvis took)
data/           notes and reminders
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

Add `confirm=True` for anything that deletes, spends money or sends messages to
other people. Jarvis then asks you before it runs.

## Safety built in

- Jarvis can only use the tools in `tools.py`. There is no open shell.
- Destructive tools need your yes. During a phone call it can't ask, so it declines them.
- Telegram, calls and texts only answer you.
- Every action is logged to `logs/tool_calls.jsonl`.
- Keys live only in `.env`, which is never shared or committed.
- Old conversation is trimmed automatically so costs don't creep up.
