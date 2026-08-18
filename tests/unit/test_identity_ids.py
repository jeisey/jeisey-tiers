"""Identifier hygiene.

The whitespace case here is not hypothetical: Phase 0 observed Sleeper serving
``" 00-0035057"`` (`docs/DATA_SOURCES.md` 13.6).
"""

from __future__ import annotations

import pytest

from ffdraft.identity.ids import (
    IdNamespace,
    is_team_code,
    make_player_id,
    normalize_id,
    parse_player_id,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00-0035057", "00-0035057"),
        (" 00-0035057", "00-0035057"),
        ("00-0035057\n", "00-0035057"),
    ],
)
def test_gsis_ids_are_trimmed(raw, expected):
    result = normalize_id(IdNamespace.GSIS, raw)
    assert result.value == expected


def test_trimming_is_recorded_as_a_quality_flag():
    result = normalize_id(IdNamespace.GSIS, " 00-0035057")
    assert result.quality_flags == ("whitespace_trimmed_gsis_id",)


@pytest.mark.parametrize("raw", ["00-35057", "0035057", "abc", "00-00350578", "00-003505x"])
def test_malformed_gsis_ids_fail_closed(raw):
    result = normalize_id(IdNamespace.GSIS, raw)
    assert result.value is None
    assert result.malformed
    assert result.reason == "malformed_gsis_id"


def test_numeric_ids_canonicalise_across_source_representations():
    """An Int64 column and a zero-padded JSON string must compare equal."""
    from_frame = normalize_id(IdNamespace.ESPN, 4362628)
    from_json = normalize_id(IdNamespace.ESPN, "04362628")
    from_float = normalize_id(IdNamespace.ESPN, 4362628.0)
    assert from_frame.value == from_json.value == from_float.value == "4362628"


def test_only_string_inputs_can_report_whitespace():
    assert normalize_id(IdNamespace.ESPN, 4362628.0).quality_flags == ()
    assert normalize_id(IdNamespace.ESPN, " 4362628").quality_flags == (
        "whitespace_trimmed_espn_id",
    )


@pytest.mark.parametrize("raw", ["", "  ", None, "NA", "n/a", "null", "0", "None"])
def test_absent_sentinels_are_absent_not_malformed(raw):
    result = normalize_id(IdNamespace.ESPN, raw)
    assert result.absent
    assert not result.malformed
    assert result.quality_flags == ()


def test_booleans_are_rejected_rather_than_becoming_id_one():
    result = normalize_id(IdNamespace.ESPN, True)
    assert result.value is None
    assert result.malformed


def test_sleeper_accepts_numeric_players_and_team_codes():
    assert normalize_id(IdNamespace.SLEEPER, "6462").value == "6462"
    assert normalize_id(IdNamespace.SLEEPER, "buf").value == "BUF"
    assert normalize_id(IdNamespace.SLEEPER, "not a code!").value is None


def test_team_code_detection():
    assert is_team_code("BUF")
    assert is_team_code(" gb ")
    assert not is_team_code("6462")
    assert not is_team_code(None)


def test_player_ids_are_namespaced_and_round_trip():
    player_id = make_player_id(IdNamespace.GSIS, "00-0035057")
    assert player_id == "gsis:00-0035057"
    assert parse_player_id(player_id) == (IdNamespace.GSIS, "00-0035057")


def test_a_bare_id_is_not_a_canonical_key():
    with pytest.raises(ValueError, match="not a namespaced canonical player id"):
        parse_player_id("00-0035057")


def test_external_ids_containing_the_separator_are_refused():
    with pytest.raises(ValueError, match="must not contain"):
        make_player_id(IdNamespace.ESPN, "43:626")
