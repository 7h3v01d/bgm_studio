# BGM Studio User Manual

Version 0.11.1 · Apache License 2.0

BGM Studio composes instrumental background music on demand. You give it a mood and a length; it composes an
original piece with a procedural composer, renders it with FluidSynth and a General MIDI SoundFont, and returns an
audio file of exactly that length. It can also score a narration: it fits the music under a voice-over, dips it
while someone is speaking and delivers a finished, loudness-normalised mix.

This manual covers installation, the musical concepts, every interface (desktop console, REST API, MCP server,
command line, Python), configuration, outputs and troubleshooting.

## Contents

1. [Overview](#1-overview)
2. [Installation](#2-installation)
3. [Concepts](#3-concepts)
4. [Desktop console](#4-desktop-console)
5. [Outputs: files, cue sheets, stems, provenance](#5-outputs-files-cue-sheets-stems-provenance)
6. [REST API](#6-rest-api)
7. [MCP server](#7-mcp-server)
8. [Command line](#8-command-line)
9. [Python](#9-python)
10. [Configuration reference](#10-configuration-reference)
11. [Deployment and security](#11-deployment-and-security)
12. [Troubleshooting](#12-troubleshooting)
13. [Glossary](#13-glossary)
- [Appendix A: Scene file format](#appendix-a-scene-file-format)
- [Appendix B: Launchers and scripts](#appendix-b-launchers-and-scripts)

---

## 1. Overview

### What it does

| Capability | Summary |
|---|---|
| Exact duration | Output is exactly the requested length, to the sample. Tempo is adjusted slightly so a whole number of bars fits. |
| Seamless loops | Loop mode folds the reverb tail back onto the start, so the file repeats without a click, gap or cut-off. |
| Proper endings | Non-loop tracks end on a cadence and fade out. |
| Long-form | Sections bring instruments in and out, and the material changes every few sections, so long beds don't sound like one short loop. Up to 2 hours. |
| Deterministic | The same settings and seed always produce the same music. |
| Twelve moods | General-purpose moods (calm, lofi, cinematic, …) and storytelling moods (horror, sleep, folklore, suspense). |
| Intensity | A single value or a tension curve shapes how busy, fast and loud the music is over time. |
| Sequences | One file whose mood changes at given cut points, in a shared key, with tempo matching and optional transition effects. |
| Narration scoring | Music fitted to a voice-over, ducked under speech and normalised to −16 LUFS. |
| Deliverables | A cue sheet (bars, sections, scenes, transitions), optional stems, and a provenance record with every render. |

### What it is not

BGM Studio writes rule-based music for General MIDI instruments: unobtrusive beds for video, podcasts and
narration, not foreground songs. It is not a digital audio workstation and has no note editor. Sound quality depends
mainly on the SoundFont you install (section 2.5).

### How the parts fit together

```
 Desktop console ─┐
 bgm_client.py ───┤                ┌─ composer (moods, intensity, sections)
 Any HTTP client ─┼─ REST API ─────┤
 AI agents ───────┼─ MCP server ───┼─ renderer (FluidSynth + SoundFont)
 Command line ────┼────────────────┤
 Python code ─────┘   (service)    └─ mixer (loudness, ducking, transitions, stems)
```

All interfaces call the same engine (`bgmstudio.service`), so the same request gives the same result whichever
interface you use. The desktop console and `bgm_client.py` talk to the REST API; the CLI, MCP server and Python
library call the engine directly.

---

## 2. Installation

### 2.1 Requirements

| Component | Notes |
|---|---|
| Python 3.11 or later | Windows, Linux or macOS. |
| FluidSynth shared library | The native synthesiser. Not installable with pip; see below. |
| FFmpeg and ffprobe | Loudness measurement, MP3/M4A/OGG encoding, reading narration files. Must be on `PATH`. |
| A General MIDI SoundFont (`.sf2`) | The instrument samples. GeneralUser GS or FluidR3_GM are recommended. |
| Disk space | Uncompressed WAV is about 10 MB per minute of stereo audio, plus stems if requested. |
| Memory | Rendering holds a few full-length stereo buffers: roughly 1.3 GB each per hour of audio. |

Python dependencies are listed in `requirements.txt` (NumPy, soundfile, mido, pyfluidsynth, FastAPI, uvicorn,
python-multipart, mcp, httpx, PyQt6).

### 2.2 Windows

1. Run **`setup.bat`**. It creates `.venv` in the project folder and installs the Python dependencies.
2. Put a General MIDI **SoundFont** in the project's `soundfonts\` folder.
3. Download the **FluidSynth** Windows x64 release and unzip it into the project's `fluidsynth\` folder. The DLLs may
   sit directly in that folder, in `bin\`, or one level down. Alternatively set `FLUIDSYNTH_DIR` to the folder that
   contains them.
4. Install **FFmpeg** so that `ffmpeg -version` and `ffprobe -version` work in a new terminal.
5. Run **`test.bat`**. It runs the test suite, then the end-to-end audio self-test, which should finish with
   `ALL PASSED`.

If any piece is missing, the error message names it and says where it is expected.

### 2.3 Linux and macOS

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# Debian/Ubuntu:  sudo apt install ffmpeg libfluidsynth3 fluid-soundfont-gm
# macOS:          brew install ffmpeg fluidsynth
export BGM_SOUNDFONT=/path/to/GeneralUser_GS.sf2     # or place the .sf2 in ~/.bgmstudio/
python -m pytest -q && python selftest.py
```

### 2.4 Verifying an installation or release

| Check | Command | What it proves |
|---|---|---|
| Unit and integration tests | `python -m pytest -q` | Engine, API, client and console logic. The console tests run offscreen and need no display. |
| End-to-end audio | `python selftest.py` | Real renders: exact lengths, seamless loops, loudness, ducking, sequences, transitions, MCP. |
| Client end to end | `python selftest_client.py` (`test_client.bat`) | `bgm_client.py` against a running service, including downloads and stems. |
| Release integrity | `python release_verify.py` | Every distributed file matches `RELEASE_SHA256.json`. |
| Full release check | `verify_release.bat` | Integrity, environment inventory, tests and self-test in one run. See `docs/RELEASING.md`. |

One test (`test_soundfont_licence_follows_symlinks_and_overrides`) is skipped on Windows unless symbolic links are
permitted (Developer Mode). That skip is expected.

### 2.5 SoundFonts and licensing

The SoundFont determines the sound. BGM Studio uses an explicitly passed path or `BGM_SOUNDFONT` if set; otherwise
it collects the `.sf2` files in the project's `soundfonts\` folder, `~/.bgmstudio/` (and its `soundfonts/`
subfolder) and the usual system locations, and picks GeneralUser GS first, then FluidR3, then any other.

| SoundFont | Licence | Use for published audio |
|---|---|---|
| GeneralUser GS | GeneralUser GS License v2.0 | Recommended. Permits use in music, including commercial. |
| FluidR3_GM | MIT | Suitable. |
| MuseScore_General | MIT (parts PD/CC0) | Suitable. |
| TimGM6mb | GPL-2.0 | Small and thin-sounding; whether the GPL reaches rendered audio is unsettled. Avoid for published work. |

The licence of the SoundFont governs the samples in your audio. Every render records the SoundFont's file name,
size, SHA-256 and licence in its provenance record (section 5.4). For a SoundFont that is not in the table above,
place its licence text in a file named `<font name>.license.txt` beside the `.sf2` (or set
`BGM_SOUNDFONT_LICENSE`); otherwise the record says `unknown`.

Streaming (section 6.4) uses a per-mood loudness calibration that is measured automatically for each SoundFont on
first use and cached in `~/.bgmstudio/calibration.json`. `calibrate.bat` (or
`python -m bgmstudio.cli calibrate`) measures it in advance.

---

## 3. Concepts

### 3.1 Moods

A mood is a preset: instruments, tempo range, scales, chord progressions, rhythm patterns and mix. Mood names are
case-insensitive; spaces and hyphens become underscores; aliases map to a mood.

| Mood | Character | BPM | Modes | Drums | Energy | Aliases |
|---|---|---|---|---|---|---|
| `calm` | Soft piano and warm pads, slow and spacious. Explainers, meditation, documentaries. | 60–76 | major, lydian, mixolydian | none | 1 | focus, peaceful, relaxing |
| `lofi` | Dusty e-piano, swung beat, mellow bass. Study, chill and tutorial backgrounds. | 68–84 | dorian, minor, major, mixolydian | lofi | 2 | chill, study |
| `cinematic` | Strings, cello, harp, big drums and reverb. Documentaries, history, storytelling. | 62–84 | minor, dorian, phrygian | epic | 4 | alt_history, documentary, epic, history, what_if |
| `uplifting` | Bright guitar arpeggios, pop beat, marimba hook. Motivation, product, travel. | 104–124 | major, mixolydian, lydian | pop | 4 | happy, motivational, positive |
| `corporate` | Clean piano, light pulse, vibraphone. Presentations, explainers, B2B. | 100–116 | major, mixolydian | pop | 3 | business, presentation |
| `dark` | Brooding synth bass, sweeping pads, music-box glints. True crime, mystery, tension. | 64–92 | minor, phrygian, dorian | minimal | 3 | mystery, true_crime |
| `ambient` | Slow evolving pads, harp, celesta. Sleep, focus, nature, long-form backgrounds. | 50–64 | lydian, major, dorian | none | 0 | nature, space |
| `tech` | Glassy arpeggios, synth bass, four-on-the-floor. Tech reviews, AI, futurism. | 116–128 | minor, dorian | fourfloor | 4 | electronic, futuristic, technology |
| `horror` | Choir pad over a contrabass drone, music box and distant bells, clashing tones. Horror. | 50–68 | phrygian, minor, harmonic minor | none | 1 | creepy, creepypasta, dread, haunted, scary, spooky |
| `sleep` | Very slow, flat and soft: warm pad, string drone, harp, rare celesta. No melody. Sleep stories. | 44–56 | major, lydian | none | 0 | bedtime, lullaby, sleep_story |
| `folklore` | Harp arpeggios, flute melody, cello and strings, frame drum. Myths, legends, folk tales. | 72–96 | dorian, mixolydian, minor, harmonic minor | frame | 2 | fairy_tale, fairytale, folk, legend, myth, mythology |
| `suspense` | Pizzicato ostinato, pulsing synth bass, heartbeat kick, uneasy strings. Thrillers, chases. | 84–104 | minor, phrygian, harmonic minor | heartbeat | 3 | chase, tension, thriller |

**Energy** (0–4) is used by automatic transitions and colours the console's scene bar. New moods are added as a
dictionary in `bgmstudio/presets.py`; no other code changes are needed (see `docs/DEVELOPMENT.md`).

### 3.2 Exact duration

Durations run from 4 seconds to 2 hours. The composer chooses a tempo near the mood's natural range such that a whole
number of bars (or, inside sequences, beats) fills the requested time, so the file is exactly
`round(duration × 44100)` samples long. Very short clips can therefore sound noticeably faster or slower than the
mood's usual tempo.

### 3.3 Seeds and determinism

Every result reports the seed it used. Supplying the same seed with the same settings and SoundFont reproduces the
same music. Leaving the seed empty picks a new one. A seed is the simplest way to keep a piece you like: note the seed,
and regenerate later at a different length or format.

### 3.4 Loops and endings

| Mode | Behaviour | Use for |
|---|---|---|
| `loop = false` (default) | Ends on a IV–I cadence over the last two bars, then fades out (`fade_out`, default 3 s). | A piece that plays once under content. |
| `loop = true` | No fade. Every note ends on the final bar line, and the reverb and release tails are folded back onto the start, so the end joins the beginning without a seam. | Background beds repeated by a player or game engine. |

Streaming cannot produce loops, because the tail fold needs the finished render.

### 3.5 Structure

A track is divided into sections (intro, verse, build, peak, break, outro), and each section kind brings a different
set of layers (pad, bass, keys, melody, sparkle, drums). Every six sections a new movement starts with fresh
progressions and patterns, so long pieces keep developing. The cue sheet (section 5.2) lists every section with its
start and end time.

### 3.6 Intensity

Intensity is an optional control from 0 to 1, available on every kind of render and on each scene of a sequence.

| Value | Effect |
|---|---|
| not set | The mood exactly as designed. |
| `0.5` | The mood's layers and dynamics as designed, with the tempo fixed at the middle of its range (unset picks a tempo from the seed). |
| below 0.5 | Fewer layers, softer playing, fewer ornaments, tempo towards the low end of the mood's range, quieter. |
| above 0.5 | More layers, harder playing, tempo towards the high end, louder. |
| a list, e.g. `[0.2, 0.3, 0.6, 1.0, 0.3]` | A tension curve spread evenly across the track (up to 64 points). Each section follows the curve. |

Level differences survive loudness normalisation: the span between intensity 0 and 1 is about 8 dB. In a sequence,
a scene's intensity also sets its level relative to the other scenes, and automatic transitions take it into account.

### 3.7 Sequences

A sequence is one file made of scenes, each with its own mood and length, in order.

- **Cuts land on the beat.** Each scene's first downbeat falls exactly at its start time (the sum of the earlier
  scenes' lengths). Total length equals the sum of scene lengths, to the sample.
- **Shared key.** All scenes use one key root (chosen from the keys the moods have in common, or set with `key`);
  modes may differ per scene.
- **Crossfade.** The outgoing scene fades out over `xfade` seconds (default 2) after each cut.
- **Tempo matching** (`tempo_match`, on by default) chooses tempos so neighbouring scenes stay within `max_bpm_jump`
  BPM (default 6). A 2:1 ratio counts as a match. Scenes may move slightly outside their mood's usual range to
  achieve this. A cut that cannot be matched is reported as a tempo warning. A scene's own `bpm` is always respected.
- **Transitions** are synthesised effects at the cuts, tuned to the key and independent of the SoundFont:

| Transition | Sound |
|---|---|
| `none` | Crossfade only (default). |
| `riser` | Noise sweep and a rising tone that end on the cut. |
| `impact` | A key-tuned sub boom and reverberant burst on the downbeat. |
| `riser_impact` | Both. |
| `downlifter` | A falling sweep starting on the cut. |
| `swell` | A smooth level lift into the cut. |
| `auto` | Chosen from the change in energy (mood energy adjusted by intensity): a large rise gives `riser_impact`, a small rise `riser`, little change `swell`, a drop `downlifter`. |

The request's `transitions` value applies to every cut; a scene's own `transition` overrides the cut into that scene.
`fx_level_db` (default −3) sets the effects' level relative to the music.

Scenes must be at least 4 seconds long. A sequence may have up to 100 scenes (configurable) and 2 hours in total.

### 3.8 Narration scoring

A mix takes a voice-over and returns `lead_in + narration + tail_out` seconds of audio, with the narration starting at
`lead_in`.

- **Music** is composed for the full length, either in one mood (optionally with intensity) or as a sequence of scenes.
  With scenes, the scene lengths must add up to the narration's length within 1.5 seconds; lead-in is added to the
  first scene and tail-out to the last.
- **Levels.** Narration is normalised to −16 LUFS and the music bed to −26 LUFS (`music_lufs`).
- **Ducking.** While someone speaks, the music dips a further `duck_db` (default 9 dB). The detector looks ahead so the
  dip begins just before the first word, and it holds through short word gaps so the music does not pump.
- **Final loudness.** The mix is normalised to −16 LUFS (`final_lufs`), with peaks kept below −1 dBFS.

Transitions in a mix are part of the music bed, so they duck with it.

### 3.9 Loudness

| Output | Default target |
|---|---|
| Track or sequence | −20 LUFS integrated (`target_lufs`, −40 to −8) |
| Mix | −16 LUFS (`final_lufs`) |
| Stream | Approximately −20 LUFS, using the per-SoundFont calibration (no look-ahead) |

File outputs are measured with FFmpeg's EBU R128 filter and normalised with a single gain, so loops stay seamless.

### 3.10 Formats

`wav` (default) and `flac` are 24-bit PCM; `mp3`, `m4a` (AAC) and `ogg` (Vorbis) are encoded with FFmpeg.
Streams are 16-bit WAV. Use WAV or FLAC when stems must add up exactly (section 5.3).

---

## 4. Desktop console

The console is a PyQt6 desktop application for producing tracks, sequences and narration mixes interactively. It
drives the REST service through `bgm_client.py` and does not import the engine.

### 4.1 Starting and stopping

Run **`run_gui.bat`** (or `python bgm_gui.py`). The console connects to `http://127.0.0.1:8765`; if no service is
running there, it starts one and shows **ONLINE** when ready. On exit it stops the service only if it started it.
`BGM_API_KEY` is passed to the service if set. **RECONNECT** repeats the connection (and start-up) at any time.

### 4.2 Layout

| Panel | Contents |
|---|---|
| 01 // PARAMETERS | Two tabs, **TRACK** and **SEQUENCE**, above settings shared by both: seed, format, **EXPORT STEMS**, export folder, file name, and the generate button. |
| 02 // STATUS | Current state (READY, RENDERING, SCORING, RENDER COMPLETE, FAILED, CHECK SETTINGS), elapsed time, details, RECONNECT. |
| 03 // LATEST OUTPUT | File name; seed, BPM, key, length, structure, stem count; the cue strip; playback; SoundFont licence; COPY SEED, REUSE SETTINGS, OPEN FOLDER. |
| 04 // LOG | Timestamped events. Warnings appear in amber and errors in red. |

Invalid input is outlined in red and explained in the status panel; nothing is sent to the service until it is
corrected. Before overwriting an existing file of the same name, the console asks for confirmation.

### 4.3 TRACK tab

| Control | Meaning |
|---|---|
| Mood | List and descriptions come from the service. |
| Duration | 4 s to 2 h; the clock beside it shows minutes and seconds. |
| Seamless loop | Loop mode (section 3.4). |
| Intensity | 0.00–1.00; 0.50 is the mood as designed (section 3.6). |

Press **GENERATE TRACK**.

### 4.4 SEQUENCE tab

**Scene table.** One row per scene:

| Column | Meaning |
|---|---|
| # | Scene number. |
| Mood | The scene's mood. |
| Length | Seconds (minimum 4). |
| Intensity | 0–1, or `—` for the mood as designed. |
| Into scene | The transition at the cut into this scene. `default` uses the sequence's default transition; the first scene has no cut. |
| BPM | `auto` lets tempo matching choose; a number fixes the scene's tempo (40–200). |
| Start | Where the scene starts, recalculated as lengths change. |

**+ SCENE** inserts a scene after the selected one, **DUPLICATE** copies it, **REMOVE** deletes it, and **▲ ▼** move
it.

**Scene bar.** Below the table, the plan is drawn to scale: blocks proportional to length, shaded by mood energy, with
amber marks at the cuts labelled R (riser), I (impact), RI (riser and impact), D (downlifter), S (swell) or A (auto).
When a narration is loaded, a dashed line marks where the voice ends. Clicking a block selects its row.

**Settings.** Default transition, crossfade, maximum BPM jump and **TEMPO MATCH** (section 3.7).

**Narration.** **BROWSE** loads a voice-over; the generate button becomes **SCORE NARRATION**. The scene total must be
within 1.5 s of the narration's length. The message beside the mix settings says whether it is, and **FIT** scales all
scenes proportionally to match exactly. Lead-in, tail-out and duck depth apply to the mix (section 3.8). **CLEAR**
returns to music-only sequences.

**LOAD / SAVE** read and write scene files (Appendix A), so a scene list written by another program can be opened,
adjusted and rendered.

### 4.5 Results and playback

After each render the output panel shows the file and its details. BPM is a range for sequences; the key shows the
shared root. The **cue strip** draws the file's structure: sections shaded by energy, a tick for every bar, amber
lines at transitions, scene numbers and boundaries for sequences, and a bar along the bottom where the narration
speaks. A teal line follows playback.

**PLAY** plays the file in the console, in any export format, with a seek bar. The audio player is created the first
time PLAY is pressed, so a faulty audio device cannot prevent the console from starting; set `BGM_GUI_NO_AUDIO=1` to
disable playback entirely.

**COPY SEED** puts the seed on the clipboard; **REUSE SETTINGS** puts it back into the seed field so the same music can
be rendered again with changes. The SoundFont licence line turns amber when the licence is unknown or GPL.

Closing the console during a render asks for confirmation. The service may finish that render, but the console will
not download it.

---

## 5. Outputs: files, cue sheets, stems, provenance

### 5.1 Files and caching

Renders are written to the output directory (`BGM_OUT_DIR`, default `bgm_out` in the working directory). The client
and the console then copy them to the destination you chose. Each render produces:

| File | Contents |
|---|---|
| `<name>.<format>` | The audio. |
| `<name>.json` | The full result: settings, per-scene details, cue sheet, stem paths and provenance record. |
| `<name>.stem-<part>.<format>` | Stems, when requested. |
| `<name>.mid` | MIDI, when requested (`midi` / `--midi`, single tracks only). |

File names include a hash of every setting that affects the sound, the SoundFont's SHA-256 and the engine revision.
A repeated request is answered from the cache immediately; identical requests made at the same time render once.
Before a cached file is reused, its size and SHA-256 are checked against its record, so damaged or modified files
are rendered again. The cache is never cleared automatically; delete files from the output directory when no longer
needed.

### 5.2 Cue sheets

Every result contains `cues`, a map of the file in seconds. Times are exact to the sample (individual notes are
humanised by up to ±12 ms around them). Example from a two-scene sequence:

```json
{
  "duration": 36.0,
  "time_signature": "4/4",
  "scenes": [
    {"scene": 1, "mood": "sleep",  "start": 0.0,  "end": 20.0, "bpm": 54.545, "beat_seconds": 1.1, "key": "F major"},
    {"scene": 2, "mood": "horror", "start": 20.0, "end": 36.0, "bpm": 60.0,   "beat_seconds": 1.0, "key": "F phrygian"}
  ],
  "sections": [
    {"scene": 1, "kind": "peak", "start": 0.0,  "end": 20.0, "bars": 5},
    {"scene": 2, "kind": "peak", "start": 20.0, "end": 36.0, "bars": 4, "intensity": 0.9}
  ],
  "downbeats": [0.0, 4.4, 8.8, 13.2, "…"],
  "transitions": [{"time": 20.0, "type": "riser_impact", "scene": 2}]
}
```

`downbeats` lists every bar line. Mixes add `"narration": {"start": …, "end": …}` in mix time. Uses include placing
video cuts, chapter cards and captions on the beat. MCP results omit `downbeats` to keep responses small, adding
`downbeat_count` instead; the full list is in the `.json` file.

### 5.3 Stems

With stems enabled, separate files are written beside the main file. Together they add up to it exactly.

| Render | Stems |
|---|---|
| Track | `pad`, `bass`, `keys`, `melody`, `sparkle`, `drums` (only the parts the mood uses) |
| Sequence | The instrument parts plus `fx` (the transition effects) |
| Mix | `voice`, `music`, `fx`, already aligned, ducked and levelled as in the mix |

FluidSynth carries a small amount of state from one note into the attack of the next when it reuses a voice, so a
full render and the sum of separately rendered instruments differ slightly. When stems are requested, the main file
is therefore built from the stems. It is cached separately, and may differ from a render without stems (same seed)
in the first milliseconds of some notes. Stems are limited to one hour per file. Stems in lossy formats will not add
up exactly; use WAV or FLAC.

### 5.4 Provenance

Every result contains `provenance`, a record of how the file was made, suitable for answering a rights enquiry or
checking a file later:

```json
{
  "generator": "bgmstudio", "version": "0.11.1", "kind": "sequence",
  "created_utc": "2026-11-11T17:21:23+00:00", "seed": 42,
  "request": {"scenes": [{"mood": "sleep", "duration": 20.0}, "…"], "xfade": 2.0, "tr": "auto", "…": "…"},
  "method": "Composed algorithmically (seeded procedural composer, no training data or sampled recordings of other music); rendered with FluidSynth from the SoundFont below.",
  "soundfont": {"file": "GeneralUser-GS.sf2", "bytes": 31277412, "sha256": "…",
                "license": "GeneralUser GS License v2.0", "music_use": "…", "source": "built-in table"},
  "fluidsynth": "2.3.4",
  "outputs": {"main": {"file": "seq_2scenes_36s_42_43fc….wav", "bytes": 9525644, "sha256": "…"}}
}
```

`outputs` holds the size and SHA-256 of every file written (main file, stems, MIDI), so a file can be matched to its
record. For mixes, `request.narration` records the narration's file name, SHA-256 and length.

---

## 6. REST API

Start the service with `run_server.bat`, `python -m bgmstudio.cli serve`, or
`uvicorn bgmstudio.api:app --host 127.0.0.1 --port 8765`. Interactive documentation, including every field and its
limits, is served at `http://127.0.0.1:8765/docs`.

If `BGM_API_KEY` is set, every endpoint except `/health` requires the header `X-API-Key: <key>`.

### 6.1 Endpoints

| Method and path | Purpose |
|---|---|
| `GET /health` | `{"ok": true, "soundfont_available": true}`, or `{"ok": false, "error": "…"}` explaining what is missing. No key needed. |
| `GET /moods` | `{mood: description}` for every mood. |
| `POST /bgm` | Render a track (6.2). |
| `POST /sequence` | Render a sequence (6.3). |
| `GET /bgm/stream` | Stream a track as it renders (6.4). |
| `POST /mix` | Score a narration (6.5). |
| `GET /files/{name}` | Download a file from the output directory (audio, stems, `.json`, `.mid`). |

`POST /bgm`, `/sequence` and `/mix` return the audio file by default, with details in `X-BGM-*` headers and
`X-BGM-Meta-URL` pointing to the JSON record. With `?as_json=true` they return the result as JSON, with
`download_url`, `meta_url`, `midi_url` and `stems` URLs under `/files/`.

### 6.2 POST /bgm

JSON body:

| Field | Default | Range / values |
|---|---|---|
| `mood` | `calm` | A mood or alias. |
| `duration` | 60 | 4–7200 seconds. |
| `loop` | false | Seamless loop instead of an ending. |
| `seed` | random | Integer. |
| `key` | per mood | e.g. `C`, `F#`, `Bb`. |
| `mode` | per mood | `major`, `minor`, `dorian`, `lydian`, `mixolydian`, `phrygian`, `harmonic_minor`. |
| `bpm` | per mood | 40–200; adjusted slightly to fit the duration. |
| `format` | `wav` | `wav`, `flac`, `mp3`, `m4a`, `ogg`. |
| `target_lufs` | −20 | −40 to −8. |
| `fade_out` | 3 | 0–30 seconds (ignored for loops). |
| `intensity` | not set | 0–1, or a list of up to 64 values. |
| `midi` | false | Also write a MIDI file. |
| `stems` | false | Also write stems. |

```bash
curl -X POST "http://127.0.0.1:8765/bgm?as_json=true" -H "Content-Type: application/json" \
     -d '{"mood": "folklore", "duration": 95, "seed": 7, "intensity": [0.3, 0.6, 0.9]}'
```

### 6.3 POST /sequence

| Field | Default | Notes |
|---|---|---|
| `scenes` | required | List of `{mood, duration, intensity?, transition?, bpm?, mode?, seed?}`, at least one. |
| `xfade` | 2 | 0–10 seconds. |
| `seed` | random | Each scene derives its own seed from this unless it sets one. |
| `key` | auto | Shared key root. |
| `tempo_match` | true | Section 3.7. |
| `max_bpm_jump` | 6 | 0–40. |
| `transitions` | `none` | Default transition for every cut. |
| `fx_level_db` | −3 | −24 to 6. |
| `format`, `target_lufs`, `fade_out`, `stems` | as `/bgm` | |

The JSON result adds `scenes` (per-scene mood, key, bpm, start, `transition_in`, `bpm_jump_from_prev` and, if tempo
matching could not close a gap, `tempo_warning`).

### 6.4 GET /bgm/stream

Query parameters: `mood`, `duration`, `seed`, `key`, `mode`, `bpm`, `target_lufs`, `fade_out`, and `intensity`
(a number or comma-separated curve). Returns 16-bit WAV with a known `Content-Length`. The first audio arrives in about
0.2 s, and rendering runs far faster than real time. Streams always end with a fade (no loops), and loudness is
approximate because the final level cannot be measured in advance.

### 6.5 POST /mix

`multipart/form-data` with the narration file in `narration` and these fields:

| Field | Default | Range |
|---|---|---|
| `mood` | `calm` | Used when no `scenes` are given. |
| `scenes` | none | JSON list as in `/sequence`; must add up to the narration within 1.5 s. |
| `lead_in` | 1.5 | 0–30 s of music before the first word. |
| `tail_out` | 3.0 | 0–60 s after the last word. |
| `music_lufs` | −26 | Bed level before ducking. |
| `duck_db` | 9 | 0–40 dB dip under speech. |
| `final_lufs` | −16 | Final level. |
| `intensity` | none | Single-mood mixes: a number or comma-separated curve. |
| `seed`, `key`, `format`, `xfade`, `tempo_match`, `max_bpm_jump`, `transitions`, `fx_level_db`, `stems` | as `/sequence` | |

```bash
curl -X POST "http://127.0.0.1:8765/mix?as_json=true" -F narration=@chapter1.mp3 \
     -F 'scenes=[{"mood":"sleep","duration":60},{"mood":"horror","duration":45,"intensity":0.9}]' \
     -F transitions=auto
```

### 6.6 Errors

| Status | Meaning |
|---|---|
| 400 | Malformed request (for example an invalid `Content-Length`). |
| 401 | Missing or wrong `X-API-Key`. |
| 413 | Narration upload larger than `BGM_MAX_UPLOAD_BYTES`. |
| 422 | Invalid input. The message names the field and the problem (unknown mood, out-of-range value, scene lengths not matching the narration, undecodable audio, over a limit). |
| 500 | Server-side problem, such as a missing SoundFont, FluidSynth library or FFmpeg, or an output that could not be written. The message says what to fix. |
| 503 | Busy: the render lock could not be acquired in time. Retry after the `Retry-After` interval. |
| 504 | FFmpeg or ffprobe exceeded `BGM_FFMPEG_TIMEOUT`. |

---

## 7. MCP server

The MCP server exposes the engine to AI agents and MCP-capable applications.

```bash
python -m bgmstudio.mcp_server                       # stdio
python -m bgmstudio.mcp_server --http --port 8766    # streamable HTTP at /mcp   (run_mcp.bat)
```

Example client configuration (stdio):

```json
{"mcpServers": {"bgm": {"command": "python", "args": ["-m", "bgmstudio.mcp_server"], "cwd": "/path/to/bgm_studio"}}}
```

| Tool | Purpose |
|---|---|
| `list_moods` | Moods and descriptions. |
| `generate_bgm` | A track: `mood`, `duration_seconds`, `loop`, `seed`, `key`, `bpm`, `format`, `target_lufs`, `output_dir`, `also_midi`, `intensity`, `stems`. |
| `generate_scene_sequence` | A sequence: `scenes`, `xfade`, `seed`, `key`, `format`, `target_lufs`, `output_dir`, `tempo_match`, `max_bpm_jump`, `transitions`, `fx_level_db`, `stems`. |
| `mix_with_narration` | A mix: `narration_path`, `mood`, `lead_in`, `tail_out`, `music_lufs`, `duck_db`, `final_lufs`, `seed`, `format`, `output_dir`, `scenes`, `xfade`, `tempo_match`, `max_bpm_jump`, `transitions`, `fx_level_db`, `intensity`, `stems`. |

The tools read and write files on the machine where the server runs, within limits set by the operator:

- Outputs are written inside `BGM_MCP_OUTPUT_DIR` (default: the output directory). A requested `output_dir` outside it
  is refused.
- Narration can only be read from inside `BGM_MCP_INPUT_DIR`. Until that variable is set, `mix_with_narration` is
  refused.

---

## 8. Command line

### 8.1 Engine CLI (`python -m bgmstudio.cli`)

Runs renders directly, without the REST service.

```bash
python -m bgmstudio.cli moods
python -m bgmstudio.cli generate lofi 95 --loop --seed 7 --midi
python -m bgmstudio.cli generate horror 600 --intensity 0.2,0.3,0.5,0.9,0.3 --stems
python -m bgmstudio.cli sequence sleep:60:0.1,suspense:45,horror:30:1.0 --transitions auto
python -m bgmstudio.cli mix chapter1.mp3 calm --duck-db 12
python -m bgmstudio.cli mix chapter1.mp3 x --scenes sleep:60,horror:45 --transitions auto
python -m bgmstudio.cli calibrate
python -m bgmstudio.cli serve --host 127.0.0.1 --port 8765
```

| Command | Options |
|---|---|
| `generate MOOD SECONDS` | `-o/--out-dir`, `--loop`, `--seed`, `--key`, `--mode`, `--bpm`, `--format`, `--lufs`, `--midi`, `--stems`, `--intensity` |
| `sequence SCENES` | `mood:seconds[:intensity]` comma-separated; `-o`, `--xfade`, `--seed`, `--key`, `--format`, `--transitions`, `--no-tempo-match`, `--max-bpm-jump`, `--fx-level-db`, `--stems` |
| `mix NARRATION MOOD` | `-o`, `--seed`, `--format`, `--music-lufs`, `--duck-db`, `--intensity`, `--scenes`, `--transitions`, `--no-tempo-match`, `--max-bpm-jump`, `--fx-level-db`, `--stems`. With `--scenes`, the mood argument is ignored. |
| `moods`, `calibrate`, `serve` | `serve`: `--host`, `--port`. |

### 8.2 Client CLI (`python bgm_client.py`)

Calls a running service (starting it if needed), so it works from any Python environment with `httpx`.

```bash
python bgm_client.py health
python bgm_client.py music ambient 45 -o loop.wav --loop --seed 3
python bgm_client.py sequence calm:20,cinematic:25 -o score.wav --transitions auto
python bgm_client.py score narration.mp3 -o scored.wav --scenes calm:20,dark:30 --lead-in 1.5
python bgm_client.py mux silent.mp4 scored.wav -o final.mp4 --trim-audio-start 1.5
```

Global options: `--url`, `--key`, `--project-dir`.

---

## 9. Python

### 9.1 Client library (`bgm_client.py`)

A single file with no dependency on the engine: copy it into any project that needs music.

```python
from bgm_client import BGMClient

with BGMClient(project_dir=r"C:\tools\bgm_studio") as bgm:     # starts the service if it is not running
    bgm.music("lofi", 312.5, "bed.wav")                          # exact-length bed
    bgm.music("ambient", 45, "loop.wav", loop=True, stems=True)  # seamless loop with stems
    bgm.sequence([("calm", 20), ("cinematic", 25, 0.9)], "score.wav", transitions="auto")
    info = bgm.score("narration.mp3", "scored.wav", scenes="calm:20,cinematic:25,dark:20")
    bgm.mux("silent.mp4", "scored.wav", "final.mp4", trim_audio_start=info["lead_in"])
```

| Method | Returns |
|---|---|
| `music(mood, duration, out, *, loop, seed, key, mode, bpm, target_lufs, fade_out, intensity, stems)` | `path`, `seed`, `bpm`, `key`, `duration`, `loop`, `cues`, `provenance`, `stems`, `meta_path` |
| `sequence(scenes, out, *, xfade, seed, key, target_lufs, fade_out, tempo_match, max_bpm_jump, transitions, fx_level_db, stems)` | adds `scenes` and `warnings` |
| `score(narration, out, *, mood, scenes, lead_in, tail_out, music_lufs, duck_db, final_lufs, seed, key, xfade, tempo_match, max_bpm_jump, transitions, fx_level_db, intensity, stems)` | `path`, `seed`, `lead_in`, `tail_out`, `total_seconds`, `final_lufs`, `cues`, `provenance`, `stems`, `meta_path` |
| `stream(mood, duration, out, *, seed, key, target_lufs, intensity)` | Streams to `out`. |
| `mux(video, audio, out, *, trim_audio_start, audio_codec, audio_bitrate)` | Adds audio to a video without re-encoding the picture. |
| `health()`, `moods()` | Service status and mood list. |

Scenes may be given as `"mood:seconds[:intensity],…"`, as tuples, or as dictionaries. The client downloads stems
beside `out` and saves the JSON record as `<out without extension>.json`. Leaving the `with` block stops the service
only if the client started it. Errors raise `BGMError` with a readable message.

`score()` returns `lead_in + narration + tail_out` seconds of audio, with the narration starting at `lead_in`. If the
video starts with the narration, pass `lead_in=0` or mux with `trim_audio_start=lead_in`.

Configuration from the environment: `BGM_URL` (default `http://127.0.0.1:8765`), `BGM_API_KEY`, `BGM_PROJECT_DIR`.

### 9.2 Engine library

```python
from bgmstudio import service

r = service.generate_bgm("cinematic", 184.2, seed=3, intensity=[0.2, 0.8])
r = service.generate_sequence([{"mood": "sleep", "duration": 30}, {"mood": "horror", "duration": 20}],
                              transitions="auto")
r = service.mix_with_narration("narration.wav", "calm", duck_db=12)
print(r["path"], r["cues"]["sections"], r["provenance"]["soundfont"]["license"])
```

Invalid input raises `ValueError` with the same messages the REST API returns.

---

## 10. Configuration reference

All settings are environment variables. Limits are checked before any rendering starts.

| Variable | Default | Purpose |
|---|---|---|
| `BGM_SOUNDFONT` | auto | Path to the `.sf2` to use. |
| `BGM_SOUNDFONT_LICENSE` | none | Licence text to record for a SoundFont not in the built-in table. |
| `FLUIDSYNTH_DIR` | auto | Folder containing the FluidSynth library (Windows). |
| `BGM_OUT_DIR` | `bgm_out` | Output and cache directory. |
| `BGM_API_KEY` | none | Require `X-API-Key` on the REST API (and send it from the client). |
| `BGM_URL` | `http://127.0.0.1:8765` | Service address used by `bgm_client.py`. |
| `BGM_PROJECT_DIR` | none | Project folder `bgm_client.py` uses to start the service. |
| `BGM_CAL_FILE` | `~/.bgmstudio/calibration.json` | Streaming loudness calibration cache. |
| `BGM_MAX_RENDER_SECONDS` | 7200 | Longest output, including a mix's lead-in and tail-out. |
| `BGM_MAX_SCENES` | 100 | Most scenes per sequence or mix. |
| `BGM_MAX_UPLOAD_BYTES` | 104857600 | Largest narration file (100 MiB). |
| `BGM_MAX_RENDER_MEMORY_MIB` | 16384 | Estimated working-memory ceiling per render; larger requests are refused before rendering. An estimate, not a measurement of free RAM. |
| `BGM_FFMPEG_TIMEOUT` | 180 | Seconds before an FFmpeg or ffprobe call is abandoned. |
| `BGM_LOCK_TIMEOUT` | 600 | Seconds to wait for the render lock before returning 503. |
| `BGM_STRICT_CACHE_HASHES` | 0 | `1` re-hashes cached files on every reuse, catching edits that preserved size and timestamp. |
| `BGM_MCP_OUTPUT_DIR` | output directory | Root that MCP outputs must stay inside. |
| `BGM_MCP_INPUT_DIR` | none | Root that MCP narration must come from; MCP narration is refused until set. |
| `BGM_GUI_NO_AUDIO` | 0 | `1` disables playback in the console. |

Per-request value ranges (also shown at `/docs`): `target_lufs`, `music_lufs`, `final_lufs` −40 to −8; `fade_out`
0–30 s; `lead_in` 0–30 s; `tail_out` 0–60 s; `duck_db` 0–40; `xfade` 0–10 s; `max_bpm_jump` 0–40; `fx_level_db`
−24 to 6; `bpm` 40–200; intensity 0–1 (curves up to 64 points); scenes at least 4 s.

---

## 11. Deployment and security

BGM Studio is designed for a single trusted user on a local machine. Keep the REST API and the MCP HTTP server bound
to `127.0.0.1` (the default for the launchers). Before exposing them to a network, read `docs/SECURITY.md`, which
describes the protections in place (input limits, upload caps, path confinement for MCP, timeouts, constant-time key
comparison, cache integrity checks) and the controls a deployment must add (authentication, a reverse proxy with
body-size limits, per-user file ownership, isolation for decoding untrusted media).

---

## 12. Troubleshooting

| Symptom | Cause and remedy |
|---|---|
| `No SoundFont (.sf2) found` | Put a General MIDI `.sf2` in `soundfonts\` or set `BGM_SOUNDFONT`. |
| `Incompatible fluidsynth Python module` or FluidSynth library not found | Install the native FluidSynth library (section 2.2/2.3) or set `FLUIDSYNTH_DIR`. `pyfluidsynth` is only the Python wrapper. Remove any unrelated package named `fluidsynth`. |
| `ffmpeg` / `ffprobe` not found | Install FFmpeg and open a new terminal so `PATH` is updated. |
| Console shows **NO SERVICE** | The service could not start or is unhealthy; the status panel shows the reason. Check the points above, then press RECONNECT. |
| 422 `scene durations add up to … but the narration is …` | Make the scenes add up to the narration (the console's FIT does this). |
| 422 `total duration exceeds render budget` | The request is longer than `BGM_MAX_RENDER_SECONDS`. |
| 422 `estimated render memory … exceeds budget` | Shorten the render, skip stems, or raise `BGM_MAX_RENDER_MEMORY_MIB` on a machine with enough RAM. |
| 503 busy | Another long render holds the lock. Wait and retry; cached results are still served immediately. |
| `audio output could not be written` | Check free space and permissions on the output directory and on `%TEMP%`, and whether antivirus or sync software is holding the files. The service log records the path, size and free space. |
| Music sounds thin | Use a full SoundFont such as GeneralUser GS (section 2.5). |
| Streaming level differs from files | Streams use a calibrated estimate. Run `calibrate.bat` after changing SoundFont, or use file outputs for exact loudness. |
| Tempo warning in a sequence | Neighbouring scenes could not be brought within `max_bpm_jump`. Lengthen short scenes, raise the limit, fix a scene's BPM, or turn tempo matching off. |
| No sound from PLAY in the console | Check the system output device. Playback can be disabled with `BGM_GUI_NO_AUDIO=1`; files are unaffected. |

---

## 13. Glossary

| Term | Meaning |
|---|---|
| Bar / downbeat | A measure of four beats; the downbeat is its first beat. Cue sheets list every downbeat. |
| Cadence | A chord progression that sounds like an ending (here IV–I). |
| Cue sheet | The timing map of a rendered file (section 5.2). |
| Ducking | Lowering the music while someone speaks. |
| Energy | A mood's busyness from 0 to 4, used by automatic transitions. |
| Intensity | A 0–1 control or curve over how busy and loud the music is. |
| LUFS | Loudness units relative to full scale (EBU R128); −16 LUFS is a common level for spoken content online. |
| Provenance | The record of how a file was made (section 5.4). |
| Scene | One segment of a sequence, with its own mood and length. |
| Seed | The number that makes a render reproducible. |
| SoundFont | A file of instrument samples (`.sf2`) that FluidSynth plays. |
| Stem | One part of a mix as a separate file. |

---

## Appendix A: Scene file format

Scene files are JSON. The console writes:

```json
{
  "format": "bgmstudio-scenes",
  "version": 1,
  "scenes": [
    {"mood": "sleep", "duration": 24},
    {"mood": "suspense", "duration": 26, "intensity": 0.6},
    {"mood": "horror", "duration": 28, "intensity": 0.95, "transition": "riser_impact", "bpm": 60}
  ],
  "settings": {"transitions": "auto", "xfade": 2.0, "tempo_match": true, "max_bpm_jump": 6.0,
               "lead_in": 1.5, "tail_out": 3.0, "duck_db": 9.0}
}
```

Each scene needs `mood` and `duration`; `intensity`, `transition` and `bpm` are optional. The console also opens the
body of a `POST /sequence` request (`{"scenes": [...]}`) or a bare list of scenes. Mood names are matched without
regard to case. Unknown moods are refused by name, and badly typed settings fall back to their defaults. The console
keeps one intensity per scene, so an intensity curve in a file is opened as its average.

## Appendix B: Launchers and scripts

| File | Purpose |
|---|---|
| `setup.bat` | Create `.venv` and install Python dependencies. |
| `test.bat` | Test suite, then the end-to-end audio self-test. |
| `run_gui.bat` | Desktop console. |
| `run_server.bat` | REST API on 127.0.0.1:8765. |
| `run_mcp.bat` | MCP server over HTTP on port 8766. |
| `calibrate.bat` | Measure streaming loudness for the current SoundFont. |
| `test_client.bat` | End-to-end test of `bgm_client.py`. |
| `verify_release.bat` | Full release verification (`docs/RELEASING.md`). |
| `selftest.py`, `selftest_client.py` | End-to-end audio and client tests. |
| `release_verify.py` | Integrity check against `RELEASE_SHA256.json`. |
| `example_client.py` | Minimal REST example. |
