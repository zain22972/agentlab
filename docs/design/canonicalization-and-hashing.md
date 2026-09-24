# Canonicalization and hashing: domain state vs. artifacts

**Status:** proposal for review before tickets #3 (evidence harness / hashing) and #7 (manifest validator) land. Nothing in `src/maf_lab/domain/` changes as a result of this document.

## The problem

`maf_lab.domain.canonical.canonical_json` refuses floating point outright (`_reject_floats` raises `TypeError`). ADR 0002 explains why: a hash that depends on a platform's float `repr` is not a hash we can compare across machines, and money is the thing the domain hashes, so money is integer minor units and floats simply never occur.

But two things the lab must also hash *do* legitimately contain floats:

- **Scenario manifests (§10)** carry `max_cost_usd: 0.25` under `limits`, and response-assertion `threshold` values (e.g. `1.0`).
- **Normalized records (§11)** carry `parameters.temperature: 0.2` and `usage.estimated_cost_usd: 0.0042` in the trial record (§11.1), and `score`, `threshold`, `estimate`, `ci_low`, `ci_high` in the evaluation result and aggregate (§11.3, §11.5).

The manifest hash (`manifest_sha256`) and the record digests are load-bearing: repeatability (§2.3 point 1) rests on "immutable scenario/config hashes", and §22.2 requires "Configured secrets never appear in serialized artifacts" and "Event canonicalization is idempotent" as properties over exactly these artifacts.

So the domain canonicalizer, as written, cannot hash a manifest or a trial record. That is not a bug in the domain canonicalizer. It is a sign that two different jobs are being asked of one function.

## The two jobs are genuinely different

| | Domain state hashing | Artifact hashing |
|---|---|---|
| What it covers | Canonical state: customers, orders, refunds, messages | Manifests, trial records, event envelopes, evaluation results, aggregates |
| Floats present? | Never, by construction (ADR 0002) | Yes, and legitimately (cost, temperature, score, CI bounds) |
| Failure mode it must prevent | A balance drifting so an oracle mis-asserts | Two byte-different serializations of the same record hashing differently |
| Who produces the values | The domain itself, under our control | Config authors, providers, the statistics engine |

The domain hash's guarantee is *"no float ever entered this number"*. The artifact hash's guarantee is *"this float serializes to one canonical byte sequence"*. Collapsing them would force the domain hash to tolerate floats, which throws away the very property `tests/unit/test_domain_purity.py` and ADR 0002 exist to protect.

## Options considered

### Option A — Separate artifact canonicalizer (recommended)

Add a second module — `maf_lab.evidence.canonical` (or `maf_lab.schemas.canonical`), owned by ticket #3 — that canonicalizes artifacts *including* floats, and leave `maf_lab.domain.canonical` exactly as it is.

The artifact canonicalizer reuses the same rules the domain one already fixes — sorted keys, `(",", ":")` separators, `ensure_ascii=False`, UTC `Z` datetimes, enum-by-value — and adds one rule the domain one deliberately refuses: **a canonical float encoding**. The candidate encoding is:

- Reject non-finite values (`NaN`, `±Inf`) — already the case via `allow_nan=False`.
- Encode via `repr(float)`, which on every CPython ≥ 3.1 is the shortest round-tripping decimal string (David Gay / Grisu). This is stable across platforms for IEEE-754 doubles, so `0.2` is always `"0.2"`, never `"0.20000000000000001"`.
- Decide `-0.0` vs `0.0` explicitly (normalize `-0.0` to `0.0`).

Money in artifacts stays integer minor units; the float path is only for cost, temperature, score, threshold and CI bounds, none of which are money.

**Why this is the recommendation.** It keeps the domain guarantee absolute (the purity test still passes, ADR 0002 stays literally true), it puts float-handling in the layer that actually owns provider-supplied and statistics-supplied numbers, and it matches the module boundary the spec already draws — §7.1 lists the evidence recorder and the manifest validator as separate components from the state store. The two canonicalizers share a small private helper for the non-float rules so they cannot drift.

**Cost.** Two canonicalizers to keep aligned. Mitigated by the shared helper and by a contract test asserting they agree on any float-free payload.

### Option B — One canonicalizer, floats allowed, domain purity enforced elsewhere

Relax `canonical_json` to encode floats, and keep floats out of the domain by relying only on the AST purity test rather than on a runtime `TypeError`.

**Rejected.** It removes the runtime tripwire that catches a float the moment it reaches the state hash, leaving only a structural test that a future refactor could weaken or a dynamically-typed value could slip past. ADR 0002's "refuses floats outright" would become false, and the guarantee would degrade from "cannot happen" to "we test that it doesn't".

### Option C — Schema change: represent every artifact float as scaled integers or decimal strings

Make `max_cost_usd` an integer count of micro-dollars, `temperature` a string, `score`/`ci_low`/`ci_high` fixed-point integers, so the existing float-rejecting canonicalizer covers everything.

**Rejected as the general answer, with one carve-out.** Author-facing YAML with `max_cost_usd: "250000"` (micro-dollars) is hostile, and provider `temperature` and statistical CI bounds are floats in every upstream and downstream tool we interoperate with (§11 explicitly types `score`, `estimate`, `ci_low`, `ci_high` as `float`). Forcing them into strings buys canonicalization we can get more cheaply in Option A and creates a translation boundary at every provider and report edge.

*The carve-out:* **cost is money and should be scaled-integer regardless.** `estimated_cost_usd: 0.0042` is a monetary quantity, and ADR 0002's argument against binary floats applies to it as much as to a refund. Independently of which canonicalizer wins, tickets #3/#8 should consider representing cost as integer micro-dollars (`estimated_cost_micros`) so cost aggregation is exact. That is a schema question for those tickets, not a canonicalization question, and it shrinks — but does not eliminate — the set of artifact floats (`temperature`, `score`, `threshold`, `estimate`, `ci_low`, `ci_high` remain).

## Recommendation

Adopt **Option A**: a separate artifact canonicalizer under the evidence/schema layer, sharing the non-float rules with the domain canonicalizer, adding a documented canonical float encoding based on `repr`. Independently, flag cost for a scaled-integer schema (part of C's carve-out) to tickets #3/#8. Record the split as an ADR when #3 implements it.

## Test obligations this creates for #3 / #7

- Idempotency: `artifact_canonical(parse(artifact_canonical(x))) == artifact_canonical(x)` (satisfies the §22.2 "event canonicalization is idempotent" property for records that contain floats).
- Cross-platform float stability: a fixed table of doubles (`0.1`, `0.2`, `0.0042`, `1.0`, `-0.0`) encodes to a fixed table of strings.
- Agreement: the two canonicalizers produce identical bytes for any float-free payload.
- The domain canonicalizer still raises on floats (existing test stays green, unchanged).
