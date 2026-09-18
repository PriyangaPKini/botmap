# botmap — Places Taxonomy Migration Research

**Date:** 2026-08-13
**Status:** Research — no implementation
**Targets:** Overture September 2026 release
**Branch:** `feat/taxonomies`

---

## 1. Problem

Overture is replacing the `categories` property on `place` with two new
properties, `basic_category` and `taxonomy`. Per
<https://docs.overturemaps.org/guides/places/#category-taxonomy>:

| Event | Release |
|---|---|
| `basic_category` introduced | October 2025 |
| `taxonomy` introduced | December 2025 |
| `categories` **removed** | **September 2026** |

Overture's own change summary: L0 top-level cut from 22 → 13; 209 categories
added; 80 removed; 407 renamed (mostly plural → singular); 482 reparented;
2,108 repathed; every place mapped to ~280 basic labels.

botmap is built on `categories.primary`. It is the `--category` flag, the
`categories` command, the zero-result "Did you mean" hint, the capabilities
reverse-map, and the vocabulary taught by the Skill. When September lands:

1. Every `--category` query silently matches nothing — the field is gone, so
   filters return zero rows rather than erroring.
2. The `categories` command enumerates a column that no longer exists.
3. The Skill teaches a vocabulary the data no longer has.

All three properties coexist until September, so there is a real transition
window — but only one release of it.

## 2. Goals

- **Expose the new taxonomy** — `basic_category`, `taxonomy.primary`, and
  `taxonomy.hierarchy` become queryable and enumerable.
- **Support hierarchy roll-up.** Aggregating POIs by supertype (all
  `food_and_drink`, regardless of leaf) is the capability the new schema exists
  to provide and the one `categories` never had.
- **Land the additive work before September**, so the breaking migration is a
  small, well-understood change rather than an emergency.
- **Mark `categories` as deprecated** A retired vocabulary must not degrade into silent
  zero-row answers; the failure path has to say what happened.

## 3. Non-Goals
- **No global enumeration.** "List every category" is not answerable without
  scanning a whole release. Every taxonomy verb is area-scoped (`--in` /
  `--bbox`), like `categories` today.
- **No old→new migration lookup.** Renames, removals, and redirects are not
  carried in the parquet, so botmap cannot tell a caller that a retired value
  has a successor.

## 4. Sample shape of Record

```json
{
    ...,
    "basic_category": "restaurant",
    "taxonomy": {
      "primary": "doner_kebab_restaurant",
      "hierarchy": ["food_and_drink","restaurant","middle_eastern_restaurant",
                            "turkish_restaurant","doner_kebab_restaurant"],
      "alternates": null}
}

```

## 5. Affected Surface

### 5.1 CLI (`botmap/cli.py`)

| Line | Surface | Issue |
|---|---|---|
| 1089-1090 | `places --category` | Shortcut for `--where categories.primary=VAL`; needs a taxonomy-aware equivalent |
| 969-1010 | `categories` command | Enumerates `categories.primary`; needs `basic_category` / `taxonomy.primary` counterparts |
| 97-149 | `_suggest_categories` | Scans the `categories` column for the "Did you mean" hint |
| 1140-1165 | zero-result hint | Keys off `categories.primary` filters |
| 332-333 | `explain` / capabilities reverse-map | Rewrites `categories.primary=` back to `--category` |
| 533, 538 | bus-stop hints | Suggest `--category bus_stop` |
| 1454 | `at --where` help | Example uses `categories.primary=coffee_shop` |

### 5.2 Docs, Skill, and tests

`botmap/data/skill.md` (18 mentions), `README.md` (41), `SPEC.md`,
`botmap/introspection.py` (type description, schema docstring), and the tests:
`test_cli_categories.py`, `test_cli_intents_places.py`, `test_filters.py`,
`test_cli_schema.py`, `test_cli_capabilities.py`, `test_introspection.py`.

The eval banks also encode `categories.primary` in questions and expectations;
without updating them the migration will read as a regression.

### 5.3 Defect: list-typed fields crash `--where`

`taxonomy.hierarchy` is `list<string>`. The filter layer walks dotted paths
into structs (`filters.py:25-74`) but has no list handling, so a hierarchy
filter **builds successfully and then crashes at execution**:

```
taxonomy.primary=cafe               -> 1 row
taxonomy.hierarchy=food_and_drink   -> ArrowNotImplementedError:
    Function 'equal' has no kernel matching input types (list<item: string>, string)
```

A raw PyArrow traceback reaches the user. `categories.alternate` and
`taxonomy.alternates` have the identical defect today — pre-existing, not
introduced by the migration.

Add support for a `contains` op for `--where`.

## 6. Proposed CLI Surface

Sketch, not a commitment. Every verb is area-scoped, mirroring `categories`:

- `taxonomies -t place --in "…"` — distinct `taxonomy.primary` with counts
- `taxonomies … --where` — accepts the same filters as the extraction verbs, so
  an enumeration can be scoped to a branch of the tree. `categories` has no
  `--where` today; without it a breakdown cannot be narrowed to a subject area
  and returns every value in the bbox, restaurants and dental clinics alike.

  ```bash
  # "Break Luxembourg's food scene down by cuisine"
  botmap taxonomies -t place --in "Luxembourg" \
    --where 'taxonomy.hierarchy contains restaurant' --top 10
  ```
  ```
    70  restaurant                  9  sushi_restaurant     4  indian_restaurant
    22  italian_restaurant          7  chinese_restaurant   4  asian_restaurant
    14  french_restaurant           5  greek_restaurant     4  thai_restaurant
    ... 35 distinct leaves
  ```

  Note the shape of the answer: leaves are fragmented (`italian_`, `french_`,
  and `greek_restaurant` are three rows that are all European) and the 70 bare
  `restaurant` rows carry no cuisine at all. Grouping at an intermediate
  hierarchy level — which would yield `european_restaurant 44`,
  `asian_restaurant 32`, `middle_eastern_restaurant 8` — needs a `--level`
  flag, deliberately out of scope. Callers wanting that shape aggregate the
  `hierarchy` arrays themselves.
- `taxonomies show <category> --in "…"` — hierarchy path for a value as it
  appears in that area, plus its `basic_category`
- `basic-categories -t place --in "…"` — distinct `basic_category` with counts
- Deprecate `categories` command and `--category` flag and switch to `taxonomies` and `--taxonomy`
  - Emit to stderr: Always stream deprecation alerts to standard error so you do not break downstream pipelines and text parsing on stdout.
  - State the alternative: Clearly name the new command, flag, or workflow that users should switch to.
  - Flag the help menus: Prepend [DEPRECATED] to the command's listing in  --help documentation.
  - Log in changelogs: Document the deprecation window explicitly in the project release notes.
- Support `basic-categories` as a new command
- Post-migration, zero-result hint which re-scans the bbox for near-miss `categories.primary` values should
  suggest from `taxonomy.primary` / `basic_category`, and ideally recognise a
  retired value rather than reporting an empty area.
- New module will be named `botmap/category_taxonomy.py`

## 7. Migration Plan

1. Fix the list-filter defect (§5.3) — independent, ships on its own, unblocks
   hierarchy work.
2. Build read-only `taxonomies` / `basic-categories` commands over the parquet.
3. Add `--basic-category` / `--taxonomy` filters to `places` and `at`.
4. Add deprecation warnings to `--category`, the `categories` command and migrate hints, Skill, docs, and eval
   banks.
5. Re-run the eval before and after step 4 to catch regressions.
