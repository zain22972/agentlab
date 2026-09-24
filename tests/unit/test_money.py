"""Unit tests for monetary values: integer minor units plus an ISO currency."""

import operator

import pytest
from pydantic import ValidationError

from maf_lab.domain.money import CurrencyMismatchError, Money, NegativeMoneyError


def test_money_is_integer_minor_units_and_currency() -> None:
    money = Money(minor_units=5000, currency="USD")
    assert money.minor_units == 5000
    assert money.currency == "USD"


def test_money_is_frozen() -> None:
    money = Money(minor_units=5000, currency="USD")
    with pytest.raises(ValidationError):
        money.minor_units = 1


def test_money_rejects_non_integer_amounts() -> None:
    with pytest.raises(ValidationError):
        Money(minor_units=20.5, currency="USD")  # type: ignore[arg-type]


def test_money_rejects_negative_amounts() -> None:
    with pytest.raises(ValidationError):
        Money(minor_units=-1, currency="USD")


def test_money_rejects_malformed_currency() -> None:
    for bad in ["usd", "US", "USDD", "US1", ""]:
        with pytest.raises(ValidationError):
            Money(minor_units=100, currency=bad)


def test_money_adds_within_one_currency() -> None:
    total = Money(minor_units=2000, currency="USD") + Money(minor_units=500, currency="USD")
    assert total == Money(minor_units=2500, currency="USD")


def test_money_subtracts_within_one_currency() -> None:
    remaining = Money(minor_units=5000, currency="USD") - Money(minor_units=2000, currency="USD")
    assert remaining == Money(minor_units=3000, currency="USD")


def test_money_subtraction_never_yields_a_negative_balance() -> None:
    with pytest.raises(NegativeMoneyError):
        Money(minor_units=1000, currency="USD") - Money(minor_units=1001, currency="USD")


def test_money_rejects_cross_currency_arithmetic() -> None:
    usd = Money(minor_units=1000, currency="USD")
    eur = Money(minor_units=1000, currency="EUR")
    for operation in (operator.add, operator.sub, operator.lt, operator.ge):
        with pytest.raises(CurrencyMismatchError):
            operation(usd, eur)


def test_money_compares_within_one_currency() -> None:
    small = Money(minor_units=1000, currency="USD")
    large = Money(minor_units=2000, currency="USD")
    assert small < large
    assert small <= large
    assert large > small
    assert large >= small
    assert small != large
    assert small == Money(minor_units=1000, currency="USD")


def test_money_of_helper_matches_constructor() -> None:
    assert Money.of(1000, "USD") == Money(minor_units=1000, currency="USD")


def test_money_is_hashable() -> None:
    assert len({Money.of(1000, "USD"), Money.of(1000, "USD"), Money.of(1000, "EUR")}) == 2
