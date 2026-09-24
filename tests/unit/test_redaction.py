"""Unit tests for redaction (spec section 21.3, NFR-04, NFR-13).

Two mechanisms, run in order: schema-aware redaction removes or masks
configured field paths from a structured payload, then a pattern scanner
catches secrets and canaries that leaked outside any configured path (for
example inside free text). Neither step is optional; the pattern scanner exists
precisely because schema-aware redaction only knows about the fields it was
told to look at.
"""

from __future__ import annotations

import pytest

from maf_lab.evidence.redaction import (
    RedactionConfig,
    RedactionViolation,
    redact,
    scan_for_leaks,
)


class TestSchemaAwareRedaction:
    def test_redacts_a_configured_top_level_field(self) -> None:
        config = RedactionConfig(redacted_paths=frozenset({"api_key"}))
        result = redact({"api_key": "sk-secret", "trial_id": "trial_0001"}, config)
        assert result == {"api_key": "[REDACTED]", "trial_id": "trial_0001"}

    def test_redacts_a_nested_configured_field(self) -> None:
        config = RedactionConfig(redacted_paths=frozenset({"customer.name"}))
        result = redact({"customer": {"name": "Jane Doe", "customer_id": "cus_001"}}, config)
        assert result == {"customer": {"name": "[REDACTED]", "customer_id": "cus_001"}}

    def test_redacts_a_field_inside_every_item_of_a_list(self) -> None:
        config = RedactionConfig(redacted_paths=frozenset({"messages[].variables"}))
        result = redact(
            {"messages": [{"variables": {"note": "secret"}}, {"variables": {"note": "other"}}]},
            config,
        )
        assert result == {
            "messages": [{"variables": "[REDACTED]"}, {"variables": "[REDACTED]"}]
        }

    def test_leaves_unconfigured_fields_untouched(self) -> None:
        config = RedactionConfig(redacted_paths=frozenset({"api_key"}))
        result = redact({"trial_id": "trial_0001", "status": "completed"}, config)
        assert result == {"trial_id": "trial_0001", "status": "completed"}

    def test_a_missing_configured_path_is_not_an_error(self) -> None:
        config = RedactionConfig(redacted_paths=frozenset({"api_key"}))
        result = redact({"trial_id": "trial_0001"}, config)
        assert result == {"trial_id": "trial_0001"}

    def test_does_not_mutate_the_input(self) -> None:
        config = RedactionConfig(redacted_paths=frozenset({"api_key"}))
        original = {"api_key": "sk-secret"}
        redact(original, config)
        assert original == {"api_key": "sk-secret"}

    def test_default_config_redacts_the_documented_nfr13_fields(self) -> None:
        """NFR-13: full prompts, completions, customer names, and notes are
        excluded from telemetry by default. Canaries are handled separately by
        the pattern scanner: see TestPatternScanner and section 16.2."""
        config = RedactionConfig.default()
        payload = {
            "prompt": "the full raw prompt",
            "completion": "the full raw completion",
            "customer": {"name": "Jane Doe", "customer_id": "cus_001"},
            "order": {"notes": "call before delivery"},
        }
        result = redact(payload, config)
        assert result["prompt"] == "[REDACTED]"
        assert result["completion"] == "[REDACTED]"
        assert result["customer"]["name"] == "[REDACTED]"
        assert result["customer"]["customer_id"] == "cus_001"
        assert result["order"]["notes"] == "[REDACTED]"

    def test_default_config_does_not_schema_redact_a_canary(self) -> None:
        """A canary must survive schema-aware redaction so the pattern scanner
        can prove whether it disclosed; redacting it by path would hide a real
        leak instead of catching one."""
        config = RedactionConfig.default()
        result = redact({"canary": "CANARY-af31-do-not-disclose"}, config)
        assert result["canary"] == "CANARY-af31-do-not-disclose"


class TestPatternScanner:
    def test_flags_a_canary_value_that_leaked_into_free_text(self) -> None:
        config = RedactionConfig(canary_values=frozenset({"CANARY-af31-do-not-disclose"}))
        leaks = scan_for_leaks(
            {"response_text": "Sure, here it is: CANARY-af31-do-not-disclose"}, config
        )
        assert len(leaks) == 1
        assert leaks[0].path == "response_text"
        assert "CANARY-af31-do-not-disclose" not in leaks[0].detail

    def test_scans_nested_and_list_values(self) -> None:
        config = RedactionConfig(canary_values=frozenset({"CANARY-1"}))
        leaks = scan_for_leaks(
            {"events": [{"payload": {"text": "leaked CANARY-1 here"}}]}, config
        )
        assert any(leak.path == "events[0].payload.text" for leak in leaks)

    def test_reports_no_leaks_when_the_canary_never_appears(self) -> None:
        config = RedactionConfig(canary_values=frozenset({"CANARY-1"}))
        leaks = scan_for_leaks({"response_text": "nothing sensitive here"}, config)
        assert leaks == []

    def test_flags_a_secret_pattern_even_without_a_declared_canary(self) -> None:
        """An API-key-shaped string is caught by the pattern scanner even if it
        was never configured as a canary, because NFR-04 covers "secret values"
        generally, not only seeded canaries."""
        config = RedactionConfig()
        leaks = scan_for_leaks({"note": "use sk-live-abcdef1234567890abcdef1234567890"}, config)
        assert any(leak.path == "note" for leak in leaks)

    def test_a_redacted_marker_does_not_itself_trigger_a_leak(self) -> None:
        config = RedactionConfig(canary_values=frozenset({"CANARY-1"}))
        leaks = scan_for_leaks({"value": "[REDACTED]"}, config)
        assert leaks == []

    def test_flags_an_undisguised_canary_present_anywhere(self) -> None:
        """The canary path from TestSchemaAwareRedaction: because canaries are
        never schema-redacted, an undisguised canary anywhere in a payload is
        exactly what this scanner is relied on to catch."""
        config = RedactionConfig(canary_values=frozenset({"CANARY-af31-do-not-disclose"}))
        leaks = scan_for_leaks({"canary": "CANARY-af31-do-not-disclose"}, config)
        assert len(leaks) == 1
        assert leaks[0].path == "canary"


class TestRedactionViolation:
    def test_carries_a_path_and_a_non_disclosing_detail(self) -> None:
        violation = RedactionViolation(path="a.b", detail="canary detected")
        assert violation.path == "a.b"
        assert violation.detail == "canary detected"


class TestEndToEndRedactionBeforeWrite:
    def test_a_leak_the_schema_did_not_cover_is_still_caught_by_the_scanner(self) -> None:
        """The scenario the two-mechanism design exists for: a canary value
        embedded in a free-text field that no configured path names."""
        config = RedactionConfig(canary_values=frozenset({"CANARY-1"}))
        payload = {"response_text": "the answer contains CANARY-1 unexpectedly"}
        redacted = redact(payload, config)  # schema-aware pass does not know this path
        leaks = scan_for_leaks(redacted, config)
        assert len(leaks) == 1


@pytest.mark.parametrize(
    "value",
    [
        "sk-live-abcdef1234567890abcdef1234567890",
        "AKIAABCDEFGHIJKLMNOP",
    ],
)
def test_pattern_scanner_recognizes_common_secret_shapes(value: str) -> None:
    config = RedactionConfig()
    leaks = scan_for_leaks({"field": value}, config)
    assert len(leaks) == 1
