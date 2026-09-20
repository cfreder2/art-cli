"""How much art to ask for, and how to lay it out on one canvas.

The rule that saves the most generation: **one facing**. A 2D game mirrors a
sprite horizontally at draw time -- AXI does it at `game.js:727` with
`ctx.scale(-1, 1)` -- so a sheet drawn facing right covers both directions and
asking for a turnaround doubles the bill for nothing.

The exception is asymmetry. Mirroring flips everything: an eye patch changes
eyes, a sash swaps shoulders, a tool moves hand. A subject like that sets
`mirror: false` and genuinely needs both facings, and the budget doubles
because it has to, not because a generator volunteered it.

Rows are animations and columns are frames. That is not arbitrary -- the cutter
finds frames by looking for the widest gaps, and an animation per row is what
lets a row share one ground line.
"""

from __future__ import annotations

from dataclasses import dataclass

from art.measure import Group
from art.profile import Profile, Subject
from art.spec import min_drawn_px

# Headroom inside a cell. A jump is taller than an idle and a swim is wider
# than it is tall; the spec asks for 20% of room in both directions.
CELL_HEADROOM = 1.2

# The clear background a cutter needs between frames to tell them apart.
MIN_GUTTER_PX = 24

# Animations per character sheet. This is the spec's number, and it is a flat
# choice rather than something derived: 6x4 for Masie, 7x4 for an enemy, 6x4
# for a friend are all "four animations". Packing more rows technically clears
# the minimum height while leaving the generator almost no room, which is the
# failure the spec warns about -- "fewer frames per image, not smaller frames".
# `--tight` opts into that trade knowingly; nothing does it by default.
SPEC_ROWS_PER_SHEET = 4


@dataclass
class SheetPlan:
    name: str
    anims: list[str]
    cols: int              # frames per row
    rows: int              # animation rows, unless `wrapped`
    cell_w: int
    cell_h: int
    min_drawn: int
    facings: int
    wrapped: int = 0       # frames in ONE animation laid across the whole grid

    @property
    def fits(self) -> bool:
        return self.cell_h >= self.min_drawn * CELL_HEADROOM

    @property
    def frames(self) -> int:
        return self.cols * self.rows



@dataclass
class SubjectPlan:
    subject: str
    kind: str
    min_drawn: int
    facings: int
    mirrored: bool
    frame_counts: dict[str, int]
    sheets: list[SheetPlan]
    notes: list[str]

    @property
    def generations(self) -> int:
        """One image per sheet per facing -- the number that costs money."""
        return len(self.sheets) * self.facings


def facings_for(subject: Subject) -> tuple[int, bool]:
    """(how many facings to draw, whether the game mirrors).

    Default is one drawn facing and a mirror at runtime, because that is what
    2D games do and it halves generation.
    """
    mirror = bool(subject.raw.get("mirror", True))
    return (1 if mirror else 2, mirror)


def rows_that_fit(canvas: int, min_drawn: int) -> int:
    """The most animation rows that still clear the minimum height with headroom.

    This is a ceiling, not a recommendation. At 2048 with Masie's 240px minimum
    it returns 7, giving 292px cells -- legal, and 52px of room for a jump pose
    that is taller than an idle. The spec's four rows give 512.
    """
    need = min_drawn * CELL_HEADROOM
    return max(1, int(canvas // need))


def plan_subject(
    profile: Profile,
    subject: Subject,
    groups: dict[str, Group] | None = None,
    tight: bool = False,
) -> SubjectPlan:
    canvas = profile.canvas
    notes: list[str] = []
    facings, mirror = facings_for(subject)

    if subject.kind == "tile":
        cell = profile.tile_px
        per_side = max(1, canvas // cell)
        return SubjectPlan(
            subject.name, subject.kind, cell, 1, True, {},
            [SheetPlan(subject.name, [], per_side, per_side, cell, cell, cell, 1)],
            [f"terrain: {per_side}×{per_side} grid of exact {cell}×{cell} cells, "
             "filled edge to edge -- a margin here becomes a seam"],
        )

    min_drawn = min_drawn_px(subject.height_tiles or 1.0, profile.tile_px)

    # Frame counts come from the atlas when there is one, because that is the
    # only honest source for art that already exists.
    counts: dict[str, int] = {}
    source = subject.raw.get("source") or {}
    group = (groups or {}).get(source.get("group", subject.name))
    if group:
        prefix = source.get("prefix", "")
        entry = source.get("entry")
        for anim_name, anim in group.anims.items():
            if entry and anim_name != entry:
                continue
            counts[anim_name[len(prefix):] if prefix else anim_name] = len(anim.frames)

    # A sheet entry is a list of animations, or {anims: [...], cols: n} when one
    # animation has to be laid across a grid. Masie needs that: she is wider
    # than she is tall, so six frames in a row would be 209px wide cells for art
    # that has to be 240px tall. Three columns of two rows gives her 418px.
    groupings: dict[str, object] = (
        subject.sheets or ({subject.name: list(counts)} if counts else {}))

    forced: dict[str, int | None] = {}
    plain: dict[str, list[str]] = {}
    for sheet_name, spec in groupings.items():
        if isinstance(spec, dict):
            plain[sheet_name] = list(spec.get("anims") or [])
            forced[sheet_name] = spec.get("cols")
        else:
            plain[sheet_name] = list(spec)
            forced[sheet_name] = None
    groupings = plain
    if not groupings:
        notes.append("no animations known -- set `sheets:` in art.yaml")
        return SubjectPlan(subject.name, subject.kind, min_drawn, facings, mirror,
                           counts, [], notes)

    ceiling = rows_that_fit(canvas, min_drawn)
    spec_rows = int(profile.raw.get("rows_per_sheet", SPEC_ROWS_PER_SHEET))
    rows_max = ceiling if tight else min(spec_rows, ceiling)
    if not tight and ceiling > rows_max:
        saved_cell = canvas // ceiling
        notes.append(
            f"--tight would allow {ceiling} rows ({saved_cell}px cells instead of "
            f"{canvas // rows_max}px) and fewer sheets -- cheaper to generate, "
            f"less room for a tall pose"
        )
    sheets: list[SheetPlan] = []
    for sheet_name, anims in groupings.items():
        anims = list(anims)

        cols_override = forced.get(sheet_name)
        if cols_override and len(anims) == 1:
            # One animation wrapped across the grid. The cutter reads rows top
            # to bottom and frames left to right within a row, so concatenating
            # them restores the order -- which only holds because the sheet
            # carries a single animation.
            total = counts.get(anims[0], 6)
            cols = int(cols_override)
            rows = -(-total // cols)
            sheets.append(SheetPlan(
                sheet_name, anims, cols, rows,
                canvas // cols, canvas // rows, min_drawn, facings, wrapped=total))
            notes.append(
                f"`{sheet_name}`: {total} frames of {anims[0]} laid {cols}x{rows}, "
                f"read left to right then top to bottom")
            continue

        chunks = [anims[i:i + rows_max] for i in range(0, len(anims), rows_max)] or [[]]
        for n, chunk in enumerate(chunks, 1):
            cols = max((counts.get(a, 6) for a in chunk), default=6)
            rows = len(chunk)
            name = sheet_name if len(chunks) == 1 else f"{sheet_name}-{n}"
            if canvas // max(cols, 1) < min_drawn:
                # A wide pose needs roughly its own height of width. When the
                # columns squeeze below that, the frames get clipped, not small.
                notes.append(
                    f"`{name}`: {cols} columns leaves {canvas // cols}px of width "
                    f"for {min_drawn}px art -- lay the animation across a grid "
                    f"(`cols:` in art.yaml) or raise the canvas"
                )
            sheets.append(SheetPlan(
                name, chunk, cols, rows,
                canvas // max(cols, 1), canvas // max(rows, 1), min_drawn, facings,
            ))
        if len(chunks) > 1:
            why = (f"{rows_max} is all that clears {min_drawn}px with headroom"
                   if tight else f"the spec puts {rows_max} animations on a sheet")
            notes.append(
                f"`{sheet_name}` holds {len(anims)} animations and {why} "
                f"-- split into {len(chunks)} sheets"
            )

    if mirror:
        notes.append("one facing: the game mirrors horizontally, so a turnaround "
                     "is a doubled bill for nothing")
    else:
        notes.append("`mirror: false` -- asymmetric, so both facings are drawn "
                     "and the generation budget doubles")
    return SubjectPlan(subject.name, subject.kind, min_drawn, facings, mirror,
                       counts, sheets, notes)
