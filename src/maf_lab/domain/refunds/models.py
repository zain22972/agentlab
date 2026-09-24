"""Canonical entities of the simulated refund-support domain.

These models are data only. They hold no policy rules (see `policy.py`), perform
no mutation (see `state.py`) and know nothing about agents, models or the
harness. Everything here is frozen and forbids unknown fields, so a state
snapshot has exactly one shape and an agent cannot smuggle an extra attribute
into canonical state by sending an extra argument.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from maf_lab.domain.clock import UtcDatetime
from maf_lab.domain.money import Currency, MinorUnits, Money

Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
]
"""An opaque synthetic identifier."""

Region = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
"""An ISO 3166-1 alpha-2 region code, validated syntactically."""

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""A lowercase hexadecimal SHA-256 digest."""

IdempotencyKey = Annotated[
    str, StringConstraints(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
]
"""A client-generated key that makes a mutation safely retryable.

The minimum length exists so that a model cannot invent a colliding key like
`"1"` and accidentally suppress a legitimate second refund.
"""

PositiveMinorUnits = Annotated[int, Field(gt=0)]
"""A strictly positive integer count of a currency's smallest unit."""


class DomainModel(BaseModel):
    """Base class for every domain entity.

    Frozen, closed to unknown fields, and populatable by field name or alias so a
    scenario's declared initial state parses straight into entities.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class CustomerTier(StrEnum):
    """Commercial tier of a customer."""

    STANDARD = "standard"
    PLUS = "plus"
    PREMIUM = "premium"


class OrderStatus(StrEnum):
    """Lifecycle status of an order."""

    PENDING = "pending"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class RefundStatus(StrEnum):
    """Lifecycle status of a refund."""

    PENDING = "pending"
    PENDING_APPROVAL = "pending_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RefundReason(StrEnum):
    """Why a refund was requested.

    A closed set rather than free text: the policy decides on the reason, and a
    policy that branched on model prose would not be an authorization boundary.
    """

    DAMAGED = "damaged"
    NOT_RECEIVED = "not_received"
    WRONG_ITEM = "wrong_item"
    LATE_DELIVERY = "late_delivery"
    CHANGED_MIND = "changed_mind"
    OTHER = "other"


class MessageChannel(StrEnum):
    """Delivery channel of an outbound customer message."""

    EMAIL = "email"
    SMS = "sms"


class SendStatus(StrEnum):
    """Delivery status of an outbound customer message."""

    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class EntityType(StrEnum):
    """Kind of entity an audit event refers to."""

    CUSTOMER = "customer"
    ORDER = "order"
    REFUND = "refund"
    MESSAGE = "message"


class AuditAction(StrEnum):
    """Action recorded in the audit log.

    Values are dotted tool-level actions so later tools extend this enum without
    renaming anything already written to an audit record.
    """

    REFUND_CREATE = "refund.create"
    REFUND_CREATE_REPLAY = "refund.create.replay"


class ToolName(StrEnum):
    """The complete tool surface the agent may call.

    Scenario manifests may name only these seven tools, so the allowlist lives
    with the domain vocabulary rather than in the manifest validator.
    """

    GET_CUSTOMER = "get_customer"
    GET_ORDER = "get_order"
    GET_REFUND_POLICY = "get_refund_policy"
    CREATE_REFUND = "create_refund"
    GET_REFUND_STATUS = "get_refund_status"
    SEND_CUSTOMER_MESSAGE = "send_customer_message"
    SEARCH_KNOWLEDGE = "search_knowledge"


class ToolOutcome(StrEnum):
    """The discriminator of every typed tool result.

    Values are part of the evidence contract: event payloads and evaluators match
    on them, so they are append-only.
    """

    SUCCESS = "success"
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    POLICY_DENIED = "policy_denied"
    TRANSIENT_FAILURE = "transient_failure"
    UNKNOWN_OUTCOME = "unknown_outcome"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"


class Scope(StrEnum):
    """Capability granted to an authenticated principal."""

    CUSTOMER_READ = "customer:read"
    ORDER_READ = "order:read"
    REFUND_CREATE = "refund:create"
    REFUND_READ = "refund:read"
    MESSAGE_SEND = "message:send"
    KNOWLEDGE_SEARCH = "knowledge:search"
    STAFF_READ = "staff:read"


class ReasonCode(StrEnum):
    """Stable reason code attached to every authorization decision.

    Reason codes are part of the evidence contract: reports and mutant tests
    compare them, so values are append-only and never reworded.
    """

    AUTHORIZED = "AUTHORIZED"
    REQUEST_SCHEMA_INVALID = "REQUEST_SCHEMA_INVALID"
    SCOPE_MISSING = "SCOPE_MISSING"
    SESSION_NOT_VERIFIED = "SESSION_NOT_VERIFIED"
    CUSTOMER_NOT_FOUND = "CUSTOMER_NOT_FOUND"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    PRINCIPAL_NOT_ORDER_OWNER = "PRINCIPAL_NOT_ORDER_OWNER"
    ORDER_STATUS_NOT_REFUNDABLE = "ORDER_STATUS_NOT_REFUNDABLE"
    ELIGIBILITY_WINDOW_EXPIRED = "ELIGIBILITY_WINDOW_EXPIRED"
    REASON_NOT_PERMITTED = "REASON_NOT_PERMITTED"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    AMOUNT_EXCEEDS_POLICY_MAXIMUM = "AMOUNT_EXCEEDS_POLICY_MAXIMUM"
    AMOUNT_EXCEEDS_REFUNDABLE_BALANCE = "AMOUNT_EXCEEDS_REFUNDABLE_BALANCE"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
    IDEMPOTENCY_KEY_CONFLICT = "IDEMPOTENCY_KEY_CONFLICT"


class Customer(DomainModel):
    """A customer of the simulated support desk."""

    customer_id: Identifier
    name: str = Field(max_length=200)
    tier: CustomerTier = CustomerTier.STANDARD
    region: Region
    verified_session: bool = Field(
        default=False,
        validation_alias=AliasChoices("verified_session", "verified"),
    )


class LineItem(DomainModel):
    """One purchased line of an order."""

    sku: Identifier
    description: str = Field(max_length=200)
    quantity: int = Field(ge=1)
    unit_amount_minor: MinorUnits


class Order(DomainModel):
    """An order that may be partially or fully refunded.

    Balances are stored flat (`refundable_minor` plus `currency`) because state
    assertions in scenario manifests select them by that path. `paid` and
    `refundable` expose the same values as `Money` for arithmetic.
    """

    order_id: Identifier
    customer_id: Identifier
    status: OrderStatus
    currency: Currency
    line_items: tuple[LineItem, ...] = ()
    paid_minor: MinorUnits
    refundable_minor: MinorUnits
    purchased_at: UtcDatetime

    @property
    def paid(self) -> Money:
        """Amount the customer paid."""
        return Money(minor_units=self.paid_minor, currency=self.currency)

    @property
    def refundable(self) -> Money:
        """Amount still available to refund."""
        return Money(minor_units=self.refundable_minor, currency=self.currency)

    @model_validator(mode="after")
    def _balance_within_paid_amount(self) -> Self:
        if self.refundable_minor > self.paid_minor:
            raise ValueError(
                f"refundable_minor {self.refundable_minor} exceeds paid_minor {self.paid_minor}"
            )
        return self


class RefundPolicy(DomainModel):
    """Trusted refund rules for an order.

    These fields are the only refund authority. Knowledge-base article text is
    untrusted by construction and can never substitute for them.
    """

    policy_id: Identifier = "policy.default.v1"
    eligibility_window_days: int = Field(ge=0)
    refundable_statuses: tuple[OrderStatus, ...]
    max_amount_minor: MinorUnits
    allowed_reasons: tuple[RefundReason, ...]
    approval_threshold_minor: MinorUnits

    def permits_status(self, status: OrderStatus) -> bool:
        """Whether an order in `status` may be refunded at all."""
        return status in self.refundable_statuses

    def permits_reason(self, reason: RefundReason) -> bool:
        """Whether `reason` is an accepted ground for a refund."""
        return reason in self.allowed_reasons

    def requires_approval(self, amount_minor: int) -> bool:
        """Whether `amount_minor` is large enough to need human approval."""
        return amount_minor > self.approval_threshold_minor

    def eligibility_deadline(self, purchased_at: datetime) -> datetime:
        """The last instant at which an order bought at `purchased_at` may be refunded."""
        return purchased_at + timedelta(days=self.eligibility_window_days)

    def initial_status_for(self, amount_minor: int) -> RefundStatus:
        """The status a newly authorized refund of `amount_minor` starts in."""
        if self.requires_approval(amount_minor):
            return RefundStatus.PENDING_APPROVAL
        return RefundStatus.PENDING


DEFAULT_REFUND_POLICY = RefundPolicy(
    policy_id="policy.default.v1",
    eligibility_window_days=30,
    refundable_statuses=(OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DELIVERED),
    max_amount_minor=50_000,
    allowed_reasons=(
        RefundReason.DAMAGED,
        RefundReason.NOT_RECEIVED,
        RefundReason.WRONG_ITEM,
        RefundReason.LATE_DELIVERY,
    ),
    approval_threshold_minor=10_000,
)
"""The policy a scenario gets when its initial state declares none."""


class Refund(DomainModel):
    """A refund recorded against an order."""

    refund_id: Identifier
    order_id: Identifier
    customer_id: Identifier
    amount_minor: PositiveMinorUnits
    currency: Currency
    reason: RefundReason
    status: RefundStatus
    idempotency_key: IdempotencyKey
    created_at: UtcDatetime

    @property
    def amount(self) -> Money:
        """Refunded amount."""
        return Money(minor_units=self.amount_minor, currency=self.currency)


class Message(DomainModel):
    """An outbound message queued for a customer."""

    message_id: Identifier
    customer_id: Identifier
    template_id: Identifier
    variables: dict[str, str] = Field(default_factory=dict)
    channel: MessageChannel = MessageChannel.EMAIL
    send_status: SendStatus = SendStatus.QUEUED
    created_at: UtcDatetime


class CreateRefundRequest(DomainModel):
    """A validated request to refund part or all of an order.

    Arguments arrive as untrusted model output and become this model or nothing.
    `reason` is a closed enum and `amount_minor` is a positive integer, so prose
    and fractional amounts are rejected at the boundary.
    """

    order_id: Identifier
    amount_minor: PositiveMinorUnits
    currency: Currency
    reason: RefundReason
    idempotency_key: IdempotencyKey


class Principal(DomainModel):
    """The authenticated identity a trial's tool calls run as.

    A principal is established by the scenario's initial state, never by model
    output. Prompts are not a security boundary.
    """

    customer_id: Identifier
    scopes: frozenset[Scope] = frozenset()

    def has(self, scope: Scope) -> bool:
        """Whether this principal holds `scope`."""
        return scope in self.scopes

    @property
    def is_staff(self) -> bool:
        """Whether this principal may read beyond its own records."""
        return Scope.STAFF_READ in self.scopes


class AuthorizationDecision(DomainModel):
    """The outcome of authorizing one tool request.

    A decision is produced from typed state and the declared principal alone, so
    it is reproducible from evidence without replaying a model.
    """

    allowed: bool
    reason_code: ReasonCode
    detail: str = Field(default="", max_length=500)

    @classmethod
    def allow(cls) -> Self:
        """An authorized decision."""
        return cls(allowed=True, reason_code=ReasonCode.AUTHORIZED)

    @classmethod
    def deny(cls, reason_code: ReasonCode, detail: str = "") -> Self:
        """A denied decision carrying a stable reason code."""
        return cls(allowed=False, reason_code=reason_code, detail=detail)

    @model_validator(mode="after")
    def _reason_matches_outcome(self) -> Self:
        authorized = self.reason_code is ReasonCode.AUTHORIZED
        if self.allowed is not authorized:
            raise ValueError(
                f"reason_code {self.reason_code} is inconsistent with allowed={self.allowed}"
            )
        return self


class AuditEvent(DomainModel):
    """One append-only record of an attempted state change.

    Denied and invalid attempts are recorded too, with `before_sha256` equal to
    `after_sha256`. That is what makes "the denial changed nothing" a checkable
    claim rather than an absence of evidence.
    """

    audit_id: Identifier
    sequence: int = Field(ge=1)
    occurred_at: UtcDatetime
    actor: Identifier
    action: AuditAction
    entity_type: EntityType
    entity_id: Identifier | None
    before_sha256: Sha256Hex
    after_sha256: Sha256Hex
    decision: AuthorizationDecision
    idempotency_key: IdempotencyKey | None

    @property
    def mutated(self) -> bool:
        """Whether canonical state changed as a result of this action."""
        return self.before_sha256 != self.after_sha256
