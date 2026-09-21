"""The read path can project columns, so enumeration need not read every field."""

import pyarrow as pa
import pyarrow.dataset as ds
import pytest

from botmap.core import _record_batch_reader_from_dataset


def _dataset():
    table = pa.table({
        "id": pa.array(["a", "b"], pa.string()),
        "taxonomy": pa.array([{"primary": "cafe"}, {"primary": "hotel"}],
                             pa.struct([("primary", pa.string())])),
        "geometry": pa.array([b"\x01", b"\x02"], pa.binary()),
    })
    return ds.dataset(table)


def _drain(reader):
    batches = []
    while True:
        try:
            batches.append(reader.read_next_batch())
        except StopIteration:
            break
    return batches


def test_without_columns_every_field_is_read():
    reader = _record_batch_reader_from_dataset(_dataset())
    assert reader.schema.names == ["id", "taxonomy", "geometry"]


def test_columns_projects_to_the_named_fields():
    reader = _record_batch_reader_from_dataset(_dataset(), columns=["taxonomy"])
    assert reader.schema.names == ["taxonomy"]
    batches = _drain(reader)
    assert [b.num_rows for b in batches] == [2]


def test_projection_without_geometry_does_not_mislabel_a_field():
    """The geoarrow adapter tags a `geometry` column; absent it, tag nothing."""
    reader = _record_batch_reader_from_dataset(_dataset(), columns=["id"])
    assert reader.schema.names == ["id"]
    assert reader.schema.field("id").metadata in (None, {})


def test_projection_keeps_geometry_tagged_when_included():
    reader = _record_batch_reader_from_dataset(_dataset(), columns=["id", "geometry"])
    meta = reader.schema.field("geometry").metadata or {}
    assert meta.get(b"ARROW:extension:name") == b"geoarrow.wkb"


def test_read_error_goes_to_stderr_not_stdout(capsys):
    """stdout carries data; an error printed there would corrupt it."""
    assert _record_batch_reader_from_dataset(_dataset(), columns=["missing"]) is None
    out, err = capsys.readouterr()
    assert out == ""
    assert "Error reading dataset" in err


def test_stac_errors_go_to_stderr_not_stdout(capsys, monkeypatch):
    from botmap.core import _get_files_from_stac
    from botmap.models import BBox

    def unreachable(url):
        raise OSError("offline")

    monkeypatch.setattr("botmap.core.urlopen", unreachable)
    assert _get_files_from_stac("places", "place", BBox(0, 0, 1, 1), "2026-08-19.0") is None
    out, err = capsys.readouterr()
    assert out == ""
    assert "Error reading STAC index" in err
