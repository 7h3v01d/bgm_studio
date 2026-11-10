"""bgm_client.py: single-file client for the bgmstudio music service.

Copy this file into your studio project.  It needs only `httpx` (no bgmstudio imports), so it works from any venv.

    from bgm_client import BGMClient

    # start_server() launches the service in the background if it isn't already running
    with BGMClient(project_dir=r"G:\\Projects\\_Multimedia\\bgm_studio") as bgm:
        bgm.music("lofi", 312.5, "bed.wav")                                  # exact-length bed
        bgm.music("ambient", 45, "loop.wav", loop=True)                      # seamless loop
        bgm.sequence([("calm", 20), ("cinematic", 25), ("dark", 20)], "score.wav")   # per-scene moods
        info = bgm.score("narration.mp3", "scored.wav", scenes="calm:20,cinematic:25,dark:20")
        bgm.mux("silent_video.mp4", "scored.wav", "final.mp4", trim_audio_start=info["lead_in"])

Environment: BGM_URL (default http://127.0.0.1:8765), BGM_API_KEY, BGM_PROJECT_DIR.
Command line:  python bgm_client.py --help
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Optional, Sequence, Union
from urllib.parse import urlparse

import httpx

Scenes = Union[str, Sequence[Union[dict, tuple]]]


class BGMError(RuntimeError):
    """Anything that went wrong talking to (or starting) the music service, with a readable message."""


def _fmt(path: str) -> str:
    return os.path.splitext(path)[1].lstrip(".").lower() or "wav"


Intensity = Union[float, Sequence[float], None]


def parse_scenes(scenes: Scenes) -> list:
    """Accepts "lofi:30,horror:20:0.8", [("lofi", 30), ("horror", 20, 0.8), ...] or
    [{"mood": "lofi", "duration": 30, "intensity": 0.8}, ...].  The optional third field is intensity (0..1)."""
    if isinstance(scenes, str):
        scenes = [tuple(p.strip().split(":")) for p in scenes.split(",") if p.strip()]
    out = []
    for s in scenes:
        if isinstance(s, dict):
            out.append(dict(s))
        else:
            if len(s) not in (2, 3):
                raise ValueError(f"scene {s!r}: use (mood, seconds) or (mood, seconds, intensity)")
            sc = {"mood": s[0], "duration": float(s[1])}
            if len(s) == 3:
                sc["intensity"] = float(s[2])
            out.append(sc)
    return out


def _intensity(v: Intensity):
    return None if v is None else (float(v) if isinstance(v, (int, float)) else [float(x) for x in v])


class BGMClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, *,
                 project_dir: Optional[str] = None, python: Optional[str] = None,
                 timeout: float = 1800.0, retries: int = 2, autostart: bool = True,
                 server_env: Optional[dict] = None):
        self.base = (base_url or os.environ.get("BGM_URL", "http://127.0.0.1:8765")).rstrip("/")
        key = api_key or os.environ.get("BGM_API_KEY")
        self.headers = {"X-API-Key": key} if key else {}
        self.timeout, self.retries, self.autostart = timeout, retries, autostart
        self.project_dir = project_dir or os.environ.get("BGM_PROJECT_DIR")
        self.python, self.server_env = python, server_env or {}
        self._proc = None
        self._log = None

    # ------------------------------------------------------------ plumbing
    def __enter__(self):
        if self.autostart:
            self.start_server()
        return self

    def __exit__(self, *exc):
        self.stop_server()

    @staticmethod
    def _explain(r: httpx.Response) -> str:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        if isinstance(detail, list):  # FastAPI validation errors
            detail = "; ".join(f"{'.'.join(str(x) for x in d.get('loc', [])[1:])}: {d.get('msg')}" for d in detail)
        if r.status_code == 401:
            return "The music service rejected the API key (set BGM_API_KEY or pass api_key=)."
        return f"Music service error {r.status_code}: {detail}"

    def _call(self, method: str, path: str, *, stream_to: Optional[str] = None, **kw) -> httpx.Response:
        last = None
        for attempt in range(self.retries + 1):
            try:
                if stream_to:
                    with httpx.stream(method, self.base + path, headers=self.headers, timeout=self.timeout, **kw) as r:
                        if r.status_code >= 400:
                            r.read()
                            raise BGMError(self._explain(r))
                        with open(stream_to, "wb") as f:
                            for chunk in r.iter_bytes(65536):
                                f.write(chunk)
                        return r
                r = httpx.request(method, self.base + path, headers=self.headers, timeout=self.timeout, **kw)
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:  # only retry "couldn't connect", never slow renders
                last = e
                time.sleep(1.0 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise BGMError(self._explain(r))
            return r
        raise BGMError(f"Cannot reach the music service at {self.base} ({last}). Start run_server.bat, "
                       f"or call BGMClient(project_dir=...).start_server().")

    def _fetch(self, meta: dict, out: str) -> dict:
        """Download the main file to `out`, any stems beside it (<out>.stem-<name>.<ext>), and save the JSON record
        (cues, provenance, settings) as <out minus extension>.json so it travels with the audio."""
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        self._call("GET", meta["download_url"], stream_to=out)
        root, ext = os.path.splitext(out)
        stems = {}
        for name, url in (meta.get("stems") or {}).items():
            stems[name] = f"{root}.stem-{name}{ext}"
            self._call("GET", url, stream_to=stems[name])
        record = {**meta, "local_path": os.path.abspath(out)}
        if stems:
            record["local_stems"] = {k: os.path.abspath(v) for k, v in stems.items()}
        meta_out = root + ".json"
        with open(meta_out, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=1)
        return {"cues": meta.get("cues"), "provenance": meta.get("provenance"), "stems": stems,
                "meta_path": meta_out}

    # ------------------------------------------------------------ server lifecycle
    def is_up(self) -> bool:
        try:
            return httpx.get(self.base + "/health", timeout=3).json().get("ok", False)
        except (httpx.HTTPError, ValueError):
            return False

    def wait_until_ready(self, timeout: float = 60.0) -> None:
        end = time.time() + timeout
        while time.time() < end:
            if self.is_up():
                return
            if self._proc is not None and self._proc.poll() is not None:
                break
            time.sleep(0.4)
        raise BGMError("The music service did not become ready." + self._log_tail())

    def _log_tail(self) -> str:
        if self._log and os.path.isfile(self._log):
            with open(self._log, errors="replace") as f:
                return "\n--- server log (tail) ---\n" + "".join(f.readlines()[-15:])
        return ""

    def start_server(self, wait: float = 60.0) -> bool:
        """Launch the service in the background if it isn't running.  Returns True if we started it.
        Needs project_dir (the bgm_studio folder) and, optionally, python (defaults to its .venv)."""
        if self.is_up():
            return False
        if not self.project_dir or not os.path.isdir(self.project_dir):
            raise BGMError("Music service is not running and no project_dir was given to start it. "
                           "Pass BGMClient(project_dir=r'...\\bgm_studio') or set BGM_PROJECT_DIR.")
        py = self.python or next((p for p in (
            os.path.join(self.project_dir, ".venv", "Scripts", "python.exe"),
            os.path.join(self.project_dir, ".venv", "bin", "python")) if os.path.isfile(p)), sys.executable)
        port = urlparse(self.base).port or 8765
        self._log = os.path.join(self.project_dir, "bgm_server.log")
        env = {**os.environ, **self.server_env}
        if "X-API-Key" in self.headers:
            env.setdefault("BGM_API_KEY", self.headers["X-API-Key"])
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with open(self._log, "w") as log:
            self._proc = subprocess.Popen([py, "-m", "uvicorn", "bgmstudio.api:app", "--host", "127.0.0.1",
                                           "--port", str(port), "--log-level", "warning"],
                                          cwd=self.project_dir, env=env, stdout=log, stderr=subprocess.STDOUT,
                                          creationflags=flags)
        self.wait_until_ready(wait)
        return True

    def stop_server(self) -> None:
        """Stops the service only if this client started it."""
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    # ------------------------------------------------------------ API
    def health(self) -> dict:
        return self._call("GET", "/health").json()

    def moods(self) -> dict:
        return self._call("GET", "/moods").json()

    def music(self, mood: str, duration: float, out: str, *, loop: bool = False, seed: Optional[int] = None,
              key: Optional[str] = None, mode: Optional[str] = None, bpm: Optional[float] = None,
              target_lufs: float = -20.0, fade_out: float = 3.0, intensity: Intensity = None,
              stems: bool = False) -> dict:
        """Exact-length background track written to `out` (format from the extension).
        intensity: 0..1, or a list of 0..1 points spread across the track (a tension curve).
        stems=True also downloads pad/bass/keys/melody/sparkle/drums files beside `out`.
        Returns path/seed/bpm/key/duration/loop plus cues (bars, sections), provenance, stems and meta_path."""
        meta = self._call("POST", "/bgm", params={"as_json": "true"}, json={
            "mood": mood, "duration": duration, "loop": loop, "seed": seed, "key": key, "mode": mode, "bpm": bpm,
            "format": _fmt(out), "target_lufs": target_lufs, "fade_out": fade_out,
            "intensity": _intensity(intensity), "stems": stems}).json()
        return {"path": out, "seed": meta["seed"], "bpm": meta["bpm"], "key": meta["key"],
                "duration": meta["duration"], "loop": loop, **self._fetch(meta, out)}

    def stream(self, mood: str, duration: float, out: str, *, seed: Optional[int] = None,
               key: Optional[str] = None, target_lufs: float = -20.0, intensity: Intensity = None) -> dict:
        """Progressive WAV download (non-loop, fade-out ending)."""
        params = {"mood": mood, "duration": duration, "target_lufs": target_lufs}
        iv = _intensity(intensity)
        if iv is not None:
            params["intensity"] = ",".join(str(x) for x in (iv if isinstance(iv, list) else [iv]))
        if seed is not None:
            params["seed"] = seed
        if key:
            params["key"] = key
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        r = self._call("GET", "/bgm/stream", params=params, stream_to=out)
        return {"path": out, "seed": int(r.headers["X-BGM-Seed"]), "key": r.headers["X-BGM-Key"]}

    def sequence(self, scenes: Scenes, out: str, *, xfade: float = 2.0, seed: Optional[int] = None,
                 key: Optional[str] = None, target_lufs: float = -20.0, fade_out: float = 3.0,
                 tempo_match: bool = True, max_bpm_jump: float = 6.0, transitions: str = "none",
                 fx_level_db: float = -3.0, stems: bool = False) -> dict:
        """Per-scene music in one file: moods change on your cuts, shared key, crossfaded.
        stems=True also downloads one file per instrument group plus fx (the transitions) beside `out`.
        tempo_match keeps neighbouring scenes within max_bpm_jump BPM; transitions adds a synthesized effect at each
        cut (none | riser | impact | riser_impact | downlifter | swell | auto; or {"transition": ...} per scene).
        Returns path/seed/key/duration plus `scenes` (per-scene bpm, start, transition_in) and `warnings`."""
        r = self._call("POST", "/sequence", params={"as_json": "true"}, json={
            "scenes": parse_scenes(scenes), "xfade": xfade, "seed": seed, "key": key, "format": _fmt(out),
            "target_lufs": target_lufs, "fade_out": fade_out, "tempo_match": tempo_match,
            "max_bpm_jump": max_bpm_jump, "transitions": transitions, "fx_level_db": fx_level_db,
            "stems": stems})
        meta = r.json()
        return {"path": out, "seed": meta["seed"], "key": meta["key"], "duration": meta["duration"],
                "lufs": meta["lufs"], "scenes": meta["scenes"],
                "warnings": [x["tempo_warning"] for x in meta["scenes"] if "tempo_warning" in x],
                **self._fetch(meta, out)}

    def score(self, narration: str, out: str, *, mood: str = "calm", scenes: Optional[Scenes] = None,
              lead_in: float = 1.5, tail_out: float = 3.0, music_lufs: float = -26.0, duck_db: float = 9.0,
              final_lufs: float = -16.0, seed: Optional[int] = None, key: Optional[str] = None,
              xfade: float = 2.0, tempo_match: bool = True, max_bpm_jump: float = 6.0,
              transitions: str = "none", fx_level_db: float = -3.0, intensity: Intensity = None,
              stems: bool = False) -> dict:
        """Narration in, finished mix out (music fitted, ducked under speech, loudness-normalised).
        stems=True also downloads voice / music / fx files beside `out` that add up to the mix.
        cues in the result are in mix time and include {"narration": {"start", "end"}}.
        The output is lead_in + narration + tail_out seconds long; the narration starts at `lead_in`."""
        data = {"mood": mood, "lead_in": lead_in, "tail_out": tail_out, "music_lufs": music_lufs,
                "duck_db": duck_db, "final_lufs": final_lufs, "format": _fmt(out), "xfade": xfade,
                "tempo_match": str(tempo_match).lower(), "max_bpm_jump": max_bpm_jump,
                "transitions": transitions, "fx_level_db": fx_level_db, "stems": str(stems).lower()}
        if seed is not None:
            data["seed"] = seed
        if key:
            data["key"] = key
        if scenes:
            data["scenes"] = json.dumps(parse_scenes(scenes))
        iv = _intensity(intensity)
        if iv is not None:
            data["intensity"] = ",".join(str(x) for x in (iv if isinstance(iv, list) else [iv]))
        with open(narration, "rb") as f:
            meta = self._call("POST", "/mix", params={"as_json": "true"}, data=data,
                              files={"narration": (os.path.basename(narration), f)}).json()
        return {"path": out, "seed": meta["seed"], "lead_in": lead_in, "tail_out": tail_out,
                "total_seconds": meta["total_seconds"], "final_lufs": meta["final_lufs"], **self._fetch(meta, out)}

    # ------------------------------------------------------------ video helper
    @staticmethod
    def mux(video: str, audio: str, out: str, *, trim_audio_start: float = 0.0, audio_codec: str = "aac",
            audio_bitrate: str = "256k") -> str:
        """Attach audio to a (silent) video without re-encoding the picture.  Uses ffmpeg from PATH.
        If your visuals start together with the narration, pass trim_audio_start=lead_in (from score())."""
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video]
        if trim_audio_start > 0:
            cmd += ["-ss", f"{trim_audio_start:.3f}"]
        cmd += ["-i", audio, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", audio_codec,
                "-b:a", audio_bitrate, "-shortest", out]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except FileNotFoundError:
            raise BGMError("ffmpeg was not found on PATH (needed for mux).")
        except subprocess.CalledProcessError as e:
            raise BGMError(f"ffmpeg failed: {e.stderr.strip()[-400:]}")
        return out


# ---------------------------------------------------------------- command line
def main(argv=None):
    ap = argparse.ArgumentParser(description="bgmstudio client")
    ap.add_argument("--url"), ap.add_argument("--key"), ap.add_argument("--project-dir")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health"), sub.add_parser("moods")
    m = sub.add_parser("music"); m.add_argument("mood"); m.add_argument("duration", type=float)
    m.add_argument("-o", "--out", required=True); m.add_argument("--loop", action="store_true"); m.add_argument("--seed", type=int)
    q = sub.add_parser("sequence"); q.add_argument("scenes", help="mood:seconds,mood:seconds"); q.add_argument("-o", "--out", required=True)
    q.add_argument("--seed", type=int); q.add_argument("--transitions", default="none")
    q.add_argument("--no-tempo-match", action="store_true")
    s = sub.add_parser("score"); s.add_argument("narration"); s.add_argument("-o", "--out", required=True)
    s.add_argument("--mood", default="calm"); s.add_argument("--scenes"); s.add_argument("--seed", type=int)
    s.add_argument("--lead-in", type=float, default=1.5); s.add_argument("--transitions", default="none")
    s.add_argument("--no-tempo-match", action="store_true")
    x = sub.add_parser("mux"); x.add_argument("video"); x.add_argument("audio"); x.add_argument("-o", "--out", required=True)
    x.add_argument("--trim-audio-start", type=float, default=0.0)
    a = ap.parse_args(argv)
    try:
        with BGMClient(a.url, a.key, project_dir=a.project_dir or os.path.dirname(os.path.abspath(__file__)),
                       autostart=a.cmd != "mux") as c:
            if a.cmd == "health":
                res = c.health()
            elif a.cmd == "moods":
                res = c.moods()
            elif a.cmd == "music":
                res = c.music(a.mood, a.duration, a.out, loop=a.loop, seed=a.seed)
            elif a.cmd == "sequence":
                res = c.sequence(a.scenes, a.out, seed=a.seed, transitions=a.transitions, tempo_match=not a.no_tempo_match)
            elif a.cmd == "score":
                res = c.score(a.narration, a.out, mood=a.mood, scenes=a.scenes, seed=a.seed, lead_in=a.lead_in,
                              transitions=a.transitions, tempo_match=not a.no_tempo_match)
            else:
                res = {"path": c.mux(a.video, a.audio, a.out, trim_audio_start=a.trim_audio_start)}
        print(json.dumps(res, indent=1))
    except BGMError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
