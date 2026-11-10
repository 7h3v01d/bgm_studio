# Development

## Setup

```bash
python -m venv .venv          # Windows: setup.bat
pip install -r requirements.txt pytest
python -m pytest -q           # fast suite; the console tests run offscreen
python selftest.py            # end-to-end audio (needs FluidSynth, FFmpeg and a SoundFont)
```

## Architecture

```
bgmstudio/
  presets.py      moods (instruments, tempo, modes, progressions, patterns, mix), aliases, energy
  compose.py      Plan: seeded procedural composition -> notes, sections, tempo, intensity
  render.py       Plan -> audio with FluidSynth; loop tail folding; intensity envelope; stems; streaming
  fx.py           synthesised transitions (riser, impact, downlifter, swell)
  audio.py        loudness (EBU R128), normalisation, ducking, narration mixing, atomic writes, decoding
  cues.py         cue sheets
  provenance.py   provenance records, SoundFont licences, hashing
  service.py      the engine API used by every interface: validation, limits, caching, locking, sequences, mixes
  api.py          REST (FastAPI)
  mcp_server.py   MCP tools
  cli.py          command line
  calibrate.py    streaming loudness calibration per SoundFont
bgmgui/           desktop console (PyQt6); uses bgm_client.py, never imports bgmstudio
bgm_client.py     single-file REST client (httpx only)
```

Every interface goes through `service.py`, so validation, limits and caching behave identically everywhere.

The render pipeline for a track is: `compose()` builds a `Plan` (notes, sections, tempo) from the mood, length, seed
and intensity; `render_audio()` plays it through FluidSynth, applies the intensity envelope and, for loops, folds the
tail onto the start; `service` normalises loudness, writes the file atomically, and records cues and provenance.
Sequences render each scene, level and crossfade them on a shared timeline, then add transitions. Mixes fit music to
the narration, duck it and normalise the sum.

## Rules that keep results stable

**Determinism.** All randomness comes from `random.Random` instances seeded from the request seed and a fixed label
(for example `f"{seed}:{name}:dissonance"`). New random choices must use their own labelled generator, never an
existing one, so adding a feature does not shift the notes of existing requests. `tests/golden_notes_0_8.json` holds
note fingerprints for the original eight moods and fails if any of them change.

**Opt-in features.** New preset options and request parameters default to "off" and must leave existing output
unchanged when unused.

**Engine revision.** If a change alters the audio produced for an unchanged request (composer, renderer, mixing,
effects), increment `ENGINE_REVISION` in `service.py` and update the golden fingerprints deliberately. Cache keys
include the revision, so stale results are not served. Changes that do not affect audio leave it alone, so caches
survive the release.

**Mirrored tables.** The console never imports the engine. `bgmgui/scenes.py` mirrors the transition names and mood
energies; `tests/test_sequencer.py` fails if they drift from the engine.

## Adding a mood

Add an entry to `PRESETS` in `bgmstudio/presets.py` with a description, tempo range, weighted modes, key choices,
programs (0-based General MIDI numbers), drum style, patterns, melody settings, reverb and mix. Optional keys
(`drone`, `dissonance`, `max_level`, `kind_gain`, `spark_scale`, `melody`) are described at the top of the file. Add
its energy to `ENERGY` (and to the mirror in `bgmgui/scenes.py`), aliases to `ALIASES`, and a `cal` estimate (measured
loudness for the streaming fallback; `python -m bgmstudio.cli calibrate` measures the real value). The self-test checks
exact length for every mood automatically.

## Tests

| File | Covers |
|---|---|
| `test_regressions.py`, `test_review_0102.py`, `test_hardening_0101.py`, `test_hardening_0103.py` | Input limits, error mapping, caching, concurrency, budgets, hashing, paths. |
| `test_story_moods.py` | Storytelling moods, intensity, golden note fingerprints. |
| `test_deliverables.py` | Cue sheets, stems (they must add up to the mix), provenance. |
| `test_output_write_resilience.py`, `test_release_loudness_pipe.py` | Write retries, loudness measurement. |
| `test_gui.py`, `test_sequencer.py`, `test_gui_qt.py` | Console validation, scene logic and the console itself (offscreen, fake client). |
| `test_release_manifest.py` | Release manifest generation and coverage. |
| `selftest.py`, `selftest_client.py` | End-to-end audio and client checks against real FluidSynth and FFmpeg. |

**Regression tests must fail without the fix.** For every bug fix, write the test first, confirm it fails on the
unfixed code, then fix. Reverting the fix should make the test fail again.

## Code conventions

- Source files carry SPDX headers: `SPDX-License-Identifier: Apache-2.0` and the copyright line.
- The console uses QObject workers on QThreads, kept referenced in `_worker_refs` until finished, with `@pyqtSlot`
  slots. Blocking calls never run on the GUI thread.
- The console's look follows the shared design system in `bgmgui/theme.py`: dark palette, JetBrains Mono, flat
  zero-radius controls.
- User-facing errors say what is wrong and what to do; engine errors are `ValueError` (bad input) or carry an
  actionable message (missing SoundFont, FluidSynth or FFmpeg).

## Contributing

1. Open an issue describing the change.
2. Keep changes focused, with tests, and with existing output unchanged unless the change is meant to alter it (then
   bump `ENGINE_REVISION`).
3. Update `CHANGELOG.md` and the documentation.
4. Run `python -m pytest -q`, and `selftest.py` where audio is affected.

Contributions are accepted under the Apache License 2.0.
