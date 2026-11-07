"""Synthesised transition effects for scene cuts (pure numpy; no samples or SoundFont needed).

  riser        band-limited noise sweeping upward + a tone gliding into the key, ending right at the cut
  impact       a key-tuned sub boom plus a reverberant noise burst, starting on the cut
  downlifter   a riser in reverse, starting on the cut (energy leaving)
  swell        a smooth gain bump on the music, peaking at the cut

All are deterministic for a given seed.
"""
from __future__ import annotations

import numpy as np

TRANSITIONS = ("none", "riser", "impact", "riser_impact", "downlifter", "swell", "auto")
_N_FFT, _HOP = 2048, 512


def _stft_shape(noise: np.ndarray, sr: int, weight_fn) -> np.ndarray:
    """Time-varying spectral shaping of `noise` via overlap-add STFT. weight_fn(frame, n_frames, freqs)->mask."""
    n = len(noise)
    freqs = np.fft.rfftfreq(_N_FFT, 1.0 / sr)
    pad = np.concatenate([noise, np.zeros(_N_FFT, dtype=noise.dtype)])
    win = np.hanning(_N_FFT).astype(np.float32)
    n_frames = max(1, (len(pad) - _N_FFT) // _HOP + 1)
    out = np.zeros(len(pad), dtype=np.float64)
    norm = np.zeros(len(pad), dtype=np.float64)
    for k in range(n_frames):
        a = k * _HOP
        spec = np.fft.rfft(pad[a:a + _N_FFT] * win) * weight_fn(k, n_frames, freqs)
        out[a:a + _N_FFT] += np.fft.irfft(spec, _N_FFT) * win
        norm[a:a + _N_FFT] += win ** 2
    return (out / np.maximum(norm, 1e-6))[:n].astype(np.float32)


def key_hz(key_pc: int, octave_c1: bool = True) -> float:
    """Frequency of the key's tonic, folded low (C1 = 32.7 Hz) if octave_c1 else C3."""
    return (32.7032 if octave_c1 else 130.8128) * 2 ** (key_pc / 12.0)


def _peak_norm(x: np.ndarray) -> np.ndarray:
    return x / max(float(np.max(np.abs(x))), 1e-9)


def riser(length: float, sr: int, seed: int, key_pc: int = 0, f0: float = 250.0, f1: float = 9000.0) -> np.ndarray:
    n = max(int(length * sr), 256)
    rng = np.random.default_rng(seed)

    def band(k, K, freqs):
        fc = f0 * (f1 / f0) ** (k / max(K - 1, 1))
        return np.exp(-0.5 * ((np.log2(np.maximum(freqs, 20.0)) - np.log2(fc)) / 1.1) ** 2)

    x = np.stack([_stft_shape(rng.standard_normal(n).astype(np.float32), sr, band) for _ in range(2)], axis=1)
    x = _peak_norm(x)
    t = np.linspace(0, 1, n, dtype=np.float64)
    f_a, f_b = key_hz(key_pc, False), key_hz(key_pc, False) * 3.0   # tonic up to the fifth above the next octave
    freq = f_a * (f_b / f_a) ** t
    tone = np.sin(2 * np.pi * np.cumsum(freq) / sr).astype(np.float32)
    env = (t ** 2.2).astype(np.float32)[:, None]
    y = (x * 0.9 + 0.35 * tone[:, None]) * env
    fade = min(int(0.006 * sr), n)
    y[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
    return _peak_norm(y).astype(np.float32)


def downlifter(length: float, sr: int, seed: int, key_pc: int = 0) -> np.ndarray:
    y = riser(length, sr, seed, key_pc)[::-1].copy()
    fade = min(int(0.012 * sr), len(y))
    y[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)[:, None]
    return y


def impact(sr: int, seed: int, key_pc: int = 0, length: float = 3.2) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(length * sr)
    t = np.arange(n, dtype=np.float64) / sr
    f_end = key_hz(key_pc, True)
    freq = f_end + (f_end * 3.2 - f_end) * np.exp(-t * 9.0)       # pitch drop onto the tonic
    boom = np.sin(2 * np.pi * np.cumsum(freq) / sr) * np.exp(-t * 1.5)
    ir_n = int(1.4 * sr)
    ir_t = np.arange(ir_n) / sr
    chans = []
    for _ in range(2):
        burst = rng.standard_normal(n) * np.exp(-t * 7.0)
        spec = np.fft.rfft(burst)
        f = np.fft.rfftfreq(n, 1 / sr)
        burst = np.fft.irfft(spec / (1 + (f / 4500.0) ** 2), n)             # roll off the fizz
        ir = rng.standard_normal(ir_n) * np.exp(-ir_t / 0.55)
        rev = np.fft.irfft(np.fft.rfft(burst, n + ir_n) * np.fft.rfft(ir, n + ir_n), n + ir_n)[:n]
        chans.append(boom + 0.55 * _peak_norm(rev) + 0.3 * burst / max(np.max(np.abs(burst)), 1e-9))
    y = np.stack(chans, axis=1).astype(np.float32)
    y[:int(0.002 * sr)] *= np.linspace(0, 1, int(0.002 * sr), dtype=np.float32)[:, None]
    return _peak_norm(y).astype(np.float32)


def swell_curve(n_total: int, cut: int, sr: int, pre: float = 2.0, post: float = 0.8, peak_db: float = 3.5):
    """Per-sample linear gain (length n_total): rises into `cut` and relaxes smoothly after it."""
    g = np.zeros(n_total, dtype=np.float32)
    a, b = max(0, cut - int(pre * sr)), min(n_total, cut + int(post * sr * 4))
    if cut > a:
        g[a:cut] = np.linspace(0, 1, cut - a, dtype=np.float32) ** 2
    if b > cut:
        g[cut:b] = np.exp(-np.arange(b - cut, dtype=np.float32) / (post * sr))
    return (10 ** (peak_db * g / 20)).astype(np.float32)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if x.size else 0.0


def apply_transition(out: np.ndarray, name: str, cut: int, sr: int, *, seed: int, key_pc: int, level_db: float,
                     prev_len: float, next_len: float) -> None:
    """Mix a transition into `out` in place around sample index `cut` (the new scene's downbeat).
    `level_db` is relative to the local music RMS (riser/downlifter end/start level)."""
    n_total = len(out)
    ref = _rms(out[max(0, cut - 3 * sr):min(n_total, cut + sr)])
    if ref <= 0 or name == "none":
        return
    gain = 10 ** (level_db / 20.0)
    if name in ("riser", "riser_impact"):
        length = min(3.2, prev_len * 0.7)
        if length >= 0.5:
            r = riser(length, sr, seed, key_pc)
            start = max(0, cut - len(r))
            r = r[len(r) - (cut - start):]
            r = r * (ref * gain / max(_rms(r[-sr:]), 1e-9))
            out[start:cut] += r
    if name in ("impact", "riser_impact"):
        im = impact(sr, seed + 1, key_pc)
        im = im * (ref * gain * 1.6 / max(_rms(im[:sr // 2]), 1e-9))
        seg = im[:max(0, n_total - cut)]
        out[cut:cut + len(seg)] += seg
    if name == "downlifter":
        length = min(3.2, next_len * 0.6)
        if length >= 0.5:
            d = downlifter(length, sr, seed + 2, key_pc)
            d = d * (ref * gain / max(_rms(d[:sr]), 1e-9))
            seg = d[:max(0, n_total - cut)]
            out[cut:cut + len(seg)] += seg
    if name == "swell":
        out *= swell_curve(n_total, cut, sr)[:, None]
