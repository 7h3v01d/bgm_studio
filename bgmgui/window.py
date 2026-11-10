# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""Main window: parameters, status, latest output (with playback and cue strip), and an operator log."""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QThread, QTimer, QUrl, Qt, pyqtSlot
from PyQt6.QtGui import QFontDatabase, QGuiApplication
from PyQt6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                             QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                             QSlider, QTabWidget, QVBoxLayout, QWidget)

from . import theme
from .scenes import narration_fit, result_summary, to_api, validate_rows
from .sequencer import SequencerTab
from .validation import FORMATS, MOODS, export_path, parse_seed, validate_track
from .widgets import CueStrip, Led, Panel, Worker, field_label

DEFAULT_NAMES = ("bgm_track", "bgm_sequence")
TAB_TRACK, TAB_SEQUENCE = 0, 1

SERVICE_URL = "http://127.0.0.1:8765"
PROJECT_DIR = Path(__file__).resolve().parent.parent

try:  # playback is optional: the console works without QtMultimedia
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
except ImportError:  # pragma: no cover - depends on the PyQt6 build
    QMediaPlayer = QAudioOutput = None


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}" if seconds >= 3600 \
        else f"{seconds // 60:02d}:{seconds % 60:02d}"


class MainWindow(QMainWindow):
    def __init__(self, client_factory: Callable | None = None, *, autoconnect: bool = True):
        super().__init__()
        self.setWindowTitle("BGM Studio")
        # no explicit minimum: the layout's own minimum applies, so controls are never squeezed
        self._client_factory = client_factory or self._default_client
        self.client = None
        self.own_server = False
        self.moods: dict[str, str] = {m: "" for m in MOODS}
        self.last_result: dict | None = None
        self._worker_refs: list[tuple[QThread, Worker]] = []
        self._busy_since: float | None = None
        self._closing = False
        self.player = None  # created on first PLAY (see _ensure_player)
        self._audio_ok = QMediaPlayer is not None and os.environ.get("BGM_GUI_NO_AUDIO") != "1"
        self._source: Path | None = None

        self._build()
        self._elapsed = QTimer(self)
        self._elapsed.setInterval(250)
        self._elapsed.timeout.connect(self._tick)
        if not self._audio_ok:
            self.play_btn.setToolTip("Playback is off (BGM_GUI_NO_AUDIO=1, or QtMultimedia is missing).")
        self._set_connection("offline")
        hint = self.sizeHint()
        w, h = max(1280, hint.width()), max(880, hint.height())
        screen = QGuiApplication.primaryScreen()
        if screen is not None:  # never open bigger than the screen (the layout minimum still applies)
            avail = screen.availableGeometry()
            w, h = min(w, avail.width()), min(h, avail.height())
        self.resize(max(w, self.minimumSizeHint().width()), max(h, self.minimumSizeHint().height()))
        self.log("Console started")
        if autoconnect:
            QTimer.singleShot(0, self.reconnect)

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        page = QVBoxLayout(root)
        page.setContentsMargins(22, 14, 22, 8)
        page.setSpacing(10)

        header = QHBoxLayout()
        brand = QLabel("BGM")
        brand.setObjectName("brand")
        slash = QLabel("//")
        slash.setObjectName("brandAccent")
        studio = QLabel("STUDIO")
        studio.setObjectName("brand")
        sub = QLabel("PROCEDURAL SCORE ENGINE  ·  LOCAL CONSOLE")
        sub.setObjectName("subtitle")
        for w in (brand, slash, studio):
            header.addWidget(w)
        header.addSpacing(14)
        header.addWidget(sub, 0, Qt.AlignmentFlag.AlignBottom)
        header.addStretch(1)
        self.led = Led()
        self.connection = QLabel()
        self.connection.setObjectName("fieldLabel")
        header.addWidget(self.led)
        header.addSpacing(6)
        header.addWidget(self.connection)
        page.addLayout(header)
        rule = QFrame()
        rule.setObjectName("accentRule")
        page.addWidget(rule)

        cols = QHBoxLayout()
        cols.setSpacing(12)
        cols.addWidget(self._params_panel(), 6)
        right = QVBoxLayout()
        right.setSpacing(12)
        right.addWidget(self._status_panel())
        right.addWidget(self._output_panel(), 1)
        right.addWidget(self._log_panel())
        cols.addLayout(right, 5)
        page.addLayout(cols, 1)
        self.statusBar().showMessage(f"SERVICE {SERVICE_URL}   ·   PROJECT {PROJECT_DIR}")

    def _params_panel(self) -> Panel:
        panel = Panel("01", "PARAMETERS")
        b = panel.body
        self.tabs = QTabWidget()
        self.tabs.addTab(self._track_tab(), "TRACK")
        self.sequencer = SequencerTab(list(self.moods))
        self.sequencer.message.connect(self.log)
        self.sequencer.changed.connect(self._update_generate_label)
        self.tabs.addTab(self.sequencer, "SEQUENCE")
        self.tabs.currentChanged.connect(self._tab_changed)
        b.addWidget(self.tabs, 1)

        shared = QGridLayout()
        shared.setHorizontalSpacing(10)
        shared.setVerticalSpacing(3)
        shared.addWidget(field_label("Seed"), 0, 0)
        shared.addWidget(field_label("Format"), 0, 1)
        self.seed = QLineEdit()
        self.seed.setPlaceholderText("random")
        self.seed.setToolTip("Same seed + same settings = the same music. Leave blank for a new piece.")
        self.seed.textChanged.connect(lambda _: self.seed.setProperty("invalid", False) or self._restyle(self.seed))
        self.format = QComboBox()
        self.format.addItems(FORMATS)
        self.stems = QPushButton("EXPORT STEMS")
        self.stems.setObjectName("toggle")
        self.stems.setCheckable(True)
        self.stems.setToolTip("Also write files that add up to the result: instrument groups for tracks, plus fx "
                              "for sequences, or voice / music / fx for a narration mix (max 1 hour).")
        shared.addWidget(self.seed, 1, 0)
        shared.addWidget(self.format, 1, 1)
        shared.addWidget(self.stems, 1, 2)
        shared.setColumnStretch(0, 1)
        shared.addWidget(field_label("Export folder"), 2, 0, 1, 2)
        shared.addWidget(field_label("File name (no extension)"), 2, 2)
        dest = QHBoxLayout()
        self.folder = QLineEdit(str(PROJECT_DIR / "gui_exports"))
        browse = QPushButton("BROWSE")
        browse.clicked.connect(self._browse)
        dest.addWidget(self.folder, 1)
        dest.addWidget(browse)
        shared.addLayout(dest, 3, 0, 1, 2)
        self.filename = QLineEdit(DEFAULT_NAMES[TAB_TRACK])
        self.filename.textChanged.connect(lambda _: self.filename.setProperty("invalid", False)
                                          or self._restyle(self.filename))
        shared.addWidget(self.filename, 3, 2)
        b.addLayout(shared)

        self.generate_btn = QPushButton("GENERATE TRACK")
        self.generate_btn.setObjectName("primary")
        self.generate_btn.setToolTip("Rendered locally. Nothing leaves this machine.")
        self.generate_btn.clicked.connect(self.generate)
        b.addWidget(self.generate_btn)
        return panel

    def _track_tab(self) -> QWidget:
        tab = QWidget()
        b = QVBoxLayout(tab)
        b.setContentsMargins(0, 10, 0, 0)
        b.setSpacing(8)
        b.addWidget(field_label("Mood"))
        self.mood = QComboBox()
        self.mood.addItems(MOODS)
        self.mood.setCurrentText("ambient")
        self.mood.currentTextChanged.connect(self._mood_changed)
        b.addWidget(self.mood)
        self.mood_desc = QLabel()
        self.mood_desc.setObjectName("hint")
        self.mood_desc.setWordWrap(True)
        self.mood_desc.setMinimumHeight(34)
        b.addWidget(self.mood_desc)

        row = QGridLayout()
        row.setHorizontalSpacing(12)
        row.setVerticalSpacing(3)
        row.addWidget(field_label("Duration"), 0, 0)
        self.duration = QDoubleSpinBox()
        self.duration.setRange(4, 7200)
        self.duration.setDecimals(1)
        self.duration.setValue(60)
        self.duration.setSuffix(" s")
        self.duration.setToolTip("4 s to 2 hours. The file is exactly this long.")
        self.duration.valueChanged.connect(self._duration_changed)
        self.duration_clock = QLabel()
        self.duration_clock.setObjectName("value")
        self.loop = QPushButton("SEAMLESS LOOP")
        self.loop.setObjectName("toggle")
        self.loop.setCheckable(True)
        self.loop.setToolTip("Ends where it starts, for looping under long content.")
        row.addWidget(self.duration, 1, 0)
        row.addWidget(self.duration_clock, 1, 1)
        row.addWidget(self.loop, 1, 2)
        row.setColumnStretch(0, 1)
        row.setColumnStretch(2, 1)
        b.addLayout(row)

        b.addWidget(field_label("Intensity"))
        irow = QHBoxLayout()
        self.intensity = QSlider(Qt.Orientation.Horizontal)
        self.intensity.setRange(0, 100)
        self.intensity.setValue(50)
        self.intensity.setToolTip("0.50 = the mood as designed. Lower is sparser and quieter, higher is busier.")
        self.intensity_value = QLabel("0.50")
        self.intensity_value.setObjectName("bigValue")
        self.intensity_value.setFixedWidth(56)
        self.intensity_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.intensity.valueChanged.connect(lambda v: self.intensity_value.setText(f"{v / 100:.2f}"))
        irow.addWidget(self.intensity, 1)
        irow.addWidget(self.intensity_value)
        b.addLayout(irow)
        b.addStretch(1)
        self._mood_changed(self.mood.currentText())
        self._duration_changed(self.duration.value())
        return tab

    def _status_panel(self) -> Panel:
        panel = Panel("02", "STATUS")
        row = QHBoxLayout()
        self.status_text = QLabel("OFFLINE")
        self.status_text.setObjectName("statusText")
        self.elapsed = QLabel("")
        self.elapsed.setObjectName("value")
        row.addWidget(self.status_text, 1)
        row.addWidget(self.elapsed)
        panel.body.addLayout(row)
        self.status_detail = QLabel(SERVICE_URL)
        self.status_detail.setObjectName("hint")
        self.status_detail.setWordWrap(True)
        panel.body.addWidget(self.status_detail)
        self.busy_bar = QProgressBar()
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedHeight(6)
        self.busy_bar.setRange(0, 1)
        panel.body.addWidget(self.busy_bar)
        self.reconnect_btn = QPushButton("RECONNECT")
        self.reconnect_btn.clicked.connect(self.reconnect)
        panel.body.addWidget(self.reconnect_btn)
        return panel

    def _output_panel(self) -> Panel:
        panel = Panel("03", "LATEST OUTPUT")
        b = panel.body
        self.out_name = QLabel("No render yet")
        self.out_name.setObjectName("fileName")
        self.out_name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        b.addWidget(self.out_name)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(2)
        self.meta: dict[str, QLabel] = {}
        for i, key in enumerate(("seed", "bpm", "key", "length", "structure", "stems")):
            grid.addWidget(field_label(key), 0 if i < 3 else 2, i % 3)
            v = QLabel("—")
            v.setObjectName("value")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.meta[key] = v
            grid.addWidget(v, 1 if i < 3 else 3, i % 3)
        b.addLayout(grid)

        b.addWidget(field_label("Structure  ·  sections, bars, transitions"))
        self.cues = CueStrip()
        b.addWidget(self.cues)

        transport = QHBoxLayout()
        self.play_btn = QPushButton("PLAY")
        self.play_btn.clicked.connect(self.toggle_play)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderMoved.connect(self._seek)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("value")
        transport.addWidget(self.play_btn)
        transport.addWidget(self.seek, 1)
        transport.addWidget(self.time_label)
        b.addLayout(transport)

        self.licence = QLabel("")
        self.licence.setObjectName("hint")
        self.licence.setWordWrap(True)
        b.addWidget(self.licence)
        b.addStretch(1)

        actions = QHBoxLayout()
        self.copy_seed_btn = QPushButton("COPY SEED")
        self.copy_seed_btn.clicked.connect(self.copy_seed)
        self.reuse_btn = QPushButton("REUSE SETTINGS")
        self.reuse_btn.setToolTip("Put this render's seed back into the parameters to regenerate or vary it.")
        self.reuse_btn.clicked.connect(self.reuse_settings)
        self.open_folder_btn = QPushButton("OPEN FOLDER")
        self.open_folder_btn.clicked.connect(self.open_folder)
        for w in (self.copy_seed_btn, self.reuse_btn, self.open_folder_btn):
            actions.addWidget(w)
        b.addLayout(actions)
        self._set_output_enabled(False)
        return panel

    def _log_panel(self) -> Panel:
        panel = Panel("04", "LOG")
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(84)
        self.log_view.setMaximumBlockCount(500)
        panel.body.addWidget(self.log_view)
        return panel

    # ------------------------------------------------------------------ small helpers
    @staticmethod
    def _restyle(w: QWidget) -> None:
        w.style().unpolish(w)
        w.style().polish(w)

    def log(self, text: str, level: str = "info") -> None:
        colour = {"info": theme.MUTED, "ok": theme.PHOSPHOR, "warn": theme.AMBER, "error": theme.RED}[level]
        stamp = time.strftime("%H:%M:%S")
        safe = text.replace("&", "&amp;").replace("<", "&lt;")
        self.log_view.appendHtml(f'<span style="color:{theme.MUTED}">{stamp}</span>&nbsp;&nbsp;'
                                 f'<span style="color:{colour}">{safe}</span>')

    def _set_status(self, text: str, colour: str, detail: str | None = None) -> None:
        self.status_text.setText(text)
        self.status_text.setStyleSheet(f"color: {colour};")
        if detail is not None:
            self.status_detail.setText(detail)

    def _set_connection(self, state: str) -> None:
        colour, text = {"online": (theme.PHOSPHOR, "ONLINE"), "offline": (theme.MUTED, "OFFLINE"),
                        "connecting": (theme.AMBER, "CONNECTING"), "error": (theme.RED, "NO SERVICE")}[state]
        self.led.set_colour(colour)
        self.connection.setText(f"{text}  ·  127.0.0.1:8765")
        self.generate_btn.setEnabled(state == "online" and not self._worker_refs)

    def _set_output_enabled(self, on: bool) -> None:
        for w in (self.copy_seed_btn, self.reuse_btn):
            w.setEnabled(on)
        for w in (self.play_btn, self.seek):
            w.setEnabled(on and self._audio_ok)

    @pyqtSlot(str)
    def _mood_changed(self, mood: str) -> None:
        self.mood_desc.setText(self.moods.get(mood, ""))

    @pyqtSlot(float)
    def _duration_changed(self, seconds: float) -> None:
        self.duration_clock.setText(_clock(seconds))

    @pyqtSlot()
    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Export folder", self.folder.text())
        if path:
            self.folder.setText(path)

    # ------------------------------------------------------------------ background work
    def _run(self, label: str, fn: Callable[[], object], on_done: Callable[[object], None]) -> bool:
        if self._worker_refs:
            return False
        thread = QThread()
        worker = Worker(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_done)
        worker.failed.connect(self._failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(lambda: self._worker_done(thread, worker))
        self._worker_refs.append((thread, worker))  # keep both alive until the thread has stopped
        self._busy_since = time.monotonic()
        self._set_status(label, theme.AMBER, "")
        self.busy_bar.setRange(0, 0)
        self.generate_btn.setEnabled(False)
        self.reconnect_btn.setEnabled(False)
        self._elapsed.start()
        thread.start()
        return True

    def _worker_done(self, thread: QThread, worker: Worker) -> None:
        self._worker_refs = [(t, w) for t, w in self._worker_refs if t is not thread]
        worker.deleteLater()
        thread.deleteLater()
        self._busy_since = None
        self._elapsed.stop()
        self.busy_bar.setRange(0, 1)
        self.reconnect_btn.setEnabled(True)
        self.generate_btn.setEnabled(self.client is not None)
        if self._closing:
            self.close()

    @pyqtSlot()
    def _tick(self) -> None:
        if self._busy_since is not None:
            self.elapsed.setText(_clock(time.monotonic() - self._busy_since))

    @pyqtSlot(str)
    def _failed(self, message: str) -> None:
        self._set_status("FAILED", theme.RED, message[:300])
        self.log(message, "error")
        if self.client is None:
            self._set_connection("error")

    # ------------------------------------------------------------------ connection
    @staticmethod
    def _default_client():
        from bgm_client import BGMClient
        return BGMClient(base_url=SERVICE_URL, project_dir=str(PROJECT_DIR), autostart=False, timeout=7200,
                         retries=0)

    @pyqtSlot()
    def reconnect(self) -> None:
        self.client = None
        self._set_connection("connecting")
        self.log(f"Connecting to {SERVICE_URL}")

        def connect():
            client = self._client_factory()
            started = False
            if not client.is_up():
                client.start_server()
                started = True
            health = client.health()
            if not health.get("ok"):
                raise RuntimeError(str(health.get("error", "service reported unhealthy")))
            return client, started, client.moods()
        self._run("CONNECTING", connect, self._connected)

    def _connected(self, result) -> None:
        client, started, moods = result
        self.client = client
        self.own_server = self.own_server or started
        if isinstance(moods, dict) and moods:
            current = self.mood.currentText()
            self.moods = dict(moods)
            self.mood.blockSignals(True)
            self.mood.clear()
            self.mood.addItems(list(self.moods))
            self.mood.setCurrentText(current if current in self.moods else next(iter(self.moods)))
            self.mood.blockSignals(False)
            self._mood_changed(self.mood.currentText())
            self.sequencer.set_moods(list(self.moods))
        self._set_connection("online")
        self._set_status("READY", theme.PHOSPHOR, "Engine connected." + ("  Started the local service." if started
                                                                        else ""))
        self.log(f"Connected · {len(self.moods)} moods" + (" · service started by this console" if started else ""),
                 "ok")

    # ------------------------------------------------------------------ generate
    # ------------------------------------------------------------------ tabs
    @pyqtSlot(int)
    def _tab_changed(self, index: int) -> None:
        other = DEFAULT_NAMES[1 - index] if index in (0, 1) else None
        if self.filename.text() == other:  # swap only the untouched default name
            self.filename.setText(DEFAULT_NAMES[index])
        self._update_generate_label()

    @pyqtSlot()
    def _update_generate_label(self) -> None:
        if self.tabs.currentIndex() == TAB_TRACK:
            self.generate_btn.setText("GENERATE TRACK")
        else:
            self.generate_btn.setText("SCORE NARRATION" if self.sequencer.narration()[0] else "GENERATE SEQUENCE")

    def _flag(self, widget: QWidget, message: str) -> None:
        if widget is not None:
            widget.setProperty("invalid", True)
            self._restyle(widget)
        self._set_status("CHECK SETTINGS", theme.RED, message)

    def _destination(self, fmt: str) -> Path | None:
        try:
            folder = Path(self.folder.text()).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
            path = export_path(str(folder), self.filename.text(), fmt)
        except (ValueError, OSError) as e:
            self._flag(self.filename, str(e))
            return None
        if path.exists() and QMessageBox.question(self, "Replace file?", f"{path.name} already exists. Replace it?") \
                != QMessageBox.StandardButton.Yes:
            return None
        return path

    # ------------------------------------------------------------------ generate
    @pyqtSlot()
    def generate(self) -> None:
        if self.tabs.currentIndex() == TAB_SEQUENCE:
            self.generate_sequence()
        else:
            self.generate_track()

    def generate_track(self) -> None:
        try:
            args = validate_track(self.mood.currentText(), str(self.duration.value()), self.seed.text(),
                                  self.intensity.value() / 100, self.format.currentText(), moods=self.moods)
        except ValueError as e:
            self._flag(self.seed if "Seed" in str(e) else None, str(e))
            return
        path = self._destination(args["format"])
        if path is None:
            return
        self._unload_player()
        loop, stems, client = self.loop.isChecked(), self.stems.isChecked(), self.client
        self.log(f"Render {args['mood']} · {_clock(args['duration'])} · intensity {args['intensity']:.2f}"
                 f"{' · loop' if loop else ''}{' · stems' if stems else ''} → {path.name}")

        def task():
            return client.music(args["mood"], args["duration"], str(path), seed=args["seed"],
                                intensity=args["intensity"], loop=loop, stems=stems)
        self._run("RENDERING", task, self._generated)

    def generate_sequence(self) -> None:
        try:
            seed = parse_seed(self.seed.text())
        except ValueError as e:
            self._flag(self.seed, str(e))
            return
        try:
            rows = validate_rows(self.sequencer.rows(), self.moods)
        except ValueError as e:
            m = re.match(r"Scene (\d+)", str(e))
            if m:
                self.sequencer.table.selectRow(int(m.group(1)) - 1)
            self._flag(None, str(e))
            return
        narration, narr_s = self.sequencer.narration()
        ok, fit_msg = narration_fit(sum(r["duration"] for r in rows), narr_s)
        if not ok:
            self._flag(None, fit_msg)
            return
        path = self._destination(self.format.currentText())
        if path is None:
            return
        self._unload_player()
        scenes, st, stems, client = to_api(rows), self.sequencer.settings(), self.stems.isChecked(), self.client
        common = dict(seed=seed, xfade=st["xfade"], tempo_match=st["tempo_match"], max_bpm_jump=st["max_bpm_jump"],
                      transitions=st["transitions"], stems=stems)
        what = f"{len(scenes)} scenes · {_clock(sum(s['duration'] for s in scenes))}"
        if narration:
            self.log(f"Score {Path(narration).name} · {what} · duck {st['duck_db']:.0f} dB"
                     f"{' · stems' if stems else ''} → {path.name}")

            def task():
                return client.score(narration, str(path), scenes=scenes, lead_in=st["lead_in"],
                                    tail_out=st["tail_out"], duck_db=st["duck_db"], **common)
            self._run("SCORING", task, self._generated)
        else:
            self.log(f"Sequence {what} · transitions {st['transitions']}{' · stems' if stems else ''} → {path.name}")

            def task():
                return client.sequence(scenes, str(path), **common)
            self._run("RENDERING", task, self._generated)

    def _generated(self, result: dict) -> None:
        self.last_result = result
        path = Path(result["path"])
        info = result_summary(result)
        self.out_name.setText(path.name)
        self.out_name.setToolTip(str(path))
        for key in ("seed", "bpm", "key", "structure", "stems"):
            self.meta[key].setText(info[key])
        self.meta["length"].setText(_clock(info["length"]))
        self.cues.set_cues(result.get("cues") or {})
        sf = (result.get("provenance") or {}).get("soundfont") or {}
        if sf:
            colour = theme.AMBER if sf.get("license") in ("unknown", "GPL-2.0") else theme.MUTED
            self.licence.setText(f"SoundFont: {sf.get('file', '?')} · {sf.get('license', '?')}")
            self.licence.setStyleSheet(f"color: {colour};")
            self.licence.setToolTip(sf.get("music_use", ""))
        self._set_output_enabled(True)
        self._load_player(path)
        took = self.elapsed.text()
        self._set_status("RENDER COMPLETE", theme.PHOSPHOR, f"Saved with its JSON record in {path.parent}")
        for w in info["warnings"]:
            self.log(w, "warn")
        self.log(f"Done in {took} · seed {info['seed']} · {info['key']} · {info['bpm']} BPM · {info['structure']}",
                 "ok")

    # ------------------------------------------------------------------ playback
    def _ensure_player(self) -> bool:
        """Create the media player on first use, so a broken audio setup can never stop the console starting."""
        if self.player is None and self._audio_ok:
            self.player = QMediaPlayer(self)
            self.audio_out = QAudioOutput(self)
            self.audio_out.setVolume(0.8)
            self.player.setAudioOutput(self.audio_out)
            self.player.positionChanged.connect(self._position)
            self.player.durationChanged.connect(lambda d: self.seek.setRange(0, d))
            self.player.playbackStateChanged.connect(self._playback_state)
            self.player.errorOccurred.connect(lambda _e, msg: self.log(f"Playback: {msg}", "warn"))
        return self.player is not None

    def _load_player(self, path: Path) -> None:
        self._source = path
        self.seek.setValue(0)
        self.time_label.setText(f"00:00 / {_clock(result_summary(self.last_result or {})['length'])}")
        if self.player is not None:
            self.player.setSource(QUrl.fromLocalFile(str(path)))

    def _unload_player(self) -> None:
        self._source = None
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())  # release the file so it can be overwritten

    @pyqtSlot()
    def toggle_play(self) -> None:
        if self._source is None or not self._ensure_player():
            return
        if self.player.source().isEmpty():
            self.player.setSource(QUrl.fromLocalFile(str(self._source)))
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    @pyqtSlot(int)
    def _seek(self, ms: int) -> None:
        if self.player is not None:
            self.player.setPosition(ms)

    def _position(self, ms: int) -> None:
        if not self.seek.isSliderDown():
            self.seek.setValue(ms)
        total = self.player.duration() if self.player else 0
        self.time_label.setText(f"{_clock(ms / 1000)} / {_clock(total / 1000)}")
        self.cues.set_position(ms / 1000)

    def _playback_state(self, state) -> None:
        self.play_btn.setText("PAUSE" if state == QMediaPlayer.PlaybackState.PlayingState else "PLAY")

    # ------------------------------------------------------------------ output actions
    @pyqtSlot()
    def copy_seed(self) -> None:
        if self.last_result:
            QGuiApplication.clipboard().setText(str(self.last_result.get("seed", "")))
            self.log("Seed copied to clipboard")

    @pyqtSlot()
    def reuse_settings(self) -> None:
        if self.last_result:
            self.seed.setText(str(self.last_result.get("seed", "")))
            self.log("Seed loaded into parameters")

    @pyqtSlot()
    def open_folder(self) -> None:
        folder = Path(self.last_result["path"]).parent if self.last_result else Path(self.folder.text())
        if folder.is_dir():
            if sys.platform == "win32":
                os.startfile(str(folder))  # noqa: S606 - opening a folder the operator chose
            else:
                self.log(str(folder))

    # ------------------------------------------------------------------ shutdown
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._worker_refs and not self._closing:
            answer = QMessageBox.question(
                self, "Render in progress",
                "A render is still running. Quit anyway?\n\nThe service may finish it, but the file won't be "
                "downloaded here.")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._closing = True
            self.hide()
            self._shutdown_service()  # ends the blocking request when we own the server
            event.ignore()  # _worker_done closes again once the thread has stopped
            return
        self._unload_player()
        if not self._closing:
            self._shutdown_service()
        event.accept()

    def _shutdown_service(self) -> None:
        if self.client is not None and self.own_server:
            try:
                self.client.stop_server()
                self.log("Stopped the service this console started")
            except Exception:  # noqa: BLE001 - best effort on exit
                pass
            self.own_server = False


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    families = set(QFontDatabase.families())
    font = app.font()
    for name in theme.FONT_FAMILIES:
        if name in families:
            font.setFamily(name)
            break
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(theme.QSS)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("BGM Studio")
    apply_theme(app)
    win = MainWindow()
    win.show()
    return app.exec()
