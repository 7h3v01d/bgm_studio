"""Core operations shared by the REST API, the MCP server and the CLI."""
from __future__ import annotations

import hashlib
import json
import os
import random

import numpy as np

from .audio import (MIME, audio_duration, measure_lufs, mix_voice_and_music, normalize_lufs,
                    read_audio, write_audio)
from .compose import MIN_SECONDS, NOTE_NAMES, Plan, compose, export_midi
from .calibrate import get_cal
from .presets import describe_moods, resolve_mood
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


def _validate_scenes(scenes) -> list:
    if not scenes:
        raise ValueError("scenes must be a non-empty list of {mood, duration}")
    out = []
    for i, sc in enumerate(scenes):
        if not isinstance(sc, dict) or "mood" not in sc or "duration" not in sc:
            raise ValueError(f"scene {i + 1}: needs 'mood' and 'duration'")
        d = float(sc["duration"])
        if d < MIN_SECONDS:
            raise ValueError(f"scene {i + 1}: duration must be at least {MIN_SECONDS}s")
        resolve_mood(sc["mood"])
        out.append({**sc, "duration": d})
    return out


def render_sequence(scenes: list, *, xfade: float = 2.0, seed: int | None = None, key: str | None = None,
                    target_lufs: float = -20.0, last_fade: float = 3.0, soundfont: str | None = None):
    """One continuous track from per-scene moods.  Scene i starts (downbeat) exactly at the sum of the previous
    durations; consecutive scenes share a key and crossfade (equal-power) over `xfade` seconds *after* the cut.
    Total length = sum of durations, exactly.  -> (audio, [per-scene summary], LUFS, key)"""
    scenes = _validate_scenes(scenes)
    n = len(scenes)
    xfade = max(0.0, min(float(xfade), min(s["duration"] for s in scenes) / 2))
    base = _new_seed(seed)
    if key is None:
        pools = [set(resolve_mood(s["mood"])[1]["key_pcs"]) for s in scenes]
        common = set.intersection(*pools) or pools[0]
        key = NOTE_NAMES[random.Random(f"{base}:key").choice(sorted(common))]
    total_n = int(round(sum(s["duration"] for s in scenes) * SR))
    xs = int(round(xfade * SR))
    fin = np.sin(np.linspace(0, np.pi / 2, xs, dtype=np.float32))[:, None] if xs > 1 else None
    fout = np.cos(np.linspace(0, np.pi / 2, xs, dtype=np.float32))[:, None] if xs > 1 else None
    out = np.zeros((total_n, 2), dtype=np.float32)
    summaries, pos = [], 0.0
    for i, sc in enumerate(scenes):
        last = i == n - 1
        plan = compose(sc["mood"], sc["duration"] + (0.0 if last else xfade), loop=False,
                       seed=sc["seed"] if sc.get("seed") is not None else base + i * 7919, key=key,
                       mode=sc.get("mode"), bpm=sc.get("bpm"), fade_out=last_fade if last else 0.0,
                       open_end=not last)
        audio, _ = normalize_lufs(render_audio(plan, soundfont), target_lufs)
        if fin is not None:
            if i > 0:
                audio[:xs] *= fin
            if not last:
                audio[-xs:] *= fout
        off = int(round(pos * SR))
        seg = audio[:max(0, total_n - off)]
        out[off:off + len(seg)] += seg
        summaries.append({**plan.summary(), "scene": i + 1, "start": round(pos, 3), "duration": sc["duration"]})
        pos += sc["duration"]
    return out, summaries, measure_lufs(out), key


def generate_sequence(scenes: list, *, xfade: float = 2.0, seed: int | None = None, key: str | None = None,
                      format: str = "wav", target_lufs: float = -20.0, fade_out: float = 3.0,
                      soundfont: str | None = None, out_dir: str | None = None) -> dict:
    """Per-scene background music as a single file (see render_sequence)."""
    format = format.lower().lstrip(".")
    scenes = _validate_scenes(scenes)
    seed = _new_seed(seed)
    sf_path = find_soundfont(soundfont)
    params = dict(scenes=scenes, xfade=xfade, seed=seed, key=key, fmt=format, lufs=target_lufs, fade=fade_out,
                  sf=f"{os.path.basename(sf_path)}:{os.path.getsize(sf_path)}")
    h = hashlib.sha1(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:12]
    d = _out_dir(out_dir)
    stem = f"seq_{len(scenes)}scenes_{int(sum(s['duration'] for s in scenes))}s_{seed}_{h}"
    path, meta_path = os.path.join(d, f"{stem}.{format}"), os.path.join(d, f"{stem}.json")
    if os.path.isfile(path) and os.path.isfile(meta_path):
        with open(meta_path) as f:
            return {**json.load(f), "cached": True}
    audio, summaries, lufs, key = render_sequence(scenes, xfade=xfade, seed=seed, key=key, target_lufs=target_lufs,
                                                  last_fade=fade_out, soundfont=soundfont)
    write_audio(path, audio)
    result = {"path": path, "format": format, "mime": MIME[format], "seed": seed, "key": key, "xfade": xfade,
              "duration": round(len(audio) / SR, 3), "samples": int(len(audio)), "sample_rate": SR,
              "lufs": None if lufs is None else round(lufs, 1), "scenes": summaries, "cached": False}
    with open(meta_path, "w") as f:
        json.dump(result, f, indent=1)
    return result


def mix_with_narration(narration_path: str, mood: str = "calm", *, lead_in: float = 1.5, tail_out: float = 3.0,
                       voice_lufs: float = -16.0, music_lufs: float = -26.0, duck_db: float = 9.0,
                       final_lufs: float = -16.0, seed: int | None = None, key: str | None = None,
                       mode: str | None = None, bpm: float | None = None, format: str = "wav",
                       soundfont: str | None = None, out_dir: str | None = None,
                       scenes: list | None = None, xfade: float = 2.0) -> dict:
    """Score a narration track: music is generated to fit it exactly, ducks under speech, fades after it.

    scenes=[{"mood":..., "duration":...}, ...] gives per-scene music; durations should add up to the narration
    length (within 1.5 s; the last scene absorbs the difference).  lead_in is added to the first scene and
    tail_out to the last."""
    format = format.lower().lstrip(".")
    voice = read_audio(narration_path)
    narr_s = len(voice) / SR
    total = lead_in + narr_s + tail_out
    seed = _new_seed(seed)
    if scenes:
        scenes = [dict(s) for s in _validate_scenes(scenes)]
        diff = narr_s - sum(s["duration"] for s in scenes)
        if abs(diff) > 1.5:
            raise ValueError(f"scene durations add up to {sum(s['duration'] for s in scenes):.1f}s but the "
                             f"narration is {narr_s:.1f}s; they should match within 1.5s")
        scenes[0]["duration"] += lead_in
        scenes[-1]["duration"] += tail_out + diff
        music, summaries, _, key = render_sequence(scenes, xfade=xfade, seed=seed, key=key,
                                                   last_fade=max(tail_out, 2.0), soundfont=soundfont)
        info = {"mood": "scenes", "seed": seed, "key": key, "scenes": summaries}
    else:
        plan = compose(mood, total, loop=False, seed=seed, key=key, mode=mode, bpm=bpm, fade_out=max(tail_out, 2.0))
        music = render_audio(plan, soundfont)
        info = plan.summary()
    mixed, stats = mix_voice_and_music(voice, music, lead_in=lead_in, tail_out=tail_out, voice_lufs=voice_lufs,
                                       music_lufs=music_lufs, duck_db=duck_db, final_lufs=final_lufs)
    d = _out_dir(out_dir)
    base = os.path.splitext(os.path.basename(narration_path))[0]
    path = os.path.join(d, f"{base}_scored_{info['mood']}_{seed}.{format}")
    write_audio(path, mixed)
    return {**info, "path": path, "format": format, "mime": MIME[format],
            "narration_seconds": round(narr_s, 2), "lead_in": lead_in, "tail_out": tail_out,
            "total_seconds": round(len(mixed) / SR, 3),
            **{k: (None if v is None else round(v, 2)) for k, v in stats.items()}}
