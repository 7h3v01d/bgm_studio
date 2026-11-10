# BGM Studio 0.10.1 — Adversarial hardening handoff

2026-11-10. This archive is an edited derivative of the user's v0.10 source.

## Implemented

- F01: mix output name now derives from every relevant parameter, narration content, SoundFont content and engine version; verified cache reuse and locked commits.
- F02: generated output length and scene count capped before renderer allocations; 600 seconds, 100 scenes by default. Limits can be configured through environment variables.
- F03: 100 MiB upload/input cap; large Content-Length rejected early; chunked copy refuses excess bytes; FFprobe rejects oversized audio by reported duration, FFmpeg decode capped and decoded sample counts checked.
- F04: MCP output paths confined to a configured output root; narration paths require BGM_MCP_INPUT_DIR and cannot escape that root using normal symlinks.
- F05 (partial): REST key comparison uses constant-time string equality; `/health` no longer returns a real SoundFont path. **Multi-user isolation and a fully secured network deployment are not implemented.**
- F06: SoundFont content participates in cache key, cache reuse checks output hashes and expected paths, lock-dictionary leak removed, and an OS filesystem lock protects shared output directories across processes.
- F07: FFmpeg and FFprobe subprocess calls have timeouts; API timeout returns HTTP 504.
- F08 (partial): setup does not automatically upgrade pip; an exact release lockfile is **not** provided because it could not be generated and tested against supported Windows environments here.

## Validation

- `python -m compileall -q bgmstudio`: PASS.
- `python -m pytest -q tests/test_hardening_0101.py`: 8 PASS.
- `python -m pytest -q tests/test_hardening_0101.py tests/test_regressions.py -k 'not alias and not concurrent'`: 31 PASS, 2 deselected.
- Full test suite: 67 PASS, 31 FAIL, 4 warnings. The review environment lacks `pyfluidsynth` (and Python's namespace package `fluidsynth/` contains no Synth implementation) as well as `mcp`. Audio integration tests and API success tests therefore do not run. A test requiring genuine audio under parallel calls also cannot establish whether caching works with the absent renderer.
- Installing dependencies during the review was unsuccessful due to disabled external package access. No full Windows 10 execution was possible.

## Windows verification (run from project directory)

1. Install project Python dependencies and native FluidSynth DLLs using the existing README and `setup.bat`.
2. Activate `.venv`; run `.venv\Scripts\python.exe -c "import fluidsynth; print(fluidsynth.Synth)"`.
3. Run `.venv\Scripts\python.exe -m pytest -q` and save its result.
4. Run `selftest.py` and a representative narration mix; inspect generated WAV/FLAC, metadata provenance, stem reconstruction, and both plain and differing ducking outputs.
5. Keep REST/MCP bound to loopback, and explicitly choose a safe `BGM_MCP_INPUT_DIR` for MCP narration.

## Remaining release gates

- Audio quality and rendering parity must be checked on Windows with the actual synthesis/encode stack.
- A production-grade render work queue / global admission control remains desirable, especially for streaming routes and multiple workers; use a single trusted loopback worker meanwhile.
- A reverse proxy must cap request body sizes before multipart buffering for remote use. Multi-user REST file permissions, caller quotas and stronger agent sandbox boundaries are not implemented.
- Cross-process locks assume cooperating processes use this patched code and share one output directory. They do not protect against external processes modifying files outside the locking protocol.
- Dependency reproducibility: build and test a Windows-specific lockfile before shipping a formally reproducible release.
- Audio formats and codecs still depend on system FFmpeg and FluidSynth versions.

### Windows self-test follow-up (2026-11-10)

On the actual Windows 10 machine, pytest passed 97 tests with one correctly skipped symlink-permission test. The full audio `selftest.py` passed the checks through MP3 encoding, then stopped at its existing 20-minute render because the new default 600-second safety budget rejected a 1,200-second request. The self-test now establishes a dedicated process-local minimum 1,200-second budget before importing the service. A subsequent complete integration run is still required; this patch does not constitute an observed end-to-end pass.
