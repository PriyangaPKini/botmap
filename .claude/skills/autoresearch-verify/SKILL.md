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

## 2. Screen on a mini-batch

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

## 3. Check for reward hacking

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

## 4. Verdict

Return one of:

- **dominant** — improved its target questions and regressed none
- **mixed** — improved some, regressed others; report both
- **no effect** — within noise
- **broken** — will not run, or regressed the target
- **rejected** — the sub-agent judged it reward hacking

Report the numbers, not an impression. One question flipping is noise; three
moving the same way is a signal.

## Cleaning up

Leave the branch in place — the loop decides what to keep. Return to the
starting point so the next candidate is measured from the same base:

```bash
git checkout -
```
