# botmap — Places Category Taxonomy CLI Redesign

**Date:** 2026-09-20
**Status:** Proposed

All numbers in this document come from Overture release `2026-08-19.0`.

---

## 1. Problem

Overture replaces the flat `categories` property on `place` with three fields
and removes `categories` in the September 2026 release.

| Field | Type | Holds |
|---|---|---|
| `taxonomy.primary` | string | most specific label, ~2,100 values |
| `taxonomy.hierarchy` | list\<string\> | root-to-leaf path |
| `basic_category` | string | ~280 coarse curated labels |

It renamed ~407 values (mostly plural to singular), removed ~80 and reparented
~482.

botmap is built on `categories.primary`. When the field disappears, nothing
errors. A filter on a missing field matches nothing, so every place query
returns zero rows and reads as "this area has none".

Two defects are already live. `--where` on a list field crashes with a raw
PyArrow traceback, which will affect `taxonomy.hierarchy` as it already affects
`categories.alternate`. And with ~2,100 values and no way to search them,
finding the right one means enumerating everything and grepping outside the
tool.

---

## 2. Goal

1. Keep working queries working. No caller rewrites a script because Overture
   moved a field.
2. Make `basic_category` and the hierarchy queryable.
3. Make values findable in one command.
4. Fail loudly, rather than returning zero rows or a traceback.

Not in scope: mapping old values to new ones, which the parquet does not carry,
and global enumeration, which stays area-scoped.

---

## 3. CLI surface

| Surface | Reads | Status |
|---|---|---|
| `categories` command | `taxonomy.primary` | was `categories.primary` |
| `--category VAL` | `taxonomy.primary` | unchanged for callers |
| `basic-categories` command | `basic_category` | new |
| `--basic-category VAL` | `basic_category` | new, on `places` |
| `--find TEXT` on both enumeration commands | listed values | new |
| `--where 'K contains V'` | any list field | new operator |
| `--where 'K~V'` | any string field on commands that take `--where` | exists internally, not parseable |

### 3.1 Existing, extended

**`categories` and `--category`** re-point to `taxonomy.primary` and keep their
names. Nothing is deprecated and nothing is renamed.

**`--find` on the enumeration commands.** `categories` has no search today,
so the only control over the value list is `--top`. With `--find`, discovery
becomes one command:

```
$ botmap categories -t place --in "…" --find vet --top 5
        14  veterinarian
```

`--find` searches the values the command lists. On `categories`, it searches
`taxonomy.primary`. On `basic-categories`, it searches `basic_category`. It is a
case-insensitive substring search, not semantic search.

**Column projection.** `core.py:210` calls `dataset.to_batches()` with no
`columns=`, so `categories` reads all 28 columns to count one field. Both
enumeration commands must project. Measured at 3.3x, 2.08s against 0.63s.

### 3.2 New commands

```
botmap basic-categories [-t place] (--bbox X | --in "NAME") [--find TEXT] [--top N] [-r REL]
```

Enumerates `basic_category` with counts, area-scoped, mirroring `categories`.

It is a separate command because `basic_category` is a separate curated
vocabulary, not a slice of the hierarchy. It sits at different depths for
different subjects: level 2 for `restaurant`, the leaf for `preschool`, level 2
`home_service` for roofing.

### 3.3 Flags

| Flag | On | Resolves to |
|---|---|---|
| `--category VAL` | `places` | `taxonomy.primary = VAL` |
| `--basic-category VAL` | `places` | `basic_category = VAL` |
| `--where 'K contains V'` | all verbs taking `--where` | list membership, post-scan |
| `--where 'K ~ V'` or `--where 'K~V'` | all verbs taking `--where` | case-insensitive substring |
| `--find TEXT` | `categories`, `basic-categories` | searches the listed values |

`at` gains no category flags. `--where` covers it, and `skill.md:136` documents
an `at --category` flag that has never existed, so the doc is corrected.

#### `contains`

For list fields. The value is always a scalar; `contains [a,b]` is rejected.

It supports parent-category queries against `taxonomy.hierarchy`. For example,
if `steakhouse` has `taxonomy.hierarchy = ["food_and_drink", "restaurant",
"steakhouse"]`, then `--where 'taxonomy.hierarchy contains restaurant'` matches
it because `restaurant` is one of the hierarchy values. A query for
`restaurant` therefore returns all places under that parent category, including
`steakhouse`, `pizza_restaurant` and other child categories.

It cannot be pushed down, because PyArrow 22 has no list-membership kernel and
`list_flatten` is rejected in a scan filter as non-scalar, since a filter must
return one value per row. So it runs after rows are read:

```python
def list_contains_mask(col, value):
    """Rows whose list holds `value`."""
    rows = pc.filter(pc.list_parent_indices(col),
                     pc.equal(pc.list_flatten(col), value))
    return pc.is_in(pa.array(range(len(col)), type=pa.int64()), value_set=rows)
```

That forks the filter path. `filters.combine()` (`filters.py:143`) returns
`(pushdown_expr, post_filters)` instead of one expression.
`record_batch_reader` (`core.py:306`) wraps its reader in a generator applying
`post_filters` per batch. `count_rows` (`core.py:285`) cannot use
`dataset.count_rows(filter=)` when post-filters exist; it streams, sums, and
must project. `_OPERATORS` (`filters.py:14`) gains `" contains "`.

#### `~`

Already implemented at `filters.py:46` for `addresses --street`, but
`_OPERATORS` omits it so `--where` cannot produce one. Adding `"~"` turns it on;
the translator needs no change.

Spaces around `~` are optional. Both `taxonomy.primary~vet` and
`taxonomy.primary ~ vet` parse to the same filter.

It is a plain case-insensitive substring, not a regular expression, so `~^vet`
searches for a literal caret. The Skill and the error messages must say so.

`~` finds names, `contains` matches structure, and they are not substitutes.
`taxonomy.primary~restaurant` matches 864 places against 805 for
`hierarchy contains restaurant`, over-counting by 68 including
`restaurant_equipment_and_supply`, a shop, and missing `steakhouse` and
`pancake_house`.

---

## 4. Errors

Every case below currently crashes or returns a silent zero.

| Input | Required |
|---|---|
| `--where 'taxonomy.hierarchy=restaurant'` | `UsageError`: list field, use `contains` |
| `--where 'categories.alternate=cafe'` | same |
| `--where 'taxonomy.primary contains x'` | `UsageError`: not a list field |
| `--where 'taxonomy.hierarchy~x'` | `UsageError`: list field, use `contains` |
| `--where 'height~x'` | `UsageError`: `~` needs a string field |
| `--where 'K contains [a,b]'` | `UsageError`: scalar value only |
| `--where 'name like cafe'` | `UsageError`: unknown operator, and list supported operators |
| `--where 'categories.primary=X'` after removal | name `taxonomy.primary` as the successor |

The parser must report unknown operators before it falls back to the generic
"no operator" message. The error names the unsupported operator and lists the
supported operators: `=`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `~` and `contains`.

`validate_against_schema` (`filters.py:51`) walks structs only and gains list
awareness.

### 4.1 The zero-result hint

Today it exists at one call site, `cli.py:1151`, inside `places`, hard-coded to
`categories.primary`. Extract it into `category_taxonomy.py` and call it from
`places`, `count`, `at` and `sample`. It fires only when the type is `place` and
a filter names a category field, and writes to stderr.

It must check both vocabularies in one pass, since a value used against the
wrong field returns a clean zero today:

```
$ botmap count -t place --in "…" --where basic_category=veterinarian
0
[botmap] 'veterinarian' is a taxonomy.primary value, not a basic_category.
         Try --where taxonomy.primary=veterinarian,
         or --basic-category animal_or_pet_service.
```

It must also keep its fuzzy matching, so `--category restaurants` answers
`Did you mean: restaurant?`. A substring search for the caller's own value finds
nothing once a value has been renamed.

Two required fixes, neither changing behaviour. Reuse the dataset
`_prepare_query` already resolved, which `record_batch_reader` discards, and
project to the category columns. Measured over the whole miss path, 15.63s
against 9.16s.

The cost lands on the cheapest command, since `count` runs in 0.65s and the
Skill tells callers to run it first. It fires only when the answer was zero.

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
2. **Schema cheatsheet** (`:210`). Teach `taxonomy.primary`, `basic_category`
   and `taxonomy.hierarchy`.
3. **Filter syntax** (`:226`). Document `contains` and `~`, state that `~` is a
   substring and not a regex, and list the full operator set.
4. **New "which category field" section**. Use `--basic-category` for broad
   asks, `--category` for specific ones, and `contains` for roll-up.
5. **New "finding a category value" section**. Show one command, not a dump and
   a grep:

   ```bash
   botmap categories -t place --in "…" --find vet --top 5
   ```

6. **A zero count is slow**. Say that it triggers a suggestion scan.
7. **Fix `:136`**. Rewrite `at --category pharmacy` as
   `at … --where taxonomy.primary=pharmacy`.
8. **Fix `:185`**. Transit stops are taught as `categories.primary` today.

### 6.2 Help text

`--help` text must use the same terms:

1. `places --help` explains that `--category` filters `taxonomy.primary`, and it
   documents `--basic-category`.
2. `categories --help` says it lists `taxonomy.primary` values and documents
   `--find` as substring search over listed values.
3. `basic-categories --help` says it lists `basic_category` values and documents
   `--find` as substring search over listed values.
4. Commands that accept `--where` list the full operator set, including `~` and
   `contains`, and say that `~` is substring matching.

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

The flag name survives but the values under it do not. ~407 renames, ~80
removals and ~482 reparentings mean a script passing a retired value gets zero
rows, and nothing in the parquet maps old to new.

---

## 8. Testing requirements

| File | Covers |
|---|---|
| `test_cli_categories.py` | restub on `taxonomy.primary`; `--find` searches listed values |
| `test_cli_basic_categories.py` | new command, human and `--json` shapes; `--find` searches listed values |
| `test_filters.py` | `contains` parsing; every error row in section 4 |
| `test_filters_contains.py` | the mask against lists, empty lists and nulls |
| `test_filters_tilde.py` | `~` parses, is case-insensitive, pushes down, is not a regex |
| `test_cli_capabilities.py` | manifest entries for the new flags |
| `test_cli_schema.py`, `test_introspection.py` | field name updates |

Every error in section 4 needs a test asserting the message names the
alternative, not just that it raises.

Re-run the eval bank before and after step 6.

---

## 9. Migration plan

1. **Remap.** Point `categories`, `--category`, the zero-result hint and its
   scan at `taxonomy.primary`. Ships alone, and is what stops every place query
   returning zero in September.
2. **`basic-categories` and `--basic-category`.** Plain string equality.
3. **`--find` on the enumeration commands.** The discovery path. Independent
   of steps 1 and 2.
4. **`~` for commands that take `--where`.** Substring filtering outside the
   enumeration commands.
5. **Column projection** and the hint extraction (section 4.1).
6. **`contains`.** The post-scan filter path. Adds roll-up and fixes the
   pre-existing list-field crash.
7. **Skill, README, evals.**

---
