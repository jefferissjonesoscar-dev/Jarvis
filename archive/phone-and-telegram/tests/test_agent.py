"""Run with:  python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from pathlib import Path

from jarvis.agent import Agent
from jarvis.brains import OfflineBrain
from jarvis.human import ScriptedHuman
from jarvis.tools import build_default_tools, calculate


class FakeBrain:
    """Calls a tool that isn't on the allowlist, then answers."""
    name = "fake"

    def respond(self, messages, tools):
        if messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], str):
            return [{"type": "tool_use", "id": "t1", "name": "run_shell",
                     "input": {"cmd": "rm -rf /"}}]
        return [{"type": "text", "text": messages[-1]["content"][0]["content"]}]


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def make(self, answers=(), brain=None):
        self.human = ScriptedHuman(answers)
        return Agent(brain or OfflineBrain(), build_default_tools(self.tmp / "data"),
                     self.human, self.tmp / "logs")

    def test_time(self):
        self.assertIn("It's", self.make().run("what time is it?"))

    def test_calculator(self):
        self.assertIn("= 84", self.make().run("calculate 12 * 7"))
        self.assertEqual(calculate("2 ^ 10"), "2 ^ 10 = 1024")
        with self.assertRaises(ValueError):
            calculate("__import__('os')")

    def test_notes_and_confirmation(self):
        agent = self.make(answers=["no", "yes"])
        agent.run("note buy milk")
        self.assertIn("buy milk", agent.run("list my notes"))
        self.assertIn("declined", agent.run("clear my notes"))
        self.assertIn("buy milk", agent.run("list my notes"))
        self.assertIn("Deleted 1", agent.run("clear my notes"))
        self.assertIn("no notes", agent.run("list my notes"))
        self.assertEqual(len(self.human.asked), 2)

    def test_ask_human(self):
        reply = self.make(answers=["the garden"]).run("ask me something")
        self.assertIn("the garden", reply)

    def test_unlisted_tool_is_refused_and_logged(self):
        reply = self.make(brain=FakeBrain()).run("delete everything")
        self.assertIn("not on the allowlist", reply)
        records = [json.loads(l) for l in (self.tmp / "logs/tool_calls.jsonl").read_text().splitlines()]
        self.assertEqual(records[-1]["tool"], "run_shell")
        self.assertTrue(records[-1]["error"])

    def test_unknown_request_gets_help(self):
        self.assertIn("offline mode", self.make().run("book me a flight"))


if __name__ == "__main__":
    unittest.main()
