from __future__ import annotations

from shaqcast.shazam_regions import SUPPORTED_ENDPOINT_COUNTRIES, SUPPORTED_LANGUAGES, find_index_by_code


def test_find_index_by_code_handles_common_variants() -> None:
    idx = find_index_by_code(SUPPORTED_LANGUAGES, "pl_pl")
    assert idx is not None
    assert SUPPORTED_LANGUAGES[idx][0] == "pl-PL"

    idx2 = find_index_by_code(SUPPORTED_ENDPOINT_COUNTRIES, "pl")
    assert idx2 is not None
    assert SUPPORTED_ENDPOINT_COUNTRIES[idx2][0] == "PL"
