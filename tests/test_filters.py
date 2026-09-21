"""Tests for the --where filter parser."""

import pyarrow as pa
import pyarrow.compute as pc
import pytest

from botmap.filters import parse_where_expr, ParsedFilter


class TestParseWhereExpr:
    def test_equality_string(self):
        f = parse_where_expr("categories.primary=restaurant")
        assert f == ParsedFilter(key="categories.primary", op="=", value="restaurant")

    def test_equality_int(self):
        f = parse_where_expr("num_floors=10")
        assert f.value == 10

    def test_equality_float(self):
        f = parse_where_expr("confidence=0.85")
        assert f.value == 0.85

    def test_equality_bool_true(self):
        f = parse_where_expr("has_parts=true")
        assert f.value is True

    def test_equality_bool_false(self):
        f = parse_where_expr("has_parts=false")
        assert f.value is False

    def test_not_equal(self):
        f = parse_where_expr("class!=footway")
        assert f.op == "!="
        assert f.value == "footway"

    def test_gt(self):
        f = parse_where_expr("height>100")
        assert f.op == ">"
        assert f.value == 100

    def test_gte(self):
        f = parse_where_expr("height>=100")
        assert f.op == ">="

    def test_lt(self):
        f = parse_where_expr("height<50")
        assert f.op == "<"

    def test_lte(self):
        f = parse_where_expr("height<=50")
        assert f.op == "<="

    def test_in_list(self):
        f = parse_where_expr("class in [motorway,primary,trunk]")
        assert f.op == "in"
        assert f.value == ["motorway", "primary", "trunk"]

    def test_in_list_with_spaces(self):
        f = parse_where_expr("class in [ motorway , primary ]")
        assert f.value == ["motorway", "primary"]

    def test_in_list_typed(self):
        f = parse_where_expr("num_floors in [1,2,3]")
        assert f.value == [1, 2, 3]

    def test_longest_operator_wins(self):
        # ensure `>=` isn't misread as `>` followed by `=...`
        f = parse_where_expr("height>=100")
        assert f.op == ">="
        assert f.value == 100

    def test_dotted_key(self):
        f = parse_where_expr("bbox.xmin<-70")
        assert f.key == "bbox.xmin"
        assert f.value == -70

    def test_missing_operator_raises(self):
        with pytest.raises(ValueError, match="no operator"):
            parse_where_expr("just_a_key")

    def test_missing_operator_explains_shell_redirection(self):
        # A bare key like "height" reaches the parser when the shell ate an
        # unquoted `>150` as a redirection. The error must name the key,
        # show the K OP V form, and explain the single-quote fix.
        with pytest.raises(ValueError) as exc:
            parse_where_expr("height")
        msg = str(exc.value)
        assert "height" in msg
        assert "height>150" in msg or "K OP V" in msg
        assert "single-quote" in msg or "single quote" in msg
        assert "redirect" in msg.lower()

    def test_empty_value_raises(self):
        with pytest.raises(ValueError, match="empty value"):
            parse_where_expr("key=")


class TestToPyarrowExpression:
    def test_simple_equality(self):
        schema = pa.schema([("class", pa.string())])
        f = ParsedFilter("class", "=", "motorway")
        expr = f.to_pyarrow_expression(schema)
        # Just verify it's an Expression; equality semantics are tested at
        # integration time against a real dataset.
        assert isinstance(expr, pc.Expression)

    def test_nested_field(self):
        schema = pa.schema([
            ("categories", pa.struct([("primary", pa.string())])),
        ])
        f = ParsedFilter("categories.primary", "=", "restaurant")
        expr = f.to_pyarrow_expression(schema)
        assert isinstance(expr, pc.Expression)

    def test_in_operator(self):
        schema = pa.schema([("class", pa.string())])
        f = ParsedFilter("class", "in", ["motorway", "primary"])
        expr = f.to_pyarrow_expression(schema)
        assert isinstance(expr, pc.Expression)

    def test_numeric_comparison(self):
        schema = pa.schema([("height", pa.float64())])
        f = ParsedFilter("height", ">", 100)
        expr = f.to_pyarrow_expression(schema)
        assert isinstance(expr, pc.Expression)


class TestValidateAgainstSchema:
    def test_top_level_field_ok(self):
        schema = pa.schema([("height", pa.float64())])
        f = ParsedFilter("height", ">", 50)
        # Should not raise
        f.validate_against_schema(schema)

    def test_nested_field_ok(self):
        schema = pa.schema([
            ("categories", pa.struct([("primary", pa.string())])),
        ])
        f = ParsedFilter("categories.primary", "=", "restaurant")
        f.validate_against_schema(schema)

    def test_unknown_top_level_raises(self):
        schema = pa.schema([("height", pa.float64())])
        f = ParsedFilter("widht", ">", 50)  # typo
        with pytest.raises(ValueError) as exc:
            f.validate_against_schema(schema)
        assert "widht" in str(exc.value)
        assert "available fields" in str(exc.value).lower()
        assert "height" in str(exc.value)

    def test_categories_primary_still_works_when_present(self):
        schema = pa.schema([
            ("categories", pa.struct([("primary", pa.string())])),
            ("taxonomy", pa.struct([("primary", pa.string())])),
        ])
        f = ParsedFilter("categories.primary", "=", "restaurant")
        f.validate_against_schema(schema)

    def test_removed_categories_primary_names_successor(self):
        schema = pa.schema([
            ("taxonomy", pa.struct([("primary", pa.string())])),
        ])
        f = ParsedFilter("categories.primary", "=", "restaurant")
        with pytest.raises(ValueError) as exc:
            f.validate_against_schema(schema)
        msg = str(exc.value)
        assert "categories.primary" in msg
        assert "taxonomy.primary" in msg

    def test_unknown_nested_raises(self):
        schema = pa.schema([
            ("categories", pa.struct([("primary", pa.string())])),
        ])
        f = ParsedFilter("categories.banana", "=", "x")
        with pytest.raises(ValueError) as exc:
            f.validate_against_schema(schema)
        assert "categories.banana" in str(exc.value)
        assert "primary" in str(exc.value)

    def test_dotted_into_non_struct_raises(self):
        schema = pa.schema([("height", pa.float64())])
        f = ParsedFilter("height.foo", "=", 1)
        with pytest.raises(ValueError):
            f.validate_against_schema(schema)

    def test_duplicate_segment_error_message(self):
        """Path with duplicate segments still produces the correct error position."""
        schema = pa.schema([
            ("a", pa.struct([("b", pa.int64())])),  # a.b is an int (not struct)
        ])
        f = ParsedFilter("a.b.c", "=", 1)  # trying to dot into the int
        with pytest.raises(ValueError) as exc:
            f.validate_against_schema(schema)
        assert "a.b is not a struct" in str(exc.value)


class TestUnknownOperator:
    def test_named_operator_is_reported(self):
        with pytest.raises(ValueError) as exc:
            parse_where_expr("name like cafe")
        msg = str(exc.value)
        assert "like" in msg
        assert "'in'" in msg or " in," in msg or "in," in msg
        assert "~" in msg

    def test_lists_the_supported_operators(self):
        with pytest.raises(ValueError) as exc:
            parse_where_expr("class isnt motorway")
        msg = str(exc.value)
        for op in ("=", "!=", "<=", ">=", "in", "~"):
            assert op in msg, f"{op!r} missing from {msg!r}"

    def test_no_operator_keeps_the_shell_redirection_hint(self):
        """A single token has no operator at all; that hint must survive."""
        with pytest.raises(ValueError) as exc:
            parse_where_expr("height150")
        assert "no operator" in str(exc.value).lower()
        assert "single quotes" in str(exc.value)

    def test_unknown_operator_beats_the_generic_message(self):
        with pytest.raises(ValueError) as exc:
            parse_where_expr("name like cafe")
        assert "no operator" not in str(exc.value).lower()


def _list_schema():
    return pa.schema([
        ("taxonomy", pa.struct([
            ("primary", pa.string()),
            ("hierarchy", pa.list_(pa.string())),
        ])),
    ])


class TestContainsParsing:
    def test_contains_parses_to_scalar_value(self):
        assert parse_where_expr("taxonomy.hierarchy contains restaurant") == ParsedFilter(
            key="taxonomy.hierarchy", op="contains", value="restaurant")

    def test_contains_rejects_a_list_value(self):
        with pytest.raises(ValueError) as exc:
            parse_where_expr("taxonomy.hierarchy contains [restaurant,cafe]")
        assert "contains" in str(exc.value)
        assert "single value" in str(exc.value)

    def test_contains_is_listed_as_supported(self):
        with pytest.raises(ValueError) as exc:
            parse_where_expr("name like cafe")
        assert "contains" in str(exc.value)


class TestListFieldValidation:
    def test_contains_on_list_field_is_allowed(self):
        ParsedFilter("taxonomy.hierarchy", "contains", "restaurant").validate_against_schema(
            _list_schema())

    def test_contains_on_scalar_field_is_rejected(self):
        with pytest.raises(ValueError) as exc:
            ParsedFilter("taxonomy.primary", "contains", "x").validate_against_schema(
                _list_schema())
        msg = str(exc.value)
        assert "taxonomy.primary" in msg
        assert "not a list" in msg

    def test_equals_on_list_field_suggests_contains(self):
        with pytest.raises(ValueError) as exc:
            ParsedFilter("taxonomy.hierarchy", "=", "restaurant").validate_against_schema(
                _list_schema())
        msg = str(exc.value)
        assert "taxonomy.hierarchy" in msg
        assert "taxonomy.hierarchy contains restaurant" in msg

    def test_tilde_on_list_field_suggests_contains(self):
        with pytest.raises(ValueError) as exc:
            ParsedFilter("taxonomy.hierarchy", "~", "rest").validate_against_schema(
                _list_schema())
        assert "contains" in str(exc.value)


class TestContainsElementType:
    def test_list_of_records_is_rejected(self):
        schema = pa.schema([("addresses", pa.list_(pa.struct([("country", pa.string())])))])
        with pytest.raises(ValueError) as exc:
            parse_where_expr("addresses contains US").validate_against_schema(schema)
        msg = str(exc.value)
        assert "addresses" in msg
        assert "plain values" in msg

    def test_value_that_looks_numeric_stays_text(self):
        assert parse_where_expr("taxonomy.hierarchy contains 5").value == "5"

    def test_value_that_cannot_be_the_element_type_is_rejected(self):
        schema = pa.schema([("ids", pa.list_(pa.int64()))])
        with pytest.raises(ValueError) as exc:
            parse_where_expr("ids contains abc").validate_against_schema(schema)
        assert "abc" in str(exc.value)

    def test_in_on_a_list_field_does_not_suggest_a_list_value(self):
        with pytest.raises(ValueError) as exc:
            parse_where_expr("taxonomy.hierarchy in [a,b]").validate_against_schema(_list_schema())
        msg = str(exc.value)
        assert "contains [" not in msg
        assert "one value" in msg
