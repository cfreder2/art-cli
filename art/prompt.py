"""Building the text a generator is sent.

The format is a labelled-field template, the way `DnD-CLI`'s `images.py` does
it, because a generator follows a stated constraint far better than it follows
the same wish buried in prose.

`Constraints:` is the load-bearing field. Every line in it is a bug that has
already happened to this art -- a keyed-away outline, a vine that had to be
eroded off a character in code, a sash that appears in one frame of four and
becomes a flicker three times a second. They are stated as rules because the
alternative is fixing them in the cutter, and some of them cannot be fixed
there at all.
"""

from __future__ import annotations

from art.plan import SheetPlan, SubjectPlan
from art.profile import Profile, Subject
from art.refs import Reference, prompt_block

# Rules for a TILE sheet. A terrain tile is not a small character: it is
# repeated edge to edge, so the two rules that keep a character readable are
# exactly wrong for it. An outline becomes a grid line drawn across the world
# every time the tile repeats, and a transparent margin becomes a gap.
# A STRIP is a tile on one axis and an object on the others: a hanging vine
# repeats top to bottom and has open air either side of it. Told to fill its
# cell corner to corner, a generator fills it -- which is how the vine came
# back as a 100% opaque rectangle of foliage.
STRIP_RULES = [
    "Each cell holds ONE NARROW OBJECT running the full height of the cell, "
    "top edge to bottom edge, with FLAT BACKGROUND showing on BOTH SIDES of "
    "it. It is not a panel and it does not fill the cell: it is a single "
    "narrow thing with open space either side, like a rope hanging in air.",
    "It must run off the TOP edge and off the BOTTOM edge -- no gap, no "
    "rounded end, no tip. It is a section of something longer.",
    "{seam}",
    "NO OUTLINE box, border or frame around the cell.",
    "The background is FLAT {backdrop}, and it is the only thing either side "
    "of the object.",
    "At least 24px of clear background between cells.",
    "No labels, no text, no numbers, no grid lines and no cell borders in the "
    "OUTPUT.",
    "Every item on this sheet shares ONE palette and ONE light direction.",
]

TILE_RULES = [
    "Each cell holds ONE SQUARE tile, drawn as a perfect square and filling "
    "that square completely, corner to corner. No margin, no rounded corners, "
    "no padding -- the artwork runs off all four edges.",
    "NO OUTLINE around a tile, and no border, frame or edging of any kind. A "
    "tile is a patch of material, and an outline becomes a line ruled across "
    "the world every time it repeats.",
    "{seam}",
    "The background is FLAT {backdrop} and shows ONLY in the gaps BETWEEN "
    "cells, never inside a tile.",
    "At least 24px of clear background between cells so they can be cut apart.",
    "No labels, no text, no numbers, no grid lines and no cell borders in the "
    "OUTPUT. The reference images carry labels; those are for reading.",
    "Every tile on this sheet shares ONE palette, ONE light direction and ONE "
    "level of detail, so they read as the same world when laid side by side.",
]

def _seam_rule(subject, sheet) -> str:
    """The tiling rule for this sheet: one line, or one line per tile.

    `seamless:` is a string for most sheets, and then every tile on the sheet
    repeats the same way. Water is not most sheets: its surface has a crest and
    only repeats sideways while the body under it is stacked as well, so the
    sheet needs both rules and has to say which tile each belongs to.
    """
    from art import seams as seams_mod
    declared = subject.raw.get("seamless")
    if not isinstance(declared, dict):
        return SEAM_RULES.get(declared, SEAM_RULES["both"])
    lines = []
    for anim in sheet.anims:
        axis = seams_mod.axis_for(declared, anim)
        lines.append(f"{anim}: {SEAM_RULES.get(axis, SEAM_RULES['both'])}")
    joins = subject.raw.get("joins") or {}
    for anim, under in joins.items():
        if anim in sheet.anims and under in sheet.anims:
            lines.append(
                f"{anim} is drawn directly ON TOP OF {under} in the game, so "
                f"where {anim} ends at its BOTTOM edge it must be the same "
                f"water, colour and depth as the TOP edge of {under}.")
    return "Each tile tiles differently. " + " ".join(lines)


SEAM_RULES = {
    "horizontal": "It TILES SIDE BY SIDE: the artwork running off its LEFT edge "
                  "must continue exactly into what runs off its RIGHT edge, so "
                  "a row of them reads as one continuous surface with no seam. "
                  "It is never stacked vertically, so top and bottom need not "
                  "match.",
    "vertical":   "It TILES TOP TO BOTTOM: the artwork running off its TOP edge "
                  "must continue exactly into what runs off its BOTTOM edge, so "
                  "a column of them reads as continuous with no seam.",
    "both":       "It TILES IN BOTH DIRECTIONS: left edge continues into right, "
                  "and top into bottom, so a field of them is seamless.",
    None:         "It is used on its own and does not repeat, so its edges need "
                  "not match.",
}

# Rules every CHARACTER sheet must follow. AXI's ASSET_SPEC.md section 7, which
# is a list of failures rather than a list of preferences.
SHEET_RULES = [
    "The background is FLAT {backdrop} and nothing else. Not white, not a "
    "gradient, not a scene. It must be a colour the artwork never uses, so it "
    "can be removed by colour alone -- including the pockets a flood fill "
    "cannot reach, between fingers and between toes.",
    "Outline every frame in a dark colour far from the background. An outline "
    "close to the background gets silently eaten when the background is keyed.",
    "NOTHING in the frame but the character. No ground, no prop, no vine, no "
    "shadow. Do not DRAW a groundline -- but place every frame as though "
    "standing on the same invisible one, so the feet line up across the sheet.",
    "The SAME character in every frame: identical colours, markings, "
    "proportions and costume. A detail present in one frame of four becomes a "
    "flicker when the row is animated.",
    "At least 24px of clear background between frames, and more between rows "
    "than within a row.",
    "No labels, no text, no numbers, no grid lines, no borders anywhere in the "
    "OUTPUT. The reference images carry row labels; those are for reading, "
    "not for copying.",
    "Every frame faces the SAME direction: {facing}. Do not draw a turnaround "
    "or a mirrored set -- the game flips the sprite itself.",
    "Align every frame to that same invisible groundline, so the animation "
    "does not bob when it plays -- unless a pose is "
    "explicitly described as airborne, which sits above it.",
    "EVERY limb the character has appears in EVERY frame. A four-legged "
    "character shows FOUR legs in all of them. Never drop, merge or hide a "
    "limb behind the body because it overlaps -- draw the far-side limbs in a "
    "slightly DARKER shade of the same colour so they read as being behind, "
    "and keep their outline. This is about never LOSING a limb; it is not a "
    "reason to draw the limbs in the same place each time. Each frame's pose "
    "governs where they go.",
]


# Rules every PROP sheet must follow. A prop is neither a character nor a tile:
# it does not animate, so it has no cycle and no groundline to share, and it
# does not repeat, so it has no seam. What it DOES have is a shape, and that is
# the thing that kept going wrong -- props were prompted with SHEET_RULES,
# whose size line reads "the character must be AT LEAST Npx tall in every
# frame. Fill the cell." Told that, the generator drew every prop to the same
# height: AXI's low sprawling flower came back upright at 0.76:1 where the art
# it replaced was 1.78:1, and a fallen log came back stubby at 1.59:1 where it
# had been 3.15:1. Eleven of fifteen props drifted that way. So the proportion
# is stated per item, in pixels, and nothing here asks for a cell to be filled.
PROP_RULES = [
    "The background is FLAT {backdrop} and nothing else. Not white, not a "
    "gradient, not a scene. It must be a colour the artwork never uses, so it "
    "can be removed by colour alone -- including the pockets a flood fill "
    "cannot reach, under a leaf and between two stems.",
    "Outline every item in a dark colour far from the background. An outline "
    "close to the background gets silently eaten when the background is keyed.",
    "DRAW EACH ITEM AT THE SIZE GIVEN FOR IT, exactly. Each one fills its "
    "cell in ONE direction and falls well short in the other -- that is what "
    "makes a log read as long and low and a reed as tall and thin. Do NOT "
    "even them out, do NOT square them up, and do NOT stretch an item to "
    "reach the sides of its cell. Wide margins on two sides are correct.",
    "NOTHING in the cell but the item itself. No ground, no shadow, no "
    "companion object, no scenery behind it.",
    "Every item stands upright as it would in the world, not tilted into its "
    "cell to make it fit.",
    "At least 24px of clear background between items.",
    "No labels, no text, no numbers, no grid lines, no borders anywhere in the "
    "OUTPUT. The reference images carry labels; those are for reading, not "
    "for copying.",
]


def _per_frame(note, count: int) -> list[str]:
    """Pose-by-pose direction, when the profile gives it.

    A general description of a cycle produces a general cycle: six drawings of
    roughly one pose. Naming what each frame is -- gather, push, stretch, land
    -- is the difference between an animation and a twitch, and it is the only
    lever that reliably moves the measured frame-to-frame change.
    """
    poses = note.get("frames") if isinstance(note, dict) else None
    if not poses:
        return []
    lines = ["  Each frame is a DISTINCTLY different pose, in this order:"]
    for i, pose in enumerate(poses[:count], 1):
        lines.append(f"    Frame {i}: {pose}")
    lines.append("  Neighbouring frames must not look alike. If two frames could "
                 "be swapped without anyone noticing, the cycle is wrong.")
    return lines


def prop_size_px(entry, subject, tile_px: int = None) -> tuple[int, int] | None:
    """The width and height, in pixels, to draw one prop at.

    `width_tiles` alone says how WIDE to draw a prop in the game and says
    nothing about its shape, so the generator was free to choose one -- and
    chose wrong for eleven of AXI's fifteen props. `height_tiles` beside it
    pins the proportion, and is read per item first because one decor sheet
    carries a 3.6-tile tree and a 0.8-tile flower.
    """
    from art import spec as spec_mod
    tile_px = tile_px or spec_mod.TARGET_TILE_PX
    get = (lambda k: entry.get(k)) if isinstance(entry, dict) else (lambda k: None)
    w = get("width_tiles") or subject.raw.get("width_tiles")
    h = get("height_tiles") or subject.raw.get("height_tiles")
    if not w or not h:
        return None
    return (round(float(w) * tile_px), round(float(h) * tile_px))


def _shape_word(w: int, h: int) -> str:
    """How the proportion reads in words, because a ratio alone did not land."""
    r = w / h if h else 1.0
    if r >= 2.5:
        return "much wider than it is tall, long and low"
    if r >= 1.4:
        return "clearly wider than it is tall"
    if r > 0.72:
        return "roughly square"
    if r > 0.4:
        return "clearly taller than it is wide"
    return "much taller than it is wide, tall and narrow"


def prop_draw_size(entry, subject, sheet) -> tuple[int, int] | None:
    """The size to ASK for: the declared proportion, grown to fill its cell.

    The game draws a prop at a fixed tile width and takes its height from the
    source aspect alone -- `ph = ts * (f[3] / f[2])` -- so the absolute size on
    the sheet is free resolution and only the SHAPE is load-bearing. Asking for
    the spec's own 192px-per-tile figures left a flower at 154x86 in a 418x627
    cell, throwing away three quarters of the sheet for no reason.

    Fitted in BOTH directions, up or down. A horizon band declares 13.4 tiles
    by 3.4 -- 2579x653px, wider than the whole canvas -- and asking for that
    is asking for nothing, since the generator cannot draw it and will pick
    its own shape instead. Only the proportion is load-bearing, so scaling to
    the cell costs nothing and keeps the instruction one that can be followed.
    """
    size = prop_size_px(entry, subject)
    if not size or not sheet:
        return size
    w, h = size
    # 0.92 keeps the clear background the frame-finder cuts on.
    fit = min(sheet.cell_w * 0.92 / w, sheet.cell_h * 0.92 / h)
    return (max(1, round(w * fit)), max(1, round(h * fit)))


def _prop_size_phrase(entry, subject, sheet=None) -> str:
    size = prop_draw_size(entry, subject, sheet)
    if not size:
        return ""
    w, h = size
    return f" [draw this one {w}x{h}px — {_shape_word(w, h)}]"


def build(
    profile: Profile,
    subject: Subject,
    sheet: SheetPlan,
    plan: SubjectPlan,
    references: list[Reference],
    note: str = "",
) -> str:
    facing = subject.raw.get("facing", "right")
    # Per-cell direction is read into `entry`, never into `note`: `note` is the
    # caller's own art direction -- `--note`, and the frames `issues` flagged --
    # and rebinding it here dropped that on the floor and printed the last
    # animation's raw dict at the bottom of the prompt instead.
    anim_notes = subject.raw.get("anims") or {}
    if sheet.gallery:
        described = [
            f"  {sheet.cols} columns x {sheet.rows} rows, ONE separate item per "
            f"cell, read left to right along the top row then continue on the "
            f"next. They are NOT frames of an animation -- each cell is a "
            f"different thing, and they share this sheet so that they share a "
            f"material, a palette and a light direction.",
            "  The cells, in order:",
        ]
        for i, name in enumerate(sheet.anims, 1):
            entry = anim_notes.get(name, name)
            text = entry.get("summary", "") if isinstance(entry, dict) else entry
            described.append(f"    Cell {i}: {name} — {text}"
                             + _prop_size_phrase(entry, subject, sheet))
        if sheet.cols * sheet.rows > len(sheet.anims):
            described.append(
                f"  The last {sheet.cols * sheet.rows - len(sheet.anims)} cell(s) "
                "are left completely EMPTY -- flat background, nothing drawn.")
    elif sheet.wrapped:
        only = sheet.anims[0]
        entry = anim_notes.get(only, "a " + only + " cycle")
        summary = entry.get("summary", "") if isinstance(entry, dict) else entry
        described = [
            f"  ONE continuous {sheet.wrapped}-frame {only} cycle, laid out "
            f"{sheet.cols} across and {sheet.rows} down. Read it left to right "
            f"along the top row, then continue on the next row — frame "
            f"{sheet.cols + 1} sits below frame 1."
            + (f" The grid holds {sheet.cols * sheet.rows} cells and there are "
               f"only {sheet.wrapped} frames, so the LAST "
               f"{sheet.cols * sheet.rows - sheet.wrapped} cell(s) are left "
               f"completely EMPTY — flat background, nothing drawn in them."
               if sheet.cols * sheet.rows > sheet.wrapped else ""),
            f"  {only} — {summary}",
        ]
        described += _per_frame(entry, sheet.wrapped)
    else:
        described = []
        for i, name in enumerate(sheet.anims, 1):
            entry = anim_notes.get(name, "a " + name + " cycle")
            summary = entry.get("summary", "") if isinstance(entry, dict) else entry
            described.append(f"  Row {i}: {name} — {summary} ({sheet.cols} frames)")
            described += ["  " + line for line in _per_frame(entry, sheet.cols)]

    from art.profile import backdrop_for
    backdrop = backdrop_for(profile, subject)
    if subject.kind == "tile":
        # One sheet can carry tiles that repeat differently -- a water surface
        # and the water under it -- so when the axes differ the rule is stated
        # per tile instead of once for the sheet.
        seam = _seam_rule(subject, sheet)
        source = (STRIP_RULES if subject.raw.get("fill") is False else TILE_RULES)
    elif subject.kind == "prop":
        # A prop is not a character. Prompting it with SHEET_RULES asked for a
        # groundline it has no cycle to share, every limb it does not have, and
        # -- the damaging one -- a uniform height that flattened every prop's
        # shape to the same one.
        seam = ""
        source = PROP_RULES
    else:
        seam = ""
        source = SHEET_RULES
    rules = "\n".join(
        f"- {r.format(backdrop=backdrop, facing=facing, seam=seam)}"
        for r in source
    )

    parts = [
        f"Draw a {sheet.rows}-row sprite sheet on a single "
        f"{profile.canvas}x{profile.canvas} image.",
        "",
        f"Subject: {subject.raw.get('description') or subject.name}",
        "",
        f"Sheet: {sheet.cols} columns x {sheet.rows} rows, evenly spaced. "
        f"Each cell is about {sheet.cell_w}x{sheet.cell_h}px.",
        ("Layout:" if (sheet.wrapped or sheet.gallery) else "Rows, top to bottom:"),
        *described,
        "",
        (("Size: the object runs the FULL HEIGHT of its cell and is a fraction "
          "of its width -- roughly a fifth as wide as it is tall."
          if subject.raw.get("fill") is False else
          f"Size: draw each tile as a SQUARE at least {sheet.min_drawn}px on a "
          f"side, filling its square completely.")
         if subject.kind == "tile" else
         ("Size: each item has its OWN width and height, given beside it above. "
          "Draw it at that size. These deliberately differ in SHAPE -- a fallen "
          "log is long and low, a reed is tall and thin -- and flattening them "
          "toward one common shape is the defect being fixed."
          if subject.kind == "prop" else
         f"Size: the character must be AT LEAST {sheet.min_drawn}px tall in every "
        f"frame -- that is the point of this sheet, and a smaller drawing is the "
        f"defect being fixed. Fill the cell; leave about 20% of room for a pose "
        f"that is taller or wider than the others.")),
        "",
        "Constraints:",
        rules,
    ]
    style = subject.raw.get("style", profile.style)
    if style:
        parts += ["", f"Style: {style}"]
    block = prompt_block(references)
    if block:
        parts += ["", block]
    if note:
        parts += ["", f"Also: {note}"]
    return "\n".join(parts)
