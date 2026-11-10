# BGM Studio 0.10.3 hardening handoff

Based on user-provided 0.10.2 archive. No composition or audio DSP changes. `ENGINE_REVISION` remains 1.

## What was addressed
- Render PCM memory admission estimate, configurable via `BGM_MAX_RENDER_MEMORY_MIB` (default 16384 MiB). Host RAM is **not** measured: adjust according to machine and concurrent workloads.
- Narration full-mix duration/memory preflight before decode; post-decode check remains.
- Unix advisory-lock timeout parity.
- Optional strict full SHA-256 cache verification for restored-mtime tampering.
- Worker-thread result/error assertions in concurrency regression.

## Verification and limitations
- New environment-independent tests run on Linux.
- Full audio integration requires the user's functioning Windows 10 + FluidSynth environment.
- No claim of protection against input file replacement between ffprobe and decode, or absolute prevention of peak OOM.
- Multipart upload storage, externally exposed endpoints, malicious FFmpeg inputs, and tenant isolation still require deployment controls.
- Preserve 0.10.2 as known-good rollback.

## Windows release check
In a fresh extracted directory with the usual SoundFont/FluidSynth/ffmpeg installation, run `setup.bat` then `test.bat`. Expected test counts may increase; the Windows symlink privilege skip is permitted. Examine all failures before promoting this build.

## Suggested operator settings
`BGM_MAX_RENDER_MEMORY_MIB=4096` on smaller-memory machines; the engine then rejects expensive requests before PCM allocation. `BGM_STRICT_CACHE_HASHES=1` for stronger integrity at the expense of hashing all cache outputs on each lookup.
