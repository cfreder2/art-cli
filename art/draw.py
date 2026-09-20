"""Driving the generator.

Image generation runs through `codex exec --enable image_generation`, which
authenticates with the user's ChatGPT subscription rather than an API key. Two
consequences shape this module.

**It costs a finite allowance.** So every other verb in this tool works without
it, `--dry-run` prints exactly what would be sent, and a generation is only
ever started deliberately.

**Codex is an agent with a working directory, not a function returning an
image.** It writes more than the plate -- scratch files, variants, whole
invented directories guessed from the prompt. Pointed at a game repo it leaves
those lying among real assets. So it is given a scratch directory of its own
and the game is never its cwd; the plate is collected from
`~/.codex/generated_images`, which is where it lands regardless.

The model: `-m` selects the AGENT, not the image model. The image comes from
OpenAI's media service (the C2PA manifest in the output names `gpt-image`), and
there is no flag that pins it. The agent is only relaying a prompt, so a small
fast one is the right default -- it is not the thing doing the drawing.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

CODEX_IMAGES = Path.home() / ".codex" / "generated_images"


class DrawError(RuntimeError):
    pass


@dataclass
class Drawn:
    path: Path
    seconds: float
    candidate: int


def available() -> bool:
    return shutil.which("codex") is not None


def _snapshot() -> set[Path]:
    if not CODEX_IMAGES.is_dir():
        return set()
    return set(CODEX_IMAGES.glob("*/*.png"))


def _newest_since(before: set[Path]) -> Path | None:
    made = [p for p in _snapshot() if p not in before]
    if not made:
        return None
    return max(made, key=lambda p: p.stat().st_mtime)


def generate(
    prompt: str,
    references: list[str],
    out: Path,
    model: str | None = None,
    timeout: int = 600,
) -> Drawn:
    """Run one generation and copy the plate to `out`."""
    if not available():
        raise DrawError(
            "The `codex` CLI is not on PATH. Generation runs through Codex "
            "(authenticated with your ChatGPT subscription) -- install it, then "
            "`codex login`. Everything else in this tool works without it, and "
            "`art cut --from <file>` takes a sheet made anywhere."
        )

    command = ["codex", "exec", "--enable", "image_generation",
               "--skip-git-repo-check"]
    if model:
        command += ["-m", model]
    # References are numbered in the order they are passed, because the prompt
    # addresses them as "Image 1", "Image 2". Absolute, so they do not depend
    # on where this process runs.
    for ref in references:
        p = Path(ref).resolve()
        if p.exists():
            command += ["-i", str(p)]

    # The prompt goes in on stdin, NOT as the positional argument. `--image`
    # is variadic (`-i, --image <FILE>...`), so a trailing positional prompt is
    # swallowed as one more filename and codex exits with "No prompt provided
    # via stdin" -- which is the truth, just not an obvious one.

    before = _snapshot()
    scratch = Path(tempfile.mkdtemp(prefix="art-codex-"))
    started = time.time()
    try:
        result = subprocess.run(command, cwd=scratch, input=prompt,
                                capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise DrawError(f"codex exec timed out after {timeout}s.") from exc
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    elapsed = time.time() - started

    plate = _newest_since(before)
    if plate is None:
        tail = (result.stderr or result.stdout or "").strip().splitlines()
        hint = tail[-1] if tail else "no output"
        raise DrawError(
            f"codex exec wrote no image (exit={result.returncode}). Last line: {hint}"
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(plate, out)
    return Drawn(out, elapsed, 1)


def next_candidate(directory: Path, stem: str) -> tuple[Path, int]:
    """Candidates are kept, not overwritten: a generator produces variations and
    picking one is a judgement `accept` records rather than makes."""
    directory.mkdir(parents=True, exist_ok=True)
    n = 1
    while (directory / f"{stem}-{n}.png").exists():
        n += 1
    return (directory / f"{stem}-{n}.png", n)
