"""Canonical serialization and hashing for artifacts: manifests and records.

`maf_lab.domain.canonical` refuses floating point outright, because the domain
never legitimately produces one (ADR 0002). Manifests and normalized records are
a different kind of payload: `limits.max_cost_usd`, `agent.parameters.temperature`,
and evaluation `score`/`threshold`/`estimate`/`ci_low`/`ci_high` are floats in
every provider and statistics tool this project interoperates with. Forcing them
into integers or strings at this layer would just move the translation problem
to every report and provider boundary instead of solving it once, here.

The two canonicalizers agree on everything except floats: sorted keys, `(",",
":")` separators, UTF-8 output, UTC RFC 3339 datetimes, enums by value. That
agreement is enforced by sharing `maf_lab.domain.canonical.encode_common`
rather than by convention, so the two cannot silently drift.

See docs/design/canonicalization-and-hashing.md for the design rationale.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from maf_lab.domain.canonical import encode_common


class _CanonicalFloat(float):
    """A float whose `repr` is its canonical decimal string.

    `json.dumps` renders `float` values through its own internal `floatstr`,
    never through the `default=` hook, so `default=` alone cannot fix a float's
    formatting. Subclassing `float` and overriding `__repr__` intercepts at the
    point `json` actually reads from: `float.__repr__(self)`.
    """

    def __repr__(self) -> str:
        return float.__repr__(self)


def _canonicalize_floats(payload: Any) -> Any:
    """Replace every float in `payload` with a `_CanonicalFloat`, rejecting non-finite values.

    `repr(float)` is the shortest decimal string that round-trips back to the
    same IEEE-754 double on every CPython >= 3.1 (David Gay / Grisu), so it is
    stable across platforms without a fixed-point schema change. `-0.0` is
    normalized to `0.0`: the two compare equal, and a hash that depended on
    which one a provider happened to send would not be a canonical hash.
    """
    if isinstance(payload, bool):
        return payload
    if isinstance(payload, float):
        if not math.isfinite(payload):
            raise TypeError(f"artifact floats must be finite, got {payload!r}")
        return _CanonicalFloat(payload + 0.0)
    if isinstance(payload, dict):
        return {key: _canonicalize_floats(value) for key, value in payload.items()}
    if isinstance(payload, list | tuple | set | frozenset):
        return [_canonicalize_floats(item) for item in payload]
    return payload


def _encode(payload: Any) -> Any:
    return encode_common(payload)


def artifact_canonical_json(payload: Any) -> str:
    """Serialize `payload` to its one canonical JSON form, floats included."""
    return json.dumps(
        _canonicalize_floats(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_encode,
    )


def artifact_sha256_hex(payload: Any) -> str:
    """Return the SHA-256 digest of the canonical form of `payload`."""
    return hashlib.sha256(artifact_canonical_json(payload).encode("utf-8")).hexdigest()
