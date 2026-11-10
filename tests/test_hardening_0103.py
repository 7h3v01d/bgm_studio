"""v0.10.3 admission, preflight and cache assurance tests (no FluidSynth required)."""
import os
import threading
import time

import pytest

from bgmstudio import provenance, service


def test_memory_admission_rejects_before_allocation(monkeypatch):
    monkeypatch.setattr(service, "MAX_RENDER_MEMORY_MIB", 1)
    with pytest.raises(ValueError, match="estimated render memory"):
        service._check_budget(60, buffers=5)


def test_documented_two_hour_duration_remains_configured():
    assert service.MAX_RENDER_SECONDS == 7200
    service._check_budget(7200, buffers=3)


def test_narration_preflight_rejects_combined_duration_without_decoding(tmp_path, monkeypatch):
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"fake media")
    monkeypatch.setattr(service, "find_soundfont", lambda _: "dummy.sf2")
    monkeypatch.setattr(service.provenance, "cached_sha256", lambda _: "fake")
    monkeypatch.setattr("bgmstudio.audio.audio_duration", lambda _: 7199.0)
    def should_not_decode(*args, **kwargs):
        raise AssertionError("decoded before preflight")
    monkeypatch.setattr(service, "read_audio", should_not_decode)
    with pytest.raises(ValueError, match="duration exceeds"):
        service.mix_with_narration(str(sample), lead_in=2, tail_out=3)


def test_narration_memory_admission_before_decoding(tmp_path, monkeypatch):
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"fake media")
    monkeypatch.setattr(service, "find_soundfont", lambda _: "dummy.sf2")
    monkeypatch.setattr("bgmstudio.audio.audio_duration", lambda _: 120.0)
    monkeypatch.setattr(service, "MAX_RENDER_MEMORY_MIB", 1)
    monkeypatch.setattr(service, "read_audio", lambda _: (_ for _ in ()).throw(AssertionError("decoded")))
    with pytest.raises(ValueError, match="estimated render memory"):
        service.mix_with_narration(str(sample))


def test_strict_hash_verifies_same_size_restored_mtime(tmp_path, monkeypatch):
    p = tmp_path / "sample.bin"
    p.write_bytes(b"AAAA")
    before = provenance.cached_sha256(str(p))
    st = p.stat()
    p.write_bytes(b"BBBB")
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    # Fast cache may legitimately preserve original under unchanged stat identity.
    monkeypatch.setenv("BGM_STRICT_CACHE_HASHES", "1")
    assert provenance.cached_sha256(str(p)) != before


@pytest.mark.skipif(os.name == "nt", reason="Unix-specific advisory lock test")
def test_unix_lock_respects_timeout(tmp_path, monkeypatch):
    # fcntl flock is process-scoped: use an independent process to hold the lock.
    import subprocess
    import sys
    holder = tmp_path / "holder.py"
    holder.write_text('''import fcntl, os, sys, time
p=sys.argv[1]
f=open(p,"a+b")
fcntl.flock(f.fileno(), fcntl.LOCK_EX)
print("locked",flush=True)
time.sleep(5)
''')
    lock = tmp_path / ".bgmstudio.render.lock"
    proc = subprocess.Popen([sys.executable, str(holder), str(lock)], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "locked"
        monkeypatch.setenv("BGM_LOCK_TIMEOUT", "0.2")
        with pytest.raises(TimeoutError, match="timed out"):
            with service._render_lock(str(tmp_path / "output.wav")):
                pass
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_invalid_narration_preflight_maps_ffprobe_failure_to_422(tmp_path, monkeypatch):
    """An invalid uploaded narration must remain a 422 after preflight was introduced."""
    import subprocess
    from fastapi.testclient import TestClient
    from bgmstudio.api import app
    from bgmstudio import audio

    monkeypatch.setattr(service, "find_soundfont", lambda _: "dummy.sf2")
    def invalid_probe(path):
        raise subprocess.CalledProcessError(1, ["ffprobe", path])
    monkeypatch.setattr(audio, "audio_duration", invalid_probe)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/mix", files={"narration": ("n.wav", b"invalid")}, data={"mood": "calm"})
    assert response.status_code == 422
    assert "decode" in response.json()["detail"].lower()


def test_invalid_narration_preflight_maps_bad_metadata_to_valueerror(tmp_path, monkeypatch):
    """Malformed ffprobe duration output follows the same input-error contract."""
    from bgmstudio import audio
    sample = tmp_path / "invalid.wav"
    sample.write_bytes(b"invalid")
    monkeypatch.setattr(service, "find_soundfont", lambda _: "dummy.sf2")
    monkeypatch.setattr(audio, "audio_duration", lambda _: (_ for _ in ()).throw(ValueError("not a number")))
    with pytest.raises(ValueError, match="could not decode"):
        service.mix_with_narration(str(sample))
