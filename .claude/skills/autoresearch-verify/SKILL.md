---
name: autoresearch-verify
description: Implement a proposed botmap candidate, screen it on a mini-batch of eval questions, and check it for reward hacking with an independent sub-agent. Use from the autoresearch-loop skill, or when asked to test whether a proposed change actually improves agent usability.
---

# Verify a candidate

Take one proposed candidate, implement it, and find out whether it actually
helps. Assume it does not until the numbers say otherwise.

## 1. Implement on a branch

```bash
git checkout -b cand/<short-slug>
```

Apply only what the candidate described. If you find yourself fixing something
else along the way, stop — that is a separate candidate, and mixing them makes
the result unattributable.

Confirm the tool still starts before spending anything on it:

```bash
uv run botmap --help >/dev/null && echo "starts"
```

A candidate that will not run scores zero. Do not evaluate it; report the
error and stop.

**Then confirm the candidate is not empty.** `git commit` exits 0 and prints
"nothing to commit" when a change was stashed, reverted, or never applied. An
empty branch screens as "no effect" -- a plausible result -- and gets recorded
as a tested negative for a change that never existed:

```bash
git diff --quiet arm-a-base <branch> && echo "EMPTY CANDIDATE -- do not measure"
```

Never measure an empty candidate.

## 2. Check the mechanism first -- it is free

Before spending any quota, prove the change does what it claims, directly
against the CLI with no agent involved. This costs nothing, has no noise, and
discards a broken candidate before it consumes a single run.

State the check as a before/after on real commands, e.g.:

```bash
# the case the candidate targets
botmap --json count -t place --in "Brooklyn, US-NY" --where categories.primary=bus_stop
#   expect: exit 0, count 0, AND a stderr hint naming a near match

# a control that must NOT change
botmap --json count -t place --in "Brooklyn, US-NY" --where categories.primary=coffee_shop
#   expect: 1253, no hint
```

Where a candidate adds sugar for an existing option, **check equivalence**: the
shortcut must return exactly what the longhand returns. A shortcut wired to the
wrong column returns a silent zero, which is the worst failure in the system.

A candidate whose mechanism fails here is dead. Do not measure it.

## 3. Screen on a mini-batch

Running all 10 questions x 2 repeats to screen a candidate is wasteful. Build a
mini-batch instead.

**Choosing the mini-batch matters.** It must contain:

- every question in the failure cluster this candidate targets (or it cannot
  show a gain), **and**
- at least two questions the candidate should *not* affect (or it cannot show a
  regression).

Use the **same mini-batch for every candidate in a round.** Comparing
candidates screened on different questions is meaningless.

```bash
# extract the chosen ids into a subset bank
uv run python - <<'PY'
import yaml, pathlib
ids = {"coffee-brooklyn-count", "where-boston"}   # <- the round's mini-batch
bank = yaml.safe_load(pathlib.Path("evals/questions.yaml").read_text())
subset = [q for q in bank if q["id"] in ids]
pathlib.Path("/tmp/minibatch.yaml").write_text(yaml.safe_dump(subset, sort_keys=False))
print(f"{len(subset)} questions")
PY

uv run python -m evals.runner --questions /tmp/minibatch.yaml --repeats 1 \
    --runs-dir evals/runs/cand-<slug>
uv run python -m evals.score --questions /tmp/minibatch.yaml \
    --runs-dir evals/runs/cand-<slug>
```

Read the result against the baseline's numbers **on the same questions** — not
against the baseline's full-suite score.

## 4. Check for reward hacking

Before accepting any candidate that improved, **launch an independent
sub-agent** to inspect it. Give the sub-agent the diff and the eval questions,
and ask it to answer one question:

> Does this change genuinely make the CLI easier for any agent to drive, or
> does it improve the score by exploiting the specific questions in the eval
> suite? Default to "exploiting" if uncertain.

Tell it to look for:

- **question-shaped logic** — place names, categories, or values from the eval
  bank appearing in the code
- **detecting the harness** — behaviour that changes under the eval shim, or
  when a specific env var is set
- **widening what counts as success** — suppressing an error, or returning
  something plausible where the tool used to admit it did not know
- **help text tuned to the exam** — examples that happen to be the eval
  questions rather than representative usage

The sub-agent must be given the diff and must reach its own verdict. Do not
tell it your prediction, or which cluster you were targeting — you would be
handing it the answer.

A candidate the sub-agent calls exploitative is **rejected**, even if it
scored well. Record it in the report: a rejected reward hack is a finding
worth keeping.

## 5. Verdict

### Do NOT judge on `cli_error_count`

`evals/taxonomy.py` classifies an exit-0 call carrying "did you mean:" as
`bad_category_value` -- an error. So a candidate that adds a diagnostic to a
previously-silent zero result converts a call the scorer called **clean** into
a call the scorer calls an **error**.

The tool gets better; the number gets worse. A candidate that fixes a silent
failure is guaranteed to look like a regression on error count. Judging on that
metric rejects the correct fix, and an optimiser following it learns to delete
diagnostics.

The same trap applies to `wasted_commands`, which is derived from the error
count.

### Judge on this instead, in order

1. **The mechanism check** (step 2). Deterministic, free, no noise. This is the
   primary evidence that the candidate works.
2. **Regression on stable questions.** Some questions have *identical* mean
   command counts across independent baselines. A change there is real signal.
   Establish which ones are stable by comparing two baselines before trusting
   any of them as detectors.
3. **Recovery and outcome.** Did the agent reach an answer, and in how many
   commands? An error followed by a corrected retry is the tool working. An
   error followed by silence and a confident wrong answer is the failure. These
   score the same today, which is why you read the trace and not the total.
4. **The trace on the target question.** Did the agent actually encounter the
   new affordance? A mechanism that works but is never reached is a failed
   candidate -- and honest evidence the fix is in the wrong place.

### Know your noise floor before calling anything a win

Measure it: run the baseline twice, unchanged, and count what moves. On
botmap's 10-question suite this was **3 of 10 questions flipping outcome with
the tool held constant**, while the aggregate barely moved (18/20 -> 17/20)
because the flips cancelled.

Do not use a rule of thumb here. An earlier version of this file said "one
question flipping is noise; three moving the same way is a signal" -- that was
written from intuition and the measurement contradicts it.

If every question with headroom is also unstable, and every stable question is
already at ceiling, then **the suite cannot demonstrate an improvement at all**
and you should say so rather than report a number from it.

### Verdicts

- **mechanism-verified** -- the change provably does what it claims (step 2).
  This stands on its own and needs no quota.
- **dominant** -- mechanism verified AND the agent demonstrably recovers where
  it previously did not, with no regression on stable questions.
- **mixed** -- improved some, regressed others; report both, with the noise
  floor beside them.
- **no effect** -- the mechanism works but the agent never reaches it. Say
  where the fix would have to live instead.
- **broken** -- will not run, empty branch, or the mechanism check failed.
- **rejected** -- the sub-agent judged it reward hacking.
- **unproven** -- any movement smaller than the measured noise floor. This is
  the honest verdict for most small gains and should be used freely.

Report the numbers, and report the floor next to them. A gain quoted without
its noise floor is not a result.

## Cleaning up

Leave the branch in place — the loop decides what to keep. Return to the
starting point so the next candidate is measured from the same base:

```bash
git checkout -
```
