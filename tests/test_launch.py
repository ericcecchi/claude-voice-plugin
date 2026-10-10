"""scripts/launch.py hands over to the newest installed version."""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

LAUNCH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "launch.py"
FAKE = 'import os, sys; print(os.path.basename(os.path.dirname(os.path.dirname(__file__))), sys.argv[1:], sys.stdin.read())'


class Launch(unittest.TestCase):
    def setUp(self):
        self.cache = pathlib.Path(tempfile.mkdtemp()) / "read-aloud"
        self.addCleanup(shutil.rmtree, self.cache.parent)

    def install(self, version, script=True):
        scripts = self.cache / version / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy(LAUNCH, scripts / "launch.py")
        if script:
            (scripts / "read-aloud.py").write_text(FAKE)
        return scripts / "launch.py"

    def run_launch(self, launch, *args):
        out = subprocess.run([sys.executable, str(launch), *args], input="event", capture_output=True, text=True)
        return out.stdout.strip()

    def test_runs_the_newest_version(self):
        old = self.install("1.9.0")
        self.install("1.10.0")
        self.install("1.2.5")
        self.assertEqual(self.run_launch(old, "toggle"), "1.10.0 ['toggle'] event")  # numeric order

    def test_skips_a_version_without_the_script(self):
        old = self.install("1.9.0")
        self.install("2.0.0", script=False)  # half-installed
        self.assertEqual(self.run_launch(old), "1.9.0 [] event")

    def test_a_working_copy_runs_itself(self):
        work = self.cache.parent / "claude-voice-plugin"
        (work / "scripts").mkdir(parents=True)
        shutil.copy(LAUNCH, work / "scripts" / "launch.py")
        (work / "scripts" / "read-aloud.py").write_text(FAKE)
        self.install("9.9.9")
        self.assertEqual(self.run_launch(work / "scripts" / "launch.py"), "claude-voice-plugin [] event")


if __name__ == "__main__":
    unittest.main()
