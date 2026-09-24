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
