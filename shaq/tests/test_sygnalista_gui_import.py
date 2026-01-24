from __future__ import annotations

import shaq._sygnalista_gui as sygnalista_gui


def test_sygnalista_gui_importable() -> None:
    assert isinstance(sygnalista_gui.sygnalista_base_url(), str)
