# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""Scene-list logic for the sequencer tab.  No Qt imports, so it is testable without a display.

A scene row in the editor is a dict:
    {"mood": str, "duration": float, "intensity": float | None, "transition": str, "bpm": float | None}
where transition "default" means "use the sequence's default transition".  to_api() turns rows into the list the
REST API / bgm_client take.  Scene files use the same shape as the API ({"scenes": [...]}) plus the editor's
settings, so InkHeart or Reelwright can write one and the console can open it.
"""
from __future__ import annotations

import json
import math

# Mirrors bgmstudio.fx.TRANSITIONS (a test keeps them in step); the GUI never imports the engine.
TRANSITIONS = ("none", "riser", "impact", "riser_impact", "downlifter", "swell", "auto")
# Mirrors bgmstudio.presets.ENERGY (0 = barely there .. 4 = full-on); colours the scene bar.  Unknown moods = 2.
ENERGY = {"ambient": 0, "calm": 1, "lofi": 2, "dark": 3, "corporate": 3, "cinematic": 4, "uplifting": 4, "tech": 4,
          "sleep": 0, "horror": 1, "folklore": 2, "suspense": 3}
MIN_SCENE_SECONDS = 4.0
MAX_TOTAL_SECONDS = 7200.0
MAX_SCENES = 100
NARRATION_TOLERANCE = 1.5  # the service accepts scene totals within this of the narration length
FILE_TAG = "bgmstudio-scenes"
FILE_VERSION = 1

DEFAULT_SETTINGS = {"transitions": "auto", "xfade": 2.0, "tempo_match": True, "max_bpm_jump": 6.0,
                    "lead_in": 1.5, "tail_out": 3.0, "duck_db": 9.0}


def new_row(mood: str = "ambient", duration: float = 30.0) -> dict:
    return {"mood": mood, "duration": float(duration), "intensity": None, "transition": "default", "bpm": None}


def _num(value, name: str, i: int) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Scene {i}: {name} must be a number.") from None
    if not math.isfinite(f):
        raise ValueError(f"Scene {i}: {name} must be a finite number.")
    return f


def validate_rows(rows: list, moods) -> list:
    """Check editor rows; return clean copies.  Raises ValueError naming the scene and the problem."""
    if not rows:
        raise ValueError("Add at least one scene.")
    if len(rows) > MAX_SCENES:
        raise ValueError(f"At most {MAX_SCENES} scenes.")
    out, total = [], 0.0
    for i, r in enumerate(rows, 1):
        if r.get("mood") not in moods:
            raise ValueError(f"Scene {i}: choose a mood.")
        d = _num(r.get("duration"), "duration", i)
        if d < MIN_SCENE_SECONDS:
            raise ValueError(f"Scene {i}: duration must be at least {MIN_SCENE_SECONDS:g} s.")
        total += d
        inten = r.get("intensity")
        if inten is not None:
            inten = _num(inten, "intensity", i)
            if not 0.0 <= inten <= 1.0:
                raise ValueError(f"Scene {i}: intensity must be between 0 and 1.")
        tr = r.get("transition") or "default"
        if tr != "default" and tr not in TRANSITIONS:
            raise ValueError(f"Scene {i}: unknown transition {tr!r}.")
        bpm = r.get("bpm")
        if bpm is not None:
            bpm = _num(bpm, "BPM", i)
            if not 40.0 <= bpm <= 200.0:
                raise ValueError(f"Scene {i}: BPM must be between 40 and 200 (or auto).")
        out.append({"mood": r["mood"], "duration": d, "intensity": inten, "transition": tr, "bpm": bpm})
    if total > MAX_TOTAL_SECONDS:
        raise ValueError(f"Scenes add up to {total:.0f} s; the limit is {MAX_TOTAL_SECONDS:.0f} s (2 hours).")
    return out


def to_api(rows: list) -> list:
    """Editor rows -> the scenes list the API takes (unset fields left out; the first scene has no cut into it)."""
    out = []
    for i, r in enumerate(rows):
        sc = {"mood": r["mood"], "duration": round(float(r["duration"]), 3)}
        if r.get("intensity") is not None:
            sc["intensity"] = round(float(r["intensity"]), 3)
        if i > 0 and r.get("transition") not in (None, "default"):
            sc["transition"] = r["transition"]
        if r.get("bpm") is not None:
            sc["bpm"] = float(r["bpm"])
        out.append(sc)
    return out


def starts(durations: list) -> list:
    t, out = 0.0, []
    for d in durations:
        out.append(t)
        t += float(d)
    return out


def narration_fit(scene_total: float, narration_seconds: float | None) -> tuple[bool, str]:
    """Does the scene total match the narration closely enough for the service to accept it?"""
    if narration_seconds is None:
        return True, ""
    diff = scene_total - narration_seconds
    if abs(diff) <= NARRATION_TOLERANCE:
        return True, "scenes match the narration"
    return False, (f"scenes are {abs(diff):.1f} s {'longer' if diff > 0 else 'shorter'} than the narration "
                   f"(must be within {NARRATION_TOLERANCE:g} s): use FIT")


def fit_durations(durations: list, target: float) -> list:
    """Scale scene lengths proportionally so they add up to `target` exactly (0.1 s steps; the last scene absorbs
    rounding).  Raises ValueError if any scene would fall below the minimum."""
    durations = [float(d) for d in durations]
    if not durations:
        raise ValueError("Add at least one scene.")
    if target < MIN_SCENE_SECONDS * len(durations):
        raise ValueError(f"{len(durations)} scenes need at least {MIN_SCENE_SECONDS * len(durations):g} s; "
                         f"the narration is {target:.1f} s.")
    total = sum(durations)
    scaled = [round(d * target / total, 1) for d in durations[:-1]]
    scaled.append(round(target - sum(scaled), 3))
    short = [i + 1 for i, d in enumerate(scaled) if d < MIN_SCENE_SECONDS]
    if short:
        raise ValueError(f"Fitting would make scene {short[0]} shorter than {MIN_SCENE_SECONDS:g} s; "
                         "lengthen it or remove a scene first.")
    return scaled


def dump_scene_file(rows: list, settings: dict) -> str:
    return json.dumps({"format": FILE_TAG, "version": FILE_VERSION, "scenes": to_api(rows),
                       "settings": {k: settings[k] for k in DEFAULT_SETTINGS if k in settings}}, indent=2)


def load_scene_file(text: str, moods) -> tuple[list, dict]:
    """Accepts a saved scene file, the API's {"scenes": [...]} body, or a bare list of scenes.
    -> (editor rows, settings).  Unknown moods are rejected by name so a typo in a generated file is obvious."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError(f"Not a JSON scene file: {e}") from None
    if isinstance(data, list):
        scenes, settings = data, {}
    elif isinstance(data, dict) and isinstance(data.get("scenes"), list):
        scenes, settings = data["scenes"], data.get("settings") or {}
    else:
        raise ValueError('Expected {"scenes": [...]} or a list of scenes.')
    rows = []
    for i, sc in enumerate(scenes, 1):
        if not isinstance(sc, dict) or "mood" not in sc or "duration" not in sc:
            raise ValueError(f"Scene {i}: needs at least mood and duration.")
        mood = str(sc["mood"]).strip().lower()
        if mood not in moods:
            raise ValueError(f"Scene {i}: unknown mood {sc['mood']!r}.")
        inten = sc.get("intensity")
        if isinstance(inten, list):  # curves are valid in the API; the editor keeps one value per scene
            inten = sum(inten) / len(inten) if inten else None
        rows.append({"mood": mood, "duration": sc["duration"], "intensity": inten,
                     "transition": sc.get("transition") or "default", "bpm": sc.get("bpm")})
    rows = validate_rows(rows, moods)
    return rows, merge_settings(settings)


def merge_settings(settings: dict) -> dict:
    """Defaults overlaid with any well-typed values from `settings`; anything else is ignored."""
    clean = dict(DEFAULT_SETTINGS)
    for k, default in DEFAULT_SETTINGS.items():
        v = settings.get(k) if isinstance(settings, dict) else None
        if isinstance(default, bool):
            if isinstance(v, bool):
                clean[k] = v
        elif isinstance(default, float):
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                clean[k] = float(v)
        elif v in TRANSITIONS:
            clean[k] = v
    return clean


def result_summary(result: dict) -> dict:
    """What the output panel shows, for any result (track, sequence or narration mix)."""
    cues = result.get("cues") or {}
    scenes = cues.get("scenes") or []
    bpms = [float(s["bpm"]) for s in scenes if s.get("bpm")] or ([float(result["bpm"])] if result.get("bpm") else [])
    if not bpms:
        bpm = "—"
    elif max(bpms) - min(bpms) < 0.05:
        bpm = f"{bpms[0]:.1f}"
    else:
        bpm = f"{min(bpms):.0f}–{max(bpms):.0f}"
    key = result.get("key") or (scenes[0].get("key") if scenes else None) or "—"
    if len(scenes) > 1 and " " in key and not result.get("key"):
        key = key.split()[0]  # scenes share a root; modes differ per scene
    n_sec = len(cues.get("sections") or [])
    structure = (f"{len(scenes)} scenes · {n_sec} sect" if len(scenes) > 1 else f"{n_sec} sections") if n_sec else "—"
    length = float(result.get("duration") or result.get("total_seconds") or cues.get("duration") or 0)
    stems = result.get("stems") or {}
    return {"seed": str(result.get("seed", "—")), "bpm": bpm, "key": str(key), "length": length,
            "structure": structure, "stems": str(len(stems)) if stems else "none",
            "warnings": list(result.get("warnings") or []), "narration": cues.get("narration")}
