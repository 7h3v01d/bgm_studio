# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""0.10: cue sheets, stems and provenance records."""
from __future__ import annotations

import io
import json
import math
import os
import struct
import wave

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from bgmstudio import provenance, service
from bgmstudio.api import app
from bgmstudio.compose import compose
from bgmstudio.cues import track_cues

SR = 44100


def _wav_bytes(seconds: float = 8.0, gap_at: float | None = 4.0) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        frames = []
        for i in range(int(22050 * seconds)):
            t = i / 22050
            on = gap_at is None or not (gap_at <= t < gap_at + 1.5)
            frames.append(struct.pack("<h", int(9000 * math.sin(2 * math.pi * 220 * t)) if on else 0))
        w.writeframes(b"".join(frames))
    return b.getvalue()


def _narration(tmp_path, name="voice.wav", **kw) -> str:
    p = tmp_path / name
    p.write_bytes(_wav_bytes(**kw))
    return str(p)


def _read(path):
    a, _ = sf.read(path, dtype="float32", always_2d=True)
    return a


def _assert_sums(main_path, stem_paths, tol_db=-60.0):
    """Stems add up to the main file: residual at least 60 dB below the main file's peak (16-bit rounding)."""
    main = _read(main_path)
    total = np.zeros_like(main)
    for p in stem_paths.values():
        s = _read(p)
        assert s.shape == main.shape, p
        total += s
    err = np.abs(total - main).max()
    peak = np.abs(main).max()
    assert 20 * np.log10(err / peak + 1e-12) < tol_db, f"stems miss the mix by {err:.5f} (peak {peak:.3f})"


# ---------------------------------------------------------------- cue sheets
def test_track_cues_match_the_plan():
    p = compose("cinematic", 95.3, seed=4, intensity=[0.2, 0.9])
    c = track_cues(p)
    bar = 4 * 60.0 / p.bpm
    assert c["duration"] == pytest.approx(95.3) and c["time_signature"] == "4/4"
    assert len(c["downbeats"]) == p.bars and c["downbeats"][0] == 0.0
    assert np.allclose(np.diff(c["downbeats"]), bar, atol=1e-3)
    assert [s["kind"] for s in c["sections"]] == [s[0] for s in p.sections]
    assert c["sections"][0]["start"] == 0.0 and c["sections"][-1]["end"] == pytest.approx(95.3, abs=1e-3)
    for a, b in zip(c["sections"], c["sections"][1:]):
        assert a["end"] == b["start"]
    assert all("intensity" in s for s in c["sections"])
    assert c["scenes"] == [{"scene": 1, "mood": "cinematic", "start": 0.0, "end": 95.3, "bpm": round(p.bpm, 3),
                            "beat_seconds": round(60 / p.bpm, 6), "key": f"{p.key} {p.mode}"}]


def test_sequence_cues_follow_the_cuts(tmp_path):
    scenes = [{"mood": "sleep", "duration": 20}, {"mood": "suspense", "duration": 17.5},
              {"mood": "horror", "duration": 22, "transition": "riser_impact"}]
    r = service.generate_sequence(scenes, seed=3, transitions="swell", out_dir=str(tmp_path))
    c = r["cues"]
    assert [(s["start"], s["end"]) for s in c["scenes"]] == [(0.0, 20.0), (20.0, 37.5), (37.5, 59.5)]
    assert c["transitions"] == [{"time": 20.0, "type": "swell", "scene": 2},
                                {"time": 37.5, "type": "riser_impact", "scene": 3}]
    for sc in c["scenes"]:
        mine = [s for s in c["sections"] if s["scene"] == sc["scene"]]
        assert mine[0]["start"] == sc["start"] and mine[-1]["end"] <= sc["end"] + 1e-6
        assert sc["start"] in c["downbeats"], "each scene starts on a downbeat"
    assert c["downbeats"] == sorted(c["downbeats"]) and c["downbeats"][-1] < 59.5
    assert c["duration"] == 59.5


def test_mix_cues_carry_the_narration(tmp_path):
    r = service.mix_with_narration(_narration(tmp_path), "folklore", lead_in=2.0, tail_out=3.0, seed=1,
                                   out_dir=str(tmp_path))
    assert r["cues"]["narration"] == {"start": 2.0, "end": 10.0}
    assert r["cues"]["duration"] == pytest.approx(13.0, abs=1e-3)


# ---------------------------------------------------------------- stems
def test_track_stems_add_up(tmp_path):
    r = service.generate_bgm("folklore", 30, seed=2, stems=True, out_dir=str(tmp_path))
    assert set(r["stems"]) <= {"pad", "bass", "keys", "melody", "sparkle", "drums"} and len(r["stems"]) >= 4
    _assert_sums(r["path"], r["stems"])


def test_loop_with_curve_stems_add_up(tmp_path):
    r = service.generate_bgm("suspense", 40, seed=5, loop=True, intensity=[0.1, 0.9], stems=True,
                             out_dir=str(tmp_path))
    _assert_sums(r["path"], r["stems"])


def test_sequence_stems_with_transitions_add_up(tmp_path):
    scenes = [{"mood": "lofi", "duration": 15}, {"mood": "cinematic", "duration": 15},
              {"mood": "calm", "duration": 15}, {"mood": "tech", "duration": 15, "transition": "swell"}]
    r = service.generate_sequence(scenes, seed=6, transitions="auto", stems=True, out_dir=str(tmp_path))
    assert "fx" in r["stems"] and np.abs(_read(r["stems"]["fx"])).max() > 0.01
    _assert_sums(r["path"], r["stems"])


def test_stems_render_is_its_own_take_and_close_to_plain(tmp_path):
    """A stems render builds its mix from the stems (FluidSynth voice reuse makes a full render differ slightly at
    note attacks), so it gets its own file; the music is the same apart from those attack details."""
    scenes = [{"mood": "lofi", "duration": 15}, {"mood": "cinematic", "duration": 15, "transition": "swell"},
              {"mood": "calm", "duration": 15}]
    a = service.generate_sequence(scenes, seed=6, transitions="riser_impact", out_dir=str(tmp_path))
    b = service.generate_sequence(scenes, seed=6, transitions="riser_impact", stems=True, out_dir=str(tmp_path))
    assert a["path"] != b["path"]
    x, y = _read(a["path"]), _read(b["path"])
    rms = lambda v: float(np.sqrt(np.mean(v.astype(np.float64) ** 2)))
    assert 20 * np.log10(rms(x - y) / rms(x)) < -35


def test_mix_stems_add_up(tmp_path):
    r = service.mix_with_narration(_narration(tmp_path), seed=2, stems=True, out_dir=str(tmp_path),
                                   scenes=[{"mood": "calm", "duration": 4}, {"mood": "cinematic", "duration": 4}],
                                   transitions="riser_impact")
    assert set(r["stems"]) == {"voice", "music", "fx"}
    _assert_sums(r["path"], r["stems"])
    voice = _read(r["stems"]["voice"])
    assert np.abs(voice[: int(1.4 * SR)]).max() == 0, "voice stem is placed after the lead-in, like the mix"


def test_stems_are_limited_in_length(tmp_path, monkeypatch):
    """Stems keep several full-length buffers in memory, so they have a length cap (an hour by default)."""
    assert service.MAX_STEM_SECONDS == 3600
    monkeypatch.setattr(service, "MAX_STEM_SECONDS", 10.0)
    with pytest.raises(ValueError, match="stems are limited"):
        service.generate_bgm("sleep", 12, stems=True, out_dir=str(tmp_path))
    with pytest.raises(ValueError, match="stems are limited"):
        service.generate_sequence([{"mood": "calm", "duration": 6}, {"mood": "calm", "duration": 6}], stems=True,
                                  out_dir=str(tmp_path))


# ---------------------------------------------------------------- provenance
def test_provenance_record(tmp_path):
    r = service.generate_bgm("horror", 10, seed=8, stems=True, midi=True, out_dir=str(tmp_path))
    pv = r["provenance"]
    assert pv["generator"] == "bgmstudio" and pv["kind"] == "track" and pv["seed"] == 8
    assert pv["request"]["mood"] == "horror" and "sf" not in pv["request"]
    assert pv["soundfont"]["sha256"] == provenance.file_sha256(os.path.realpath(pv_sf(pv)))
    for label, info in pv["outputs"].items():
        path = os.path.join(tmp_path, info["file"])
        assert provenance.file_sha256(path) == info["sha256"], label
    assert {"main", "midi"} <= set(pv["outputs"]) and any(k.startswith("stem-") for k in pv["outputs"])
    with open(r["meta_path"]) as f:
        assert json.load(f)["provenance"] == pv


def pv_sf(pv):
    from bgmstudio.render import find_soundfont
    real = os.path.realpath(find_soundfont())
    assert os.path.basename(real) == pv["soundfont"]["file"]
    return real


def test_soundfont_licence_follows_symlinks_and_overrides(tmp_path, monkeypatch):
    monkeypatch.delenv("BGM_SOUNDFONT_LICENSE", raising=False)
    real = tmp_path / "fonts" / "FluidR3_GM.sf2"
    real.parent.mkdir()
    real.write_bytes(b"sfbk")
    link = tmp_path / "default-GM.sf2"
    try:
        link.symlink_to(real)
    except OSError as exc:
        # Windows without Developer Mode / symlink privilege raises WinError 1314.
        # The application is not at fault; preserve the symlink-specific assertions
        # for environments that can create the link.
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink creation requires Developer Mode or privilege (WinError 1314)")
        raise
    assert provenance.soundfont_license(str(link))["license"] == "MIT"
    (tmp_path / "fonts" / "FluidR3_GM.license.txt").write_text("Custom licence line\nmore")
    assert provenance.soundfont_license(str(link)) == {"license": "Custom licence line",
                                                       "source": str(tmp_path / "fonts" / "FluidR3_GM.license.txt")}
    monkeypatch.setenv("BGM_SOUNDFONT_LICENSE", "Bought it, receipt #42")
    assert provenance.soundfont_license(str(link))["license"] == "Bought it, receipt #42"


def test_unknown_soundfont_says_how_to_record_it(tmp_path, monkeypatch):
    monkeypatch.delenv("BGM_SOUNDFONT_LICENSE", raising=False)
    f = tmp_path / "Mystery.sf2"
    f.write_bytes(b"x")
    info = provenance.soundfont_license(str(f))
    assert info["license"] == "unknown" and "Mystery.license.txt" in info["music_use"]


def test_mix_provenance_hashes_the_narration(tmp_path):
    n = _narration(tmp_path)
    r = service.mix_with_narration(n, "calm", seed=4, out_dir=str(tmp_path))
    assert r["provenance"]["request"]["narration"]["sha256"] == provenance.file_sha256(n)
    assert os.path.isfile(r["meta_path"])


def test_different_narrations_never_share_an_output(tmp_path):
    a = service.mix_with_narration(_narration(tmp_path / "a" if False else tmp_path, "narration.wav"), seed=4,
                                   out_dir=str(tmp_path / "out"))
    other = tmp_path / "x"
    other.mkdir()
    b_path = other / "narration.wav"
    b_path.write_bytes(_wav_bytes(gap_at=None))
    b = service.mix_with_narration(str(b_path), seed=4, out_dir=str(tmp_path / "out"))
    assert a["path"] != b["path"] and os.path.isfile(a["path"])


# ---------------------------------------------------------------- cache
def test_old_cache_entries_without_cues_are_rerendered(tmp_path):
    r = service.generate_bgm("calm", 6, seed=1, out_dir=str(tmp_path))
    meta = dict(r)
    for k in ("cues", "provenance"):
        meta.pop(k)
    with open(r["meta_path"], "w") as f:
        json.dump(meta, f)
    again = service.generate_bgm("calm", 6, seed=1, out_dir=str(tmp_path))
    assert again["cached"] is False and "cues" in again


def test_asking_for_stems_after_a_plain_render(tmp_path):
    a = service.generate_bgm("calm", 6, seed=1, out_dir=str(tmp_path))
    b = service.generate_bgm("calm", 6, seed=1, stems=True, out_dir=str(tmp_path))
    c = service.generate_bgm("calm", 6, seed=1, stems=True, out_dir=str(tmp_path))
    assert b["path"] != a["path"] and b["cached"] is False and b["stems"]
    assert c["cached"] is True and c["stems"] == b["stems"]
    d = service.generate_bgm("calm", 6, seed=1, out_dir=str(tmp_path))
    assert d["cached"] is True and d["path"] == a["path"], "plain renders keep their own file"


# ---------------------------------------------------------------- front ends
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "OUT_DIR", str(tmp_path))
    return TestClient(app, raise_server_exceptions=False)


def test_api_json_links_everything(client):
    j = client.post("/bgm?as_json=true", json={"mood": "folklore", "duration": 12, "seed": 3, "stems": True,
                                                "midi": True}).json()
    assert "path" not in j and "meta_path" not in j
    for url in [j["download_url"], j["meta_url"], j["midi_url"], *j["stems"].values()]:
        assert client.get(url).status_code == 200, url
    assert client.get(j["meta_url"]).json()["cues"] == j["cues"]


def test_api_binary_points_to_record(client):
    r = client.post("/bgm", json={"mood": "calm", "duration": 6, "seed": 3})
    meta = client.get(r.headers["X-BGM-Meta-URL"]).json()
    assert meta["provenance"]["outputs"]["main"]["sha256"] == __import__("hashlib").sha256(r.content).hexdigest()


def test_api_mix_json_with_stems(client):
    r = client.post("/mix?as_json=true", files={"narration": ("n.wav", _wav_bytes())},
                    data={"mood": "sleep", "stems": "true", "seed": "2"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j["stems"]) == {"voice", "music"} and j["cues"]["narration"]["start"] == 1.5
    assert client.get(j["stems"]["voice"]).status_code == 200


def test_api_sequence_stems(client):
    r = client.post("/sequence?as_json=true", json={"scenes": [{"mood": "calm", "duration": 8},
                                                               {"mood": "dark", "duration": 8}],
                                                    "transitions": "impact", "stems": True, "seed": 1})
    assert r.status_code == 200, r.text
    assert "fx" in r.json()["stems"] and r.json()["cues"]["transitions"][0]["type"] == "impact"


def test_mcp_results_leave_out_per_bar_list():
    from bgmstudio.mcp_server import _slim
    r = {"cues": {"duration": 10, "downbeats": [0, 2, 4], "sections": []}, "seed": 1}
    s = _slim(r)
    assert "downbeats" not in s["cues"] and s["cues"]["downbeat_count"] == 3


@pytest.mark.parametrize("names", [["riser_impact", "swell"], ["swell", "downlifter"], ["impact", "riser", "swell"]])
def test_separate_fx_buffer_is_exactly_the_old_single_buffer(names):
    """Transitions into a separate fx buffer (stems) must give music + fx == the single-buffer result, even when a
    swell scales a stretch that already holds an earlier effect."""
    from bgmstudio.fx import apply_transition
    rng = np.random.default_rng(1)
    base = (rng.standard_normal((SR * 12, 2)) * 0.1).astype(np.float32)
    single, music, fx = base.copy(), base.copy(), np.zeros_like(base)
    cuts = [SR * 3, SR * 5, SR * 8][:len(names)]
    for i, (name, cut) in enumerate(zip(names, cuts)):
        kw = dict(seed=i, key_pc=2, level_db=-3.0, prev_len=3.0, next_len=3.0)
        apply_transition(single, name, cut, SR, **kw)
        apply_transition(music, name, cut, SR, fx_out=fx, **kw)
    assert np.abs(fx).max() > 0.01
    assert np.abs(music + fx - single).max() < 1e-5
