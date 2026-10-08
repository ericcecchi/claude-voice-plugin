#!/usr/bin/env python3
"""Optional warm Kokoro voice for the read-aloud hook (read-aloud.py).

Loads Kokoro-82M once and keeps it in memory. It listens on a Unix socket (~/.claude/kokoro.sock),
takes UTF-8 text, synthesizes it, and plays it with `afplay`, sentence by sentence, so long text
starts at once. A new request cuts off the one still playing.
When this server isn't running, the hook falls back to macOS `say`.

Needs a Python venv with `kokoro soundfile numpy torch` and `brew install espeak-ng`. See the
README for a launchd job that keeps it running.

Environment:
  KOKORO_VOICE   voice id (default bm_fable); the first letter picks the language (a US, b UK)
  KOKORO_SPEED   speaking speed (default 1.2); `/read-aloud speed` overrides it
  ESPEAK_PREFIX  where espeak-ng is installed (default: `brew --prefix espeak-ng`)
"""
import json
import os
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
import torch  # noqa: E402
from kokoro import KPipeline  # noqa: E402

SOCK = os.path.expanduser("~/.claude/kokoro.sock")
VOICE = os.environ.get("KOKORO_VOICE", "bm_fable")
SPEED = float(os.environ.get("KOKORO_SPEED", "1.2"))  # the default; `/read-aloud speed` overrides it
CONFIG = os.path.expanduser("~/.claude/read-aloud/config.json")


def speed() -> float:
    """The speed `/read-aloud speed` saved, read fresh for each request, else SPEED."""
    try:
        with open(CONFIG) as f:
            value = json.load(f).get("speed", SPEED)
        return min(2.0, max(0.5, float(value)))
    except (OSError, ValueError, TypeError):
        return SPEED
SR = 24000
WAV = os.path.join(tempfile.gettempdir(), "kokoro-speak.wav")

pipe = KPipeline(lang_code=VOICE[0], repo_id="hexgrad/Kokoro-82M",
                 device="mps" if torch.backends.mps.is_available() else "cpu")
list(pipe("Ready.", voice=VOICE))  # load the voice and pay the first-call cost now, not on a turn
player = None
lock = threading.Lock()
generation = 0  # bumped by each request; a reading still running for an older one stops
synth = threading.Lock()  # one synthesis at a time; an outdated one gives way at its next segment


def speak(text: str, gen: int) -> None:
    """Synthesize and play segment by segment, so a long reply starts at once and is never cut short."""
    with synth:
        _speak(text, gen)


def _speak(text: str, gen: int) -> None:
    global player
    for i, (_, _, audio) in enumerate(pipe(text, voice=VOICE, speed=speed())):
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


def start(text: str) -> None:
    """Cut off whatever is playing and read text instead."""
    global generation, player
    with lock:
        generation += 1
        gen = generation
        if player and player.poll() is None:
            player.terminate()
        player = None
    def run() -> None:
        try:
            speak(text, gen)
        except Exception as e:  # keep serving
            print(f"speak failed: {e}", flush=True)
    threading.Thread(target=run, daemon=True).start()


def main() -> None:
    try:
        os.unlink(SOCK)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    os.chmod(SOCK, 0o600)
    srv.listen(4)
    print("kokoro-speak ready", flush=True)
    while True:
        conn, _ = srv.accept()
        with conn:
            data = b""
            while chunk := conn.recv(65536):
                data += chunk
        text = data.decode("utf-8", "replace").strip()
        if text and text != "ping":
            start(text)


if __name__ == "__main__":
    main()
