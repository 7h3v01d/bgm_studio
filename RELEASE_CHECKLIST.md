# BGM Studio v0.10.3 — validated baseline release checklist

This is a **release-engineering wrapper** around the v0.10.3 Windows hotfix. The music engine, API, and tests are unchanged. The previously reported Windows result was **116 passed, 2 skipped**, followed by the audio self-test's `ALL PASSED`. This report is historical user-supplied evidence; it is **not** a new test execution of this archive.

## Scope and limitations

- `RELEASE_SHA256.json` records SHA-256 hashes of the distributed source, tests, and documentation. It is a local *integrity comparison*, **not** an authenticated digital signature. An attacker able to change both the files and manifest can forge this baseline.
- `release_verify.py` uses only the Python standard library to check the baseline before running tests. It does not install/update dependencies.
- `verify_release.bat` runs Python from `.venv`, verifies the file baseline, records dependency and FFmpeg versions, then runs pytest and the full audio self-test. A failure in either test stage causes a non-zero exit status.
- `release_evidence/environment.json` is generated locally, not included in the shipped baseline. Review it before sharing.
- The source ZIP does not include licensed SoundFonts, FluidSynth DLLs or FFmpeg binaries. Supply those independently, complying with their distribution licences.
- Package versions in `requirements.txt` remain unpinned. Capturing installed versions documents the tested Windows environment but does **not** guarantee reproducible future resolution. For truly reproducible Windows installs, derive a locked requirements file from the verified Windows environment and archive installers / wheel hashes, including native dependencies.

## Windows release verification

1. Retain your original validated v0.10.3 hotfix ZIP unmodified as rollback material.
2. Extract this archive to a new directory.
3. Set up the virtual environment and native audio dependencies per `README.md` (`setup.bat` if necessary).
4. From a Command Prompt in the project root, run `verify_release.bat`.
5. Confirm the integrity check passes, pytest reports zero failures, and `selftest.py` ends with `ALL PASSED`.
6. Preserve `release_evidence/environment.json`, your test console log, the original ZIP and SHA-256 of the distributed ZIP.
7. Review both test skips individually before promoting to a release outside your trusted workstation.

## Quick integrity check (no audio dependencies required)

```
python release_verify.py
```

## Suggested follow-up

Once this baseline is frozen, design any new GUI as an **independent client** of the REST API, not as modifications to the trusted synthesis engine. Keep UI convenience functions separate from the existing library and permit only explicit actions to overwrite/export files.

### LUFS temporary-file mitigation (release hotfix)

The release-verification run previously reported two intermittent `soundfile.LibsndfileError: System error` failures in `measure_lufs()` when it wrote a large temporary float WAV. The revised implementation streams PCM to FFmpeg stdin instead. The original Windows error could also indicate temporary-disk exhaustion or filesystem interference; this mitigation removes the known scratch-WAV dependency but does not prove the underlying system condition. Verify with `verify_release.bat` twice and retain any failures with available disk-space and TEMP diagnostics.

## Windows SoundFile `System error` investigation

The release suite writes generated WAV and FLAC files to `bgm_out` by default. If a test returns `{"detail":"System error."}` or the newer actionable `audio output could not be written` message:

1. Look in the **local console/server log** for `Audio output write failed`. It records the write target, estimated PCM bytes, destination free space and the native library exception. Do not expose this log to remote callers.
2. Check available space and write permissions on **both** the output volume (`bgm_out` / `BGM_OUT_DIR`) and `%TEMP%`. Lossy encoding and input decoding still use temporary WAV files.
3. Preserve the first failure log and check whether antivirus, backup or sync software was accessing that output directory.
4. Repeat `verify_release.bat` from a clean process. The retry only addresses a transient native write failure; persistent failures require investigating the environment, not raising the retry count.
5. Do not delete existing generated assets or caches automatically just to obtain a green test run.

A passing run demonstrates this release on that host; it cannot rule out intermittent OS storage failures.

## GUI Phase 01 extension

The GUI is additive; verify its behaviour using `GUI_README.md` on Windows 10. The integrity manifest covers GUI files as well as the frozen backend. The existing release verification script does not prove the GUI launches or renders correctly on Windows.
