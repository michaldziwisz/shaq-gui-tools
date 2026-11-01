"""Pilnuje zgodności modułów oraz zachowania pełnej próbki do wyboru okna."""

from pathlib import Path

from shaq import _gui


def test_independent_packages_keep_identical_recognition_modules() -> None:
    """Porównuje klienta i jego tłumaczenia w obu pakietach."""
    root = Path(__file__).resolve().parents[2]
    assert (root / "shaq/shaq/_recognition.py").read_bytes() == (
        root / "shaqcast/shaqcast/_recognition.py"
    ).read_bytes()


def test_default_sample_keeps_room_for_ranking_windows() -> None:
    """Nowa konfiguracja nagrywa 15 s dla maksymalnie 12-sekundowej sygnatury."""
    defaults = _gui._default_advanced_settings()
    assert defaults.sample_seconds == 15
    assert defaults.segment_seconds == 12
