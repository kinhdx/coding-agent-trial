# 0002: Tasks come from real fixes, graded by the tests written for them

## Context

Public coding benchmarks say little about how an agent does on your own services: their repositories,
conventions and failure modes are someone else's, and their tasks may be in the model's training data. A
trial that decides whether a harness is allowed near internal code should run on that code.

## Decision

Each task is one bug fixed in the history of the three service repositories this trial targets. A task file
records the commit before the fix (`base`), the fix commit (`fix`), a bug report written the way a user or a
reviewer would raise it, and the tests the fix added, which become the hidden tests.

- The agent works on the tree of `base` in a fresh one-commit repository, so the fix cannot be read from git
  history.
- Grading happens in a new container with no network: apply the agent's diff to `base`, restore `tests/` from
  `base` so the agent cannot change the yardstick, add the hidden tests, run them and then the original suite.
- A run is resolved when the diff applies, every hidden test passes and the original suite still passes. Files
  changed outside `src/`, `tests/`, `policy/` and the docs are listed as out-of-scope edits.
- `trial validate` checks every task before a trial: the hidden tests must fail at `base` and pass with the
  real fix applied.

## Consequences

- The numbers describe these repositories and these bug types: input parsing, redaction rules, validation of
  a catalogue. They do not predict results on a large legacy codebase.
- Fifteen tasks with two or three attempts each is enough to separate a harness that fails often from one
  that does not, and too few to rank two harnesses that differ by a task or two.
- The first eleven bug reports name the behaviour to change. The other four describe only what a user sees
  (applicants aged 58 or 59 always sent to review, a review queue that holds incomplete dossiers, a 500
  during a provider outage, a traceback from one bad manifest), and one needs changes in two modules. Their fixes were written for this trial
  in October 2026, after the first eleven had run, so they test cause-finding on a realistic report rather
  than recall of a historical commit.
- Several tasks share a fix commit, so their bug reports are written to describe one symptom each. An agent
  that fixes more than it was asked still passes, and the scope list shows what else it touched.
- Hidden tests can be stricter than the bug report. A run that fixes the reported symptom in a different way
  can fail a hidden test that pins the original implementation's behaviour; such runs are read by hand before
  they count against a harness.
