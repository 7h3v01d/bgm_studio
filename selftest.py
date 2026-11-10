"""End-to-end checks.  Run:  python selftest.py"""
import asyncio
import io
import os
import sys
import tempfile
import time

import numpy as np
import soundfile as sf

# This dedicated end-to-end test intentionally renders a 20-minute track.
# Give only this self-test process a large enough budget before importing the
# service (which reads the environment variable at import time). The default
# 600-second production budget remains unchanged for normal invocations.
_selftest_min_seconds = 1200
_selftest_configured_budget = float(os.environ.get("BGM_MAX_RENDER_SECONDS", "600"))
os.environ["BGM_MAX_RENDER_SECONDS"] = str(max(_selftest_configured_budget, _selftest_min_seconds))
os.environ["BGM_OUT_DIR"] = tempfile.mkdtemp(prefix="bgm_selftest_")
from bgmstudio import service
from bgmstudio.audio import duck_gain, measure_lufs
from bgmstudio.compose import compose
from bgmstudio.presets import PRESETS
from bgmstudio.render import SR, render_audio

ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


# 1. exact duration for every mood, loop and non-loop, awkward lengths
for mood in PRESETS:
    for dur, loop in [(5.0, True), (37.3, False), (181.7, True)]:
        a = render_audio(compose(mood, dur, loop=loop, seed=11))
        check(f"exact length {mood:9s} {dur:6.1f}s loop={loop}", len(a) == round(dur * SR), f"({len(a)} vs {round(dur*SR)})")

# 2. determinism
p1, p2 = compose("lofi", 60, seed=5), compose("lofi", 60, seed=5)
check("same seed -> identical notes", [(n.start, n.pitch, n.vel) for n in p1.notes] == [(n.start, n.pitch, n.vel) for n in p2.notes])
check("same seed -> identical audio", np.array_equal(render_audio(p1), render_audio(p2)))
p3 = compose("lofi", 60, seed=6)
check("different seed -> different music", [(n.start, n.pitch) for n in p1.notes] != [(n.start, n.pitch) for n in p3.notes])

# 3. loop seam: wrap the file around and look at the join
def seam_stats(a):
    m = a.mean(axis=1)
    wrapped = np.concatenate([m[-SR:], m[:SR]])           # 1 s either side of the join
    d = np.abs(np.diff(wrapped))
    j = len(m[-SR:]) - 1
    seam_jump = d[j]
    ref = np.percentile(np.delete(d, j), 99.9)
    # energy continuity: RMS of the 150 ms either side of the join
    pre = np.sqrt(np.mean(wrapped[j - int(.15*SR):j] ** 2)); post = np.sqrt(np.mean(wrapped[j:j + int(.15*SR)] ** 2))
    return seam_jump, ref, pre, post

for mood in ["lofi", "cinematic", "ambient", "tech"]:
    a = render_audio(compose(mood, 40, loop=True, seed=3))
    jump, ref, pre, post = seam_stats(a)
    check(f"loop seam click-free  {mood:9s}", jump <= ref * 1.5 + 1e-4, f"(jump {jump:.5f}, 99.9th pct {ref:.5f})")
    ratio = max(pre, post) / max(min(pre, post), 1e-9)
    check(f"loop seam energy even {mood:9s}", ratio < 2.5, f"(RMS before {pre:.4f}, after {post:.4f})")

# tail fold really happens: the start of a loop must contain the ringing tail of the end
pl = compose("cinematic", 40, loop=True, seed=3)
folded = render_audio(pl)
import dataclasses
unfolded = render_audio(dataclasses.replace(pl, loop=False, fade_out=0))
head = slice(0, int(1.5 * SR))
check("tail is folded onto loop start", np.sqrt(np.mean(folded[head] ** 2)) > np.sqrt(np.mean(unfolded[head] ** 2)) * 1.02)

# 4. non-loop ends with a fade to silence
a = render_audio(compose("calm", 30, loop=False, seed=2))
check("non-loop fades to silence", np.abs(a[-200:]).max() < 1e-3 and np.abs(a[-int(2*SR):-int(1.5*SR)]).max() > 1e-3)

# 5. loudness targeting
r = service.generate_bgm("uplifting", 30, seed=9, target_lufs=-20.0)
data, sr = sf.read(r["path"])
check("loudness lands on target", abs(measure_lufs(data.astype("float32"), sr) + 20.0) < 0.6, f"({measure_lufs(data.astype('float32'), sr):.2f} LUFS)")
check("cache hit on repeat", service.generate_bgm("uplifting", 30, seed=9, target_lufs=-20.0)["cached"])
check("midi export", os.path.getsize(service.generate_bgm("lofi", 20, seed=1, midi=True)["midi_path"]) > 200)
check("mp3 encode", os.path.getsize(service.generate_bgm("calm", 12, seed=1, format="mp3")["path"]) > 5000)

# 6. long-form scales: 20 min renders fast, sections evolve
t = time.time()
r = service.generate_bgm("ambient", 1200, seed=4, format="flac")
el = time.time() - t
check("20-minute track", r["samples"] == 1200 * SR, f"({el:.1f}s wall, {1200/el:.0f}x realtime, sections={len(r['sections'])})")

# 7. ducking behaves
sr = SR
rng = np.random.default_rng(0)
voice = np.zeros((12 * sr, 2), dtype=np.float32)
for s, e in [(1, 3), (6, 8)]:
    voice[int(s*sr):int(e*sr)] = rng.normal(0, .1, (int((e-s)*sr), 2))
# short gaps between words must NOT make the music pump
for k in range(int(1.2*10), int(2.8*10), 4):
    voice[int(k/10*sr):int((k/10+0.12)*sr)] = 0
g = duck_gain(voice)
db = lambda t: 20 * np.log10(g[int(t*sr)])
check("music ducks during speech", g[int(2*sr)] < 0.4, f"({db(2):.1f} dB while talking)")
check("no pumping across 120 ms word gaps", g[int(1.5*sr):int(2.8*sr)].max() < 0.45, f"(worst {20*np.log10(g[int(1.5*sr):int(2.8*sr)].max()):.1f} dB)")
check("ducks before first word (look-ahead)", g[int(0.98*sr)] < 0.9, f"({db(0.98):.1f} dB at 20 ms before onset)")
check("music recovers in a long pause", g[int(5.8*sr)] > 0.85, f"({db(5.8):.1f} dB)")
check("music recovers after final word", g[-1] > 0.95, f"({db(11.99):.1f} dB)")

# 8. API
from fastapi.testclient import TestClient
from bgmstudio.api import app
c = TestClient(app)
check("GET /health", c.get("/health").json()["ok"])
check("GET /moods", set(c.get("/moods").json()) == set(PRESETS))
r = c.post("/bgm", json={"mood": "lofi", "duration": 25, "loop": True, "seed": 42, "format": "wav"})
d_, sr_ = sf.read(io.BytesIO(r.content))
check("POST /bgm returns audio", r.status_code == 200 and len(d_) == 25 * sr_ and r.headers["X-BGM-Seed"] == "42", f"(bpm {r.headers['X-BGM-BPM']}, key {r.headers['X-BGM-Key']})")
j = c.post("/bgm?as_json=true", json={"mood": "tech", "duration": 15, "seed": 1}).json()
check("POST /bgm?as_json", c.get(j["download_url"]).status_code == 200)
check("bad mood -> 422", c.post("/bgm", json={"mood": "nope", "duration": 10}).status_code == 422)
check("bad duration -> 422", c.post("/bgm", json={"mood": "calm", "duration": 1}).status_code == 422)

t = time.time()
with c.stream("GET", "/bgm/stream", params={"mood": "cinematic", "duration": 120, "seed": 3}) as resp:
    it = resp.iter_bytes(65536)
    first = next(it); t_first = time.time() - t
    body = first + b"".join(it)
t_all = time.time() - t
d_, sr_ = sf.read(io.BytesIO(body))
lu = measure_lufs(d_.astype("float32"), sr_)
check("stream: exact length + Content-Length", len(d_) == 120 * sr_ and int(resp.headers["content-length"]) == len(body))
check("stream: loudness near target (no look-ahead)", abs(lu + 20) < 2.5, f"({lu:.1f} LUFS)")
check("stream: faster than realtime", t_all < 120 / 5, f"(first bytes {t_first:.2f}s, all 120s audio in {t_all:.1f}s)")

# mix: synthetic narration (bursts of noise) through the API
nar = np.zeros((12 * SR, 2), dtype=np.float32)
for s, e in [(0.3, 3.0), (4.0, 7.0), (8.0, 11.5)]:
    seg = rng.normal(0, .12, (int((e - s) * SR), 2)).astype(np.float32)
    nar[int(s*SR):int(e*SR)] = seg
buf = io.BytesIO(); sf.write(buf, nar, SR, format="WAV"); buf.seek(0)
r = c.post("/mix", files={"narration": ("n.wav", buf, "audio/wav")}, data={"mood": "calm", "seed": "8"})
m_, sr_ = sf.read(io.BytesIO(r.content), dtype="float32")
check("POST /mix total length = lead+narration+tail", r.status_code == 200 and abs(len(m_) / sr_ - (1.5 + 12 + 3)) < 0.01, f"({len(m_)/sr_:.2f}s)")
fl = measure_lufs(m_, sr_)
check("mix final loudness ~ -16 LUFS", abs(fl + 16) < 1.0, f"({fl:.2f})")
lead = np.sqrt(np.mean(m_[:int(1.4*sr_)] ** 2)); tail = np.sqrt(np.mean(m_[-int(2.5*sr_):-int(0.5*sr_)] ** 2))
check("music audible in lead-in and tail", lead > 1e-4 and tail > 1e-4, f"(lead RMS {lead:.4f}, tail RMS {tail:.4f})")

# 8b. scene sequences
scenes = [{"mood": "lofi", "duration": 20}, {"mood": "cinematic", "duration": 25.5}, {"mood": "dark", "duration": 12}]
sa, summ, slufs, skey = service.render_sequence(scenes, xfade=2, seed=3)
check("sequence exact total length", len(sa) == round(57.5 * SR), f"({len(sa)/SR:.3f}s)")
check("scenes start on schedule", [x["start"] for x in summ] == [0, 20, 45.5], str([x["start"] for x in summ]))
check("all scenes share one key", len({x["key"].split()[0] for x in summ}) == 1, f"({skey}; {[x['key'] for x in summ]})")
mono = sa.mean(axis=1); dd = np.abs(np.diff(mono)); ref = np.percentile(dd, 99.9)
for b in (20, 45.5):
    i0 = int(b * SR)
    check(f"no click at cut {b}s", dd[i0 - int(.05*SR): i0 + int(.05*SR)].max() < ref * 1.5, f"(local max {dd[i0-int(.05*SR):i0+int(.05*SR)].max():.4f}, ref {ref:.4f})")
check("sequence loudness on target", abs(slufs + 20) < 1.5, f"({slufs:.2f} LUFS)")
try:
    service.render_sequence([{"mood": "lofi", "duration": 2}]); check("rejects <4s scene", False)
except ValueError:
    check("rejects <4s scene", True)
r = c.post("/sequence", json={"scenes": [{"mood": "tech", "duration": 10}, {"mood": "calm", "duration": 14.25}], "seed": 2, "format": "flac"})
d_, sr_ = sf.read(io.BytesIO(r.content))
check("POST /sequence", r.status_code == 200 and len(d_) == round(24.25 * sr_), f"(key {r.headers['X-BGM-Key']})")
buf = io.BytesIO(); sf.write(buf, nar, SR, format="WAV"); buf.seek(0)
import json as _json
r = c.post("/mix", files={"narration": ("n.wav", buf, "audio/wav")},
           data={"scenes": _json.dumps([{"mood": "lofi", "duration": 5}, {"mood": "tech", "duration": 7}]), "seed": "8"})
m_, sr_ = sf.read(io.BytesIO(r.content), dtype="float32")
check("POST /mix with per-scene moods", r.status_code == 200 and abs(len(m_) / sr_ - 16.5) < 0.01, f"({len(m_)/sr_:.2f}s)")
buf.seek(0)
r = c.post("/mix", files={"narration": ("n.wav", buf, "audio/wav")}, data={"scenes": _json.dumps([{"mood": "lofi", "duration": 30}])})
check("scene/narration length mismatch -> 422", r.status_code == 422)

# 8c. tempo matching
HARD = [{"mood": "ambient", "duration": 20}, {"mood": "tech", "duration": 18}, {"mood": "calm", "duration": 22}, {"mood": "uplifting", "duration": 16}]
TYPICAL = [{"mood": m, "duration": d} for m, d in [("calm", 30), ("lofi", 30), ("cinematic", 40), ("dark", 25), ("corporate", 30)]]
for label, sc in [("hard 4-scene", HARD), ("typical 5-scene", TYPICAL)]:
    _, off, _, _ = service.render_sequence(sc, seed=3, tempo_match=False)
    a_, on, _, _ = service.render_sequence(sc, seed=3, tempo_match=True)
    j_off = [x["bpm_jump_from_prev"] for x in off[1:]]; j_on = [x["bpm_jump_from_prev"] for x in on[1:]]
    check(f"tempo match: {label} jumps <= 6 BPM", max(j_on) <= 6.5, f"(off {j_off} -> on {j_on})")
    check(f"tempo match: {label} improves on unmatched", max(j_on) < max(j_off))
    check(f"tempo match: {label} exact length kept", len(a_) == round(sum(x['duration'] for x in sc) * SR))
FAST = [{"mood": m, "duration": d} for m, d in [("lofi", 12), ("tech", 9), ("dark", 14), ("uplifting", 10), ("calm", 11), ("cinematic", 13)]]
_, on, _, _ = service.render_sequence(FAST, seed=3)
check("tempo match: 9-14 s scenes", max(x["bpm_jump_from_prev"] for x in on[1:]) <= 6.5, f"({[x['bpm_jump_from_prev'] for x in on[1:]]})")
_, fixed, _, _ = service.render_sequence([{"mood": "lofi", "duration": 20, "bpm": 90}, {"mood": "calm", "duration": 20}], seed=3)
check("tempo match respects a scene's explicit bpm", abs(fixed[0]["bpm"] - 90) < 6)
x1, _, _, _ = service.render_sequence(TYPICAL, seed=9); x2, _, _, _ = service.render_sequence(TYPICAL, seed=9)
check("sequence is deterministic", np.array_equal(x1, x2))

# 8d. transitions
TR = [{"mood": "calm", "duration": 14}, {"mood": "cinematic", "duration": 14}, {"mood": "calm", "duration": 14}]
cut = int(14 * SR)
base_a, base_s, _, _ = service.render_sequence(TR, seed=4, transitions="none")
rms = lambda a, t0, t1: float(np.sqrt(np.mean(a[int(t0*SR):int(t1*SR)] ** 2)))
db = lambda x, y: 20 * np.log10(max(x, 1e-9) / max(y, 1e-9))
want = {"riser": (lambda a: db(rms(a, 13.0, 14.0), rms(a, 10.0, 11.0)) - db(rms(base_a, 13.0, 14.0), rms(base_a, 10.0, 11.0)), 1.0, "riser lifts the last second before the cut"),
        "impact": (lambda a: db(rms(a, 14.0, 14.4), rms(a, 10.0, 11.0)) - db(rms(base_a, 14.0, 14.4), rms(base_a, 10.0, 11.0)), 2.0, "impact hits on the downbeat"),
        "riser_impact": (lambda a: db(rms(a, 14.0, 14.4), rms(a, 10.0, 11.0)) - db(rms(base_a, 14.0, 14.4), rms(base_a, 10.0, 11.0)), 2.0, "riser_impact hits on the downbeat"),
        "downlifter": (lambda a: db(rms(a, 14.0, 15.0), rms(a, 10.0, 11.0)) - db(rms(base_a, 14.0, 15.0), rms(base_a, 10.0, 11.0)), 1.0, "downlifter adds energy after the cut"),
        "swell": (lambda a: db(rms(a, 13.5, 14.0), rms(a, 10.0, 11.0)) - db(rms(base_a, 13.5, 14.0), rms(base_a, 10.0, 11.0)), 1.0, "swell lifts into the cut")}
for name, (metric, need, label) in want.items():
    a_, sm, l_, _ = service.render_sequence(TR, seed=4, transitions=name)
    gain = metric(a_)
    check(f"transition {name:12s} {label}", gain >= need, f"(+{gain:.1f} dB vs none)")
    check(f"transition {name:12s} length/finite/no clipping/loudness", len(a_) == len(base_a) and np.isfinite(a_).all() and np.abs(a_).max() <= 1.0 and abs(l_ + 20) < 1.5,
          f"(peak {np.abs(a_).max():.2f}, {l_:.1f} LUFS)")
a_, _, _, _ = service.render_sequence(TR, seed=4, transitions="swell")
clk = np.abs(np.diff(a_.mean(axis=1))); check("swell is smooth through the cut (no step)", clk[cut - 200:cut + 200].max() < np.percentile(clk, 99.9) * 1.5)
_, sm, _, _ = service.render_sequence(TR, seed=4, transitions="auto")
check("auto: calm->cinematic = riser_impact, cinematic->calm = downlifter", [x["transition_in"] for x in sm[1:]] == ["riser_impact", "downlifter"], str([x["transition_in"] for x in sm[1:]]))
_, sm, _, _ = service.render_sequence([{"mood": "lofi", "duration": 8}, {"mood": "lofi", "duration": 8}, {"mood": "calm", "duration": 8}, {"mood": "uplifting", "duration": 8}], seed=4, transitions="auto")
check("auto: same energy = swell, energy drop = downlifter, big rise = riser_impact", [x["transition_in"] for x in sm[1:]] == ["swell", "downlifter", "riser_impact"], str([x["transition_in"] for x in sm[1:]]))
TR2 = [dict(x) for x in TR]; TR2[1]["transition"] = "none"; TR2[2]["transition"] = "impact"
_, sm, _, _ = service.render_sequence(TR2, seed=4, transitions="riser")
check("per-scene transition overrides the default", [x["transition_in"] for x in sm[1:]] == ["none", "impact"])
for bad in ("whoosh",):
    try:
        service.render_sequence(TR, transitions=bad); check("rejects unknown transition", False)
    except ValueError as e:
        check("rejects unknown transition", "unknown transition" in str(e))
r = c.post("/sequence?as_json=true", json={"scenes": [{"mood": "calm", "duration": 10}, {"mood": "tech", "duration": 10, "transition": "riser_impact"}],
                                           "transitions": "swell", "seed": 2, "max_bpm_jump": 5})
j = r.json()
check("API /sequence transitions + tempo options", r.status_code == 200 and j["scenes"][1]["transition_in"] == "riser_impact" and "bpm_jump_from_prev" in j["scenes"][1], f"(jump {j['scenes'][1].get('bpm_jump_from_prev')})")
check("API rejects bad transition -> 422", c.post("/sequence", json={"scenes": [{"mood": "calm", "duration": 10}], "transitions": "nope"}).status_code == 422)
buf = io.BytesIO(); sf.write(buf, nar, SR, format="WAV"); buf.seek(0)
r = c.post("/mix", files={"narration": ("n.wav", buf, "audio/wav")}, data={"scenes": _json.dumps([{"mood": "calm", "duration": 5}, {"mood": "tech", "duration": 7}]), "transitions": "auto", "seed": "8"})
m_, sr_ = sf.read(io.BytesIO(r.content), dtype="float32")
check("POST /mix with scenes + auto transitions", r.status_code == 200 and abs(len(m_) / sr_ - 16.5) < 0.01 and np.abs(m_).max() <= 1.0)

# 9. MCP over stdio
async def mcp_roundtrip():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable, args=["-m", "bgmstudio.mcp_server"],
                                   env={**os.environ, "BGM_OUT_DIR": os.environ["BGM_OUT_DIR"]})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            res = await s.call_tool("generate_bgm", {"mood": "corporate", "duration_seconds": 20, "seed": 5, "loop": True})
            return tools, res
tools, res = asyncio.run(mcp_roundtrip())
txt = res.content[0].text
check("MCP tools listed", set(tools) == {"list_moods", "generate_bgm", "generate_scene_sequence", "mix_with_narration"}, str(tools))
check("MCP generate_bgm works", not getattr(res, "is_error", getattr(res, "isError", False)) and "corporate" in txt and ".wav" in txt)

print("\nALL PASSED" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
