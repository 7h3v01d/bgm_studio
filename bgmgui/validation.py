# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""Input validation for the GUI.  No Qt imports, so it is testable without a display."""
from __future__ import annotations

import re
from pathlib import Path

MOODS = ('calm', 'lofi', 'cinematic', 'uplifting', 'corporate', 'dark',
         'ambient', 'tech', 'horror', 'sleep', 'folklore', 'suspense')
FORMATS = ('wav', 'flac', 'mp3', 'm4a', 'ogg')


def parse_seed(seed: str):
    """Blank -> None (a new piece each time); otherwise an integer."""
    if not seed.strip():
        return None
    if not re.fullmatch(r'[+-]?\d+', seed.strip()):
        raise ValueError('Seed must be an integer or blank for a random seed.')
    return int(seed.strip())


def validate_track(mood: str, seconds: str, seed: str, intensity: float, fmt: str, moods=None) -> dict:
    """Pure validation for user inputs; server enforces its own independent limits.
    `moods`: the server's mood list once connected (defaults to the built-in list)."""
    if mood not in (moods or MOODS):
        raise ValueError('Select a supported mood.')
    try:
        duration = float(seconds)
    except (ValueError, TypeError):
        raise ValueError('Duration must be a number of seconds.') from None
    if not 4 <= duration <= 7200 or not duration < float('inf'):
        raise ValueError('Duration must be between 4 and 7200 seconds.')
    if not 0 <= intensity <= 1:
        raise ValueError('Intensity must be between 0 and 1.')
    if fmt not in FORMATS:
        raise ValueError('Select a supported audio format.')
    seed_value = parse_seed(seed)
    return {'mood': mood, 'duration': duration, 'seed': seed_value,
            'intensity': round(float(intensity), 3), 'format': fmt}


def export_path(folder: str, stem: str, fmt: str) -> Path:
    folder_path = Path(folder).expanduser()
    if not folder_path.is_dir():
        raise ValueError('Choose an existing output folder.')
    name = stem.strip()
    if not name or name in ('.', '..') or any(c in name for c in '<>:"/\\|?*') or name.endswith(('.', ' ')):
        raise ValueError('Enter a valid Windows filename without an extension.')
    if len(name) > 140:
        raise ValueError('Output filename is too long.')
    if name.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL', *{f'COM{i}' for i in range(1, 10)}, *{f'LPT{i}' for i in range(1, 10)}}:
        raise ValueError('That filename is reserved by Windows.')
    return folder_path / f'{name}.{fmt}'
