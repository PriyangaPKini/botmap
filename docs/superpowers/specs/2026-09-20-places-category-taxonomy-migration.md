# botmap — Places Category Taxonomy Migration

**Date:** 2026-09-20
**Status:** Proposed
**Plan:** `docs/superpowers/plans/2026-09-20-places-category-taxonomy-migration.md`
**Follow-up:** `docs/superpowers/specs/2026-09-20-places-category-discovery-and-list-filters.md`

Value counts and churn figures come from Overture's taxonomy sheet, "Place
Categories + Basic Categories", February 2026. Measurements and examples come
from release `2026-08-19.0`.

---

## 1. Problem

Overture replaces the flat `categories` property on `place` with three fields
and removes `categories` in the September 2026 release.

| Field | Type | Holds |
|---|---|---|
| `taxonomy.primary` | string | most specific label, 2,354 values |
| `taxonomy.hierarchy` | list\<string\> | root-to-leaf path |
| `basic_category` | string | 286 coarse curated labels |

It renamed 214 values (mostly plural to singular), removed 51 and reparented
1,583, which is two thirds of the taxonomy.

botmap is built on `categories.primary`. When the field disappears, nothing
errors. A filter on a missing field matches nothing, so every place query
returns zero rows and reads as "this area has none".

Release `2026-08-19.0` still carries both `categories.primary` and
`taxonomy.primary`. This work lands ahead of the cutover rather than after it.

---

## 2. Goal

1. Keep working queries working. No caller rewrites a script because Overture
   moved a field.
2. Make `basic_category` queryable.
3. Fail loudly when a caller uses the removed field or a flag the command does
   not take, rather than returning zero rows.

Not in scope here: searching category values, filtering on
`taxonomy.hierarchy`, and zero-result hints. Those are in the discovery and list
filters spec.

Also not in scope: mapping old values to new ones, and global enumeration, which
stays area-scoped. The parquet does not carry an old-to-new mapping. Overture's
taxonomy sheet does, in its `PC Redirect To` column, and that is left for later.

---

## 3. CLI surface

| Surface | Reads | Status |
|---|---|---|
| `categories` command | `taxonomy.primary` | was `categories.primary` |
| `--category VAL` | `taxonomy.primary` | unchanged for callers |
| `basic-categories` command | `basic_category` | new |
| `--basic-category VAL` | `basic_category` | new, on `places` |

### 3.1 Existing, extended

**`categories` and `--category`** re-point to `taxonomy.primary` and keep their
names. Nothing is deprecated and nothing is renamed.

### 3.2 New commands

```
botmap basic-categories [-t place] (--bbox X | --in "NAME") [--top N] [-r REL]
```

Enumerates `basic_category` with counts, area-scoped, mirroring `categories`.

It is a separate command because `basic_category` is a separate curated
vocabulary, not a slice of the hierarchy. It is the broader of the two: in
2,310 of 2,342 rows of the taxonomy sheet, the basic value is the primary
value's own ancestor or the value itself. How much broader varies by subject. It
sits at level 2 for `restaurant`, at the leaf for `preschool`, and at level 2
`home_service` for roofing.

### 3.3 Flags

| Flag | On | Resolves to |
|---|---|---|
| `--category VAL` | `places` | `taxonomy.primary = VAL` |
| `--basic-category VAL` | `places` | `basic_category = VAL` |

The two flags are independent and may be used together.

`at` gains no category flags. `--where` covers it, and `skill.md:136` documents
an `at --category` flag that has never existed, so the doc is corrected.

The same holds for `count`, `sample` and `download`. They take `-t TYPE`, so a
category flag has no meaning on them. Rather than let Click reject it with a
bare "no such option", each claims the flag and names the `--where` form. See
section 4.

---

## 4. Errors

| Input | Required |
|---|---|
| `--where 'categories.primary=X'` after removal | name `taxonomy.primary` as the successor |
| `--category X` on `count`, `sample`, `at` or `download` | `UsageError` naming `--where taxonomy.primary=X` |
| `--basic-category X` on the same commands | `UsageError` naming `--where basic_category=X` |

While both fields exist, `categories.primary` keeps working as a raw field path.
The successor error fires only once the schema has `taxonomy.primary` and no
`categories.primary`.

---

## 5. Output shapes

Unchanged. Both enumeration commands emit the same shape.

```
$ botmap categories -t place --in "Luxembourg" --top 3
       286  restaurant
       112  hotel
        79  cafe

$ botmap --json basic-categories -t place --in "Luxembourg" --top 2
[{"value": "restaurant", "count": 811}, {"value": "hotel", "count": 78}]
```

---

## 6. Skill and docs

### 6.1 Skill

`botmap/data/skill.md` needs these updates:

1. **Troubleshooting** (`:48-69`). Values are singular from the 2026-09 release
   on, so use `restaurant`, not `restaurants`.
2. **Schema cheatsheet** (`:210`). Teach `taxonomy.primary` and `basic_category`.
3. **New "which category field" section**. Use `--basic-category` for broad
   asks and `--category` for specific ones. Say that both are `places` flags,
   and show the `--where` form for every other command.
4. **Fix `:136`**. Rewrite `at --category pharmacy` as
   `at … --where taxonomy.primary=pharmacy`.
5. **Fix `:185`**. Transit stops are taught as `categories.primary` today.

Do not name specific category values or counts in the Skill beyond a worked
example. With 214 renames and 1,583 reparentings in one release, a listed value
goes stale without anything noticing.

### 6.2 Help text

`--help` text must use the same terms:

1. `places --help` explains that `--category` filters `taxonomy.primary`, and it
   documents `--basic-category`.
2. `categories --help` says it lists `taxonomy.primary` values.
3. `basic-categories --help` says it lists `basic_category` values.

### 6.3 Project docs and evals

`README.md` (41 mentions) and `SPEC.md` follow the same substitutions.
`evals/questions.yaml` (`:18,36,42,82,94,95`) and `evals/taxonomy.py:24-26`
encode `categories.primary`; without updating them the migration reads as a
regression.

---

## 7. Backwards compatibility

Nothing is deprecated and nothing is renamed. `categories` and `--category`
keep their names and their meaning. Existing scripts keep working.

Raw `--where categories.primary=X` breaks when the field goes. Raw paths speak
literal schema by design, so the error names the successor instead of dumping
the field list.

There is no release fallback. Both catalog releases postdate `taxonomy` and
`basic_category`, older releases are deleted from S3 after ~60 days for GDPR
compliance, and `validate_release` (`cli.py:413`) rejects any release absent
from the catalog.

The flag name survives but the values under it do not. 214 renames, 51
removals and 1,583 reparentings mean a script passing a retired value gets zero
rows. The parquet does not map old values to new ones.

---

## 8. Testing requirements

| File | Covers |
|---|---|
| `test_cli_categories.py` | restub on `taxonomy.primary` |
| `test_cli_basic_categories.py` | new command, human and `--json` shapes, `--in`, `--bbox`/`--in` exclusion |
| `test_filters.py` | the `categories.primary` successor error, with and without `taxonomy.primary` present |
| `test_cli_category_flag_rejection.py` | each rejecting command names the `--where` form, and `places` keeps its flags |
| `test_cli_capabilities.py` | manifest entries for the new command and flag |
| `test_cli_schema.py`, `test_introspection.py` | field name updates |

Every error in section 4 needs a test asserting the message names the
alternative, not just that it raises.

---

## 9. Delivery

1. **Remap.** Point `categories`, `--category`, the zero-result hint and its
   scan at `taxonomy.primary`. Ships alone, and is what stops every place query
   returning zero in September.
2. **`basic-categories` and `--basic-category`.** Plain string equality.

Discovery, `~`, `contains` and the shared zero-result hint follow in the
discovery and list filters spec.

---
