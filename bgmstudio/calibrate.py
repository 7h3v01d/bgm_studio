"""Per-SoundFont loudness calibration for the streaming endpoint.

Streaming can't measure a finished file, so it applies a fixed gain per mood.  How loud a mood is depends on the
SoundFont, so we measure it once per (SoundFont, mood) and cache it in ~/.bgmstudio/calibration.json
(override with BGM_CAL_FILE).  First stream for a new font+mood costs a few seconds; after that it's free.
"""
from __future__ import annotations

import json
import os
import threading

from .audio import measure_lufs
from .compose import compose
from .presets import PRESETS, resolve_mood
from .render import find_soundfont, render_audio

_lock = threading.Lock()


def _file() -> str:
    return os.path.expanduser(os.environ.get("BGM_CAL_FILE", "~/.bgmstudio/calibration.json"))


def _font_id(sf: str) -> str:
    return f"{os.path.basename(sf)}:{os.path.getsize(sf)}"


def _load() -> dict:
    try:
        with open(_file()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def get_cal(mood: str, soundfont: str | None = None) -> float:
    """Average un-normalised LUFS of this mood with this SoundFont (measured on first use)."""
    name, _ = resolve_mood(mood)
    sf = find_soundfont(soundfont)
    fid = _font_id(sf)
    with _lock:
        data = _load()
        if name in data.get(fid, {}):
            return data[fid][name]
        vals = [measure_lufs(render_audio(compose(name, 45, seed=s), sf)) for s in (1, 2, 3)]
        vals = [v for v in vals if v is not None]
        cal = round(sum(vals) / len(vals), 1) if vals else PRESETS[name]["cal"]
        data.setdefault(fid, {})[name] = cal
        try:
            os.makedirs(os.path.dirname(_file()), exist_ok=True)
            with open(_file(), "w") as f:
                json.dump(data, f, indent=1)
        except OSError:
            pass  # read-only home: still works, just recalibrates next run
        return cal


def calibrate_all(soundfont: str | None = None) -> dict:
    return {m: get_cal(m, soundfont) for m in PRESETS}
