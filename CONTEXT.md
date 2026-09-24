# Agent Reliability Lab

A laboratory for measuring whether a Microsoft Agent Framework agent behaves correctly under repetition, adversarial input, and infrastructure faults. Correctness is judged from simulated state and authorization history, not from how convincing the agent's prose is.

## Language

### Execution units

**Trial**:
One execution of one scenario against a freshly created state instance.
_Avoid_: Run, attempt, sample

**Experiment**:
A scheduled set of trials spanning scenarios and agent configurations, compared as a whole.
_Avoid_: Run, batch, campaign, benchmark

> "Run" is deliberately retired as a noun. It survives only as the command-line verb (`maf-lab run`). Industry tools use "run" for both of the above concepts; this project does not, because a single word covering both hides whether a number describes one execution or thousands.

### Scenario vocabulary

**Scenario**:
One versioned declaration of a single situation the agent is placed in, carrying exactly one scenario identity.
_Avoid_: Test case, manifest, fixture

**Scenario Family**:
A group of scenarios sharing a template or an attack paraphrase. A family never crosses a split.
_Avoid_: Group, cluster, variant set

**Scenario Manifest**:
The YAML file that declares exactly one scenario. "Manifest" names the file and only the file; calling a Scenario a manifest is what the entry above rules out, because a scenario has one identity whether or not it is on disk.
_Avoid_: Config, spec, definition file

### Domain vocabulary

**Trusted core**:
The refund domain as it exists with no model, no agent framework and no harness loaded: entities, authorization rules, per-trial state and the tool gateway. Its purity is enforced structurally, not by convention.
_Avoid_: Business logic, backend, service layer

**Canonical state**:
The customers, orders, refunds and messages of one trial, as the state instance holds them. Correctness is judged against this, never against the agent's prose. Its serialization is canonical in the literal sense: one payload, one byte sequence, one hash.
_Avoid_: Database, world state, environment

**Principal**:
The authenticated identity a trial's tool calls run as, established by the declared initial state and never by model output.
_Avoid_: User, caller, session

**Authorization decision**:
The allow-or-deny outcome of one tool request, computed from typed state and carrying a stable reason code. Reproducible from evidence without replaying a model.
_Avoid_: Guardrail, validation, permission check

**Typed result union**:
The closed set of outcomes a tool may return (`Success`, `InvalidRequest`, `NotFound`, `PolicyDenied`, `TransientFailure`, `UnknownOutcome`, `IdempotencyConflict`), discriminated by `outcome`. A tool never returns a bare exception or free-form string.
_Avoid_: Response, error, status code

**Audit event**:
One append-only record of an attempted state change, carrying a monotonic sequence, the actor, the action, before and after state hashes, the authorization decision and the idempotency key. Denied and malformed attempts are recorded too, with equal hashes, so "nothing changed" is evidence rather than absence of evidence.
_Avoid_: Log line, trace, history entry
