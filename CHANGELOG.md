## 0.11.0 (2026-11-11): scene sequencer in the console

- New **SEQUENCE** tab: a scene table (mood, length, intensity, transition into the scene, BPM, start), toolbar
  (add, duplicate, remove, reorder), a scene bar showing the plan (energy shading, transition marks, narration end;
  click to select), and the sequence settings (default transition, crossfade, tempo match, max BPM jump).
- **Narration scoring** from the same tab: load a voice-over, check the scene total against it (within 1.5 s), **FIT**
  scales the scenes to match, and **SCORE NARRATION** renders the ducked mix (lead-in, tail-out, duck depth).
- **Scene files** (LOAD/SAVE) in the API's own shape, so InkHeart/Reelwright can hand scenes to the console.
- Seed, format, stems, export folder and file name are shared by both tabs; the log moved into the right column so
  the window fits a 1080p screen. The output panel and cue strip handle sequences and mixes (scene numbers, cuts,
  narration span, BPM range, tempo warnings in the log).
- `bgmgui/scenes.py` holds the scene logic with no Qt (validation, start times, fit, scene files, result summary);
  `tests/test_sequencer.py` (25 tests) checks it, including that its transition and energy tables match the engine.
  `tests/test_gui_qt.py` adds 9 sequencer tests that drive the tab like an operator.
- Engine, REST API and `ENGINE_REVISION` unchanged.

## 0.10.4 (2026-11-11): PyQt6 desktop console

- Rebuilt the GUI in PyQt6 on the shared dark industrial design system (Obsidian/Panel/Border, Teal accent,
  Phosphor/Amber/Red states, JetBrains Mono, flat zero-radius controls), replacing the Tkinter phase-01 console.
  Code is in the `bgmgui` package; `bgm_gui.py` is the launcher and still exports the validation helpers.
- Same scope (single-track generation) plus: moods and descriptions loaded from the service; a cue strip showing
  sections, bars and transitions with a playback cursor; in-app playback with seek for every format (QtMultimedia,
  replacing winsound/ffplay); SoundFont licence shown and flagged amber when it is unknown or GPL; copy/reuse seed;
  timestamped operator log; elapsed render timer.
- Background work uses QObject workers on QThreads (kept alive in `_worker_refs`). The console stops the service on
  exit only if it started it; closing mid-render asks first.
- The media player is created on first PLAY, so a broken audio stack can't stop the console starting
  (`BGM_GUI_NO_AUDIO=1` turns playback off).
- `tests/test_gui_qt.py`: 11 offscreen tests with a fake client (no server, display or audio device needed).
- `requirements.txt` adds PyQt6. Engine, REST API and `ENGINE_REVISION` unchanged.

## GUI Phase 01 (2026-11-11) — optional desktop client

- Added industrial-themed `bgm_gui.py` and `run_gui.bat` for track generation, loop/intensity controls, export and playback.
- Added `tests/test_gui.py` with 18 headless input-validation tests and `GUI_README.md` with Windows manual acceptance checks.
- No changes to synthesis engine, REST endpoints, `ENGINE_REVISION`, or existing tests.

## v0.10.3 Windows test-contract correction

- Updated `test_failed_write_leaves_no_partial_file` to expect the documented actionable `RuntimeError` after a bounded two-attempt write failure, to assert that its chained cause is the original `OSError`, and to verify both retry attempts and no partial artifacts.
- No application, audio-rendering, cache, or API changes.
- This corrects a regression-test expectation mismatch discovered on Windows (122 passed, 1 failed, 2 skipped before correction).

## 0.10.3 output-write diagnostic hotfix (2026-11-10)

- Addressed a second intermittent Windows `soundfile.LibsndfileError: System error` failure, now seen when writing a final `/sequence` output rather than when measuring LUFS. The root OS cause is not established from the reported traceback.
- WAV/FLAC writes now retry once after a short delay if libsndfile reports a write error; each attempt uses a fresh temporary sibling path, preserving the last good output and cleaning up partial files.
- Persistent failures log the destination path, estimated audio payload size, free disk capacity, and underlying error locally; the REST error remains a non-sensitive HTTP 500 with troubleshooting guidance.
- Added tests for a transient failure, persistent failure with atomic preservation, and byte-identical successful PCM24 WAV output.
- No change to music composition, PCM data, normal successful encoding, or `ENGINE_REVISION`. Release manifest regenerated.
- A passing Windows end-to-end verification is still required. The retry is not a substitute for fixing insufficient disk space, native-library errors, or permissions problems.

## 0.10.3 release-verification LUFS hotfix (2026-11-10)

- Replaced the temporary float WAV in `measure_lufs()` with raw float32 PCM delivered to FFmpeg over stdin. This avoids large temporary-file writes and reduces sensitivity to Windows TEMP volume errors during repeated release tests. FFmpeg `ebur128` measurement and gain/normalisation algorithms are unchanged.
- FFmpeg loudness failures now raise a descriptive error rather than being interpreted as silence.
- Added four regression tests for diskless loudness, process failures, empty audio and channel validation.
- Rebuilt `RELEASE_SHA256.json` to cover the modified source, test and documentation. Previous release manifests intentionally do not match this updated baseline.
- Full Windows release verification is pending; the prior 116-pass Windows run validates the unpatched build, not this hotfix.

## 0.10.3 Windows regression hotfix (2026-11-10)

- Fixed `POST /mix` returning HTTP 500 for undecodable narration after the new ffprobe preflight. The service now translates failed ffprobe execution and malformed duration metadata into a clear invalid-media `ValueError`, which the API maps to HTTP 422.
- Added focused regression coverage for the ffprobe process-failure and malformed-metadata paths. No rendering parameters, resource budgets, cache identity, or audio-generation algorithms changed.

## 0.10.3 (2026-11-10): targeted resource and integrity hardening

- Added configurable estimated float32 stereo PCM working-memory admission budget (`BGM_MAX_RENDER_MEMORY_MIB`, default 16384). The two-hour duration limit remains unchanged. This is an estimate, not a guarantee against out-of-memory conditions.
- Mix narration duration is now probed **before decoding** and checked with lead/tail, stem and estimated memory requirements. The existing `read_audio()` independent duration checks remain; decoded WAV frame count is checked before loading samples into NumPy.
- Unix render locks now honor `BGM_LOCK_TIMEOUT` via non-blocking `flock`, matching Windows behaviour.
- Added `BGM_STRICT_CACHE_HASHES=1` as a full-rehash integrity mode to detect same-size file changes with restored modification timestamps. Default cache-fast mode remains unchanged.
- Concurrency test now asserts all worker threads complete successfully, not merely that the renderer was called once.
- Added focused v0.10.3 regressions; expanded existing synthetic test mocks to cover the new pre-decode probe.
- No changes to composition algorithms, sound presets, audio synthesis, or `ENGINE_REVISION`.

## 0.10.2 (2026-11-10): review fixes for 0.10.1

Each fix has a test in `tests/test_review_0102.py` that fails on 0.10.1.

- **Render budget back to the documented 2 hours.** `BGM_MAX_RENDER_SECONDS` defaults to 7200 again (it was 600, which
  refused 30-minute sleep beds and narration over 10 minutes, while the API advertised 7200). The variable still
  lowers it.
- **Cache hits no longer queue behind renders.** Tracks, sequences and mixes check the cache before taking the render
  lock (and again after, so identical concurrent requests still render once). A cached call during a 400 s render
  took 8.6 s on 0.10.1.
- **No full re-hash on every cache hit.** SoundFont and output hashes are computed once per process per
  (path, size, modification time); a modified file is still caught.
- **Cache names follow `ENGINE_REVISION`**, not the package version, so releases that don't change the sound keep the
  cache. (One-time re-render from 0.10.1 names.)
- A malformed `Content-Length` on `/mix` returns **400** (was an unhandled exception → bare 500).
- A render-lock timeout returns **503** with `Retry-After` (was a bare 500).

## 0.10.1 — Windows self-test compatibility follow-up (2026-11-10)

- The standalone `selftest.py` intentionally renders a 1,200-second FLAC track. It now raises `BGM_MAX_RENDER_SECONDS` to at least 1,200 seconds **for the self-test process only**, before loading the service; normal invocations retain the 600-second default.
- No production render-limit bypass or runtime API changes.

## 0.10.1 — Integrity and resource-safety hardening (2026-11-10)

- Full canonical request fingerprints (including SoundFont SHA-256 and engine version) prevent narration mixes differing only in ducking, loudness, scenes or other options from sharing an output filename. All render paths now use content-based cache keys; old cache names deliberately migrate.
- Narration mixes now use the shared render lock and reuse verified cached outputs; directory-wide OS file locks coordinate across CLI/API processes. Per-process rendering is serial to reduce peak allocations.
- Explicit default output-duration budget (600 s), scene-count budget (100), narration upload byte budget (100 MiB) and decoded duration budget. Configurable through BGM_MAX_RENDER_SECONDS, BGM_MAX_SCENES and BGM_MAX_UPLOAD_BYTES.
- Streaming, sequence and track render calls validate budgets before rendering. Decoding applies a time limit and an upper bound on decoded length.
- Cache reuse requires recorded output size and SHA-256 match (including requested stems/MIDI); SoundFont content changes invalidate render identity.
- All FFmpeg/FFprobe subprocess calls now have timeouts (BGM_FFMPEG_TIMEOUT, default 180 s). Incompatible pyfluidsynth environments produce explicit diagnostic errors.
- MCP tool input and output paths are confined to operator-specified directories. Narration via MCP requires BGM_MCP_INPUT_DIR; outputs default to BGM_MCP_OUTPUT_DIR or BGM_OUT_DIR.
- REST /health no longer returns an absolute SoundFont path; API key comparison is constant-time. Uploads with advertised excessive body sizes are rejected before multipart parsing, and the copy loop enforces a byte limit.
- Added eight no-synthesizer regression tests for security and integrity. Windows audio, remote deployment security and full compatibility testing still required.
- setup.bat no longer upgrades pip automatically.

# Changelog

## 0.10.0 (2026-11-10): cue sheets, stems and provenance

### Added
- **Cue sheets** in every result and in the saved record: scenes, sections (with intensity), every downbeat,
  transitions, and the narration's start/end for mixes. Times are in file time, sample-accurate to the renderer.
- **Stems** (`stems: true` on `/bgm`, `/sequence`, `/mix`, MCP tools, CLI `--stems`, `bgm_client.py`): instrument
  groups for tracks; instrument groups + fx for sequences; voice / music / fx for mixes. They add back up to the main
  file (tested to 16-bit rounding). Capped at an hour per file.
- **Provenance records**: version, seed, inputs, SoundFont SHA-256 and licence (symlinks followed, sidecar
  `<font>.license.txt` or `BGM_SOUNDFONT_LICENSE` override), FluidSynth version, SHA-256 of every output.
- Every render saves `<file>.json` beside the audio; REST returns `meta_url` and binary responses send
  `X-BGM-Meta-URL`. `/mix` gained `?as_json=true`.
- `bgm_client.py`: `music()`, `sequence()` and `score()` return `cues`, `provenance`, `stems` and `meta_path`,
  download stems beside the output and save the record as `<output>.json`.
- `tests/test_deliverables.py`.

### Changed
- `score()` and `music()` in the client now use the JSON endpoints (same return keys as before, plus the new ones).
- Mix output names include a hash of the narration, so two different narrations with the same seed no longer
  overwrite each other's mix.
- Cache entries written before 0.10 (no cues/provenance) are re-rendered once.

### Found while building
- FluidSynth reuses voice slots and carries some state into the next note's attack, so per-instrument renders don't
  sum exactly to a full render. Stems renders therefore build the mix from the stems (and are their own cache entry).

## 0.9.0 (2026-11-10): story moods and intensity

### Added
- **Four storytelling moods:** `horror` (drone, clashing tones, music box, bells), `sleep` (very slow and flat, no
  drums or melody), `folklore` (harp, flute, cello, frame drum) and `suspense` (pizzicato ostinato, heartbeat kick).
  New aliases include creepypasta, bedtime, myth, legend, thriller, alt_history and what_if.
- **Intensity**, a number `0..1` or a tension curve (list of up to 64 points), on `/bgm`, `/bgm/stream`, `/mix`,
  every `/sequence` scene, the MCP tools, the CLI (`--intensity`, `mood:seconds:intensity`) and `bgm_client.py`.
  It moves each section up or down the busyness ladder, scales velocities and sparkle, picks the tempo within the
  mood's range, and applies a per-section level envelope that survives normalisation (loops ramp back to the start
  level, so they stay seamless). Scene intensity sets scene levels and feeds `transitions="auto"`.
- New preset options: `drone`, `dissonance`, `max_level`, `kind_gain`, `spark_scale`, `melody` (all off by
  default); a `harmonic_minor` mode; `heartbeat` and `frame` drum styles.
- `tests/test_story_moods.py`, including a golden check that the original eight moods are note-identical to 0.8.

### Changed
- The `sleep` and `suspense` aliases (previously ambient and dark) and `tension` (previously dark) now point to the
  new moods with those names. Ask for `ambient` or `dark` explicitly to get the old sound.
- Cache file names are unchanged when intensity isn't used.

## 0.8.0 (2026-11-10): hardening release

Fixes from the 0.7 review. Each one has a regression test in `tests/test_regressions.py` that fails on 0.7.

### Fixed
- `POST /mix` with an audio file ffmpeg can't decode now returns **422** with ffmpeg's reason (was a bare 500).
- `POST /mix` now enforces limits on `lead_in`, `tail_out`, `music_lufs`, `duck_db`, `final_lufs`, `xfade`,
  `max_bpm_jump` and `fx_level_db` (previously `duck_db=500` was accepted and `lead_in=-5` gave a numpy error).
  `scenes` that isn't a JSON list returns 422 (was 500).
- `GET /bgm/stream` now enforces limits on `target_lufs`, `fade_out` and `bpm` (`target_lufs=+40` produced hard-clipped audio).
- The same limits are enforced in the engine (`service.LIMITS`), so MCP, CLI and library callers get the same
  clear errors as the REST API, and they are published in the OpenAPI schema (`/docs`).
- Identical concurrent requests render **once**; the others wait and are served from the cache (was one full render
  per request, all writing the same file).
- Audio and metadata files are written atomically: a reader never sees a half-written file, and a failed write leaves nothing behind.
- Mood aliases share the canonical mood's cache entry (`chill` and `lofi` with the same seed were cached twice).
  Moods are validated before they go into any file name.
- `mix_with_narration` with a missing narration path raises a clear `FileNotFoundError`.
- CLI: `--scenes lofi` (no duration) prints a usage hint instead of a traceback; engine errors print `error: ...`.
- Added the `setup.bat` and `test.bat` that the README and `run_server.bat` referred to.
- Single version source: `bgmstudio.__version__` (the API reported `1.0`).

### Changed
- Cache file names now use the canonical mood name, so files cached by 0.7 under an alias are re-rendered once.

## 0.7
- Per-scene sequences, tempo matching, synthesised transitions, single-file client.

### Windows test portability correction
- Skip `test_soundfont_licence_follows_symlinks_and_overrides` only when Windows denies symlink creation with WinError 1314. All other symlink errors still fail the test; no runtime code or licensing behavior changed.
