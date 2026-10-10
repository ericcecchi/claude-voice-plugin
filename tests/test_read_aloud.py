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
import threading
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
        self.real_speak = self.ra.speak
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


class Settings(Toggle):
    def context(self, prompt):
        return json.loads(self.run_toggle(prompt))["hookSpecificOutput"]["additionalContext"]

    def test_defaults(self):
        s = self.ra.settings()
        self.assertEqual((s["updates"], s["reactions"], s["speed"], s["voice"]), (False, True, 1.2, "af_heart"))

    def test_updates_and_reactions(self):
        self.assertIn("now ON", self.context("/read-aloud updates on"))
        self.assertTrue(self.ra.settings()["updates"])
        self.context("/read-aloud progress off")  # a synonym
        self.assertFalse(self.ra.settings()["updates"])
        self.context("/read-aloud reactions")  # no on/off flips it
        self.assertFalse(self.ra.settings()["reactions"])
        self.assertIsNone(self.state())  # settings leave the session's voice alone

    def test_speed(self):
        self.assertIn("1.4x", self.context("/read-aloud speed 1.4"))
        self.assertEqual(self.ra.settings()["speed"], 1.4)
        self.context("/read-aloud speed 9")
        self.assertEqual(self.ra.settings()["speed"], 2.0)  # clamped
        self.assertIn("isn't a speed", self.context("/read-aloud speed fast"))
        self.assertEqual(self.ra.tts_command("hi")[2], "350") if self.ra.shutil.which("say") else None

    def test_voice(self):
        self.assertIn("now Emma", self.context("/read-aloud voice emma"))  # short name
        self.assertIn("now Fenrir", self.context("/read-aloud voice am_fenrir"))  # its pool name
        self.assertIn("Couldn't find a Kokoro voice", self.context("/read-aloud voice robot"))
        self.assertEqual(self.ra.session_voice("s1", "kokoro")[0], "am_fenrir")  # this session only
        self.assertEqual(self.ra.settings()["voice"], "af_heart")  # the default is untouched
        self.assertIn("default Kokoro voice is now", self.context("/read-aloud default-voice bella"))
        self.assertEqual(self.ra.settings()["voice"], "af_bella")
        note = self.context("/read-aloud voices")
        self.assertIn("This session's voice is Fenrir", note)
        self.assertIn("US female: heart", note)

    def test_settings_and_unknown(self):
        self.assertIn("speed 1.2x", self.context("/read-aloud settings"))
        self.assertIn("isn't a read-aloud option", self.context("/read-aloud loud"))

    def test_bad_config_falls_back(self):
        os.makedirs(os.path.dirname(self.ra.CONFIG), exist_ok=True)
        with open(self.ra.CONFIG, "w") as f:
            f.write('{"speed": "fast", "updates": "yes"')
        self.assertEqual(self.ra.settings(), self.ra.DEFAULTS)


class ElevenLabs(Toggle):
    VOICES = {"voices": [{"voice_id": "JBFqnCBsd6RMkjVDRZzb", "name": "George"},
                         {"voice_id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah - Mature, Reassuring"}]}

    def setUp(self):
        super().setUp()
        self.requests = []

        def fake_request(path, body=None, timeout=30):
            self.requests.append((path, body))
            return json.dumps(self.VOICES).encode() if path == "/voices" else b"ID3fake-mp3"
        self.ra.elevenlabs_request = fake_request
        self.played = []
        fake_popen = lambda argv, **kw: (self.played.append(argv), mock.Mock(pid=4242))[1]
        self.patches = [mock.patch.object(self.ra.subprocess, "Popen", fake_popen),
                        mock.patch.object(self.ra, "kokoro_send", lambda t: None)]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def context(self, prompt):
        return json.loads(self.run_toggle(prompt))["hookSpecificOutput"]["additionalContext"]

    def test_engine_without_a_key_warns_and_falls_back(self):
        with mock.patch.object(self.ra, "elevenlabs_key", lambda: ""):
            note = self.context("/read-aloud engine elevenlabs")
            self.assertIn("No ElevenLabs API key", note)
            self.assertIn("Never paste", note)
            self.real_speak("Hello there.")
        self.assertEqual(self.ra.settings()["engine"], "elevenlabs")
        self.assertNotIn("/text-to-speech", str(self.requests))

    def test_speaks_with_the_chosen_voice_and_clamped_speed(self):
        with mock.patch.object(self.ra, "elevenlabs_key", lambda: "k"), \
                mock.patch.object(self.ra.shutil, "which", lambda n: "/usr/bin/" + n):
            self.context("/read-aloud engine elevenlabs")
            self.assertIn("now Sarah", self.context("/read-aloud voice sarah"))
            self.ra.SESSION["id"] = "s1"  # the session the voice was set for
            self.context("/read-aloud speed 1.6")
            self.real_speak("Hello there.")
        path, body = self.requests[-1]
        self.assertTrue(path.startswith("/text-to-speech/EXAVITQu4vr4xnSDxMaL?"))
        # v4 ignores the API's speed, so the player applies it, pitch kept
        self.assertEqual((body["text"], body["voice_settings"]["speed"]), ("Hello there.", 1.0))
        self.assertEqual(self.played[-1][:5], ["afplay", "-r", "1.6", "-q", "1"])

    def test_older_models_get_speed_from_the_api(self):
        with mock.patch.object(self.ra, "elevenlabs_key", lambda: "k"), \
                mock.patch.object(self.ra.shutil, "which", lambda n: "/usr/bin/" + n):
            self.context("/read-aloud engine elevenlabs")
            self.context("/read-aloud model eleven_multilingual_v2")
            self.context("/read-aloud speed 1.6")
            self.real_speak("Hello there.")
        self.assertEqual(self.requests[-1][1]["voice_settings"]["speed"], 1.2)  # its 0.7-1.2 range
        self.assertEqual(self.played[-1][:3], ["afplay", "-r", "1"])

    def test_model(self):
        self.assertEqual(self.ra.settings()["elevenlabs_model"], "eleven_v4")
        self.assertIn("now eleven_v4_turbo", self.context("/read-aloud model eleven_v4_turbo"))
        self.assertIn("doesn't look like", self.context("/read-aloud model v4!"))
        self.assertEqual(self.ra.settings()["elevenlabs_model"], "eleven_v4_turbo")

    def test_voice_id_is_taken_as_is(self):
        vid = "pNInz6obpgDQGcFmaJgB"  # not in the account's list
        with mock.patch.object(self.ra, "elevenlabs_key", lambda: "k"):
            self.context("/read-aloud engine elevenlabs")
            self.assertIn(f"now {vid}", self.context(f"/read-aloud voice {vid}"))
        self.assertEqual(self.ra.session_voice("s1", "elevenlabs")[0], vid)  # case kept

    def test_voice_id_on_another_engine(self):
        vid = "pNInz6obpgDQGcFmaJgB"
        with mock.patch.object(self.ra, "elevenlabs_key", lambda: ""):
            note = self.context(f"/read-aloud voice {vid}")
        self.assertIn("once the engine is elevenlabs", note)
        self.assertEqual(self.ra.session_voice("s1", "elevenlabs")[0], vid)
        self.assertEqual(self.ra.settings()["engine"], "kokoro")

    def test_unknown_voice_lists_the_account(self):
        with mock.patch.object(self.ra, "elevenlabs_key", lambda: "k"):
            self.context("/read-aloud engine elevenlabs")
            note = self.context("/read-aloud voice nobody")
        self.assertIn("Couldn't find", note)
        self.assertIn("George", note)

    def test_failure_falls_back_to_kokoro(self):
        def boom(*a, **k):
            raise OSError("network down")
        sent = []
        with mock.patch.object(self.ra, "elevenlabs_key", lambda: "k"), \
                mock.patch.object(self.ra, "elevenlabs_request", boom), \
                mock.patch.object(self.ra, "kokoro_send", lambda t: sent.append(t)):
            self.context("/read-aloud engine elevenlabs")
            self.real_speak("Hello there.")
        self.assertEqual(sent, ["\x00kind=reply;voice=af_heart\x00Hello there."])


class Rotation(Base):
    """Each new session gets its own voice, so sessions sound different."""

    def test_sessions_get_different_voices(self):
        voices = [self.ra.session_voice(f"s{i}", "kokoro")[0] for i in range(4)]
        self.assertEqual(len(set(voices)), 4)
        self.assertEqual(voices[0], "af_heart")  # the pool's first voice goes first

    def test_a_session_keeps_its_voice(self):
        first = self.ra.session_voice("a", "elevenlabs")
        self.ra.session_voice("b", "elevenlabs")
        self.assertEqual(self.ra.session_voice("a", "elevenlabs"), first)

    def test_engines_are_separate(self):
        self.assertEqual(self.ra.session_voice("a", "kokoro")[1], "Heart")
        self.assertEqual(self.ra.session_voice("a", "elevenlabs")[1], "George")
        self.assertIsNone(self.ra.session_voice("a", "system"))

    def test_rotate_off_uses_the_default(self):
        self.ra.save_setting("rotate", False)
        self.ra.save_setting("voice", "bf_emma")
        self.assertEqual(self.ra.session_voice("a", "kokoro")[0], "bf_emma")
        self.assertEqual(self.ra.session_voice("b", "kokoro")[0], "bf_emma")

    def test_when_every_voice_is_taken_the_least_recent_comes_back(self):
        pool = self.ra.POOLS["kokoro"]
        for i in range(len(pool)):
            self.ra.session_voice(f"s{i}", "kokoro")
            time.sleep(0.01)
        self.assertEqual(self.ra.session_voice("extra", "kokoro")[0], pool[0][0])

    def test_an_idle_sessions_voice_is_free_again(self):
        self.ra.session_voice("old", "kokoro")  # takes Heart
        stale = time.time() - self.ra.ACTIVE_FOR - 60
        os.utime(self.ra._session_file("old"), (stale, stale))
        self.assertEqual(self.ra.session_voice("new", "kokoro")[0], "am_fenrir")  # least recently given
        os.utime(self.ra._session_file("new"), (stale, stale))
        self.assertEqual(self.ra.session_voice("newer", "kokoro")[0], "bf_emma")

    def test_turning_voice_on_names_the_voice(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.ra.toggle({"prompt": "/read-aloud on", "session_id": "s1"})
        self.assertIn("This session's voice is Heart", out.getvalue())

    def test_kokoro_gets_the_sessions_voice(self):
        sent = []
        self.ra.kokoro_send = sent.append
        self.ra.SESSION["id"] = "x"
        self.ra.set_session_voice("x", "kokoro", ("bm_george", "George"))
        self.real_speak("Hi.", "reply")
        self.assertEqual(sent, ["\x00kind=reply;voice=bm_george\x00Hi."])


class Queueing(Base):
    """Lines wait for the one playing instead of cutting it off (unless interrupt is on)."""

    def setUp(self):
        super().setUp()
        self.ra.save_setting("engine", "system")
        self.started = []
        self.ra.start_player = lambda argv: self.started.append(argv[-1])
        self.ra.tts_command = lambda text: ["say", text]
        self.playing = [True]
        self.ra.playing_pid = lambda: 4242 if self.playing[0] else None
        self.killed = []
        self.ra.stop_playing = lambda: self.killed.append(True)

    def test_a_reaction_is_dropped_while_something_plays(self):
        self.real_speak("On it.", "ack")
        self.assertEqual(self.started, [])

    def test_a_reply_waits_for_the_line_playing(self):
        timer = threading.Timer(0.5, lambda: self.playing.__setitem__(0, False))
        timer.start()
        t = time.time()
        self.real_speak("All done.", "reply")
        self.assertEqual(self.started, ["All done."])
        self.assertGreaterEqual(time.time() - t, 0.4)
        self.assertEqual(self.killed, [])

    def test_gives_up_after_its_wait(self):
        self.ra.WAIT["progress"] = 0.3
        self.real_speak("Still working.", "progress")
        self.assertEqual(self.started, [])

    def test_interrupt_on_cuts_off_instead(self):
        self.ra.save_setting("interrupt", True)
        self.real_speak("On it.", "ack")
        self.assertEqual((self.killed, self.started), ([True], ["On it."]))

    def test_interrupt_command(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.ra.toggle({"prompt": "/read-aloud interrupt on", "session_id": "s1"})
        self.assertIn("now ON", out.getvalue())
        self.assertTrue(self.ra.settings()["interrupt"])

    def test_two_waiting_lines_take_turns(self):
        self.playing[0] = False
        order = []
        def fake_start(argv):
            order.append(("start", argv[-1]))
            self.playing[0] = True  # it plays for a moment
            threading.Timer(0.3, lambda: (order.append(("end", argv[-1])), self.playing.__setitem__(0, False))).start()
        self.ra.start_player = fake_start
        a = threading.Thread(target=self.real_speak, args=("First.", "reply"))
        b = threading.Thread(target=self.real_speak, args=("Second.", "reply"))
        a.start(); time.sleep(0.05); b.start(); a.join(); b.join(); time.sleep(0.4)
        self.assertEqual([e for e, _ in order], ["start", "end", "start", "end"])


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


class SpokenSummary(Base):
    def test_short_reply_read_as_is_without_a_model_call(self):
        self.ra.claude_text = lambda *a: self.fail("called the model for a short reply")
        self.assertEqual(self.ra.spoken_summary("Voice is off for this session."), "Voice is off for this session.")

    def test_long_reply_uses_the_model(self):
        calls = []
        def fake(model, system, text, timeout):
            calls.append(text)
            return "It **works** now.\nWant me to push?"
        self.ra.claude_text = fake
        long = "Done. " + " ".join(f"Detail number {i} about the change." for i in range(40))
        self.assertEqual(self.ra.spoken_summary(long), "It works now. Want me to push?")
        self.assertIn("<reply>", calls[0])

    def test_falls_back_to_rules_when_the_model_fails(self):
        self.ra.claude_text = lambda *a: ""
        long = "Done. " + " ".join(f"Detail number {i} about the change." for i in range(40))
        self.assertEqual(self.ra.spoken_summary(long), self.ra.summarize(long))


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

    def setUp(self):
        super().setUp()
        self.ra.save_setting("updates", True)

    def test_off_by_default(self):
        self.ra.save_setting("updates", False)
        self.write(user("go"), assistant("1", "Found the files."))
        self.ra.progress(self.event())
        self.assertEqual(self.said, [])

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

    def test_reactions_off(self):
        self.ra.save_setting("reactions", False)
        os.makedirs(self.ra.ON_DIR, exist_ok=True)
        with open(os.path.join(self.ra.ON_DIR, "s"), "w") as f:
            f.write("on")
        self.ra.quick_reply = lambda p: self.fail("asked for a reaction while reactions are off")
        event = {"session_id": "s", "hook_event_name": "UserPromptSubmit", "prompt": "fix the CI",
                 "transcript_path": self.transcript, "cwd": self.home}
        self.write(user("fix the CI"))
        with mock.patch("sys.stdin", io.StringIO(json.dumps(event))), mock.patch("sys.argv", ["x"]):
            self.ra.main()
        self.assertEqual(self.said, [])

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
