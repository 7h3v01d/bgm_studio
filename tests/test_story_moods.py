# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""0.9: story moods (horror, sleep, folklore, suspense) and intensity (scalar or tension curve)."""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

from bgmstudio import service
from bgmstudio.api import app
from bgmstudio.audio import measure_lufs, normalize_lufs
from bgmstudio.cli import _parse_scenes
from bgmstudio.compose import CH_BASS, CH_DRUM, CH_MEL, CH_PAD, compose, parse_intensity
from bgmstudio.presets import ENERGY, PRESETS, resolve_mood
from bgmstudio.render import SR, render_audio

GOLDEN = os.path.join(os.path.dirname(__file__), "golden_notes_0_8.json")
STORY = ["horror", "sleep", "folklore", "suspense"]


def _fingerprint(plan) -> str:
    notes = [(round(n.start, 6), round(n.dur, 6), n.pitch, n.vel, n.ch) for n in plan.notes]
    return hashlib.sha256(repr(notes).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- nothing old changed
def test_original_moods_are_note_identical_to_0_8():
    """New preset options and intensity must not move a single note of the original eight moods."""
    with open(GOLDEN) as f:
        golden = json.load(f)
    for k, (h, bpm, key, mode) in golden.items():
        mood, seed, loop, d = k.split("|")
        p = compose(mood, float(d), seed=int(seed), loop=loop == "True")
        assert (_fingerprint(p), round(p.bpm, 4), p.key, p.mode) == (h, bpm, key, mode), k


def test_cache_name_includes_0101_engine_and_soundfont_digest(tmp_path):
    """0.10.1 intentionally migrates cache names to content-based identifiers."""
    r = service.generate_bgm("calm", 5, seed=3, out_dir=str(tmp_path))
    from bgmstudio.render import find_soundfont
    from bgmstudio.provenance import file_sha256
    sf = find_soundfont()
    params = dict(mood="calm", duration=5.0, loop=False, seed=3, key=None, mode=None, bpm=None, fmt="wav",
                  lufs=-20.0, fade=3.0, sf_sha256=file_sha256(sf))
    h = service._request_hash(params)
    assert os.path.basename(r["path"]) == f"bgm_calm_5s_3_{h}.wav"
    r2 = service.generate_bgm("calm", 5, seed=3, out_dir=str(tmp_path), intensity=0.5)
    assert r2["path"] != r["path"]


# ---------------------------------------------------------------- the story moods
def test_story_moods_listed_with_energy():
    moods = service.moods()
    for m in STORY:
        assert m in moods and m in ENERGY


@pytest.mark.parametrize("alias,mood", [("creepypasta", "horror"), ("scary", "horror"), ("bedtime", "sleep"),
                                        ("sleep_story", "sleep"), ("myth", "folklore"), ("legend", "folklore"),
                                        ("tension", "suspense"), ("thriller", "suspense"),
                                        ("alt-history", "cinematic"), ("true crime", "dark")])
def test_story_aliases(alias, mood):
    assert resolve_mood(alias)[0] == mood


def test_horror_has_drone_and_dissonance():
    p = compose("horror", 120, seed=2)
    bars_beats = 4.0 * 8
    drones = [n for n in p.notes if n.ch == CH_BASS and n.dur >= bars_beats - 0.01]
    assert len(drones) >= 2 * (len(p.sections) - 1), "a held root+fifth pedal under each section"
    starts = {}
    for n in p.notes:
        if n.ch == CH_PAD:
            starts.setdefault(round(n.start, 3), []).append(n.pitch % 12)
    clashes = sum(any((a - b) % 12 in (1, 11) for a in pcs for b in pcs if a != b) for pcs in starts.values())
    assert clashes >= 2, "pad chords should sometimes carry a minor-2nd clash"


def test_sleep_is_sparse_flat_and_drumless():
    p = compose("sleep", 600, seed=4)
    assert not any(n.ch == CH_DRUM for n in p.notes)
    assert not any(n.ch == CH_MEL for n in p.notes), "sleep never reaches a melody layer (max_level 2)"
    assert len(p.notes) / 10 < 90, "notes per minute"
    lo, hi = PRESETS["sleep"]["bpm"]
    assert lo - 3 <= p.bpm <= hi + 3


def test_suspense_heartbeat_and_folklore_frame_drum():
    sus = compose("suspense", 60, seed=1)
    kicks = sorted(round(n.start % 4.0, 2) for n in sus.notes if n.ch == CH_DRUM and n.pitch == 36)
    assert {0.0, 0.75} <= set(kicks), "lub-dub: kick on the beat and a 16th-dotted later"
    folk = compose("folklore", 60, seed=1)
    assert any(n.ch == CH_DRUM and n.pitch == 45 for n in folk.notes), "frame drum on low tom"


@pytest.mark.parametrize("mood", STORY)
def test_story_moods_render_clean(mood):
    a = render_audio(compose(mood, 20, seed=1))
    assert len(a) == 20 * SR and np.isfinite(a).all() and np.abs(a).max() < 0.99
    assert measure_lufs(a) > -45


# ---------------------------------------------------------------- intensity
@pytest.mark.parametrize("bad", [1.5, -0.1, [0.2, 2], [], "x", [0.5] * 65])
def test_parse_intensity_rejects(bad):
    with pytest.raises(ValueError, match="intensity"):
        parse_intensity(bad)


def test_parse_intensity_forms():
    assert parse_intensity(None) is None
    assert parse_intensity(0.3) == [0.3]
    assert parse_intensity("0.2, 0.8") == [0.2, 0.8]


@pytest.mark.parametrize("mood", ["horror", "cinematic", "folklore"])
def test_intensity_drives_busyness_and_tempo(mood):
    lo, hi = compose(mood, 120, seed=5, intensity=0.1), compose(mood, 120, seed=5, intensity=0.9)
    assert len(hi.notes) > 1.5 * len(lo.notes)
    assert hi.bpm > lo.bpm


def test_intensity_curve_sets_section_levels():
    p = compose("cinematic", 240, seed=5, intensity=[0.1, 0.1, 0.9, 0.9])
    a, _ = normalize_lufs(render_audio(p), -20)
    q = len(a) // 4
    assert measure_lufs(a[2 * q:3 * q]) - measure_lufs(a[:q]) >= 6.0
    s = p.summary()
    assert s["intensity"] == [0.1, 0.1, 0.9, 0.9] and len(s["section_intensity"]) == len(p.sections)


def test_loop_with_curve_stays_seamless():
    a = render_audio(compose("suspense", 120, seed=3, loop=True, intensity=[0.1, 0.9]))
    d = np.abs(np.diff(a, axis=0)).max(axis=1)
    assert np.abs(a[0] - a[-1]).max() < np.percentile(d, 99.9)


def test_sequence_intensity_levels_and_auto_transitions():
    scs = [{"mood": "folklore", "duration": 30, "intensity": 0.2}, {"mood": "folklore", "duration": 30, "intensity": 0.9},
           {"mood": "folklore", "duration": 30, "intensity": 0.2}]
    out, summ, _, _ = service.render_sequence(scs, seed=4, transitions="auto")
    n = 30 * SR
    lv = [measure_lufs(out[i * n + 3 * SR:(i + 1) * n - SR]) for i in range(3)]
    assert lv[1] - lv[0] >= 4.0 and lv[1] - lv[2] >= 4.0
    assert [s["transition_in"] for s in summ] == [None, "riser_impact", "downlifter"]


def test_sequence_scene_intensity_validated():
    with pytest.raises(ValueError, match="scene 2: intensity"):
        service.generate_sequence([{"mood": "calm", "duration": 10}, {"mood": "calm", "duration": 10, "intensity": 3}])


# ---------------------------------------------------------------- front ends
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "OUT_DIR", str(tmp_path))
    return TestClient(app, raise_server_exceptions=False)


def test_api_bgm_accepts_curve(client):
    r = client.post("/bgm?as_json=true", json={"mood": "creepypasta", "duration": 30, "seed": 1,
                                               "intensity": [0.2, 0.9]})
    assert r.status_code == 200, r.text
    assert r.json()["mood"] == "horror" and r.json()["intensity"] == [0.2, 0.9]


def test_api_rejects_bad_intensity(client):
    assert client.post("/bgm", json={"mood": "sleep", "duration": 10, "intensity": 1.5}).status_code == 422
    assert client.get("/bgm/stream", params={"mood": "sleep", "duration": 5, "intensity": "0.2,9"}).status_code == 422


def test_api_stream_accepts_curve(client):
    r = client.get("/bgm/stream", params={"mood": "suspense", "duration": 8, "intensity": "0.1,0.9", "seed": 2})
    assert r.status_code == 200 and len(r.content) == 44 + 8 * SR * 4


def test_api_sequence_scene_intensity(client):
    r = client.post("/sequence?as_json=true", json={"scenes": [{"mood": "sleep", "duration": 10, "intensity": 0.1},
                                                               {"mood": "horror", "duration": 10, "intensity": 0.9}],
                                                    "transitions": "auto", "seed": 1})
    assert r.status_code == 200, r.text
    assert r.json()["scenes"][1]["transition_in"] == "riser_impact"


def test_cli_scene_intensity():
    assert _parse_scenes("sleep:60:0.1,horror:45") == [{"mood": "sleep", "duration": 60.0, "intensity": 0.1},
                                                       {"mood": "horror", "duration": 45.0}]


def test_mcp_tools_take_intensity():
    import inspect
    from bgmstudio import mcp_server
    for tool in (mcp_server.generate_bgm, mcp_server.mix_with_narration):
        fn = getattr(tool, "fn", tool)
        assert "intensity" in inspect.signature(fn).parameters


def test_loop_envelope_returns_to_start_level():
    """A loop whose curve ends high must ramp back to the first section's level before wrapping."""
    from bgmstudio.render import section_envelope
    p = compose("suspense", 120, seed=3, loop=True, intensity=[0.1, 0.9])
    env = section_envelope(p)
    total = int(round(p.duration * SR))
    first, last = env(0, 1)[0], env(total - 1, 1)[0]
    peak = env(0, total).max()
    assert abs(20 * np.log10(last / first)) < 0.1 and peak / first > 1.5
