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
