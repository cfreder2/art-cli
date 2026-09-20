"""A guide sheet to draw into, instead of a description to draw from.

Everything hard about a generated sprite sheet is placement: which cell a pose
belongs in, whether the feet share a groundline, how much clear background sits
between frames, and -- the one nothing else solves -- where the character's
standing point is horizontally.

That last one cannot be recovered afterwards without guessing. `cut` infers it
from the middle of the footprint, which works, but a template makes it KNOWN:
the tick is at the same offset in every cell, so the anchor is given rather
than measured.

The risk is that a generator redraws its reference instead of drawing into it,
and bakes the guides into the art. So the guides are one flat colour that
nothing else on the sheet uses, which makes leftovers easy to find afterwards
rather than easy to miss.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# A mid grey: far from any backdrop in the palette and far from skin, so a
# surviving guide line is obvious both to a person and to a check.
GUIDE = (128, 128, 128)

# Where the groundline sits inside a cell, as a share of cell height from the
# top. Leaves room beneath for a foot that dips.
BASELINE = 0.88


@dataclass
class Template:
    path: Path
    cols: int
    rows: int
    cell_w: int
    cell_h: int
    anchor_x: float       # share of cell width where the standing mark sits
    baseline_y: float     # share of cell height where the groundline sits

    def describe(self) -> str:
        return (
            f"{self.cols} columns x {self.rows} rows. In EACH cell: a horizontal "
            f"GROUNDLINE and a short vertical ANCHOR MARK crossing it. Draw one "
            f"pose per cell. Her feet rest ON the groundline, and her body "
            f"straddles the anchor mark -- the mark is where she stands, so it "
            f"must fall between her front and back legs in every frame, however "
            f"far her tail streams out behind."
        )


def build(out: Path, canvas: int, cols: int, rows: int,
          backdrop: tuple[int, int, int], anchor_x: float = 0.5) -> Template:
    """Draw the guide sheet."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (canvas, canvas), backdrop)
    d = ImageDraw.Draw(img)
    cell_w, cell_h = canvas // cols, canvas // rows
    # Thick enough that the generator cannot overlook them. A guide it ignores
    # is a generation spent for nothing; a guide it copies is caught by
    # `guide_remnants` afterwards, which is the cheaper failure.
    line = max(4, canvas // 220)

    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * cell_w, r * cell_h
            # Cell border, so the grid itself is unambiguous.
            d.rectangle([x0 + 2, y0 + 2, x0 + cell_w - 3, y0 + cell_h - 3],
                        outline=GUIDE, width=max(2, line // 2))
            base = y0 + int(cell_h * BASELINE)
            # Groundline, inset so it does not run into the next cell.
            pad = int(cell_w * 0.06)
            d.line([(x0 + pad, base), (x0 + cell_w - pad, base)],
                   fill=GUIDE, width=line)
            # Anchor mark: a short vertical tick straddling the groundline.
            ax = x0 + int(cell_w * anchor_x)
            tick = int(cell_h * 0.16)
            d.line([(ax, base - tick), (ax, base + tick // 2)],
                   fill=GUIDE, width=line)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return Template(out, cols, rows, cell_w, cell_h, anchor_x, BASELINE)


def guide_remnants(rgb, tolerance: int = 26) -> float:
    """Share of pixels still sitting on the guide colour after a generation.

    A generator that redrew the template rather than drawing into it leaves
    these behind, and they are easier to catch by measurement than by eye on a
    2048px sheet.
    """
    import numpy as np

    d = np.abs(rgb.astype(int) - np.array(GUIDE)).max(axis=-1)
    return float((d < tolerance).mean())
