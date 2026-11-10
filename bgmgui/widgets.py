# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""Worker plumbing and the console's custom widgets."""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QObject, QRectF, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from . import theme


class Worker(QObject):
    """Runs one blocking call on a QThread; reports back through signals (queued to the GUI thread)."""
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn: Callable[[], object]):
        super().__init__()
        self._fn = fn

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as e:  # noqa: BLE001 - every failure is reported to the operator
            self.failed.emit(str(e) or type(e).__name__)
        else:
            self.finished.emit(result)


class Panel(QFrame):
    """Bordered machine panel with a numbered title: "01 // PARAMETERS"."""

    def __init__(self, number: str, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 10, 16, 12)
        outer.setSpacing(7)
        head = QLabel(f"{number} // {title}")
        head.setObjectName("panelTitle")
        rule = QFrame()
        rule.setObjectName("panelRule")
        outer.addWidget(head)
        outer.addWidget(rule)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body)


def field_label(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("fieldLabel")
    return label


class Led(QWidget):
    """Square status lamp."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._colour = QColor(theme.MUTED)

    def set_colour(self, colour: str) -> None:
        self._colour = QColor(colour)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        glow = QColor(self._colour)
        glow.setAlpha(70)
        p.fillRect(self.rect(), glow)
        p.fillRect(self.rect().adjusted(2, 2, -2, -2), self._colour)
        p.end()


class CueStrip(QWidget):
    """The rendered file's structure from its cue sheet: sections as blocks (brighter = more energy), every bar
    as a tick, transitions as amber marks, scene boundaries and numbers for sequences, the narration's span for
    mixes, and the playback position as a teal cursor."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(64)
        self._cues: dict | None = None
        self._position = None  # seconds

    def set_cues(self, cues: dict | None) -> None:
        self._cues = cues
        self._position = None
        self.setToolTip(self._summary())
        self.update()

    def set_position(self, seconds: float | None) -> None:
        self._position = seconds
        self.update()

    def _summary(self) -> str:
        if not self._cues:
            return ""
        lines = [f"{s['kind']:<6} {s['start']:7.1f}s - {s['end']:7.1f}s  {s['bars']} bars"
                 + (f"  intensity {s['intensity']:.2f}" if "intensity" in s else "")
                 for s in self._cues.get("sections", [])]
        return "\n".join(lines)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(0, 0, -1, -1)
        p.fillRect(r, QColor(theme.OBSIDIAN))
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.drawRect(r)
        dur = float((self._cues or {}).get("duration") or 0)
        if dur <= 0:
            p.setPen(QColor(theme.MUTED))
            f = QFont(self.font())
            f.setPointSize(8)
            p.setFont(f)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "NO CUE DATA")
            p.end()
            return
        scenes = self._cues.get("scenes") or []
        multi = len(scenes) > 1
        narration = self._cues.get("narration")
        top = 26 if multi else 14
        inner = r.adjusted(1, top, -1, -6 if narration else -1)

        def x(t: float) -> float:
            return inner.left() + inner.width() * max(0.0, min(1.0, t / dur))

        f = QFont(self.font())
        f.setPointSize(7)
        p.setFont(f)
        for s in self._cues.get("sections", []):
            colour = QColor(theme.SECTION_COLOURS.get(s["kind"], theme.BORDER))
            block = QRectF(x(s["start"]), inner.top(), max(1.0, x(s["end"]) - x(s["start"]) - 1), inner.height())
            p.fillRect(block, colour)
            if block.width() > 34:
                p.setPen(QColor(theme.OBSIDIAN) if s["kind"] in ("peak", "build") else QColor(theme.TEXT))
                p.drawText(block.adjusted(4, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, s["kind"].upper())
        tick_top = r.top() + (16 if multi else 4)
        p.setPen(QPen(QColor(theme.MUTED), 1))
        for t in self._cues.get("downbeats", []):
            xx = x(t)
            p.drawLine(int(xx), int(tick_top), int(xx), int(tick_top + 7))
        if multi:
            for sc in scenes:
                x0, x1 = x(sc["start"]), x(sc["end"])
                p.setPen(QPen(QColor(theme.TEXT), 1))
                p.drawLine(int(x0), int(r.top() + 1), int(x0), int(r.bottom()))
                p.setPen(QColor(theme.TEXT))
                label = f"{sc['scene']} {str(sc.get('mood', '')).upper()}"
                p.drawText(QRectF(x0 + 3, r.top() + 2, max(0.0, x1 - x0 - 4), 12),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           p.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, int(max(0, x1 - x0 - 4))))
        if narration:
            p.fillRect(QRectF(x(narration["start"]), r.bottom() - 4, x(narration["end"]) - x(narration["start"]), 3),
                       QColor(theme.TEXT))
        p.setPen(QPen(QColor(theme.AMBER), 2))
        for tr in self._cues.get("transitions", []):
            xx = x(tr["time"])
            p.drawLine(int(xx), int(r.top() + 1), int(xx), int(r.bottom()))
        if self._position is not None:
            p.setPen(QPen(QColor(theme.TEAL), 2))
            xx = x(self._position)
            p.drawLine(int(xx), int(r.top()), int(xx), int(r.bottom()))
        p.end()
