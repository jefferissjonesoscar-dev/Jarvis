"""The Jarvis chat screen: a small web server on your own computer.

It only listens on 127.0.0.1, so nothing outside this computer can reach it.
There are two pages: the chat screen (ui/index.html, at /) and voice mode
(ui/voice.html, at /voice), where you just talk and Jarvis answers out loud.
Both talk to these endpoints:

    GET  /api/status   brain name and voices, so the page can show them
    POST /api/chat     {"text": ...} -> {"type": "reply" | "ask", "text": ...}
    POST /api/speak    {"text": ..., "voice": ...} -> MP3 audio (see voice.py)

When Jarvis needs to ask you something (a yes before deleting notes, or a
question), /api/chat returns type "ask" and your next message is the answer.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from . import voice as tts

log = logging.getLogger("jarvis.web")
UI_DIR = Path(__file__).resolve().parent / "ui"
PAGES = {"/": "index.html", "/index.html": "index.html", "/voice": "voice.html", "/voice.html": "voice.html"}


class WebHuman:
    """Questions from Jarvis go to the chat screen; your next message answers."""

    def __init__(self, session: "ChatSession", timeout_s: int = 600):
        self.session = session
        self.timeout_s = timeout_s

    def ask(self, question: str) -> str | None:
        s = self.session
        s.waiting_for_answer = True
        s.events.put(("ask", question))
        try:
            return s.answers.get(timeout=self.timeout_s)
        except queue.Empty:
            return None
        finally:
            s.waiting_for_answer = False


class ChatSession:
    def __init__(self, make_agent: Callable[[WebHuman], object], reply_timeout_s: int = 180):
        self.events: queue.Queue = queue.Queue()
        self.answers: queue.Queue = queue.Queue()
        self.waiting_for_answer = False
        self.reply_timeout_s = reply_timeout_s
        self.agent = make_agent(WebHuman(self))
        self._lock = threading.Lock()

    def _work(self, text: str) -> None:
        try:
            self.events.put(("reply", self.agent.run(text)))
        except Exception as exc:
            log.exception("Agent failed")
            self.events.put(("error", f"Sorry, something went wrong: {exc}"))

    def send(self, text: str) -> dict:
        with self._lock:
            if self.waiting_for_answer:
                self.answers.put(text)
            else:
                threading.Thread(target=self._work, args=(text,), daemon=True).start()
            try:
                kind, body = self.events.get(timeout=self.reply_timeout_s)
            except queue.Empty:
                kind, body = "error", "That took too long. Try again."
            return {"type": kind, "text": body}


def make_handler(session: ChatSession, brain: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.debug(fmt, *args)

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: dict, code: int = 200) -> None:
            self._send(code, json.dumps(data).encode("utf-8"), "application/json")

        def do_GET(self):
            page = PAGES.get(self.path.split("?")[0])
            if page:
                self._send(200, (UI_DIR / page).read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self._json({"brain": brain, "tts": tts.available(),
                            "voices": [{"id": v, "label": l} for v, l in tts.VOICES],
                            "default_voice": tts.DEFAULT_VOICE})
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            if self.path not in ("/api/chat", "/api/speak"):
                return self._json({"error": "not found"}, 404)
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                text = str(body.get("text", "")).strip()
            except (ValueError, AttributeError):
                return self._json({"error": "bad request"}, 400)
            if not text:
                return self._json({"error": "empty message"}, 400)
            if self.path == "/api/speak":
                return self._speak(text, str(body.get("voice") or tts.DEFAULT_VOICE))
            self._json(session.send(text[:4000]))

        def _speak(self, text: str, voice: str) -> None:
            try:
                audio = tts.synthesize(text, voice)
            except Exception as exc:
                log.warning("Voice failed: %s", exc)
                return self._json({"error": f"voice unavailable: {exc}"}, 503)
            self._send(200, audio, "audio/mpeg")

    return Handler


def serve(cfg, make_agent: Callable[[WebHuman], object], brain: str, open_browser: bool = True) -> int:
    session = ChatSession(make_agent)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", cfg.port), make_handler(session, brain))
    except OSError:
        print(f"Port {cfg.port} is busy. Jarvis may already be running: look for it at "
              f"http://127.0.0.1:{cfg.port}, or set JARVIS_PORT in .env to another number.")
        return 1
    url = f"http://127.0.0.1:{cfg.port}"
    print(f"Jarvis is online at {url}  (brain: {brain})")
    print(f"For voice mode (just talk, Jarvis answers out loud) go to {url}/voice")
    print("Your browser should open by itself. Press Ctrl+C here to stop Jarvis.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("Jarvis stopped.")
    return 0
