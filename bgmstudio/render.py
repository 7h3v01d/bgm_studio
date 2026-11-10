# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""Plan -> audio, using FluidSynth driven sample-accurately from Python.

Seamless loops: the plan guarantees every note ends on or before the last bar
line.  We render the track plus a few seconds of *post-roll* (release + reverb
tail) and then add that tail onto the start of the file.  That is exactly what
the audio would be if the loop were already playing, so the wrap point carries
no click, no cut-off tail and no gap.
"""
from __future__ import annotations

import os
import struct
from typing import Iterator

import numpy as np

import dataclasses

from .compose import CH_BASS, CH_DRUM, CH_KEYS, CH_MEL, CH_PAD, CH_SPARK, Plan

# Instrument stems: name -> MIDI channels.
# FluidSynth reuses voice slots, and a reused voice carries a little state from the note it played before into the
# first moments of the next one.  So a full render and the sum of per-group renders differ slightly at note attacks
# (measured up to ~20 dB under the music in a 50 ms window on drum-heavy moods).  For exact stems the mix is
# therefore *built from* the group renders (render_split); each group render is deterministic, so rendering a group
# again later gives the identical audio.
STEM_GROUPS = {"pad": (CH_PAD,), "bass": (CH_BASS,), "keys": (CH_KEYS,), "melody": (CH_MEL,),
               "sparkle": (CH_SPARK,), "drums": (CH_DRUM,)}

SR = 44100
SYNTH_GAIN = 0.6
LOOP_TAIL_SECONDS = 9.0

_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Folders scanned for any *.sf2 (first match wins; preferred fonts sorted first).
_SF_DIRS = [os.path.join(_PROJECT, "soundfonts"), "~/.bgmstudio", "~/.bgmstudio/soundfonts",
            "/usr/share/sounds/sf2", "/usr/share/soundfonts", "/opt/homebrew/share/soundfonts",
            "/usr/local/share/soundfonts"]
_PREFERRED = ("generaluser", "fluidr3", "default")


def find_soundfont(explicit: str | None = None) -> str:
    for c in (explicit, os.environ.get("BGM_SOUNDFONT")):
        if c:
            p = os.path.expanduser(c)
            if os.path.isfile(p):
                return p
            raise FileNotFoundError(f"SoundFont not found at {c!r} (from BGM_SOUNDFONT / argument)")
    found = []
    for d in _SF_DIRS:
        d = os.path.expanduser(d)
        if os.path.isdir(d):
            found += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith(".sf2")]
    if found:
        found.sort(key=lambda p: next((i for i, k in enumerate(_PREFERRED) if k in os.path.basename(p).lower()),
                                      len(_PREFERRED)))
        return found[0]
    raise FileNotFoundError(
        "No SoundFont (.sf2) found. Download a General MIDI SoundFont (e.g. GeneralUser GS or FluidR3_GM) and "
        f"put the .sf2 file in:  {os.path.join(_PROJECT, 'soundfonts')}  "
        "(or set BGM_SOUNDFONT=C:\\path\\to\\font.sf2).")


def _prepare_fluidsynth():
    """Make the FluidSynth shared library discoverable (mainly for Windows, where it is not on PATH).
    Looks in $FLUIDSYNTH_DIR, <project>/fluidsynth[/bin], ~/.bgmstudio/fluidsynth[/bin]."""
    dirs = [os.environ.get("FLUIDSYNTH_DIR")]
    for base in (os.path.join(_PROJECT, "fluidsynth"), os.path.expanduser("~/.bgmstudio/fluidsynth")):
        dirs += [base, os.path.join(base, "bin")]
        if os.path.isdir(base):  # e.g. fluidsynth/fluidsynth-v2.x.x-win10-x64/bin
            for sub in sorted(os.listdir(base)):
                dirs += [os.path.join(base, sub), os.path.join(base, sub, "bin")]
    for d in dirs:
        if d and os.path.isdir(d) and any(f.lower().startswith(("libfluidsynth", "fluidsynth"))
                                          and f.lower().endswith(".dll") for f in os.listdir(d)):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(d)
            return d
    return None


def _import_fluidsynth():
    _prepare_fluidsynth()
    try:
        import fluidsynth
        return fluidsynth
    except (ImportError, OSError) as e:
        raise RuntimeError(
            "Could not load the FluidSynth library (pyfluidsynth needs the native FluidSynth DLL/so). "
            "Windows: download the FluidSynth Windows x64 release zip, unzip it into "
            f"{os.path.join(_PROJECT, 'fluidsynth')} (so the .dll files end up in its bin folder), or set FLUIDSYNTH_DIR "
            f"to that bin folder. Linux: apt install libfluidsynth3. macOS: brew install fluidsynth. ({e})") from e


def _make_synth(plan: Plan, soundfont: str, sr: int):
    fluidsynth = _import_fluidsynth()
    fs = fluidsynth.Synth(gain=SYNTH_GAIN, samplerate=float(sr))
    sfid = fs.sfload(soundfont)
    if sfid < 0:
        raise RuntimeError(f"Could not load SoundFont {soundfont}")
    for ch, prog in plan.programs.items():
        fs.program_select(ch, sfid, 0, prog)
    fs.program_select(9, sfid, 128, 0)
    for ch, cc in plan.channel_cc.items():
        fs.cc(ch, 7, cc["vol"])
        fs.cc(ch, 10, cc["pan"])
        fs.cc(ch, 91, cc["rev"])
    room, damp, width, level = plan.reverb
    fs.set_reverb(room, damp, width, level)
    return fs


def _gen(fs, n: int) -> np.ndarray:
    a = np.asarray(fs.get_samples(int(n)), dtype=np.float32) / 32768.0
    return a.reshape(-1, 2)


def _iter_audio(plan: Plan, fs, sr: int, tail_samples: int) -> Iterator[np.ndarray]:
    spb = 60.0 / plan.bpm
    ev = []
    for n in plan.notes:
        on = int(round(n.start * spb * sr))
        off = max(on + 1, int(round((n.start + n.dur) * spb * sr)))
        ev.append((on, 1, n.ch, n.pitch, n.vel))
        ev.append((off, 0, n.ch, n.pitch, 0))
    ev.sort()
    total = int(round(plan.duration * sr))
    target = total + tail_samples
    cur = 0
    for s, typ, ch, p, v in ev:
        s = min(s, target)
        if s > cur:
            yield _gen(fs, s - cur)
            cur = s
        if typ:
            fs.noteon(ch, p, v)
        else:
            fs.noteoff(ch, p)
    if target > cur:
        yield _gen(fs, target - cur)


def section_envelope(plan: Plan, sr: int = SR):
    """Gain envelope from plan.section_db (intensity), or None.  -> f(start_sample, n) -> float32 gains.

    Each section holds its level; the change ramps over the bar *before* the boundary so the new level lands on
    the downbeat.  Loops ramp back to the first section's level in the final bar, so the seam stays seamless
    (samples past the end - the folded loop tail - use the first section's level, matching where they land)."""
    if not plan.section_db or all(abs(d) < 1e-9 for d in plan.section_db):
        return None
    spb = 60.0 / plan.bpm
    total = plan.duration * sr
    bar = 4 * spb * sr
    xs, ys = [0.0], [plan.section_db[0]]
    for (_, start_bar, _), prev_db, db in zip(plan.sections[1:], plan.section_db, plan.section_db[1:]):
        t = start_bar * 4 * spb * sr
        xs += [max(xs[-1], t - bar), t]
        ys += [prev_db, db]
    if plan.loop:
        xs += [max(xs[-1], total - bar), total]
        ys += [plan.section_db[-1], plan.section_db[0]]
    xp, fp = np.asarray(xs), 10 ** (np.asarray(ys) / 20.0)

    def env(start: int, n: int) -> np.ndarray:
        return np.interp(np.arange(start, start + n, dtype=np.float64), xp, fp).astype(np.float32)
    return env


def _apply_envelope(audio: np.ndarray, env, chunk: int = 1 << 20) -> None:
    for i in range(0, len(audio), chunk):
        blk = audio[i:i + chunk]
        blk *= env(i, len(blk))[:, None]


def _fade_curve(n: int) -> np.ndarray:
    x = np.linspace(0.0, 1.0, n, endpoint=True, dtype=np.float32)
    return 0.5 * (1.0 + np.cos(np.pi * x))


def render_audio(plan: Plan, soundfont: str | None = None, sr: int = SR) -> np.ndarray:
    """Render to float32 stereo of *exactly* round(duration*sr) samples."""
    sf = find_soundfont(soundfont)
    fs = _make_synth(plan, sf, sr)
    try:
        total = int(round(plan.duration * sr))
        tail = int(LOOP_TAIL_SECONDS * sr) if plan.loop else 0
        audio = np.concatenate(list(_iter_audio(plan, fs, sr, tail)), axis=0)
    finally:
        fs.delete()
    env = section_envelope(plan, sr)
    if env is not None:
        _apply_envelope(audio, env)
    main, post = audio[:total].copy(), audio[total:]
    if plan.loop:
        pos = 0
        while pos < len(post):  # fold repeatedly in case the loop is shorter than the tail
            seg = post[pos:pos + total]
            main[:len(seg)] += seg
            pos += total
    elif not plan.open_end:
        n = int(min(plan.fade_out, plan.duration * 0.3) * sr)
        if n > 1:
            main[-n:] *= _fade_curve(n)[:, None]
    return main


def render_split(plan: Plan, soundfont: str | None = None, sr: int = SR) -> np.ndarray:
    """The mix as the sum of separately rendered instrument groups (see STEM_GROUPS): what stems add up to."""
    total = None
    for sp in stem_plans(plan).values():
        a = render_audio(sp, soundfont, sr)
        if total is None:
            total = a
        else:
            total += a
    if total is None:  # no notes at all
        return np.zeros((int(round(plan.duration * sr)), 2), dtype=np.float32)
    return total


def stem_plans(plan: Plan) -> dict:
    """-> {stem name: plan holding only that group's notes}, skipping groups with no notes."""
    out = {}
    for name, chans in STEM_GROUPS.items():
        notes = [n for n in plan.notes if n.ch in chans]
        if notes:
            out[name] = dataclasses.replace(plan, notes=notes)
    return out


def stream_wav(plan: Plan, gain_db: float = 0.0, soundfont: str | None = None,
               sr: int = SR, block_seconds: float = 0.5) -> tuple[int, Iterator[bytes]]:
    """Progressive 16-bit WAV.  Returns (content_length, byte iterator).

    Audio is produced as fast as the synth runs, so the first bytes arrive
    almost immediately and the whole thing finishes far quicker than real time.
    Loop folding needs the finished render, so streaming is always non-loop
    (fade-out ending); use render_audio() for seamless loop files.
    """
    total = int(round(plan.duration * sr))
    data_len = total * 4
    header = (b"RIFF" + struct.pack("<I", 36 + data_len) + b"WAVEfmt " +
              struct.pack("<IHHIIHH", 16, 1, 2, sr, sr * 4, 4, 16) + b"data" + struct.pack("<I", data_len))
    gain = 10 ** (gain_db / 20.0)
    fade_n = int(min(plan.fade_out, plan.duration * 0.3) * sr)
    fade = _fade_curve(fade_n) if fade_n > 1 else None
    env = section_envelope(plan, sr)

    def gen() -> Iterator[bytes]:
        yield header
        fs = _make_synth(plan, find_soundfont(soundfont), sr)
        try:
            pos, buf, buffered = 0, [], 0
            for blk in _iter_audio(plan, fs, sr, 0):
                buf.append(blk)
                buffered += len(blk)
                if buffered < block_seconds * sr:
                    continue
                out = np.concatenate(buf, axis=0)
                buf, buffered = [], 0
                yield _to_pcm(out, pos, total, gain, fade, fade_n, env)
                pos += len(out)
            if buf:
                out = np.concatenate(buf, axis=0)
                yield _to_pcm(out, pos, total, gain, fade, fade_n, env)
        finally:
            fs.delete()

    return len(header) + data_len, gen()


def _to_pcm(block, pos, total, gain, fade, fade_n, env=None) -> bytes:
    block = block * gain
    if env is not None:
        block *= env(pos, len(block))[:, None]
    if fade is not None:
        start_fade = total - fade_n
        lo = max(pos, start_fade)
        hi = pos + len(block)
        if hi > lo:
            block[lo - pos:] *= fade[lo - start_fade:hi - start_fade][:, None]
    return (np.clip(block, -0.999, 0.999) * 32767.0).astype("<i2").tobytes()
