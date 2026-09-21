"""`--find` narrows the values an enumeration command lists."""

import json

import pyarrow as pa
from click.testing import CliRunner

from botmap.cli import cli

BBOX = ["--bbox", "-71.1,42.3,-71.0,42.4"]


def _stub(monkeypatch, column, values, struct=False):
    """Stub the read path with one batch of `values`; capture the projection."""
    if struct:
        schema = pa.schema([(column, pa.struct([("primary", pa.string())]))])
        rows = [{column: {"primary": v}} for v in values]
    else:
        schema = pa.schema([(column, pa.string())])
        rows = [{column: v} for v in values]
    captured = {}

    class _Reader:
        def __init__(self):
            self.schema = schema
            self._done = False

        def read_next_batch(self):
            if self._done:
                raise StopIteration
            self._done = True
            return pa.RecordBatch.from_pylist(rows, schema=schema)

    def fake(*a, **k):
        captured["columns"] = k.get("columns")
        return _Reader()

    monkeypatch.setattr("botmap.cli.record_batch_reader", fake)
    monkeypatch.setattr("botmap.cli.get_latest_release", lambda: "2025-12-17.0")
    return captured


def _values(output):
    return [r["value"] for r in json.loads(output)]


class TestCategoriesFind:
    def test_find_narrows_to_matching_values(self, monkeypatch):
        _stub(monkeypatch, "taxonomy",
              ["veterinarian", "vet_supply_store", "bakery", "cafe"], struct=True)
        r = CliRunner().invoke(cli, ["--json", "categories", "-t", "place", *BBOX, "--find", "vet"])
        assert r.exit_code == 0, r.output
        assert sorted(_values(r.output)) == ["vet_supply_store", "veterinarian"]

    def test_find_is_case_insensitive(self, monkeypatch):
        _stub(monkeypatch, "taxonomy", ["Veterinarian", "bakery"], struct=True)
        r = CliRunner().invoke(cli, ["--json", "categories", "-t", "place", *BBOX, "--find", "VET"])
        assert _values(r.output) == ["Veterinarian"]

    def test_find_is_substring_not_semantic(self, monkeypatch):
        """`animal` must not pull in `veterinarian`; this is not semantic search."""
        _stub(monkeypatch, "taxonomy", ["veterinarian", "animal_shelter"], struct=True)
        r = CliRunner().invoke(cli, ["--json", "categories", "-t", "place", *BBOX, "--find", "animal"])
        assert _values(r.output) == ["animal_shelter"]

    def test_no_match_returns_empty(self, monkeypatch):
        _stub(monkeypatch, "taxonomy", ["bakery"], struct=True)
        r = CliRunner().invoke(cli, ["--json", "categories", "-t", "place", *BBOX, "--find", "zzz"])
        assert json.loads(r.output) == []

    def test_without_find_everything_is_listed(self, monkeypatch):
        _stub(monkeypatch, "taxonomy", ["veterinarian", "bakery"], struct=True)
        r = CliRunner().invoke(cli, ["--json", "categories", "-t", "place", *BBOX])
        assert sorted(_values(r.output)) == ["bakery", "veterinarian"]


class TestBasicCategoriesFind:
    def test_find_narrows_basic_category_values(self, monkeypatch):
        _stub(monkeypatch, "basic_category", ["restaurant", "fast_food_restaurant", "hotel"])
        r = CliRunner().invoke(cli, ["--json", "basic-categories", "-t", "place", *BBOX,
                                     "--find", "restaurant"])
        assert r.exit_code == 0, r.output
        assert sorted(_values(r.output)) == ["fast_food_restaurant", "restaurant"]


class TestProjection:
    def test_categories_reads_only_its_column(self, monkeypatch):
        captured = _stub(monkeypatch, "taxonomy", ["cafe"], struct=True)
        CliRunner().invoke(cli, ["--json", "categories", "-t", "place", *BBOX])
        assert captured["columns"] == ["taxonomy"]

    def test_basic_categories_reads_only_its_column(self, monkeypatch):
        captured = _stub(monkeypatch, "basic_category", ["hotel"])
        CliRunner().invoke(cli, ["--json", "basic-categories", "-t", "place", *BBOX])
        assert captured["columns"] == ["basic_category"]
