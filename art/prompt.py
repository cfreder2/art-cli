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

# Rules every sheet must follow. AXI's ASSET_SPEC.md section 7, which is a list
# of failures rather than a list of preferences.
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


def build(
    profile: Profile,
    subject: Subject,
    sheet: SheetPlan,
    plan: SubjectPlan,
    references: list[Reference],
    note: str = "",
) -> str:
    facing = subject.raw.get("facing", "right")
    anim_notes = subject.raw.get("anims") or {}
    if sheet.wrapped:
        only = sheet.anims[0]
        note = anim_notes.get(only, "a " + only + " cycle")
        summary = note.get("summary", "") if isinstance(note, dict) else note
        described = [
            f"  ONE continuous {sheet.wrapped}-frame {only} cycle, laid out "
            f"{sheet.cols} across and {sheet.rows} down. Read it left to right "
            f"along the top row, then continue on the next row — frame "
            f"{sheet.cols + 1} sits below frame 1.",
            f"  {only} — {summary}",
        ]
        described += _per_frame(note, sheet.wrapped)
    else:
        described = []
        for i, name in enumerate(sheet.anims, 1):
            note = anim_notes.get(name, "a " + name + " cycle")
            summary = note.get("summary", "") if isinstance(note, dict) else note
            described.append(f"  Row {i}: {name} — {summary} ({sheet.cols} frames)")
            described += ["  " + line for line in _per_frame(note, sheet.cols)]

    from art.profile import backdrop_for
    rules = "\n".join(
        f"- {r.format(backdrop=backdrop_for(profile, subject), facing=facing)}"
        for r in SHEET_RULES
    )

    parts = [
        f"Draw a {sheet.rows}-row sprite sheet on a single "
        f"{profile.canvas}x{profile.canvas} image.",
        "",
        f"Subject: {subject.raw.get('description') or subject.name}",
        "",
        f"Sheet: {sheet.cols} columns x {sheet.rows} rows, evenly spaced. "
        f"Each cell is about {sheet.cell_w}x{sheet.cell_h}px.",
        ("Layout:" if sheet.wrapped else "Rows, top to bottom:"),
        *described,
        "",
        f"Size: the character must be AT LEAST {sheet.min_drawn}px tall in every "
        f"frame -- that is the point of this sheet, and a smaller drawing is the "
        f"defect being fixed. Fill the cell; leave about 20% of room for a pose "
        f"that is taller or wider than the others.",
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
