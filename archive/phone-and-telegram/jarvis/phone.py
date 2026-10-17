"""Phone calls and SMS through Twilio.

- Jarvis calls you: TwilioClient.call() places a call that speaks a message, or
  PhoneServer.ask_by_call() asks a question and hears your spoken answer.
- You call Jarvis: Twilio sends your call to PhoneServer at /voice/incoming and
  you have a spoken conversation with the same brain and tools.
- SMS: texts to your Twilio number arrive at /sms and Jarvis texts back.

Only your own number (JARVIS_MY_PHONE_NUMBER) is accepted, and every request is
checked against Twilio's signature, so nobody else can drive Jarvis by phone.
No extra packages: this uses Python's built-in HTTP server and urllib.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import threading
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape, quoteattr

log = logging.getLogger("jarvis.phone")

GOODBYE = re.compile(r"^\s*(bye|goodbye|good bye|that'?s all|that is all|no thanks?|nothing( else)?|hang up)\b", re.I)


# --- Twilio REST ------------------------------------------------------------

class TwilioClient:
    def __init__(self, sid: str, token: str, from_number: str,
                 base: str = "https://api.twilio.com/2010-04-01"):
        self.sid, self.token, self.from_number = sid, token, from_number
        self.base = f"{base}/Accounts/{sid}"

    def _request(self, path: str, params: dict | None = None, method: str = "POST") -> dict:
        url = f"{self.base}/{path}.json"
        data = None
        if method == "GET" and params:
            url += "?" + urllib.parse.urlencode(params)
        elif params:
            data = urllib.parse.urlencode(params).encode()
        auth = base64.b64encode(f"{self.sid}:{self.token}".encode()).decode()
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Authorization": f"Basic {auth}"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())

    def call(self, to: str, twiml: str) -> str:
        result = self._request("Calls", {"To": to, "From": self.from_number, "Twiml": twiml})
        log.info("Placed call %s to %s", result.get("sid"), to)
        return result.get("sid", "")

    def sms(self, to: str, body: str) -> str:
        result = self._request("Messages", {"To": to, "From": self.from_number, "Body": body[:1500]})
        return result.get("sid", "")

    def point_number_at(self, public_url: str) -> bool:
        """Set the Twilio number's voice and SMS webhooks to this Jarvis, so you
        don't have to do it by hand in the Twilio console."""
        found = self._request("IncomingPhoneNumbers", {"PhoneNumber": self.from_number}, "GET")
        numbers = found.get("incoming_phone_numbers") or []
        if not numbers:
            log.warning("Twilio number %s not found on this account", self.from_number)
            return False
        self._request(f"IncomingPhoneNumbers/{numbers[0]['sid']}", {
            "VoiceUrl": f"{public_url}/voice/incoming", "VoiceMethod": "POST",
            "SmsUrl": f"{public_url}/sms", "SmsMethod": "POST"})
        log.info("Pointed %s at %s", self.from_number, public_url)
        return True


def compute_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Twilio's request signature: HMAC-SHA1 of the URL plus sorted POST params."""
    payload = url + "".join(k + params[k] for k in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def valid_signature(auth_token: str, url: str, params: dict[str, str], signature: str) -> bool:
    return hmac.compare_digest(compute_signature(auth_token, url, params), signature or "")


# --- TwiML ------------------------------------------------------------------

class Voice:
    def __init__(self, voice: str = "Polly.Brian", language: str = "en-GB"):
        self.voice, self.language = voice, language

    def say(self, text: str) -> str:
        return f"<Say voice={quoteattr(self.voice)}>{escape(text)}</Say>"

    def gather(self, action: str, inner: str = "", timeout: int = 6) -> str:
        return (f"<Gather input=\"speech\" method=\"POST\" speechTimeout=\"auto\" "
                f"timeout=\"{timeout}\" language={quoteattr(self.language)} "
                f"action={quoteattr(action)}>{inner}</Gather>")


def twiml(*parts: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(parts) + "</Response>"


# --- Web server for Twilio webhooks -------------------------------------------

class PhoneServer:
    def __init__(self, *, auth_token: str, public_url: str, my_number: str,
                 voice_agent, sms_agent=None, twilio: TwilioClient | None = None,
                 voice: Voice | None = None, host: str = "0.0.0.0", port: int = 8080,
                 wait_s: float = 8.0):
        self.auth_token = auth_token
        self.public_url = public_url.rstrip("/")
        self.my_number = my_number
        self.voice_agent = voice_agent
        self.sms_agent = sms_agent or voice_agent
        self.twilio = twilio
        self.v = voice or Voice()
        self.host, self.port = host, port
        self.wait_s = wait_s
        self.jobs: dict[str, tuple[threading.Thread, dict]] = {}
        self.answers: dict[str, dict] = {}
        self.httpd: ThreadingHTTPServer | None = None

    # -- lifecycle
    def start(self) -> None:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode()
                params = {k: v[0] for k, v in urllib.parse.parse_qs(body, keep_blank_values=True).items()}
                status, out = server.handle(self.path, params, self.headers.get("X-Twilio-Signature", ""))
                self.send_response(status)
                self.send_header("Content-Type", "text/xml")
                self.end_headers()
                self.wfile.write(out.encode())

            def do_GET(self):  # noqa: N802  (a simple health check)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Jarvis phone server is running.")

            def log_message(self, fmt, *args):
                log.debug("http: " + fmt, *args)

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        log.info("Phone server listening on port %s (public URL %s)", self.port, self.public_url)

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()

    # -- routing
    def handle(self, path: str, params: dict[str, str], signature: str) -> tuple[int, str]:
        if not valid_signature(self.auth_token, self.public_url + path, params, signature):
            log.warning("Rejected request to %s with a bad Twilio signature", path)
            return 403, twiml()
        if self.my_number not in (params.get("From"), params.get("To")):
            log.warning("Rejected call/text from %s", params.get("From"))
            return 200, twiml("<Reject/>") if path.startswith("/voice") else twiml()

        route, _, query = path.partition("?")
        q = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
        speech = (params.get("SpeechResult") or "").strip()

        if route == "/voice/incoming":
            return 200, twiml(
                self.v.gather(self._url("/voice/turn"), self.v.say("Jarvis here. How can I help?")),
                self.v.say("I didn't hear anything. Goodbye."), "<Hangup/>")
        if route == "/voice/turn":
            if not speech:
                return 200, twiml(self.v.say("I didn't catch that. Goodbye."), "<Hangup/>")
            if GOODBYE.match(speech):
                return 200, twiml(self.v.say("Goodbye."), "<Hangup/>")
            job = self._start_job(speech)
            return 200, self._job_response(job, first=True)
        if route == "/voice/wait":
            return 200, self._job_response(q.get("job", ""), first=False)
        if route == "/voice/answer":
            slot = self.answers.get(q.get("q", ""))
            if slot is not None:
                slot["answer"] = speech or None
                slot["event"].set()
            return 200, twiml(self.v.say("Thanks, got it. Goodbye." if speech else "Okay. Goodbye."),
                              "<Hangup/>")
        if route == "/sms":
            text = (params.get("Body") or "").strip()
            if text:
                threading.Thread(target=self._sms_reply, args=(text,), daemon=True).start()
            return 200, twiml()
        return 404, twiml()

    def _url(self, path: str) -> str:
        return self.public_url + path

    # -- voice conversation: run the agent in the background so Twilio's
    #    15-second webhook limit never cuts a slow answer off.
    def _start_job(self, text: str) -> str:
        job_id = uuid.uuid4().hex
        box: dict = {}

        def work():
            try:
                box["reply"] = self.voice_agent.run(text)
            except Exception as exc:
                log.exception("Agent failed during call")
                box["reply"] = f"Sorry, I hit a problem: {exc}"

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        self.jobs[job_id] = (thread, box)
        return job_id

    def _job_response(self, job_id: str, first: bool) -> str:
        if job_id not in self.jobs:
            return twiml(self.v.say("Sorry, I lost track of that. Goodbye."), "<Hangup/>")
        thread, box = self.jobs[job_id]
        thread.join(timeout=self.wait_s)
        if thread.is_alive():
            hold = self.v.say("One moment.") if first else '<Pause length="1"/>'
            return twiml(hold, f"<Redirect method=\"POST\">{escape(self._url('/voice/wait?job=' + job_id))}</Redirect>")
        del self.jobs[job_id]
        return twiml(self.v.gather(self._url("/voice/turn"), self.v.say(box.get("reply") or "Done.")),
                     self.v.say("Goodbye."), "<Hangup/>")

    def _sms_reply(self, text: str) -> None:
        try:
            reply = self.sms_agent.run(text)
        except Exception as exc:
            log.exception("Agent failed on SMS")
            reply = f"Sorry, something went wrong: {exc}"
        if self.twilio:
            self.twilio.sms(self.my_number, reply)

    # -- Jarvis calls you with a question
    def ask_by_call(self, question: str, intro: str = "", timeout_s: int = 120) -> str | None:
        if not self.twilio:
            raise RuntimeError("Twilio isn't set up")
        qid = uuid.uuid4().hex
        slot = {"event": threading.Event(), "answer": None}
        self.answers[qid] = slot
        parts = [self.v.say(intro)] if intro else []
        parts += [self.v.gather(self._url(f"/voice/answer?q={qid}"), self.v.say(question), timeout=8),
                  self.v.say("I didn't hear an answer. Goodbye."), "<Hangup/>"]
        self.twilio.call(self.my_number, twiml(*parts))
        slot["event"].wait(timeout_s)
        self.answers.pop(qid, None)
        return slot["answer"]
