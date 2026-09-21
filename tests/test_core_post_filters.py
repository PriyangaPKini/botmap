"""`contains` runs after the scan, through both the count and the read path."""

import pyarrow as pa
import pyarrow.dataset as ds
import pytest

from botmap.core import count_rows, record_batch_reader
from botmap.filters import ParsedFilter, apply_post_filters, combine, parse_where_expr

_TAXONOMY = pa.struct([
    ("primary", pa.string()),
    ("hierarchy", pa.list_(pa.string())),
])


def _places_table():
    return pa.table({
        "id": ["steak", "pizza", "books", "unknown"],
        "name": ["Prime Cut", "Slice", "Pages", "Mystery"],
        "taxonomy": pa.array([
            {"primary": "steakhouse",
             "hierarchy": ["food_and_drink", "restaurant", "steakhouse"]},
            {"primary": "pizza_restaurant",
             "hierarchy": ["food_and_drink", "restaurant", "pizza_restaurant"]},
            {"primary": "bookstore", "hierarchy": ["shopping", "bookstore"]},
            None,
        ], type=_TAXONOMY),
    })


@pytest.fixture
def in_memory_places(monkeypatch):
    """Serve the in-memory table wherever core would open the S3 dataset."""
    places = ds.dataset(_places_table())
    monkeypatch.setattr("botmap.core.ds.dataset", lambda *args, **kwargs: places)


def _where(*exprs):
    return [parse_where_expr(e) for e in exprs]


def _read_ids(**kwargs):
    reader = record_batch_reader("place", release="2026-08-19.0", **kwargs)
    return reader.read_all().column("id").to_pylist()


class TestCombine:
    def test_contains_is_held_back_for_after_the_scan(self):
        schema = _places_table().schema
        pushdown, post = combine(
            _where("name=Slice", "taxonomy.hierarchy contains restaurant"), schema)
        assert pushdown is not None
        assert post == [ParsedFilter("taxonomy.hierarchy", "contains", "restaurant")]

    def test_scalar_filters_alone_have_no_post_filters(self):
        pushdown, post = combine(_where("name=Slice"), _places_table().schema)
        assert pushdown is not None
        assert post == []

    def test_contains_alone_has_no_pushdown(self):
        pushdown, post = combine(
            _where("taxonomy.hierarchy contains restaurant"), _places_table().schema)
        assert pushdown is None
        assert len(post) == 1


class TestApplyPostFilters:
    def test_keeps_rows_matching_every_filter(self):
        batch = _places_table().to_batches()[0]
        kept = apply_post_filters(batch, _where(
            "taxonomy.hierarchy contains restaurant",
            "taxonomy.hierarchy contains steakhouse"))
        assert kept.column("id").to_pylist() == ["steak"]


@pytest.mark.usefixtures("in_memory_places")
class TestQueryPath:
    def test_read_returns_every_child_of_the_parent(self):
        ids = _read_ids(where_filters=_where("taxonomy.hierarchy contains restaurant"))
        assert ids == ["steak", "pizza"]

    def test_read_combines_pushdown_and_post_filters(self):
        ids = _read_ids(where_filters=_where(
            "taxonomy.hierarchy contains restaurant", "name=Slice"))
        assert ids == ["pizza"]

    def test_projection_drops_the_field_read_only_for_filtering(self):
        reader = record_batch_reader(
            "place", release="2026-08-19.0", columns=["id"],
            where_filters=_where("taxonomy.hierarchy contains restaurant"))
        table = reader.read_all()
        assert table.schema.names == ["id"]
        assert table.column("id").to_pylist() == ["steak", "pizza"]

    def test_count_applies_post_filters(self):
        assert count_rows("place", release="2026-08-19.0",
                          where_filters=_where("taxonomy.hierarchy contains restaurant")) == 2

    def test_count_without_post_filters_is_unchanged(self):
        assert count_rows("place", release="2026-08-19.0",
                          where_filters=_where("name=Slice")) == 1
