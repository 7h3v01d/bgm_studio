# Changelog

All notable changes to BGM Studio. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [semantic versioning](https://semver.org/). "Engine revision" refers to `ENGINE_REVISION`, which
changes only when the audio produced for an unchanged request changes.

## [0.11.1] - 2026-11-11

Documentation release. Engine revision unchanged.

### Added
- User Manual (`docs/USER_MANUAL.md`) covering installation, concepts, the desktop console, REST API, MCP server,
  command line, Python, configuration, outputs and troubleshooting.
- `docs/SECURITY.md`, `docs/DEVELOPMENT.md` and `docs/RELEASING.md`.
- `LICENSE` (Apache License 2.0) and `NOTICE`.
- `release_verify.py --write-manifest <version>` regenerates the integrity manifest; `tests/test_release_manifest.py`
  checks that the manifest covers exactly the distributed files.

### Changed
- README rewritten as a project overview.
- The desktop console guide, release checklist and hardening notes are consolidated into the documents above.

## [0.11.0] - 2026-11-11

### Added
- Desktop console **SEQUENCE** tab: a scene table (mood, length, intensity, transition into the scene, BPM, start
  time), scene editing (add, duplicate, remove, reorder), a scaled scene bar showing energy, transitions and the
  narration's end, and sequence settings (default transition, crossfade, tempo matching, maximum BPM jump).
- Narration scoring from the console: scene totals are checked against the narration, **FIT** scales scenes to match,
  and lead-in, tail-out and duck depth are adjustable.
- Scene files (LOAD/SAVE) in the same JSON shape as the API, so other programs can supply scene lists.
- The output panel and cue strip show sequences and mixes (scene numbers, cuts, narration span, BPM range); tempo
  warnings appear in the log.

### Changed
- Seed, format, stems, export folder and file name are shared by both console tabs; the log moved to the right-hand
  column.

## [0.10.4] - 2026-11-11

### Changed
- The desktop console was rebuilt in PyQt6 with the project's dark design system, replacing the Tkinter console of
  0.10.3. Moods and their descriptions are loaded from the service. A cue strip shows sections, bars and
  transitions with a playback cursor. Every export format plays in the console with seeking (QtMultimedia). The
  SoundFont licence is shown and highlighted when unknown or GPL. The console adds copy/reuse seed, an operator log and
  an elapsed-time display.
- Console work runs on background threads. The console stops the service on exit only if it started it, and asks
  before closing during a render. The audio player is created on first use, so a faulty audio device cannot prevent
  start-up (`BGM_GUI_NO_AUDIO=1` disables playback).
- `requirements.txt` adds PyQt6.

## [0.10.3] - 2026-11-10

### Added
- Render memory admission: an estimate of working memory per render is checked against
  `BGM_MAX_RENDER_MEMORY_MIB` (default 16384) before rendering.
- `BGM_STRICT_CACHE_HASHES=1` re-hashes cached files on every reuse.
- First desktop console (Tkinter) with single-track generation, and release verification tooling
  (`release_verify.py`, `verify_release.bat`, `RELEASE_SHA256.json`).

### Changed
- Narration duration is probed before decoding and checked together with lead-in, tail-out, stems and memory.
- Unix render locks honour `BGM_LOCK_TIMEOUT`, matching Windows.
- Loudness measurement streams audio to FFmpeg instead of writing a temporary WAV file.
- WAV and FLAC writes retry once after a transient write error; persistent failures keep any previous output, remove
  temporary files and log the target, size and free space.

### Fixed
- `POST /mix` returns 422 instead of 500 when ffprobe cannot read the narration.

## [0.10.2] - 2026-11-10

### Changed
- `BGM_MAX_RENDER_SECONDS` defaults to 7200 s, the documented two-hour limit (0.10.1 used 600 s).
- Cache keys use `ENGINE_REVISION` instead of the package version, so releases that do not change the audio keep
  their caches.

### Fixed
- Cache hits no longer wait behind unrelated renders (tracks, sequences and mixes check the cache before taking the
  render lock).
- Cached files and the SoundFont are hashed once per process per path, size and modification time instead of on every
  request.
- A malformed `Content-Length` on `/mix` returns 400 instead of 500.
- A render-lock timeout returns 503 with `Retry-After` instead of 500.

## [0.10.1] - 2026-11-10

### Added
- Limits on output length, scene count and narration upload size (`BGM_MAX_RENDER_SECONDS`, `BGM_MAX_SCENES`,
  `BGM_MAX_UPLOAD_BYTES`), checked before rendering.
- Timeouts on every FFmpeg and ffprobe call (`BGM_FFMPEG_TIMEOUT`); a timeout returns 504.
- MCP path confinement: outputs inside `BGM_MCP_OUTPUT_DIR`; narration only from `BGM_MCP_INPUT_DIR`.
- A cross-process render lock in the output directory.

### Changed
- Output names derive from every audible parameter, the narration's content and the SoundFont's SHA-256, so
  different requests never share a file. Cached results are reused only if their recorded size and SHA-256 match.
- The REST API key is compared in constant time; `/health` no longer reveals the SoundFont path.
- `setup.bat` no longer upgrades pip.

## [0.10.0] - 2026-11-10

### Added
- Cue sheets in every result: scenes, sections (with intensity), every downbeat, transitions, and the narration's
  span for mixes.
- Stems (`stems: true`): instrument parts for tracks; parts plus effects for sequences; voice, music and effects for
  mixes. Stems add up exactly to the main file; a stems render builds its mix from the stems.
- Provenance records: version, seed, inputs, SoundFont SHA-256 and licence, FluidSynth version and the SHA-256 of
  every output.
- A JSON record beside every output; `meta_url` in REST results and the `X-BGM-Meta-URL` header; `?as_json=true` on
  `/mix`.
- `bgm_client.py` returns cues, provenance and stems, downloads stems and saves the record beside the output.

### Changed
- Mix output names include the narration's hash, so different narrations never overwrite each other.

## [0.9.0] - 2026-11-10

### Added
- Storytelling moods `horror`, `sleep`, `folklore` and `suspense`, with aliases.
- Intensity, a value from 0 to 1 or a tension curve of up to 64 points, on every kind of render and per scene. It
  shapes layering, dynamics, tempo and section levels, and feeds automatic transitions.
- Preset options `drone`, `dissonance`, `max_level`, `kind_gain`, `spark_scale` and `melody`; the harmonic minor mode;
  `heartbeat` and `frame` drum styles.

### Changed
- The aliases `sleep`, `suspense` and `tension` now refer to the new moods of those names (previously `ambient` and
  `dark`).

## [0.8.0] - 2026-11-10

### Added
- Engine-wide value limits (`service.LIMITS`), enforced identically by every interface and published in the OpenAPI
  schema.
- `setup.bat` and `test.bat`; a single version source (`bgmstudio.__version__`).

### Fixed
- Undecodable narration returns 422 with the decoder's reason instead of 500.
- `/mix` and `/bgm/stream` reject out-of-range values with errors naming the field.
- Identical concurrent requests render once; outputs are written atomically.
- Mood aliases share their mood's cache entry; moods are validated before use in file names.
- Clearer errors for a missing narration file and malformed CLI scene lists.

## [0.7.0]

### Added
- Sequences with per-scene moods, tempo matching and synthesised transitions.
- The single-file Python client `bgm_client.py`.
