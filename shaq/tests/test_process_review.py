"""Regresje zgłoszone w recenzji: tłumaczenia, fokus i zgodność kopii modułów."""

from pathlib import Path
from string import Formatter
from types import SimpleNamespace

import pytest

from shaq import _process_audio, _process_picker
from shaq._i18n import I18n
from shaq._process_messages import _STRINGS


@pytest.mark.parametrize(
    "module", ["_process_audio", "_process_picker", "_win_process_audio", "_process_messages"]
)
def test_independent_packages_keep_identical_process_modules(module: str) -> None:
    """Wykrywa zmianę wprowadzoną tylko do jednej kopii modułu."""
    root = Path(__file__).resolve().parents[2]
    assert (root / "shaq/shaq" / f"{module}.py").read_bytes() == (
        root / "shaqcast/shaqcast" / f"{module}.py"
    ).read_bytes()


def test_process_translations_have_both_languages_and_matching_parameters() -> None:
    """Kontroluje kompletność obu wersji komunikatów."""
    for translations in _STRINGS.values():
        assert set(translations) == {"pl", "en"}
        fields = [
            {name for _, name, _, _ in Formatter().parse(text) if name}
            for text in translations.values()
        ]
        assert fields[0] == fields[1]


@pytest.mark.parametrize("language,fragment", [("pl", "Uruchom go"), ("en", "Launch it")])
def test_closed_program_message_uses_ui_language(language: str, fragment: str) -> None:
    target = _process_audio.ProcessTarget(r"C:\winamp.exe")
    assert fragment in _process_audio.process_unavailable_message(
        target, translate=I18n(language, _STRINGS).t
    )


def test_windows_error_translates_operation_and_preserves_error_code() -> None:
    error = _process_audio.ProcessAudioError(
        "process.windows_error", operation="process.operation.0", code=0x80004005
    )
    message = error.localized(I18n("en", _STRINGS).t)
    assert message == "Activate audio capture: Windows error 0x80004005."


@pytest.mark.parametrize(
    "focused,force,expected", [(True, False, 0), (False, False, 1), (True, True, 1)]
)
def test_refresh_preserves_focused_list_unless_explicitly_requested(
    monkeypatch: pytest.MonkeyPatch, focused: bool, force: bool, expected: int
) -> None:
    reads = []
    updates = []
    choice = SimpleNamespace(
        HasFocus=lambda: focused,
        SetItems=lambda values: updates.append(values),
        SetSelection=lambda value: None,
    )
    monkeypatch.setattr(_process_picker, "list_processes", lambda: reads.append(True) or [])
    picker = _process_picker.ProcessPicker(
        None, choice, None, changed=lambda: None, status=lambda _: None
    )
    picker.refresh(force=force)
    assert len(reads) == expected
    assert len(updates) == expected


def test_missing_selection_has_english_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_process_picker, "require_process_capture", lambda: None)
    picker = _process_picker.ProcessPicker(
        None,
        None,
        None,
        changed=lambda: None,
        status=lambda _: None,
        translate=I18n("en", _STRINGS).t,
    )
    with pytest.raises(ValueError, match="Select a program"):
        picker.selected()
