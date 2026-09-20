"""Every module-level helper a function calls is actually defined.

Three separate times, a splice of cli.py removed a top-level helper that only
one code path used -- `_issue_note`, `_groups_or_empty`, `_backdrop_warning` --
and each stayed invisible until that path ran. Once that was a third of the way
into a batch of eleven generations.

This deliberately checks one narrow thing rather than resolving scopes properly:
calls to `_private` helpers, which by convention live at module level. A full
scope analyser is a linter, and a linter that reports lambda arguments as
undefined teaches people to ignore it.
"""

import ast
import builtins
import pathlib

import pytest

MODULES = sorted(pathlib.Path(__file__).parent.parent.joinpath("art").glob("*.py"))


def _module_level(tree):
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names |= {(a.asname or a.name).split(".")[0] for a in node.names}
    return names


def _nested(tree):
    """Helpers defined inside another function -- visible to their siblings."""
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_every_private_helper_called_is_defined(path):
    tree = ast.parse(path.read_text())
    defined = _module_level(tree) | _nested(tree)
    missing = sorted({
        f"{n.func.id}() (line {n.lineno})"
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id.startswith("_") and not n.func.id.startswith("__")
        and n.func.id not in defined and not hasattr(builtins, n.func.id)
    })
    assert not missing, path.name + " calls undefined helpers:\n" + "\n".join(missing)


def test_the_check_would_catch_a_deleted_helper(tmp_path):
    """The failure it exists for, so the check itself cannot rot silently."""
    f = tmp_path / "m.py"
    f.write_text("def keep():\n    return _gone(1)\n")
    tree = ast.parse(f.read_text())
    defined = _module_level(tree) | _nested(tree)
    calls = {n.func.id for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id.startswith("_")}
    assert calls - defined == {"_gone"}
