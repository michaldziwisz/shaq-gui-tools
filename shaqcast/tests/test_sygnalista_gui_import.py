from __future__ import annotations

import shaqcast.sygnalista_gui as sygnalista_gui


def test_sygnalista_gui_importable() -> None:
    assert isinstance(sygnalista_gui.sygnalista_base_url(), str)
