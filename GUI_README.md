# BGM Studio desktop console

A PyQt6 front end for the local REST service, in the shared dark industrial style. It drives the service through
`bgm_client` and never imports the engine.

## Launch

1. `setup.bat` once (it installs PyQt6 with the other requirements). Your SoundFont, FluidSynth DLLs and FFmpeg setup
   stay as they are.
2. Double-click `run_gui.bat`, or run `.venv\Scripts\python.exe bgm_gui.py`.
3. The console connects to `127.0.0.1:8765` and starts the service if it isn't running. On exit it stops the service
   **only if it started it**. `BGM_API_KEY` is passed through if set.

## Panels

| Panel | What it does |
|---|---|
| 01 // PARAMETERS | **TRACK** tab: mood (list and descriptions come from the service), duration (4 s to 2 h), intensity, seamless loop. **SEQUENCE** tab: see below. Shared by both: seed (blank = new piece), format, stems, export folder and file name |
| 02 // STATUS | Connection and render state, elapsed time, reconnect |
| 03 // LATEST OUTPUT | Seed, BPM, key, length, sections, stems; the cue strip (sections coloured by energy, a tick per bar, amber transition marks, teal playhead); play/pause with seek; SoundFont licence (amber if unknown or GPL); copy seed, reuse settings, open folder |
| 04 // LOG | Timestamped record of what happened, warnings in amber, errors in red |

## SEQUENCE tab

One file whose mood changes on your cuts: the same engine as `/sequence`, or `/mix` when a narration is loaded.

- **Scene table:** one row per scene with mood, length, intensity (`—` = the mood as designed), the transition
  *into* the scene (`default` = the sequence's default; the first scene has none), BPM (`auto` = chosen for the mood
  and its neighbours) and its start time. **+ SCENE**, **DUPLICATE**, **REMOVE** and **▲ ▼** edit the list.
- **Scene bar:** the plan at a glance. Blocks are proportional to length and shaded by mood energy, amber marks show
  the transition at each cut (R riser, I impact, RI both, D downlifter, S swell, A auto), and a dashed line shows
  where the narration ends. Click a block to select its row.
- **Settings:** default transition (`auto` picks by the change in energy), crossfade, tempo match and the largest
  tempo jump it allows.
- **Narration (optional):** choose a voice-over and the button becomes **SCORE NARRATION**. Scenes must add up to the
  narration within 1.5 s; **FIT** scales them proportionally to match. Lead-in and tail-out add music before the
  first word and after the last; duck sets how far the music dips under speech.
- **LOAD / SAVE:** scene files are JSON in the same shape as the API, so InkHeart or Reelwright can write one and the
  console opens it:

```json
{"format": "bgmstudio-scenes", "version": 1,
 "scenes": [{"mood": "sleep", "duration": 24},
            {"mood": "horror", "duration": 28, "intensity": 0.95, "transition": "riser_impact"}],
 "settings": {"transitions": "auto", "xfade": 2.0, "tempo_match": true, "max_bpm_jump": 6.0,
              "lead_in": 1.5, "tail_out": 3.0, "duck_db": 9.0}}
```

  A bare list of scenes, or the body you would POST to `/sequence`, opens too. Unknown moods are refused by name.
  The editor keeps one intensity per scene, so a curve in a file is opened as its average.

After a sequence or mix, the cue strip numbers the scenes, marks every cut, and draws the narration's span along the
bottom. BPM shows the range across scenes, and tempo warnings from the engine appear in the log.

Next to every render the client saves `<name>.json` with the cue sheet and provenance record, plus stem files if
you asked for them.

## Notes

- Streaming and per-scene intensity curves are available through the REST API, CLI and MCP, not the console.
- The service gives no percentage while rendering, so the console shows a busy bar and elapsed time. Closing during
  a render asks first; the service may finish that render, but the file won't be downloaded.
- Playback uses QtMultimedia (part of the PyQt6 wheels) and plays every export format. The player is created on the
  first PLAY, so a broken audio device can't stop the console starting. `BGM_GUI_NO_AUDIO=1` turns playback off.
- An existing file of the same name is only replaced after you confirm.
- The console is not a security boundary: the service enforces its own limits and authentication.

## Tests

`.venv\Scripts\python.exe -m pytest -q tests\test_gui.py tests\test_gui_qt.py`

The Qt tests run offscreen with a fake client, so they need no server, display or audio device.

### Manual check on Windows

- [ ] Console opens in the dark industrial theme with JetBrains Mono, and shows ONLINE.
- [ ] Stop the service, press RECONNECT: it starts the service again.
- [ ] Generate a short WAV: the output panel fills in, the cue strip shows sections, PLAY plays and the playhead moves.
- [ ] Generate MP3 and FLAC; both play in the console.
- [ ] Same seed and settings twice: identical result (the second comes back instantly from the cache).
- [ ] Stems on: stem files appear next to the track.
- [ ] Seed `banana`, or file name `CON`: flagged in red, nothing renders.
- [ ] Same file name again: asks before replacing.
- [ ] SEQUENCE: add, duplicate, reorder and remove scenes; the start column and scene bar follow.
- [ ] SEQUENCE: generate with transitions `auto`; the cue strip shows numbered scenes and amber cuts.
- [ ] SEQUENCE: load a narration, see the mismatch, press FIT, then SCORE NARRATION; the mix plays with the music
      dipping under the voice.
- [ ] SEQUENCE: SAVE, change things, LOAD: the scenes and settings come back.
- [ ] Close while the service was already running before the console: the service keeps running.
