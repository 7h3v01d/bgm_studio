"""Command line:  python -m bgmstudio.cli {moods,generate,mix,serve}"""
from __future__ import annotations

import argparse
import json


def _parse_scenes(text: str) -> list:
    out = []
    for part in text.split(","):
        mood, _, dur = part.strip().partition(":")
        out.append({"mood": mood, "duration": float(dur)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bgmstudio")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("moods", help="list moods")
    sub.add_parser("calibrate", help="measure per-mood loudness for the current SoundFont (streaming)")

    g = sub.add_parser("generate", help="make a track")
    g.add_argument("mood")
    g.add_argument("duration", type=float, help="seconds")
    g.add_argument("-o", "--out-dir")
    g.add_argument("--loop", action="store_true")
    g.add_argument("--seed", type=int)
    g.add_argument("--key")
    g.add_argument("--mode")
    g.add_argument("--bpm", type=float)
    g.add_argument("--format", default="wav")
    g.add_argument("--lufs", type=float, default=-20.0)
    g.add_argument("--midi", action="store_true")

    q = sub.add_parser("sequence", help="per-scene music, e.g.  sequence lofi:30,cinematic:45,dark:20")
    q.add_argument("scenes", help="comma-separated mood:seconds")
    q.add_argument("-o", "--out-dir")
    q.add_argument("--xfade", type=float, default=2.0)
    q.add_argument("--seed", type=int)
    q.add_argument("--key")
    q.add_argument("--format", default="wav")

    m = sub.add_parser("mix", help="score a narration file")
    m.add_argument("narration")
    m.add_argument("mood")
    m.add_argument("-o", "--out-dir")
    m.add_argument("--seed", type=int)
    m.add_argument("--format", default="wav")
    m.add_argument("--music-lufs", type=float, default=-26.0)
    m.add_argument("--duck-db", type=float, default=9.0)
    m.add_argument("--scenes", help="per-scene moods, comma-separated mood:seconds (must sum to the narration length)")

    s = sub.add_parser("serve", help="run the REST API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)

    a = ap.parse_args(argv)
    from . import service
    if a.cmd == "moods":
        for k, v in service.moods().items():
            print(f"{k:10s} {v}")
    elif a.cmd == "calibrate":
        from .calibrate import calibrate_all
        print(json.dumps(calibrate_all(), indent=1))
    elif a.cmd == "generate":
        r = service.generate_bgm(a.mood, a.duration, loop=a.loop, seed=a.seed, key=a.key, mode=a.mode, bpm=a.bpm,
                                 format=a.format, target_lufs=a.lufs, out_dir=a.out_dir, midi=a.midi)
        print(json.dumps(r, indent=1))
    elif a.cmd == "sequence":
        r = service.generate_sequence(_parse_scenes(a.scenes), xfade=a.xfade, seed=a.seed, key=a.key,
                                      format=a.format, out_dir=a.out_dir)
        print(json.dumps(r, indent=1))
    elif a.cmd == "mix":
        r = service.mix_with_narration(a.narration, a.mood, seed=a.seed, format=a.format, out_dir=a.out_dir,
                                       music_lufs=a.music_lufs, duck_db=a.duck_db,
                                       scenes=_parse_scenes(a.scenes) if a.scenes else None)
        print(json.dumps(r, indent=1))
    elif a.cmd == "serve":
        import uvicorn
        uvicorn.run("bgmstudio.api:app", host=a.host, port=a.port)


if __name__ == "__main__":
    main()
