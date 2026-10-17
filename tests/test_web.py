"""Tests for the chat screen's server. Run with: python -m unittest discover -s tests"""
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from jarvis.agent import Agent
from jarvis.brains import OfflineBrain
from jarvis.tools import build_default_tools
from jarvis import voice
from jarvis.web import ChatSession, make_handler


class WebTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        session = ChatSession(lambda human: Agent(OfflineBrain(), build_default_tools(tmp / "data"),
                                                  human, tmp / "logs"))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(session, "offline"))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def chat(self, text):
        req = urllib.request.Request(self.base + "/api/chat", data=json.dumps({"text": text}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def test_page_and_status(self):
        with urllib.request.urlopen(self.base + "/", timeout=10) as r:
            self.assertIn(b"JARVIS", r.read())
        with urllib.request.urlopen(self.base + "/api/status", timeout=10) as r:
            self.assertEqual(json.loads(r.read())["brain"], "offline")

    def test_voice_page(self):
        with urllib.request.urlopen(self.base + "/voice", timeout=10) as r:
            page = r.read()
        self.assertIn(b"orb", page)
        self.assertIn(b'href="/"', page)
        with urllib.request.urlopen(self.base + "/", timeout=10) as r:
            self.assertIn(b'href="/voice"', r.read())

    def test_reply(self):
        reply = self.chat("calculate 6 * 7")
        self.assertEqual(reply["type"], "reply")
        self.assertIn("= 42", reply["text"])

    def test_question_then_answer(self):
        ask = self.chat("ask me something")
        self.assertEqual(ask["type"], "ask")
        reply = self.chat("the garden")
        self.assertEqual(reply["type"], "reply")
        self.assertIn("the garden", reply["text"])

    def test_confirmation_in_chat(self):
        self.chat("note buy milk")
        self.assertEqual(self.chat("clear my notes")["type"], "ask")
        self.assertIn("Deleted 1", self.chat("yes")["text"])

    def test_speak_returns_audio(self):
        real = voice.synthesize
        voice.synthesize = lambda text, v: b"ID3fake-mp3"
        try:
            req = urllib.request.Request(self.base + "/api/speak",
                                         data=json.dumps({"text": "hi", "voice": "en-GB-RyanNeural"}).encode())
            with urllib.request.urlopen(req, timeout=10) as r:
                self.assertEqual(r.headers["Content-Type"], "audio/mpeg")
                self.assertEqual(r.read(), b"ID3fake-mp3")
        finally:
            voice.synthesize = real

    def test_status_lists_voices(self):
        with urllib.request.urlopen(self.base + "/api/status", timeout=10) as r:
            status = json.loads(r.read())
        self.assertEqual(status["default_voice"], "en-GB-RyanNeural")
        self.assertTrue(any(v["id"] == "en-GB-RyanNeural" for v in status["voices"]))


if __name__ == "__main__":
    unittest.main()
