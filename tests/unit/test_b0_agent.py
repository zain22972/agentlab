"""Unit tests for the B0 scripted deterministic reference agent (spec section 23).

B0 is "a scripted policy-correct mock agent" that "validates harness upper
bound and reproducibility." No model, no credentials: it reads a scenario's
`oracle.required_tool_calls` and calls each one through the tool gateway with
exactly the given arguments plus a derived idempotency key, in order. It never
does anything a policy-correct agent would not do, which is what makes it the
harness's upper bound rather than a test of agent behavior.
"""

from datetime import UTC, datetime

import pytest

from maf_lab.domain.refunds.models import OrderStatus, Scope
from maf_lab.domain.refunds.state import RefundState
from maf_lab.domain.refunds.tools import Success, ToolGateway
from maf_lab.runner.b0 import B0Agent
from maf_lab.schemas.scenario import ScenarioManifest

CLOCK_START = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)


def a_manifest(**oracle_overrides: object) -> ScenarioManifest:
    oracle_fields: dict[str, object] = {
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
        "state_assertions": [],
    }
    oracle_fields.update(oracle_overrides)
    return ScenarioManifest.model_validate(
        {
            "schema_version": "1.0",
            "scenario_id": "refund.eligible.single.v1",
            "family_id": "refund.eligible",
            "title": "Eligible customer requests a partial refund",
            "split": "regression",
            "risk": "high",
            "fixture_version": "refund-fixtures-1.0",
            "initial_state": {
                "clock": CLOCK_START,
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
            "oracle": oracle_fields,
        }
    )


class TestSingleToolCall:
    def test_drives_the_gateway_and_commits_the_expected_effect(self) -> None:
        manifest = a_manifest()
        state = RefundState.from_initial(manifest.initial_state)
        gateway = ToolGateway(state)
        agent = B0Agent(manifest)

        results = agent.run(gateway)

        assert len(results) == 1
        assert isinstance(results[0].result, Success)
        assert state.order("ord_100").refundable_minor == 3000  # type: ignore[union-attr]

    def test_reports_the_tool_name_and_arguments_it_used(self) -> None:
        manifest = a_manifest()
        state = RefundState.from_initial(manifest.initial_state)
        agent = B0Agent(manifest)

        results = agent.run(ToolGateway(state))

        assert results[0].tool_name.value == "create_refund"
        assert results[0].arguments["order_id"] == "ord_100"
        assert results[0].arguments["amount_minor"] == 2000

    def test_derives_a_stable_idempotency_key_from_the_scenario_and_call_index(self) -> None:
        """B0 must supply an idempotency_key (create_refund requires one) and
        must do so deterministically, so identical scenario executions produce
        byte-identical evidence (NFR-02)."""
        manifest = a_manifest()
        first = B0Agent(manifest).run(ToolGateway(RefundState.from_initial(manifest.initial_state)))
        second = B0Agent(manifest).run(
            ToolGateway(RefundState.from_initial(manifest.initial_state))
        )
        assert first[0].arguments["idempotency_key"] == second[0].arguments["idempotency_key"]


class TestMultipleToolCalls:
    def test_calls_every_required_tool_call_in_order(self) -> None:
        manifest = a_manifest(
            required_tool_calls=[
                {
                    "name": "create_refund",
                    "args_subset": {
                        "order_id": "ord_100",
                        "amount_minor": 1000,
                        "currency": "USD",
                        "reason": "damaged",
                    },
                },
                {
                    "name": "create_refund",
                    "args_subset": {
                        "order_id": "ord_100",
                        "amount_minor": 500,
                        "currency": "USD",
                        "reason": "wrong_item",
                    },
                },
            ]
        )
        state = RefundState.from_initial(manifest.initial_state)
        agent = B0Agent(manifest)

        results = agent.run(ToolGateway(state))

        assert len(results) == 2
        assert all(isinstance(r.result, Success) for r in results)
        assert state.order("ord_100").refundable_minor == 3500  # type: ignore[union-attr]

    def test_distinct_calls_get_distinct_idempotency_keys(self) -> None:
        manifest = a_manifest(
            required_tool_calls=[
                {
                    "name": "create_refund",
                    "args_subset": {
                        "order_id": "ord_100",
                        "amount_minor": 1000,
                        "currency": "USD",
                        "reason": "damaged",
                    },
                },
                {
                    "name": "create_refund",
                    "args_subset": {
                        "order_id": "ord_100",
                        "amount_minor": 500,
                        "currency": "USD",
                        "reason": "wrong_item",
                    },
                },
            ]
        )
        state = RefundState.from_initial(manifest.initial_state)
        results = B0Agent(manifest).run(ToolGateway(state))
        assert results[0].arguments["idempotency_key"] != results[1].arguments["idempotency_key"]


class TestNoRequiredToolCalls:
    def test_an_empty_oracle_produces_no_calls_and_no_error(self) -> None:
        manifest = a_manifest(required_tool_calls=[])
        state = RefundState.from_initial(manifest.initial_state)
        results = B0Agent(manifest).run(ToolGateway(state))
        assert results == ()


class TestUnsupportedTool:
    def test_a_tool_the_gateway_does_not_yet_serve_raises_a_clear_error(self) -> None:
        """`get_customer` is in the allowlist (schemas/scenario.py) but ticket
        #5 has not implemented it in the gateway yet. B0 must fail loudly
        rather than silently skip or fabricate a result."""
        manifest = a_manifest(
            required_tool_calls=[{"name": "get_customer", "args_subset": {}}]
        )
        state = RefundState.from_initial(manifest.initial_state)
        from maf_lab.runner.b0 import UnsupportedToolError

        with pytest.raises(UnsupportedToolError, match="get_customer"):
            B0Agent(manifest).run(ToolGateway(state))
