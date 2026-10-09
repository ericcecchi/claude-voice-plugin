# read-aloud

A Claude Code plugin that reads Claude's replies out loud, so you can look away from the screen while it works.

- **Off by default.** `/read-aloud` toggles it for the current session; `/read-aloud on` and `/read-aloud off` set it. A **Voice on / Voice off** button does the same: just above the prompt in the desktop app, in the prompt footer in the terminal (experimental, see below).
- **Replies:** when Claude finishes, Claude Haiku sums up the final message for the ear: the outcome, anything you need to do or decide, and any question for you, at a length that fits. Short replies are read as they are. If Haiku is slow or missing, it reads the message minus code, tables and pleasantries.
- **Acknowledgment:** a beat after you send a prompt, it reacts out loud in a sentence or two, so there's no dead air. The line comes from Claude Haiku (through `claude -p`, on your Claude login); if Haiku is slow or missing, from a local [Ollama](https://ollama.com) model; otherwise it's a canned one.
- **Updates (off by default):** on long tasks, it reads what Claude last wrote between tool calls (each line once), but only after 20 seconds of quiet, so short turns stay quiet.
- **Questions:** when an `AskUserQuestion` prompt opens, it gives a short heads-up.
- **Voice:** a warm [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) server if one is running, otherwise the system voice: `say` on macOS, `spd-say` or `espeak` on Linux. Or [ElevenLabs](https://elevenlabs.io), with your own API key. New speech cuts off the old.

Scheduled tasks and subagents are never read aloud.

## Requirements

- **Claude Code** with plugin support.
- **`python3` on your PATH.** A fresh Mac doesn't have it until the Xcode command line tools are installed (`xcode-select --install`). Without it the hooks fail silently.
- **A speech engine.** macOS has `say` built in. On Linux, install `speech-dispatcher` (`spd-say`) or `espeak-ng`.
- **Optional:** a local [Ollama](https://ollama.com) with `gemma4:e2b` as the fallback for acknowledgments, and the Kokoro server below for a better voice (macOS only, since it plays through `afplay`).

## Install

In Claude Code, add this repo as a marketplace, then install the plugin:

```
/plugin marketplace add ericcecchi/claude-voice-plugin
/plugin install read-aloud@claude-voice
```

A local checkout works too: `/plugin marketplace add /path/to/claude-voice-plugin`. Restart Claude Code, then type `/read-aloud` in any session to turn the voice on.

## Privacy and cost

Speech is synthesized on your machine. Two things go to Claude Haiku through your own `claude` login: your prompt (its first 1,500 characters) for the spoken reaction, and Claude's final message (when it's longer than a couple of sentences) for the summary. That's up to two small calls per turn. Set `READ_ALOUD_ACK_MODEL` and `READ_ALOUD_SUMMARY_MODEL` to empty to keep everything local. With the ElevenLabs engine, every spoken line also goes to ElevenLabs.

## Settings

These are saved for every session (in `~/.claude/read-aloud/config.json`):

| Command | Default | What it does |
|---|---|---|
| `/read-aloud updates on\|off` | off | Mid-task updates on long turns. |
| `/read-aloud reactions on\|off` | on | The short spoken reaction when you send a prompt. |
| `/read-aloud speed 1.3` | `1.2` | Speaking speed, 0.5 to 2.0, for Kokoro and the system voice. |
| `/read-aloud engine elevenlabs` | `kokoro` | What speaks: `kokoro` (Kokoro when its server runs, else the system voice), `elevenlabs`, or `system`. |
| `/read-aloud voice heart` | `af_heart` / George | The voice for the current engine: a Kokoro name (`heart`, `emma`, `am_fenrir`), or an ElevenLabs voice name or id from your account. |
| `/read-aloud voices` | | Lists the current engine's voices. |
| `/read-aloud settings` | | Shows what's set now. |

`/read-aloud`, `/read-aloud on` and `/read-aloud off` turn the voice on or off for the current session only.

For finer control, set these in the `env` block of `~/.claude/settings.json`:

| Variable | Default | What it does |
|---|---|---|
| `READ_ALOUD_DIRS` | unset | Colon-separated folders. If set, speak only when the session's cwd is inside one. |
| `READ_ALOUD_ACK_MODEL` | `haiku` | Claude model for the acknowledgment, via `claude -p`. Empty to skip it. |
| `READ_ALOUD_ACK_WAIT` | `8` | Seconds to wait for that model before falling back. |
| `READ_ALOUD_SUMMARY_MODEL` | `haiku` | Claude model that sums up the final message. Empty for the rule-based reading only. |
| `READ_ALOUD_SUMMARY_WAIT` | `60` | Seconds to wait for it before the rule-based reading. |
| `READ_ALOUD_EFFORT` | `high` | Effort level for every Haiku call. |
| `READ_ALOUD_OLLAMA_MODEL` | `gemma4:e2b` | Local Ollama model, the fallback. Empty to skip it. |
| `READ_ALOUD_SAY_RATE` | 175 × speed | System voice words per minute, overriding the speed setting. |
| `READ_ALOUD_PROGRESS_GAP` | `20` | Seconds of quiet before a mid-task update. `0` speaks every one. |

Each utterance is logged to `~/.claude/read-aloud.log` with the hook that spoke it and the engine (`kokoro` or `say`).

`touch ~/.claude/read-aloud.off` silences it everywhere; delete the file to undo.

State lives in `~/.claude/read-aloud/on/<session id>` (`on` or `off`), so other tools (for example a status-line toggle) can read or flip it.

## ElevenLabs

1. Get an API key from your ElevenLabs account, then make it available to Claude Code in one of two ways (never paste it into a chat):
   - add `"ELEVENLABS_API_KEY": "..."` to the `env` block of `~/.claude/settings.json`, or
   - store it in the macOS Keychain: `security add-generic-password -s elevenlabs -a "$USER" -w` (it prompts for the key).
2. Run `/read-aloud engine elevenlabs`, then `/read-aloud voices` and `/read-aloud voice <name>` to pick a voice. A restricted key needs the Text to Speech permission to speak, and Voices (read) to list voices or pick one by name; without it, pick one by its voice id. A 20-character voice id always works, including Voice Library voices, and can be set before switching engines.

It uses `eleven_v4` by default; `/read-aloud model eleven_v4_turbo` (or any model id) switches it and your speed setting, limited to ElevenLabs' 0.7–1.2 range. If a request fails, that line falls back to Kokoro or the system voice. ElevenLabs bills by character, so long replies cost more; the Haiku summary keeps them short.

## The voice button (experimental)

The **Voice on / Voice off** button is drawn with Claude Code's early-access plugin UI API, which changes between releases, so it may not appear on some versions or surfaces. The `/read-aloud` command and everything spoken are ordinary hooks and don't depend on it.

## Optional: Kokoro voice

`scripts/kokoro-speak-server.py` keeps Kokoro loaded and listens on `~/.claude/kokoro.sock`.

```bash
brew install espeak-ng
```

```bash
python3 -m venv ~/.kokoro-venv && ~/.kokoro-venv/bin/pip install kokoro soundfile numpy torch
```

Copy the server somewhere stable (the plugin's install path changes between versions), then keep it running with launchd. Save this as `~/Library/LaunchAgents/local.kokoro-speak.plist`, replacing `YOU`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.kokoro-speak</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOU/.kokoro-venv/bin/python</string>
    <string>/Users/YOU/.kokoro-venv/kokoro-speak-server.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>/Users/YOU/.claude/kokoro-speak.log</string>
  <key>StandardErrorPath</key><string>/Users/YOU/.claude/kokoro-speak.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/local.kokoro-speak.plist
```

`KOKORO_VOICE` (the default voice, `af_heart`, which `/read-aloud voice` overrides) and `KOKORO_DEVICE` (`cpu` by default; `mps` uses the GPU, but it's slower for this small model and roughens the voice) go in the plist's `EnvironmentVariables`. Voices differ in quality: Kokoro grades the US voices `af_heart` (A) and `af_bella` (A-) highest; the British ones, `bf_emma` (B-) and `bm_fable` (C), lower. See Kokoro's VOICES.md for the full list. The server reads `/read-aloud speed` and `/read-aloud voice` on every request, so changes need no restart.

## Development

```bash
python3 -m unittest discover tests
```

```bash
claude plugin validate .
```

```bash
claude plugin test .
```

Installed copies run from Claude Code's plugin cache, which refreshes only when the version changes: bump `version` in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` with every change, then run `claude plugin update read-aloud@claude-voice`.

## License

MIT
