# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""Cue sheets: where the bars, sections, scenes and transitions fall in a rendered file, in seconds.

Every result carries the same shape, whether it came from one track, a scene sequence or a narration mix:

    {"duration": 312.5, "time_signature": "4/4",
     "scenes":      [{"scene": 1, "mood": "horror", "start": 0.0, "end": 60.0, "bpm": 58.0, "beat_seconds": 1.0345}],
     "sections":    [{"scene": 1, "kind": "intro", "start": 0.0, "end": 33.1, "bars": 8, "intensity": 0.2}],
     "downbeats":   [0.0, 4.1379, ...],            # every bar line, in file time
     "transitions": [{"time": 60.0, "type": "riser_impact"}],
     "narration":   {"start": 1.5, "end": 301.5}}  # mixes only

Times are exact to the sample the renderer used (before the ±12 ms humanising of individual notes), so cuts,
chapter cards and captions placed on them land on the beat.
"""
from __future__ import annotations

from .compose import Plan


def _r(t: float) -> float:
    return round(t, 4)


def plan_cues(plan: Plan, *, offset: float = 0.0, length: float | None = None, scene: int = 1) -> dict:
    """Cues for one plan placed at `offset` seconds, cut off after `length` seconds (scenes in a sequence render
    a little past their cut for the crossfade; the next scene owns that time)."""
    length = plan.duration if length is None else length
    bar_s = 4 * 60.0 / plan.bpm
    downbeats = [_r(offset + b * bar_s) for b in range(plan.bars) if b * bar_s < length - 1e-6]
    sections = []
    for i, (kind, start_bar, n) in enumerate(plan.sections):
        start = start_bar * bar_s
        if start >= length - 1e-6:
            break
        end = min((start_bar + n) * bar_s, length)
        item = {"scene": scene, "kind": kind, "start": _r(offset + start), "end": _r(offset + end), "bars": n}
        if plan.section_intensity is not None:
            item["intensity"] = round(plan.section_intensity[i], 3)
        sections.append(item)
    sc = {"scene": scene, "mood": plan.mood, "start": _r(offset), "end": _r(offset + length),
          "bpm": round(plan.bpm, 3), "beat_seconds": round(60.0 / plan.bpm, 6), "key": f"{plan.key} {plan.mode}"}
    return {"scenes": [sc], "sections": sections, "downbeats": downbeats}


def merge(parts: list, duration: float, transitions: list | None = None) -> dict:
    out = {"duration": _r(duration), "time_signature": "4/4", "scenes": [], "sections": [], "downbeats": [],
           "transitions": transitions or []}
    for p in parts:
        for k in ("scenes", "sections", "downbeats"):
            out[k] += p[k]
    return out


def track_cues(plan: Plan) -> dict:
    return merge([plan_cues(plan)], plan.duration)


def summary(cues: dict) -> dict:
    """Same cue sheet without the per-bar list: small enough for an agent's context (MCP results)."""
    return {k: v for k, v in cues.items() if k != "downbeats"} | {"downbeat_count": len(cues["downbeats"])}
