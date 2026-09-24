"""Monetary values for the simulated domain.

Money is an integer count of minor units plus an ISO 4217 alpha-3 currency code.
Binary floating point never appears: it cannot represent 0.10 exactly, so a
sequence of partial refunds would drift away from the balance the oracle asserts.

The currency check is syntactic (three uppercase letters). The lab only needs to
detect *mismatch* between a request and an order, so a full ISO 4217 registry
would add a maintenance burden without adding an assertion anyone makes.
"""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

CURRENCY_PATTERN = r"^[A-Z]{3}$"

Currency = Annotated[str, StringConstraints(pattern=CURRENCY_PATTERN)]
"""An ISO 4217 alpha-3 currency code, validated syntactically."""

MinorUnits = Annotated[int, Field(ge=0)]
"""A non-negative integer count of a currency's smallest unit."""


class MoneyError(ValueError):
    """Base class for arithmetic that the money type refuses to perform."""


class CurrencyMismatchError(MoneyError):
    """Raised when two amounts in different currencies are combined or compared."""


class NegativeMoneyError(MoneyError):
    """Raised when an operation would produce a negative amount."""


class Money(BaseModel):
    """A non-negative amount in one currency.

    Non-negativity is enforced by the type rather than by the caller, so a
    balance can never become negative even if an authorization check is wrong:
    the subtraction raises instead of silently storing a debt.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    minor_units: MinorUnits
    currency: Currency

    @classmethod
    def of(cls, minor_units: int, currency: str) -> Self:
        """Build an amount from positional values."""
        return cls(minor_units=minor_units, currency=currency)

    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                f"cannot combine {self.currency} with {other.currency}"
            )

    def __add__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(minor_units=self.minor_units + other.minor_units, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same_currency(other)
        if other.minor_units > self.minor_units:
            raise NegativeMoneyError(
                f"cannot subtract {other.minor_units} from {self.minor_units} {self.currency}"
            )
        return Money(minor_units=self.minor_units - other.minor_units, currency=self.currency)

    def __lt__(self, other: Money) -> bool:
        self._same_currency(other)
        return self.minor_units < other.minor_units

    def __le__(self, other: Money) -> bool:
        self._same_currency(other)
        return self.minor_units <= other.minor_units

    def __gt__(self, other: Money) -> bool:
        self._same_currency(other)
        return self.minor_units > other.minor_units

    def __ge__(self, other: Money) -> bool:
        self._same_currency(other)
        return self.minor_units >= other.minor_units

    def __str__(self) -> str:
        return f"{self.minor_units} {self.currency}"
