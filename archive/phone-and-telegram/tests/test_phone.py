"""Tests for Telegram, phone calls, SMS and reminders, using fakes (no network)."""
import re
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError

from jarvis.agent import Agent
from jarvis.brains import OfflineBrain
from jarvis.human import ScriptedHuman
from jarvis.phone import PhoneServer, compute_signature, valid_signature
from jarvis.reach import Reach, ReminderScheduler, ReminderStore, parse_when
from jarvis.telegram import TelegramHuman, handle_update
from jarvis.tools import build_default_tools

ME = "+447700900123"
TOKEN = "test-auth-token"


class FakeTelegram:
    def __init__(self, incoming=()):
        self.sent = []
        self.incoming = list(incoming)

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))

    def typing(self, chat_id):
        pass

    def get_updates(self, timeout=25):
        return [self.incoming.pop(0)] if self.incoming else []


class FakeTwilio:
    def __init__(self):
        self.calls, self.texts = [], []
        self.on_call = None

    def call(self, to, twiml):
        self.calls.append((to, twiml))
        if self.on_call:
            self.on_call(twiml)
        return "CA123"

    def sms(self, to, body):
        self.texts.append((to, body))
        return "SM123"


def update(chat_id, text):
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text}}


class EchoAgent:
    def __init__(self, delay=0):
        self.delay = delay

    def run(self, text):
        if self.delay:
            threading.Event().wait(self.delay)
        return f"You said {text}"


class TelegramTests(unittest.TestCase):
    def test_unknown_chat_ignored_and_setup_reply(self):
        tg = FakeTelegram()
        handle_update(update(42, "hello"), tg, EchoAgent(), chat_id=None)
        self.assertIn("Your chat ID is 42", tg.sent[0][1])
        handle_update(update(99, "hello"), tg, EchoAgent(), chat_id=42)
        self.assertEqual(len(tg.sent), 1)  # stranger ignored
        handle_update(update(42, "hello"), tg, EchoAgent(), chat_id=42)
        self.assertEqual(tg.sent[-1], (42, "You said hello"))

    def test_ask_human_over_telegram(self):
        tg = FakeTelegram([update(99, "not me"), update(42, "yes")])
        self.assertEqual(TelegramHuman(tg, 42, timeout_s=5).ask("Allow it?"), "yes")
        self.assertIn("Allow it?", tg.sent[0][1])


class PhoneServerTests(unittest.TestCase):
    def setUp(self):
        self.twilio = FakeTwilio()
        self.server = PhoneServer(auth_token=TOKEN, public_url="https://jarvis.example",
                                  my_number=ME, voice_agent=EchoAgent(), twilio=self.twilio,
                                  host="127.0.0.1", port=0, wait_s=2)
        self.server.start()

    def tearDown(self):
        self.server.stop()

    def post(self, path, params, sign=True):
        sig = compute_signature(TOKEN, "https://jarvis.example" + path, params) if sign else "bad"
        req = urllib.request.Request(f"http://127.0.0.1:{self.server.port}{path}",
                                     data=urllib.parse.urlencode(params).encode(),
                                     headers={"X-Twilio-Signature": sig})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode()

    def test_signature_roundtrip(self):
        sig = compute_signature(TOKEN, "https://a/b", {"x": "1"})
        self.assertTrue(valid_signature(TOKEN, "https://a/b", {"x": "1"}, sig))
        self.assertFalse(valid_signature(TOKEN, "https://a/b", {"x": "2"}, sig))

    def test_bad_signature_rejected(self):
        with self.assertRaises(HTTPError) as ctx:
            self.post("/voice/incoming", {"From": ME}, sign=False)
        self.assertEqual(ctx.exception.code, 403)

    def test_stranger_rejected(self):
        self.assertIn("<Reject/>", self.post("/voice/incoming", {"From": "+15550000000", "To": "+1"}))

    def test_call_jarvis_conversation(self):
        greeting = self.post("/voice/incoming", {"From": ME})
        self.assertIn("How can I help", greeting)
        reply = self.post("/voice/turn", {"From": ME, "SpeechResult": "what time is it"})
        self.assertIn("You said what time is it", reply)
        self.assertIn("<Gather", reply)
        self.assertIn("Goodbye", self.post("/voice/turn", {"From": ME, "SpeechResult": "bye"}))

    def test_slow_answer_uses_redirect(self):
        self.server.voice_agent = EchoAgent(delay=3)
        first = self.post("/voice/turn", {"From": ME, "SpeechResult": "think hard"})
        self.assertIn("One moment", first)
        wait_path = re.search(r"https://jarvis\.example(/voice/wait\?job=\w+)", first).group(1)
        self.assertIn("You said think hard", self.post(wait_path, {"From": ME}))

    def test_jarvis_calls_and_hears_answer(self):
        def answer(twiml):
            path = re.search(r"https://jarvis\.example(/voice/answer\?q=\w+)", twiml).group(1)
            threading.Timer(0.2, self.post, (path, {"To": ME, "SpeechResult": "the blue one"})).start()
        self.twilio.on_call = answer
        self.assertEqual(self.server.ask_by_call("Which one?", timeout_s=5), "the blue one")

    def test_sms_reply(self):
        self.post("/sms", {"From": ME, "Body": "hello"})
        for _ in range(50):
            if self.twilio.texts:
                break
            threading.Event().wait(0.05)
        self.assertEqual(self.twilio.texts[0], (ME, "You said hello"))


class ReachAndReminderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tg, self.twilio = FakeTelegram(), FakeTwilio()
        self.reach = Reach(self.tg, 42, self.twilio, ME)
        self.store = ReminderStore(self.tmp / "reminders.json")

    def test_parse_when(self):
        now = datetime(2026, 10, 15, 12, 0)
        self.assertEqual(parse_when("in 20 minutes", now), now + timedelta(minutes=20))
        self.assertEqual(parse_when("17:30", now), datetime(2026, 10, 15, 17, 30))
        self.assertEqual(parse_when("09:00", now), datetime(2026, 10, 16, 9, 0))
        self.assertEqual(parse_when("tomorrow 08:00", now), datetime(2026, 10, 16, 8, 0))
        self.assertEqual(parse_when("2026-10-20 09:15", now), datetime(2026, 10, 20, 9, 15))
        with self.assertRaises(ValueError):
            parse_when("whenever", now)

    def test_tools_message_call_and_remind(self):
        agent = Agent(OfflineBrain(), build_default_tools(self.tmp, self.reach, self.store),
                      ScriptedHuman([]), self.tmp / "logs")
        agent.run("text me buy bread")
        self.assertEqual(self.tg.sent[-1], (42, "buy bread"))
        agent.run("call me")
        self.assertEqual(self.twilio.calls[-1][0], ME)
        self.assertIn("set", agent.run("remind me in 5 minutes to stretch"))
        self.assertIn("stretch", agent.run("list reminders"))

    def test_scheduler_delivers_due_reminders(self):
        self.store.add(datetime.now() - timedelta(seconds=1), "stretch")
        self.store.add(datetime.now() - timedelta(seconds=1), "meeting", method="call")
        self.store.add(datetime.now() + timedelta(hours=1), "later")
        self.assertEqual(ReminderScheduler(self.store, self.reach).deliver_due(), 2)
        self.assertEqual(self.tg.sent[-1], (42, "Reminder: stretch"))
        self.assertIn("Reminder: meeting", self.twilio.calls[-1][1])
        self.assertEqual([r["message"] for r in self.store.pending()], ["later"])

    def test_message_falls_back_to_sms(self):
        reach = Reach(None, None, self.twilio, ME)
        reach.message("hi")
        self.assertEqual(self.twilio.texts[-1], (ME, "hi"))


if __name__ == "__main__":
    unittest.main()
