"""Tests for the releases module."""

import pytest
from botmap import releases
from botmap.core import (
    _RELEASE_RE,
    _release_from_href,
    get_available_releases,
    get_latest_release,
)


def test_list_releases():
    """Test that list_releases returns a non-empty list."""
    all_releases = releases.list_releases()
    assert isinstance(all_releases, list)
    assert len(all_releases) > 0
    # Should be sorted newest first
    assert all_releases == sorted(all_releases, reverse=True)


def test_get_latest_release():
    """Test that get_latest_release returns a valid release string."""
    latest = get_latest_release()
    assert isinstance(latest, str)
    assert len(latest) > 0
    # Should be in the format YYYY-MM-DD.N
    assert "-" in latest
    assert "." in latest


def test_release_exists():
    """Test release_exists with a known release."""
    latest = get_latest_release()
    assert releases.release_exists(latest) is True
    assert releases.release_exists("invalid-release") is False


def test_get_next_release():
    """Test get_next_release logic."""
    all_releases = releases.list_releases()
    if len(all_releases) < 2:
        pytest.skip("Need at least 2 releases to test get_next_release")

    # Latest release should have no next release
    latest = all_releases[0]
    assert releases.get_next_release(latest) is None

    # Second-to-last release should return latest
    second_latest = all_releases[1]
    assert releases.get_next_release(second_latest) == latest

    # Invalid release should return None
    assert releases.get_next_release("invalid-release") is None


def test_release_from_href_absolute():
    """Catalog child links are absolute URLs as of 2026."""
    assert _release_from_href(
        "https://stac.overturemaps.org/2026-08-19.0/catalog.json"
    ) == "2026-08-19.0"


def test_release_from_href_relative():
    """Older catalogs served relative hrefs; both must parse."""
    assert _release_from_href("./2026-08-19.0/catalog.json") == "2026-08-19.0"


def test_release_from_href_no_filename():
    """An href without a trailing document still yields the release."""
    assert _release_from_href(
        "https://stac.overturemaps.org/2026-08-19.0/"
    ) == "2026-08-19.0"


def test_release_from_href_without_release_id():
    """A link carrying no release ID yields None rather than a path fragment."""
    assert _release_from_href("https://stac.overturemaps.org/catalog.json") is None
    assert _release_from_href("") is None


def test_available_releases_are_release_ids():
    """Guard the parse bug: every entry must look like a release, not a URL part."""
    all_releases, latest = get_available_releases()
    assert all_releases, "catalog returned no releases"
    for r in all_releases:
        assert _RELEASE_RE.fullmatch(r), f"{r!r} is not a release ID"
    assert latest in all_releases
