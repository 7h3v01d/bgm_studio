# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""Narration length for the sequencer (to check scene totals before sending anything to the service)."""
from __future__ import annotations

import subprocess


def audio_seconds(path: str) -> float:
    """Length of an audio file in seconds: soundfile for WAV/FLAC/OGG, ffprobe for everything else."""
    try:
        import soundfile
        info = soundfile.info(path)
        if info.samplerate and info.frames:
            return info.frames / info.samplerate
    except Exception:  # noqa: BLE001 - not a format soundfile reads; try ffprobe
        pass
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                            "default=nw=1:nk=1", path], capture_output=True, text=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return float(r.stdout.strip())
    except FileNotFoundError:
        raise ValueError("ffprobe is needed to read this audio format (or use WAV/FLAC).") from None
    except (ValueError, subprocess.TimeoutExpired):
        raise ValueError("Could not read the narration's length; is it an audio file?") from None
