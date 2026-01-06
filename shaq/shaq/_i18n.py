from __future__ import annotations

import locale
import os
from dataclasses import dataclass
from typing import Any

SUPPORTED_UI_LANGUAGES: tuple[str, ...] = ("pl", "en")
UI_LANGUAGE_CHOICES: tuple[tuple[str, str], ...] = (("pl", "Polski"), ("en", "English"))


def normalize_ui_language(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("_", "-")
    if not normalized:
        return None
    if normalized == "pl" or normalized.startswith("pl-"):
        return "pl"
    if normalized == "en" or normalized.startswith("en-"):
        return "en"
    return None


def infer_ui_language_from_system() -> str:
    locale_name = ""
    try:
        locale_name = locale.getlocale()[0] or ""
    except Exception:
        locale_name = ""

    if not locale_name:
        try:
            locale_name = locale.getdefaultlocale()[0] or ""
        except Exception:
            locale_name = ""

    if not locale_name:
        locale_name = (
            os.environ.get("LC_ALL", "")
            or os.environ.get("LC_MESSAGES", "")
            or os.environ.get("LANG", "")
        )

    normalized = locale_name.strip().lower().replace("_", "-")
    if normalized.startswith("pl"):
        return "pl"
    return "en"


def ui_language_from_config(value: Any) -> str:
    return normalize_ui_language(value) or infer_ui_language_from_system()


@dataclass(frozen=True, slots=True)
class I18n:
    lang: str
    strings: dict[str, dict[str, str]]

    def t(self, key: str, **kwargs: Any) -> str:
        template = (
            self.strings.get(key, {}).get(self.lang)
            or self.strings.get(key, {}).get("en")
            or key
        )
        if not kwargs:
            return template
        try:
            return template.format(**kwargs)
        except Exception:
            return template

