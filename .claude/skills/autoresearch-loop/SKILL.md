---
name: autoresearch-loop
description: Run a self-driving research loop that makes the botmap CLI easier for an AI agent to drive. Use when asked to improve botmap's agent-usability, run an autoresearch loop, or optimise the CLI against the eval suite.
---

# Autoresearch loop

You are running a research loop on the `botmap` CLI. Your goal is to make the
tool **easier for an AI agent to drive** — not to make its answers more
correct.

The users of `botmap` are AI assistants, not people. An assistant is handed a
plain-English question ("how many hospitals are in Rhode Island?") and a shell,
and must work out the right command alone. Nobody tells it which command to
use. **Working that out is exactly what is being measured.**

There is no optimiser library here. You are the optimiser. Run the loop
yourself.

## The loop

```
measure  ->  read the evidence  ->  propose 2-3 candidates
   ^                                        |
   |                                        v
   +---- keep the winner  <----  verify each candidate
```

One pass through that is a **round**. Do rounds until a stop condition below
is met.

## Round procedure

### 1. Measure

The eval suite lives in `evals/`. A full run is 10 questions x 2 repeats = 20
`claude -p` invocations, which is slow and burns quota. **Do not run the full
suite to screen candidates.**

Full run (use for the baseline, and for a finalist only):

```bash
uv run python -m evals.runner --model sonnet --runs-dir evals/runs/<label>
uv run python -m evals.score  --runs-dir evals/runs/<label>
uv run python -m evals.synthesize --model opus --runs-dir evals/runs/<label>
```

Mini-batch (use for screening — see `autoresearch-verify`):

```bash
uv run python -m evals.runner --questions /tmp/minibatch.yaml --repeats 1 \
    --runs-dir evals/runs/<label>
uv run python -m evals.score --questions /tmp/minibatch.yaml --runs-dir evals/runs/<label>
```

Always give each measurement its own `--runs-dir`. Mixing runs silently
corrupts the score.

Record the baseline once, before changing anything. Every later number is read
against it.

### 2. Read the evidence

`evals/report.md` ranks failure clusters. `evals/proposals.json` lists concrete
findings. Read both. Also read the raw `record.json` under the runs dir when a
cluster is unclear — the actual commands the agent typed are the most useful
thing in this whole system.

What counts as a failure, worst first:

1. **Silent wrong answers** — the tool exits 0 and returns "0 rows", the agent
   reads that as "there are none here" and confidently reports a wrong answer.
   This is the worst failure mode in the system.
2. **Falling back to `download`** — when `download_is_legitimate: false`, the
   agent could not find the purpose-built command and reached for the bulk
   escape hatch.
3. **Errors it never recovered from** — the message failed to hand back a
   usable next command.
4. **Wasted turns** — many commands before the first correct one.

### 3. Propose

Invoke the `autoresearch-propose` skill. It returns 2-3 candidates. Do not
propose only one — a single candidate gives you nothing to compare.

### 4. Verify

Invoke the `autoresearch-verify` skill for each candidate. It screens on a
mini-batch, checks for reward hacking, and returns a verdict.

### 5. Keep the winner

Pick the candidate that **dominates** — better on the mini-batch without being
worse on any question the others handled. If none dominates, keep none and say
so; a tie is a real result, not a failure to decide.

Confirm the winner on the **full** suite before committing it. A mini-batch
gain that vanishes on the full suite was noise.

Commit each accepted winner separately, so every change stays attributable:

```bash
git add -A && git commit -m "Update. <what changed and which failure it targets>"
```

## Stop conditions

Stop and report when any of these is true:

- **Two consecutive rounds** produce no candidate that beats the baseline.
- You have run **six rounds**.
- The full-suite score has stopped moving by more than noise (one question
  flipping is noise; three is not).

## Keeping yourself honest

- **Never edit `evals/`.** That is the exam. Changing it makes every number
  meaningless. If you believe a question is wrong, say so in your report and
  leave it alone.
- **The baseline is measured once**, on unmodified code, and reused. Do not
  re-measure it to make a candidate look better.
- **Report what happened, including nothing.** "Six rounds, no reliable gain"
  is a valid and useful outcome. Do not manufacture an improvement.
- Two attempts at the same question will not behave identically. Treat a small
  gain as suspicion, not evidence.

## Final report

Write `AUTORESEARCH-REPORT.md` in the repo root:

- baseline numbers, and the numbers after each accepted change
- every candidate proposed, and why each was kept or dropped
- which failure clusters you closed and which you could not
- what you would try next, and what stopped you trying it now
