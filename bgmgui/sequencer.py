# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""SEQUENCE tab: a scene list (one mood per scene, cut on your timings), a scene bar preview, sequence settings,
and an optional narration to score (music fitted under it, ducked while speaking)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from . import theme
from .media import audio_seconds
from .scenes import (DEFAULT_SETTINGS, ENERGY, TRANSITIONS, dump_scene_file, fit_durations, load_scene_file,
                     narration_fit, new_row, starts)
from .widgets import field_label

COLS = ("#", "MOOD", "LENGTH", "INTENSITY", "INTO SCENE", "BPM", "START")
C_NUM, C_MOOD, C_LEN, C_INT, C_TR, C_BPM, C_START = range(len(COLS))
TR_SHORT = {"none": "", "riser": "R", "impact": "I", "riser_impact": "RI", "downlifter": "D", "swell": "S",
            "auto": "A"}


def _clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 3600:d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}" if seconds >= 3600 \
        else f"{seconds // 60:02d}:{seconds % 60:02d}"


def energy_colour(mood: str) -> QColor:
    return QColor(theme.ENERGY_COLOURS[min(4, max(0, ENERGY.get(mood, 2)))])


class SceneBar(QWidget):
    """Planning preview: scenes as blocks proportional to length (shade = mood energy), the transition into each
    cut, the selected scene outlined, and where the narration ends if one is loaded.  Click a block to select it."""
    sceneClicked = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rows: list = []
        self._default_tr = "auto"
        self._narration: float | None = None
        self._selected = -1

    def set_state(self, rows: list, default_tr: str, narration: float | None, selected: int) -> None:
        self._rows, self._default_tr, self._narration, self._selected = rows, default_tr, narration, selected
        self.update()

    def _span(self) -> float:
        total = sum(float(r["duration"]) for r in self._rows)
        return max(total, self._narration or 0.0) or 1.0

    def _geometry(self):
        r = QRectF(self.rect()).adjusted(0, 0, -1, -1)
        return r, r.adjusted(1, 1, -1, -12)

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802 - Qt override
        _, inner = self._geometry()
        t = (e.position().x() - inner.left()) / max(1.0, inner.width()) * self._span()
        for i, s in enumerate(starts([r["duration"] for r in self._rows])):
            if s <= t < s + float(self._rows[i]["duration"]):
                self.sceneClicked.emit(i)
                return

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        r, inner = self._geometry()
        p.fillRect(r, QColor(theme.OBSIDIAN))
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.drawRect(r)
        span = self._span()

        def x(t: float) -> float:
            return inner.left() + inner.width() * t / span

        f = QFont(self.font())
        f.setPointSize(7)
        p.setFont(f)
        st = starts([row["duration"] for row in self._rows])
        for i, (row, s) in enumerate(zip(self._rows, st)):
            block = QRectF(x(s), inner.top(), max(1.0, x(s + float(row["duration"])) - x(s) - 1), inner.height())
            p.fillRect(block, energy_colour(row["mood"]))
            if block.width() > 30:
                p.setPen(QColor(theme.OBSIDIAN) if ENERGY.get(row["mood"], 2) >= 3 else QColor(theme.TEXT))
                p.drawText(block.adjusted(4, 0, -2, 0), Qt.AlignmentFlag.AlignVCenter,
                           f"{i + 1} {row['mood'].upper()}")
            if i > 0:
                tr = row["transition"] if row["transition"] != "default" else self._default_tr
                if tr != "none":
                    p.setPen(QPen(QColor(theme.AMBER), 2))
                    p.drawLine(int(block.left()), int(inner.top()), int(block.left()), int(inner.bottom()))
                    p.drawText(QRectF(block.left() + 2, inner.bottom() + 1, 30, 10),
                               Qt.AlignmentFlag.AlignLeft, TR_SHORT[tr])
        if 0 <= self._selected < len(self._rows):
            s = st[self._selected]
            p.setPen(QPen(QColor(theme.TEXT), 1))
            p.drawRect(QRectF(x(s), inner.top(), x(s + float(self._rows[self._selected]["duration"])) - x(s) - 1,
                              inner.height() - 1))
        if self._narration:
            xx = x(self._narration)
            p.setPen(QPen(QColor(theme.TEXT), 1, Qt.PenStyle.DashLine))
            p.drawLine(int(xx), int(r.top()), int(xx), int(r.bottom()))
            p.drawText(QRectF(xx - 64, inner.bottom() + 1, 62, 10), Qt.AlignmentFlag.AlignRight, "VOICE END")
        p.end()


class SequencerTab(QWidget):
    """Edits a scene list.  rows() / settings() / narration() give the window what it needs to render."""
    changed = pyqtSignal()
    message = pyqtSignal(str, str)  # text, level -> the window's log

    def __init__(self, moods: list, parent: QWidget | None = None):
        super().__init__(parent)
        self._moods = list(moods)
        self._narration_path: str | None = None
        self._narration_s: float | None = None
        self._loading = False
        self._build()
        self.set_rows([new_row("ambient", 30.0), new_row("cinematic", 30.0)])

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.add_btn = self._tool("+ SCENE", self.add_scene, "Add a scene after the selected one")
        self.dup_btn = self._tool("DUPLICATE", self.duplicate_scene, "Copy the selected scene")
        self.del_btn = self._tool("REMOVE", self.remove_scene, "Remove the selected scene")
        self.up_btn = self._tool("▲", lambda: self.move_scene(-1), "Move the selected scene earlier")
        self.down_btn = self._tool("▼", lambda: self.move_scene(1), "Move the selected scene later")
        for b in (self.add_btn, self.dup_btn, self.del_btn, self.up_btn, self.down_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        self.load_btn = self._tool("LOAD", self.load_file, "Open a scene file (.json), e.g. one InkHeart wrote")
        self.save_btn = self._tool("SAVE", self.save_file, "Save these scenes and settings as a .json scene file")
        bar.addWidget(self.load_btn)
        bar.addWidget(self.save_btn)
        v.addLayout(bar)

        self.table = QTableWidget(0, len(COLS))
        self.table.setObjectName("scenes")
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(30 * 5 + 28)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        for c, w in ((C_NUM, 26), (C_LEN, 76), (C_INT, 84), (C_BPM, 50), (C_START, 54)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(c, w)
        for c in (C_MOOD, C_TR):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._refresh_bar)
        v.addWidget(self.table, 1)

        self.scene_bar = SceneBar()
        self.scene_bar.sceneClicked.connect(self.table.selectRow)
        v.addWidget(self.scene_bar)
        self.total_label = QLabel()
        self.total_label.setObjectName("hint")
        v.addWidget(self.total_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(3)
        self.default_tr = QComboBox()
        self.default_tr.addItems(TRANSITIONS)
        self.default_tr.setToolTip("Effect at every cut unless a scene sets its own. auto picks by the change in "
                                   "energy: rises get a riser/impact, drops a downlifter.")
        self.xfade = self._spin(0, 10, 1, " s", "Crossfade after each cut")
        self.max_jump = self._spin(0, 40, 0, " bpm", "Tempo matching keeps neighbouring scenes within this")
        self.tempo_match = QPushButton("TEMPO MATCH")
        self.tempo_match.setObjectName("toggle")
        self.tempo_match.setCheckable(True)
        self.tempo_match.setToolTip("Choose tempos so neighbouring scenes don't lurch (2:1 counts as matched)")
        for col, (label, w) in enumerate((("Default transition", self.default_tr), ("Crossfade", self.xfade),
                                          ("Max BPM jump", self.max_jump), ("", self.tempo_match))):
            grid.addWidget(field_label(label), 0, col)
            grid.addWidget(w, 1, col)
        grid.setColumnStretch(0, 2)
        v.addLayout(grid)

        v.addWidget(field_label("Narration (optional: score a voice-over)"))
        nrow = QHBoxLayout()
        self.narration_edit = QLineEdit()
        self.narration_edit.setReadOnly(True)
        self.narration_edit.setPlaceholderText("none: render music only")
        self.narr_btn = self._tool("BROWSE", self.browse_narration, "Choose a voice-over to score")
        self.narr_clear = self._tool("CLEAR", self.clear_narration, "Render music only")
        self.fit_btn = self._tool("FIT", self.fit_to_narration,
                                  "Scale every scene so they add up to the narration's length")
        nrow.addWidget(self.narration_edit, 1)
        for b in (self.narr_btn, self.narr_clear, self.fit_btn):
            nrow.addWidget(b)
        v.addLayout(nrow)
        mix = QGridLayout()
        mix.setHorizontalSpacing(10)
        mix.setVerticalSpacing(3)
        self.lead_in = self._spin(0, 30, 1, " s", "Music before the first word")
        self.tail_out = self._spin(0, 60, 1, " s", "Music after the last word")
        self.duck_db = self._spin(0, 40, 0, " dB", "How far the music dips under speech")
        self.fit_label = QLabel()
        self.fit_label.setObjectName("hint")
        self.fit_label.setWordWrap(True)
        for col, (label, w) in enumerate((("Lead-in", self.lead_in), ("Tail-out", self.tail_out),
                                          ("Duck", self.duck_db))):
            mix.addWidget(field_label(label), 0, col)
            mix.addWidget(w, 1, col)
        mix.addWidget(self.fit_label, 1, 3)
        mix.setColumnStretch(3, 1)
        v.addLayout(mix)

        for w in (self.default_tr,):
            w.currentTextChanged.connect(self._emit_changed)
        for w in (self.xfade, self.max_jump, self.lead_in, self.tail_out, self.duck_db):
            w.valueChanged.connect(self._emit_changed)
        self.tempo_match.toggled.connect(self._emit_changed)
        self.set_settings(DEFAULT_SETTINGS)
        self._narration_widgets_enabled()

    def _tool(self, text: str, slot, tip: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("tool")
        b.setToolTip(tip)
        b.clicked.connect(slot)
        return b

    @staticmethod
    def _spin(lo: float, hi: float, decimals: int, suffix: str, tip: str) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(decimals)
        s.setSuffix(suffix)
        s.setToolTip(tip)
        return s

    # ------------------------------------------------------------------ rows <-> widgets
    def set_moods(self, moods: list) -> None:
        rows = self.rows()
        self._moods = list(moods)
        for r in rows:
            if r["mood"] not in self._moods:
                r["mood"] = self._moods[0]
        self.set_rows(rows, self.selected())

    def _row_widgets(self, i: int, row: dict) -> None:
        num = QTableWidgetItem(str(i + 1))
        num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        num.setForeground(QColor(theme.MUTED))
        self.table.setItem(i, C_NUM, num)
        mood = QComboBox()
        mood.addItems(self._moods)
        mood.setCurrentText(row["mood"])
        mood.currentTextChanged.connect(self._emit_changed)
        self.table.setCellWidget(i, C_MOOD, mood)
        length = self._spin(4, 7200, 2, " s", "Scene length")
        length.setValue(float(row["duration"]))
        length.valueChanged.connect(self._emit_changed)
        self.table.setCellWidget(i, C_LEN, length)
        inten = self._spin(-0.05, 1.0, 2, "", "0.50 = the mood as designed; — = not set")
        inten.setSingleStep(0.05)
        inten.setSpecialValueText("—")
        inten.setValue(-0.05 if row["intensity"] is None else float(row["intensity"]))
        inten.valueChanged.connect(self._emit_changed)
        self.table.setCellWidget(i, C_INT, inten)
        tr = QComboBox()
        if i == 0:
            tr.addItem("—")
            tr.setEnabled(False)
            tr.setToolTip("The first scene has no cut into it")
        else:
            tr.addItems(("default",) + TRANSITIONS)
            tr.setCurrentText(row["transition"])
            tr.setToolTip("Effect at the cut into this scene (default = the sequence's default transition)")
        tr.currentTextChanged.connect(self._emit_changed)
        self.table.setCellWidget(i, C_TR, tr)
        bpm = self._spin(39, 200, 0, "", "Fixed tempo for this scene; auto = chosen for the mood and neighbours")
        bpm.setSpecialValueText("auto")
        bpm.setValue(39 if row["bpm"] is None else float(row["bpm"]))
        bpm.valueChanged.connect(self._emit_changed)
        self.table.setCellWidget(i, C_BPM, bpm)
        start = QTableWidgetItem()
        start.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        start.setForeground(QColor(theme.PHOSPHOR))
        self.table.setItem(i, C_START, start)

    def set_rows(self, rows: list, select: int = 0) -> None:
        self._loading = True
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self._row_widgets(i, row)
        self._loading = False
        if rows:
            self.table.selectRow(max(0, min(select, len(rows) - 1)))
        self._emit_changed()

    def rows(self) -> list:
        out = []
        for i in range(self.table.rowCount()):
            inten = self.table.cellWidget(i, C_INT).value()
            bpm = self.table.cellWidget(i, C_BPM).value()
            tr = self.table.cellWidget(i, C_TR).currentText()
            out.append({"mood": self.table.cellWidget(i, C_MOOD).currentText(),
                        "duration": self.table.cellWidget(i, C_LEN).value(),
                        "intensity": None if inten < 0 else round(inten, 2),
                        "transition": "default" if i == 0 or tr == "—" else tr,
                        "bpm": None if bpm < 40 else bpm})
        return out

    def selected(self) -> int:
        sel = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return sel[0].row() if sel else -1

    def settings(self) -> dict:
        return {"transitions": self.default_tr.currentText(), "xfade": self.xfade.value(),
                "tempo_match": self.tempo_match.isChecked(), "max_bpm_jump": self.max_jump.value(),
                "lead_in": self.lead_in.value(), "tail_out": self.tail_out.value(), "duck_db": self.duck_db.value()}

    def set_settings(self, s: dict) -> None:
        self.default_tr.setCurrentText(s["transitions"])
        self.xfade.setValue(s["xfade"])
        self.tempo_match.setChecked(s["tempo_match"])
        self.max_jump.setValue(s["max_bpm_jump"])
        self.lead_in.setValue(s["lead_in"])
        self.tail_out.setValue(s["tail_out"])
        self.duck_db.setValue(s["duck_db"])

    def narration(self) -> tuple[str | None, float | None]:
        return self._narration_path, self._narration_s

    # ------------------------------------------------------------------ refresh
    @pyqtSlot()
    def _emit_changed(self, *_args) -> None:
        if self._loading:
            return
        self._refresh_starts()
        self._refresh_bar()
        self.changed.emit()

    def _refresh_starts(self) -> None:
        rows = self.rows()
        for i, s in enumerate(starts([r["duration"] for r in rows])):
            item = self.table.item(i, C_START)
            if item is not None:
                item.setText(_clock(s))
        total = sum(r["duration"] for r in rows)
        ok, msg = narration_fit(total, self._narration_s)
        self.total_label.setText(f"{len(rows)} scene{'s' if len(rows) != 1 else ''}  ·  total {_clock(total)}"
                                 + (f"  ·  narration {_clock(self._narration_s)}" if self._narration_s else ""))
        self.fit_label.setText(msg)
        self.fit_label.setStyleSheet(f"color: {theme.PHOSPHOR if ok else theme.AMBER};")

    @pyqtSlot()
    def _refresh_bar(self) -> None:
        if self._loading:  # selection changes fire while rows are being rebuilt
            return
        self.scene_bar.set_state(self.rows(), self.default_tr.currentText(), self._narration_s, self.selected())

    def _narration_widgets_enabled(self) -> None:
        on = self._narration_path is not None
        for w in (self.narr_clear, self.fit_btn, self.lead_in, self.tail_out, self.duck_db):
            w.setEnabled(on)

    # ------------------------------------------------------------------ toolbar
    @pyqtSlot()
    def add_scene(self) -> None:
        rows, i = self.rows(), self.selected()
        mood = rows[i]["mood"] if 0 <= i < len(rows) else (self._moods[0] if self._moods else "ambient")
        rows.insert(i + 1 if i >= 0 else len(rows), new_row(mood, 30.0))
        self.set_rows(rows, i + 1 if i >= 0 else len(rows) - 1)

    @pyqtSlot()
    def duplicate_scene(self) -> None:
        rows, i = self.rows(), self.selected()
        if 0 <= i < len(rows):
            rows.insert(i + 1, dict(rows[i]))
            self.set_rows(rows, i + 1)

    @pyqtSlot()
    def remove_scene(self) -> None:
        rows, i = self.rows(), self.selected()
        if 0 <= i < len(rows) and len(rows) > 1:
            del rows[i]
            self.set_rows(rows, min(i, len(rows) - 1))

    def move_scene(self, step: int) -> None:
        rows, i = self.rows(), self.selected()
        j = i + step
        if 0 <= i < len(rows) and 0 <= j < len(rows):
            rows[i], rows[j] = rows[j], rows[i]  # rows() already reports the first scene as "default"
            self.set_rows(rows, j)

    @pyqtSlot()
    def load_file(self, path: str | None = None) -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open scene file", "", "Scene files (*.json)")
        if not path:
            return
        try:
            rows, settings = load_scene_file(Path(path).read_text(encoding="utf-8"), self._moods)
        except (OSError, ValueError) as e:
            self.message.emit(f"Scene file: {e}", "error")
            return
        self.set_settings(settings)
        self.set_rows(rows)
        self.message.emit(f"Loaded {len(rows)} scenes from {Path(path).name}", "ok")

    @pyqtSlot()
    def save_file(self, path: str | None = None) -> None:
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save scene file", "scenes.json", "Scene files (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(dump_scene_file(self.rows(), self.settings()), encoding="utf-8")
        except OSError as e:
            self.message.emit(f"Could not save: {e}", "error")
            return
        self.message.emit(f"Saved {self.table.rowCount()} scenes to {Path(path).name}", "ok")

    @pyqtSlot()
    def browse_narration(self, path: str | None = None) -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Narration", "",
                                                  "Audio (*.wav *.flac *.mp3 *.m4a *.ogg *.aac);;All files (*)")
        if not path:
            return
        try:
            seconds = audio_seconds(path)
        except ValueError as e:
            self.message.emit(f"Narration: {e}", "error")
            return
        self._narration_path, self._narration_s = path, seconds
        self.narration_edit.setText(path)
        self._narration_widgets_enabled()
        self._emit_changed()
        self.message.emit(f"Narration {Path(path).name} · {_clock(seconds)}", "info")

    @pyqtSlot()
    def clear_narration(self) -> None:
        self._narration_path = self._narration_s = None
        self.narration_edit.clear()
        self._narration_widgets_enabled()
        self._emit_changed()

    @pyqtSlot()
    def fit_to_narration(self) -> None:
        if not self._narration_s:
            return
        rows = self.rows()
        try:
            fitted = fit_durations([r["duration"] for r in rows], self._narration_s)
        except ValueError as e:
            self.message.emit(str(e), "warn")
            return
        for r, d in zip(rows, fitted):
            r["duration"] = d
        self.set_rows(rows, self.selected())
        self.message.emit(f"Fitted {len(rows)} scenes to the narration ({_clock(self._narration_s)})", "ok")
