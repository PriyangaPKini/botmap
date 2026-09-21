# botmap — Places Category Discovery and List Filters

**Date:** 2026-09-20
**Status:** Proposed
**Plan:** `docs/superpowers/plans/2026-09-20-places-category-discovery-and-list-filters.md`
**Builds on:** `docs/superpowers/specs/2026-09-20-places-category-taxonomy-migration.md`

Value counts and churn figures come from Overture's taxonomy sheet, "Place
Categories + Basic Categories", February 2026. Measurements and examples come
from release `2026-08-19.0`.

---

## 1. Problem

The taxonomy migration moves botmap onto `taxonomy.primary` and
`basic_category`. It leaves three gaps.

First, `taxonomy.primary` has 2,354 values and there is no way to search them.
Finding the right one means enumerating everything and grepping outside the
tool.

Second, `--where` on a list field crashes with a raw PyArrow traceback. That
already affects `categories.alternate`, and it will affect `taxonomy.hierarchy`.

Third, there is no way to ask for a category and everything beneath it.
`taxonomy.primary in [a,b,c]` needs the caller to name every child, and misses
whichever one they forget. The release reparented 1,583 of 2,354 categories, so
a list that was complete last release may not be complete this one.

---

## 2. Goal

1. Make values findable in one command.
2. Make `taxonomy.hierarchy` queryable, so a parent category returns its
   children.
3. Fail loudly, rather than returning a traceback or a silent zero.

Not in scope: semantic search, and global enumeration, which stays area-scoped.

---

## 3. CLI surface

| Surface | Reads | Status |
|---|---|---|
| `--find TEXT` on both enumeration commands | listed values | new |
| `--where 'K contains V'` | any list field | new operator |
| `--where 'K~V'` | any string field on commands that take `--where` | exists internally, not parseable |

### 3.1 Discovery

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

### 3.2 Flags

| Flag | On | Resolves to |
|---|---|---|
| `--where 'K contains V'` | all verbs taking `--where` | list membership, post-scan |
| `--where 'K ~ V'` or `--where 'K~V'` | all verbs taking `--where` | case-insensitive substring |
| `--find TEXT` | `categories`, `basic-categories` | searches the listed values |

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

The parser must report unknown operators before it falls back to the generic
"no operator" message. The error names the unsupported operator and lists the
supported operators: `=`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `~` and `contains`.

`validate_against_schema` (`filters.py:51`) walks structs only and gains list
awareness.

### 4.1 The zero-result hint

Today it exists at one call site, `cli.py:1151`, inside `places`. Extract it into
`category_taxonomy.py` and call it from `places`, `count`, `at` and `sample`. It
fires only when the type is `place` and a filter names a category field, and
writes to stderr.

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

## 5. Skill and docs

### 5.1 Skill

`botmap/data/skill.md` needs these updates:

1. **Schema cheatsheet**. Teach `taxonomy.hierarchy`.
2. **Filter syntax** (`:226`). Document `contains` and `~`, state that `~` is a
   substring and not a regex, and list the full operator set.
3. **"Which category field" section**. Add `contains` for roll-up.
4. **New "finding a category value" section**. Show one command, not a dump and
   a grep:

   ```bash
   botmap categories -t place --in "…" --find vet --top 5
   ```

5. **A zero count is slow**. Say that it triggers a suggestion scan.

### 5.2 Help text

1. `categories --help` and `basic-categories --help` document `--find` as
   substring search over listed values.
2. Commands that accept `--where` list the full operator set, including `~` and
   `contains`, and say that `~` is substring matching.

---

## 6. Testing requirements

| File | Covers |
|---|---|
| `test_cli_categories.py` | `--find` searches listed values |
| `test_cli_basic_categories.py` | `--find` searches listed values |
| `test_filters.py` | `contains` parsing; every error row in section 4 |
| `test_filters_contains.py` | the mask against lists, empty lists and nulls |
| `test_filters_tilde.py` | `~` parses, is case-insensitive, pushes down, is not a regex |
| `test_cli_capabilities.py` | manifest entries for the new flags |

Every error in section 4 needs a test asserting the message names the
alternative, not just that it raises.

Re-run the eval bank before and after `contains` lands.

---

## 7. Delivery

Steps are numbered from 3 because steps 1 and 2 are in the migration spec, and
commits and PRs refer to these numbers.

3. **`--find` on the enumeration commands.** The discovery path. Independent
   of steps 1 and 2.
4. **`~` for commands that take `--where`.** Substring filtering outside the
   enumeration commands.
5. **Column projection** and the hint extraction (section 4.1).
6. **`contains`.** The post-scan filter path. Adds roll-up and fixes the
   pre-existing list-field crash.
7. **Skill, README, evals.**

---
