# Places Category Taxonomy CLI Redesign Implementation Plan

> **For agentic workers:** Use the incremental delivery workflow in sliced mode. Each task below is meant to be a small reviewable unit. Open one slice PR per task or per tightly related pair of tasks when the diff is still small.

**Goal:** Move botmap from Overture's old `categories.primary` place category field to the new taxonomy fields, while keeping the existing CLI shape stable for callers.

**Architecture:** Keep Click commands thin. Put category enumeration and zero-result hint logic in a new `botmap/category_taxonomy.py` module. Keep parsing and type validation in `botmap/filters.py`. Extend the existing `core.py` query path to support projected reads and post-scan list filters, without changing writer code or output shapes.

**Tech Stack:** Python 3.10+, Click, PyArrow datasets and compute, pytest with `CliRunner`. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-20-places-category-taxonomy-cli-redesign.md`

## Phase layout

| Phase | Tasks | Outcome |
|---|---|---|
| **1. Compatibility remap** | 1.1 to 1.3 | Existing `categories` and `--category` use `taxonomy.primary`. |
| **2. Basic category surface** | 2.1 to 2.3 | `basic-categories` and `--basic-category` work. |
| **3. Search and filter operators** | 3.1 to 3.3 | `~` works in `--where`, and enumeration commands support `--find`. |
| **4. List filters** | 4.1 to 4.3 | `contains` works for `taxonomy.hierarchy` and other list fields. |
| **5. Zero-result hints** | 5.1 to 5.3 | Zero-row category failures explain wrong fields and near matches. |
| **6. Docs and evals** | 6.1 to 6.4 | Skill, help text, README, SPEC, evals and performance notes match the new taxonomy. |

## Repository conventions

- **Run unit tests:** `uv run pytest tests/ -m "not integration" -v`
- **Run targeted tests:** `uv run pytest tests/<file>.py -v`
- **Run integration tests only when needed:** `uv run pytest tests/ -m integration -v`
- **stdout is data and stderr is for human messages.** Keep warnings and hints on stderr.
- **Commit format:** `<Operation>. <lowercase message>`, for example `Add. basic category command`.
- **PR shape:** Keep each task small. Prefer one slice PR per task unless two adjacent tasks share the same tests and implementation.

---

# Phase 1. Compatibility remap

End state: callers can keep using `categories` and `--category`, but both read `taxonomy.primary`.

## Task 1.1: Remap `places --category` to `taxonomy.primary`

**Files:**
- Modify: `botmap/cli.py`
- Modify: `tests/test_cli_*places*.py` or the nearest existing CLI test file

- [ ] Add or update a CLI test that asserts `places --category restaurant` builds a filter for `taxonomy.primary=restaurant`.
- [ ] Update the `places` command so `--category` appends `ParsedFilter(key="taxonomy.primary", op="=", value=category)`.
- [ ] Update the `places --help` text to say `--category` filters `taxonomy.primary`.
- [ ] Run the targeted CLI tests.
- [ ] Commit the task.

## Task 1.2: Remap the `categories` command to `taxonomy.primary`

**Files:**
- Modify: `botmap/cli.py`
- Modify: `tests/test_cli_categories.py`

- [ ] Update tests so `categories -t place` counts `taxonomy.primary` values instead of `categories.primary` values.
- [ ] Update the command docstring and help text to say it lists `taxonomy.primary` values.
- [ ] Change the command implementation to read `taxonomy.primary`.
- [ ] Keep the human and `--json` output shape unchanged.
- [ ] Run `uv run pytest tests/test_cli_categories.py -v`.
- [ ] Commit the task.

## Task 1.3: Report the successor for removed `categories.primary`

**Files:**
- Modify: `botmap/filters.py`
- Modify: `tests/test_filters.py`

- [ ] Add a test for `--where categories.primary=restaurant` against a schema that only has `taxonomy.primary`.
- [ ] Make the validation error name `taxonomy.primary` as the successor.
- [ ] Keep unknown-field errors for unrelated fields unchanged.
- [ ] Run `uv run pytest tests/test_filters.py -v`.
- [ ] Commit the task.

---

# Phase 2. Basic category surface

End state: users can enumerate and filter the coarse `basic_category` vocabulary.

## Task 2.1: Add `basic-categories`

**Files:**
- Modify: `botmap/cli.py`
- Create or modify: `tests/test_cli_basic_categories.py`

- [ ] Add tests for human output and `--json` output.
- [ ] Add the `basic-categories` command with the same location options as `categories`.
- [ ] Require `--bbox` or `--in`, and reject global enumeration.
- [ ] Count `basic_category` values and keep the same output shape as `categories`.
- [ ] Run the new targeted test file.
- [ ] Commit the task.

## Task 2.2: Add `places --basic-category`

**Files:**
- Modify: `botmap/cli.py`
- Modify: CLI tests for `places`

- [ ] Add a test that `places --basic-category restaurant` builds a `basic_category=restaurant` filter.
- [ ] Add the `--basic-category` option to `places`.
- [ ] Keep `--category` and `--basic-category` independent, and let both be used together if the user wants both filters.
- [ ] Update `places --help` text.
- [ ] Run the targeted CLI tests.
- [ ] Commit the task.

## Task 2.3: Update capabilities for the new category surface

**Files:**
- Modify: `botmap/cli.py`
- Modify: `tests/test_cli_capabilities.py`

- [ ] Add tests for `basic-categories` in the capabilities manifest.
- [ ] Add tests for `places --basic-category` in the command parameters.
- [ ] Update the manifest generation only if the existing walker does not pick up the new command and flag automatically.
- [ ] Run `uv run pytest tests/test_cli_capabilities.py -v`.
- [ ] Commit the task.

---

# Phase 3. Search and filter operators

End state: users can search category values with `--find`, and `~` works on commands that accept `--where`.

## Task 3.1: Parse `~` in `--where`

**Files:**
- Modify: `botmap/filters.py`
- Create or modify: `tests/test_filters_tilde.py`

- [ ] Add tests for `taxonomy.primary~vet` and `taxonomy.primary ~ vet`.
- [ ] Add a test that `~` is case-insensitive substring matching.
- [ ] Add a test that `~^vet` treats `^` as a literal character, not a regular expression.
- [ ] Add `~` to the parser without changing `ParsedFilter.to_pyarrow_expression`, since the translator already supports it.
- [ ] Run the tilde tests.
- [ ] Commit the task.

## Task 3.2: Improve unknown-operator errors

**Files:**
- Modify: `botmap/filters.py`
- Modify: `tests/test_filters.py`

- [ ] Add a test for `name like cafe`.
- [ ] Make the error name the unsupported operator and list the supported operators.
- [ ] Keep the existing shell-redirection hint for expressions that truly have no operator.
- [ ] Run `uv run pytest tests/test_filters.py -v`.
- [ ] Commit the task.

## Task 3.3: Add `--find` to enumeration commands and project columns

**Files:**
- Modify: `botmap/cli.py`
- Modify: `botmap/core.py`
- Modify: `tests/test_cli_categories.py`
- Modify: `tests/test_cli_basic_categories.py`

- [ ] Add tests that `categories --find vet` searches listed `taxonomy.primary` values.
- [ ] Add tests that `basic-categories --find restaurant` searches listed `basic_category` values.
- [ ] Add a test that `--find` is case-insensitive substring search, not semantic search.
- [ ] Add column projection support to the read path used by enumeration.
- [ ] Read only the category field needed by the enumeration command.
- [ ] Run category command tests.
- [ ] Commit the task.

---

# Phase 4. List filters

End state: `--where 'taxonomy.hierarchy contains restaurant'` works and list-field mistakes return clear errors.

## Task 4.1: Parse and validate `contains`

**Files:**
- Modify: `botmap/filters.py`
- Modify: `tests/test_filters.py`

- [ ] Add parser tests for `taxonomy.hierarchy contains restaurant`.
- [ ] Add a test that `contains [a,b]` is rejected because the value must be scalar.
- [ ] Add validation tests for these errors: using `contains` on a scalar field, using `~` on a list field, using `~` on a numeric field, and using `=` on a list field.
- [ ] Add list-aware schema validation.
- [ ] Run `uv run pytest tests/test_filters.py -v`.
- [ ] Commit the task.

## Task 4.2: Implement the list contains mask

**Files:**
- Modify: `botmap/filters.py`
- Create: `tests/test_filters_contains.py`

- [ ] Add tests for a list column with matching rows, non-matching rows, empty lists and nulls.
- [ ] Implement a pure helper that returns a row mask for list membership.
- [ ] Keep the helper independent from Click and from the CLI commands.
- [ ] Run `uv run pytest tests/test_filters_contains.py -v`.
- [ ] Commit the task.

## Task 4.3: Add post-scan filters to the core query path

**Files:**
- Modify: `botmap/core.py`
- Modify: `botmap/filters.py`
- Modify: tests for count, sample or download filters

- [ ] Change `filters.combine()` so it returns a pushdown expression and post-scan filters.
- [ ] Apply post-scan filters per batch in `record_batch_reader`.
- [ ] Make `count_rows` stream and sum when post-scan filters exist, since `dataset.count_rows(filter=...)` cannot apply list membership.
- [ ] Project the fields needed for post-scan filters.
- [ ] Add an end-to-end test for `taxonomy.hierarchy contains restaurant`.
- [ ] Run the targeted core and CLI tests.
- [ ] Commit the task.

---

# Phase 5. Zero-result hints

End state: a zero-row category query suggests the right field or near value, and the hint code is shared across commands.

## Task 5.1: Extract category enumeration and matching helpers

**Files:**
- Create: `botmap/category_taxonomy.py`
- Create or modify: tests for category taxonomy helpers

- [ ] Move the fuzzy category matching logic out of `cli.py`.
- [ ] Keep fuzzy matching for hints only. Do not use it to filter rows.
- [ ] Add helper tests for plural input, token overlap and typo matching.
- [ ] Add helper support for scanning both `taxonomy.primary` and `basic_category` in one pass.
- [ ] Commit the task.

## Task 5.2: Detect wrong category vocabulary on zero rows

**Files:**
- Modify: `botmap/category_taxonomy.py`
- Modify: hint tests

- [ ] Add a test for `basic_category=veterinarian` where rows exist with `taxonomy.primary=veterinarian` and `basic_category=animal_or_pet_service`.
- [ ] Return a certain wrong-field hint when the target value exists in the other vocabulary.
- [ ] Include the matching `basic_category` value when suggesting a replacement for a `taxonomy.primary` value.
- [ ] Keep fuzzy near-match hints for renamed or mistyped values.
- [ ] Commit the task.

## Task 5.3: Call zero-result hints from all relevant commands

**Files:**
- Modify: `botmap/cli.py`
- Modify: CLI tests for `places`, `count`, `sample` and `at`

- [ ] Replace the inline `places` hint with the shared helper.
- [ ] Call the helper from `count`, `sample` and `at` after a zero-row result.
- [ ] Fire the hint only for `place` queries with a category filter.
- [ ] Write hints to stderr, and keep JSON and data stdout clean.
- [ ] Reuse the resolved dataset and project only category columns on the miss path.
- [ ] Run the targeted CLI tests.
- [ ] Commit the task.

---

# Phase 6. Docs and evals

End state: the public docs, generated help and eval harness all use the new taxonomy.

## Task 6.1: Update the Skill and command help text

**Files:**
- Modify: `botmap/data/skill.md`
- Modify: `botmap/cli.py`
- Modify: help or capability tests if present

- [ ] Update the Skill troubleshooting section to use singular taxonomy values.
- [ ] Teach `taxonomy.primary`, `basic_category` and `taxonomy.hierarchy`.
- [ ] Document `contains` and `~`, and state that `~` is substring matching.
- [ ] Add the category-field guidance from the spec.
- [ ] Fix the `at --category pharmacy` example so it uses `--where taxonomy.primary=pharmacy`.
- [ ] Update command help text for `places`, `categories`, `basic-categories` and commands with `--where`.
- [ ] Document `--find` on `categories` and `basic-categories` as substring search over listed values.
- [ ] Commit the task.

## Task 6.2: Update README and SPEC

**Files:**
- Modify: `README.md`
- Modify: `SPEC.md`

- [ ] Replace old `categories.primary` examples with the new public surface where appropriate.
- [ ] Keep `--category` in user-facing examples when it is the friendlier form.
- [ ] Add examples for `basic-categories`, `--basic-category`, `--find`, `~` and `contains`.
- [ ] Make sure examples preserve stdout and stderr guidance.
- [ ] Commit the task.

## Task 6.3: Update evals and record before and after results

**Files:**
- Modify: `evals/questions.yaml`
- Modify: `evals/taxonomy.py`
- Modify: eval tests as needed
- Create or modify: an eval or performance notes file if the project already has one

- [ ] Update eval questions that encode `categories.primary`.
- [ ] Update error taxonomy labels that mention the old field.
- [ ] Run unit tests for eval modules.
- [ ] Run the eval bank before the docs and CLI changes, and save the baseline result.
- [ ] Run the eval bank after the docs and CLI changes, and save the result beside the baseline.
- [ ] Record the before and after numbers in the PR body or in a checked-in notes file.
- [ ] Record any intentional eval expectation change in the commit or PR body.
- [ ] Commit the task.

## Task 6.4: Measure the performance-sensitive changes

**Files:**
- Create or modify: a performance notes file if the project already has one
- Modify: PR body during delivery

- [ ] Measure `categories` before and after column projection on the same area and release.
- [ ] Measure the zero-result hint miss path before and after reusing the resolved dataset and projecting category columns.
- [ ] Measure `count` with and without a zero-result category hint, because `count` is the cheapest command and the Skill tells agents to run it first.
- [ ] Use the same release, area and command shape for each before and after pair.
- [ ] Record the commands, timings and environment in the PR body or in a checked-in notes file.
- [ ] Commit the notes only if they are useful to future readers. Otherwise, keep the numbers in the PR body.

---

# Final validation

Run these before opening the aggregate PR:

```bash
uv run pytest tests/ -m "not integration" -v
botmap --help
botmap places --help
botmap categories --help
botmap basic-categories --help
```

If network access is available, also run one small smoke query against a recent release that has `taxonomy.primary` and `basic_category`.
