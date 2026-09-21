# Places Category Taxonomy Migration Implementation Plan

> **For agentic workers:** Use the incremental delivery workflow in sliced mode. Each task below is meant to be a small reviewable unit. Open one slice PR per task or per tightly related pair of tasks when the diff is still small.

**Goal:** Move botmap from Overture's old `categories.primary` place category field to `taxonomy.primary` and `basic_category`, while keeping the existing CLI shape stable for callers.

**Architecture:** Keep Click commands thin. Keep parsing and field validation in `botmap/filters.py`. Change no writer code and no output shapes.

**Tech Stack:** Python 3.10+, Click, PyArrow datasets and compute, pytest with `CliRunner`. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-20-places-category-taxonomy-migration.md`

**Follow-up:** `docs/superpowers/plans/2026-09-20-places-category-discovery-and-list-filters.md` continues with phases 3 to 6.

## Phase layout

| Phase | Tasks | Outcome |
|---|---|---|
| **1. Compatibility remap** | 1.1 to 1.3 | Existing `categories` and `--category` use `taxonomy.primary`. |
| **2. Basic category surface** | 2.1 to 2.3 | `basic-categories` and `--basic-category` work. |

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

# Delivered alongside the plan

Review and eval runs on the migration turned up work the tasks above did not
list. It shipped with the migration because each item is about the new fields
or the error interface:

- `count`, `sample`, `at` and `download` reject `--category` and
  `--basic-category` with the equivalent `--where` filter. An eval run showed
  agents reaching for `count --category`, which Click rejected with a bare
  "no such option".
- `basic-categories` names the type's verb for non-place types, as
  `categories` already did.
- The `download` verb suggestion desugars `taxonomy.primary=` to `--category`
  and `basic_category=` to `--basic-category`.
- The eval error classifier recognises `taxonomy.primary` zero-result hints.
- The Skill, README and SPEC describe the new fields, scope the category flags
  to `places`, and stop naming category values they cannot keep current.

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
