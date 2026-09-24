"""Unit tests for canonical serialization and hashing."""

from datetime import UTC, datetime
from enum import StrEnum

import pytest

from maf_lab.domain.canonical import canonical_json, sha256_hex


class _Colour(StrEnum):
    RED = "red"


def test_canonical_json_sorts_keys() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_canonical_json_omits_insignificant_whitespace() -> None:
    assert canonical_json({"a": [1, 2]}) == '{"a":[1,2]}'


def test_canonical_json_is_key_order_independent() -> None:
    assert sha256_hex({"a": 1, "b": 2}) == sha256_hex({"b": 2, "a": 1})


def test_canonical_json_is_idempotent() -> None:
    once = canonical_json({"b": 1, "a": {"d": 4, "c": 3}})
    assert canonical_json({"a": {"c": 3, "d": 4}, "b": 1}) == once


def test_canonical_json_encodes_datetimes_as_utc_rfc3339() -> None:
    moment = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
    assert canonical_json({"at": moment}) == '{"at":"2026-02-01T12:00:00Z"}'


def test_canonical_json_matches_pydantic_json_mode_for_utc_instants() -> None:
    moment = datetime.fromisoformat("2026-02-01T14:00:00+02:00")
    assert canonical_json({"at": moment}) == '{"at":"2026-02-01T12:00:00Z"}'


def test_canonical_json_encodes_enums_by_value() -> None:
    assert canonical_json({"colour": _Colour.RED}) == '{"colour":"red"}'


def test_canonical_json_rejects_floating_point() -> None:
    with pytest.raises(TypeError, match="floating point"):
        canonical_json({"amount": 20.5})


def test_canonical_json_rejects_nested_floating_point() -> None:
    with pytest.raises(TypeError, match="floating point"):
        canonical_json({"amounts": [1, {"nested": 2.0}]})


def test_canonical_json_rejects_floating_point_inside_a_set() -> None:
    """Sets are encoded by sorting into a list, so they need the same guard."""
    with pytest.raises(TypeError, match="floating point"):
        canonical_json({"amounts": {1.5}})
    with pytest.raises(TypeError, match="floating point"):
        canonical_json({"amounts": frozenset({1.5})})


def test_sha256_hex_is_stable_and_64_hex_characters() -> None:
    digest = sha256_hex({"a": 1})
    assert digest == sha256_hex({"a": 1})
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_sha256_hex_distinguishes_different_payloads() -> None:
    assert sha256_hex({"a": 1}) != sha256_hex({"a": 2})
