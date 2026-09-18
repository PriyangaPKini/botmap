"""Tests for the `categories` command."""

import json

import pyarrow as pa
import pytest
from click.testing import CliRunner

from botmap.cli import cli


def test_categories_returns_top_values(monkeypatch):
    """Stub a reader that yields a batch with category values; verify top-N counting."""

    schema = pa.schema([
        ("categories", pa.struct([("primary", pa.string())])),
    ])

    rows = (
        [{"categories": {"primary": "restaurant"}}] * 10 +
        [{"categories": {"primary": "cafe"}}] * 7 +
        [{"categories": {"primary": "bar"}}] * 3 +
        [{"categories": {"primary": "hotel"}}] * 1
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
        "--json", "categories", "-t", "place",
        "--bbox", "-71.1,42.3,-71.0,42.4", "--top", "3",
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data == [
        {"value": "restaurant", "count": 10},
        {"value": "cafe", "count": 7},
        {"value": "bar", "count": 3},
    ]
    assert "truncated" in result.stderr


def test_categories_search_filters_values_case_insensitively(monkeypatch):
    """--search filters the counted category vocabulary without breaking JSON stdout."""

    schema = pa.schema([
        ("categories", pa.struct([("primary", pa.string())])),
    ])
    rows = (
        [{"categories": {"primary": "bicycle_parking"}}] * 10 +
        [{"categories": {"primary": "bicycle_rental"}}] * 3 +
        [{"categories": {"primary": "car_parking"}}] * 7
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
        "--json", "categories", "-t", "place",
        "--bbox", "-71.1,42.3,-71.0,42.4", "--search", "BICYCLE",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [
        {"value": "bicycle_parking", "count": 10},
        {"value": "bicycle_rental", "count": 3},
    ]


def test_categories_search_no_matches_keeps_empty_json_stdout(monkeypatch):
    """A failed search returns [] on stdout and a diagnostic on stderr."""

    schema = pa.schema([
        ("categories", pa.struct([("primary", pa.string())])),
    ])
    rows = [{"categories": {"primary": "restaurant"}}]

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
        "--json", "categories", "-t", "place",
        "--bbox", "-71.1,42.3,-71.0,42.4", "--search", "bicycle",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []
    assert "No categories matching" in result.stderr


def test_categories_non_place_type_with_verb_gives_helpful_error(monkeypatch):
    """`categories -t land_use` should explain `class` and point to the verb."""
    monkeypatch.setattr("botmap.cli.get_latest_release", lambda: "2025-12-17.0")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "categories", "-t", "land_use", "--bbox", "-71.1,42.3,-71.0,42.4",
    ])
    assert result.exit_code != 0
    assert "class" in result.output
    assert "landuse" in result.output
    assert "schema" in result.output


def test_categories_non_place_type_without_verb_gives_schema_hint(monkeypatch):
    """`categories -t infrastructure` should point to schema."""
    monkeypatch.setattr("botmap.cli.get_latest_release", lambda: "2025-12-17.0")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "categories", "-t", "infrastructure", "--bbox", "-71.1,42.3,-71.0,42.4",
    ])
    assert result.exit_code != 0
    assert "schema" in result.output
