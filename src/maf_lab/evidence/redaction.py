"""Redaction before disk or telemetry export (spec section 21.3, NFR-04, NFR-13).

Two mechanisms run in order, and both are required:

1. **Schema-aware redaction** (`redact`) replaces configured field paths in a
   structured payload with `[REDACTED]`. It only ever looks at the paths it was
   told about.
2. **A pattern scanner** (`scan_for_leaks`) walks every string value in a
   payload — after schema-aware redaction has run — looking for a configured
   canary value or a secret-shaped string. It exists because schema-aware
   redaction cannot catch a canary that leaked into a field nobody configured,
   such as free text an agent echoed back.

Neither step replaces the other. Section 21.3: "Schema-aware redaction runs
before logs and telemetry, followed by a pattern scanner."
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

REDACTED_MARKER = "[REDACTED]"

_DEFAULT_REDACTED_PATHS = frozenset(
    {
        "prompt",
        "completion",
        "customer.name",
        "order.notes",
    }
)
"""NFR-13: full prompts, completions, customer names, notes.

Canaries are deliberately not schema-redacted by default: a canary is a
planted probe whose whole purpose is to prove it did *not* leak (spec section
16.2, "insert a unique non-sensitive canary... scan normalized exported
content for exact canary disclosure after canonicalization"). Redacting it by
path would hide a real disclosure instead of catching one; `scan_for_leaks`
with the trial's configured `canary_values` is what does that job.
"""

_SECRET_PATTERNS = (
    re.compile(r"sk-live-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)
"""Shapes of common provider/API secrets, matched independently of any
configured canary, because NFR-04 covers secret values generally."""


class RedactionConfig(BaseModel):
    """What to redact and what to scan for.

    `redacted_paths` uses dotted field names, with a trailing `[]` marking a
    list whose items should each be visited (`"messages[].variables"`), so one
    entry covers every element without the caller enumerating indices.
    """

    model_config = ConfigDict(frozen=True)

    redacted_paths: frozenset[str] = frozenset()
    canary_values: frozenset[str] = frozenset()

    @classmethod
    def default(cls) -> RedactionConfig:
        """The NFR-13 baseline: prompts, completions, customer names, notes, canaries."""
        return cls(redacted_paths=_DEFAULT_REDACTED_PATHS)


class RedactionViolation(BaseModel):
    """One place the pattern scanner found a canary or secret-shaped value.

    `detail` never repeats the disclosed value: a violation report that quoted
    the leak would itself be a second leak.
    """

    model_config = ConfigDict(frozen=True)

    path: str
    detail: str


def redact(payload: Mapping[str, Any], config: RedactionConfig) -> dict[str, Any]:
    """Return a copy of `payload` with every configured path replaced by `[REDACTED]`.

    Never mutates `payload`. A path absent from the payload is silently
    skipped: a configured field that a given payload happens not to carry is
    not an error.
    """
    result: dict[str, Any] = _deep_copy(payload)
    for path in config.redacted_paths:
        _redact_path(result, path.split("."))
    return result


def _deep_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_deep_copy(item) for item in value]
    return value


def _redact_path(node: Any, remaining: list[str]) -> None:
    """Apply one dotted (and possibly `[]`-marked) path to `node` in place."""
    if not remaining or not isinstance(node, dict):
        return
    segment, *rest = remaining
    is_list_segment = segment.endswith("[]")
    key = segment[:-2] if is_list_segment else segment
    if key not in node:
        return

    if is_list_segment:
        items = node[key]
        if not isinstance(items, list):
            return
        if rest:
            for item in items:
                _redact_path(item, rest)
        else:
            node[key] = [REDACTED_MARKER for _ in items]
        return

    if rest:
        _redact_path(node[key], rest)
    else:
        node[key] = REDACTED_MARKER


def scan_for_leaks(payload: Mapping[str, Any], config: RedactionConfig) -> list[RedactionViolation]:
    """Find every string in `payload` that contains a canary or secret-shaped value.

    Runs after `redact`, over whatever schema-aware redaction did not already
    remove. `[REDACTED]` markers are ordinary strings and are scanned like any
    other value; they never match a canary or a secret pattern, so they never
    produce a false violation.
    """
    violations: list[RedactionViolation] = []
    _scan(payload, "", config, violations)
    return violations


def _scan(
    value: Any, path: str, config: RedactionConfig, violations: list[RedactionViolation]
) -> None:
    if isinstance(value, str):
        for canary in config.canary_values:
            if canary in value:
                violations.append(
                    RedactionViolation(path=path, detail="configured canary value detected")
                )
                return
        for pattern in _SECRET_PATTERNS:
            if pattern.search(value):
                violations.append(
                    RedactionViolation(path=path, detail="secret-shaped value detected")
                )
                return
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _scan(item, f"{path}.{key}" if path else str(key), config, violations)
        return
    if isinstance(value, Sequence) and not isinstance(value, str):
        for index, item in enumerate(value):
            _scan(item, f"{path}[{index}]", config, violations)
