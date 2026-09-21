"""Help text uses the same filter and category terms as the Skill."""

import pytest
from click.testing import CliRunner

from botmap.cli import cli


def _commands_with_where():
    return sorted(name for name, command in cli.commands.items()
                  if any(p.name == "where_exprs" for p in command.params))


def _help(*args):
    return " ".join(CliRunner().invoke(cli, [*args, "--help"]).output.split())


@pytest.mark.parametrize("command", _commands_with_where())
def test_where_help_lists_every_operator(command):
    text = _help(command)
    for operator in ("~", "contains", "in"):
        assert operator in text, f"{command} --help lacks {operator!r}"
    assert "substring" in text


@pytest.mark.parametrize("command,field", [
    ("categories", "taxonomy.primary"),
    ("basic-categories", "basic_category"),
])
def test_enumeration_help_names_its_field_and_find(command, field):
    text = _help(command)
    assert field in text
    assert "--find" in text and "substring" in text


def test_places_help_names_both_category_fields():
    text = _help("places")
    assert "taxonomy.primary" in text
    assert "basic_category" in text
