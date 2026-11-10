# BGM Studio

Procedural background music, composed on demand. Ask for a mood and a length and BGM Studio composes an original
instrumental piece, renders it with FluidSynth and a General MIDI SoundFont, and returns a file of exactly that
length. It can also score a narration: music fitted under a voice-over, dipped while someone speaks, delivered as a
finished, loudness-normalised mix.

It runs locally and is reachable from a desktop console, a REST API, an MCP server for AI agents, a command line and
Python.

- **Exact length, to the sample.** Tempo is adjusted slightly so a whole number of bars fills the requested time.
- **Seamless loops or proper endings.** Loops fold the reverb tail back onto the start; non-loops end on a cadence.
- **Long-form.** Sections and changing material keep beds of up to two hours from sounding like one short loop.
- **Deterministic.** The same settings and seed reproduce the same music.
- **Twelve moods**, including four for storytelling (horror, sleep, folklore, suspense), plus aliases.
- **Intensity and tension curves** shape how busy, fast and loud the music is over time.
- **Sequences.** One file whose mood changes at your cut points, in a shared key, with tempo matching and
  synthesised transitions.
- **Narration scoring** with look-ahead ducking and EBU R128 loudness normalisation.
- **Deliverables.** Every render comes with a cue sheet (bars, sections, scenes, transitions), optional stems that add
  up exactly to the mix, and a provenance record (inputs, seed, SoundFont and its licence, file hashes).

## Quick start (Windows)

1. Run `setup.bat` (creates `.venv`, installs the Python dependencies).
2. Add a General MIDI SoundFont (`.sf2`, e.g. GeneralUser GS) to `soundfonts\`.
3. Unzip the FluidSynth Windows x64 release into `fluidsynth\`.
4. Install FFmpeg so `ffmpeg` and `ffprobe` are on `PATH`.
5. Run `test.bat`, which should end with `ALL PASSED`.
6. Run `run_gui.bat` for the desktop console, or `run_server.bat` for the REST API at `http://127.0.0.1:8765/docs`.

Linux and macOS: install `ffmpeg` and the FluidSynth library from the system package manager, then
`pip install -r requirements.txt` and set `BGM_SOUNDFONT`. See the [User Manual](docs/USER_MANUAL.md#2-installation).

## Examples

```bash
# A 95-second seamless loop
python -m bgmstudio.cli generate lofi 95 --loop --seed 7

# Ten minutes of horror following a tension curve, with stems
python -m bgmstudio.cli generate horror 600 --intensity 0.2,0.3,0.5,0.9,0.3 --stems

# One file, three scenes, transitions chosen automatically
python -m bgmstudio.cli sequence sleep:60:0.1,suspense:45,horror:30:1.0 --transitions auto
```

```python
from bgm_client import BGMClient    # single file, needs only httpx

with BGMClient(project_dir=r"C:\tools\bgm_studio") as bgm:
    info = bgm.score("narration.mp3", "scored.wav", scenes="calm:20,cinematic:25,dark:20", transitions="auto")
    bgm.mux("silent.mp4", "scored.wav", "final.mp4", trim_audio_start=info["lead_in"])
```

```bash
curl -X POST "http://127.0.0.1:8765/bgm?as_json=true" -H "Content-Type: application/json" \
     -d '{"mood": "folklore", "duration": 95, "seed": 7}'
```

## Documentation

| Document | Contents |
|---|---|
| [User Manual](docs/USER_MANUAL.md) | Installation, concepts, desktop console, REST API, MCP, CLI, Python, configuration, troubleshooting. |
| [Security](docs/SECURITY.md) | Intended deployment, protections, and what a networked deployment must add. |
| [Development](docs/DEVELOPMENT.md) | Architecture, determinism and caching rules, tests, adding moods, contributing. |
| [Releasing](docs/RELEASING.md) | Release verification and the integrity manifest. |
| [Changelog](CHANGELOG.md) | Version history. |

## Project layout

```
bgmstudio/          engine: composer, renderer, mixer, effects, service, REST API, MCP server, CLI
bgmgui/             PyQt6 desktop console (talks to the REST API)
bgm_client.py       single-file Python client and client CLI
bgm_gui.py          console launcher
tests/              pytest suite (engine, API, client, console)
selftest.py         end-to-end audio test;  selftest_client.py: client end-to-end test
docs/               user manual and project documentation
*.bat               Windows launchers (setup, test, console, server, MCP, calibration, release check)
```

## Requirements

Python 3.11+, the FluidSynth library, FFmpeg/ffprobe, and a General MIDI SoundFont. Python packages are listed in
`requirements.txt`.

## Licence

BGM Studio is licensed under the [Apache License 2.0](LICENSE). Copyright 2026 Leon Priest
([7h3v01d](https://github.com/7h3v01d)).

FluidSynth, FFmpeg and SoundFonts are installed separately and carry their own licences (see [NOTICE](NOTICE)). The
SoundFont's licence governs the samples in rendered audio. GeneralUser GS and FluidR3_GM are suitable for published
work; the provenance record of every render names the SoundFont and its licence.

## Limitations

BGM Studio writes rule-based music for General MIDI instruments, aimed at unobtrusive beds for video, podcasts and
narration rather than foreground songs, and its quality depends largely on the SoundFont. It is designed for a single
trusted user on a local machine; see [Security](docs/SECURITY.md) before exposing it to a network.
