# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""Audio utilities: LUFS measurement/normalisation, encoding, voice-activity ducking mix."""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
import uuid

import numpy as np
import soundfile as sf

from .render import SR

LOSSLESS = {"wav": ("WAV", "PCM_24"), "flac": ("FLAC", "PCM_24")}
LOSSY = {"mp3": ["-codec:a", "libmp3lame", "-q:a", "2"],
         "m4a": ["-codec:a", "aac", "-b:a", "256k"],
         "ogg": ["-codec:a", "libvorbis", "-q:a", "6"]}
MIME = {"wav": "audio/wav", "flac": "audio/flac", "mp3": "audio/mpeg", "m4a": "audio/mp4", "ogg": "audio/ogg"}


def measure_lufs(audio: np.ndarray, sr: int = SR):
    """Integrated loudness (BS.1770 via ffmpeg's ebur128). Returns None for silence."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "m.wav")
        sf.write(p, audio, sr, subtype="FLOAT")
        r = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", p, "-af", "ebur128=framelog=quiet",
                            "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", r.stderr)
    if not m:
        return None
    v = float(m[-1])
    return v if math.isfinite(v) else None


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


def write_audio(path: str, audio: np.ndarray, sr: int = SR) -> str:
    """Encode `audio` to `path` atomically: readers see either no file or the complete file, never a partial one."""
    fmt = os.path.splitext(path)[1].lstrip(".").lower() or "wav"
    if fmt not in LOSSLESS and fmt not in LOSSY:
        raise ValueError(f"Unsupported format {fmt!r}; use one of: {', '.join(list(LOSSLESS) + list(LOSSY))}")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    part = _partial_path(path)
    try:
        if fmt in LOSSLESS:
            sf.write(part, audio, sr, format=LOSSLESS[fmt][0], subtype=LOSSLESS[fmt][1])
        else:
            with tempfile.TemporaryDirectory() as d:
                tmp = os.path.join(d, "t.wav")
                sf.write(tmp, audio, sr, subtype="FLOAT")
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp] + LOSSY[fmt] + [part], check=True)
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return path


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
    with tempfile.TemporaryDirectory() as d:
        tmp = os.path.join(d, "in.wav")
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-ac", "2", "-ar", str(sr),
                            "-c:a", "pcm_f32le", tmp], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(tmp):
            reason = (r.stderr.strip().splitlines() or ["unknown error"])[-1]
            raise ValueError(f"could not decode audio file {os.path.basename(path)!r}: {reason}")
        data, _ = sf.read(tmp, dtype="float32", always_2d=True)
    if not len(data):
        raise ValueError(f"audio file {os.path.basename(path)!r} contains no samples")
    return data


def audio_duration(path: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                        "default=nw=1:nk=1", path], capture_output=True, text=True, check=True)
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
