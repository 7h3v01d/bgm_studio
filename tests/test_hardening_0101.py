"""Release 0.10.1 safety regression tests; no FluidSynth installation required."""
import io
import json
import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from bgmstudio import service, audio
from bgmstudio.api import app


def test_render_budget_rejects_oversize_before_soundfont(monkeypatch):
    monkeypatch.setattr(service, "MAX_RENDER_SECONDS", 10.0)
    with pytest.raises(ValueError, match="budget"):
        service.generate_bgm(duration=11, seed=5)
    with pytest.raises(ValueError, match="budget"):
        service.generate_sequence([{"mood": "calm", "duration": 7},
                                   {"mood": "calm", "duration": 7}])
    with pytest.raises(ValueError, match="budget"):
        service.stream_bgm("calm", 11)


def test_sequence_count_and_infinite_duration_denied(monkeypatch):
    monkeypatch.setattr(service, "MAX_SCENES", 2)
    with pytest.raises(ValueError, match="scene count"):
        service.generate_sequence([{"mood": "calm", "duration": 5}] * 3)
    with pytest.raises(ValueError, match="finite"):
        service.generate_bgm(duration=float("nan"))


def test_upload_is_bounded_before_decode(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "OUT_DIR", str(tmp_path))
    monkeypatch.setattr(service, "MAX_NARRATION_BYTES", 10)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post("/mix", files={"narration": ("n.wav", b"x" * 11)})
    assert r.status_code == 413


def test_request_fingerprint_sensitive_to_all_options():
    request = {"seed": 5, "music_lufs": -26, "duck_db": 9, "stems": False}
    original = service._request_hash(request)
    for key, value in [("music_lufs", -30), ("duck_db", 12), ("stems", True)]:
        changed = {**request, key: value}
        assert service._request_hash(changed) != original
    assert service._request_hash(request) == original


def test_cached_files_with_bad_hash_do_not_validate(tmp_path):
    main = tmp_path / "out.wav"
    main.write_bytes(b"GOOD")
    meta = {"path": str(main), "cues": {}, "provenance": {"outputs": {
        "main": {"file": "out.wav", "bytes": 4, "sha256": "0" * 64}}}}
    assert not service._meta_complete(meta, stems=False, expected_path=str(main))
    from bgmstudio.provenance import file_sha256
    meta["provenance"]["outputs"]["main"]["sha256"] = file_sha256(main)
    assert service._meta_complete(meta, stems=False, expected_path=str(main))
    meta["path"] = str(tmp_path / "wrong.wav")
    assert not service._meta_complete(meta, stems=False, expected_path=str(main))


def test_ffmpeg_subprocess_timeout_configured(monkeypatch, tmp_path):
    calls = []
    def fake_run(*args, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout="1.2\n", stderr="")
    monkeypatch.setattr(audio.subprocess, "run", fake_run)
    assert audio.audio_duration(str(tmp_path / "fake.wav")) == 1.2
    assert calls[0]["timeout"] == audio.FFMPEG_TIMEOUT


def test_mcp_path_authorization_without_mcp_sdk(monkeypatch, tmp_path):
    # Importing the MCP SDK is optional, so exercise the isolated rules by
    # loading the helper definitions rather than requiring an agent runtime.
    import ast
    from pathlib import Path
    import bgmstudio
    source = (Path(bgmstudio.__file__).parent / "mcp_server.py").read_text()
    tree = ast.parse(source)
    functions = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name in
                 ("_approved_output", "_approved_narration")]
    code = compile(ast.Module(body=functions, type_ignores=[]), "mcp_helpers", "exec")
    namespace = {"os": os, "Optional": __import__("typing").Optional, "service": service}
    exec(code, namespace)
    out = tmp_path / "out"
    out.mkdir()
    inp = tmp_path / "input"
    inp.mkdir()
    monkeypatch.setenv("BGM_MCP_OUTPUT_DIR", str(out))
    monkeypatch.setenv("BGM_MCP_INPUT_DIR", str(inp))
    assert namespace["_approved_output"](None) == str(out)
    assert namespace["_approved_narration"](str(inp / "voice.wav")) == str(inp / "voice.wav")
    with pytest.raises(ValueError, match="output directory"):
        namespace["_approved_output"](str(tmp_path))
    with pytest.raises(ValueError, match="narration"):
        namespace["_approved_narration"](str(out / "voice.wav"))


def test_mix_outputs_distinguish_render_settings_and_cache(monkeypatch, tmp_path):
    """Directly reproduce F01 without needing FluidSynth: changing ducking cannot overwrite an earlier mix."""
    import numpy as np
    narration = tmp_path / "voice.wav"
    narration.write_bytes(b"example narration identity")
    sf = tmp_path / "sound.sf2"
    sf.write_bytes(b"soundfont test identity")
    monkeypatch.setattr(service, "find_soundfont", lambda *a, **kw: str(sf))
    monkeypatch.setattr(service, "read_audio", lambda *a, **kw: np.zeros((5 * service.SR, 2), dtype=np.float32))
    class FakePlan:
        def summary(self):
            return {"mood": "calm", "seed": 4, "key": "C"}
    monkeypatch.setattr(service, "compose", lambda *a, **kw: FakePlan())
    monkeypatch.setattr(service, "render_audio", lambda *a, **kw: np.zeros((9 * service.SR, 2), dtype=np.float32))
    monkeypatch.setattr(service, "track_cues", lambda *a: {"downbeats": []})
    monkeypatch.setattr(service, "mix_voice_and_music", lambda *a, **kw: (
        np.zeros((9 * service.SR, 2), dtype=np.float32),
        {"final_lufs": -16.0}, None))
    def fake_write(path, data):
        with open(path, "wb") as stream:
            stream.write(b"fake audio")
        return path
    monkeypatch.setattr(service, "write_audio", fake_write)
    first = service.mix_with_narration(str(narration), seed=4, out_dir=str(tmp_path), duck_db=6)
    second = service.mix_with_narration(str(narration), seed=4, out_dir=str(tmp_path), duck_db=18)
    assert first["path"] != second["path"]
    assert os.path.isfile(first["path"]) and os.path.isfile(second["path"])
    third = service.mix_with_narration(str(narration), seed=4, out_dir=str(tmp_path), duck_db=6)
    assert third["cached"] is True
    assert third["path"] == first["path"]
    with open(first["meta_path"]) as stream:
        assert json.load(stream)["provenance"]["request"]["duck_db"] == 6
