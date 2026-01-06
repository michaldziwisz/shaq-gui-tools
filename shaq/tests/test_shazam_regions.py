from __future__ import annotations

from shaq._shazam_regions import (
    SUPPORTED_ENDPOINT_COUNTRIES,
    SUPPORTED_LANGUAGES,
    country_choice_strings,
    country_codes,
    find_index_by_code,
    language_choice_strings,
    language_codes,
)


def test_language_and_country_lists_are_consistent() -> None:
    assert len(language_codes()) == len(SUPPORTED_LANGUAGES)
    assert len(country_codes()) == len(SUPPORTED_ENDPOINT_COUNTRIES)
    assert len(language_choice_strings()) == len(SUPPORTED_LANGUAGES)
    assert len(country_choice_strings()) == len(SUPPORTED_ENDPOINT_COUNTRIES)


def test_find_index_by_code_is_case_and_separator_insensitive() -> None:
    idx = find_index_by_code(SUPPORTED_LANGUAGES, "PL_pl")
    assert idx is not None
    assert SUPPORTED_LANGUAGES[idx][0] == "pl-PL"

    idx2 = find_index_by_code(SUPPORTED_ENDPOINT_COUNTRIES, "pl")
    assert idx2 is not None
    assert SUPPORTED_ENDPOINT_COUNTRIES[idx2][0] == "PL"
