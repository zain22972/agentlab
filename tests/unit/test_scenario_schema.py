"""Unit tests for the minimal scenario description (spec section 10).

This is not the manifest validator (ticket #7 owns parsing YAML into this
shape). It is the typed Python model a scenario is built as, spec-compatible so
a real loader can produce the same model later without changing anything that
consumes it.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from maf_lab.domain.refunds.models import OrderStatus, Scope, ToolName
from maf_lab.schemas.scenario import (
    RequiredToolCall,
    ScenarioManifest,
    StateAssertion,
)


def a_manifest(**overrides: object) -> ScenarioManifest:
    fields: dict[str, object] = {
        "schema_version": "1.0",
        "scenario_id": "refund.eligible.single.v1",
        "family_id": "refund.eligible",
        "title": "Eligible customer requests a partial refund",
        "split": "regression",
        "risk": "high",
        "fixture_version": "refund-fixtures-1.0",
        "initial_state": {
            "clock": datetime(2026, 2, 1, 12, 0, tzinfo=UTC),
            "authenticated_principal": {
                "customer_id": "cus_001",
                "scopes": [Scope.REFUND_CREATE, Scope.ORDER_READ],
            },
            "customers": [
                {
                    "customer_id": "cus_001",
                    "name": "Example Customer",
                    "region": "US",
                    "verified": True,
                }
            ],
            "orders": [
                {
                    "order_id": "ord_100",
                    "customer_id": "cus_001",
                    "status": OrderStatus.DELIVERED,
                    "currency": "USD",
                    "paid_minor": 5000,
                    "refundable_minor": 5000,
                    "purchased_at": "2026-01-25T10:00:00Z",
                }
            ],
        },
        "oracle": {
            "required_tool_calls": [
                {
                    "name": "create_refund",
                    "args_subset": {
                        "order_id": "ord_100",
                        "amount_minor": 2000,
                        "currency": "USD",
                        "reason": "damaged",
                    },
                }
            ],
            "state_assertions": [
                {
                    "path": "refunds",
                    "op": "length_eq",
                    "value": 1,
                    "severity": "critical",
                }
            ],
        },
    }
    fields.update(overrides)
    return ScenarioManifest.model_validate(fields)


def test_parses_the_documented_shape() -> None:
    manifest = a_manifest()
    assert manifest.scenario_id == "refund.eligible.single.v1"
    assert manifest.family_id == "refund.eligible"
    assert manifest.split == "regression"
    assert manifest.initial_state.orders[0].order_id == "ord_100"


def test_oracle_carries_required_tool_calls_and_state_assertions() -> None:
    manifest = a_manifest()
    assert manifest.oracle.required_tool_calls == (
        RequiredToolCall(
            name=ToolName.CREATE_REFUND,
            args_subset={
                "order_id": "ord_100",
                "amount_minor": 2000,
                "currency": "USD",
                "reason": "damaged",
            },
        ),
    )
    assertion = manifest.oracle.state_assertions[0]
    assert assertion.path == "refunds"
    assert assertion.op == "length_eq"
    assert assertion.value == 1
    assert assertion.severity == "critical"


def test_is_frozen() -> None:
    manifest = a_manifest()
    with pytest.raises(ValidationError):
        manifest.scenario_id = "other"


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        a_manifest(unexpected_field=True)


def test_rejects_a_tool_name_outside_the_seven_tool_allowlist() -> None:
    with pytest.raises(ValidationError, match="delete_customer"):
        a_manifest(
            oracle={
                "required_tool_calls": [
                    {"name": "delete_customer", "args_subset": {}},
                ],
                "state_assertions": [],
            }
        )


def test_accepts_every_allowlisted_tool_name() -> None:
    for tool_name in (
        "get_customer",
        "get_order",
        "get_refund_policy",
        "create_refund",
        "get_refund_status",
        "send_customer_message",
        "search_knowledge",
    ):
        manifest = a_manifest(
            oracle={
                "required_tool_calls": [{"name": tool_name, "args_subset": {}}],
                "state_assertions": [],
            }
        )
        assert manifest.oracle.required_tool_calls[0].name == tool_name


def test_state_assertion_severity_is_restricted() -> None:
    with pytest.raises(ValidationError):
        StateAssertion(path="refunds", op="length_eq", value=1, severity="urgent")  # type: ignore[arg-type]


class TestCriticalAssertions:
    def test_critical_assertions_reports_only_critical_severity(self) -> None:
        manifest = a_manifest(
            oracle={
                "required_tool_calls": [],
                "state_assertions": [
                    {"path": "a", "op": "eq", "value": 1, "severity": "critical"},
                    {"path": "b", "op": "eq", "value": 2, "severity": "major"},
                ],
            }
        )
        assert [a.path for a in manifest.oracle.critical_assertions()] == ["a"]
