"""Every command is reachable, and every helper it calls exists.

Twice now a splice of this file removed a module-level helper that only one
command used, and nothing noticed until that command was run -- once mid-way
through a batch of eleven generations. A NameError inside a click callback is
invisible until the callback runs, so the callbacks get run.
"""

import pytest
from click.testing import CliRunner

from art.cli import main

EXPECTED = {"init", "status", "audit", "plan", "prompt", "draw", "accept",
            "cut", "check", "pack", "view", "issues", "effects", "template",
            "review", "runtime"}


def test_every_command_is_registered():
    assert EXPECTED <= set(main.commands), EXPECTED - set(main.commands)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_command_has_help(name):
    result = CliRunner().invoke(main, [name, "--help"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_command_runs_far_enough_to_need_a_project(name, tmp_path):
    """Invoked outside a project, every command must fail on the MISSING
    art.yaml -- not on a NameError, an AttributeError or a TypeError, which is
    what a removed helper looks like."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, [name], catch_exceptions=True)
    if result.exception and not isinstance(result.exception, SystemExit):
        pytest.fail(f"{name} raised {type(result.exception).__name__}: "
                    f"{result.exception}")
