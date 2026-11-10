# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""REST API.   Run:  uvicorn bgmstudio.api:app --host 0.0.0.0 --port 8765

Optional auth: set BGM_API_KEY and send it as the X-API-Key header.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import secrets
from typing import List, Optional, Union

from fastapi import Request, Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import __version__, service
from .audio import MIME
from .render import find_soundfont

app = FastAPI(title="bgmstudio", version=__version__,
              description="Procedural MIDI background music: exact duration, seamless loops, streaming, voice ducking.")


@app.middleware("http")
async def reject_oversized_multipart(request: Request, call_next):
    # Fail early for clients that advertise a body length; the copy loop still
    # enforces the actual byte cap even when Content-Length is omitted or forged.
    if request.url.path == "/mix" and request.method == "POST":
        advertised = request.headers.get("content-length")
        if advertised is not None:
            try:
                length = int(advertised)
            except ValueError:
                # middleware runs outside FastAPI's exception handling: return the response, don't raise
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "invalid Content-Length"}, status_code=400)
            # Allow limited multipart framing on top of the narration payload.
            if length > service.MAX_NARRATION_BYTES + 1024 * 1024:
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "narration upload too large"}, status_code=413)
    return await call_next(request)


def auth(x_api_key: Optional[str] = Header(default=None)):
    want = os.environ.get("BGM_API_KEY")
    if want and not secrets.compare_digest(x_api_key or "", want):
        raise HTTPException(401, "Invalid or missing X-API-Key")


class BGMRequest(BaseModel):
    mood: str = Field("calm", description="see GET /moods (e.g. calm, lofi, cinematic, dark, horror, sleep, "
                                           "folklore, suspense; aliases accepted)")
    duration: float = Field(60.0, ge=4, le=7200, description="seconds; output is exactly this long")
    loop: bool = Field(False, description="true = seamless loop (no fade); false = cadence ending + fade-out")
    seed: Optional[int] = Field(None, description="same seed + params = same music")
    key: Optional[str] = Field(None, description="e.g. C, F#, Bb")
    mode: Optional[str] = Field(None, description="major, minor, dorian, lydian, mixolydian, phrygian")
    bpm: Optional[float] = Field(None, ge=40, le=200, description="target tempo; nudged to fit the duration")
    format: str = Field("wav", description="wav, flac, mp3, m4a, ogg")
    target_lufs: float = Field(-20.0, ge=-40, le=-8)
    fade_out: float = Field(3.0, ge=0, le=30)
    midi: bool = False
    stems: bool = Field(False, description="also write one file per part that adds up to the main file (see the stems field in the JSON): pad, bass, keys, melody, sparkle, drums")
    intensity: Optional[Union[float, List[float]]] = Field(None, description="0..1 (0.5 = the mood as designed), or a list of 0..1 points spread evenly across the track: a tension curve. Shapes busyness, tempo and section levels.")


class Scene(BaseModel):
    mood: str
    duration: float = Field(..., ge=4, le=7200)
    seed: Optional[int] = None
    mode: Optional[str] = None
    bpm: Optional[float] = Field(None, ge=40, le=200)
    transition: Optional[str] = Field(None, description="transition INTO this scene; overrides the request default")
    intensity: Optional[Union[float, List[float]]] = Field(
        None, description="0..1 or a curve for this scene; also sets its level relative to other scenes")


class SequenceRequest(BaseModel):
    scenes: list[Scene] = Field(..., min_length=1, max_length=300,
                                description="one entry per visual scene; music changes mood at each cut")
    xfade: float = Field(2.0, ge=0, le=10, description="crossfade seconds after each cut")
    seed: Optional[int] = None
    key: Optional[str] = Field(None, description="shared by all scenes; default: auto-picked common key")
    format: str = "wav"
    target_lufs: float = Field(-20.0, ge=-40, le=-8)
    fade_out: float = Field(3.0, ge=0, le=30)
    tempo_match: bool = Field(True, description="pick tempos so neighbouring scenes stay close (2:1 counts as matched)")
    max_bpm_jump: float = Field(6.0, ge=0, le=40)
    transitions: str = Field("none", description="none, riser, impact, riser_impact, downlifter, swell, auto")
    fx_level_db: float = Field(-3.0, ge=-24, le=6, description="transition loudness relative to the music")
    stems: bool = Field(False, description="also write one file per part that adds up to the main file (see the stems field in the JSON): instrument groups plus fx (the transitions)")


def _check_fmt(fmt: str):
    if fmt.lower() not in MIME:
        raise HTTPException(422, f"format must be one of {', '.join(MIME)}")


def _guard(fn, *a, **kw):
    """Map engine errors to HTTP: bad input -> 422; missing setup (SoundFont, FluidSynth, ffmpeg) -> 500 with the
    engine's explanation, so the caller sees what to fix instead of a bare 'Internal Server Error'."""
    try:
        return fn(*a, **kw)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except subprocess.TimeoutExpired as e:
        raise HTTPException(504, f"audio processor timed out: {e.cmd}")
    except TimeoutError as e:  # the render lock: another long render is running
        raise HTTPException(503, f"busy with another render, retry shortly ({e})", headers={"Retry-After": "30"})
    except (FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as e:
        raise HTTPException(500, str(e))


_L = service.LIMITS


def _url(path: str) -> str:
    return f"/files/{os.path.basename(path)}"


def _public(r: dict) -> dict:
    """Engine result -> JSON for clients: server paths become download URLs under /files/."""
    out = {k: v for k, v in r.items() if k not in ("path", "meta_path", "midi_path", "stems")}
    out["file"] = os.path.basename(r["path"])
    out["download_url"] = _url(r["path"])
    out["meta_url"] = _url(r["meta_path"])
    if r.get("midi_path"):
        out["midi_url"] = _url(r["midi_path"])
    if r.get("stems"):
        out["stems"] = {k: _url(v) for k, v in r["stems"].items()}
    return out


def _meta_headers(r: dict) -> dict:
    """Binary responses point at the JSON record (cues, stems, provenance) so clients can fetch it."""
    return {"X-BGM-Meta-URL": _url(r["meta_path"])}


@app.get("/health")
def health():
    try:
        sf = find_soundfont()
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "soundfont_available": True}


@app.get("/moods", dependencies=[Depends(auth)])
def moods():
    return service.moods()


@app.post("/bgm", dependencies=[Depends(auth)])
def bgm(req: BGMRequest, as_json: bool = Query(False, description="return metadata + download URL instead of audio")):
    """Generate a track.  Returns the audio file (metadata in X-BGM-* headers), or JSON with ?as_json=true."""
    _check_fmt(req.format)
    r = _guard(service.generate_bgm, req.mood, req.duration, loop=req.loop, seed=req.seed, key=req.key,
               mode=req.mode, bpm=req.bpm, format=req.format, target_lufs=req.target_lufs,
               fade_out=req.fade_out, midi=req.midi, intensity=req.intensity, stems=req.stems)
    name = os.path.basename(r["path"])
    if as_json:
        return _public(r)
    return FileResponse(r["path"], media_type=r["mime"], filename=name, headers={
        "X-BGM-Seed": str(r["seed"]), "X-BGM-BPM": str(r["bpm"]), "X-BGM-Key": r["key"],
        "X-BGM-Duration": str(r["duration"]), "X-BGM-Loop": str(r["loop"]).lower(), **_meta_headers(r)})


@app.post("/sequence", dependencies=[Depends(auth)])
def sequence(req: SequenceRequest, as_json: bool = Query(False)):
    """Per-scene music in one file: moods change on your cuts, same key, crossfaded, exact total length."""
    _check_fmt(req.format)
    r = _guard(service.generate_sequence, [s.model_dump() for s in req.scenes], xfade=req.xfade, seed=req.seed,
               key=req.key, format=req.format, target_lufs=req.target_lufs, fade_out=req.fade_out,
               tempo_match=req.tempo_match, max_bpm_jump=req.max_bpm_jump, transitions=req.transitions,
               fx_level_db=req.fx_level_db, stems=req.stems)
    name = os.path.basename(r["path"])
    if as_json:
        return _public(r)
    return FileResponse(r["path"], media_type=r["mime"], filename=name, headers={
        "X-BGM-Seed": str(r["seed"]), "X-BGM-Key": r["key"], "X-BGM-Duration": str(r["duration"]),
        "X-BGM-BPMs": ",".join(str(x["bpm"]) for x in r["scenes"]), **_meta_headers(r)})


@app.get("/bgm/stream", dependencies=[Depends(auth)])
def bgm_stream(mood: str = "calm", duration: float = Query(60.0, ge=4, le=7200), seed: Optional[int] = None,
               key: Optional[str] = None, mode: Optional[str] = None,
               bpm: Optional[float] = Query(None, ge=_L["bpm"][0], le=_L["bpm"][1]),
               target_lufs: float = Query(-20.0, ge=_L["target_lufs"][0], le=_L["target_lufs"][1]),
               fade_out: float = Query(3.0, ge=_L["fade_out"][0], le=_L["fade_out"][1]),
               intensity: Optional[str] = Query(None, description="0..1, or comma-separated curve e.g. 0.2,0.5,0.9")):
    """Progressive WAV (16-bit/44.1k).  Begins almost instantly; finishes far faster than real time."""
    plan, length, it = _guard(service.stream_bgm, mood, duration, seed=seed, key=key, mode=mode, bpm=bpm,
                              target_lufs=target_lufs, fade_out=fade_out, intensity=intensity)
    return StreamingResponse(it, media_type="audio/wav", headers={
        "Content-Length": str(length), "X-BGM-Seed": str(plan.seed), "X-BGM-BPM": f"{plan.bpm:.2f}",
        "X-BGM-Key": f"{plan.key} {plan.mode}"})


@app.post("/mix", dependencies=[Depends(auth)])
def mix(narration: UploadFile = File(...), mood: str = Form("calm"),
        lead_in: float = Form(1.5, ge=_L["lead_in"][0], le=_L["lead_in"][1]),
        tail_out: float = Form(3.0, ge=_L["tail_out"][0], le=_L["tail_out"][1]),
        music_lufs: float = Form(-26.0, ge=_L["music_lufs"][0], le=_L["music_lufs"][1]),
        duck_db: float = Form(9.0, ge=_L["duck_db"][0], le=_L["duck_db"][1]),
        final_lufs: float = Form(-16.0, ge=_L["final_lufs"][0], le=_L["final_lufs"][1]),
        seed: Optional[int] = Form(None), key: Optional[str] = Form(None),
        format: str = Form("wav"), scenes: Optional[str] = Form(None, description='JSON list [{"mood","duration"}]'),
        xfade: float = Form(2.0, ge=_L["xfade"][0], le=_L["xfade"][1]), tempo_match: bool = Form(True),
        max_bpm_jump: float = Form(6.0, ge=_L["max_bpm_jump"][0], le=_L["max_bpm_jump"][1]),
        transitions: str = Form("none"),
        fx_level_db: float = Form(-3.0, ge=_L["fx_level_db"][0], le=_L["fx_level_db"][1]),
        intensity: Optional[str] = Form(None, description="single-mood mixes: 0..1 or comma-separated curve"),
        stems: bool = Form(False, description="also write voice / music / fx files that add up to the mix"),
        as_json: bool = Query(False, description="return metadata + download URLs instead of audio")):
    """Upload narration audio -> get back narration + fitted music, ducked under speech, loudness-normalised."""
    _check_fmt(format)
    scene_list = None
    if scenes:
        try:
            scene_list = json.loads(scenes)
        except ValueError:
            scene_list = None
        if not isinstance(scene_list, list):
            raise HTTPException(422, "scenes must be a JSON list like [{\"mood\": \"lofi\", \"duration\": 30}]")
    suffix = os.path.splitext(narration.filename or "")[1] or ".wav"
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "narration" + suffix)
        with open(src, "wb") as f:
            size = 0
            while chunk := narration.file.read(1024 * 1024):
                size += len(chunk)
                if size > service.MAX_NARRATION_BYTES:
                    raise HTTPException(413, "narration exceeds upload byte budget")
                f.write(chunk)
        r = _guard(service.mix_with_narration, src, mood, lead_in=lead_in, tail_out=tail_out,
                   music_lufs=music_lufs, duck_db=duck_db, final_lufs=final_lufs, seed=seed, key=key, format=format,
                   scenes=scene_list, xfade=xfade, tempo_match=tempo_match,
                   max_bpm_jump=max_bpm_jump, transitions=transitions, fx_level_db=fx_level_db,
                   intensity=intensity or None, stems=stems)
    if as_json:
        return _public(r)
    return FileResponse(r["path"], media_type=r["mime"], filename=os.path.basename(r["path"]), headers={
        "X-BGM-Seed": str(r["seed"]), "X-BGM-Total-Seconds": str(r["total_seconds"]),
        "X-BGM-Final-LUFS": str(r["final_lufs"]), **_meta_headers(r)})


@app.get("/files/{name}", dependencies=[Depends(auth)])
def files(name: str):
    path = os.path.join(service.OUT_DIR, os.path.basename(name))
    if not os.path.isfile(path):
        raise HTTPException(404, "not found")
    return FileResponse(path)
