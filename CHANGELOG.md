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
