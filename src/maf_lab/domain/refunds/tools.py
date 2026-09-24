"""The typed tool gateway.

This is the only door between an agent and canonical state. Every call through it
does the same four things in the same order: validate the request into a Pydantic
model, authorize it from typed state, mutate state and append an audit event, and
return a typed result. A tool never trusts the text that asked for it, and it
never returns a bare exception or a free-form string for a caller to interpret.

Only `create_refund` is implemented here. The remaining six tools follow the
same shape; `ToolGateway.tool_names` reports what is actually served so a suite
validator cannot silently pass a scenario naming a tool that does not exist yet.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Generic, Literal, TypeVar

from pydantic import Field, TypeAdapter, ValidationError

from maf_lab.domain.canonical import sha256_hex
from maf_lab.domain.refunds.models import (
    AuditAction,
    AuthorizationDecision,
    CreateRefundRequest,
    DomainModel,
    EntityType,
    IdempotencyKey,
    Identifier,
    MinorUnits,
    ReasonCode,
    Refund,
    ToolName,
    ToolOutcome,
)
from maf_lab.domain.refunds.policy import authorize_create_refund
from maf_lab.domain.refunds.state import RefundState

_IDENTIFIER = TypeAdapter(Identifier)
_IDEMPOTENCY_KEY = TypeAdapter(IdempotencyKey)

DataT = TypeVar("DataT", bound=DomainModel)


class Success(DomainModel, Generic[DataT]):
    """The tool ran and its effect, if any, is committed."""

    outcome: Literal[ToolOutcome.SUCCESS] = ToolOutcome.SUCCESS
    data: DataT


class InvalidRequest(DomainModel):
    """The arguments did not validate, so nothing was attempted.

    `errors` carries field paths and validator messages only. Rejected values are
    deliberately excluded: they are untrusted model output, and copying them into
    evidence would turn every artifact reader into an injection target.
    """

    outcome: Literal[ToolOutcome.INVALID_REQUEST] = ToolOutcome.INVALID_REQUEST
    reason_code: Literal[ReasonCode.REQUEST_SCHEMA_INVALID] = ReasonCode.REQUEST_SCHEMA_INVALID
    errors: tuple[str, ...]


class NotFound(DomainModel):
    """A named entity does not exist."""

    outcome: Literal[ToolOutcome.NOT_FOUND] = ToolOutcome.NOT_FOUND
    reason_code: ReasonCode
    entity_type: EntityType
    entity_id: str


class PolicyDenied(DomainModel):
    """The request was understood, authorized against state, and refused."""

    outcome: Literal[ToolOutcome.POLICY_DENIED] = ToolOutcome.POLICY_DENIED
    reason_code: ReasonCode
    detail: str = Field(default="", max_length=500)


class TransientFailure(DomainModel):
    """The tool failed in a way that a retry may resolve.

    Produced by fault injection at this boundary; the domain itself never fails
    transiently.
    """

    outcome: Literal[ToolOutcome.TRANSIENT_FAILURE] = ToolOutcome.TRANSIENT_FAILURE
    reason_code: ReasonCode
    retryable: Literal[True] = True


class UnknownOutcome(DomainModel):
    """The tool cannot say whether its effect was committed.

    The only safe recovery is to reconcile by the same idempotency key. Inventing
    a new key for an uncertain write is a test failure, not a retry.
    """

    outcome: Literal[ToolOutcome.UNKNOWN_OUTCOME] = ToolOutcome.UNKNOWN_OUTCOME
    reason_code: ReasonCode
    idempotency_key: IdempotencyKey


class IdempotencyConflict(DomainModel):
    """The key was already used for a materially different request.

    No effect is performed. Returning the earlier result instead would let a
    second, different refund silently inherit the first one's outcome.
    """

    outcome: Literal[ToolOutcome.IDEMPOTENCY_CONFLICT] = ToolOutcome.IDEMPOTENCY_CONFLICT
    reason_code: Literal[ReasonCode.IDEMPOTENCY_KEY_CONFLICT] = ReasonCode.IDEMPOTENCY_KEY_CONFLICT
    idempotency_key: IdempotencyKey


class CreateRefundData(DomainModel):
    """The committed refund and the balance it left behind."""

    refund: Refund
    order_refundable_minor: MinorUnits


CreateRefundResult = (
    Success[CreateRefundData]
    | InvalidRequest
    | NotFound
    | PolicyDenied
    | TransientFailure
    | UnknownOutcome
    | IdempotencyConflict
)
"""Every outcome `create_refund` may report, discriminated by `outcome`."""


class ToolGateway:
    """Serves the typed fake tools for one trial."""

    def __init__(self, state: RefundState) -> None:
        self._state = state

    @property
    def tool_names(self) -> tuple[ToolName, ...]:
        """The tools this gateway actually serves."""
        return (ToolName.CREATE_REFUND,)

    def create_refund(self, arguments: Mapping[str, Any]) -> CreateRefundResult:
        """Refund part or all of an order.

        `arguments` is untrusted: it is whatever the agent proposed. The request
        either becomes a `CreateRefundRequest` or is rejected; the authorization
        decision is then taken from typed state alone.
        """
        state = self._state
        try:
            request = CreateRefundRequest.model_validate(dict(arguments))
        except ValidationError as error:
            return self._reject(arguments, error)

        request_sha256 = sha256_hex(request.model_dump(mode="json"))
        replayed = self._replay(request, request_sha256)
        if replayed is not None:
            return replayed

        decision = authorize_create_refund(
            principal=state.principal,
            customer=state.customer(state.principal.customer_id),
            order=state.order(request.order_id),
            policy=state.refund_policy,
            request=request,
            now=state.clock.now(),
        )
        if not decision.allowed:
            self._audit_attempt_without_effect(
                action=AuditAction.REFUND_CREATE,
                entity_type=EntityType.ORDER,
                entity_id=request.order_id,
                decision=decision,
                idempotency_key=request.idempotency_key,
            )
            if decision.reason_code is ReasonCode.ORDER_NOT_FOUND:
                return NotFound(
                    reason_code=decision.reason_code,
                    entity_type=EntityType.ORDER,
                    entity_id=request.order_id,
                )
            if decision.reason_code is ReasonCode.CUSTOMER_NOT_FOUND:
                return NotFound(
                    reason_code=decision.reason_code,
                    entity_type=EntityType.CUSTOMER,
                    entity_id=state.principal.customer_id,
                )
            return PolicyDenied(reason_code=decision.reason_code, detail=decision.detail)

        # One effect, one idempotency record, one audit event. In this profile the
        # block is a single synchronous step; the durable profile wraps the same
        # three writes in one database transaction.
        before_sha256 = state.state_sha256()
        refund = Refund(
            refund_id=self._refund_id(request),
            order_id=request.order_id,
            customer_id=state.principal.customer_id,
            amount_minor=request.amount_minor,
            currency=request.currency,
            reason=request.reason,
            status=state.refund_policy.initial_status_for(request.amount_minor),
            idempotency_key=request.idempotency_key,
            created_at=state.clock.now(),
        )
        order = state.commit_refund(refund)
        data = CreateRefundData(refund=refund, order_refundable_minor=order.refundable_minor)
        state.record_idempotency(
            tool_name=ToolName.CREATE_REFUND,
            idempotency_key=request.idempotency_key,
            request_sha256=request_sha256,
            result_payload=data.model_dump(mode="json"),
        )
        state.record_audit(
            action=AuditAction.REFUND_CREATE,
            entity_type=EntityType.REFUND,
            entity_id=refund.refund_id,
            decision=decision,
            idempotency_key=request.idempotency_key,
            before_sha256=before_sha256,
            after_sha256=state.state_sha256(),
        )
        return Success[CreateRefundData](data=data)

    def _audit_attempt_without_effect(
        self,
        *,
        action: AuditAction,
        entity_type: EntityType,
        entity_id: str | None,
        decision: AuthorizationDecision,
        idempotency_key: str | None,
    ) -> None:
        """Record an attempt whose before and after hashes are identical.

        Every refusal and every replay goes through here, so "this call changed
        nothing" is always written down with the same shape rather than left as an
        absence of evidence.
        """
        unchanged = self._state.state_sha256()
        self._state.record_audit(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            decision=decision,
            idempotency_key=idempotency_key,
            before_sha256=unchanged,
            after_sha256=unchanged,
        )

    def _reject(self, arguments: Mapping[str, Any], error: ValidationError) -> InvalidRequest:
        """Audit and report a request that never became a typed model."""
        self._audit_attempt_without_effect(
            action=AuditAction.REFUND_CREATE,
            entity_type=EntityType.ORDER,
            entity_id=_validated_or_none(_IDENTIFIER, arguments.get("order_id")),
            decision=_schema_denial(error),
            idempotency_key=_validated_or_none(
                _IDEMPOTENCY_KEY, arguments.get("idempotency_key")
            ),
        )
        return InvalidRequest(errors=_error_paths(error))

    def _replay(
        self, request: CreateRefundRequest, request_sha256: str
    ) -> Success[CreateRefundData] | IdempotencyConflict | None:
        """Resolve a key that has already been used, or return `None` if it is new."""
        state = self._state
        record = state.idempotency_record(
            tool_name=ToolName.CREATE_REFUND, idempotency_key=request.idempotency_key
        )
        if record is None:
            return None

        if record.request_sha256 != request_sha256:
            self._audit_attempt_without_effect(
                action=AuditAction.REFUND_CREATE,
                entity_type=EntityType.ORDER,
                entity_id=request.order_id,
                decision=_conflict_denial(),
                idempotency_key=request.idempotency_key,
            )
            return IdempotencyConflict(idempotency_key=request.idempotency_key)

        data = CreateRefundData.model_validate(record.result_payload)
        self._audit_attempt_without_effect(
            action=AuditAction.REFUND_CREATE_REPLAY,
            entity_type=EntityType.REFUND,
            entity_id=data.refund.refund_id,
            decision=AuthorizationDecision.allow(),
            idempotency_key=request.idempotency_key,
        )
        return Success[CreateRefundData](data=data)

    def _refund_id(self, request: CreateRefundRequest) -> str:
        """Derive a refund identifier from the request, never from a random source.

        A random identifier would differ between two trials that behaved
        identically, and identity is what the replay path compares.
        """
        digest = sha256_hex(
            {
                "principal_id": self._state.principal.customer_id,
                "order_id": request.order_id,
                "idempotency_key": request.idempotency_key,
            }
        )
        return f"ref_{digest[:12]}"


def _error_paths(error: ValidationError) -> tuple[str, ...]:
    return tuple(
        f"{'.'.join(str(part) for part in item['loc']) or '<request>'}: {item['msg']}"
        for item in error.errors(include_url=False, include_input=False, include_context=False)
    )


def _schema_denial(error: ValidationError) -> AuthorizationDecision:
    return AuthorizationDecision.deny(
        ReasonCode.REQUEST_SCHEMA_INVALID,
        f"{error.error_count()} argument validation error(s)",
    )


def _conflict_denial() -> AuthorizationDecision:
    return AuthorizationDecision.deny(
        ReasonCode.IDEMPOTENCY_KEY_CONFLICT,
        "idempotency key was used for a different request",
    )


def _validated_or_none(adapter: TypeAdapter[str], value: Any) -> str | None:
    """Keep `value` only if it satisfies `adapter`.

    Audit fields are constrained, and the arguments here are untrusted. An
    unusable value is dropped rather than coerced, so the audit record never
    carries a field shaped by model output.
    """
    try:
        return str(adapter.validate_python(value))
    except ValidationError:
        return None
