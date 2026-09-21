"""`--category` is a `places` flag; the polymorphic commands reject it with guidance."""

import pytest
from click.testing import CliRunner

from botmap.cli import cli

REJECTING = ["count", "sample", "at", "download"]


def _invoke(monkeypatch, command, flag, value):
    monkeypatch.setattr("botmap.cli.get_latest_release", lambda: "2025-12-17.0")
    if command == "at":
        argv = ["at", "42.36,-71.10", "-t", "place"]
    else:
        argv = [command, "-t", "place", "--bbox", "-71.1,42.3,-71.0,42.4"]
    return CliRunner().invoke(cli, argv + [flag, value])


@pytest.mark.parametrize("command", REJECTING)
def test_category_flag_names_the_where_filter(monkeypatch, command):
    result = _invoke(monkeypatch, command, "--category", "asian_restaurant")
    assert result.exit_code != 0
    assert "--where taxonomy.primary=asian_restaurant" in result.output
    assert "places" in result.output


@pytest.mark.parametrize("command", REJECTING)
def test_basic_category_flag_names_the_where_filter(monkeypatch, command):
    result = _invoke(monkeypatch, command, "--basic-category", "restaurant")
    assert result.exit_code != 0
    assert "--where basic_category=restaurant" in result.output


@pytest.mark.parametrize("command", REJECTING)
def test_rejected_flag_stays_hidden_from_help(command):
    result = CliRunner().invoke(cli, [command, "--help"])
    assert result.exit_code == 0
    assert "--category" not in result.output
    assert "--basic-category" not in result.output


def test_places_keeps_a_working_category_flag(monkeypatch):
    """The redirect must not touch the verb the flag belongs to."""
    result = CliRunner().invoke(cli, ["places", "--help"])
    assert result.exit_code == 0
    assert "--category" in result.output
    assert "--basic-category" in result.output
