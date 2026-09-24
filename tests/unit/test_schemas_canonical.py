"""Unit tests for the artifact canonicalizer.

`maf_lab.domain.canonical` refuses floating point outright (ADR 0002): the
domain never produces one, so a float reaching a state hash is a bug to catch,
not a value to encode. Manifests and normalized records are different: they
legitimately carry `max_cost_usd`, `temperature`, `score`, `ci_low`, `ci_high`.
This canonicalizer covers those artifacts. See
docs/design/canonicalization-and-hashing.md for the full design rationale.
"""

import math
from datetime import UTC, datetime
from enum import StrEnum

import pytest

from maf_lab.domain.canonical import canonical_json as domain_canonical_json
from maf_lab.schemas.canonical import artifact_canonical_json, artifact_sha256_hex


class _Colour(StrEnum):
    RED = "red"


def test_sorts_keys() -> None:
    assert artifact_canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_omits_insignificant_whitespace() -> None:
    assert artifact_canonical_json({"a": [1, 2]}) == '{"a":[1,2]}'


def test_encodes_datetimes_as_utc_rfc3339() -> None:
    moment = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
    assert artifact_canonical_json({"at": moment}) == '{"at":"2026-02-01T12:00:00Z"}'


def test_encodes_enums_by_value() -> None:
    assert artifact_canonical_json({"colour": _Colour.RED}) == '{"colour":"red"}'


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.2, "0.2"),
        (0.1, "0.1"),
        (0.0042, "0.0042"),
        (1.0, "1.0"),
        (0.25, "0.25"),
        (-0.0, "0.0"),
        (100.0, "100.0"),
    ],
)
def test_encodes_floats_via_repr(value: float, expected: str) -> None:
    """`repr(float)` is the shortest round-tripping decimal on every CPython >= 3.1."""
    assert artifact_canonical_json({"v": value}) == f'{{"v":{expected}}}'


def test_rejects_nan() -> None:
    with pytest.raises(TypeError, match="finite"):
        artifact_canonical_json({"v": math.nan})


def test_rejects_infinity() -> None:
    with pytest.raises(TypeError, match="finite"):
        artifact_canonical_json({"v": math.inf})
    with pytest.raises(TypeError, match="finite"):
        artifact_canonical_json({"v": -math.inf})


def test_is_idempotent_for_manifest_shaped_floats() -> None:
    payload = {"limits": {"max_cost_usd": 0.25}, "agent": {"parameters": {"temperature": 0.2}}}
    once = artifact_canonical_json(payload)
    twice = artifact_canonical_json(
        {"agent": {"parameters": {"temperature": 0.2}}, "limits": {"max_cost_usd": 0.25}}
    )
    assert once == twice


def test_encodes_floats_inside_a_set() -> None:
    assert artifact_canonical_json({"v": {1.5, 0.5}}) == '{"v":[0.5,1.5]}'


def test_agrees_with_the_domain_canonicalizer_on_float_free_payloads() -> None:
    payload = {"b": 1, "a": {"nested": [1, 2, 3], "flag": True, "missing": None}}
    assert artifact_canonical_json(payload) == domain_canonical_json(payload)


def test_agrees_with_the_domain_canonicalizer_on_datetimes_and_enums() -> None:
    payload = {"at": datetime(2026, 2, 1, 12, 0, tzinfo=UTC), "colour": _Colour.RED}
    assert artifact_canonical_json(payload) == domain_canonical_json(payload)


def test_artifact_sha256_hex_is_stable_and_64_hex_characters() -> None:
    digest = artifact_sha256_hex({"temperature": 0.2})
    assert digest == artifact_sha256_hex({"temperature": 0.2})
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_artifact_sha256_hex_distinguishes_different_floats() -> None:
    assert artifact_sha256_hex({"v": 0.1}) != artifact_sha256_hex({"v": 0.2})
