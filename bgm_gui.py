# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Leon Priest (GitHub: 7h3v01d)
"""BGM Studio desktop console (PyQt6, dark industrial).  Launch: run_gui.bat  or  python bgm_gui.py

Talks to the local REST service on 127.0.0.1:8765 through bgm_client (starting it if needed, and stopping it on exit
only if this console started it).  The code lives in the bgmgui package.
"""
from bgmgui.validation import FORMATS, MOODS, export_path, validate_track  # noqa: F401 - re-exported for tests

if __name__ == "__main__":
    import sys

    from bgmgui.window import main
    sys.exit(main())
