"""Parser and PyArrow translator for the --where filter flag."""

from __future__ import annotations

import functools
import operator
from dataclasses import dataclass
from typing import Any, List, Tuple, Union

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc


# Operators ordered longest-first so the splitter doesn't mistake `>=` for `>`.
_OPERATORS = [" contains ", "<=", ">=", "!=", " in ", "=", "<", ">", "~"]

# Words people type as operators that --where does not support. Naming them
# beats the generic "no operator" message; other words are part of a value.
_OPERATOR_LOOKALIKES = frozenset({
    "like", "ilike", "is", "isnt", "not", "eq", "ne", "gt", "ge", "lt", "le",
    "has", "match", "matches", "regex", "regexp", "startswith", "endswith",
})

# Operators that only make sense on a string field.
_STRING_ONLY_OPERATORS = ("~",)

# Operators applied to batches after the scan, because they cannot be pushed down.
_POST_SCAN_OPERATORS = ("contains",)


@dataclass(frozen=True)
class ParsedFilter:
    key: str
    # User-facing ops from --where: =, !=, <, <=, >, >=, in, ~, contains
    #   ~ : case-insensitive substring match, also used by `addresses --street`
    #   contains : list membership, the only operator a list field accepts
    op: str
    value: Any  # str | int | float | bool | list

    def to_pyarrow_expression(self, schema: pa.Schema) -> pc.Expression:
        """Build a pc.Expression resolving dotted keys against `schema`."""
        # Walk dotted path -> pc.field(...) with nested struct access.
        parts = self.key.split(".")
        field_ref = pc.field(*parts) if len(parts) > 1 else pc.field(parts[0])

        if self.op == "=":
            return field_ref == self.value
        if self.op == "!=":
            return field_ref != self.value
        if self.op == "<":
            return field_ref < self.value
        if self.op == "<=":
            return field_ref <= self.value
        if self.op == ">":
            return field_ref > self.value
        if self.op == ">=":
            return field_ref >= self.value
        if self.op == "in":
            return field_ref.isin(self.value)
        if self.op == "~":
            return pc.match_substring(field_ref, self.value, ignore_case=True)
        raise ValueError(f"Unsupported operator: {self.op!r}")

    def validate_against_schema(self, schema: pa.Schema) -> None:
        """Verify self.key resolves to a field in `schema`; raise ValueError otherwise."""
        parts = self.key.split(".")
        # Top-level lookup
        top = parts[0]
        if top not in schema.names:
            if self.key == "categories.primary" and _has_taxonomy_primary(schema):
                raise ValueError(
                    "Field 'categories.primary' is no longer present. "
                    "Use 'taxonomy.primary' instead."
                )
            raise ValueError(
                f"Unknown field {self.key!r}. Available fields: "
                f"{', '.join(sorted(schema.names))}"
            )
        # Walk into nested struct types if dotted
        current_type = schema.field(top).type
        for i, part in enumerate(parts[1:], start=1):
            if not pa.types.is_struct(current_type):
                raise ValueError(
                    f"Field {self.key!r} is invalid: "
                    f"{'.'.join(parts[:i])} is not a struct"
                )
            child_names = [current_type.field(j).name for j in range(current_type.num_fields)]
            if part not in child_names:
                raise ValueError(
                    f"Unknown field {self.key!r}. "
                    f"Available subfields: {', '.join(sorted(child_names))}"
                )
            current_type = current_type.field(child_names.index(part)).type
        self._validate_operator_against_type(current_type)

    def _validate_operator_against_type(self, field_type: pa.DataType) -> None:
        """Reject an operator the resolved field type cannot support."""
        if self.op == "contains":
            self._validate_contains(field_type)
            return
        if _is_list_type(field_type):
            example = self.value[0] if self.op == "in" and self.value else self.value
            raise ValueError(
                f"Field {self.key!r} is a list ({field_type}), so '{self.op}' cannot "
                f"compare it. Use --where '{self.key} contains {example}' to keep "
                f"rows whose list holds that value. `contains` takes one value."
            )
        if self.op in _STRING_ONLY_OPERATORS and not pa.types.is_string(field_type):
            raise ValueError(
                f"Operator '{self.op}' needs a string field, but {self.key!r} is "
                f"{field_type}. Use a comparison such as '=' instead."
            )

    def _validate_contains(self, field_type: pa.DataType) -> None:
        """Reject `contains` unless the field is a list of plain values the value fits."""
        if not _is_list_type(field_type):
            raise ValueError(
                f"Operator 'contains' needs a list field, but {self.key!r} is "
                f"{field_type}, not a list. Use '=' or '~' instead."
            )
        element_type = field_type.value_type
        if pa.types.is_nested(element_type):
            raise ValueError(
                f"Operator 'contains' needs a list of plain values, but {self.key!r} "
                f"is a list of records ({element_type})."
            )
        try:
            _as_element(self.value, element_type)
        except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
            raise ValueError(
                f"{self.value!r} cannot be compared with the items of {self.key!r}, "
                f"which are {element_type}."
            )


def list_contains_mask(column: pa.Array, value: Any) -> pa.BooleanArray:
    """Return a row mask that is true where `column`'s list holds `value`.

    This runs after the scan rather than inside it. PyArrow has no
    list-membership kernel, and a scan filter must yield one value per row,
    which `list_flatten` does not. So we flatten, find the matching elements,
    and map each one back to the row it came from.
    """
    element = _as_element(value, column.type.value_type)
    matching_rows = pc.filter(pc.list_parent_indices(column),
                              pc.equal(pc.list_flatten(column), element))
    mask = np.zeros(len(column), dtype=bool)
    mask[matching_rows.to_numpy()] = True
    return pa.array(mask)


def _as_element(value: Any, element_type: pa.DataType) -> pa.Scalar:
    """Convert a `contains` value to the list's item type, e.g. "5" for an int64 list."""
    return pa.scalar(value).cast(element_type)


def _is_list_type(field_type: pa.DataType) -> bool:
    return (pa.types.is_list(field_type)
            or pa.types.is_large_list(field_type)
            or pa.types.is_fixed_size_list(field_type))


def _has_taxonomy_primary(schema: pa.Schema) -> bool:
    """Return whether `schema` has the `taxonomy.primary` successor field."""
    if "taxonomy" not in schema.names:
        return False
    taxonomy_type = schema.field("taxonomy").type
    if not pa.types.is_struct(taxonomy_type):
        return False
    try:
        taxonomy_type.field("primary")
        return True
    except KeyError:
        return False


def _coerce_scalar(raw: str) -> Union[str, int, float, bool]:
    s = raw.strip()
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return _strip_quotes(s)


def _strip_quotes(s: str) -> str:
    """Drop one pair of matching surrounding quotes, if present."""
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _parse_list_value(raw: str) -> List[Any]:
    s = raw.strip()
    if not (s.startswith("[") and s.endswith("]")):
        raise ValueError(f"`in` value must be a [a,b,c] list, got: {raw!r}")
    inner = s[1:-1]
    parts = [p for p in (chunk.strip() for chunk in inner.split(",")) if p]
    return [_coerce_scalar(p) for p in parts]


def _reject_unknown_operator(expr: str) -> None:
    """Name the word a caller used as an operator, when it isn't one.

    `name like cafe` reads as K OP V but `like` is not supported. Saying so
    beats the generic "no operator" hint, which sends the caller looking for
    a shell-quoting problem they do not have.
    """
    parts = expr.split()
    if len(parts) < 3 or parts[1].lower() not in _OPERATOR_LOOKALIKES:
        return
    supported = ", ".join(repr(o.strip()) for o in _OPERATORS)
    raise ValueError(
        f"Unsupported operator {parts[1]!r} in filter {expr!r}. "
        f"Supported operators: {supported}."
    )


def parse_where_expr(expr: str) -> ParsedFilter:
    """Parse a single --where expression of the form 'KEY OP VALUE'."""
    # Locate the leftmost occurrence of any operator, preferring longer matches.
    best_idx = -1
    best_op = None
    for op in _OPERATORS:
        idx = expr.find(op)
        if idx == -1:
            continue
        # Prefer earlier-starting matches; on tie, prefer longer operator
        if best_idx == -1 or idx < best_idx or (idx == best_idx and len(op) > len(best_op)):
            best_idx = idx
            best_op = op

    if best_op is None:
        _reject_unknown_operator(expr)
        raise ValueError(
            f"Filter {expr!r} has no operator. Use K OP V, e.g. "
            f"--where 'height>150'. If you typed an unquoted > or <, your "
            f"shell redirected it to a file — wrap the whole expression in "
            f"single quotes."
        )

    key = expr[:best_idx].strip()
    value_raw = expr[best_idx + len(best_op):].strip()
    op = best_op.strip()  # ' in ' -> 'in'

    if not key:
        raise ValueError(f"--where expression has empty key: {expr!r}")
    if not value_raw:
        raise ValueError(f"--where expression has empty value: {expr!r}")

    if op == "in":
        value = _parse_list_value(value_raw)
    elif op == "contains":
        if value_raw.startswith("["):
            raise ValueError(
                f"`contains` takes a single value, not a list: {expr!r}. "
                f"Use --where 'KEY contains VALUE'."
            )
        value = _strip_quotes(value_raw)
    else:
        value = _coerce_scalar(value_raw)

    return ParsedFilter(key=key, op=op, value=value)


def combine(
    filters: List[ParsedFilter], schema: pa.Schema,
) -> Tuple[pc.Expression | None, List[ParsedFilter]]:
    """Validate filters and split them into a scan expression and post-scan filters.

    Most filters AND together into one expression the scan pushes down.
    `contains` cannot be pushed down (see `list_contains_mask`), so those
    filters come back separately for the caller to apply to each batch.
    """
    for f in filters:
        f.validate_against_schema(schema)
    post_filters = [f for f in filters if f.op in _POST_SCAN_OPERATORS]
    exprs = [f.to_pyarrow_expression(schema)
             for f in filters if f.op not in _POST_SCAN_OPERATORS]
    pushdown = functools.reduce(operator.and_, exprs) if exprs else None
    return pushdown, post_filters


def apply_post_filters(batch: pa.RecordBatch, post_filters: List[ParsedFilter]) -> pa.RecordBatch:
    """Keep the rows of `batch` that pass every post-scan filter."""
    masks = [list_contains_mask(_column_at(batch, f.key), f.value) for f in post_filters]
    return batch.filter(functools.reduce(pc.and_, masks))


def post_filter_fields(post_filters: List[ParsedFilter]) -> List[str]:
    """Top-level fields a scan must read so the post-scan filters can run."""
    return list(dict.fromkeys(f.key.split(".")[0] for f in post_filters))


def _column_at(batch: pa.RecordBatch, key: str) -> pa.Array:
    """Resolve a dotted key such as `taxonomy.hierarchy` to a column of `batch`."""
    top, *path = key.split(".")
    column = batch.column(top)
    return pc.struct_field(column, path) if path else column
