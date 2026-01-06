from __future__ import annotations

from collections.abc import Sequence

# Values observed from Shazam Web app locale redirect script (supported locales):
# https://www.shazam.com/  (inline <script id="locale-redirect">)
SUPPORTED_LANGUAGES: list[tuple[str, str]] = [
    ("cs-CZ", "Čeština"),
    ("de-DE", "Deutsch"),
    ("el-GR", "Ελληνικά"),
    ("en-US", "English (US)"),
    ("en-GB", "English (UK)"),
    ("es-ES", "Español (ES)"),
    ("es-MX", "Español (MX)"),
    ("fr-FR", "Français"),
    ("hi-IN", "हिन्दी"),
    ("id-ID", "Bahasa Indonesia"),
    ("it-IT", "Italiano"),
    ("ja-JP", "日本語"),
    ("ko-KR", "한국어"),
    ("nl-NL", "Nederlands"),
    ("pl-PL", "Polski"),
    ("pt-PT", "Português (Portugal)"),
    ("pt-BR", "Português (Brasil)"),
    ("ru-RU", "Русский"),
    ("tr-TR", "Türkçe"),
    ("zh-CN", "简体中文"),
    ("zh-TW", "繁體中文"),
]

# Values observed from Shazam locations endpoint:
# https://www.shazam.com/services/charts/locations  (data["countries"][*]["id"/"name"])
SUPPORTED_ENDPOINT_COUNTRIES: list[tuple[str, str]] = [
    ("DZ", "Algeria"),
    ("AR", "Argentina"),
    ("AU", "Australia"),
    ("AT", "Austria"),
    ("AZ", "Azerbaijan"),
    ("BY", "Belarus"),
    ("BE", "Belgium"),
    ("BR", "Brazil"),
    ("BG", "Bulgaria"),
    ("CM", "Cameroon"),
    ("CA", "Canada"),
    ("CL", "Chile"),
    ("CN", "China"),
    ("CO", "Colombia"),
    ("CR", "Costa Rica"),
    ("HR", "Croatia"),
    ("CZ", "Czechia"),
    ("DK", "Denmark"),
    ("EG", "Egypt"),
    ("FI", "Finland"),
    ("FR", "France"),
    ("DE", "Germany"),
    ("GH", "Ghana"),
    ("GR", "Greece"),
    ("HU", "Hungary"),
    ("IN", "India"),
    ("ID", "Indonesia"),
    ("IE", "Ireland"),
    ("IL", "Israel"),
    ("IT", "Italy"),
    ("CI", "Ivory Coast"),
    ("JP", "Japan"),
    ("KZ", "Kazakhstan"),
    ("KE", "Kenya"),
    ("MY", "Malaysia"),
    ("MX", "Mexico"),
    ("MA", "Morocco"),
    ("MZ", "Mozambique"),
    ("NL", "Netherlands"),
    ("NZ", "New Zealand"),
    ("NG", "Nigeria"),
    ("NO", "Norway"),
    ("PE", "Peru"),
    ("PH", "Philippines"),
    ("PL", "Poland"),
    ("PT", "Portugal"),
    ("RO", "Romania"),
    ("RU", "Russia"),
    ("SA", "Saudi Arabia"),
    ("SN", "Senegal"),
    ("SG", "Singapore"),
    ("ZA", "South Africa"),
    ("KR", "South Korea"),
    ("ES", "Spain"),
    ("SE", "Sweden"),
    ("CH", "Switzerland"),
    ("TZ", "Tanzania"),
    ("TH", "Thailand"),
    ("TN", "Tunisia"),
    ("TR", "Türkiye"),
    ("UG", "Uganda"),
    ("UA", "Ukraine"),
    ("AE", "United Arab Emirates"),
    ("GB", "United Kingdom"),
    ("US", "United States"),
    ("UY", "Uruguay"),
    ("UZ", "Uzbekistan"),
    ("VE", "Venezuela"),
    ("VN", "Vietnam"),
    ("ZM", "Zambia"),
]


def _norm(value: str) -> str:
    return value.strip().replace("_", "-").lower()


def language_choice_strings() -> list[str]:
    return [f"{code} — {name}" for code, name in SUPPORTED_LANGUAGES]


def country_choice_strings() -> list[str]:
    return [f"{code} — {name}" for code, name in SUPPORTED_ENDPOINT_COUNTRIES]


def language_codes() -> list[str]:
    return [code for code, _ in SUPPORTED_LANGUAGES]


def country_codes() -> list[str]:
    return [code for code, _ in SUPPORTED_ENDPOINT_COUNTRIES]


def find_index_by_code(options: Sequence[tuple[str, str]], code: str) -> int | None:
    target = _norm(code)
    for idx, (value, _label) in enumerate(options):
        if _norm(value) == target:
            return idx
    return None

