"""How your studio pipeline calls the music service.  Needs only `httpx`.

    uvicorn bgmstudio.api:app --port 8765        # start the service (BGM_API_KEY=... to require a key)
    python example_client.py narration.mp3
"""
import os
import sys

import httpx

BASE = os.environ.get("BGM_URL", "http://127.0.0.1:8765")
HEADERS = {"X-API-Key": os.environ["BGM_API_KEY"]} if "BGM_API_KEY" in os.environ else {}


def music_for(duration_s: float, mood: str, out: str, loop=False, seed=None) -> dict:
    """Exact-length background track saved to `out`. Returns the seed etc. so scenes can be regenerated."""
    r = httpx.post(f"{BASE}/bgm", headers=HEADERS, timeout=600, json={
        "mood": mood, "duration": duration_s, "loop": loop, "seed": seed,
        "format": os.path.splitext(out)[1].lstrip(".") or "wav"})
    r.raise_for_status()
    open(out, "wb").write(r.content)
    return {"seed": int(r.headers["X-BGM-Seed"]), "bpm": float(r.headers["X-BGM-BPM"]), "key": r.headers["X-BGM-Key"]}


def stream_music(duration_s: float, mood: str, out: str):
    """Progressive download: bytes start flowing immediately."""
    with httpx.stream("GET", f"{BASE}/bgm/stream", headers=HEADERS, timeout=600,
                      params={"mood": mood, "duration": duration_s}) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            for chunk in r.iter_bytes(65536):
                f.write(chunk)


def score_narration(narration_path: str, mood: str, out: str) -> int:
    """Upload narration, get back the finished mix (music fitted, ducked under speech, -16 LUFS)."""
    with open(narration_path, "rb") as f:
        r = httpx.post(f"{BASE}/mix", headers=HEADERS, timeout=1200,
                       files={"narration": (os.path.basename(narration_path), f)},
                       data={"mood": mood, "format": os.path.splitext(out)[1].lstrip(".") or "wav"})
    r.raise_for_status()
    open(out, "wb").write(r.content)
    return int(r.headers["X-BGM-Seed"])


if __name__ == "__main__":
    narration = sys.argv[1] if len(sys.argv) > 1 else "narration.wav"
    seed = score_narration(narration, "cinematic", "scored_audio.wav")
    print("wrote scored_audio.wav (seed", seed, ")")
    # Then mux with your visuals, e.g.:
    #   ffmpeg -i video_silent.mp4 -i scored_audio.wav -c:v copy -c:a aac -b:a 256k -shortest final.mp4
