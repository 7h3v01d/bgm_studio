# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""Core operations shared by the REST API, the MCP server and the CLI."""
from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import time
import threading
from contextlib import contextmanager

import numpy as np

from . import __version__, provenance
from .audio import (MIME, audio_duration, loudness_gain, measure_lufs, mix_voice_and_music, normalize_lufs,
                    read_audio, write_audio, write_json)
from .cues import merge as merge_cues, plan_cues, track_cues
from .compose import INTENSITY_SPAN_DB, parse_intensity, MIN_SECONDS, NOTE_NAMES, Plan, compose, export_midi, fit_bars, parse_key
from .calibrate import get_cal
from .fx import TRANSITIONS, apply_transition, swell_curve
from .presets import ENERGY, describe_moods, resolve_mood
from .render import SR, find_soundfont, render_audio, render_split, stem_plans, stream_wav

OUT_DIR = os.path.abspath(os.environ.get("BGM_OUT_DIR", "bgm_out"))

# Valid ranges, shared by the REST API, MCP tools, CLI and library callers.  (lo, hi) inclusive.
LIMITS = {
    "target_lufs": (-40.0, -8.0), "music_lufs": (-40.0, -8.0), "final_lufs": (-40.0, -8.0),
    "voice_lufs": (-40.0, -8.0), "fade_out": (0.0, 30.0), "lead_in": (0.0, 30.0), "tail_out": (0.0, 60.0),
    "duck_db": (0.0, 40.0), "xfade": (0.0, 10.0), "max_bpm_jump": (0.0, 40.0), "fx_level_db": (-24.0, 6.0),
    "bpm": (40.0, 200.0),
}


def check_ranges(**values) -> None:
    """Raise ValueError naming the first argument outside LIMITS.  None values are skipped (= use default)."""
    for name, v in values.items():
        if v is None:
            continue
        lo, hi = LIMITS[name]
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a number, got {v!r}") from None
        if not (lo <= f <= hi):
            raise ValueError(f"{name} must be between {lo:g} and {hi:g}, got {f:g}")


# Process memory is dominated by multiple float32 stereo buffers (352,800 bytes/s each).
# Defaults keep ordinary desktop machines safe; operators can explicitly tune these budgets.
MAX_RENDER_SECONDS = float(os.environ.get("BGM_MAX_RENDER_SECONDS", "7200"))  # the documented 2-hour limit
MAX_SCENES = int(os.environ.get("BGM_MAX_SCENES", "100"))
MAX_NARRATION_BYTES = int(os.environ.get("BGM_MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))
# Conservative *estimate*, not an OS memory reservation. Lower on memory-constrained hosts.
# Float32 stereo PCM takes SR * 2 channels * 4 bytes per second; each algorithm can hold
# multiple simultaneous full-length arrays. Counts below deliberately include headroom.
MAX_RENDER_MEMORY_MIB = int(os.environ.get("BGM_MAX_RENDER_MEMORY_MIB", "16384"))
MAX_STEM_SECONDS = 3600.0  # stems hold ~3 full-length buffers in memory (about 1.3 GB each per hour of audio)


def _check_budget(seconds: float, *, scenes: int = 1, buffers: int = 3) -> None:
    if not np.isfinite(seconds) or seconds < MIN_SECONDS:
        raise ValueError(f"duration must be finite and at least {MIN_SECONDS}s")
    if seconds > MAX_RENDER_SECONDS:
        raise ValueError(f"total duration exceeds render budget ({MAX_RENDER_SECONDS:g}s)")
    if scenes > MAX_SCENES:
        raise ValueError(f"scene count exceeds budget ({MAX_SCENES})")
    # Enforce an operator-controlled admission budget *before* allocating large arrays.
    # This estimates buffers for each call path; actual peak memory remains platform-dependent.
    if buffers < 1:
        raise ValueError("buffer estimate must be positive")
    estimated_mib = seconds * SR * 2 * 4 * buffers / (1024 * 1024)
    if estimated_mib > MAX_RENDER_MEMORY_MIB:
        raise ValueError(f"estimated render memory {estimated_mib:.0f} MiB exceeds budget "
                         f"({MAX_RENDER_MEMORY_MIB} MiB); lower duration or adjust BGM_MAX_RENDER_MEMORY_MIB")


# Bump when a change alters the audio produced for the same request (composer, renderer, mixing, fx).  Cache names
# depend on this, not on the package version, so releases that don't change the sound keep their cache.
ENGINE_REVISION = 1


def _request_hash(params: dict) -> str:
    """Content-derived output identity: every audible option and the engine revision participate."""
    return hashlib.sha256(json.dumps({"engine": ENGINE_REVISION, **params}, sort_keys=True,
                                     separators=(",", ":"), default=str).encode()).hexdigest()[:20]


def _stem_path(path: str, name: str) -> str:
    root, ext = os.path.splitext(path)
    return f"{root}.stem-{name}{ext}"


def _check_stems(stems: bool, seconds: float) -> None:
    if stems and seconds > MAX_STEM_SECONDS:
        raise ValueError(f"stems are limited to {MAX_STEM_SECONDS / 60:.0f} minutes per file "
                         f"(asked for {seconds / 60:.1f}); render the long bed without stems")


def _meta_complete(meta: dict, *, stems: bool, midi_path: str | None = None, expected_path: str | None = None) -> bool:
    """Fail closed when cached outputs do not match their recorded content hashes."""
    if "cues" not in meta or "provenance" not in meta:
        return False
    if expected_path is not None and os.path.realpath(meta.get("path", "")) != os.path.realpath(expected_path):
        return False
    outputs = meta["provenance"].get("outputs", {})
    expected = {"main"}
    if stems:
        if not meta.get("stems"):
            return False
        expected.update(f"stem-{k}" for k in meta["stems"])
    if midi_path:
        expected.add("midi")
    if not expected.issubset(outputs):
        return False
    directory = os.path.dirname(os.path.abspath(expected_path or meta.get("path", "")))
    main_path = os.path.abspath(expected_path or meta["path"])
    for name in expected:
        entry = outputs[name]
        filename = entry.get("file", "")
        if not filename or os.path.basename(filename) != filename:
            return False
        path = os.path.join(directory, filename)
        required_path = (main_path if name == "main" else
                         midi_path if name == "midi" else
                         _stem_path(main_path, name[len("stem-"):]))
        if os.path.normcase(os.path.abspath(path)) != os.path.normcase(os.path.abspath(required_path)):
            return False
        if not os.path.isfile(path) or os.path.getsize(path) != entry.get("bytes"):
            return False
        if provenance.cached_sha256(path) != entry.get("sha256"):
            return False
    return True


def _cached_result(meta_path: str, path: str, **want):
    """The cached result for `path` if its record and files check out, else None.  Safe without the render lock:
    files are only ever replaced atomically, and a half-finished entry has no record yet."""
    if not (os.path.isfile(path) and os.path.isfile(meta_path)):
        return None
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        if _meta_complete(meta, expected_path=path, **want):
            return {**meta, "cached": True}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


# Single-worker serialisation avoids uncontrolled concurrent float32 render buffers.
# A durable per-directory OS file lock also coordinates independent CLI/API processes.
_render_mutex = threading.RLock()


@contextmanager
def _render_lock(path: str):
    with _render_mutex:
        lock_path = os.path.join(os.path.dirname(os.path.abspath(path)), ".bgmstudio.render.lock")
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        with open(lock_path, "a+b") as lock_file:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt
                deadline = time.monotonic() + float(os.environ.get("BGM_LOCK_TIMEOUT", "600"))
                while True:
                    try:
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("timed out waiting for BGM output directory lock")
                        time.sleep(0.1)
                try:
                    yield
                finally:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                deadline = time.monotonic() + float(os.environ.get("BGM_LOCK_TIMEOUT", "600"))
                while True:
                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("timed out waiting for BGM output directory lock")
                        time.sleep(0.1)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _out_dir(d=None) -> str:
    p = os.path.abspath(d or OUT_DIR)
    os.makedirs(p, exist_ok=True)
    return p


def moods() -> dict:
    return describe_moods()


def _new_seed(seed):
    return int(seed) if seed is not None else random.SystemRandom().randrange(1, 2**31 - 1)


def render_music(mood: str, duration: float, *, loop=False, seed=None, key=None, mode=None, bpm=None,
                 fade_out=3.0, target_lufs=-20.0, soundfont=None, intensity=None, split=False):
    """-> (float32 stereo array, Plan, achieved LUFS, applied linear gain).  Exactly round(duration*SR) samples."""
    _check_budget(float(duration))
    plan = compose(mood, duration, loop=loop, seed=_new_seed(seed), key=key, mode=mode, bpm=bpm,
                   fade_out=fade_out, intensity=intensity)
    raw = render_split(plan, soundfont) if split else render_audio(plan, soundfont)
    gain, lufs = loudness_gain(raw, target_lufs)
    audio = raw if lufs is None else (raw * gain).astype(np.float32)
    return audio, plan, lufs, gain


def generate_bgm(mood: str = "calm", duration: float = 60.0, *, loop: bool = False, seed: int | None = None,
                 key: str | None = None, mode: str | None = None, bpm: float | None = None,
                 format: str = "wav", target_lufs: float = -20.0, fade_out: float = 3.0,
                 soundfont: str | None = None, out_dir: str | None = None, midi: bool = False,
                 use_cache: bool = True, intensity=None, stems: bool = False) -> dict:
    """Generate a background-music file of exactly `duration` seconds.

    loop=True  -> sample-seamless loop (no fade, tail folded onto the start).
    loop=False -> proper cadence ending plus a fade-out.
    intensity  0..1, or a list of 0..1 points spread evenly across the track (a tension curve).
    stems      also write one file per instrument group (pad, bass, keys, melody, sparkle, drums); the main file is
               built from them, so they add up to it exactly.  Paths in result["stems"].  A stems render can differ
               from a plain render of the same seed in the first milliseconds of some notes (see render_split).
    Every result has "cues" (bars, sections; see cues.py) and "provenance" (see provenance.py), and the same
    record is saved next to the audio as <file>.json ("meta_path").
    The same (mood, duration, seed, ...) always gives the same music; the seed is returned.
    """
    format = format.lower().lstrip(".")
    if format not in MIME:
        raise ValueError(f"format must be one of {', '.join(MIME)}")
    check_ranges(target_lufs=target_lufs, fade_out=fade_out, bpm=bpm)
    intensity = parse_intensity(intensity)
    _check_budget(float(duration), buffers=5 if stems else 3)
    _check_stems(stems, float(duration))
    mood = resolve_mood(mood)[0]  # canonical name: aliases share one cache entry, and nothing unvalidated
    seed = _new_seed(seed)        # ever reaches a file name
    sf_path = find_soundfont(soundfont)  # SoundFont content hash participates in the cache key
    params = dict(mood=mood, duration=float(duration), loop=loop, seed=seed, key=key, mode=mode, bpm=bpm,
                  fmt=format, lufs=target_lufs, fade=fade_out, sf_sha256=provenance.cached_sha256(sf_path))
    if intensity is not None:  # only when used, so files cached without intensity keep their names
        params["intensity"] = intensity
    if stems:  # a stems render builds its mix from the stems, so it is its own cache entry (see render_split)
        params["stems"] = True
    h = _request_hash(params)
    d = _out_dir(out_dir)
    stem = f"bgm_{params['mood'].lower()}_{int(duration)}s{'_loop' if loop else ''}_{seed}_{h}"
    path, meta_path, mid_path = (os.path.join(d, stem + ext) for ext in (f".{format}", ".json", ".mid"))
    want = dict(stems=stems, midi_path=mid_path if midi else None)
    if use_cache and (hit := _cached_result(meta_path, path, **want)):
        return hit  # fast path: cache hits don't queue behind renders
    with _render_lock(path):
        if use_cache and (hit := _cached_result(meta_path, path, **want)):
            return hit  # rendered by whoever held the lock before us

        audio, plan, lufs, gain = render_music(mood, duration, loop=loop, seed=seed, key=key, mode=mode, bpm=bpm,
                                               fade_out=fade_out, target_lufs=target_lufs, soundfont=soundfont,
                                               intensity=intensity, split=stems)
        write_audio(path, audio)
        n_samples = int(len(audio))
        del audio
        outputs = {"main": path}
        stem_paths = {}
        if stems:
            for name, sp in stem_plans(plan).items():
                a = render_audio(sp, soundfont)
                a *= np.float32(gain)
                stem_paths[name] = write_audio(_stem_path(path, name), a)
                del a
            outputs.update({f"stem-{k}": v for k, v in stem_paths.items()})
        result = {**plan.summary(), "path": path, "format": format, "mime": MIME[format],
                  "lufs": None if lufs is None else round(lufs, 1), "samples": n_samples,
                  "sample_rate": SR, "cached": False, "meta_path": meta_path, "cues": track_cues(plan)}
        if stem_paths:
            result["stems"] = stem_paths
        if midi:
            result["midi_path"] = outputs["midi"] = export_midi(plan, mid_path)
        request = {k: v for k, v in params.items() if k != "sf_sha256"}
        result["provenance"] = provenance.build("track", request, seed, sf_path, outputs)
        write_json(meta_path, result)  # written last: its presence marks a complete cache entry
        return result


def stream_bgm(mood: str, duration: float, *, seed=None, key=None, mode=None, bpm=None,
               target_lufs: float = -20.0, fade_out: float = 3.0, soundfont=None, intensity=None):
    """-> (plan, content_length, iterator of WAV bytes).  Non-loop; static per-mood gain (no look-ahead)."""
    check_ranges(target_lufs=target_lufs, fade_out=fade_out, bpm=bpm)
    _check_budget(float(duration))
    plan = compose(mood, duration, loop=False, seed=_new_seed(seed), key=key, mode=mode, bpm=bpm,
                   fade_out=fade_out, intensity=intensity)
    length, it = stream_wav(plan, gain_db=target_lufs - get_cal(plan.mood, soundfont), soundfont=soundfont)
    return plan, length, it


def _validate_scenes(scenes) -> list:
    if not isinstance(scenes, (list, tuple)) or not scenes:
        raise ValueError("scenes must be a non-empty list of {mood, duration}")
    if len(scenes) > MAX_SCENES:
        raise ValueError(f"scene count exceeds budget ({MAX_SCENES})")
    out = []
    for i, sc in enumerate(scenes):
        if not isinstance(sc, dict) or "mood" not in sc or "duration" not in sc:
            raise ValueError(f"scene {i + 1}: needs 'mood' and 'duration'")
        try:
            d = float(sc["duration"])
        except (TypeError, ValueError):
            raise ValueError(f"scene {i + 1}: duration must be a number, got {sc['duration']!r}") from None
        check_ranges(bpm=sc.get("bpm"))
        if not np.isfinite(d) or d < MIN_SECONDS:
            raise ValueError(f"scene {i + 1}: duration must be at least {MIN_SECONDS}s")
        resolve_mood(sc["mood"])
        try:
            inten = parse_intensity(sc.get("intensity"))
        except ValueError as e:
            raise ValueError(f"scene {i + 1}: {e}") from None
        item = {**sc, "duration": d}
        if inten is None:
            item.pop("intensity", None)
        else:
            item["intensity"] = inten
        out.append(item)
    return out


def _tdist(a: float, b: float) -> float:
    """Tempo distance in BPM, counting a 2:1 ratio as the same pulse (62 vs 124 BPM feel locked together)."""
    return min(abs(a - b), abs(a - 2 * b), abs(2 * a - b))


def plan_tempos(items: list, max_jump: float) -> list:
    """items: [{"mood", "dur" (rendered seconds), "bpm" (fixed or None)}] -> target BPM per scene.

    Dynamic programming: each scene keeps close to its mood's natural tempo range, while the *fitted* tempos
    (after snapping to whole bars) of neighbouring scenes stay within `max_jump` BPM wherever that is possible."""
    cands = []
    for it in items:
        lo, hi = resolve_mood(it["mood"])[1]["bpm"]
        targets = [float(it["bpm"])] if it.get("bpm") else [float(x) for x in np.arange(max(40.0, lo - 14), hi + 14.01, 1.0)]
        seen, row = set(), []
        for t in targets:
            actual = fit_bars(it["dur"], t, it.get("grain", 4))[1]
            if round(actual, 2) in seen:
                continue
            seen.add(round(actual, 2))
            cost = 0.0 if it.get("bpm") else 1.5 * max(lo - actual, actual - hi, 0.0) + 0.15 * abs(actual - (lo + hi) / 2)
            row.append((t, actual, cost))
        cands.append(row)
    best, back = [[c[2] for c in cands[0]]], []
    for i in range(1, len(cands)):
        cur, bp = [], []
        for _, a, c in cands[i]:
            v, j = min((best[-1][k] + 30.0 * max(0.0, _tdist(pa, a) - max_jump) + 0.4 * _tdist(pa, a), k)
                       for k, (_, pa, _) in enumerate(cands[i - 1]))
            cur.append(v + c)
            bp.append(j)
        best.append(cur)
        back.append(bp)
    j = int(np.argmin(best[-1]))
    path = [j]
    for bp in reversed(back):
        j = bp[j]
        path.append(j)
    path.reverse()
    return [cands[i][path[i]][0] for i in range(len(cands))]


def _mean(curve) -> float:
    return sum(curve) / len(curve)


def scene_energy(scene: dict) -> float:
    """Mood energy (0-4), shifted by the scene's intensity if it has one (0.5 = no shift, 0/1 = -2/+2)."""
    e = float(ENERGY[resolve_mood(scene["mood"])[0]])
    if scene.get("intensity") is not None:
        e += 4.0 * (_mean(scene["intensity"]) - 0.5)
    return e


def _resolve_transition(name: str, prev_scene: dict, scene: dict) -> str:
    if name != "auto":
        return name
    delta = scene_energy(scene) - scene_energy(prev_scene)
    return ("riser_impact" if delta >= 1.5 else "riser" if delta >= 0.5 else "swell" if delta > -0.5
            else "downlifter")


def render_sequence(scenes: list, *, xfade: float = 2.0, seed: int | None = None, key: str | None = None,
                    target_lufs: float = -20.0, last_fade: float = 3.0, soundfont: str | None = None,
                    tempo_match: bool = True, max_bpm_jump: float = 6.0, transitions: str = "none",
                    fx_level_db: float = -3.0):
    """One continuous track from per-scene moods.  Scene i starts (downbeat) exactly at the sum of the previous
    durations; consecutive scenes share a key and crossfade (equal-power) over `xfade` seconds *after* the cut.
    Total length = sum of durations, exactly.

    tempo_match   choose tempos so neighbouring scenes sit within `max_bpm_jump` BPM (2:1 counts as matched).
    transitions   none | riser | impact | riser_impact | downlifter | swell | auto  (default for every cut; a scene's
                  own "transition" key overrides the cut *into* that scene).  auto = by mood energy change.
    fx_level_db   transition loudness relative to the surrounding music.
    -> (audio, [per-scene summary], LUFS, key)"""
    validated = _validate_scenes(scenes)
    _check_budget(sum(sc["duration"] for sc in validated), scenes=len(validated), buffers=4)
    parts = _sequence_parts(validated, xfade=xfade, seed=seed, key=key, target_lufs=target_lufs, last_fade=last_fade,
                            soundfont=soundfont, tempo_match=tempo_match, max_bpm_jump=max_bpm_jump,
                            transitions=transitions, fx_level_db=fx_level_db)
    out, lufs = normalize_lufs(parts["music"], target_lufs)
    return out, parts["summaries"], lufs, parts["key"]


def _sequence_parts(scenes: list, *, xfade, seed, key, target_lufs, last_fade, soundfont, tempo_match,
                    max_bpm_jump, transitions, fx_level_db, separate_fx: bool = False, split: bool = False) -> dict:
    """The work behind render_sequence, before the final loudness gain.

    -> {"music": scenes (+ transitions unless separate_fx), "fx": transitions or None, "summaries", "key",
        "cues": cue sheet, and what sequence_stems() needs to rebuild any instrument group on the same timeline}"""
    scenes = _validate_scenes(scenes)
    for name in [transitions] + [sc.get("transition") for sc in scenes]:
        if name is not None and name not in TRANSITIONS:
            raise ValueError(f"unknown transition {name!r}; choose from {', '.join(TRANSITIONS)}")
    n = len(scenes)
    xfade = max(0.0, min(float(xfade), min(s["duration"] for s in scenes) / 2))
    base = _new_seed(seed)
    if key is None:
        pools = [set(resolve_mood(s["mood"])[1]["key_pcs"]) for s in scenes]
        common = set.intersection(*pools) or pools[0]
        key = NOTE_NAMES[random.Random(f"{base}:key").choice(sorted(common))]
    key_pc = parse_key(key)
    render_d = [sc["duration"] + (0.0 if i == n - 1 else xfade) for i, sc in enumerate(scenes)]
    if tempo_match and n > 1:
        targets = plan_tempos([{"mood": sc["mood"], "dur": render_d[i], "bpm": sc.get("bpm"),
                                "grain": 4 if i == n - 1 else 1} for i, sc in enumerate(scenes)], max_bpm_jump)
    else:
        targets = [sc.get("bpm") for sc in scenes]
    total_n = int(round(sum(s["duration"] for s in scenes) * SR))
    xs = int(round(xfade * SR))
    fin = np.sin(np.linspace(0, np.pi / 2, xs, dtype=np.float32))[:, None] if xs > 1 else None
    fout = np.cos(np.linspace(0, np.pi / 2, xs, dtype=np.float32))[:, None] if xs > 1 else None
    out = np.zeros((total_n, 2), dtype=np.float32)
    fx = np.zeros_like(out) if separate_fx else None
    summaries, offsets, plans, gains, cue_parts, pos = [], [], [], [], [], 0.0
    for i, sc in enumerate(scenes):
        last = i == n - 1
        plan = compose(sc["mood"], render_d[i], loop=False,
                       seed=sc["seed"] if sc.get("seed") is not None else base + i * 7919, key=key,
                       mode=sc.get("mode"), bpm=sc.get("bpm") or targets[i], fade_out=last_fade if last else 0.0,
                       open_end=not last, intensity=sc.get("intensity"))
        raw = render_split(plan, soundfont) if split else render_audio(plan, soundfont)
        g, lufs_s = loudness_gain(raw, target_lufs)
        audio = raw if lufs_s is None else (raw * g).astype(np.float32)
        del raw
        if sc.get("intensity") is not None:  # scenes are levelled individually; intensity sets them apart again
            k = np.float32(10 ** (INTENSITY_SPAN_DB * (_mean(sc["intensity"]) - 0.5) / 20.0))
            audio *= k
            g *= float(k)
        _place(out, audio, int(round(pos * SR)), i, n, fin, fout, xs)
        off = int(round(pos * SR))
        offsets.append(off)
        plans.append(plan)
        gains.append(g)
        cue_parts.append(plan_cues(plan, offset=pos, length=sc["duration"], scene=i + 1))
        info = {**plan.summary(), "scene": i + 1, "start": round(pos, 3), "duration": sc["duration"],
                "transition_in": None}
        if i > 0:
            jump = _tdist(summaries[-1]["bpm"], info["bpm"])
            info["bpm_jump_from_prev"] = round(jump, 2)
            if tempo_match and jump > max_bpm_jump + 0.5:
                info["tempo_warning"] = (f"{summaries[-1]['mood']} -> {sc['mood']} could not be brought within "
                                         f"{max_bpm_jump} BPM at these scene lengths")
        summaries.append(info)
        pos += sc["duration"]
    swells, cue_tr = [], []
    for i in range(1, n):
        name = _resolve_transition(scenes[i].get("transition") or transitions, scenes[i - 1], scenes[i])
        summaries[i]["transition_in"] = name
        if name != "none":
            apply_transition(out, name, offsets[i], SR, seed=base + i * 131, key_pc=key_pc, level_db=fx_level_db,
                             prev_len=scenes[i - 1]["duration"], next_len=scenes[i]["duration"], fx_out=fx)
            cue_tr.append({"time": round(offsets[i] / SR, 4), "type": name, "scene": i + 1})
            if name == "swell":
                swells.append(offsets[i])
    return {"music": out, "fx": fx, "summaries": summaries, "key": key, "plans": plans, "gains": gains,
            "offsets": offsets, "swells": swells, "total_n": total_n, "xs": xs, "fin": fin, "fout": fout,
            "cues": merge_cues(cue_parts, total_n / SR, cue_tr)}


def _place(out, audio, off, i, n, fin, fout, xs) -> None:
    """Crossfade a scene's audio and add it at sample `off` (in place on `audio` and `out`)."""
    if fin is not None:
        if i > 0:
            audio[:xs] *= fin
        if i < n - 1:
            audio[-xs:] *= fout
    seg = audio[:max(0, len(out) - off)]
    out[off:off + len(seg)] += seg


def sequence_stems(parts: dict, soundfont: str | None, gain: float):
    """Yield (stem name, audio) for each instrument group, on the sequence timeline, already scaled by `gain` so
    the stems plus the fx stem add up to the delivered file.  One full-length buffer at a time."""
    names = []
    for plan in parts["plans"]:
        names += [k for k in stem_plans(plan) if k not in names]
    n = len(parts["plans"])
    for name in names:
        buf = np.zeros((parts["total_n"], 2), dtype=np.float32)
        for i, plan in enumerate(parts["plans"]):
            sp = stem_plans(plan).get(name)
            if sp is None:
                continue
            a = render_audio(sp, soundfont)
            a *= np.float32(parts["gains"][i])
            _place(buf, a, parts["offsets"][i], i, n, parts["fin"], parts["fout"], parts["xs"])
        for cut in parts["swells"]:
            buf *= swell_curve(len(buf), cut, SR)[:, None]
        buf *= np.float32(gain)
        yield name, buf
        del buf


def generate_sequence(scenes: list, *, xfade: float = 2.0, seed: int | None = None, key: str | None = None,
                      format: str = "wav", target_lufs: float = -20.0, fade_out: float = 3.0,
                      soundfont: str | None = None, out_dir: str | None = None, tempo_match: bool = True,
                      max_bpm_jump: float = 6.0, transitions: str = "none", fx_level_db: float = -3.0,
                      stems: bool = False) -> dict:
    """Per-scene background music as a single file (see render_sequence).
    stems=True also writes one file per instrument group plus "fx" (the transitions); the main file is built from
    them, so they add up to it exactly (and it is its own cache entry; see render_split)."""
    format = format.lower().lstrip(".")
    if format not in MIME:
        raise ValueError(f"format must be one of {', '.join(MIME)}")
    check_ranges(xfade=xfade, target_lufs=target_lufs, fade_out=fade_out, max_bpm_jump=max_bpm_jump,
                 fx_level_db=fx_level_db)
    scenes = [{**s, "mood": resolve_mood(s["mood"])[0]} for s in _validate_scenes(scenes)]
    _check_budget(sum(s["duration"] for s in scenes), scenes=len(scenes), buffers=6 if stems else 4)
    _check_stems(stems, sum(s["duration"] for s in scenes))
    seed = _new_seed(seed)
    sf_path = find_soundfont(soundfont)
    params = dict(scenes=scenes, xfade=xfade, seed=seed, key=key, fmt=format, lufs=target_lufs, fade=fade_out,
                  tm=tempo_match, jump=max_bpm_jump, tr=transitions, fx=fx_level_db,
                  sf_sha256=provenance.cached_sha256(sf_path))
    if stems:
        params["stems"] = True
    h = _request_hash(params)
    d = _out_dir(out_dir)
    stem = f"seq_{len(scenes)}scenes_{int(sum(s['duration'] for s in scenes))}s_{seed}_{h}"
    path, meta_path = os.path.join(d, f"{stem}.{format}"), os.path.join(d, f"{stem}.json")
    if hit := _cached_result(meta_path, path, stems=stems):
        return hit
    with _render_lock(path):
        if hit := _cached_result(meta_path, path, stems=stems):
            return hit
        parts = _sequence_parts(scenes, xfade=xfade, seed=seed, key=key, target_lufs=target_lufs,
                                last_fade=fade_out, soundfont=soundfont, tempo_match=tempo_match,
                                max_bpm_jump=max_bpm_jump, transitions=transitions, fx_level_db=fx_level_db,
                                separate_fx=stems, split=stems)
        mix = parts["music"] if parts["fx"] is None else parts["music"] + parts["fx"]
        gain, lufs = loudness_gain(mix, target_lufs)
        audio = mix if lufs is None else (mix * gain).astype(np.float32)
        write_audio(path, audio)
        n_samples = int(len(audio))
        del audio, mix
        outputs, stem_paths = {"main": path}, {}
        if stems:
            parts["music"] = None  # free it before the stem passes
            for name, buf in sequence_stems(parts, soundfont, gain):
                stem_paths[name] = write_audio(_stem_path(path, name), buf)
            fxa = parts["fx"]
            fxa *= np.float32(gain)
            stem_paths["fx"] = write_audio(_stem_path(path, "fx"), fxa)
            outputs.update({f"stem-{k}": v for k, v in stem_paths.items()})
        result = {"path": path, "format": format, "mime": MIME[format], "seed": seed, "key": parts["key"],
                  "xfade": xfade, "duration": round(n_samples / SR, 3), "samples": n_samples, "sample_rate": SR,
                  "lufs": None if lufs is None else round(lufs, 1), "scenes": parts["summaries"], "cached": False,
                  "meta_path": meta_path, "cues": parts["cues"]}
        if stem_paths:
            result["stems"] = stem_paths
        request = {k: v for k, v in params.items() if k != "sf_sha256"}
        result["provenance"] = provenance.build("sequence", request, seed, sf_path, outputs)
        write_json(meta_path, result)
        return result


def mix_with_narration(narration_path: str, mood: str = "calm", *, lead_in: float = 1.5, tail_out: float = 3.0,
                       voice_lufs: float = -16.0, music_lufs: float = -26.0, duck_db: float = 9.0,
                       final_lufs: float = -16.0, seed: int | None = None, key: str | None = None,
                       mode: str | None = None, bpm: float | None = None, format: str = "wav",
                       soundfont: str | None = None, out_dir: str | None = None,
                       scenes: list | None = None, xfade: float = 2.0, tempo_match: bool = True,
                       max_bpm_jump: float = 6.0, transitions: str = "none", fx_level_db: float = -3.0,
                       intensity=None, stems: bool = False) -> dict:
    """Score a narration track: music is generated to fit it exactly, ducks under speech, fades after it.

    scenes=[{"mood":..., "duration":...}, ...] gives per-scene music; durations should add up to the narration
    length (within 1.5 s; the last scene absorbs the difference).  lead_in is added to the first scene and
    tail_out to the last.
    stems=True also writes voice / music / fx files (ducked, aligned) that add up to the mix.
    The result has "cues" (in mix time, with the narration's start and end) and "provenance"; both are also
    saved next to the mix as <file>.json ("meta_path")."""
    format = format.lower().lstrip(".")
    if format not in MIME:
        raise ValueError(f"format must be one of {', '.join(MIME)}")
    check_ranges(lead_in=lead_in, tail_out=tail_out, voice_lufs=voice_lufs, music_lufs=music_lufs,
                 duck_db=duck_db, final_lufs=final_lufs, bpm=bpm, xfade=xfade, max_bpm_jump=max_bpm_jump,
                 fx_level_db=fx_level_db)
    intensity = parse_intensity(intensity)
    sf_path = find_soundfont(soundfont)
    if not os.path.isfile(narration_path):
        raise FileNotFoundError(f"narration file not found: {narration_path}")
    if os.path.getsize(narration_path) > MAX_NARRATION_BYTES:
        raise ValueError(f"narration exceeds input byte budget ({MAX_NARRATION_BYTES} bytes)")
    # Probe before decoding so even a small compressed file cannot force an oversized
    # PCM allocation; include lead/tail and optional stems in the admission check.
    from .audio import audio_duration
    try:
        narr_probe_s = audio_duration(narration_path)
    except (subprocess.CalledProcessError, ValueError, OverflowError) as exc:
        # Invalid narration is a client-input error, not an internal server failure.
        # Keep the public message stable and avoid exposing ffprobe internals.
        raise ValueError(f"could not decode audio file {os.path.basename(narration_path)!r}: invalid media") from exc
    _check_budget(lead_in + narr_probe_s + tail_out, scenes=len(scenes) if scenes else 1,
                  buffers=7 if stems else 5)
    _check_stems(stems, lead_in + narr_probe_s + tail_out)
    voice = read_audio(narration_path)
    narr_s = len(voice) / SR
    total = lead_in + narr_s + tail_out
    _check_budget(total, scenes=len(scenes) if scenes else 1, buffers=7 if stems else 5)
    _check_stems(stems, total)
    seed = _new_seed(seed)
    # Preserve canonical original scenes, before lead-in/tail-out adjustments.
    identity_scenes = _validate_scenes(scenes) if scenes else None
    narration_sha = provenance.file_sha256(narration_path)
    request = {"narration": {"file": os.path.basename(narration_path), "sha256": narration_sha,
                             "seconds": round(narr_s, 3)},
               "mood": None if scenes else resolve_mood(mood)[0], "scenes": identity_scenes,
               "lead_in": lead_in, "tail_out": tail_out, "voice_lufs": voice_lufs,
               "music_lufs": music_lufs, "duck_db": duck_db, "final_lufs": final_lufs,
               "key": key, "mode": mode, "bpm": bpm, "xfade": xfade,
               "tempo_match": tempo_match, "max_bpm_jump": max_bpm_jump,
               "transitions": transitions, "fx_level_db": fx_level_db,
               "intensity": intensity, "fmt": format, "stems": stems,
               "soundfont_sha256": provenance.cached_sha256(sf_path), "seed": seed}
    d = _out_dir(out_dir)
    base = os.path.splitext(os.path.basename(narration_path))[0]
    # SoundFont and every output-affecting option are part of this destination.
    path = os.path.join(d, f"{base}_scored_{_request_hash(request)}.{format}")
    meta_path = os.path.splitext(path)[0] + ".json"
    if hit := _cached_result(meta_path, path, stems=stems):
        return hit
    with _render_lock(path):
        if hit := _cached_result(meta_path, path, stems=stems):
            return hit
        fx = None
        if scenes:
            scenes = [dict(s) for s in _validate_scenes(scenes)]
            diff = narr_s - sum(s["duration"] for s in scenes)
            if abs(diff) > 1.5:
                raise ValueError(f"scene durations add up to {sum(s['duration'] for s in scenes):.1f}s but the "
                                 f"narration is {narr_s:.1f}s; they should match within 1.5s")
            scenes[0]["duration"] += lead_in
            scenes[-1]["duration"] += tail_out + diff
            parts = _sequence_parts(scenes, xfade=xfade, seed=seed, key=key, target_lufs=-20.0,
                                    last_fade=max(tail_out, 2.0), soundfont=soundfont, tempo_match=tempo_match,
                                    max_bpm_jump=max_bpm_jump, transitions=transitions, fx_level_db=fx_level_db,
                                    separate_fx=stems)
            bed = parts["music"] if parts["fx"] is None else parts["music"] + parts["fx"]
            g_seq, _ = loudness_gain(bed, -20.0)  # same levelling render_sequence applies
            del bed
            music = (parts["music"] * g_seq).astype(np.float32)
            if parts["fx"] is not None:
                fx = (parts["fx"] * g_seq).astype(np.float32)
            key = parts["key"]
            info = {"mood": "scenes", "seed": seed, "key": key, "scenes": parts["summaries"]}
            cues = parts["cues"]
        else:
            plan = compose(mood, total, loop=False, seed=seed, key=key, mode=mode, bpm=bpm, fade_out=max(tail_out, 2.0),
                           intensity=intensity)
            music = render_audio(plan, soundfont)
            info = plan.summary()
            cues = track_cues(plan)
        mixed, stats, stem_audio = mix_voice_and_music(voice, music, lead_in=lead_in, tail_out=tail_out,
                                                       voice_lufs=voice_lufs, music_lufs=music_lufs, duck_db=duck_db,
                                                       final_lufs=final_lufs, fx=fx, stems=stems)
        del music, fx
        write_audio(path, mixed)
        outputs, stem_paths = {"main": path}, {}
        for name, a in (stem_audio or {}).items():
            stem_paths[name] = write_audio(_stem_path(path, name), a)
        del stem_audio
        outputs.update({f"stem-{k}": v for k, v in stem_paths.items()})
        cues = {**cues, "duration": round(len(mixed) / SR, 4),
                "narration": {"start": round(lead_in, 4), "end": round(lead_in + narr_s, 4)}}
        result = {**info, "path": path, "format": format, "mime": MIME[format],
                  "narration_seconds": round(narr_s, 2), "lead_in": lead_in, "tail_out": tail_out,
                  "total_seconds": round(len(mixed) / SR, 3), "meta_path": meta_path, "cues": cues,
                  **{k: (None if v is None else round(v, 2)) for k, v in stats.items()}}
        if stem_paths:
            result["stems"] = stem_paths
        result["provenance"] = provenance.build("mix", request, seed, sf_path, outputs)
        write_json(meta_path, result)
        return result
