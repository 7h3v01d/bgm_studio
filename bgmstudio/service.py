"""Core operations shared by the REST API, the MCP server and the CLI."""
from __future__ import annotations

import hashlib
import json
import os
import random

import numpy as np

from .audio import (MIME, audio_duration, measure_lufs, mix_voice_and_music, normalize_lufs,
                    read_audio, write_audio)
from .compose import Plan, compose, export_midi
from .calibrate import get_cal
from .presets import describe_moods
from .render import SR, find_soundfont, render_audio, stream_wav

OUT_DIR = os.path.abspath(os.environ.get("BGM_OUT_DIR", "bgm_out"))


def _out_dir(d=None) -> str:
    p = os.path.abspath(d or OUT_DIR)
    os.makedirs(p, exist_ok=True)
    return p


def moods() -> dict:
    return describe_moods()


def _new_seed(seed):
    return int(seed) if seed is not None else random.SystemRandom().randrange(1, 2**31 - 1)


def render_music(mood: str, duration: float, *, loop=False, seed=None, key=None, mode=None, bpm=None,
                 fade_out=3.0, target_lufs=-20.0, soundfont=None):
    """-> (float32 stereo array, Plan, achieved LUFS).  Exactly round(duration*SR) samples."""
    plan = compose(mood, duration, loop=loop, seed=_new_seed(seed), key=key, mode=mode, bpm=bpm,
                   fade_out=fade_out)
    audio = render_audio(plan, soundfont)
    audio, lufs = normalize_lufs(audio, target_lufs)
    return audio, plan, lufs


def generate_bgm(mood: str = "calm", duration: float = 60.0, *, loop: bool = False, seed: int | None = None,
                 key: str | None = None, mode: str | None = None, bpm: float | None = None,
                 format: str = "wav", target_lufs: float = -20.0, fade_out: float = 3.0,
                 soundfont: str | None = None, out_dir: str | None = None, midi: bool = False,
                 use_cache: bool = True) -> dict:
    """Generate a background-music file of exactly `duration` seconds.

    loop=True  -> sample-seamless loop (no fade, tail folded onto the start).
    loop=False -> proper cadence ending plus a fade-out.
    The same (mood, duration, seed, ...) always gives the same music; the seed is returned.
    """
    format = format.lower().lstrip(".")
    seed = _new_seed(seed)
    sf_path = find_soundfont(soundfont)  # resolved font (name+size) is part of the cache key
    params = dict(mood=mood, duration=float(duration), loop=loop, seed=seed, key=key, mode=mode, bpm=bpm,
                  fmt=format, lufs=target_lufs, fade=fade_out, sf=f"{os.path.basename(sf_path)}:{os.path.getsize(sf_path)}")
    h = hashlib.sha1(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:12]
    d = _out_dir(out_dir)
    stem = f"bgm_{params['mood'].lower()}_{int(duration)}s{'_loop' if loop else ''}_{seed}_{h}"
    path, meta_path, mid_path = (os.path.join(d, stem + ext) for ext in (f".{format}", ".json", ".mid"))
    if use_cache and os.path.isfile(path) and os.path.isfile(meta_path) and (not midi or os.path.isfile(mid_path)):
        with open(meta_path) as f:
            return {**json.load(f), "cached": True}

    audio, plan, lufs = render_music(mood, duration, loop=loop, seed=seed, key=key, mode=mode, bpm=bpm,
                                     fade_out=fade_out, target_lufs=target_lufs, soundfont=soundfont)
    write_audio(path, audio)
    result = {**plan.summary(), "path": path, "format": format, "mime": MIME[format],
              "lufs": None if lufs is None else round(lufs, 1), "samples": int(len(audio)),
              "sample_rate": SR, "cached": False}
    if midi:
        result["midi_path"] = export_midi(plan, mid_path)
    with open(meta_path, "w") as f:
        json.dump(result, f, indent=1)
    return result


def stream_bgm(mood: str, duration: float, *, seed=None, key=None, mode=None, bpm=None,
               target_lufs: float = -20.0, fade_out: float = 3.0, soundfont=None):
    """-> (plan, content_length, iterator of WAV bytes).  Non-loop; static per-mood gain (no look-ahead)."""
    plan = compose(mood, duration, loop=False, seed=_new_seed(seed), key=key, mode=mode, bpm=bpm,
                   fade_out=fade_out)
    length, it = stream_wav(plan, gain_db=target_lufs - get_cal(plan.mood, soundfont), soundfont=soundfont)
    return plan, length, it


def mix_with_narration(narration_path: str, mood: str = "calm", *, lead_in: float = 1.5, tail_out: float = 3.0,
                       voice_lufs: float = -16.0, music_lufs: float = -26.0, duck_db: float = 9.0,
                       final_lufs: float = -16.0, seed: int | None = None, key: str | None = None,
                       mode: str | None = None, bpm: float | None = None, format: str = "wav",
                       soundfont: str | None = None, out_dir: str | None = None) -> dict:
    """Score a narration track: music is generated to fit it exactly, ducks under speech, fades after it."""
    format = format.lower().lstrip(".")
    voice = read_audio(narration_path)
    total = lead_in + len(voice) / SR + tail_out
    seed = _new_seed(seed)
    plan = compose(mood, total, loop=False, seed=seed, key=key, mode=mode, bpm=bpm, fade_out=max(tail_out, 2.0))
    music = render_audio(plan, soundfont)
    mixed, stats = mix_voice_and_music(voice, music, lead_in=lead_in, tail_out=tail_out, voice_lufs=voice_lufs,
                                       music_lufs=music_lufs, duck_db=duck_db, final_lufs=final_lufs)
    d = _out_dir(out_dir)
    base = os.path.splitext(os.path.basename(narration_path))[0]
    path = os.path.join(d, f"{base}_scored_{plan.mood}_{seed}.{format}")
    write_audio(path, mixed)
    return {**plan.summary(), "path": path, "format": format, "mime": MIME[format],
            "narration_seconds": round(len(voice) / SR, 2), "lead_in": lead_in, "tail_out": tail_out,
            "total_seconds": round(len(mixed) / SR, 3),
            **{k: (None if v is None else round(v, 2)) for k, v in stats.items()}}
