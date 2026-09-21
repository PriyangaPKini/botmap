"""Tests for the `basic-categories` command."""

import json

import pyarrow as pa
from click.testing import CliRunner

from botmap.cli import cli


def test_basic_categories_returns_top_values(monkeypatch):
    """Stub a reader that yields basic_category values; verify top-N counting."""

    schema = pa.schema([
        ("basic_category", pa.string()),
    ])

    rows = (
        [{"basic_category": "restaurant"}] * 10 +
        [{"basic_category": "hotel"}] * 7 +
        [{"basic_category": "pharmacy_and_drug_store"}] * 3 +
        [{"basic_category": None}] * 2
    )

    class _Reader:
        def __init__(self):
            self.schema = schema
            self._done = False

        def read_next_batch(self):
            if self._done:
                raise StopIteration
            self._done = True
            return pa.RecordBatch.from_pylist(rows, schema=schema)

    monkeypatch.setattr("botmap.cli.record_batch_reader",
                        lambda *a, **k: _Reader())
    monkeypatch.setattr("botmap.cli.get_latest_release",
                        lambda: "2025-12-17.0")

    runner = CliRunner()
    result = runner.invoke(cli, [
        "--json", "basic-categories", "-t", "place",
        "--bbox", "-71.1,42.3,-71.0,42.4", "--top", "2",
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data == [
        {"value": "restaurant", "count": 10},
        {"value": "hotel", "count": 7},
    ]


def test_basic_categories_requires_bbox_or_in(monkeypatch):
    monkeypatch.setattr("botmap.cli.get_latest_release", lambda: "2025-12-17.0")
    runner = CliRunner()
    result = runner.invoke(cli, ["basic-categories", "-t", "place"])
    assert result.exit_code != 0
    assert "Provide --bbox or --in" in result.output


def test_basic_categories_rejects_non_place_type(monkeypatch):
    monkeypatch.setattr("botmap.cli.get_latest_release", lambda: "2025-12-17.0")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "basic-categories", "-t", "building", "--bbox", "-71.1,42.3,-71.0,42.4",
    ])
    assert result.exit_code != 0
    assert "place" in result.output
    assert "basic_category" in result.output


def test_basic_categories_human_output_shows_counts_and_values(monkeypatch):
    """Without --json the command prints right-aligned counts beside values."""
    schema = pa.schema([("basic_category", pa.string())])
    rows = (
        [{"basic_category": "restaurant"}] * 4 +
        [{"basic_category": "cafe"}] * 2
    )

    class _Reader:
        def __init__(self):
            self.schema = schema
            self._done = False

        def read_next_batch(self):
            if self._done:
                raise StopIteration
            self._done = True
            return pa.RecordBatch.from_pylist(rows, schema=schema)

    monkeypatch.setattr("botmap.cli.record_batch_reader",
                        lambda *a, **k: _Reader())
    monkeypatch.setattr("botmap.cli.get_latest_release",
                        lambda: "2025-12-17.0")

    runner = CliRunner()
    result = runner.invoke(cli, [
        "basic-categories", "-t", "place",
        "--bbox", "-71.1,42.3,-71.0,42.4",
    ])
    assert result.exit_code == 0, result.output
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert lines == ["         4  restaurant", "         2  cafe"]


def test_basic_categories_resolves_in_place_to_bbox(monkeypatch):
    """`--in NAME` resolves to that division's bbox before scanning."""
    schema = pa.schema([("basic_category", pa.string())])
    captured = {}

    class _Division:
        bbox = (-71.19, 42.23, -70.99, 42.40)

    class _Reader:
        def __init__(self):
            self.schema = schema
            self._done = False

        def read_next_batch(self):
            if self._done:
                raise StopIteration
            self._done = True
            return pa.RecordBatch.from_pylist(
                [{"basic_category": "restaurant"}], schema=schema)

    def fake_reader(type_, bbox, *a, **k):
        captured["bbox"] = bbox
        return _Reader()

    monkeypatch.setattr("botmap.cli._resolve_in_place",
                        lambda name: _Division())
    monkeypatch.setattr("botmap.cli.record_batch_reader", fake_reader)
    monkeypatch.setattr("botmap.cli.get_latest_release",
                        lambda: "2025-12-17.0")

    runner = CliRunner()
    result = runner.invoke(cli, [
        "--json", "basic-categories", "-t", "place", "--in", "Boston, MA",
    ])
    assert result.exit_code == 0, result.output
    assert captured["bbox"] == [-71.19, 42.23, -70.99, 42.40]


def test_basic_categories_bbox_and_in_are_mutually_exclusive(monkeypatch):
    monkeypatch.setattr("botmap.cli.get_latest_release", lambda: "2025-12-17.0")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "basic-categories", "-t", "place",
        "--bbox", "-71.1,42.3,-71.0,42.4", "--in", "Boston, MA",
    ])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_basic_categories_non_place_type_with_verb_points_to_class(monkeypatch):
    """`basic-categories -t land_use` should explain `class` and name the verb."""
    monkeypatch.setattr("botmap.cli.get_latest_release", lambda: "2025-12-17.0")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "basic-categories", "-t", "land_use",
        "--bbox", "-71.1,42.3,-71.0,42.4",
    ])
    assert result.exit_code != 0
    assert "class" in result.output
    assert "landuse" in result.output
