"""Tests bgm_client.py against a server it starts itself (port 8791, API key enabled, temp output dir).
Run:  python selftest_client.py"""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bgm_client import BGMClient, BGMError, parse_scenes

ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def dur(path):
    i = sf.info(path)
    return i.frames / i.samplerate


tmp = tempfile.mkdtemp(prefix="bgm_client_test_")
URL, KEY = "http://127.0.0.1:8791", "test-key-123"
env = {"BGM_OUT_DIR": os.path.join(tmp, "server_out")}

check("parse_scenes accepts 3 forms",
      parse_scenes("lofi:30,calm:20") == parse_scenes([("lofi", 30), ("calm", 20)]) ==
      parse_scenes([{"mood": "lofi", "duration": 30}, {"mood": "calm", "duration": 20}]))

# server down -> clear error, fast
down = BGMClient("http://127.0.0.1:8799", retries=0, autostart=False)
try:
    down.moods(); check("server-down error is readable", False)
except BGMError as e:
    check("server-down error is readable", "Cannot reach the music service" in str(e))
try:
    BGMClient("http://127.0.0.1:8799", retries=0).start_server(); check("no project_dir -> readable error", False)
except BGMError as e:
    check("no project_dir -> readable error", "project_dir" in str(e))

with BGMClient(URL, KEY, project_dir=HERE, server_env=env, timeout=600) as c:
    check("autostart brought the server up", c.is_up())
    check("health ok", c.health()["ok"])
    check("moods listed", len(c.moods()) == 8)

    # auth
    try:
        BGMClient(URL, "wrong-key", autostart=False).moods(); check("wrong API key rejected", False)
    except BGMError as e:
        check("wrong API key rejected", "API key" in str(e))

    # music (wav + loop + mp3)
    o = os.path.join(tmp, "bed.wav")
    r = c.music("lofi", 37.25, o, seed=5)
    check("music: exact length", abs(dur(o) - 37.25) < 1 / 44100 * 2, f"({dur(o):.4f}s, seed {r['seed']}, {r['key']}, {r['bpm']} bpm)")
    r2 = c.music("lofi", 37.25, os.path.join(tmp, "bed2.wav"), seed=5)
    check("music: same seed reproduces", open(o, "rb").read() == open(os.path.join(tmp, "bed2.wav"), "rb").read())
    r = c.music("ambient", 20, os.path.join(tmp, "loop.flac"), loop=True)
    check("music: loop flac", abs(dur(os.path.join(tmp, "loop.flac")) - 20) < 1e-3 and r["loop"])
    c.music("calm", 12, os.path.join(tmp, "x.mp3"))
    check("music: mp3", os.path.getsize(os.path.join(tmp, "x.mp3")) > 4000)

    # stream
    r = c.stream("cinematic", 30, os.path.join(tmp, "s.wav"), seed=2)
    check("stream: exact length", abs(dur(os.path.join(tmp, "s.wav")) - 30) < 1e-3, f"(key {r['key']})")

    # sequence
    r = c.sequence([("calm", 10), ("cinematic", 12.5), ("dark", 8)], os.path.join(tmp, "seq.wav"), seed=1)
    check("sequence: exact total length", abs(dur(os.path.join(tmp, "seq.wav")) - 30.5) < 1e-3, f"(key {r['key']})")

    # score (synthetic narration), with and without scenes
    rng = np.random.default_rng(1)
    nar = np.zeros((14 * 44100, 2), dtype=np.float32)
    for s, e in [(0.5, 4.0), (5.0, 9.0), (10.0, 13.5)]:
        nar[int(s * 44100):int(e * 44100)] = rng.normal(0, .12, (int((e - s) * 44100), 2))
    npath = os.path.join(tmp, "narration.wav")
    sf.write(npath, nar, 44100)
    r = c.score(npath, os.path.join(tmp, "scored.wav"), mood="calm", seed=3)
    check("score: length = lead_in + narration + tail_out", abs(dur(r["path"]) - (1.5 + 14 + 3)) < 0.01 and abs(r["total_seconds"] - 18.5) < 0.01, f"({dur(r['path']):.2f}s)")
    check("score: final loudness ~ -16 LUFS", abs(r["final_lufs"] + 16) < 1.0, f"({r['final_lufs']})")
    r = c.score(npath, os.path.join(tmp, "scored_scenes.wav"), scenes="lofi:5,tech:9", seed=3, lead_in=0.0, tail_out=2.0)
    check("score with scenes", abs(dur(r["path"]) - 16.0) < 0.01, f"({dur(r['path']):.2f}s)")

    # readable errors from the server
    for label, fn, needle in [
        ("unknown mood", lambda: c.music("nope", 10, os.path.join(tmp, "e.wav")), "Unknown mood"),
        ("duration too short", lambda: c.music("lofi", 1, os.path.join(tmp, "e.wav")), "duration"),
        ("scene/narration mismatch", lambda: c.score(npath, os.path.join(tmp, "e.wav"), scenes="lofi:60"), "narration"),
    ]:
        try:
            fn(); check(f"error readable: {label}", False)
        except BGMError as e:
            check(f"error readable: {label}", needle.lower() in str(e).lower(), f"-> {str(e)[:110]}")

    # mux onto a silent test video
    vid = os.path.join(tmp, "silent.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=14",
                    "-pix_fmt", "yuv420p", vid], check=True)
    out = c.mux(vid, os.path.join(tmp, "scored.wav"), os.path.join(tmp, "final.mp4"), trim_audio_start=1.5)
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,duration",
                                       "-of", "json", out], capture_output=True, text=True).stdout)
    kinds = {s["codec_type"]: s for s in probe["streams"]}
    check("mux: video copied + AAC audio", kinds["video"]["codec_name"] == "h264" and kinds["audio"]["codec_name"] == "aac")
    check("mux: audio trimmed to match picture", abs(float(kinds["audio"]["duration"]) - 14.0) < 0.2, f"(audio {float(kinds['audio']['duration']):.2f}s vs video 14s)")
    try:
        BGMClient.mux(os.path.join(tmp, "missing.mp4"), os.path.join(tmp, "scored.wav"), os.path.join(tmp, "z.mp4")); check("mux error readable", False)
    except BGMError as e:
        check("mux error readable", "ffmpeg failed" in str(e))

check("server stopped when the with-block ended", not BGMClient(URL, KEY, autostart=False).is_up())

print("\nALL PASSED" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
