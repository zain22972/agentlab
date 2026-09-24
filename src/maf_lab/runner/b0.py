"""The B0 scripted deterministic reference agent (spec section 23).

> B0 deterministic reference: Scripted policy-correct mock agent; validates
> harness upper bound and reproducibility.

B0 involves no model and no credentials. It reads a scenario's
`oracle.required_tool_calls` and calls each one through the tool gateway with
exactly the declared arguments, in declaration order, adding only the
idempotency key every mutating call requires. It never improvises, retries, or
recovers: those are properties of an agent under test, and B0 exists to be the
ceiling a real agent is measured against, not a stand-in for one.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from maf_lab.domain.canonical import sha256_hex
from maf_lab.domain.refunds.models import ToolName
from maf_lab.domain.refunds.tools import CreateRefundResult, ToolGateway
from maf_lab.schemas.scenario import RequiredToolCall, ScenarioManifest


class UnsupportedToolError(RuntimeError):
    """Raised when a scenario requires a tool the gateway does not yet serve.

    B0 fails loudly here rather than skipping the call: a silently skipped call
    would make the harness's own upper-bound trial look policy-correct while
    quietly not exercising what the scenario asked for.
    """


class ToolCallOutcome(NamedTuple):
    """One completed call B0 made, kept for the event recorder to describe."""

    tool_name: ToolName
    arguments: dict[str, Any]
    result: CreateRefundResult


class B0Agent:
    """Drives one scenario's `oracle.required_tool_calls` through a gateway."""

    def __init__(self, manifest: ScenarioManifest) -> None:
        self._manifest = manifest

    def run(self, gateway: ToolGateway) -> tuple[ToolCallOutcome, ...]:
        """Call every required tool call in order and return each outcome."""
        outcomes: list[ToolCallOutcome] = []
        for index, call in enumerate(self._manifest.oracle.required_tool_calls):
            arguments = self._arguments_for(call, index)
            result = self._invoke(gateway, call.name, arguments)
            outcomes.append(
                ToolCallOutcome(tool_name=call.name, arguments=arguments, result=result)
            )
        return tuple(outcomes)

    def _arguments_for(self, call: RequiredToolCall, index: int) -> dict[str, Any]:
        arguments = dict(call.args_subset)
        if call.name is ToolName.CREATE_REFUND:
            arguments["idempotency_key"] = self._idempotency_key(call, index)
        return arguments

    def _idempotency_key(self, call: RequiredToolCall, index: int) -> str:
        """A key derived from the scenario and this call's position.

        Deterministic rather than random: NFR-02 requires that an identical
        manifest, code revision, fixture version, mock agent and seed produce
        byte-equivalent canonical output, and a random key would fail that on
        the very first field it touches.
        """
        digest = sha256_hex(
            {
                "scenario_id": self._manifest.scenario_id,
                "call_index": index,
                "tool_name": call.name.value,
                "args_subset": call.args_subset,
            }
        )
        return f"b0-{digest[:24]}"

    def _invoke(
        self, gateway: ToolGateway, tool_name: ToolName, arguments: dict[str, Any]
    ) -> CreateRefundResult:
        if tool_name is ToolName.CREATE_REFUND:
            return gateway.create_refund(arguments)
        raise UnsupportedToolError(
            f"the tool gateway does not yet serve {tool_name.value}; "
            "B0 cannot drive a scenario that requires it"
        )
