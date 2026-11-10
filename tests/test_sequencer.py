# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""Scene-list logic behind the console's SEQUENCE tab (no Qt needed)."""
import json

import pytest

from bgmgui.scenes import (DEFAULT_SETTINGS, ENERGY, TRANSITIONS, dump_scene_file, fit_durations, load_scene_file,
                           narration_fit, new_row, result_summary, starts, to_api, validate_rows)

MOODS = {"calm", "horror", "sleep", "suspense"}


def rows(*spec):
    return [new_row(m, d) for m, d in spec]


def test_engine_tables_stay_in_step():
    """The GUI mirrors these so it never imports the engine; this catches drift."""
    from bgmstudio.fx import TRANSITIONS as ENGINE_TR
    from bgmstudio.presets import ENERGY as ENGINE_ENERGY
    assert TRANSITIONS == ENGINE_TR and ENERGY == ENGINE_ENERGY


@pytest.mark.parametrize("bad,msg", [
    ({"mood": "jazz"}, "Scene 2: choose a mood"),
    ({"duration": 3.9}, "Scene 2: duration must be at least 4"),
    ({"duration": float("nan")}, "Scene 2: duration must be a finite"),
    ({"intensity": 1.2}, "Scene 2: intensity must be between 0 and 1"),
    ({"transition": "explode"}, "Scene 2: unknown transition"),
    ({"bpm": 250}, "Scene 2: BPM must be between 40 and 200"),
])
def test_validate_names_the_scene_and_problem(bad, msg):
    r = rows(("calm", 10), ("horror", 10))
    r[1].update(bad)
    with pytest.raises(ValueError, match=msg):
        validate_rows(r, MOODS)


def test_validate_limits():
    with pytest.raises(ValueError, match="at least one scene"):
        validate_rows([], MOODS)
    with pytest.raises(ValueError, match="limit is 7200"):
        validate_rows(rows(("calm", 3000), ("calm", 3000), ("calm", 1300)), MOODS)
    with pytest.raises(ValueError, match="At most 100"):
        validate_rows(rows(*[("calm", 4)] * 101), MOODS)


def test_to_api_leaves_out_unset_fields_and_the_first_cut():
    r = rows(("sleep", 20), ("horror", 15.5), ("calm", 10))
    r[0]["transition"] = "impact"          # no cut into the first scene: dropped
    r[1].update(intensity=0.8, transition="riser_impact", bpm=60)
    r[2]["transition"] = "default"         # default: use the sequence's setting -> dropped
    assert to_api(validate_rows(r, MOODS)) == [
        {"mood": "sleep", "duration": 20.0},
        {"mood": "horror", "duration": 15.5, "intensity": 0.8, "transition": "riser_impact", "bpm": 60.0},
        {"mood": "calm", "duration": 10.0}]


def test_starts():
    assert starts([10, 5.5, 4]) == [0.0, 10.0, 15.5]


def test_fit_scales_proportionally_and_sums_exactly():
    fitted = fit_durations([40, 25.5, 30], 101.3)
    assert sum(fitted) == pytest.approx(101.3, abs=1e-9)
    assert fitted[0] / fitted[1] == pytest.approx(40 / 25.5, rel=0.01)


def test_fit_refuses_to_squash_a_scene():
    with pytest.raises(ValueError, match="scene 2 shorter than 4"):
        fit_durations([60, 4, 60], 100)
    with pytest.raises(ValueError, match="3 scenes need at least 12"):
        fit_durations([10, 10, 10], 11)


@pytest.mark.parametrize("total,ok", [(100, True), (101.5, True), (98.5, True), (101.6, False), (98.4, False)])
def test_narration_fit_tolerance(total, ok):
    assert narration_fit(total, 100.0)[0] is ok
    assert narration_fit(total, None) == (True, "")


def test_scene_file_round_trip():
    r = rows(("sleep", 20), ("horror", 15))
    r[1].update(intensity=0.9, transition="swell")
    settings = {**DEFAULT_SETTINGS, "transitions": "riser", "xfade": 3.0, "tempo_match": False}
    text = dump_scene_file(validate_rows(r, MOODS), settings)
    assert json.loads(text)["format"] == "bgmstudio-scenes"
    back, s = load_scene_file(text, MOODS)
    assert to_api(back) == to_api(validate_rows(r, MOODS)) and s == settings


def test_scene_file_accepts_api_body_and_bare_list():
    """InkHeart/Reelwright can hand over exactly what they send to /sequence."""
    body = {"scenes": [{"mood": "Horror", "duration": 12, "intensity": [0.2, 0.8]}], "transitions": "auto"}
    r, s = load_scene_file(json.dumps(body), MOODS)
    assert r[0]["mood"] == "horror" and r[0]["intensity"] == pytest.approx(0.5) and s == DEFAULT_SETTINGS
    r, _ = load_scene_file('[{"mood": "calm", "duration": 9}]', MOODS)
    assert r[0]["duration"] == 9.0


@pytest.mark.parametrize("text,msg", [("{not json", "Not a JSON"), ('{"x": 1}', "Expected"),
                                      ('[{"mood": "jazz", "duration": 5}]', "unknown mood 'jazz'"),
                                      ('[{"mood": "calm"}]', "needs at least mood and duration")])
def test_scene_file_errors(text, msg):
    with pytest.raises(ValueError, match=msg):
        load_scene_file(text, MOODS)


def test_scene_file_ignores_badly_typed_settings():
    text = json.dumps({"scenes": [{"mood": "calm", "duration": 5}],
                       "settings": {"xfade": "lots", "tempo_match": 1, "transitions": "boom", "duck_db": 12}})
    _, s = load_scene_file(text, MOODS)
    assert s == {**DEFAULT_SETTINGS, "duck_db": 12.0}


def test_result_summary_for_each_kind():
    track = {"seed": 4, "bpm": 59.2, "key": "A# minor", "duration": 30.0,
             "cues": {"scenes": [{"bpm": 59.2, "key": "A# minor"}], "sections": [{}, {}]}}
    assert result_summary(track)["bpm"] == "59.2" and result_summary(track)["structure"] == "2 sections"
    seq = {"seed": 7, "key": "D", "duration": 60.0, "warnings": ["tempo"], "stems": {"pad": "x", "fx": "y"},
           "cues": {"scenes": [{"bpm": 48.1}, {"bpm": 96.0}], "sections": [{}] * 5}}
    s = result_summary(seq)
    assert (s["bpm"], s["key"], s["structure"], s["stems"], s["warnings"]) == \
        ("48–96", "D", "2 scenes · 5 sect", "2", ["tempo"])
    mix = {"seed": 9, "total_seconds": 101.5, "cues": {"scenes": [{"bpm": 50, "key": "D dorian"},
                                                                   {"bpm": 50, "key": "D minor"}],
                                                        "sections": [{}], "narration": {"start": 1.5, "end": 98.5}}}
    m = result_summary(mix)
    assert (m["length"], m["key"], m["bpm"], m["narration"]["end"]) == (101.5, "D", "50.0", 98.5)
