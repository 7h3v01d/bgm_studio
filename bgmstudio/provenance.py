# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""Provenance records: what made a track, from which inputs and samples, so its origin can be shown later
(for example in answer to a YouTube Content ID claim).

The record is stored in the track's metadata JSON (`<track>.json`) under "provenance".
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import threading

from . import __version__

# Licences of well-known General MIDI SoundFonts, matched on the *real* file name (symlinks resolved).
# Checked Nov 2026 against the upstream licence texts; verify again before relying on them.
KNOWN_SOUNDFONTS = [
    ("generaluser", {
        "name": "GeneralUser GS", "author": "S. Christian Collins", "license": "GeneralUser GS License v2.0",
        "music_use": "Allowed without restriction for your own music, private or commercial.",
        "url": "https://github.com/mrbumpy409/GeneralUser-GS/blob/main/documentation/LICENSE.txt"}),
    ("musescore_general", {
        "name": "MuseScore_General", "author": "S. Christian Collins et al.", "license": "MIT (parts PD/CC0)",
        "music_use": "Permissive (MIT).", "url": "https://musescore.org/en/handbook/soundfonts-and-sfz-files"}),
    ("fluidr3", {
        "name": "Fluid (R3) GM", "author": "Frank Wen", "license": "MIT",
        "music_use": "Permissive (MIT); the licence places no conditions on recordings made with it.",
        "url": "https://tracker.debian.org/pkg/fluid-soundfont"}),
    ("timgm6mb", {
        "name": "TimGM6mb", "author": "Tim Brechbill", "license": "GPL-2.0",
        "music_use": "GPL-2.0 sample set: whether rendered audio is covered is unsettled. Prefer GeneralUser GS "
                     "or FluidR3 for published music.",
        "url": "https://tracker.debian.org/pkg/timgm6mb-soundfont"}),
]

_sha_cache: dict = {}
_sha_lock = threading.Lock()


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cached_sha256(path: str) -> str:
    """SHA-256 of a file, computed once per process for each (real path, size, mtime) and reused after that.
    Any change to the file changes its size or modification time, so a modified file is hashed again."""
    st = os.stat(path)
    key = (os.path.realpath(path), st.st_size, st.st_mtime_ns)
    with _sha_lock:
        hit = _sha_cache.get(key)
    if hit is not None:
        return hit
    digest = file_sha256(path)  # outside the lock: large files must not block other lookups
    with _sha_lock:
        _sha_cache[key] = digest
    return digest


_cached_sha = cached_sha256  # older name


def soundfont_license(path: str) -> dict:
    """Licence info for a SoundFont.  A text file next to it named <font>.license.txt (or LICENSE.txt in the same
    folder), or the BGM_SOUNDFONT_LICENSE variable, overrides the built-in table."""
    env = os.environ.get("BGM_SOUNDFONT_LICENSE")
    if env:
        return {"license": env, "source": "BGM_SOUNDFONT_LICENSE"}
    real = os.path.realpath(path)
    for side in (os.path.splitext(real)[0] + ".license.txt", real + ".license.txt",
                 os.path.join(os.path.dirname(real), "LICENSE.txt")):
        if os.path.isfile(side):
            with open(side, encoding="utf-8", errors="replace") as f:
                text = f.read().strip()
            return {"license": text.splitlines()[0][:200] if text else "see file", "source": side}
    low = os.path.basename(real).lower()
    for needle, info in KNOWN_SOUNDFONTS:
        if needle in low:
            return {**info, "source": "built-in table"}
    return {"license": "unknown",
            "music_use": f"Unknown. Put the font's licence in {os.path.splitext(os.path.basename(real))[0]}"
                         ".license.txt next to it, or set BGM_SOUNDFONT_LICENSE."}


def soundfont_record(path: str) -> dict:
    real = os.path.realpath(path)
    return {"file": os.path.basename(real), "bytes": os.path.getsize(real), "sha256": _cached_sha(real),
            **soundfont_license(real)}


def fluidsynth_version() -> str | None:
    try:
        import ctypes
        import fluidsynth
        fn = fluidsynth._fl.fluid_version_str
        fn.restype = ctypes.c_char_p
        return fn().decode()
    except Exception:  # noqa: BLE001 - version is informative only
        return None


def build(kind: str, request: dict, seed: int, soundfont: str, outputs: dict) -> dict:
    """kind: track | sequence | mix.  request: the canonical inputs.  outputs: {label: path} of files written."""
    return {
        "generator": "bgmstudio", "version": __version__, "kind": kind,
        "created_utc": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "seed": seed, "request": request,
        "method": "Composed algorithmically (seeded procedural composer, no training data or sampled recordings "
                  "of other music); rendered with FluidSynth from the SoundFont below.",
        "soundfont": soundfont_record(soundfont), "fluidsynth": fluidsynth_version(),
        "outputs": {k: {"file": os.path.basename(p), "bytes": os.path.getsize(p), "sha256": file_sha256(p)}
                    for k, p in outputs.items()},
    }
