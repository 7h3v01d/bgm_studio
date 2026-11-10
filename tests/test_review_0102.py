# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""0.10.2: fixes for the 0.10.1 review.  Each test fails on 0.10.1."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import time

import pytest
from fastapi import HTTPException

from bgmstudio import provenance, service
from bgmstudio.api import BGMRequest, _guard, app


# ---------------------------------------------------------------- render budget matches the documented limit
def test_default_render_budget_is_the_documented_two_hours():
    assert service.MAX_RENDER_SECONDS == 7200
    assert BGMRequest.model_fields["duration"].metadata[-1].le == 7200


def test_render_budget_can_still_be_lowered_by_environment():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, "BGM_MAX_RENDER_SECONDS": "900"}
    out = subprocess.run([sys.executable, "-c", "from bgmstudio import service; print(service.MAX_RENDER_SECONDS)"],
                         cwd=root, env=env, capture_output=True, text=True, check=True)
    assert float(out.stdout.strip()) == 900


def test_long_form_requests_pass_the_budget_check():
    """A 30-minute sleep bed and a 25-minute narration mix are what the fiction channel needs."""
    service._check_budget(1800.0)
    service._check_budget(25 * 60 + 4.5)


# ---------------------------------------------------------------- cache hits don't queue behind renders
def _hold_render_lock(seconds: float, started: threading.Event, path: str):
    with service._render_lock(path):
        started.set()
        time.sleep(seconds)


@pytest.mark.parametrize("kind", ["track", "sequence", "mix"])
def test_cache_hit_does_not_wait_for_an_unrelated_render(tmp_path, kind):
    narration = tmp_path / "voice.wav"
    if kind == "mix":
        import numpy as np
        import soundfile as sf
        t = np.arange(44100 * 5) / 44100
        sf.write(str(narration), (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), 44100)

    def call():
        if kind == "mix":
            return service.mix_with_narration(str(narration), "calm", seed=1, out_dir=str(tmp_path))
        if kind == "track":
            return service.generate_bgm("calm", 6, seed=1, out_dir=str(tmp_path))
        return service.generate_sequence([{"mood": "calm", "duration": 5}, {"mood": "lofi", "duration": 5}],
                                         seed=1, out_dir=str(tmp_path))
    call()  # warm the cache
    started = threading.Event()
    t = threading.Thread(target=_hold_render_lock, args=(4.0, started, str(tmp_path / "other.wav")))
    t.start()
    started.wait()
    t0 = time.monotonic()
    r = call()
    waited = time.monotonic() - t0
    t.join()
    assert r["cached"] is True
    assert waited < 1.0, f"cached call waited {waited:.1f}s behind another render"


def test_identical_concurrent_requests_still_render_once(tmp_path, monkeypatch):
    calls, real = [], service.render_music
    monkeypatch.setattr(service, "render_music", lambda *a, **kw: (calls.append(1), real(*a, **kw))[1])
    barrier = threading.Barrier(3)

    results, errors = [], []
    def go():
        try:
            barrier.wait(timeout=20)
            results.append(service.generate_bgm("calm", 6, seed=7, out_dir=str(tmp_path)))
        except Exception as exc:
            errors.append(exc)
    ts = [threading.Thread(target=go) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors, f"concurrent request errors: {errors!r}"
    assert len(results) == 3
    assert len({r["path"] for r in results}) == 1
    assert len(calls) == 1


# ---------------------------------------------------------------- hashing cost on cache hits
def test_cache_hits_reuse_verified_hashes(tmp_path, monkeypatch):
    service.generate_bgm("calm", 6, seed=2, stems=True, out_dir=str(tmp_path))
    n, real = [0], provenance.file_sha256

    def counting(p):
        n[0] += 1
        return real(p)
    monkeypatch.setattr(provenance, "file_sha256", counting)
    service.generate_bgm("calm", 6, seed=2, stems=True, out_dir=str(tmp_path))  # may hash once per process
    first = n[0]
    for _ in range(3):
        service.generate_bgm("calm", 6, seed=2, stems=True, out_dir=str(tmp_path))
    assert n[0] == first, f"{n[0] - first} full-file hashes on 3 repeat cache hits"


def test_modified_cached_file_is_still_caught(tmp_path):
    r = service.generate_bgm("calm", 6, seed=3, out_dir=str(tmp_path))
    assert service.generate_bgm("calm", 6, seed=3, out_dir=str(tmp_path))["cached"] is True
    time.sleep(0.05)
    with open(r["path"], "r+b") as f:  # same size, different content
        f.seek(1000)
        f.write(b"\x7f" * 64)
    again = service.generate_bgm("calm", 6, seed=3, out_dir=str(tmp_path))
    assert again["cached"] is False


# ---------------------------------------------------------------- cache identity
def test_cache_identity_ignores_package_version_but_tracks_engine_revision(monkeypatch):
    base = service._request_hash({"x": 1})
    monkeypatch.setattr(service, "__version__", "9.9.9")
    assert service._request_hash({"x": 1}) == base, "a docs-only release must not invalidate the cache"
    monkeypatch.setattr(service, "ENGINE_REVISION", service.ENGINE_REVISION + 1)
    assert service._request_hash({"x": 1}) != base


# ---------------------------------------------------------------- error mapping
def _asgi_post_mix(headers):
    msgs = []
    scope = {"type": "http", "method": "POST", "path": "/mix", "headers": headers, "query_string": b"",
             "http_version": "1.1", "scheme": "http", "server": ("t", 80), "client": ("c", 1), "root_path": ""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        msgs.append(m)
    asyncio.run(app(scope, receive, send))
    return next(m["status"] for m in msgs if m["type"] == "http.response.start")


def test_malformed_content_length_is_400():
    assert _asgi_post_mix([(b"content-length", b"abc")]) == 400


def test_lock_timeout_is_503():
    def busy():
        raise TimeoutError("timed out waiting for BGM output directory lock")
    with pytest.raises(HTTPException) as e:
        _guard(busy)
    assert e.value.status_code == 503 and "retry" in e.value.detail.lower()
