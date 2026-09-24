---
status: accepted
---

# Trial and Experiment replace Run

The word "run" was doing three jobs in the original specification: one execution of one scenario (`run_id`), a scheduled set of executions (`maf-lab run --trials 3`), and a whole live campaign ("live runs require a cost cap"). Because this project's central claim is statistical — that a pass rate, a `pass^k` and a confidence interval mean something — a noun that silently covers both "one execution" and "thousands of executions" corrupts the one thing the lab exists to report. We therefore define **Trial** as one execution of one scenario and **Experiment** as a scheduled set of trials, and retire "run" as a noun entirely, keeping it only as the command-line verb.

## Considered Options

- **Keep `run` as the single execution unit**, matching LangSmith, Langfuse and MAF itself. Rejected: it reads naturally in isolation but forces a qualifier ("a single run", "the whole run") at exactly the points where precision matters most, and the qualifier is what gets dropped in a report.
- **Keep `run` for the execution and introduce only `Experiment` above it.** Rejected: it fixes the aggregate ambiguity but leaves "live runs" and `maf-lab run` still colliding with `run_id`.

## Consequences

- Any future import/export bridge to LangSmith or Langfuse must translate at the boundary, since those tools call a trial a "run". This is a deliberate cost: the translation is explicit and testable, whereas a shared word would let two different meanings pass silently.
- The rename touches the artifact schema, the event type names and the HTTP surface (`/v1/trials/*`). It was applied before any code existed, which is the only cheap moment to do it.
- Newcomers fluent in other evaluation tools will reach for "run" by habit. `CONTEXT.md` records it under `_Avoid_` so reviews can catch it.
