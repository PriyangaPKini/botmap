"""A follow-up scan reads only the columns it needs, from the dataset already opened."""

import pyarrow as pa
import pyarrow.dataset as ds
import pytest

from botmap.core import _prepare_query, column_batches, count_rows

_RELEASE = "2026-08-19.0"
_BBOX = (-71.16, 42.35, -71.06, 42.40)


def _places(with_basic_category=True):
    columns = {
        "id": ["a"],
        "taxonomy": pa.array([{"primary": "cafe"}], pa.struct([("primary", pa.string())])),
        "name": ["Bean"],
    }
    if with_basic_category:
        columns["basic_category"] = ["cafe"]
    return ds.dataset(pa.table(columns))


def _serve(monkeypatch, dataset):
    """Serve `dataset` wherever core opens one, and count how often it does."""
    opened = []

    def fake_dataset(*args, **kwargs):
        opened.append(args)
        return dataset

    monkeypatch.setattr("botmap.core.ds.dataset", fake_dataset)
    return opened


def _column_names(batches):
    return [b.schema.names for b in batches]


def test_reads_only_the_named_columns(monkeypatch):
    _serve(monkeypatch, _places())
    batches = column_batches("place", ("taxonomy", "basic_category"), release=_RELEASE)
    assert _column_names(batches) == [["taxonomy", "basic_category"]]


def test_skips_columns_the_release_lacks(monkeypatch):
    _serve(monkeypatch, _places(with_basic_category=False))
    batches = column_batches("place", ("taxonomy", "basic_category"), release=_RELEASE)
    assert _column_names(batches) == [["taxonomy"]]


def test_reuses_the_dataset_the_query_already_opened(monkeypatch):
    opened = _serve(monkeypatch, _places())
    count_rows("place", release=_RELEASE, stac=True)  # as the CLI calls it
    list(column_batches("place", ("taxonomy",), release=_RELEASE))
    assert len(opened) == 1


def _stac(monkeypatch, files):
    """Make the STAC lookup return `files` (None means it failed); count the calls."""
    calls = []

    def lookup(*args):
        calls.append(args)
        return files

    monkeypatch.setattr("botmap.core._get_files_from_stac", lookup)
    return calls


def test_successful_stac_lookup_is_cached(monkeypatch):
    _serve(monkeypatch, _places())
    calls = _stac(monkeypatch, ["bucket/part-0.parquet"])
    _prepare_query("place", _BBOX, _RELEASE, stac=True)
    _prepare_query("place", _BBOX, _RELEASE, stac=True)
    assert len(calls) == 1


def test_failed_stac_lookup_is_retried_not_cached(monkeypatch):
    """A brief STAC outage must not pin the slow whole-partition scan for the process."""
    _serve(monkeypatch, _places())
    calls = _stac(monkeypatch, None)
    assert _prepare_query("place", _BBOX, _RELEASE, stac=True) is not None
    _prepare_query("place", _BBOX, _RELEASE, stac=True)
    assert len(calls) == 2
