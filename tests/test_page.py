"""The preview page is JavaScript, so it gets parsed before it ships.

A syntax error anywhere in a <script> block kills the whole block, and the
symptom is a page that renders its static HTML and nothing else -- no device
buttons, no rows, no error a person would see without opening a console. That
happened once, to a `let sync` colliding with an existing `function sync()`,
and the only honest defence is to parse it.
"""

import json
import re
import shutil
import subprocess

import pytest

from art.view import PAGE, device_list


def _script(data=None) -> str:
    page = (PAGE.replace("__TITLE__", "t").replace("__SUB__", "s")
                .replace("__DATA__", json.dumps(data or _data())))
    return re.search(r"<script>(.*?)</script>", page, re.S).group(1)


def _data():
    return {"devices": device_list(), "subject": "x", "editable": "cand",
            "available": [], "edits": {}, "issues": [], "effects": {},
            "catalogue": [], "height_tiles": 1.0, "sheet": "x",
            "rows": [{"name": "run", "frames": [[0, 0, 4, 4, 0, 2]], "src_h": 4,
                      "spread": 0, "variants": [
                          {"label": "today", "image": "a.png", "ref_h": 4,
                           "frames": [[0, 0, 4, 4, 0, 2]]}]}]}


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_the_page_script_parses():
    node = shutil.which("node")
    proc = subprocess.run([node, "--input-type=module", "--check"],
                          input=_script(), text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_no_identifier_is_declared_twice():
    """The exact failure: `let sync` beside `function sync()`."""
    # Column zero only: the same name inside two different functions is fine,
    # and it is the TOP-level collision that kills the block.
    script = _script()
    declared = re.findall(r"^(?:let|const|var|function)\s+([A-Za-z_$][\w$]*)",
                          script, re.M)
    dupes = {n for n in declared if declared.count(n) > 1}
    assert not dupes, f"declared more than once at top level: {sorted(dupes)}"


def test_the_data_placeholder_is_substituted():
    assert "__DATA__" not in _script() and "__TITLE__" not in _script()
