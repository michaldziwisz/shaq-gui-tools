from __future__ import annotations

from shaqcast._soundcard_compat import patch_soundcard_numpy_fromstring


def test_patch_soundcard_numpy_fromstring_noop_on_non_windows() -> None:
    patch_soundcard_numpy_fromstring()

