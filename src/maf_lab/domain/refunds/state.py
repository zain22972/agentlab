"""Per-trial refund state, built from a declared initial state.

Every trial gets its own `RefundState`. Nothing is shared between trials and
nothing survives one: a leaked balance or a leaked idempotency key would make a
`pass^k` estimate a measure of execution order rather than of the agent.

The state is the only writer of canonical entities. Agents never touch it; they
go through the tool gateway in `tools.py`.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Self

from pydantic import model_validator

from maf_lab.domain.canonical import sha256_hex
from maf_lab.domain.clock import Clock, FakeClock, UtcDatetime
from maf_lab.domain.money import CurrencyMismatchError, NegativeMoneyError
from maf_lab.domain.refunds.models import (
    DEFAULT_REFUND_POLICY,
    AuditAction,
    AuditEvent,
    AuthorizationDecision,
    Customer,
    DomainModel,
    EntityType,
    IdempotencyKey,
    Identifier,
    Message,
    Order,
    Principal,
    Refund,
    RefundPolicy,
    Sha256Hex,
    ToolName,
)


class StateError(RuntimeError):
    """Raised when a mutation would break a canonical-state invariant.

    Reaching this exception means an authorization check was missing or wrong:
    the gateway is expected to deny such a request before it gets here.
    """


class IdempotencyRecord(DomainModel):
    """The effective result of one mutating call, retrievable by its key.

    This is the in-process stand-in for the unique `(principal_id, tool_name,
    idempotency_key)` database constraint. The durable store, the transaction and
    the crash behaviour arrive with the durable profile.
    """

    principal_id: Identifier
    tool_name: ToolName
    idempotency_key: IdempotencyKey
    request_sha256: Sha256Hex
    result_payload: dict[str, Any]
    recorded_at: UtcDatetime


class InitialState(DomainModel):
    """The declared starting point of a trial.

    This mirrors the `initial_state` block a scenario declares. Cross references
    and balances are validated here, so an inconsistent declaration fails before
    a model is ever invoked.
    """

    clock: UtcDatetime
    authenticated_principal: Principal
    customers: tuple[Customer, ...] = ()
    orders: tuple[Order, ...] = ()
    refunds: tuple[Refund, ...] = ()
    messages: tuple[Message, ...] = ()
    refund_policy: RefundPolicy = DEFAULT_REFUND_POLICY

    @model_validator(mode="after")
    def _references_resolve(self) -> Self:
        customer_ids = _ids_without_duplicates(entity.customer_id for entity in self.customers)
        order_ids = _ids_without_duplicates(entity.order_id for entity in self.orders)
        _ids_without_duplicates(entity.refund_id for entity in self.refunds)
        _ids_without_duplicates(entity.message_id for entity in self.messages)

        orders_by_id = {order.order_id: order for order in self.orders}

        for order in self.orders:
            if order.customer_id not in customer_ids:
                raise ValueError(
                    f"order {order.order_id} names unknown customer {order.customer_id}"
                )
        for refund in self.refunds:
            if refund.order_id not in order_ids:
                raise ValueError(f"refund {refund.refund_id} names unknown order {refund.order_id}")
            if refund.currency != orders_by_id[refund.order_id].currency:
                raise ValueError(
                    f"refund {refund.refund_id} currency {refund.currency} does not match "
                    f"order {refund.order_id} currency {orders_by_id[refund.order_id].currency}"
                )
        for message in self.messages:
            if message.customer_id not in customer_ids:
                raise ValueError(
                    f"message {message.message_id} names unknown customer {message.customer_id}"
                )
        self._balances_account_for_declared_refunds(orders_by_id)
        return self

    def _balances_account_for_declared_refunds(self, orders_by_id: dict[str, Order]) -> None:
        """Refuse a declared state whose balances contradict its refund history.

        Without this, a state could declare a full refundable balance *and* a
        refund that already consumed it, letting the total refunded exceed the
        amount paid. The property test that a balance never goes negative would
        then be established only over states that happen to start consistent.
        """
        for order_id, order in orders_by_id.items():
            already_refunded = sum(
                refund.amount_minor for refund in self.refunds if refund.order_id == order_id
            )
            if order.refundable_minor + already_refunded > order.paid_minor:
                raise ValueError(
                    f"order {order_id} declares a refundable balance of "
                    f"{order.refundable_minor} with {already_refunded} already refunded, "
                    f"which exceeds the {order.paid_minor} paid"
                )


def _ids_without_duplicates(ids: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    for identifier in ids:
        if identifier in seen:
            raise ValueError(f"duplicate identifier {identifier} in initial state")
        seen.add(identifier)
    return seen


class RefundState:
    """Isolated, mutable canonical state for exactly one trial."""

    def __init__(self, initial: InitialState, clock: Clock) -> None:
        self._clock = clock
        self._principal = initial.authenticated_principal
        self._refund_policy = initial.refund_policy
        self._customers: dict[str, Customer] = {c.customer_id: c for c in initial.customers}
        self._orders: dict[str, Order] = {o.order_id: o for o in initial.orders}
        self._refunds: dict[str, Refund] = {r.refund_id: r for r in initial.refunds}
        self._messages: dict[str, Message] = {m.message_id: m for m in initial.messages}
        self._audit_log: list[AuditEvent] = []
        self._idempotency: dict[tuple[str, ToolName, str], IdempotencyRecord] = {}

    @classmethod
    def from_initial(cls, initial: InitialState, clock: Clock | None = None) -> Self:
        """Build a fresh state instance from `initial`.

        Omitting `clock` builds a `FakeClock` at the declared instant. Callers
        that need to move time within a trial inject their own.
        """
        return cls(initial, clock if clock is not None else FakeClock(initial.clock))

    @property
    def clock(self) -> Clock:
        """The clock every timestamp in this trial is read from."""
        return self._clock

    @property
    def principal(self) -> Principal:
        """The authenticated identity declared for this trial."""
        return self._principal

    @property
    def refund_policy(self) -> RefundPolicy:
        """The trusted refund rules declared for this trial."""
        return self._refund_policy

    @property
    def audit_log(self) -> tuple[AuditEvent, ...]:
        """Append-only audit events in the order they were recorded."""
        return tuple(self._audit_log)

    def customer(self, customer_id: str) -> Customer | None:
        """The customer with `customer_id`, if declared."""
        return self._customers.get(customer_id)

    def order(self, order_id: str) -> Order | None:
        """The order with `order_id`, if declared."""
        return self._orders.get(order_id)

    def refund(self, refund_id: str) -> Refund | None:
        """The refund with `refund_id`, if present."""
        return self._refunds.get(refund_id)

    def refunds_for_order(self, order_id: str) -> tuple[Refund, ...]:
        """Refunds recorded against `order_id`, ordered by identifier."""
        return tuple(
            self._refunds[key] for key in sorted(self._refunds) if self._refunds[key].order_id == order_id
        )

    def snapshot(self) -> dict[str, Any]:
        """A JSON-safe, deterministically ordered copy of canonical state.

        Collections are sorted by identifier so that two trials reaching the same
        state produce the same bytes, and therefore the same hash.
        """
        return {
            "customers": [self._customers[key].model_dump(mode="json") for key in sorted(self._customers)],
            "orders": [self._orders[key].model_dump(mode="json") for key in sorted(self._orders)],
            "refunds": [self._refunds[key].model_dump(mode="json") for key in sorted(self._refunds)],
            "messages": [self._messages[key].model_dump(mode="json") for key in sorted(self._messages)],
        }

    def state_sha256(self) -> str:
        """The digest of the current canonical state."""
        return sha256_hex(self.snapshot())

    def commit_refund(self, refund: Refund) -> Order:
        """Record `refund` and reduce its order's refundable balance.

        Raises `StateError` rather than storing an impossible balance. The
        subtraction is performed on `Money`, which cannot go negative.
        """
        order = self._orders.get(refund.order_id)
        if order is None:
            raise StateError(f"unknown order {refund.order_id}")
        if refund.refund_id in self._refunds:
            raise StateError(f"refund {refund.refund_id} already exists")
        try:
            remaining = order.refundable - refund.amount
        except CurrencyMismatchError as error:
            raise StateError(
                f"refund {refund.refund_id} currency {refund.currency} does not match "
                f"order {order.order_id} currency {order.currency}"
            ) from error
        except NegativeMoneyError as error:
            raise StateError(
                f"refund {refund.refund_id} of {refund.amount} exceeds refundable "
                f"balance {order.refundable} of order {order.order_id}"
            ) from error

        updated = order.model_copy(update={"refundable_minor": remaining.minor_units})
        self._orders[order.order_id] = updated
        self._refunds[refund.refund_id] = refund
        return updated

    def record_audit(
        self,
        *,
        action: AuditAction,
        entity_type: EntityType,
        entity_id: str | None,
        decision: AuthorizationDecision,
        idempotency_key: str | None,
        before_sha256: str,
        after_sha256: str,
    ) -> AuditEvent:
        """Append one audit event with the next monotonic sequence number."""
        sequence = len(self._audit_log) + 1
        event = AuditEvent(
            audit_id=f"audit_{sequence}",
            sequence=sequence,
            occurred_at=self._clock.now(),
            actor=self._principal.customer_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_sha256=before_sha256,
            after_sha256=after_sha256,
            decision=decision,
            idempotency_key=idempotency_key,
        )
        self._audit_log.append(event)
        return event

    def idempotency_record(
        self, *, tool_name: ToolName, idempotency_key: str
    ) -> IdempotencyRecord | None:
        """The effective result already recorded for this key, if any."""
        return self._idempotency.get((self._principal.customer_id, tool_name, idempotency_key))

    def record_idempotency(
        self,
        *,
        tool_name: ToolName,
        idempotency_key: str,
        request_sha256: str,
        result_payload: dict[str, Any],
    ) -> IdempotencyRecord:
        """Record the effective result of a mutation under its key."""
        index = (self._principal.customer_id, tool_name, idempotency_key)
        if index in self._idempotency:
            raise StateError(
                f"idempotency key {idempotency_key} already recorded for {tool_name}"
            )
        record = IdempotencyRecord(
            principal_id=self._principal.customer_id,
            tool_name=tool_name,
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
            result_payload=result_payload,
            recorded_at=self._clock.now(),
        )
        self._idempotency[index] = record
        return record
