#!/usr/bin/env python3
"""Runs read-aloud.py from the newest installed version of the plugin, not the one this session
started with, so updates reach sessions that are already open.

Claude Code points a session's hooks at the plugin version installed when the session started
(${CLAUDE_PLUGIN_ROOT}, e.g. …/cache/claude-voice/read-aloud/1.13.0). Versions sit side by side,
so this looks at its siblings and hands over to the highest one. Arguments and stdin pass through.
"""
import os
import re
import sys

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # this version's plugin root


def version(name):
    return tuple(int(n) for n in re.findall(r"\d+", name)) if re.fullmatch(r"\d+(\.\d+)*", name) else None


newest = here
parent = os.path.dirname(here)
if version(os.path.basename(here)) is not None:  # inside the cache; a working copy runs as is
    candidates = [(version(n), os.path.join(parent, n)) for n in os.listdir(parent) if version(n)]
    candidates = [c for c in candidates if os.path.isfile(os.path.join(c[1], "scripts", "read-aloud.py"))]
    if candidates:
        newest = max(candidates)[1]

script = os.path.join(newest, "scripts", "read-aloud.py")
os.environ["READ_ALOUD_ROOT"] = newest
os.execv(sys.executable, [sys.executable, script] + sys.argv[1:])
