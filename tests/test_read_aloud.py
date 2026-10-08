"""Tests for scripts/read-aloud.py. Nothing is spoken: speak() and the model calls are replaced.

Run: python3 -m unittest discover tests
"""
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "read-aloud.py"


def load(home):
    """A fresh copy of the script with ~ pointed at a temporary folder."""
    with mock.patch.dict(os.environ, {"HOME": home}):
        spec = importlib.util.spec_from_file_location("read_aloud", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def assistant(uid, *texts):
    return {"type": "assistant", "uuid": uid,
            "message": {"content": [{"type": "text", "text": t} for t in texts]}}


class Base(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.ra = load(self.home)
        self.said = []

        def fake_speak(s, kind="reply"):
            self.said.append((kind, s))
            with open(self.ra.LAST_SPOKE, "w") as f:
                f.write(str(time.time()))
        self.ra.speak = fake_speak
        self.transcript = os.path.join(self.home, "t.jsonl")

    def write(self, *rows):
        with open(self.transcript, "w") as f:
            f.write("\n".join(json.dumps(r) for r in rows))


class Toggle(Base):
    def run_toggle(self, prompt, sid="s1"):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.ra.toggle({"prompt": prompt, "session_id": sid})
        return out.getvalue()

    def state(self, sid="s1"):
        try:
            with open(os.path.join(self.ra.ON_DIR, sid)) as f:
                return f.read()
        except OSError:
            return None

    def test_command_forms(self):
        self.run_toggle("/read-aloud")
        self.assertEqual(self.state(), "on")
        self.run_toggle("/read-aloud off")
        self.assertEqual(self.state(), "off")
        self.run_toggle("<command-name>/read-aloud:read-aloud</command-name>\n<command-args>on</command-args>")
        self.assertEqual(self.state(), "on")

    def test_ignores_lookalikes(self):
        for prompt in ("/voice", "/voice:voice", "/read-aloudly", "please /read-aloud", "hello"):
            self.assertEqual(self.run_toggle(prompt, sid="other"), "", prompt)
        self.assertIsNone(self.state("other"))


class Summarize(Base):
    def test_reads_whole_reply_minus_fluff(self):
        text = ("Fixed it. The cap is gone.\n\n- **Speed:** now 1.2x.\n\n```bash\nrm -rf /\n```\n\n"
                "| a | b |\n|---|---|\n\nHope this helps! Let me know if you want more.")
        self.assertEqual(self.ra.summarize(text), "Fixed it. The cap is gone. Speed: now 1.2x.")

    def test_drops_intro_to_unread_code_and_repeats(self):
        text = "Run this:\n\n```bash\ntail -f x\n```\n\nDone now. Done now!"
        self.assertEqual(self.ra.summarize(text), "Done now.")

    def test_paths_and_versions(self):
        out = self.ra.summarize("See `scripts/read-aloud.py` for v4.1 and CSF 2.0.")
        self.assertIn("aloud.py", out)
        self.assertNotIn("scripts/", out)
        self.assertIn("version 4.1", out)
        self.assertIn("2 point oh", out)

    def test_no_length_cap(self):
        text = " ".join(f"Sentence number {i} is here." for i in range(400))
        self.assertGreater(len(self.ra.summarize(text)), 5000)


class FinalMessage(Base):
    def test_reads_only_the_last_block(self):
        self.write(user("go"), assistant("1", "Looking now."), assistant("2", "All done. It works."))
        full = "Looking now.\n\nAll done. It works."
        self.assertEqual(self.ra.last_assistant_text(
            {"transcript_path": self.transcript, "last_assistant_message": full}), "All done. It works.")

    def test_transcript_lagging_behind_the_event(self):
        self.write(user("go"), assistant("1", "Looking now."))
        full = "Looking now.\n\nAll done. It works."
        self.assertEqual(self.ra.last_assistant_text(
            {"transcript_path": self.transcript, "last_assistant_message": full}).strip(), "All done. It works.")


class Progress(Base):
    def event(self, **extra):
        return {"session_id": "s", "transcript_path": self.transcript, "hook_event_name": "PostToolUse", **extra}

    def test_speaks_new_updates_once_after_quiet(self):
        self.write(user("old"), assistant("x", "Old turn."), user("go"), assistant("1", "Found the files."))
        self.ra.progress(self.event())
        self.assertEqual(self.said, [("progress", "Found the files.")])
        self.ra.progress(self.event())  # same block again
        self.assertEqual(len(self.said), 1)
        self.write(user("go"), assistant("1", "Found the files."), assistant("2", "Now testing."))
        self.ra.progress(self.event())  # new block, but something spoke a moment ago
        self.assertEqual(len(self.said), 1)
        with open(self.ra.LAST_SPOKE, "w") as f:
            f.write(str(time.time() - 60))
        self.ra.progress(self.event())
        self.assertEqual(self.said[-1], ("progress", "Now testing."))

    def test_ignores_subagents(self):
        self.write(user("go"), assistant("1", "Found the files."))
        self.ra.progress(self.event(agent_id="sub"))
        self.assertEqual(self.said, [])


class QuickReply(Base):
    def test_filters(self):
        usable = self.ra._usable
        self.assertEqual(usable("Got it, I'll adjust the timing.", "slow it down"), "I'll adjust the timing.")
        self.assertEqual(usable("Request: review the database.", "x y z"), "")
        self.assertEqual(usable("Yep, it's working fine on my end.", "does it work?"), "")
        self.assertEqual(usable("Let me check whether it's working now.", "does it work?"),
                         "Let me check whether it's working now.")
        self.assertEqual(usable("Dark mode for settings, nice.", "fix the CI"), "")
        self.assertEqual(usable("I'll dig in. What broke?", "fix the CI"), "I'll dig in.")

    def test_falls_back_when_models_fail(self):
        self.ra._ask_claude = lambda p: ""
        self.ra._ask_ollama = lambda p: ""
        self.assertIn(self.ra.quick_reply("fix the CI"), self.ra.ACKS)

    def test_prefers_claude(self):
        self.ra._ask_claude = lambda p: "Annoying when CI breaks, I'll dig in."
        self.ra._ask_ollama = lambda p: "Ollama line here, okay."
        self.assertTrue(self.ra.quick_reply("fix the CI").endswith("I'll dig in."))

    def test_no_ack_for_thanks_or_commands(self):
        for prompt in ("thanks!", "ok", "sounds good"):
            self.assertTrue(self.ra.NO_ACK.match(prompt), prompt)
        self.assertFalse(self.ra.NO_ACK.match("ok try again"))


class SpeechEngine(Base):
    def test_picks_an_available_engine(self):
        have = lambda *names: (lambda n: f"/usr/bin/{n}" if n in names else None)
        with mock.patch("shutil.which", have("say")):
            self.assertEqual(self.ra.tts_command("hi")[0], "say")
        with mock.patch("shutil.which", have("spd-say")):
            self.assertEqual(self.ra.tts_command("hi")[:2], ["spd-say", "-w"])
        with mock.patch("shutil.which", have("espeak")):
            self.assertEqual(self.ra.tts_command("hi")[0], "espeak")
        with mock.patch("shutil.which", have()):
            self.assertIsNone(self.ra.tts_command("hi"))


if __name__ == "__main__":
    unittest.main()
