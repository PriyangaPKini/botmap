"""A zero-row place query with a category filter explains itself on stderr."""

import json

import pyarrow as pa
import pytest
from click.testing import CliRunner

from botmap.cli import cli

_BBOX = "-71.16,42.35,-71.06,42.40"
_WRONG_FIELD = "is a taxonomy.primary value, not a basic_category"


class _NullWriter:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _EmptyReader:
    schema = pa.schema([("geometry", pa.binary())])

    def read_next_batch(self):
        raise StopIteration


def _vet_batches(*args, **kwargs):
    return [pa.RecordBatch.from_pydict({
        "taxonomy": pa.array([{"primary": "veterinarian"}],
                             pa.struct([("primary", pa.string())])),
        "basic_category": ["animal_or_pet_service"],
    })]


@pytest.fixture
def zero_rows(monkeypatch):
    """Every query matches nothing; record whether the hint scan ran."""
    scans = []

    def category_batches(*args, **kwargs):
        scans.append(args)
        return _vet_batches()

    monkeypatch.setattr("botmap.cli.get_latest_release", lambda: "2026-08-19.0")
    monkeypatch.setattr("botmap.cli.count_rows", lambda *a, **k: 0)
    monkeypatch.setattr("botmap.cli.record_batch_reader", lambda *a, **k: _EmptyReader())
    monkeypatch.setattr("botmap.cli.get_writer", lambda *a, **k: _NullWriter())
    monkeypatch.setattr("botmap.cli.copy", lambda *a, **k: 0)
    monkeypatch.setattr("botmap.cli.save_state", lambda *a, **k: None)
    monkeypatch.setattr("botmap.cli.column_batches", category_batches)
    return scans


def _run(*args):
    return CliRunner().invoke(cli, list(args))


@pytest.mark.parametrize("command", [
    ["count", "-t", "place", "--bbox", _BBOX],
    ["sample", "-t", "place", "--bbox", _BBOX],
    ["at", "42.37,-71.11", "-t", "place"],
])
def test_wrong_vocabulary_is_explained(zero_rows, command):
    result = _run(*command, "--where", "basic_category=veterinarian")
    assert result.exit_code == 0, result.output
    assert _WRONG_FIELD in result.stderr


def test_places_basic_category_flag_is_explained(zero_rows):
    result = _run("places", "--bbox", _BBOX, "--basic-category", "veterinarian")
    assert result.exit_code == 0, result.output
    assert _WRONG_FIELD in result.stderr


def test_json_stdout_stays_clean(zero_rows):
    result = _run("--json", "count", "-t", "place", "--bbox", _BBOX,
                  "--where", "basic_category=veterinarian")
    assert json.loads(result.stdout)["count"] == 0
    assert _WRONG_FIELD in result.stderr


def test_non_place_type_skips_the_hint_scan(zero_rows):
    _run("count", "-t", "building", "--bbox", _BBOX, "--where", "class=house")
    assert zero_rows == []


def test_place_query_without_category_filter_skips_the_hint_scan(zero_rows):
    _run("count", "-t", "place", "--bbox", _BBOX, "--where", "name=Bean")
    assert zero_rows == []


def test_nonzero_count_skips_the_hint_scan(zero_rows, monkeypatch):
    monkeypatch.setattr("botmap.cli.count_rows", lambda *a, **k: 3)
    _run("count", "-t", "place", "--bbox", _BBOX, "--where", "basic_category=veterinarian")
    assert zero_rows == []


def test_failed_hint_scan_leaves_the_result_intact(zero_rows, monkeypatch):
    def unreachable(*args, **kwargs):
        raise OSError("S3 unreachable")

    monkeypatch.setattr("botmap.cli.column_batches", unreachable)
    result = _run("count", "-t", "place", "--bbox", _BBOX,
                  "--where", "basic_category=veterinarian")
    assert result.exit_code == 0
    assert result.stdout.strip() == "0"


def test_arrow_error_in_hint_scan_leaves_the_result_intact(zero_rows, monkeypatch):
    def broken(*args, **kwargs):
        raise pa.ArrowInvalid("unreadable fragment")

    monkeypatch.setattr("botmap.cli.column_batches", broken)
    result = _run("count", "-t", "place", "--bbox", _BBOX,
                  "--where", "basic_category=veterinarian")
    assert result.exit_code == 0
    assert result.stdout.strip() == "0"

