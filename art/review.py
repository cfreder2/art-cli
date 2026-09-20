"""Agentic verification: a model looks at the sheet and says what is wrong.

The measurable rules in `rules.py` catch what a formula can catch -- a frame
that is too short, a row that cut into the wrong number of frames, backdrop
left inside the art. Every defect that actually cost a generation on this
project was outside that set:

    a stub protruding from the base of her tail
    two frogs in one frame
    a doubled tail
    five legs
    gills that drifted blue
    a nose that stopped being her nose

Those are visual judgements. A person made every one of them, by squinting at a
1254px sheet, and that does not survive sixty-six more subjects.

So the sheet is laid out as a NUMBERED contact sheet and handed to a model with
the specific list of things that have gone wrong before. Numbered, because a
finding has to be addressable: "frame 4" is actionable and "one of the frames"
is not -- and a numbered finding drops straight into the same `issues` block
the preview writes, so it becomes art direction on the next draw.

This does not replace looking. It replaces looking FIRST, which is the part
that does not scale.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

# What to ask about. Every line is a defect this project actually shipped or
# nearly shipped, which is why the list is specific rather than "look for
# problems" -- a general ask gets a general answer.
LOOK_FOR = [
    "a limb that is missing, duplicated, or drawn in the wrong place -- count "
    "the legs in EVERY frame and say if any frame has a different number",
    "a stray stub, lump or leftover appendage, especially where the body meets "
    "the tail or where a limb would overlap the body",
    "any body part drawn twice -- two tails, two of an ear, a doubled fin",
    "the character changing between frames: colour, markings, proportions, "
    "face, or a detail present in some frames and not others",
    "anything anatomically wrong for the creature described",
    "a frame that would flicker or jump if these were played in order",
    "more than one character in a single frame",
    "guide lines, labels, text or numbers left inside a frame's ARTWORK -- not "
    "the contact sheet's own numbering, which is not part of the art",
]

PROMPT = """You are reviewing a sprite sheet for defects before it goes into a game.

The character: {description}

The sheet is laid out as a numbered contact sheet. Each frame is labelled with \
its number in the margin ABOVE it. The frames are {count} poses of "{anim}", \
meant to play in order as a loop.

IMPORTANT: the numbered dark strips, the pale backing squares and the thin grey \
borders around each cell are THIS REVIEW SHEET, not the artwork -- they were \
added to show you the frames and are not in the game. Never report them as a \
defect. Judge only what is drawn inside each cell.

Look for each of these, frame by frame:
{checks}

Be specific and be strict -- this art is about to ship. Judge only what you can \
see; do not invent problems to be helpful, and do not excuse a real one.

Reply with ONLY a JSON object, no prose around it:

{{"findings": [{{"frame": <number, or null if it affects the whole sheet>,
                "issue": "<what is wrong, in one sentence>",
                "severity": "high" | "low"}}]}}

If the sheet is clean, reply {{"findings": []}}."""


@dataclass
class Note:
    frame: int | None
    issue: str
    severity: str = "high"

    @property
    def high(self) -> bool:
        return self.severity == "high"


class ReviewError(RuntimeError):
    pass


def contact_sheet(frames: list[Image.Image], out: Path,
                  per_row: int = 5, cell: int = 380) -> Path:
    """Lay the frames out big and numbered, on a neutral ground.

    Numbers go in a margin ABOVE each frame rather than on it, because a label
    touching the art is a label the model reads as part of the character -- the
    same reason the sheet rules forbid it in generated art.
    """
    label_h = 46
    rows = -(-len(frames) // per_row)
    w, h = per_row * cell, rows * (cell + label_h)
    sheet = Image.new("RGB", (w, h), (238, 238, 240))
    d = ImageDraw.Draw(sheet)
    for i, frame in enumerate(frames):
        cx, cy = (i % per_row) * cell, (i // per_row) * (cell + label_h)
        d.rectangle([cx, cy, cx + cell - 2, cy + label_h - 2], fill=(28, 28, 32))
        d.text((cx + 12, cy + 12), f"FRAME {i + 1}", fill=(255, 255, 255))
        fit = min((cell - 24) / frame.width, (cell - 24) / frame.height, 3)
        small = frame.resize((max(1, int(frame.width * fit)),
                             max(1, int(frame.height * fit))), Image.LANCZOS)
        plate = Image.new("RGB", (cell, cell), (250, 250, 251))
        plate.paste(small, ((cell - small.width) // 2,
                            (cell - small.height) // 2), small)
        sheet.paste(plate, (cx, cy + label_h))
        d.rectangle([cx, cy, cx + cell - 2, cy + label_h + cell - 2],
                    outline=(205, 205, 210))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def build_prompt(description: str, anim: str, count: int) -> str:
    return PROMPT.format(
        description=description or "not described",
        anim=anim, count=count,
        checks="\n".join(f"  - {c}" for c in LOOK_FOR),
    )


def available() -> bool:
    return shutil.which("codex") is not None


def ask(image: Path, prompt: str, model: str | None = None,
        timeout: int = 300) -> list[Note]:
    """Show the model the contact sheet and parse what it says back."""
    if not available():
        raise ReviewError(
            "The `codex` CLI is not on PATH. Review reads an image through it, "
            "the same way `draw` writes one."
        )
    command = ["codex", "exec", "--skip-git-repo-check",
               "-i", str(image.resolve())]
    if model:
        command += ["-m", model]
    scratch = Path(tempfile.mkdtemp(prefix="art-review-"))
    try:
        result = subprocess.run(command, cwd=scratch, input=prompt,
                                capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ReviewError(f"codex exec timed out after {timeout}s.") from exc
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return parse(result.stdout or result.stderr or "")


def parse(text: str) -> list[Note]:
    """Pull the findings out, tolerating prose or fences around the JSON."""
    blocks = re.findall(r"\{[^{}]*\"findings\"\s*:\s*\[.*?\]\s*\}", text, re.S)
    if not blocks:
        raise ReviewError(
            "No findings block in the reply. Last 200 characters: "
            + text.strip()[-200:]
        )
    data = json.loads(blocks[-1])
    out: list[Note] = []
    for f in data.get("findings") or []:
        frame = f.get("frame")
        out.append(Note(
            frame=int(frame) - 1 if isinstance(frame, int) else None,
            issue=str(f.get("issue", "")).strip(),
            severity="low" if str(f.get("severity")).lower() == "low" else "high",
        ))
    return [n for n in out if n.issue]
