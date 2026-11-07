"""REST API.   Run:  uvicorn bgmstudio.api:app --host 0.0.0.0 --port 8765

Optional auth: set BGM_API_KEY and send it as the X-API-Key header.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import service
from .audio import MIME
from .render import find_soundfont

app = FastAPI(title="bgmstudio", version="1.0",
              description="Procedural MIDI background music: exact duration, seamless loops, streaming, voice ducking.")


def auth(x_api_key: Optional[str] = Header(default=None)):
    want = os.environ.get("BGM_API_KEY")
    if want and x_api_key != want:
        raise HTTPException(401, "Invalid or missing X-API-Key")


class BGMRequest(BaseModel):
    mood: str = Field("calm", description="calm, lofi, cinematic, uplifting, corporate, dark, ambient, tech (+aliases)")
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


class Scene(BaseModel):
    mood: str
    duration: float = Field(..., ge=4, le=7200)
    seed: Optional[int] = None
    mode: Optional[str] = None
    bpm: Optional[float] = Field(None, ge=40, le=200)


class SequenceRequest(BaseModel):
    scenes: list[Scene] = Field(..., min_length=1, max_length=300,
                                description="one entry per visual scene; music changes mood at each cut")
    xfade: float = Field(2.0, ge=0, le=10, description="crossfade seconds after each cut")
    seed: Optional[int] = None
    key: Optional[str] = Field(None, description="shared by all scenes; default: auto-picked common key")
    format: str = "wav"
    target_lufs: float = Field(-20.0, ge=-40, le=-8)
    fade_out: float = Field(3.0, ge=0, le=30)


def _check_fmt(fmt: str):
    if fmt.lower() not in MIME:
        raise HTTPException(422, f"format must be one of {', '.join(MIME)}")


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(422 if isinstance(e, ValueError) else 500, str(e))


@app.get("/health")
def health():
    try:
        sf = find_soundfont()
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "soundfont": sf}


@app.get("/moods", dependencies=[Depends(auth)])
def moods():
    return service.moods()


@app.post("/bgm", dependencies=[Depends(auth)])
def bgm(req: BGMRequest, as_json: bool = Query(False, description="return metadata + download URL instead of audio")):
    """Generate a track.  Returns the audio file (metadata in X-BGM-* headers), or JSON with ?as_json=true."""
    _check_fmt(req.format)
    r = _guard(service.generate_bgm, req.mood, req.duration, loop=req.loop, seed=req.seed, key=req.key,
               mode=req.mode, bpm=req.bpm, format=req.format, target_lufs=req.target_lufs,
               fade_out=req.fade_out, midi=req.midi)
    name = os.path.basename(r["path"])
    if as_json:
        return {**{k: v for k, v in r.items() if k != "path"}, "file": name, "download_url": f"/files/{name}"}
    return FileResponse(r["path"], media_type=r["mime"], filename=name, headers={
        "X-BGM-Seed": str(r["seed"]), "X-BGM-BPM": str(r["bpm"]), "X-BGM-Key": r["key"],
        "X-BGM-Duration": str(r["duration"]), "X-BGM-Loop": str(r["loop"]).lower()})


@app.post("/sequence", dependencies=[Depends(auth)])
def sequence(req: SequenceRequest, as_json: bool = Query(False)):
    """Per-scene music in one file: moods change on your cuts, same key, crossfaded, exact total length."""
    _check_fmt(req.format)
    r = _guard(service.generate_sequence, [s.model_dump() for s in req.scenes], xfade=req.xfade, seed=req.seed,
               key=req.key, format=req.format, target_lufs=req.target_lufs, fade_out=req.fade_out)
    name = os.path.basename(r["path"])
    if as_json:
        return {**{k: v for k, v in r.items() if k != "path"}, "file": name, "download_url": f"/files/{name}"}
    return FileResponse(r["path"], media_type=r["mime"], filename=name, headers={
        "X-BGM-Seed": str(r["seed"]), "X-BGM-Key": r["key"], "X-BGM-Duration": str(r["duration"])})


@app.get("/bgm/stream", dependencies=[Depends(auth)])
def bgm_stream(mood: str = "calm", duration: float = Query(60.0, ge=4, le=7200), seed: Optional[int] = None,
               key: Optional[str] = None, mode: Optional[str] = None, bpm: Optional[float] = None,
               target_lufs: float = -20.0, fade_out: float = 3.0):
    """Progressive WAV (16-bit/44.1k).  Begins almost instantly; finishes far faster than real time."""
    plan, length, it = _guard(service.stream_bgm, mood, duration, seed=seed, key=key, mode=mode, bpm=bpm,
                              target_lufs=target_lufs, fade_out=fade_out)
    return StreamingResponse(it, media_type="audio/wav", headers={
        "Content-Length": str(length), "X-BGM-Seed": str(plan.seed), "X-BGM-BPM": f"{plan.bpm:.2f}",
        "X-BGM-Key": f"{plan.key} {plan.mode}"})


@app.post("/mix", dependencies=[Depends(auth)])
def mix(narration: UploadFile = File(...), mood: str = Form("calm"), lead_in: float = Form(1.5),
        tail_out: float = Form(3.0), music_lufs: float = Form(-26.0), duck_db: float = Form(9.0),
        final_lufs: float = Form(-16.0), seed: Optional[int] = Form(None), key: Optional[str] = Form(None),
        format: str = Form("wav"), scenes: Optional[str] = Form(None, description='JSON list [{"mood","duration"}]'),
        xfade: float = Form(2.0)):
    """Upload narration audio -> get back narration + fitted music, ducked under speech, loudness-normalised."""
    _check_fmt(format)
    try:
        scene_list = json.loads(scenes) if scenes else None
    except ValueError:
        raise HTTPException(422, "scenes must be a JSON list like [{\"mood\": \"lofi\", \"duration\": 30}]")
    suffix = os.path.splitext(narration.filename or "")[1] or ".wav"
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "narration" + suffix)
        with open(src, "wb") as f:
            shutil.copyfileobj(narration.file, f)
        r = _guard(service.mix_with_narration, src, mood, lead_in=lead_in, tail_out=tail_out,
                   music_lufs=music_lufs, duck_db=duck_db, final_lufs=final_lufs, seed=seed, key=key, format=format,
                   scenes=scene_list, xfade=xfade)
    return FileResponse(r["path"], media_type=r["mime"], filename=os.path.basename(r["path"]), headers={
        "X-BGM-Seed": str(r["seed"]), "X-BGM-Total-Seconds": str(r["total_seconds"]),
        "X-BGM-Final-LUFS": str(r["final_lufs"])})


@app.get("/files/{name}", dependencies=[Depends(auth)])
def files(name: str):
    path = os.path.join(service.OUT_DIR, os.path.basename(name))
    if not os.path.isfile(path):
        raise HTTPException(404, "not found")
    return FileResponse(path)
