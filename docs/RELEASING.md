# Releasing

## Versions

- **Package version** (`bgmstudio/__init__.py`, `__version__`) follows semantic versioning. It is reported by the API,
  recorded in every provenance record and used as the release number in the manifest.
- **Engine revision** (`ENGINE_REVISION` in `bgmstudio/service.py`) changes only when the audio produced for the same
  request changes. It is part of every cache key, so bumping it re-renders cached results and leaving it alone keeps
  them. See `docs/DEVELOPMENT.md`.

## Integrity manifest

`RELEASE_SHA256.json` lists the SHA-256 of every distributed file: source, tests, documentation and launchers. Local
environments, native binaries, SoundFonts, generated audio and caches are excluded (see `EXCLUDED_DIRS` in
`release_verify.py`).

```bash
python release_verify.py                         # check the files against the manifest
python release_verify.py --write-manifest 0.11.1 # regenerate it for a release
```

The manifest is an integrity check, not a signature: anyone able to change the files can also change the manifest.
For authenticated releases, sign the release archive or tag separately. `tests/test_release_manifest.py` fails if a
file is added or removed without regenerating the manifest.

## Release procedure

1. Update `__version__`, and `ENGINE_REVISION` if the audio changes.
2. Update `CHANGELOG.md` and any affected documentation.
3. Run the test suite: `python -m pytest -q`.
4. Run the end-to-end tests on Windows with the production SoundFont, FluidSynth and FFmpeg: `selftest.py` and
   `selftest_client.py` (or `test.bat` and `test_client.bat`).
5. Regenerate the manifest: `python release_verify.py --write-manifest <version>`.
6. Run `verify_release.bat` on a clean extraction of the release archive. It checks the manifest, records the
   environment in `release_evidence/environment.json`, and runs the tests and the audio self-test. It exits non-zero
   on any failure.
7. Open the desktop console and work through the manual checks below.
8. Archive the release ZIP with its SHA-256, the console output of step 6 and `release_evidence/environment.json`.

## Expected test results

- All tests pass. On Windows without symbolic-link permission, `test_soundfont_licence_follows_symlinks_and_overrides`
  is skipped; every other skip needs investigating.
- `selftest.py` ends with `ALL PASSED`.

## Manual console checks

- The console opens in the dark theme with JetBrains Mono and shows ONLINE.
- With the service stopped, RECONNECT starts it again.
- TRACK: a short WAV renders, the output panel fills in, the cue strip shows sections, and PLAY plays with a moving
  playhead. MP3 and FLAC renders also play.
- The same seed and settings rendered twice give an identical result; the second comes from the cache immediately.
- With EXPORT STEMS, stem files appear beside the output.
- An invalid seed (`banana`) or file name (`CON`) is flagged and nothing renders. An existing file name prompts before
  replacing.
- SEQUENCE: adding, duplicating, reordering and removing scenes updates the start column and scene bar. A render with
  `auto` transitions shows numbered scenes and amber cuts on the cue strip.
- SEQUENCE: loading a narration shows the length mismatch; FIT corrects it; SCORE NARRATION produces a mix in which the
  music dips under the voice.
- SAVE, change the scenes, LOAD: the scenes and settings return.
- Closing the console leaves running a service that was started outside it.

## Release contents

The source archive does not include SoundFonts, FluidSynth or FFmpeg. Users install them separately under their own
licences. `requirements.txt` is not pinned; the environment captured in step 6 records the versions tested. For fully
reproducible installs, derive a locked requirements file from that environment.

## Troubleshooting release runs

An `audio output could not be written` failure during the tests usually points to the environment rather than the
code. Check free space and permissions on the output directory and `%TEMP%`, and whether antivirus, backup or
synchronisation software was accessing the output folder. The service log records the target path, estimated size,
free space and underlying error. Keep the first failure log, and rerun from a clean process.
