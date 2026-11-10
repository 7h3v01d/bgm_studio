# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""release_verify.py --write-manifest: what a release contains, and that the result verifies."""
import json

import release_verify as rv


def _tree(root):
    for rel in ("README.md", "bgmstudio/service.py", "docs/USER_MANUAL.md", ".venv/lib/x.py", "bgm_out/a.wav",
                "soundfonts/GM.sf2", "fluidsynth/bin/libfluidsynth.dll", "bgmstudio/__pycache__/s.pyc",
                "release_evidence/environment.json", "gui_exports/t.wav", "bgm_server.log", ".git/HEAD",
                "soundfonts/PUT_SF2_HERE.txt", "fluidsynth/PUT_WINDOWS_FLUIDSYNTH_HERE.txt"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rel)


def test_release_files_exclude_environments_binaries_and_outputs(tmp_path):
    _tree(tmp_path)
    assert rv.release_files(tmp_path) == ["README.md", "bgmstudio/service.py", "docs/USER_MANUAL.md",
                                          "fluidsynth/PUT_WINDOWS_FLUIDSYNTH_HERE.txt", "soundfonts/PUT_SF2_HERE.txt"]


def test_written_manifest_verifies_and_detects_changes(tmp_path):
    _tree(tmp_path)
    assert rv.write_manifest(tmp_path, "9.9.9", "v9.9.9") == 5
    m = json.loads((tmp_path / rv.MANIFEST).read_text())
    assert m["release"] == "9.9.9" and "soundfonts/GM.sf2" not in m["files"] and "README.md" in m["files"]
    assert rv.verify(tmp_path) == (True, [])
    (tmp_path / "README.md").write_text("edited")
    ok, problems = rv.verify(tmp_path)
    assert not ok and problems == ["CHANGED README.md"]


def test_shipped_manifest_covers_exactly_the_release_files():
    """Catches a file added or removed without regenerating the manifest."""
    from pathlib import Path
    root = Path(rv.__file__).resolve().parent
    listed = set(json.loads((root / rv.MANIFEST).read_text())["files"])
    assert listed == set(rv.release_files(root))
