---
status: accepted
---

# Money is a non-negative integer count of minor units

The lab's central claim is that a reported pass rate means something. A refund oracle asserts an exact balance (`orders[0].refundable_minor == 3000`), so the arithmetic that produces that balance has to be exact and has to fail loudly rather than drift. Two decisions follow.

**Amounts are integer minor units plus an ISO 4217 alpha-3 currency.** Binary floating point cannot represent 0.10, so a sequence of partial refunds would diverge from the asserted balance by an amount that depends on the order of operations. `canonical_json` refuses floats outright, and a structural test (`tests/unit/test_domain_purity.py`) rejects float literals, float conversions, float annotations and true division anywhere under `src/maf_lab/domain/`.

**`Money` cannot hold a negative amount, and subtraction raises instead of producing one.** The invariant "a refundable balance can never become negative" is then enforced twice: the authorization check in `policy.py` denies an over-balance request, and `RefundState.commit_refund` performs the subtraction on `Money`, which raises `NegativeMoneyError` if the check was ever wrong or missing. A mutant that deletes the balance check therefore cannot silently store a debt; it produces a loud failure.

## Considered Options

- **`Decimal` with an explicit currency exponent.** Rejected: exact, but it reintroduces a value with more than one textual form (`20`, `20.0`, `2E+1`), which then has to be normalized before hashing anyway. Integers have exactly one form, and the domain never needs to divide.
- **Signed `Money`, with balance checks left to the caller.** Rejected: it makes a negative balance representable, so the only thing standing between a bug and a nonsensical committed state is the very check the mutant suite is designed to delete.
- **Storing balances as `Money` on `Order` rather than flat `refundable_minor` plus `currency`.** Rejected: scenario manifests select state by path (`orders[0].refundable_minor`), and a nested object would push a currency copy into every selector. `Order.refundable` exposes the `Money` view for arithmetic, so the type is still used where it matters.

## Consequences

- Any future need for a signed quantity (a ledger delta, a reporting variance) needs a separate type. `Money` is for amounts and balances, not differences.
- Subtraction can raise, so callers either check first or handle `NegativeMoneyError`. `commit_refund` translates it into `StateError`, which the gateway treats as a harness fault rather than a policy denial: reaching it means an authorization check is missing.
- Currency validation is syntactic (three uppercase letters). The lab only asserts *mismatch* between a request and an order, so a full ISO 4217 registry would add maintenance without adding an assertion.
