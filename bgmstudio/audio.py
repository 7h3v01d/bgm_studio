"""Audio utilities: LUFS measurement/normalisation, encoding, voice-activity ducking mix."""
from __future__ import annotations

import math
import os
import re
import subprocess
import tempfile

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


def normalize_lufs(audio: np.ndarray, target: float, sr: int = SR, ceiling_db: float = -1.0):
    """Constant-gain loudness match (loop-seam safe).  Gain is capped so the sample peak stays <= ceiling.
    Returns (audio, resulting_lufs)."""
    cur = measure_lufs(audio, sr)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if cur is None or peak <= 0:
        return audio, cur
    gain_db = min(target - cur, ceiling_db - 20 * math.log10(peak))
    return (audio * 10 ** (gain_db / 20)).astype(np.float32), cur + gain_db


def write_audio(path: str, audio: np.ndarray, sr: int = SR) -> str:
    fmt = os.path.splitext(path)[1].lstrip(".").lower() or "wav"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if fmt in LOSSLESS:
        sf.write(path, audio, sr, format=LOSSLESS[fmt][0], subtype=LOSSLESS[fmt][1])
    elif fmt in LOSSY:
        with tempfile.TemporaryDirectory() as d:
            tmp = os.path.join(d, "t.wav")
            sf.write(tmp, audio, sr, subtype="FLOAT")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp] + LOSSY[fmt] + [path], check=True)
    else:
        raise ValueError(f"Unsupported format {fmt!r}; use one of: {', '.join(list(LOSSLESS) + list(LOSSY))}")
    return path


def read_audio(path: str, sr: int = SR) -> np.ndarray:
    """Decode anything ffmpeg understands to float32 stereo at `sr`."""
    with tempfile.TemporaryDirectory() as d:
        tmp = os.path.join(d, "in.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-ac", "2", "-ar", str(sr),
                        "-c:a", "pcm_f32le", tmp], check=True)
        data, _ = sf.read(tmp, dtype="float32", always_2d=True)
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
                        duck_db: float = 9.0, final_lufs: float = -16.0, threshold_db: float = -42.0):
    """Voice gets `lead_in` seconds of music before the first word and `tail_out` after the last.
    `music` must already be lead_in + len(voice) + tail_out long."""
    li = int(lead_in * sr)
    total = li + len(voice) + int(tail_out * sr)
    if abs(len(music) - total) > sr // 10:
        raise ValueError(f"music length {len(music)/sr:.2f}s does not match required {total/sr:.2f}s")
    music = music[:total] if len(music) >= total else np.pad(music, ((0, total - len(music)), (0, 0)))
    voice_n, v_lufs = normalize_lufs(voice, voice_lufs, sr, ceiling_db=-1.5)
    music_n, m_lufs = normalize_lufs(music, music_lufs, sr, ceiling_db=-3.0)
    placed = np.zeros_like(music_n)
    placed[li:li + len(voice_n)] = voice_n
    g = duck_gain(placed, sr, threshold_db=threshold_db, duck_db=duck_db)
    mixed = placed + music_n * g[:, None]
    out, f_lufs = normalize_lufs(mixed, final_lufs, sr, ceiling_db=-1.0)
    stats = {"voice_lufs": v_lufs, "music_lufs": m_lufs, "final_lufs": f_lufs,
             "ducked_fraction": float(np.mean(g < 0.8))}
    return out, stats
