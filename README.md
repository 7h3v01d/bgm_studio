# bgmstudio: procedural background music for your video pipeline

A small service that composes instrumental background music from a **mood + duration** and renders it with
FluidSynth. Same idea as your voice appliance: your app calls it over **REST** or **MCP**, gets audio of
*exactly* the length it asked for. No per-track fees, no licensing questions: you own the output.

* **Exact duration.** Tempo is nudged slightly so a whole number of bars equals the requested length to the sample.
* **Seamless loops** (`loop=true`). Every note ends on the last bar line; the renderer folds the reverb/release tail
  back onto the start, so the wrap point has no click, no cut-off tail and no gap.
* **Proper endings** (`loop=false`). Plagal cadence (IV to I) on the last two bars, then a fade.
* **Long-form.** Sections (intro, verse, build, peak, break, outro) layer instruments in and out; a new *movement*
  (fresh chords and patterns) starts every 6 sections, so a 30-minute bed doesn't feel like one 30-second loop.
* **Deterministic.** Same `(mood, duration, seed, ...)` returns identical music. The seed comes back in the response,
  so you can regenerate or tweak a scene later.
* **Streaming.** `GET /bgm/stream` sends progressive WAV that starts in ~0.2 s and generates far faster than realtime.
* **Voice-aware mixing.** `POST /mix` takes your narration, fits music to it, ducks the music under speech
  (with look-ahead and word-gap hold, so it doesn't pump), and normalises to -16 LUFS.

Moods: `calm, lofi, cinematic, uplifting, corporate, dark, ambient, tech`, plus four for storytelling:
`horror, sleep, folklore, suspense` (+ aliases like `chill`, `epic`, `creepypasta`, `bedtime`, `myth`, `tension`).
Add your own by adding a dict in `presets.py`; no code changes needed.

| Story mood | Sound | Aliases |
|---|---|---|
| `horror` | choir pad over a contrabass drone, music box, distant bells, clashing tones; no beat | creepy, creepypasta, scary, spooky, haunted, dread |
| `sleep` | 44-56 BPM, flat and soft, string drone, harp, rare celesta; no drums, no melody | bedtime, sleep_story, lullaby |
| `folklore` | harp arpeggios, flute melody, cello and strings, frame drum, slight lilt | folk, myth, mythology, legend, fairytale |
| `suspense` | pizzicato ostinato, pulsing synth bass, heartbeat kick, uneasy strings | tension, thriller, chase |

## Intensity (tension curves)

Every generate/stream/mix call and every scene takes an optional `intensity`:

* a number `0..1`: `0.5` is the mood as designed; lower is sparser, slower and quieter, higher is busier, faster and
  louder (within the mood's own tempo range), or
* a list of `0..1` points spread evenly across the track, e.g. `[0.2, 0.3, 0.6, 1.0, 0.3]`: a tension curve.
  Each section follows the curve, and quiet stretches stay quiet after loudness normalisation (up to 8 dB apart).

In a sequence, a scene's intensity also sets its level against the other scenes, and `transitions: "auto"` reads
it: a jump in tension gets a riser/impact, a drop gets a downlifter. Leave `intensity` out and the music is
note-for-note what earlier versions made.

```bash
python -m bgmstudio.cli generate horror 600 --intensity 0.2,0.3,0.5,0.9,0.3 --seed 7
python -m bgmstudio.cli sequence sleep:60:0.1,horror:45:0.6,horror:30:1.0 --transitions auto
```

## Install

```bash
pip install -r requirements.txt
# system packages: ffmpeg, plus the FluidSynth library
#   Debian/Ubuntu: sudo apt install ffmpeg libfluidsynth3 fluid-soundfont-gm
#   macOS:         brew install ffmpeg fluidsynth
#   Windows:       install FluidSynth (add its bin/ to PATH) and ffmpeg
python selftest.py          # full integration test, should end with ALL PASSED
```

**Sound quality = your SoundFont.** The service auto-finds one, but the tiny default GM font is thin. For a big
upgrade, download a free SF2 such as *GeneralUser GS* or *FluidR3_GM* and point at it:
`export BGM_SOUNDFONT=/path/to/GeneralUser_GS.sf2` (or drop it in `~/.bgmstudio/`). Check the font's licence if you
distribute audio commercially. Streaming loudness is calibrated automatically per SoundFont on first use (cached in `~/.bgmstudio/calibration.json`; pre-warm with `python -m bgmstudio.cli calibrate`).

## Windows setup (venv)

`setup.bat` (venv + `pip install -r requirements.txt`) is all the Python side needs. Three native pieces are not pip-installable;
drop them **inside the project folder** and the code finds them automatically:

1. **SoundFont:** put a General MIDI `.sf2` (GeneralUser GS or FluidR3_GM) in `soundfonts\`.
2. **FluidSynth DLLs:** unzip the FluidSynth Windows x64 release into `fluidsynth\` (the `.dll` files can sit in that folder,
   in `bin\`, or one folder down). Or set `FLUIDSYNTH_DIR` to the folder containing them.
3. **ffmpeg + ffprobe** on your PATH (`ffmpeg -version` should work in a new terminal).

Then run `test.bat` (fast regression tests via pytest, then the full selftest). Anything missing produces an error naming
exactly what to add and where.

## REST

```bash
uvicorn bgmstudio.api:app --host 0.0.0.0 --port 8765      # BGM_API_KEY=secret to require X-API-Key
```

| Endpoint | What |
|---|---|
| `POST /bgm` | JSON `{mood, duration, loop, seed, key, mode, bpm, format, target_lufs, fade_out, midi}` returns the audio file (metadata in `X-BGM-*` headers). `?as_json=true` returns metadata + `download_url`. |
| `GET /bgm/stream?mood=&duration=&seed=` | Progressive 16-bit WAV, `Content-Length` known up front. Non-loop. |
| `POST /mix` | multipart: `narration` file + `mood, lead_in, tail_out, music_lufs, duck_db, final_lufs, seed, format` returns the finished mix. |
| `GET /moods`, `GET /health`, `GET /files/{name}` | helpers |

Out-of-range parameters return **422** naming the field; the limits are listed in `/docs` and in `bgmstudio.service.LIMITS`.
Identical requests made at the same time render once and share the cached file.

`format`: wav, flac, mp3, m4a, ogg. Results are cached on disk by parameters (`BGM_OUT_DIR`, default `./bgm_out`).

```python
# see example_client.py
r = httpx.post("http://127.0.0.1:8765/bgm", json={"mood": "lofi", "duration": 312.5, "loop": False})
open("bed.wav", "wb").write(r.content)
```

## MCP

```bash
python -m bgmstudio.mcp_server                      # stdio
python -m bgmstudio.mcp_server --http --port 8766   # streamable HTTP at /mcp
```
Tools: `list_moods`, `generate_bgm(mood, duration_seconds, loop, seed, key, bpm, format, target_lufs, output_dir, also_midi)`,
`mix_with_narration(narration_path, mood, ...)`. They read and write files on the machine the server runs on.
Claude Desktop / Claude Code config: `{"mcpServers": {"bgm": {"command": "python", "args": ["-m", "bgmstudio.mcp_server"], "cwd": "/path/to/bgm_studio"}}}`

## CLI / library

```bash
python -m bgmstudio.cli generate lofi 95 --loop --seed 7 --midi
python -m bgmstudio.cli mix narration.mp3 cinematic
```
```python
from bgmstudio import service
r = service.generate_bgm("cinematic", 184.2, seed=3)      # -> {"path": ..., "bpm": ..., "seed": 3, ...}
```

## Per-scene music (one file, moods change on your cuts)

```bash
python -m bgmstudio.cli sequence lofi:30,cinematic:45,dark:20 --seed 3
python -m bgmstudio.cli mix narration.mp3 x --scenes lofi:30,cinematic:45,dark:20   # scene music + narration, ducked
```
`POST /sequence` takes `{"scenes": [{"mood": "lofi", "duration": 30}, ...], "xfade": 2.0, "seed": 3}`; `POST /mix` takes the same
list in a `scenes` form field (JSON); MCP has `generate_scene_sequence` and a `scenes` argument on `mix_with_narration`.
Each scene's downbeat lands exactly on its cut, all scenes share one key (auto-picked, or pass `key`), and the previous scene
crossfades out over `xfade` seconds *after* the cut. Total length = sum of scene durations, to the sample. Scenes need to be
4 s or longer. In `/mix`, scene durations must sum to the narration length (within 1.5 s); lead-in and tail are added for you.

### Tempo matching and transition effects

Both apply to `/sequence`, to `scenes` in `/mix`, to the MCP tools and to the CLI/client.

* **`tempo_match`** (default on, `max_bpm_jump` default 6): picks each scene's tempo so neighbouring scenes sit within a few BPM,
  while keeping every scene as close as possible to its mood's natural range. A 2:1 ratio counts as matched (62 and 124 BPM share a
  pulse). Every scene except the last snaps to whole *beats* rather than whole bars (it is crossfading out anyway), which keeps the
  tempo grid fine even for short scenes. Any cut that still can't be matched is reported as `tempo_warning` in the response.
  Cost: scenes may sit a little outside their mood's usual tempo range. Set `tempo_match=false` for each mood's natural tempo, or
  give a scene its own `"bpm"` to pin it.
* **`transitions`** (default `none`), synthesised in code, tuned to the key, independent of the SoundFont:
  `riser` (noise sweep plus a tone gliding up, ending on the cut) | `impact` (key-tuned sub boom plus reverberant burst, on the
  downbeat) | `riser_impact` | `downlifter` (a riser reversed, starting on the cut) | `swell` (smooth gain bump into the cut) |
  `auto` (by energy change between moods: big rise = `riser_impact`, small rise = `riser`, same = `swell`, drop = `downlifter`).
  Put `"transition": "impact"` on a scene to override the cut *into* that scene. `fx_level_db` (default -3) sets loudness relative to
  the music. In `/mix` the effects are part of the music bed, so they duck under speech like everything else.

```bash
python -m bgmstudio.cli sequence calm:18,cinematic:20,lofi:18,tech:18 --seed 11 --transitions auto
```

## Cue sheets, stems and provenance

Every result (REST `?as_json=true`, MCP, CLI, `bgm_client.py`) carries three extra things, and the same record is
saved next to the audio as `<file>.json` (`meta_url` in REST; binary responses point to it in `X-BGM-Meta-URL`).

**Cue sheet** (`cues`): where everything falls in the file, in seconds:
`scenes` (mood, start/end, bpm, beat length, key), `sections` (intro/verse/build/peak/break/outro, with intensity
when used), `downbeats` (every bar line), `transitions` (time and type at each cut) and, for mixes, `narration`
(start/end). Use it to land video cuts, chapter cards and captions on the beat. MCP results leave out the per-bar
list to keep agent context small; it's in the JSON file.

**Stems** (`stems: true`): separate files beside the main one that add back up to it exactly:

| Call | Stems |
|---|---|
| `/bgm` | pad, bass, keys, melody, sparkle, drums |
| `/sequence` | the instrument groups plus `fx` (transitions) |
| `/mix` | voice, music, fx (aligned, ducked and levelled as in the mix) |

FluidSynth reuses voice slots and carries a little state into the next note's attack, so a full render and the sum
of separately rendered instruments differ slightly. A stems render therefore builds its mix from the stems. It's its
own cached take and can differ from a plain render of the same seed in the first milliseconds of some notes.
Stems are limited to an hour per file (memory). Stems from lossy formats (mp3/m4a/ogg) won't null exactly; use wav or
flac when you need that.

**Provenance** (`provenance`): engine version, seed, every input, the SoundFont (file, size, SHA-256, licence),
the FluidSynth version, and the SHA-256 of every file written, for answering a Content ID claim or checking a file
later. Licences of GeneralUser GS, FluidR3, MuseScore_General and TimGM6mb are built in; for any other font put a
`<font>.license.txt` next to the `.sf2` (or set `BGM_SOUNDFONT_LICENSE`), otherwise the record says "unknown" and how
to fix it. TimGM6mb is GPL-2.0, and whether that reaches rendered audio is unsettled: publish with GeneralUser GS or
FluidR3.

## Using it from your studio app

Copy **`bgm_client.py`** into your studio project. It is one file and needs only `httpx`, so it works from any venv.

```python
from bgm_client import BGMClient

with BGMClient(project_dir=r"G:\Projects\_Multimedia\bgm_studio") as bgm:   # starts the service if it isn't running
    info = bgm.score("narration.mp3", "scored.wav", scenes="calm:20,cinematic:25,dark:20")
    bgm.mux("silent_video.mp4", "scored.wav", "final.mp4", trim_audio_start=info["lead_in"])
```
* Leaving the `with` block stops the service only if the client started it. To keep one service running all day instead, use
  `run_server.bat` and `BGMClient()` (no `project_dir`). Set `BGM_URL` / `BGM_API_KEY` / `BGM_PROJECT_DIR` to configure from outside.
* Methods: `music`, `stream`, `sequence`, `score`, `mux`, `moods`, `health`. Errors raise `BGMError` with a readable message
  (service down, wrong key, unknown mood, mismatched scene lengths, ffmpeg problems).
* `score()` returns audio of `lead_in + narration + tail_out` seconds, with the narration starting at `lead_in`. If your visuals
  start together with the narration, either pass `lead_in=0`, or `mux(..., trim_audio_start=lead_in)`.
* Command line, no code: `python bgm_client.py score narration.mp3 -o scored.wav --scenes calm:20,dark:30`.

Launchers (double-click): `run_server.bat` (API on 127.0.0.1:8765, docs at `/docs`), `run_mcp.bat` (MCP over HTTP),
`calibrate.bat` (pre-warm streaming loudness), `test_client.bat` (tests the client end to end).

## Recommended pipeline

1. Make narration (your voice appliance) and visuals.
2. `POST /mix` with the narration, or `/bgm` plus your own mixer. You get one audio file whose length is
   `lead_in + narration + tail_out`.
3. Mux: `ffmpeg -i video_silent.mp4 -i scored_audio.wav -c:v copy -c:a aac -b:a 256k -shortest final.mp4`
4. Per-scene moods: use `/sequence` (or `scenes` in `/mix`), described above.

## Tuning

* `mix` levels: narration -16 LUFS, music bed -26 LUFS before ducking, -9 dB extra while speaking. Adjust
  `music_lufs` / `duck_db` per request.
* Streaming has no look-ahead, so it applies a fixed per-mood gain, auto-calibrated per SoundFont (`calibrate.py`).
  File outputs are measured and normalised exactly.
* Loop length: longer `LOOP_TAIL_SECONDS` in `render.py` if you use very long reverbs.

## Limits and honesty

* It's rule-based composition with General MIDI instruments: pleasant, unobtrusive beds, not hit songs.
  Quality scales with the SoundFont and with how much you tweak presets.
* Streaming can't do seamless loops (the tail fold needs the finished render); use `/bgm` with `loop=true`.
  Rendering runs ~50-75x realtime on one core, so even a 1-hour file takes about a minute.
* Duration range is 4 s to 2 hours (`BGM_MAX_RENDER_SECONDS`, default 7200, can lower it). Very short clips (a few seconds) may speed up the tempo noticeably to fit whole bars.


## v0.10.1 hardening / operational limits

**This is a targeted local-first hardening release, not a certification for public Internet hosting.**
The default limits are deliberately conservative for single-user desktop systems:

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `BGM_MAX_RENDER_SECONDS` | `7200` | Maximum total generated output, including narration lead/tail (the documented 2-hour limit; set lower on small machines) |
| `BGM_MAX_SCENES` | `100` | Maximum accepted scenes per sequence/mix |
| `BGM_MAX_UPLOAD_BYTES` | `104857600` | Maximum uploaded/input narration bytes (100 MiB) |
| `BGM_FFMPEG_TIMEOUT` | `180` | FFmpeg/FFprobe timeout in seconds |
| `BGM_LOCK_TIMEOUT` | `600` | Windows process lock acquisition deadline in seconds |
| `BGM_MCP_OUTPUT_DIR` | `BGM_OUT_DIR` or `bgm_out` | Root of allowed MCP output directory tree |
| `BGM_MCP_INPUT_DIR` | unset (narration denied) | Root of allowed MCP narration input files |

Explicitly configure `BGM_MCP_INPUT_DIR` before exposing narration mixing through MCP.
Symlinks are resolved for MCP directory checks; paths outside the configured roots are refused.
Outputs use a new request fingerprint and will not reuse filenames from older releases.
File hashes in the metadata are checked before reusing cached results. Each file is hashed once per process and
re-hashed only if its size or modification time changes. Cache hits are answered without waiting for the render
lock, so they never queue behind a long render. Cache names follow `ENGINE_REVISION` in `service.py` (bump it when
the audio for a given request changes), not the package version.

**Deployment boundary:** REST and MCP should be kept on `127.0.0.1` by default. Do not expose
this service to untrusted users without a separate access-control layer and rate/size limits.
The REST `/files` endpoint still uses a shared output namespace, not per-user ownership.
Multipart bodies may be spooled by the framework before the endpoint copy limit is applied;
for Internet exposure, an ingress/proxy body-size cap is mandatory. Untrusted media still
needs process-level isolation for comprehensive decoder security.

**Known limits:** streaming audio is not globally admission-controlled across separate API
workers; the cross-process lock protects file renders within a shared output directory only.
Use one API worker for trusted local use. A production-grade job queue, CPU/memory quotas,
external task cancellation, dependency lockfile, complete Windows audio integration tests
and authenticated per-client artifact ownership remain future work.

For a clean Windows environment, run `setup.bat`, install the Native FluidSynth DLLs,
and check that `python -c "import fluidsynth; print(fluidsynth.Synth)"` succeeds in the project
virtual environment. The `pyfluidsynth` Python package is distinct from the native library.
