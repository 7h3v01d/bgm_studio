# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""Audio utilities: LUFS measurement/normalisation, encoding, voice-activity ducking mix."""
from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid

import numpy as np
import soundfile as sf

from .render import SR

LOSSLESS = {"wav": ("WAV", "PCM_24"), "flac": ("FLAC", "PCM_24")}
LOSSY = {"mp3": ["-codec:a", "libmp3lame", "-q:a", "2"],
         "m4a": ["-codec:a", "aac", "-b:a", "256k"],
         "ogg": ["-codec:a", "libvorbis", "-q:a", "6"]}
FFMPEG_TIMEOUT = float(os.environ.get("BGM_FFMPEG_TIMEOUT", "180"))

MIME = {"wav": "audio/wav", "flac": "audio/flac", "mp3": "audio/mpeg", "m4a": "audio/mp4", "ogg": "audio/ogg"}
_LOG = logging.getLogger(__name__)


def measure_lufs(audio: np.ndarray, sr: int = SR):
    """Integrated loudness (BS.1770 via FFmpeg ebur128); no temporary WAV file.

    Send raw float32 PCM through stdin instead of writing a potentially huge
    scratch WAV to the Windows temporary directory.  The measurement filter,
    sample values, rate and channel layout remain the same as before.
    """
    pcm = np.asarray(audio, dtype=np.float32)
    if pcm.ndim == 1:
        channels = 1
    elif pcm.ndim == 2 and pcm.shape[1] in (1, 2):
        channels = pcm.shape[1]
    else:
        raise ValueError("expected mono or stereo audio for loudness measurement")
    if pcm.size == 0:
        return None
    pcm = np.ascontiguousarray(pcm, dtype="<f4")
    command = ["ffmpeg", "-nostats", "-hide_banner", "-f", "f32le",
               "-ar", str(sr), "-ac", str(channels), "-i", "pipe:0",
               "-af", "ebur128=framelog=quiet", "-f", "null", "-"]
    result = subprocess.run(command, input=pcm.tobytes(), capture_output=True,
                            timeout=FFMPEG_TIMEOUT)
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        reason = (stderr.strip().splitlines() or ["unknown error"])[-1]
        raise RuntimeError(f"FFmpeg loudness measurement failed: {reason}")
    matches = re.findall(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", stderr)
    if not matches:
        return None
    value = float(matches[-1])
    return value if math.isfinite(value) else None


def loudness_gain(audio: np.ndarray, target: float, sr: int = SR, ceiling_db: float = -1.0):
    """-> (linear gain, resulting LUFS) that normalize_lufs would apply.  Lets callers apply one gain to several
    tracks (stems) that must keep adding up to the normalised mix.  (1.0, None) for silence."""
    cur = measure_lufs(audio, sr)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if cur is None or peak <= 0:
        return 1.0, cur
    gain_db = min(target - cur, ceiling_db - 20 * math.log10(peak))
    return 10 ** (gain_db / 20), cur + gain_db


def normalize_lufs(audio: np.ndarray, target: float, sr: int = SR, ceiling_db: float = -1.0):
    """Constant-gain loudness match (loop-seam safe).  Gain is capped so the sample peak stays <= ceiling.
    Returns (audio, resulting_lufs)."""
    g, lufs = loudness_gain(audio, target, sr, ceiling_db)
    if lufs is None:
        return audio, lufs
    return (audio * g).astype(np.float32), lufs


def _partial_path(path: str) -> str:
    """Sibling temp name that keeps the real extension (ffmpeg picks the container from it)."""
    d, name = os.path.split(os.path.abspath(path))
    stem, ext = os.path.splitext(name)
    return os.path.join(d, f".{stem}.{uuid.uuid4().hex[:8]}.partial{ext}")


def _output_write_failure(path: str, audio: np.ndarray, fmt: str, exc: BaseException) -> RuntimeError:
    """Provide useful local diagnostics without returning paths or disk details to API clients."""
    directory = os.path.dirname(os.path.abspath(path))
    try:
        free_mib = shutil.disk_usage(directory).free / (1024 * 1024)
        free = f"{free_mib:.1f} MiB"
    except OSError as disk_error:
        free = f"unavailable ({disk_error})"
    try:
        nbytes = int(np.asarray(audio).nbytes)
    except (ValueError, TypeError):
        nbytes = -1
    _LOG.error("Audio output write failed: path=%r format=%s pcm_bytes=%d free=%s error=%r",
               path, fmt, nbytes, free, exc)
    return RuntimeError("audio output could not be written; check destination disk space, "
                        "write permissions and native audio libraries (see server log)")


def write_audio(path: str, audio: np.ndarray, sr: int = SR) -> str:
    """Encode audio atomically, retrying a transient libsndfile write once.

    On failure, preserve an existing destination and remove partial files.
    Each attempt uses a unique sibling partial path. No alternate encoder is
    used: successful WAV/FLAC bytes retain the existing deterministic semantics.
    """
    fmt = os.path.splitext(path)[1].lstrip(".").lower() or "wav"
    if fmt not in LOSSLESS and fmt not in LOSSY:
        raise ValueError(f"Unsupported format {fmt!r}; use one of: {', '.join(list(LOSSLESS) + list(LOSSY))}")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    attempts = 2 if fmt in LOSSLESS else 1
    for attempt in range(attempts):
        part = _partial_path(path)
        try:
            if fmt in LOSSLESS:
                sf.write(part, audio, sr, format=LOSSLESS[fmt][0], subtype=LOSSLESS[fmt][1])
            else:
                with tempfile.TemporaryDirectory() as d:
                    tmp = os.path.join(d, "t.wav")
                    sf.write(tmp, audio, sr, subtype="FLOAT")
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp] + LOSSY[fmt] + [part],
                                   check=True, timeout=FFMPEG_TIMEOUT)
            os.replace(part, path)
            return path
        except (sf.LibsndfileError, OSError) as exc:
            if attempt + 1 < attempts:
                _LOG.warning("Audio file write failed (attempt %d/%d); retrying: %s",
                             attempt + 1, attempts, type(exc).__name__)
                time.sleep(0.15)
            else:
                raise _output_write_failure(path, audio, fmt, exc) from exc
        finally:
            if os.path.exists(part):
                os.remove(part)
    raise AssertionError("unreachable audio write state")


def write_json(path: str, data) -> str:
    """Atomic JSON write (same guarantee as write_audio)."""
    part = _partial_path(path)
    try:
        with open(part, "w") as f:
            json.dump(data, f, indent=1)
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return path


def read_audio(path: str, sr: int = SR) -> np.ndarray:
    """Decode anything ffmpeg understands to float32 stereo at `sr`.

    Raises FileNotFoundError if `path` is missing and ValueError (with ffmpeg's reason) if it can't be decoded."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"narration file not found: {path}")
    from .service import MAX_RENDER_SECONDS, MAX_NARRATION_BYTES
    if os.path.getsize(path) > MAX_NARRATION_BYTES:
        raise ValueError("narration exceeds input byte budget")
    try:
        duration = audio_duration(path)
    except (subprocess.CalledProcessError, ValueError) as e:
        raise ValueError(f"could not decode audio file {os.path.basename(path)!r}: invalid media") from e
    if not math.isfinite(duration) or duration <= 0 or duration > MAX_RENDER_SECONDS:
        raise ValueError(f"narration duration exceeds input budget ({MAX_RENDER_SECONDS:g}s)")
    with tempfile.TemporaryDirectory() as d:
        tmp = os.path.join(d, "in.wav")
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-ac", "2", "-ar", str(sr),
                            "-t", str(MAX_RENDER_SECONDS + 1), "-c:a", "pcm_f32le", tmp], capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
        if r.returncode != 0 or not os.path.isfile(tmp):
            reason = (r.stderr.strip().splitlines() or ["unknown error"])[-1]
            raise ValueError(f"could not decode audio file {os.path.basename(path)!r}: {reason}")
        # Decoder is capped with -t, but also inspect decoded frame count before loading
        # into NumPy (a malformed container can otherwise allocate too much memory).
        with sf.SoundFile(tmp) as decoded:
            if decoded.frames > int(MAX_RENDER_SECONDS * sr):
                raise ValueError("decoded narration exceeds duration budget")
            data = decoded.read(dtype="float32", always_2d=True)
    if len(data) > int(MAX_RENDER_SECONDS * sr):
        raise ValueError("decoded narration exceeds duration budget")
    if not len(data):
        raise ValueError(f"audio file {os.path.basename(path)!r} contains no samples")
    return data


def audio_duration(path: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                        "default=nw=1:nk=1", path], capture_output=True, text=True, check=True, timeout=FFMPEG_TIMEOUT)
    return float(r.stdout.strip())


# ------------------------------------------------------------------ ducking
def duck_gain(voice: np.ndarray, sr: int = SR, *, threshold_db: float = -42.0, duck_db: float = 9.0,
              attack_ms: float = 80.0, release_ms: float = 700.0, hold_ms: float = 350.0,
              lookahead_ms: float = 60.0) -> np.ndarray:
    """Per-sample linear gain curve for the music: dips while someone is talking.

    Voice activity at 100 frames/s, held across the short gaps between words, shifted
    earlier by `lookahead_ms` so the music is already down when the first word lands,
    then smoothed with separate attack/release time constants.
    """
    mono = voice.mean(axis=1) if voice.ndim == 2 else voice
    hop = sr // 100
    nfr = len(mono) // hop + 1
    pad = np.zeros(nfr * hop - len(mono), dtype=np.float32)
    frames = np.concatenate([mono, pad]).reshape(nfr, hop)
    rms_db = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-12)
    active = (rms_db > threshold_db).astype(np.float32)
    hold = max(1, int(hold_ms / 10))
    active = (np.convolve(active, np.ones(hold, dtype=np.float32))[:nfr] > 0).astype(np.float32)
    la = int(lookahead_ms / 10)
    if la:
        active = np.concatenate([active[la:], np.zeros(la, dtype=np.float32)])
    a_att = math.exp(-10.0 / attack_ms)
    a_rel = math.exp(-10.0 / release_ms)
    env = np.empty(nfr, dtype=np.float32)
    y = 0.0
    for i, x in enumerate(active):
        coef = a_att if x > y else a_rel
        y = coef * y + (1 - coef) * x
        env[i] = y
    gain_db = -duck_db * env
    centers = (np.arange(nfr) + 0.5) * hop
    g = np.interp(np.arange(len(mono)), centers, gain_db)
    return (10 ** (g / 20)).astype(np.float32)


def mix_voice_and_music(voice: np.ndarray, music: np.ndarray, sr: int = SR, *, lead_in: float = 1.5,
                        tail_out: float = 3.0, voice_lufs: float = -16.0, music_lufs: float = -26.0,
                        duck_db: float = 9.0, final_lufs: float = -16.0, threshold_db: float = -42.0,
                        fx: np.ndarray | None = None, stems: bool = False):
    """Voice gets `lead_in` seconds of music before the first word and `tail_out` after the last.
    `music` must already be lead_in + len(voice) + tail_out long.

    fx: transition effects kept apart from `music` (same length); they are levelled, ducked and mixed exactly as
    if they were part of the music.  stems=True also returns {"voice", "music", ["fx"]}: aligned, ducked and
    scaled so they add up to the mix.  -> (mix, stats, stems or None)"""
    li = int(lead_in * sr)
    total = li + len(voice) + int(tail_out * sr)
    if abs(len(music) - total) > sr // 10:
        raise ValueError(f"music length {len(music)/sr:.2f}s does not match required {total/sr:.2f}s")

    def fit(a):
        return a[:total] if len(a) >= total else np.pad(a, ((0, total - len(a)), (0, 0)))
    music = fit(music)
    fx = None if fx is None else fit(fx)
    voice_n, v_lufs = normalize_lufs(voice, voice_lufs, sr, ceiling_db=-1.5)
    bed = music if fx is None else music + fx
    gm, m_lufs = loudness_gain(bed, music_lufs, sr, ceiling_db=-3.0)
    music_n = bed if m_lufs is None else (bed * gm).astype(np.float32)
    placed = np.zeros_like(music_n)
    placed[li:li + len(voice_n)] = voice_n
    g = duck_gain(placed, sr, threshold_db=threshold_db, duck_db=duck_db)
    mixed = placed + music_n * g[:, None]
    gf, f_lufs = loudness_gain(mixed, final_lufs, sr, ceiling_db=-1.0)
    out = mixed if f_lufs is None else (mixed * gf).astype(np.float32)
    stats = {"voice_lufs": v_lufs, "music_lufs": m_lufs, "final_lufs": f_lufs,
             "ducked_fraction": float(np.mean(g < 0.8))}
    parts = None
    if stems:
        k = (g * np.float32(gm * gf))[:, None]
        parts = {"voice": (placed * np.float32(gf)).astype(np.float32), "music": (music * k).astype(np.float32)}
        if fx is not None:
            parts["fx"] = (fx * k).astype(np.float32)
    return out, stats, parts
