---
name: autoresearch-propose
description: Read botmap's eval evidence and propose 2-3 competing candidate changes that would make the CLI easier for an AI agent to drive. Use from the autoresearch-loop skill, or when asked to propose botmap improvements from eval results.
---

# Propose candidates

Turn eval evidence into **2-3 competing candidate changes**. You propose only.
Implementing and testing belongs to `autoresearch-verify`.

## Inputs

- `evals/report.md` — ranked failure clusters
- `evals/proposals.json` — concrete findings
- `evals/runs/<label>/*/record.json` — the commands the agent actually typed

The `record.json` files matter most. A cluster name tells you *what* broke; the
commands tell you *what the agent was reaching for when it broke*. Design for
the reach, not the error.

## What you may change

The whole `botmap/` package is yours, plus `botmap/data/skill.md`.

These two are different levers and it is worth being deliberate about which
you pull:

| Lever | File | Changes |
|---|---|---|
| tool | `botmap/*.py` | what the CLI **does** |
| prompt | `botmap/data/skill.md` | what the agent is **told** |

Prefer the tool lever when the agent's reach was reasonable and the tool
refused it. Prefer the prompt lever when the tool already does the right thing
and the agent never found it. Say which lever each candidate pulls and why.

**Never touch `evals/`.** That is the exam.

`botmap/core.py` is data-access plumbing — a bad edit there breaks every
command at once. You may edit it, but a candidate that touches it must say
plainly why nothing shallower would do.

## What has worked before

- adding a purpose-built command for a common task, so the agent stops falling
  back to the bulk `download`
- error messages that name the problem **and** print a ready-to-run replacement
  command, so a wrong first try becomes a correct second try
- accepting the obvious spelling of an argument as well as the official one
- making a command that already exists cover more of the cases an agent will
  reasonably try it on

## What scores badly

- returning zero results with no explanation — the agent reads it as "there are
  none here" and reports a confident wrong answer
- crashing with a raw Python traceback
- being correct but so hard to discover the agent never finds it

## Rules for the candidate set

**Propose 2-3, and make them genuinely different.** Three variations on one
idea teach you nothing. Aim for different levers or different failure clusters,
so whichever wins tells you something.

Each candidate must state:

1. **Target** — which failure cluster, and how many eval questions it touches
2. **Lever** — tool or prompt, and why that one
3. **Change** — the specific edit, concretely enough to apply without guessing
4. **Prediction** — what should improve, and *what would prove it did not*
5. **Risk** — what else this could break

The prediction matters. A candidate with no falsifiable prediction cannot be
verified, only believed.

## Do not

- Do not special-case a specific eval question. Fixing `hospitals-rhode-island`
  by name is reward hacking, and `autoresearch-verify` is looking for it.
- Do not bundle unrelated fixes into one candidate. If it needs "and" to
  describe, it is two candidates.
- Do not propose a change you cannot measure with the existing eval suite.

## Output

Return the candidates as a numbered list with the five fields above. Do not
edit any files.
