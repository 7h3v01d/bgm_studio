"""Musical building blocks and mood presets.

Everything the composer knows about style lives here, so adding a mood is a
data change, not a code change.  GM program numbers are 0-based.
"""
from __future__ import annotations

SCALES = {
    "major":      [0, 2, 4, 5, 7, 9, 11],
    "minor":      [0, 2, 3, 5, 7, 8, 10],
    "dorian":     [0, 2, 3, 5, 7, 9, 10],
    "lydian":     [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "phrygian":   [0, 1, 3, 5, 7, 8, 10],
}

# Four-chord progressions as 0-based scale degrees (0 = I/i, 3 = IV/iv, ...).
PROGS = {
    "major":      [[0, 4, 5, 3], [0, 5, 3, 4], [5, 3, 0, 4], [0, 3, 4, 3], [0, 2, 3, 4], [0, 3, 5, 4]],
    "lydian":     [[0, 1, 0, 1], [0, 1, 4, 0], [0, 5, 1, 4]],
    "mixolydian": [[0, 6, 3, 0], [0, 3, 6, 3], [0, 4, 6, 3]],
    "minor":      [[0, 5, 2, 6], [0, 6, 5, 6], [0, 3, 6, 2], [5, 2, 6, 0], [0, 2, 5, 6]],
    "dorian":     [[0, 3, 0, 3], [0, 3, 6, 3], [0, 6, 3, 0], [0, 1, 3, 0]],
    "phrygian":   [[0, 1, 0, 1], [0, 1, 6, 0], [0, 5, 1, 0]],
}

# Bass: (step_on_16th_grid, length_in_steps, semitone_offset_from_root)
BASS_PATTERNS = {
    "whole":      [(0, 16, 0)],
    "half":       [(0, 8, 0), (8, 8, 0)],
    "pulse8":     [(s, 2, 0) for s in range(0, 16, 2)],
    "root_fifth": [(0, 6, 0), (8, 6, 7), (14, 2, 12)],
    "syncopated": [(0, 3, 0), (6, 3, 0), (10, 4, 7), (14, 2, 12)],
    "walk":       [(0, 4, 0), (4, 4, 7), (8, 4, 12), (12, 4, 7)],
    "driving":    [(0, 2, 0), (2, 2, 12), (4, 2, 0), (6, 2, 12), (8, 2, 0), (10, 2, 12), (12, 2, 0), (14, 2, 12)],
}

# Keys: arpeggios (idx into chord tones, last entries = octave doublings) or chord comping hits.
KEYS_PATTERNS = {
    "arp8":      {"type": "arp", "step": 2, "idx": [0, 1, 2, 3, 2, 1, 2, 1], "gate": 1.5},
    "arp8b":     {"type": "arp", "step": 2, "idx": [0, 2, 1, 3, 0, 2, 1, 2], "gate": 1.5},
    "arp16":     {"type": "arp", "step": 1, "idx": [0, 1, 2, 3, 2, 1, 2, 3, 0, 1, 2, 3, 2, 1, 0, 1], "gate": 1.6},
    "arp_slow":  {"type": "arp", "step": 4, "idx": [0, 1, 2, 3], "gate": 3.2},
    "comp_lofi": {"type": "comp", "hits": [(0, 6), (7, 3), (10, 4)]},
    "comp_sync": {"type": "comp", "hits": [(0, 3), (3, 3), (6, 4), (10, 3)]},
    "comp_off":  {"type": "comp", "hits": [(2, 2), (6, 2), (10, 2), (14, 2)]},
}

# Drums on GM channel 10.  "core" = kick/snare-ish, "color" = hats/shakers.
# Each voice: (gm_note, steps_in_bar_on_16th_grid, vel_lo, vel_hi)
DRUM_STYLES = {
    "lofi":      {"core": [(36, [0, 10], 78, 92), (38, [4, 12], 62, 78)],
                  "color": [(42, [0, 2, 4, 6, 8, 10, 12, 14], 38, 62), (37, [15], 35, 50)], "fill": 38},
    "pop":       {"core": [(36, [0, 6, 8, 11], 82, 100), (38, [4, 12], 80, 96)],
                  "color": [(42, [0, 2, 4, 6, 8, 10, 12, 14], 50, 72), (46, [14], 55, 65)], "fill": 38},
    "fourfloor": {"core": [(36, [0, 4, 8, 12], 92, 104), (39, [4, 12], 75, 90)],
                  "color": [(42, [2, 6, 10, 14], 55, 72), (42, [1, 3, 5, 7, 9, 11, 13, 15], 25, 38)], "fill": 38},
    "epic":      {"core": [(36, [0, 8], 96, 110), (45, [12], 85, 100)],
                  "color": [(54, [0, 4, 8, 12], 35, 50)], "fill": 45},
    "minimal":   {"core": [(36, [0, 6], 68, 82), (37, [12], 55, 70)],
                  "color": [(42, [4, 10, 14], 30, 48)], "fill": 37},
}

# Layers per section kind.
LAYERS = {
    "intro": ["pad", "keys_lite", "spark"],
    "verse": ["pad", "bass", "keys", "drums_lite", "mel_verse"],
    "build": ["pad", "bass", "keys", "drums", "spark"],
    "peak":  ["pad", "bass", "keys", "drums", "mel", "spark"],
    "break": ["pad", "keys_lite", "mel_sparse", "spark"],
    "outro": ["pad", "keys_lite", "spark"],
}
KIND_GAIN = {"intro": 0.72, "verse": 0.85, "build": 0.92, "peak": 1.0, "break": 0.70, "outro": 0.65}

# Channels: 0 pad, 1 bass, 2 keys, 3 melody, 4 sparkle, 9 drums.
PRESETS = {
    "calm": {
        "desc": "Soft piano and warm pads, slow and spacious. Explainers, meditation, documentaries.",
        "bpm": (60, 76), "modes": {"major": 3, "lydian": 2, "mixolydian": 1},
        "key_pcs": [0, 2, 3, 5, 7, 8, 9, 10], "seventh": True, "bpc": 2,
        "programs": {"pad": 89, "bass": 32, "keys": 0, "mel": 73, "spark": 8},
        "drums": None, "bass_patterns": ["whole", "half"], "keys_patterns": ["arp_slow", "arp8"],
        "mel_density": "sparse", "mel_in_verse": True, "swing": 0.0,
        "reverb": (0.8, 0.35, 0.9, 0.6),
        "mix": {"pad": 85, "bass": 90, "keys": 95, "mel": 95, "spark": 80, "drums": 80},
        "cal": -27.6,
    },
    "lofi": {
        "desc": "Dusty e-piano, swung beat, mellow bass. Study/chill/tutorial backgrounds.",
        "bpm": (68, 84), "modes": {"dorian": 3, "minor": 3, "major": 2, "mixolydian": 1},
        "key_pcs": [0, 2, 3, 5, 7, 8, 9, 10], "seventh": True, "bpc": 1,
        "programs": {"pad": 89, "bass": 33, "keys": 4, "mel": 11, "spark": 9},
        "drums": "lofi", "bass_patterns": ["syncopated", "root_fifth", "half"],
        "keys_patterns": ["comp_lofi", "comp_sync", "arp8"],
        "mel_density": "medium", "mel_in_verse": True, "swing": 0.22,
        "reverb": (0.6, 0.45, 0.8, 0.35),
        "mix": {"pad": 70, "bass": 100, "keys": 100, "mel": 95, "spark": 75, "drums": 85},
        "cal": -25.9,
    },
    "cinematic": {
        "desc": "Strings, cello, harp, big drums and reverb. Documentaries, history, storytelling.",
        "bpm": (62, 84), "modes": {"minor": 4, "dorian": 1, "phrygian": 1},
        "key_pcs": [0, 2, 3, 5, 7, 9, 10], "seventh": False, "bpc": 2,
        "programs": {"pad": 48, "bass": 42, "keys": 46, "mel": 40, "spark": 14},
        "drums": "epic", "bass_patterns": ["whole", "pulse8", "half"],
        "keys_patterns": ["arp8", "arp_slow", "arp8b"],
        "mel_density": "medium", "mel_in_verse": False, "swing": 0.0,
        "reverb": (0.9, 0.3, 1.0, 0.75),
        "mix": {"pad": 100, "bass": 105, "keys": 90, "mel": 100, "spark": 80, "drums": 95},
        "cal": -17.5,
    },
    "uplifting": {
        "desc": "Bright guitar arpeggios, pop beat, marimba hook. Motivation, product, travel.",
        "bpm": (104, 124), "modes": {"major": 4, "mixolydian": 1, "lydian": 1},
        "key_pcs": [0, 2, 4, 5, 7, 9, 10], "seventh": False, "bpc": 1,
        "programs": {"pad": 89, "bass": 33, "keys": 24, "mel": 12, "spark": 9},
        "drums": "pop", "bass_patterns": ["root_fifth", "walk", "driving"],
        "keys_patterns": ["arp8", "arp8b", "arp16"],
        "mel_density": "medium", "mel_in_verse": True, "swing": 0.0,
        "reverb": (0.55, 0.45, 0.85, 0.3),
        "mix": {"pad": 75, "bass": 100, "keys": 100, "mel": 100, "spark": 80, "drums": 90},
        "cal": -26.1,
    },
    "corporate": {
        "desc": "Clean piano, light pulse, vibraphone. Presentations, explainers, B2B.",
        "bpm": (100, 116), "modes": {"major": 5, "mixolydian": 1},
        "key_pcs": [0, 2, 4, 5, 7, 9, 10], "seventh": False, "bpc": 1,
        "programs": {"pad": 88, "bass": 33, "keys": 0, "mel": 11, "spark": 9},
        "drums": "pop", "bass_patterns": ["root_fifth", "half", "walk"],
        "keys_patterns": ["arp16", "arp8", "arp8b"],
        "mel_density": "medium", "mel_in_verse": False, "swing": 0.0,
        "reverb": (0.5, 0.5, 0.8, 0.3),
        "mix": {"pad": 75, "bass": 95, "keys": 100, "mel": 95, "spark": 80, "drums": 80},
        "cal": -27.7,
    },
    "dark": {
        "desc": "Brooding synth bass, sweeping pads, music-box glints. True crime, mystery, tension.",
        "bpm": (64, 92), "modes": {"minor": 3, "phrygian": 3, "dorian": 1},
        "key_pcs": [0, 1, 2, 3, 5, 7, 9, 10], "seventh": True, "bpc": 2,
        "programs": {"pad": 95, "bass": 38, "keys": 4, "mel": 0, "spark": 10},
        "drums": "minimal", "bass_patterns": ["whole", "half", "pulse8"],
        "keys_patterns": ["arp_slow", "arp8b"],
        "mel_density": "sparse", "mel_in_verse": False, "swing": 0.0,
        "reverb": (0.9, 0.35, 1.0, 0.7),
        "mix": {"pad": 90, "bass": 105, "keys": 85, "mel": 95, "spark": 85, "drums": 85},
        "cal": -29.4,
    },
    "ambient": {
        "desc": "Slow evolving pads, harp, celesta. Sleep, focus, nature, long-form backgrounds.",
        "bpm": (50, 64), "modes": {"lydian": 3, "major": 2, "dorian": 1},
        "key_pcs": [0, 2, 3, 5, 7, 8, 9, 10], "seventh": True, "bpc": 2,
        "programs": {"pad": 89, "bass": 33, "keys": 46, "mel": 73, "spark": 8},
        "drums": None, "bass_patterns": ["whole"], "keys_patterns": ["arp_slow"],
        "mel_density": "sparse", "mel_in_verse": False, "swing": 0.0,
        "reverb": (0.95, 0.3, 1.0, 0.8),
        "mix": {"pad": 100, "bass": 80, "keys": 85, "mel": 80, "spark": 85, "drums": 70},
        "cal": -22.3,
    },
    "tech": {
        "desc": "Glassy arps, synth bass, four-on-the-floor. Tech reviews, AI, futurism.",
        "bpm": (116, 128), "modes": {"minor": 3, "dorian": 2},
        "key_pcs": [0, 2, 3, 5, 7, 9, 10], "seventh": False, "bpc": 1,
        "programs": {"pad": 90, "bass": 39, "keys": 98, "mel": 80, "spark": 9},
        "drums": "fourfloor", "bass_patterns": ["pulse8", "driving", "syncopated"],
        "keys_patterns": ["arp16", "arp8", "comp_off"],
        "mel_density": "medium", "mel_in_verse": False, "swing": 0.0,
        "reverb": (0.5, 0.5, 0.8, 0.28),
        "mix": {"pad": 80, "bass": 100, "keys": 85, "mel": 75, "spark": 80, "drums": 90},
        "cal": -24.8,
    },
}

ALIASES = {
    "chill": "lofi", "study": "lofi", "focus": "calm", "relaxing": "calm", "peaceful": "calm",
    "epic": "cinematic", "documentary": "cinematic", "history": "cinematic",
    "happy": "uplifting", "positive": "uplifting", "motivational": "uplifting",
    "business": "corporate", "presentation": "corporate",
    "tension": "dark", "suspense": "dark", "mystery": "dark", "true_crime": "dark",
    "space": "ambient", "sleep": "ambient", "nature": "ambient",
    "electronic": "tech", "technology": "tech", "futuristic": "tech",
}


def resolve_mood(name: str):
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    key = ALIASES.get(key, key)
    if key not in PRESETS:
        raise ValueError(f"Unknown mood {name!r}. Available: {', '.join(sorted(PRESETS))} "
                         f"(aliases: {', '.join(sorted(ALIASES))})")
    return key, PRESETS[key]


def describe_moods():
    return {k: v["desc"] for k, v in PRESETS.items()}
