"""`~` is case-insensitive substring matching, parseable from --where."""

import pyarrow as pa
import pytest

from botmap.filters import ParsedFilter, parse_where_expr


def _string_schema():
    return pa.schema([
        ("taxonomy", pa.struct([("primary", pa.string())])),
        ("height", pa.float64()),
    ])


class TestParsing:
    def test_tilde_without_spaces(self):
        assert parse_where_expr("taxonomy.primary~vet") == ParsedFilter(
            key="taxonomy.primary", op="~", value="vet")

    def test_tilde_with_spaces(self):
        assert parse_where_expr("taxonomy.primary ~ vet") == ParsedFilter(
            key="taxonomy.primary", op="~", value="vet")

    def test_earlier_operator_wins(self):
        """A `~` inside the value must not be mistaken for the operator."""
        assert parse_where_expr("taxonomy.primary=a~b") == ParsedFilter(
            key="taxonomy.primary", op="=", value="a~b")


class TestMatching:
    def _matches(self, values, needle):
        table = pa.table({"name": pa.array(values, type=pa.string())})
        expr = ParsedFilter("name", "~", needle).to_pyarrow_expression(table.schema)
        return table.filter(expr).column("name").to_pylist()

    def test_is_case_insensitive(self):
        assert self._matches(["Veterinarian", "bakery"], "vet") == ["Veterinarian"]

    def test_is_substring_not_prefix(self):
        assert self._matches(["animal_vet_clinic"], "vet") == ["animal_vet_clinic"]

    def test_caret_is_literal_not_regex(self):
        """`~^vet` searches for a literal caret, so it matches nothing here."""
        assert self._matches(["veterinarian"], "^vet") == []


class TestValidation:
    def test_string_field_is_allowed(self):
        ParsedFilter("taxonomy.primary", "~", "vet").validate_against_schema(_string_schema())

    def test_numeric_field_is_rejected(self):
        with pytest.raises(ValueError) as exc:
            ParsedFilter("height", "~", "x").validate_against_schema(_string_schema())
        msg = str(exc.value)
        assert "~" in msg
        assert "height" in msg
        assert "string" in msg.lower()
