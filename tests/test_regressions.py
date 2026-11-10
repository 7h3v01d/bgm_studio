# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""Regression tests for bugs found in the 0.7 review.  Each one fails on 0.7 and passes on 0.8."""
from __future__ import annotations

import io
import math
import os
import struct
import threading
import wave

import pytest
from fastapi.testclient import TestClient

from bgmstudio import audio, service
from bgmstudio.api import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "OUT_DIR", str(tmp_path))
    return TestClient(app, raise_server_exceptions=False)


def _wav(seconds: float = 6.0) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 10))) for i in range(int(22050 * seconds))))
    return b.getvalue()


def _mix(client, **data):
    return client.post("/mix", files={"narration": ("n.wav", _wav())}, data={"mood": "calm", **data})


# ---------------------------------------------------------------- /mix error mapping and validation
def test_mix_undecodable_upload_is_422_with_message(client):
    r = client.post("/mix", files={"narration": ("n.wav", b"not audio at all")}, data={"mood": "calm"})
    assert r.status_code == 422
    assert "decode" in r.json()["detail"].lower()


@pytest.mark.parametrize("field,value", [("lead_in", "-5"), ("tail_out", "-10"), ("duck_db", "500"),
                                         ("music_lufs", "40"), ("final_lufs", "5"), ("xfade", "-1")])
def test_mix_rejects_out_of_range_fields(client, field, value):
    r = _mix(client, **{field: value})
    assert r.status_code == 422, (field, r.status_code, r.text[:200])
    assert field in r.text, f"error should name the bad field: {r.text[:200]}"


def test_mix_scenes_not_a_list_is_422(client):
    r = _mix(client, scenes="5")
    assert r.status_code == 422


def test_service_mix_rejects_negative_lead_in(tmp_path):
    p = tmp_path / "n.wav"
    p.write_bytes(_wav())
    with pytest.raises(ValueError, match="lead_in"):
        service.mix_with_narration(str(p), "calm", lead_in=-5, out_dir=str(tmp_path))


def test_service_mix_missing_file_is_clear(tmp_path):
    with pytest.raises(FileNotFoundError, match="narration"):
        service.mix_with_narration(str(tmp_path / "nope.wav"), "calm", out_dir=str(tmp_path))


# ---------------------------------------------------------------- /bgm/stream validation
@pytest.mark.parametrize("params", [{"target_lufs": 40}, {"fade_out": -3}, {"bpm": 0.5}, {"bpm": 900}])
def test_stream_rejects_out_of_range(client, params):
    r = client.get("/bgm/stream", params={"mood": "calm", "duration": 5, **params})
    assert r.status_code == 422, (params, r.status_code)


def test_service_stream_rejects_hot_target():
    with pytest.raises(ValueError, match="target_lufs"):
        service.stream_bgm("calm", 5, target_lufs=40)


# ---------------------------------------------------------------- cache: aliases and concurrency
def test_alias_shares_cache_with_canonical_mood(tmp_path):
    a = service.generate_bgm("chill", 5, seed=1, out_dir=str(tmp_path))
    b = service.generate_bgm("lofi", 5, seed=1, out_dir=str(tmp_path))
    assert a["path"] == b["path"]
    assert b["cached"] is True
    assert "_lofi_" in os.path.basename(a["path"])


def test_concurrent_identical_requests_render_once(tmp_path, monkeypatch):
    calls = []
    real = service.render_music

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(service, "render_music", counting)
    results, barrier = [], threading.Barrier(4)

    def go():
        barrier.wait()
        results.append(service.generate_bgm("calm", 8, seed=42, out_dir=str(tmp_path)))

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1
    assert len({r["path"] for r in results}) == 1
    assert sorted(r["cached"] for r in results) == [False, True, True, True]


def test_failed_write_leaves_no_partial_file(tmp_path, monkeypatch):
    import numpy as np
    target = tmp_path / "out.wav"

    def broken_write(path, *a, **kw):
        with open(path, "wb") as f:
            f.write(b"RIFF partial")
        raise OSError("disk full")

    monkeypatch.setattr(audio.sf, "write", broken_write)
    with pytest.raises(OSError):
        audio.write_audio(str(target), np.zeros((100, 2), dtype=np.float32))
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- packaging / CLI
def test_launchers_referenced_by_readme_exist():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("setup.bat", "test.bat"):
        assert os.path.isfile(os.path.join(root, name)), name


def test_single_version_source():
    import bgmstudio
    assert app.version == bgmstudio.__version__


def test_cli_scene_without_duration_is_clear():
    from bgmstudio.cli import _parse_scenes
    with pytest.raises(SystemExit, match="mood:seconds"):
        _parse_scenes("lofi")


def test_api_publishes_limits_in_openapi(client):
    """The limits must be visible in /docs, not only enforced deep in the engine."""
    spec = client.get("/openapi.json").json()
    mix_schema = next(iter(spec["components"]["schemas"][n] for n in spec["components"]["schemas"]
                           if n.startswith("Body_mix")))
    assert mix_schema["properties"]["lead_in"]["minimum"] == 0
    assert mix_schema["properties"]["duck_db"]["maximum"] == 40
    stream_params = {p["name"]: p for p in spec["paths"]["/bgm/stream"]["get"]["parameters"]}
    assert stream_params["target_lufs"]["schema"]["maximum"] == -8


@pytest.mark.parametrize("bad", [5, "lofi:30", {"mood": "lofi", "duration": 30}])
def test_service_scenes_must_be_a_list(bad):
    """MCP and library callers reach the service directly, without the API's JSON check."""
    with pytest.raises(ValueError, match="non-empty list"):
        service.generate_sequence(bad)
