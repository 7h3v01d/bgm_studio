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

Moods: `calm, lofi, cinematic, uplifting, corporate, dark, ambient, tech` (+ aliases like `chill`, `epic`,
`suspense`, `study`). Add your own by adding a dict in `presets.py`; no code changes needed.

## Install

```bash
pip install -r requirements.txt
# system packages: ffmpeg, plus the FluidSynth library
#   Debian/Ubuntu: sudo apt install ffmpeg libfluidsynth3 fluid-soundfont-gm
#   macOS:         brew install ffmpeg fluidsynth
#   Windows:       install FluidSynth (add its bin/ to PATH) and ffmpeg
python selftest.py          # ~2 minutes, should end with ALL PASSED
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

Then run `test.bat`. Anything missing produces an error naming exactly what to add and where.

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

## Recommended pipeline

1. Make narration (your voice appliance) and visuals.
2. `POST /mix` with the narration, or `/bgm` plus your own mixer. You get one audio file whose length is
   `lead_in + narration + tail_out`.
3. Mux: `ffmpeg -i video_silent.mp4 -i scored_audio.wav -c:v copy -c:a aac -b:a 256k -shortest final.mp4`
4. Per-scene moods: call `/bgm` once per scene with the scene's duration and a different mood and **the same `key`**,
   then crossfade 1-2 s.

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
* Duration range is 4 s to 2 hours. Very short clips (a few seconds) may speed up the tempo noticeably to fit whole bars.
