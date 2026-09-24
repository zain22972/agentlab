"""Canonical serialization and hashing for domain payloads.

Audit events carry before/after state hashes, and idempotency conflicts are
detected by comparing request digests. Both only work if two semantically
identical payloads serialize to exactly the same bytes, so this module fixes key
order, strips insignificant whitespace, and encodes datetimes as UTC ISO 8601.

Floating point is rejected rather than encoded: `repr` of a float is
platform-sensitive at the edges, and a hash that depends on the platform is not
a hash the lab can compare across machines.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any


def _reject_floats(payload: Any) -> None:
    if isinstance(payload, bool | int | str | type(None)):
        return
    if isinstance(payload, float):
        raise TypeError(f"floating point is not canonicalizable: {payload!r}")
    if isinstance(payload, Enum):
        _reject_floats(payload.value)
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            _reject_floats(key)
            _reject_floats(value)
        return
    if isinstance(payload, list | tuple | set | frozenset):
        for item in payload:
            _reject_floats(item)
        return


def _encode(payload: Any) -> Any:
    if isinstance(payload, datetime):
        # RFC 3339 with a `Z` suffix, matching how Pydantic's JSON mode renders
        # UTC instants, so both serialization paths hash identically.
        return payload.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(payload, Enum):
        return payload.value
    if isinstance(payload, tuple | set | frozenset):
        return sorted(payload) if isinstance(payload, set | frozenset) else list(payload)
    raise TypeError(f"not canonicalizable: {type(payload).__name__}")


def canonical_json(payload: Any) -> str:
    """Serialize `payload` to its one canonical JSON form."""
    _reject_floats(payload)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_encode,
    )


def sha256_hex(payload: Any) -> str:
    """Return the SHA-256 digest of the canonical form of `payload`."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
