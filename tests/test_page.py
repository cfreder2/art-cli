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


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_a_sway_does_not_reverse_when_the_sprite_flips():
    """A sway is wind. Wind does not change direction because the character
    turned around -- but `ctx.scale(-1, 1)` before `ctx.rotate` puts the
    rotation inside the mirror and negates it. game.js flips last and was
    right; the emitted runtime flipped first and leaned the head the other way.
    """
    import json
    import pathlib as _p

    runtime = _p.Path(__file__).parent.parent / "art" / "runtime.js"
    harness = runtime.read_text() + """
// A ctx that only records the transform, composed as a 2x2 matrix.
const mul = (a, b) => [a[0]*b[0]+a[2]*b[1], a[1]*b[0]+a[3]*b[1],
                       a[0]*b[2]+a[2]*b[3], a[1]*b[2]+a[3]*b[3]];
function probe(flip) {
  let m = [1, 0, 0, 1];
  const ctx = {
    save() {}, restore() {}, translate() {}, drawImage() {},
    rotate(t) { m = mul(m, [Math.cos(t), Math.sin(t), -Math.sin(t), Math.cos(t)]); },
    scale(x, y) { m = mul(m, [x, 0, 0, y]); },
    set globalAlpha(v) {},
  };
  const atlas = { axi: { idle: [[0, 0, 10, 10, 0, 5]] }, scales: {}, anims: {} };
  const sheet = new Sheet(atlas, {});
  const a = new Actor(sheet, 'axi', { ref: 'idle', tiles: 1,
                                      effects: { idle: { sway: { degrees: 10, hz: 0 } } } });
  a.play('idle');
  // hz 0 and now 0 gives sin(0) = 0, so drive the phase to a quarter turn.
  a.effects.idle.sway.phase = Math.PI / 2;
  a.draw(ctx, 0, 0, { tile: 1, flip, now: 0 });
  // Where the top of the head lands.
  return m[0] * 0 + m[2] * -1;
}
console.log(JSON.stringify([probe(1), probe(-1)]));
"""
    node = shutil.which("node")
    proc = subprocess.run([node, "--input-type=module"], input=harness,
                          text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    facing_right, facing_left = json.loads(proc.stdout)
    assert abs(facing_right) > 1e-6, "the sway did nothing; the probe is wrong"
    assert facing_right == pytest.approx(facing_left), (
        f"the sway reversed when the sprite flipped: {facing_right:.3f} "
        f"facing right, {facing_left:.3f} facing left")


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_a_named_phase_does_not_kill_the_effect():
    """`phase` NAMES how an offset is chosen -- 'none', 'x', 'random' -- so it
    arrives as a string as often as a number, and the packer writes 'none' for
    AXI's breathing frog. `e.phase || 0` let that through into
    `2 * Math.PI * hz * t + 'none'`, which is string concatenation: the wave
    went NaN and the frog stopped breathing with no error anywhere."""
    import json
    import pathlib as _p

    runtime = _p.Path(__file__).parent.parent / "art" / "runtime.js"
    harness = runtime.read_text() + """
function heightAt(phase) {
  let drawn = null;
  const ctx = {
    save() {}, restore() {}, translate() {}, rotate() {},
    scale(x) { drawn = x; }, drawImage() {}, set globalAlpha(v) {},
  };
  const atlas = {
    npc: { frog_idle: [[0, 0, 10, 10, 0, 5]] },
    scales: {},
    anims: { 'npc/frog_idle': { effects: { breathe: { amount: 0.1, hz: 1, phase } } } },
  };
  // Quarter of a second at 1Hz puts sin() at its peak, so a live effect must
  // move and a dead one must not.
  new Sheet(atlas, {}).drawFrame(ctx, 'npc', 'frog_idle', 0,
                                 { x: 0, y: 0, tile: 1, scale: 1, now: 250 });
  return drawn;
}
console.log(JSON.stringify([heightAt('none'), heightAt(0), heightAt('random')]));
"""
    node = shutil.which("node")
    proc = subprocess.run([node, "--input-type=module"], input=harness,
                          text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    named, numeric, random_ = json.loads(proc.stdout)
    assert numeric == pytest.approx(1.1), "the probe itself is wrong"
    for got, label in ((named, "'none'"), (random_, "'random'")):
        assert got is not None and got == pytest.approx(numeric), (
            f"phase={label} gave {got!r}, not the {numeric} a numeric phase "
            "gives -- the effect was silently lost")
