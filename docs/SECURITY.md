# Security

## Intended deployment

BGM Studio is designed for a single trusted user on one machine. The launchers bind the REST API and the MCP HTTP
server to `127.0.0.1`. In this configuration the protections below are sufficient. They are not sufficient for a
service reachable by untrusted users; see [Networked deployment](#networked-deployment).

## Protections in place

### Input limits

Every request is validated before rendering begins, in the engine itself, so the REST API, MCP server, CLI and
Python library enforce the same rules.

| Control | Default | Setting |
|---|---|---|
| Value ranges for every numeric parameter | see the User Manual, section 10 | fixed |
| Maximum output length (including a mix's lead-in and tail-out) | 7200 s | `BGM_MAX_RENDER_SECONDS` |
| Maximum scenes per sequence or mix | 100 | `BGM_MAX_SCENES` |
| Estimated render working memory | 16384 MiB | `BGM_MAX_RENDER_MEMORY_MIB` |
| Stems | 1 hour per file | fixed |
| Narration file size | 100 MiB | `BGM_MAX_UPLOAD_BYTES` |

Narration uploads are rejected early when the declared `Content-Length` is too large, and the copy loop enforces the
byte limit even if the header is absent or wrong. The narration's duration is probed with ffprobe before decoding,
decoding is capped in length, and the decoded sample count is checked again.

Memory admission is an estimate based on the number of full-length buffers each kind of render holds. It does not
measure the RAM actually available and is not a hard allocation limit.

### External processes

FFmpeg and ffprobe are invoked with argument lists (no shell) and a timeout (`BGM_FFMPEG_TIMEOUT`, default 180 s).
A timeout returns HTTP 504. Undecodable media returns HTTP 422 with the decoder's reason.

### Authentication

Setting `BGM_API_KEY` requires `X-API-Key` on every REST endpoint except `/health`. The key is compared in constant
time. `/health` reports whether a SoundFont is available but not its location.

### MCP file access

MCP tools act on the server's file system, so their paths are confined:

- Outputs must resolve (symbolic links included) inside `BGM_MCP_OUTPUT_DIR`, which defaults to the output directory.
- Narration must resolve inside `BGM_MCP_INPUT_DIR`. Until that variable is set, narration mixing over MCP is refused.

### Output integrity and concurrency

- Output files and their JSON records are written atomically through temporary sibling files, so a reader never sees a
  partial file and a failed write leaves the previous file intact.
- Cache entries are reused only if each file's size and SHA-256 match its record. Hashes are cached per process by
  path, size and modification time; `BGM_STRICT_CACHE_HASHES=1` re-hashes on every reuse to catch edits that restore
  the size and timestamp.
- Cache identity includes every audible parameter, the SoundFont's SHA-256 and the engine revision, so different
  requests never share an output file.
- Renders are serialised within a process and coordinated across processes by a lock file in the output directory.
  A lock wait longer than `BGM_LOCK_TIMEOUT` returns HTTP 503 with `Retry-After`. Cache hits do not wait for the lock.

### File serving

`GET /files/{name}` serves only files directly inside the output directory. The path is reduced to its base name
before lookup.

## Networked deployment

Before exposing the REST API or the MCP HTTP server beyond the local machine, add:

1. **Authentication and transport security.** Set `BGM_API_KEY` at minimum, and serve over TLS through a reverse proxy.
2. **A request body limit at the proxy.** The framework may buffer multipart uploads before the service's own limit
   applies.
3. **Rate and concurrency limits.** Renders are CPU- and memory-intensive. Run a single worker process; the render
   lock coordinates file renders but streaming is not admission-controlled across workers.
4. **Per-user separation.** The output directory and `/files` are shared by all callers. There is no per-user
   ownership of results.
5. **Isolation for untrusted media.** Narration files are decoded by FFmpeg. Decode untrusted input in a sandboxed
   process or container with resource quotas.
6. **Lower limits** appropriate to the host (`BGM_MAX_RENDER_SECONDS`, `BGM_MAX_RENDER_MEMORY_MIB`, `BGM_MAX_SCENES`).

Known limitations: there is no job queue or cancellation for long renders, and a file replaced between the ffprobe
check and decoding is not detected.

## Reporting a vulnerability

Report suspected vulnerabilities privately to the maintainer through GitHub
([7h3v01d](https://github.com/7h3v01d)) rather than in a public issue. Include the version (`bgmstudio.__version__`),
the interface involved and steps to reproduce.
