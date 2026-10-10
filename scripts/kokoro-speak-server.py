#!/usr/bin/env python3
"""Optional warm Kokoro voice for the read-aloud hook (read-aloud.py).

Loads Kokoro-82M once and keeps it in memory. It listens on a Unix socket (~/.claude/kokoro.sock),
takes UTF-8 text, synthesizes it, and plays it with `afplay`, sentence by sentence, so long text
starts at once. Lines queue, one after another; a reaction that would have to wait is dropped.
With `/read-aloud interrupt on` a new line cuts off the one playing instead. "\\x00stop" only cuts
it off; "\\x00kind=<kind>;voice=<id>\\x00<text>" says what kind of line it is and which voice
reads it (each session has its own).
When this server isn't running, the hook falls back to macOS `say`.

Needs a Python venv with `kokoro soundfile numpy torch` and `brew install espeak-ng`. See the
README for a launchd job that keeps it running.

Environment:
  KOKORO_VOICE   default voice (af_heart); `/read-aloud voice` overrides it. a… US, b… UK English
  KOKORO_SPEED   speaking speed (default 1.2); `/read-aloud speed` overrides it
  KOKORO_DEVICE  cpu (default) or mps; cpu sounds cleaner and is faster here
  ESPEAK_PREFIX  where espeak-ng is installed (default: `brew --prefix espeak-ng`)
"""
import itertools
import json
import os
import queue
import shutil
import socket
import subprocess
import tempfile
import threading
import warnings

warnings.filterwarnings("ignore")


def _point_kokoro_at_brew_espeak() -> None:
    """The pip `espeakng-loader` library often fails to load on macOS; use Homebrew's espeak-ng.

    Must run before `kokoro` is imported.
    """
    prefix = os.environ.get("ESPEAK_PREFIX")
    if not prefix and (brew := shutil.which("brew")):
        out = subprocess.run([brew, "--prefix", "espeak-ng"], capture_output=True, text=True)
        prefix = out.stdout.strip() if out.returncode == 0 else ""
    prefix = prefix or "/opt/homebrew"
    data = os.path.join(prefix, "share", "espeak-ng-data")
    lib = next((os.path.join(prefix, "lib", n)
                for n in ("libespeak-ng.dylib", "libespeak-ng.so", "libespeak-ng.so.1")
                if os.path.exists(os.path.join(prefix, "lib", n))),
               os.path.join(prefix, "lib", "libespeak-ng.dylib"))
    try:
        import espeakng_loader
    except ImportError:
        return
    espeakng_loader.get_data_path = lambda: data
    espeakng_loader.get_library_path = lambda: lib
    os.environ["ESPEAK_DATA_PATH"] = data


_point_kokoro_at_brew_espeak()
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402,F401  (loaded before kokoro, which needs it)
from kokoro import KPipeline  # noqa: E402

SOCK = os.path.expanduser("~/.claude/kokoro.sock")
VOICE = os.environ.get("KOKORO_VOICE", "af_heart")
SPEED = float(os.environ.get("KOKORO_SPEED", "1.2"))  # the default; `/read-aloud speed` overrides it
CONFIG = os.path.expanduser("~/.claude/read-aloud/config.json")


def setting(key, default):
    """A value `/read-aloud` saved, read fresh for each request, else the default."""
    try:
        with open(CONFIG) as f:
            return json.load(f).get(key, default)
    except (OSError, ValueError):
        return default


def speed() -> float:
    try:
        return min(2.0, max(0.5, float(setting("speed", SPEED))))
    except (ValueError, TypeError):
        return SPEED


def is_voice(v) -> bool:
    """An English Kokoro voice id: a… US, b… UK."""
    return isinstance(v, str) and len(v) > 3 and v[0] in "ab" and v[2] == "_"


def voice(wanted: str = "") -> str:
    """The voice a line asked for, else the saved default, else VOICE."""
    if is_voice(wanted):
        return wanted
    v = setting("voice", VOICE)
    return v if is_voice(v) else VOICE


SR = 24000
WAV = os.path.join(tempfile.gettempdir(), "kokoro-speak.wav")
# CPU by default: on Apple silicon it's faster than MPS for a model this small, and MPS (with its
# CPU fallbacks) audibly roughens the voice.
DEVICE = os.environ.get("KOKORO_DEVICE", "cpu")
pipes = {}  # one pipeline per language: "a" US English, "b" UK English


def pipeline(lang: str):
    if lang not in pipes:
        pipes[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M", device=DEVICE)
    return pipes[lang]


list(pipeline(voice()[0])("Ready.", voice=voice()))  # pay the first-call cost now, not on a turn
player = None
lock = threading.Lock()
generation = 0  # bumped by each request; a reading still running for an older one stops
synth = threading.Lock()  # one synthesis at a time; an outdated one gives way at its next segment


def speak(text: str, gen: int, wanted: str = "") -> None:
    """Synthesize and play segment by segment, so a long reply starts at once and is never cut short."""
    with synth:
        _speak(text, gen, wanted)


def _speak(text: str, gen: int, wanted: str = "") -> None:
    global player
    v = voice(wanted)
    try:
        chunks = pipeline(v[0])(text, voice=v, speed=speed())
        first = next(chunks, None)
    except Exception:  # a voice Kokoro doesn't have: fall back to the default
        v = VOICE
        chunks = pipeline(v[0])(text, voice=v, speed=speed())
        first = next(chunks, None)
    if first is None:
        return
    for i, (_, _, audio) in enumerate(itertools.chain([first], chunks)):
        if gen != generation:
            return
        wav = f"{WAV[:-4]}-{gen}-{i}.wav"
        sf.write(wav, audio.numpy() if hasattr(audio, "numpy") else np.asarray(audio), SR)
        with lock:
            prev = player
        if prev:
            prev.wait()  # the segment before this one finishes first
        with lock:
            if gen != generation:
                return
            player = subprocess.Popen(["afplay", wav])
        threading.Thread(target=_cleanup, args=(player, wav), daemon=True).start()


def _cleanup(proc: subprocess.Popen, wav: str) -> None:
    proc.wait()
    try:
        os.unlink(wav)
    except OSError:
        pass


def stop() -> int:
    """Cut off whatever is playing; returns the new generation."""
    global generation, player
    with lock:
        generation += 1
        if player and player.poll() is None:
            player.terminate()
        player = None
        return generation


lines: "queue.Queue[tuple[str, int, str]]" = queue.Queue()
busy = threading.Event()  # set while a line is being synthesized or played


def start(text: str, kind: str = "reply", wanted: str = "") -> None:
    """Read text. With `/read-aloud interrupt on`, cut off whatever is playing first; otherwise
    queue it behind the line playing, except a reaction ("ack"), which is dropped if it would wait."""
    if setting("interrupt", False) is True:
        lines.put((text, stop(), wanted))
        return
    if kind == "ack" and (busy.is_set() or not lines.empty()):
        print(f"skipped a reaction while speaking: {text[:60]}", flush=True)
        return
    lines.put((text, generation, wanted))


def worker() -> None:
    """Reads queued lines one after another."""
    while True:
        text, gen, wanted = lines.get()
        if gen != generation:  # queued before an interrupt
            continue
        busy.set()
        try:
            speak(text, gen, wanted)
            with lock:
                last = player
            if last:
                last.wait()  # its final segment, too, before the next line
        except Exception as e:  # keep serving
            print(f"speak failed: {e}", flush=True)
        finally:
            busy.clear()


def main() -> None:
    try:
        os.unlink(SOCK)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    os.chmod(SOCK, 0o600)
    srv.listen(4)
    threading.Thread(target=worker, daemon=True).start()
    print("kokoro-speak ready", flush=True)
    while True:
        conn, _ = srv.accept()
        with conn:
            data = b""
            while chunk := conn.recv(65536):
                data += chunk
        text = data.decode("utf-8", "replace").strip()
        fields = {}
        if text.startswith("\x00kind="):  # "\x00kind=ack;voice=af_bella\x00<text>" from the hook
            header, _, text = text[1:].partition("\x00")
            fields = dict(f.partition("=")[::2] for f in header.split(";"))
        kind, wanted = fields.get("kind", "reply"), fields.get("voice", "")
        if text == "\x00stop":  # another engine is about to speak
            stop()
        elif text and text != "ping":
            start(text, kind, wanted)


if __name__ == "__main__":
    main()
