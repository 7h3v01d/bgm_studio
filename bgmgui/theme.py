# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""Dark industrial theme: the shared design system (palette, JetBrains Mono, flat zero-radius controls)."""
from __future__ import annotations

OBSIDIAN = "#0b0f14"   # window
PANEL = "#11161d"      # panels, inputs
BORDER = "#1e2831"     # rules, outlines
TEAL = "#2fd6c3"       # primary accent, actions
PHOSPHOR = "#4be08a"   # healthy state, live values
AMBER = "#ffb454"      # busy / attention
RED = "#ff6b6b"        # errors
TEXT = "#c8d3da"       # body text
MUTED = "#6c7b86"      # labels (TEXT dimmed; derived, not a palette colour)
RAISED = "#161d26"     # hover / pressed surface (PANEL lifted; derived)

FONT_FAMILIES = ["JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono", "monospace"]

# Section colours for the cue strip: calm kinds dim, energetic kinds bright.
SECTION_COLOURS = {"intro": "#1d5f58", "outro": "#1d5f58", "break": "#24474f", "verse": "#24857a",
                   "build": "#a87a3c", "peak": TEAL}

# Mood energy 0..4 for the scene bar: same ramp as the sections (dim teal -> amber -> teal).
ENERGY_COLOURS = ("#173f3b", "#1d5f58", "#24857a", "#a87a3c", TEAL)

QSS = f"""
* {{ font-family: "JetBrains Mono", "Cascadia Mono", Consolas, monospace; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QWidget#root {{ background: {OBSIDIAN}; }}
QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}

QFrame#panel {{ background: {PANEL}; border: 1px solid {BORDER}; }}
QLabel#panelTitle {{ color: {TEAL}; font-weight: 700; letter-spacing: 1px; padding: 0 0 2px 0; }}
QFrame#panelRule {{ background: {BORDER}; max-height: 1px; min-height: 1px; }}
QLabel#fieldLabel {{ color: {MUTED}; font-size: 8pt; letter-spacing: 1px; }}
QLabel#hint {{ color: {MUTED}; font-size: 9pt; }}
QLabel#brand {{ color: {TEXT}; font-size: 18pt; font-weight: 800; letter-spacing: 2px; }}
QLabel#brandAccent {{ color: {TEAL}; font-size: 18pt; font-weight: 800; }}
QLabel#subtitle {{ color: {MUTED}; font-size: 8pt; letter-spacing: 2px; }}
QFrame#accentRule {{ background: {TEAL}; max-height: 2px; min-height: 2px; }}
QLabel#value {{ color: {PHOSPHOR}; font-weight: 700; }}
QLabel#bigValue {{ color: {PHOSPHOR}; font-size: 14pt; font-weight: 700; }}
QLabel#fileName {{ color: {TEXT}; font-weight: 700; }}
QLabel#statusText {{ font-size: 12pt; font-weight: 700; letter-spacing: 1px; }}

QLineEdit, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {OBSIDIAN}; border: 1px solid {BORDER}; border-radius: 0; padding: 6px 8px;
    selection-background-color: {TEAL}; selection-color: {OBSIDIAN};
}}
QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {TEAL}; }}
QDoubleSpinBox {{ padding-left: 10px; }}
QLineEdit:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {MUTED}; }}
QLineEdit[invalid="true"] {{ border: 1px solid {RED}; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent; border-right: 4px solid transparent;
                         border-top: 5px solid {TEAL}; width: 0; height: 0; margin-right: 8px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {BORDER}; outline: 0;
                              selection-background-color: {RAISED}; selection-color: {TEAL}; }}
QPlainTextEdit#log {{ color: {MUTED}; font-size: 9pt; padding: 6px; }}

QPushButton {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 0; padding: 7px 14px;
              font-weight: 700; letter-spacing: 1px; }}
QPushButton:hover {{ background: {RAISED}; border-color: {TEAL}; color: {TEAL}; }}
QPushButton:pressed {{ background: {OBSIDIAN}; }}
QPushButton:disabled {{ color: {BORDER}; border-color: {BORDER}; background: {PANEL}; }}
QPushButton#primary {{ background: {TEAL}; color: {OBSIDIAN}; border: 1px solid {TEAL}; padding: 11px; font-size: 11pt; }}
QPushButton#primary:hover {{ background: {OBSIDIAN}; color: {TEAL}; }}
QPushButton#primary:disabled {{ background: {BORDER}; color: {MUTED}; border-color: {BORDER}; }}
QPushButton#tool {{ padding: 4px 9px; font-size: 8pt; }}
QPushButton#toggle {{ color: {MUTED}; }}
QPushButton#toggle:checked {{ color: {OBSIDIAN}; background: {PHOSPHOR}; border-color: {PHOSPHOR}; }}

QSlider {{ min-height: 18px; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border: none; margin: 0; }}
QSlider::sub-page:horizontal {{ height: 4px; background: {TEAL}; border: none; }}
QSlider::add-page:horizontal {{ height: 4px; background: {BORDER}; border: none; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 8px; height: 16px; margin: -6px 0; border: none; border-radius: 0; }}
QSlider::handle:horizontal:hover {{ background: {TEAL}; }}
QSlider::sub-page:horizontal:disabled {{ background: {MUTED}; }}

QProgressBar {{ background: {OBSIDIAN}; border: 1px solid {BORDER}; border-radius: 0; height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {AMBER}; }}

QTabWidget::pane {{ border: none; border-top: 1px solid {BORDER}; top: -1px; }}
QTabBar::tab {{ background: {PANEL}; color: {MUTED}; border: 1px solid {BORDER}; border-bottom: none;
               padding: 6px 18px; margin-right: 2px; font-weight: 700; letter-spacing: 1px; border-radius: 0; }}
QTabBar::tab:selected {{ background: {OBSIDIAN}; color: {TEAL}; border-top: 2px solid {TEAL}; }}
QTabBar::tab:hover:!selected {{ color: {TEXT}; }}

QTableWidget#scenes {{ background: {OBSIDIAN}; border: 1px solid {BORDER}; gridline-color: {BORDER};
                      selection-background-color: {RAISED}; outline: 0; }}
QTableWidget#scenes::item {{ border-bottom: 1px solid {BORDER}; padding: 0 4px; }}
QTableWidget#scenes::item:selected {{ background: {RAISED}; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
                       padding: 4px 6px; font-size: 8pt; letter-spacing: 1px; }}
QTableWidget#scenes QComboBox, QTableWidget#scenes QDoubleSpinBox {{ border: none; background: transparent;
                                                                    padding: 2px 6px; }}
QTableWidget#scenes QComboBox::drop-down {{ width: 12px; }}
QTableWidget#scenes QComboBox::down-arrow {{ margin-right: 2px; }}
QTableWidget#scenes QComboBox:focus, QTableWidget#scenes QDoubleSpinBox:focus {{ border: 1px solid {TEAL}; }}

QScrollBar:vertical {{ background: {OBSIDIAN}; width: 8px; border: none; }}
QScrollBar::handle:vertical {{ background: {BORDER}; min-height: 20px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QStatusBar {{ background: {OBSIDIAN}; color: {MUTED}; border-top: 1px solid {BORDER}; font-size: 8pt; }}
QMessageBox, QFileDialog {{ background: {PANEL}; }}
"""
