"""Procedural composer: mood + duration + seed  ->  a complete note plan.

Design goals
  * Exact duration: tempo is nudged so a whole number of 4/4 bars equals the
    requested length to the sample.
  * Deterministic: same (mood, duration, seed, ...) -> identical notes.
  * Loop-safe: with loop=True no note outlives the final bar, so the renderer can
    fold the release/reverb tail back onto the start (see render.py).  The final
    chord is the one that naturally resolves back to bar 1.
  * Long-form: sections (intro/verse/build/peak/break/outro) layer instruments in
    and out, and a new "movement" (fresh progressions/patterns) starts every six
    sections so a 30-minute bed doesn't feel like one 30-second loop.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .presets import (BASS_PATTERNS, DRUM_STYLES, KEYS_PATTERNS, KIND_GAIN, LAYERS,
                      PROGS, SCALES, resolve_mood)

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_FLATS = {"DB": 1, "EB": 3, "GB": 6, "AB": 8, "BB": 10}
CH_PAD, CH_BASS, CH_KEYS, CH_MEL, CH_SPARK, CH_DRUM = 0, 1, 2, 3, 4, 9
MIN_SECONDS, MAX_SECONDS = 4.0, 7200.0
SECTION_BARS = 8
MOVEMENT_EVERY = 6  # sections


@dataclass
class Note:
    start: float  # beats
    dur: float    # beats
    pitch: int
    vel: int
    ch: int


@dataclass
class Plan:
    mood: str
    seed: int
    key: str
    mode: str
    bpm: float
    bars: int
    duration: float
    loop: bool
    fade_out: float
    notes: list
    programs: dict
    channel_cc: dict
    reverb: tuple
    sections: list
    cal_lufs: float = -22.0

    @property
    def total_beats(self) -> float:
        return self.bars * 4.0

    def summary(self) -> dict:
        return {"mood": self.mood, "seed": self.seed, "key": f"{self.key} {self.mode}",
                "bpm": round(self.bpm, 2), "bars": self.bars, "duration": self.duration,
                "loop": self.loop, "sections": [s[0] for s in self.sections], "notes": len(self.notes)}


# ---------------------------------------------------------------- theory helpers
def parse_key(key: str) -> int:
    k = key.strip().upper().replace("♯", "#").replace("♭", "B")
    if k in _FLATS:
        return _FLATS[k]
    names = [n.upper() for n in NOTE_NAMES]
    if k in names:
        return names.index(k)
    raise ValueError(f"Unknown key {key!r}; use e.g. C, F#, Bb")


def scale_pitch(root: int, scale: list, idx: int) -> int:
    octv, deg = divmod(idx, 7)
    return root + scale[deg] + 12 * octv


def chord_from_degree(root: int, scale: list, degree: int, seventh: bool) -> list:
    idxs = [degree, degree + 2, degree + 4] + ([degree + 6] if seventh else [])
    return [scale_pitch(root, scale, i) for i in idxs]


class Voicer:
    """Voice-leads chords inside [lo, hi] choosing the smoothest inversion."""

    def __init__(self, lo: int, hi: int):
        self.lo, self.hi, self.prev = lo, hi, None

    def voice(self, chord: list) -> list:
        pcs = [p % 12 for p in chord]
        n = len(pcs)
        best, best_cost = None, 1e9
        for inv in range(n):
            order = pcs[inv:] + pcs[:inv]
            for k in range(0, 9):
                notes, cur = [], None
                for pc in order:
                    if cur is None:
                        p = pc + 12 * k
                    else:
                        p = pc
                        while p <= cur:
                            p += 12
                    notes.append(p)
                    cur = p
                if notes[0] < self.lo or notes[-1] > self.hi:
                    continue
                if self.prev is None:
                    cost = abs(sum(notes) / n - (self.lo + self.hi) / 2)
                elif len(self.prev) == n:
                    cost = sum(abs(a - b) for a, b in zip(notes, self.prev))
                else:
                    cost = abs(sum(notes) / n - sum(self.prev) / len(self.prev)) * n
                if cost < best_cost:
                    best, best_cost = notes, cost
        if best is None:  # range too tight: fall back to plain stack
            best = sorted(self.lo + ((p - self.lo) % 12) for p in chord)
        self.prev = best
        return best


# ---------------------------------------------------------------- structure
def fit_bars(duration: float, target_bpm: float):
    bar_s = 240.0 / target_bpm
    bars = max(2, round(duration / bar_s))
    return bars, bars * 240.0 / duration


def plan_sections(bars: int, loop: bool):
    """-> list of (kind, start_bar, n_bars)."""
    if bars < SECTION_BARS:
        return [("peak", 0, bars)]
    n, rem = divmod(bars, SECTION_BARS)
    sizes = [SECTION_BARS] * n
    if rem:
        if rem >= 4:
            sizes.append(rem)
        else:
            sizes[-1] += rem
    count = len(sizes)
    if count == 1:
        kinds = ["peak"]
    elif count == 2:
        kinds = ["verse", "peak"]
    else:
        last = "break" if loop else "outro"
        m = count - 2
        if m == 1:
            mid = ["peak"]
        elif m == 2:
            mid = ["verse", "peak"]
        elif m == 3:
            mid = ["verse", "build", "peak"]
        else:
            cyc = ["verse", "build", "peak", "peak", "break", "verse", "build", "peak"]
            mid = [cyc[i % len(cyc)] for i in range(m)]
        kinds = ["intro"] + mid + [last]
    out, pos = [], 0
    for kind, size in zip(kinds, sizes):
        out.append((kind, pos, size))
        pos += size
    return out


# ---------------------------------------------------------------- melody
def _gen_phrase(rng, scale, root_pc, degs, bpc, density):
    """One progression-long melodic phrase -> list per bar of (step, len, pitch, vel)."""
    mel_root = 60 + root_pc

    def pitch(i):
        return scale_pitch(mel_root, scale, i)

    valid = [i for i in range(-14, 35) if 64 <= pitch(i) <= 86]
    phrase_bars = len(degs) * bpc
    rhythms = {
        "sparse": [[(0, 8), (8, 8)], [(0, 6), (8, 4), (12, 4)], [(4, 4), (8, 8)], [(0, 12)], [(2, 6), (8, 8)]],
        "medium": [[(0, 4), (4, 4), (8, 4), (12, 4)], [(0, 6), (6, 2), (8, 4), (12, 4)],
                   [(0, 4), (4, 2), (6, 2), (8, 8)], [(2, 2), (4, 4), (8, 2), (10, 2), (12, 4)]],
        "dense":  [[(0, 2), (2, 2), (4, 4), (8, 2), (10, 2), (12, 4)],
                   [(0, 4), (4, 2), (6, 2), (8, 4), (10, 2), (12, 2), (14, 2)]],
    }
    pool, calm_pool = rhythms[density], rhythms["sparse"]
    cur = min(valid, key=lambda i: abs(pitch(i) - (mel_root + 7 + 12)))
    out = []
    for b in range(phrase_bars):
        d = degs[b // bpc]
        chord_idx = [i for i in valid if (i - d) % 7 in (0, 2, 4)]
        if density == "sparse" and b > 0 and rng.random() < 0.25:
            out.append([])
            continue
        rhythm = rng.choice(calm_pool if b % 4 == 3 else pool)
        bar = []
        for j, (step, ln) in enumerate(rhythm):
            if step % 4 == 0:
                ranked = sorted(chord_idx, key=lambda i: abs(i - cur))
                cur = ranked[0] if (len(ranked) < 2 or rng.random() < 0.6) else ranked[1]
            else:
                nxt = cur + rng.choices([-2, -1, 0, 1, 2], [1, 3, 1, 3, 1])[0]
                if nxt in valid:
                    cur = nxt
            vel = 78 + (8 if step % 4 == 0 else 0) + rng.randint(-4, 4)
            bar.append([step, ln, pitch(cur), vel])
        if b == phrase_bars - 1 and bar:  # resolve on a root
            roots = [i for i in valid if (i - d) % 7 == 0]
            cur = min(roots, key=lambda i: abs(i - cur))
            bar[-1][2] = pitch(cur)
            bar[-1][1] = 16 - bar[-1][0]
        out.append([tuple(x) for x in bar])
    return out


# ---------------------------------------------------------------- composer
def compose(mood: str, duration: float, *, loop: bool = False, seed: int | None = None,
            key: str | None = None, mode: str | None = None, bpm: float | None = None,
            fade_out: float = 3.0) -> Plan:
    name, P = resolve_mood(mood)
    duration = float(duration)
    if not (MIN_SECONDS <= duration <= MAX_SECONDS):
        raise ValueError(f"duration must be between {MIN_SECONDS} and {MAX_SECONDS} seconds")
    seed = int(seed) if seed is not None else random.SystemRandom().randrange(1, 2**31 - 1)
    rng = random.Random(f"{seed}:{name}")

    mode = (mode or rng.choices(list(P["modes"]), weights=list(P["modes"].values()))[0]).lower()
    if mode not in SCALES:
        raise ValueError(f"Unknown mode {mode!r}; choose from {', '.join(SCALES)}")
    scale = SCALES[mode]
    key_pc = parse_key(key) if key else rng.choice(P["key_pcs"])
    root = 48 + key_pc
    target_bpm = float(bpm) if bpm else rng.uniform(*P["bpm"])
    bars, bpm_fit = fit_bars(duration, target_bpm)
    total = bars * 4.0
    bpc, seventh, swing = P["bpc"], P["seventh"], P["swing"]
    drum_style = DRUM_STYLES.get(P["drums"]) if P["drums"] else None
    sections = plan_sections(bars, loop)

    # --- chord segments (bar, n_bars, degree, section index, offset in section)
    movements: dict = {}

    def movement(m):
        if m not in movements:
            r = random.Random(f"{seed}:{name}:mv{m}")
            pool = PROGS[mode]
            a = r.choice(pool)
            b = r.choice([p for p in pool if p != a] or pool)
            movements[m] = {"A": a, "B": b, "bass": r.choice(P["bass_patterns"]),
                            "keys": r.choice(P["keys_patterns"])}
        return movements[m]

    segs = []
    for si, (kind, start, n) in enumerate(sections):
        mv = movement(si // MOVEMENT_EVERY)
        prog = mv["B"] if kind == "build" else mv["A"]
        for r in range(0, n, bpc):
            segs.append({"bar": start + r, "n": min(bpc, n - r), "deg": prog[(r // bpc) % len(prog)],
                         "si": si, "r": r, "kind": kind})
    cadence = (not loop) and bars >= 3
    if cadence:
        kept = []
        for s in segs:
            if s["bar"] + s["n"] <= bars - 2:
                kept.append(s)
            elif s["bar"] < bars - 2:
                kept.append({**s, "n": bars - 2 - s["bar"]})
        last_kind = sections[-1][0]
        si_last = len(sections) - 1
        kept.append({"bar": bars - 2, "n": 1, "deg": 3, "si": si_last, "r": -1, "kind": last_kind})
        kept.append({"bar": bars - 1, "n": 1, "deg": 0, "si": si_last, "r": -2, "kind": "end"})
        segs = kept
    elif not loop:
        segs[-1] = {**segs[-1], "deg": 0}

    # --- note emitters
    rngh = random.Random(f"{seed}:{name}:human")
    notes: list = []

    def add(ch, beat, dur, pitch, vel, hum=0.012):
        start = max(0.0, beat + (rngh.uniform(-hum, hum) if hum else 0.0))
        if start >= total - 0.05:
            return
        end = min(start + dur, total)
        if end - start < 0.04:
            return
        v = max(1, min(127, int(vel) + (rngh.randint(-5, 5) if hum else 0)))
        notes.append(Note(start, end - start, int(pitch), v, ch))

    def t(bar, step):
        return bar * 4.0 + step * 0.25 + (swing * 0.5 if step % 4 == 2 else 0.0)

    pad_v, key_v = Voicer(50, 71), Voicer(55, 76)
    phrases: dict = {}

    def phrase(m, which, variant):
        k = (m, which, variant)
        if k not in phrases:
            mv = movement(m)
            dens = "sparse" if variant == "sparse" else P["mel_density"]
            phrases[k] = _gen_phrase(random.Random(f"{seed}:{name}:mel:{k}"), scale, key_pc,
                                     mv["B" if which == "B" else "A"], bpc, dens)
        return phrases[k]

    spark_p = {"intro": 0.5, "verse": 0.3, "build": 0.6, "peak": 0.8, "break": 0.5, "outro": 0.5, "end": 1.0}
    rsp = random.Random(f"{seed}:{name}:spark")

    for s in segs:
        si, kind = s["si"], s["kind"]
        sec_kind, sec_start, sec_n = sections[si]
        m = si // MOVEMENT_EVERY
        mv = movement(m)
        is_end = kind == "end"
        layers = ["pad", "bass", "keys_end", "spark"] if is_end else list(LAYERS[kind])
        if drum_style is None:
            layers = [l for l in layers if not l.startswith("drums")]
        if not P["mel_in_verse"]:
            layers = [l for l in layers if l != "mel_verse"]
        chord = chord_from_degree(root, scale, s["deg"], seventh)
        pad_notes = pad_v.voice(chord)
        key_notes = key_v.voice(chord)
        bass_pc = chord[0] % 12
        bass_root = 33 + ((bass_pc - 33) % 12)

        for rel in range(s["n"]):
            bar = s["bar"] + rel
            r_in_sec = bar - sec_start
            g = KIND_GAIN["outro" if is_end else sec_kind]
            if sec_kind == "build" and sec_n > 1 and not is_end:
                g = 0.88 + 0.22 * (r_in_sec / (sec_n - 1))
            if is_end:
                g = 0.8

            if "pad" in layers and rel == 0:
                for p in pad_notes:
                    add(CH_PAD, bar * 4.0, s["n"] * 4.0, p, 62 * g, hum=0.0)

            if "bass" in layers:
                pat = [(0, 16, 0)] if is_end else BASS_PATTERNS[mv["bass"]]
                for step, ln, off in pat:
                    p = bass_root + off
                    if p > 52:
                        p -= 12
                    add(CH_BASS, t(bar, step), ln * 0.25 * 0.95, p, 88 * g)

            if "keys_end" in layers:
                for i, p in enumerate(key_notes):
                    add(CH_KEYS, bar * 4.0 + i * 0.06, 15.0, p, 70 * g, hum=0.0)

            if "keys" in layers or "keys_lite" in layers:
                spec = KEYS_PATTERNS[mv["keys"]]
                kv = 72 * g * (0.72 if "keys_lite" in layers else 1.0)
                if spec["type"] == "arp":
                    ext = key_notes + [key_notes[0] + 12] + ([key_notes[1] + 12] if len(key_notes) > 3 else [])
                    for i, idx in enumerate(spec["idx"]):
                        step = i * spec["step"]
                        if step >= 16:
                            break
                        add(CH_KEYS, t(bar, step), spec["step"] * 0.25 * spec["gate"],
                            ext[min(idx, len(ext) - 1)], kv + (7 if step % 4 == 0 else 0))
                else:
                    for step, ln in spec["hits"]:
                        for i, p in enumerate(key_notes):
                            add(CH_KEYS, t(bar, step) + i * 0.02, ln * 0.25, p, kv * 0.95)

            mel_variant = None
            if "mel" in layers:
                mel_variant = "main"
            elif "mel_verse" in layers or "mel_sparse" in layers:
                mel_variant = "sparse"
            if mel_variant and not is_end and r_in_sec >= 0:
                ph = phrase(m, "B" if sec_kind == "build" else "A", mel_variant)
                for step, ln, p, v in ph[r_in_sec % len(ph)]:
                    add(CH_MEL, t(bar, step), ln * 0.25 * 0.97, p, v * g)

            if "spark" in layers and rsp.random() < spark_p[kind if not is_end else "end"]:
                tones = [p for p in chord]
                for j in range(2 if (not is_end and rsp.random() < 0.35) else 1):
                    pc = rsp.choice(tones) % 12
                    p = 72 + ((pc - 72) % 12)
                    step = rsp.choice([0, 6, 10]) + j * 2
                    add(CH_SPARK, t(bar, min(step, 14)), 1.5 if not is_end else 6.0, p, rsp.randint(55, 75) * g)

            if drum_style and not is_end and any(l.startswith("drums") for l in layers):
                full = "drums" in layers
                voices = (drum_style["core"] if full else []) + drum_style["color"]
                for note, steps, vlo, vhi in voices:
                    for step in steps:
                        add(CH_DRUM, t(bar, step), 0.2, note, rngh.randint(vlo, vhi) * g, hum=0.006)
                if full and sec_kind == "build" and r_in_sec == sec_n - 1:
                    for k, step in enumerate(range(8, 16)):
                        add(CH_DRUM, t(bar, step), 0.15, drum_style["fill"], 50 + k * 8, hum=0.004)
                if r_in_sec == 0 and sec_kind in ("peak",) and bar > 0 and "drums" in layers:
                    add(CH_DRUM, bar * 4.0, 2.0, 49, 85, hum=0.0)

    notes.sort(key=lambda n: (n.start, n.ch, n.pitch))
    prog_names = {"pad": CH_PAD, "bass": CH_BASS, "keys": CH_KEYS, "mel": CH_MEL, "spark": CH_SPARK}
    programs = {prog_names[k]: v for k, v in P["programs"].items()}
    pans = {CH_PAD: 64, CH_BASS: 64, CH_KEYS: 52, CH_MEL: 76, CH_SPARK: 88, CH_DRUM: 64}
    revs = {CH_PAD: 95, CH_BASS: 10, CH_KEYS: 60, CH_MEL: 75, CH_SPARK: 105, CH_DRUM: 35}
    mixmap = {CH_PAD: "pad", CH_BASS: "bass", CH_KEYS: "keys", CH_MEL: "mel", CH_SPARK: "spark", CH_DRUM: "drums"}
    channel_cc = {ch: {"vol": P["mix"][mixmap[ch]], "pan": pans[ch], "rev": revs[ch]} for ch in pans}

    return Plan(mood=name, seed=seed, key=NOTE_NAMES[key_pc], mode=mode, bpm=bpm_fit, bars=bars,
                duration=duration, loop=loop, fade_out=fade_out, notes=notes, programs=programs,
                channel_cc=channel_cc, reverb=P["reverb"], sections=sections, cal_lufs=P["cal"])


# ---------------------------------------------------------------- MIDI export
def export_midi(plan: Plan, path: str) -> str:
    import mido
    tpb = 480
    mid = mido.MidiFile(ticks_per_beat=tpb)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(plan.bpm), time=0))
    tr.append(mido.MetaMessage("track_name", name=f"bgmstudio {plan.mood} seed={plan.seed}", time=0))
    for ch, prog in plan.programs.items():
        tr.append(mido.Message("program_change", channel=ch, program=prog, time=0))
    events = []
    for n in plan.notes:
        events.append((round(n.start * tpb), 1, n))
        events.append((round((n.start + n.dur) * tpb), 0, n))
    events.sort(key=lambda e: (e[0], e[1]))
    last = 0
    for tick, on, n in events:
        msg = "note_on" if on else "note_off"
        tr.append(mido.Message(msg, channel=n.ch, note=n.pitch, velocity=n.vel if on else 0, time=tick - last))
        last = tick
    mid.save(path)
    return path
