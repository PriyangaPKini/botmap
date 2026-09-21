"""The zero-result hint reads only category columns, from the dataset already opened."""

import pyarrow as pa
import pyarrow.dataset as ds
import pytest

from botmap.core import count_rows, place_category_batches

_RELEASE = "2026-08-19.0"


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


def test_reads_only_the_category_columns(monkeypatch):
    _serve(monkeypatch, _places())
    assert _column_names(place_category_batches(release=_RELEASE)) == [
        ["taxonomy", "basic_category"]]


def test_release_without_basic_category_reads_taxonomy_alone(monkeypatch):
    _serve(monkeypatch, _places(with_basic_category=False))
    assert _column_names(place_category_batches(release=_RELEASE)) == [["taxonomy"]]


def test_reuses_the_dataset_the_query_already_opened(monkeypatch):
    opened = _serve(monkeypatch, _places())
    count_rows("place", release=_RELEASE, stac=True)  # as the CLI calls it
    list(place_category_batches(release=_RELEASE))
    assert len(opened) == 1
