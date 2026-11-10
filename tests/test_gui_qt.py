# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""PyQt6 console tests: offscreen, with a fake client (no server, no audio device, no display)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest = __import__("pytest")
pytest.importorskip("PyQt6")

from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import bgmgui.window as W  # noqa: E402
from bgmgui import theme  # noqa: E402

MOODS = {"calm": "Soft piano and pads.", "horror": "Choir pad over a contrabass drone.", "sleep": "Very slow."}
CUES = {"duration": 30.0, "time_signature": "4/4", "transitions": [{"time": 15.0, "type": "swell", "scene": 2}],
        "sections": [{"scene": 1, "kind": "intro", "start": 0.0, "end": 10.0, "bars": 4},
                     {"scene": 1, "kind": "peak", "start": 10.0, "end": 30.0, "bars": 8, "intensity": 0.9}],
        "downbeats": [i * 2.5 for i in range(12)], "scenes": []}


class FakeClient:
    def __init__(self, *, up=True, healthy=True, fail_music=None):
        self.up, self.healthy, self.fail_music = up, healthy, fail_music
        self.started = self.stopped = False
        self.calls = []

    def is_up(self):
        return self.up

    def start_server(self):
        self.started = self.up = True

    def stop_server(self):
        self.stopped = True

    def health(self):
        return {"ok": self.healthy, "error": "no SoundFont found"}

    def moods(self):
        return dict(MOODS)

    def music(self, mood, duration, out, **kw):
        self.calls.append((mood, duration, out, kw))
        if self.fail_music:
            raise RuntimeError(self.fail_music)
        with open(out, "wb") as f:
            f.write(b"RIFF")
        return {"path": out, "seed": 4471, "bpm": 59.2, "key": "A# minor", "duration": duration, "loop": False,
                "cues": CUES, "stems": {}, "meta_path": out[:-4] + ".json",
                "provenance": {"soundfont": {"file": "TimGM6mb.sf2", "license": "GPL-2.0", "music_use": "unsettled"}}}

    def _multi(self, out, scenes, extra):
        with open(out, "wb") as f:
            f.write(b"RIFF")
        t, cs = 0.0, []
        for i, sc in enumerate(scenes, 1):
            cs.append({"scene": i, "mood": sc["mood"], "start": t, "end": t + sc["duration"], "bpm": 50.0 + 10 * i,
                       "key": "D minor"})
            t += sc["duration"]
        cues = {"duration": t, "scenes": cs, "sections": [{"scene": c["scene"], "kind": "verse", "start": c["start"],
                                                           "end": c["end"], "bars": 4} for c in cs],
                "downbeats": [], "transitions": [{"time": c["start"], "type": "swell", "scene": c["scene"]}
                                                 for c in cs[1:]], **extra}
        return {"path": out, "seed": 77, "cues": cues, "stems": {}, "meta_path": out[:-4] + ".json",
                "provenance": {"soundfont": {"file": "GeneralUser-GS.sf2", "license": "GeneralUser GS License v2.0"}}}

    def sequence(self, scenes, out, **kw):
        self.calls.append(("sequence", scenes, out, kw))
        return {**self._multi(out, scenes, {}), "key": "D", "duration": sum(s["duration"] for s in scenes),
                "warnings": ["horror -> sleep could not be brought within 6 BPM"]}

    def score(self, narration, out, **kw):
        self.calls.append(("score", narration, out, kw))
        total = kw["lead_in"] + sum(s["duration"] for s in kw["scenes"]) + kw["tail_out"]
        return {**self._multi(out, kw["scenes"], {"narration": {"start": kw["lead_in"], "end": total - kw["tail_out"]}}),
                "total_seconds": total}


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    W.apply_theme(a)
    return a


@pytest.fixture()
def no_audio(monkeypatch):
    """Count QtMultimedia constructions: on a broken audio stack creating them can crash the process, so the
    console must not create them until the operator presses PLAY.  (Counting, not raising: an exception inside a
    Qt slot aborts the whole test run.)"""
    made = []

    class Spy:
        PlaybackState = W.QMediaPlayer.PlaybackState if W.QMediaPlayer else None

        def __init__(self, *a, **k):
            made.append(type(self).__name__)

        def __getattr__(self, _name):  # any method / signal: accept and ignore
            class Anything:
                def __call__(self, *a, **k):
                    return self

                def __getattr__(self, _n):
                    return self
            return Anything()
    monkeypatch.setattr(W, "QMediaPlayer", type("QMediaPlayer", (Spy,), {}))
    monkeypatch.setattr(W, "QAudioOutput", type("QAudioOutput", (Spy,), {}))
    return made


def wait_for(cond, ms=10000) -> bool:
    """PyQt6 has no QTest.qWaitFor: pump the event loop until `cond()` or the deadline."""
    import time
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        if cond():
            return True
        QTest.qWait(20)
    return cond()


def make(app, client, tmp_path, connect=True):
    w = W.MainWindow(client_factory=lambda: client, autoconnect=False)
    w.folder.setText(str(tmp_path))
    if connect:
        w.reconnect()
        assert wait_for(lambda: not w._worker_refs, 5000)
    return w


def wait_idle(w):
    assert wait_for(lambda: not w._worker_refs, 10000), "worker did not finish"


def test_connect_loads_moods_from_the_service(app, tmp_path):
    w = make(app, FakeClient(), tmp_path)
    assert [w.mood.itemText(i) for i in range(w.mood.count())] == list(MOODS)
    w.mood.setCurrentText("horror")
    assert w.mood_desc.text() == MOODS["horror"]
    assert w.status_text.text() == "READY" and w.generate_btn.isEnabled()
    seq_mood = w.sequencer.table.cellWidget(0, 1)
    assert [seq_mood.itemText(i) for i in range(seq_mood.count())] == list(MOODS), "sequencer uses server moods"


def test_starts_service_when_down_and_stops_only_its_own(app, tmp_path):
    mine = FakeClient(up=False)
    w = make(app, mine, tmp_path)
    assert mine.started and w.own_server
    w.close()
    assert mine.stopped
    theirs = FakeClient(up=True)
    w2 = make(app, theirs, tmp_path)
    w2.close()
    assert not theirs.stopped, "a service someone else started must keep running"


def test_unhealthy_service_reports_and_blocks_generate(app, tmp_path):
    w = make(app, FakeClient(healthy=False), tmp_path)
    assert w.status_text.text() == "FAILED" and "SoundFont" in w.status_detail.text()
    assert "NO SERVICE" in w.connection.text() and not w.generate_btn.isEnabled()


def test_generate_end_to_end_without_touching_audio(app, tmp_path, no_audio):
    client = FakeClient()
    w = make(app, client, tmp_path)
    w.mood.setCurrentText("horror")
    w.duration.setValue(30)
    w.intensity.setValue(62)
    w.stems.setChecked(True)
    w.filename.setText("ch01")
    w.generate()
    wait_idle(w)
    mood, duration, out, kw = client.calls[0]
    assert (mood, duration, os.path.basename(out)) == ("horror", 30.0, "ch01.wav")
    assert kw["intensity"] == 0.62 and kw["stems"] is True and kw["seed"] is None
    assert w.meta["seed"].text() == "4471" and w.meta["key"].text() == "A# minor"
    assert w.meta["structure"].text() == "2 sections"
    assert w.cues._cues is CUES and "GPL-2.0" in w.licence.text()
    assert w.play_btn.isEnabled() and no_audio == [], "player is created on first PLAY, not on render"
    assert w.status_text.text() == "RENDER COMPLETE"


def test_failed_render_is_reported_and_console_recovers(app, tmp_path):
    w = make(app, FakeClient(fail_music="total duration exceeds render budget"), tmp_path)
    w.generate()
    wait_idle(w)
    assert w.status_text.text() == "FAILED" and "budget" in w.status_detail.text()
    assert w.generate_btn.isEnabled() and not w._worker_refs


def test_bad_seed_is_flagged_without_rendering(app, tmp_path):
    client = FakeClient()
    w = make(app, client, tmp_path)
    w.seed.setText("banana")
    w.generate()
    assert not w._worker_refs and not client.calls
    assert w.status_text.text() == "CHECK SETTINGS" and w.seed.property("invalid") is True


def test_existing_file_asks_before_replacing(app, tmp_path, monkeypatch):
    client = FakeClient()
    w = make(app, client, tmp_path)
    (tmp_path / "bgm_track.wav").write_bytes(b"x")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    w.generate()
    assert not client.calls and not w._worker_refs


def test_reuse_settings_puts_seed_back(app, tmp_path):
    w = make(app, FakeClient(), tmp_path)
    w.generate()
    wait_idle(w)
    w.reuse_settings()
    assert w.seed.text() == "4471"


def test_window_opens_large_enough_for_its_controls(app, tmp_path):
    """An explicit minimum below the layout's own minimum lets Qt squash the inputs (seen in 0.10.3's first cut)."""
    w = make(app, FakeClient(), tmp_path, connect=False)
    hint, explicit = w.minimumSizeHint(), w.minimumSize()
    assert w.width() >= hint.width() and w.height() >= hint.height()
    assert explicit.isNull() or (explicit.width() >= hint.width() and explicit.height() >= hint.height())


def test_slider_disabled_rule_uses_valid_selector():
    """`QSlider:disabled::sub-page` is misread by Qt and paints grey bands over every slider."""
    assert "QSlider:disabled::" not in theme.QSS and "::sub-page:horizontal:disabled" in theme.QSS


def test_palette_is_the_design_system():
    assert (theme.OBSIDIAN, theme.PANEL, theme.BORDER, theme.TEAL, theme.PHOSPHOR, theme.AMBER, theme.RED,
            theme.TEXT) == ("#0b0f14", "#11161d", "#1e2831", "#2fd6c3", "#4be08a", "#ffb454", "#ff6b6b", "#c8d3da")
    assert "border-radius: 0" in theme.QSS and "JetBrains Mono" in theme.QSS


# ---------------------------------------------------------------- SEQUENCE tab
def seq_rows(*spec):
    return [{"mood": m, "duration": d, "intensity": i, "transition": t, "bpm": None} for m, d, i, t in spec]


def test_scene_editing_toolbar(app, tmp_path):
    w = make(app, FakeClient(), tmp_path)
    sq = w.sequencer
    sq.set_rows(seq_rows(("sleep", 20, None, "default"), ("horror", 10, 0.9, "riser")), 0)
    sq.add_scene()                       # after the selected one, same mood
    assert [r["mood"] for r in sq.rows()] == ["sleep", "sleep", "horror"] and sq.selected() == 1
    sq.duplicate_scene()
    assert len(sq.rows()) == 4 and sq.selected() == 2
    sq.remove_scene()
    sq.table.selectRow(2)
    sq.move_scene(-5)                    # out of range: nothing happens
    sq.move_scene(-1)
    sq.move_scene(-1)                    # horror to the top: the first scene has no cut into it
    r = sq.rows()
    assert r[0]["mood"] == "horror" and r[0]["transition"] == "default" and r[0]["intensity"] == 0.9
    assert not sq.table.cellWidget(0, 4).isEnabled() and sq.table.cellWidget(1, 4).isEnabled()
    assert sq.table.item(2, 6).text() == "00:30", "start column follows the lengths"


def test_rows_round_trip_through_widgets(app, tmp_path):
    w = make(app, FakeClient(), tmp_path)
    rows = seq_rows(("sleep", 20.25, None, "default"), ("horror", 14.5, 0.35, "swell"))
    rows[1]["bpm"] = 72.0
    w.sequencer.set_rows(rows)
    assert w.sequencer.rows() == rows


def test_generate_sequence_sends_scenes_and_settings(app, tmp_path):
    client = FakeClient()
    w = make(app, client, tmp_path)
    w.tabs.setCurrentIndex(1)
    assert w.filename.text() == "bgm_sequence" and w.generate_btn.text() == "GENERATE SEQUENCE"
    w.sequencer.set_rows(seq_rows(("sleep", 20, 0.2, "default"), ("horror", 15, 0.9, "riser_impact")))
    w.sequencer.set_settings({**w.sequencer.settings(), "transitions": "swell", "xfade": 3.0, "tempo_match": False})
    w.seed.setText("77")
    w.stems.setChecked(True)
    w.generate()
    wait_idle(w)
    kind, scenes, out, kw = client.calls[0]
    assert kind == "sequence" and os.path.basename(out) == "bgm_sequence.wav"
    assert scenes == [{"mood": "sleep", "duration": 20.0, "intensity": 0.2},
                      {"mood": "horror", "duration": 15.0, "intensity": 0.9, "transition": "riser_impact"}]
    assert kw == {"seed": 77, "xfade": 3.0, "tempo_match": False, "max_bpm_jump": 6.0, "transitions": "swell",
                  "stems": True}
    assert w.meta["structure"].text() == "2 scenes · 2 sect" and w.meta["bpm"].text() == "60–70"
    assert "could not be brought within" in w.log_view.toPlainText(), "tempo warnings reach the log"


def _narration(tmp_path, seconds):
    import numpy as np
    import soundfile as sf
    p = tmp_path / "voice.wav"
    sf.write(str(p), np.zeros(int(8000 * seconds), dtype=np.float32), 8000)
    return str(p)


def test_narration_must_fit_then_fit_and_score(app, tmp_path):
    client = FakeClient()
    w = make(app, client, tmp_path)
    w.tabs.setCurrentIndex(1)
    w.sequencer.set_rows(seq_rows(("sleep", 20, None, "default"), ("horror", 20, None, "default")))
    w.sequencer.browse_narration(_narration(tmp_path, 50.0))
    assert w.generate_btn.text() == "SCORE NARRATION"
    w.generate()
    assert not client.calls and "shorter than the narration" in w.status_detail.text()
    w.sequencer.fit_to_narration()
    assert sum(r["duration"] for r in w.sequencer.rows()) == pytest.approx(50.0, abs=0.02)
    assert "match" in w.sequencer.fit_label.text()
    w.generate()
    wait_idle(w)
    kind, narration, out, kw = client.calls[0]
    assert kind == "score" and narration.endswith("voice.wav")
    assert (kw["lead_in"], kw["tail_out"], kw["duck_db"]) == (1.5, 3.0, 9.0)
    assert w.meta["length"].text() == "00:54" and w.cues._cues["narration"] == {"start": 1.5, "end": 51.5}
    w.sequencer.clear_narration()
    assert w.generate_btn.text() == "GENERATE SEQUENCE" and not w.sequencer.fit_btn.isEnabled()


def test_over_long_sequence_is_refused(app, tmp_path):
    client = FakeClient()
    w = make(app, client, tmp_path)
    w.tabs.setCurrentIndex(1)
    w.sequencer.set_rows(seq_rows(("calm", 3600, None, "default"), ("calm", 3601, None, "default")))
    w.generate()
    assert not client.calls and "limit is 7200" in w.status_detail.text()


def test_scene_file_save_and_load_through_the_tab(app, tmp_path):
    w = make(app, FakeClient(), tmp_path)
    sq = w.sequencer
    sq.set_rows(seq_rows(("sleep", 20, 0.1, "default"), ("horror", 15, 1.0, "impact")))
    sq.set_settings({**sq.settings(), "transitions": "riser"})
    path = str(tmp_path / "ch01.json")
    sq.save_file(path)
    sq.set_rows(seq_rows(("calm", 9, None, "default")))
    sq.load_file(path)
    assert [(r["mood"], r["duration"], r["intensity"]) for r in sq.rows()] == [("sleep", 20, 0.1), ("horror", 15, 1.0)]
    assert sq.settings()["transitions"] == "riser"
    (tmp_path / "bad.json").write_text('[{"mood": "jazz", "duration": 5}]')
    sq.load_file(str(tmp_path / "bad.json"))
    assert "unknown mood 'jazz'" in w.log_view.toPlainText() and len(sq.rows()) == 2


def test_scene_bar_click_selects_scene(app, tmp_path):
    from PyQt6.QtCore import QPoint, Qt
    w = make(app, FakeClient(), tmp_path)
    sq = w.sequencer
    sq.set_rows(seq_rows(("sleep", 10, None, "default"), ("horror", 30, None, "default")))
    sq.scene_bar.resize(400, 44)
    QTest.mouseClick(sq.scene_bar, Qt.MouseButton.LeftButton, pos=QPoint(300, 20))
    assert sq.selected() == 1


def test_multi_scene_cue_strip_paints(app, tmp_path):
    w = make(app, FakeClient(), tmp_path)
    w.tabs.setCurrentIndex(1)
    w.sequencer.set_rows(seq_rows(("sleep", 10, None, "default"), ("horror", 30, None, "default")))
    w.generate()
    wait_idle(w)
    w.cues.resize(500, 64)
    assert not w.cues.grab().isNull()
