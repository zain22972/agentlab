# Metric Card

Performance and reliability numbers are meaningless without the machine that produced them. This file names the machines and states which requirement is asserted where.

## Reference machine

Requirements **NFR-10** (p95 under 100 ms per tool event, excluding model and injected-fault latency) and **NFR-11** (aggregate reporting for 1,000 stored trials under 30 seconds) and acceptance **criterion 17** are asserted on this machine only:

| Property | Value |
|---|---|
| CPU | AMD Ryzen 7 5800HS |
| Cores / threads | 8 / 16 |
| Memory | 15.4 GB |
| Operating system | Windows |
| Python | 3.12 |
| Store profile | `memory` |

Re-measure and update this table before quoting either number. A result from any other machine is a different measurement, not a comparable one.

## CI runner

Requirement **NFR-01** (tiers T0 and T1 together under 5 minutes) and acceptance **criterion 14** are asserted on the two-core Linux CI runner, not on the reference machine. T1 executes the 15-scenario regression split at one trial each.

## Platform scope

| Guarantee | Asserted on |
|---|---|
| NFR-12 atomic artifact writes | Linux only |
| Section 9.4 crash acceptance scenarios | Linux only, `durable` store profile |
| NFR-10, NFR-11 latency and aggregation | Reference machine above |
| NFR-01 pipeline duration | Two-core Linux CI runner |

Windows is supported as a development convenience. It differs from Linux on `fsync` semantics, rename atomicity and file locking, so the durability guarantees are not claimed there.

## Retrieval metrics

Retrieval is an optional, cuttable adapter serving **untrusted knowledge articles only**. Trusted refund policy is read from typed fixtures and is never retrieved, so these metrics measure corpus quality, not agent correctness.

### Labeled retrieval set

| Property | Value |
|---|---|
| Location | `fixtures/knowledge-corpus/retrieval-labels-v1.json` |
| Unit | One query paired with the set of article identities judged relevant |
| Size | 40 labeled queries minimum, stratified across benign lookups and indirect-injection lures |
| Provenance | Hand-labeled, independently reviewed, versioned with the corpus |
| Split discipline | A query and its relevant articles never cross a scenario split, same rule as `family_id` |

Labels are versioned with the corpus. Re-embedding, re-indexing or editing an article is a new corpus version, never a silent mutation of an existing one.

### Reported measures

| Metric | Definition | Reported at |
|---|---|---|
| **Recall@k** | Fraction of relevant articles retrieved within the top `k`, for `k ∈ {1, 3, 5, 10}` | Per query, then macro-averaged over the labeled set |
| **MRR** | Mean reciprocal rank of the first relevant article | Macro-averaged over the labeled set |

Both carry the corpus version, embedding model identity, embedding dimension, index parameters and `k`. Because embeddings are precomputed and checked in, both are deterministic: identical inputs must reproduce identical values, and any drift is a corpus or index change, not noise.

### Embedding provenance

| Property | Value |
|---|---|
| Corpus artifact | `fixtures/knowledge-corpus/embeddings-v1.npy` |
| Array | float32, shape `(n_articles, 384)`, article order matching `articles-v1.jsonl` |
| Embedding model | `BAAI/bge-small-en-v1.5` via `fastembed==0.8.1`, CPU ONNX, no network |
| Dimension | 384 |
| Resolved revision | Recorded at generation time in the corpus manifest; treat as unset until the build script is first run |
| Generator | Committed build script; output checksummed with the rest of the corpus fixture |

Query embeddings MUST come from this same model, revision and dimension. A query embedded by any other model occupies a different vector space, so the comparison is invalid rather than approximate, and the suite fails closed on a fingerprint mismatch.

### Retrieval modes

| Mode | Query mechanism | Recall@k / MRR |
|---|---|---|
| `dense` | Pinned local ONNX model, offline | Reported |
| `sparse` | BM25 lexical over the same corpus | Reported, labeled `sparse` |
| `fixture` | Fixture stub returns declared articles | Not applicable, never zero |

Results are reported **per mode and never pooled across modes.** Hosted embedding APIs are not permitted in any tier, and cassette replay is not a valid live-tier mechanism because a live agent generates queries that were never recorded.

### Separation rule

Retrieval numbers are published **beside** reliability numbers and never merged into them.

- Recall@k and MRR MUST NOT contribute to session pass rate, `pass@k`, `pass^k`, state-oracle verdicts, or any security gate.
- A retrieval miss is a retrieval failure with its own reason code and owner. It never downgrades a critical state violation into a soft score, and it never excuses one.
- Good retrieval is not evidence of a true answer. A retrieved passage can be wrong, stale, poisoned or unauthorized and still be retrieved perfectly.
- Acceptance criteria 1 and 5 are independent of retrieval. Scenarios declaring `requires: [retrieval]` fall back to the fixture stub when Qdrant is cut, so the scenario count and the attack classification hold in every configuration; only these retrieval metrics drop out.

## Recording rule

Every published benchmark must carry its date, the exact provider and model identifier, decoding parameters, the store profile, the trial and scenario counts, and the numerator and denominator behind every rate. Cost figures are configurable caps and planning targets, never price quotes.
