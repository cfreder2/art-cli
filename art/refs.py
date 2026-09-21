"""Reference images: showing the generator what it should look like.

`codex exec -i/--image FILE` attaches images to a prompt, and they arrive
numbered -- so the prompt can say "Image 1" and mean something. That numbering
is the whole mechanism, and it only works if each image has a stated job.

A reference is never just "inspiration". It is one of four things, and saying
which is what stops a style plate being copied as a pose, or an old sheet's
tiny frames being treated as the target size:

  style     the look: brushwork, palette, line weight, outline.
  identity  who this is. Markings, colours, silhouette, costume.
  revise    the sheet being changed -- keep everything not mentioned.
  pose      a layout or a specific pose to follow.

The one that matters most for a redraw is `identity`. Mr Frog is 45x45 pixels
today, which is the bug, but he is still canonically Mr Frog: that sheet is the
only statement of what he looks like. So a `legacy` subject attaches its own
old sheet automatically, and the prompt says to keep the character and ignore
the size.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from art.profile import Profile, Subject

ROLES = ("style", "identity", "template", "revise", "pose")

# When one file arrives under two roles, the more specific one wins. Sir
# Croaks' sheet is a style benchmark for the whole game AND the statement of
# who Sir Croaks is; attaching it twice wastes an image slot, and letting
# "style" win would tell the model to ignore the very subject it is drawing.
ROLE_PRIORITY = {"style": 0, "pose": 1, "identity": 2, "template": 3,
                 "revise": 4}

# What the prompt says about each role, once the images are numbered.
ROLE_INSTRUCTION = {
    "style": "match its brushwork, palette, line weight and outline; "
             "do not copy its subject or composition",
    "identity": "this is WHO the character is, AND how they are drawn. Keep the "
                "colours, markings, proportions, costume and the rendering -- "
                "line weight, shading, how soft or hard the edges are. Do NOT "
                "copy its poses, its framing or its resolution: the poses are "
                "specified above, and where they differ from this image the "
                "description wins",
    "template": "this is the LAYOUT to draw into, at the exact canvas size. Its "
                "background colour is the backdrop to use. Draw one pose per "
                "cell, feet resting ON each cell's groundline, body straddling "
                "each cell's vertical anchor mark. The grey guide lines are "
                "instructions, NOT artwork: your output must contain no grey "
                "lines, no marks and no cell borders of any kind",
    "revise": "this is the sheet being changed. Keep every row not named below "
              "identical, including costume and palette",
    "pose": "follow its LAYOUT and POSING only -- the gait, the timing, where "
            "each limb is in each frame. Take nothing else from it: not the "
            "colours, not the facial features, not the proportions. Those come "
            "from the identity image and the description",
}


@dataclass(frozen=True)
class Reference:
    role: str
    path: Path

    def line(self, number: int) -> str:
        return f"Image {number} — {self.role}: {ROLE_INSTRUCTION[self.role]}."


def resolve(
    profile: Profile,
    subject: Subject,
    extra: dict[str, list[Path]] | None = None,
) -> list[Reference]:
    """Every reference a generation for this subject should carry, in order.

    Order is the numbering the prompt depends on, so it is fixed: style first
    because it applies to the whole image, then identity, then the sheet under
    revision, then poses.
    """
    by_path: dict[Path, str] = {}
    root = profile.root

    def add(role: str, raw) -> None:
        if not raw:
            return
        for item in ([raw] if isinstance(raw, (str, Path)) else list(raw)):
            p = Path(item)
            p = p if p.is_absolute() else root / p
            if not p.exists():
                continue
            held = by_path.get(p)
            if held is None or ROLE_PRIORITY[role] > ROLE_PRIORITY[held]:
                by_path[p] = role

    # A subject's own sheet is never a style reference FOR that subject: the
    # style instruction says "do not copy its subject", which is nonsense
    # pointed at the very character being drawn. Identity covers it instead.
    own = (subject.raw.get("source") or {}).get("sheet")
    own_path = (root / own).resolve() if own else None
    # A subject may replace the project's style anchors, or drop them entirely
    # with `style_ref: []`. A character whose own art defines the house style
    # is better served by its identity reference than by another character's
    # sheet pulling it somewhere else.
    declared_style = subject.raw.get("style_ref")
    anchors = (profile.raw.get("style_ref") or []) if declared_style is None \
        else declared_style
    for candidate in anchors:
        c = Path(candidate)
        c = c if c.is_absolute() else root / c
        if own_path and c.resolve() == own_path:
            continue
        add("style", c)

    declared = subject.raw.get("reference") or {}
    if isinstance(declared, dict):
        for role in ROLES:
            add(role, declared.get(role))
    else:
        add("identity", declared)

    # A subject still on its old art is its own best identity reference, and
    # forgetting to pass it is how a redraw comes back as a different frog.
    if "identity" not in by_path.values() and subject.state == "legacy":
        add("identity", (subject.raw.get("source") or {}).get("sheet"))

    for role, paths in (extra or {}).items():
        add(role, paths)

    # Order is the numbering the prompt depends on: style first because it
    # applies to the whole image, then who it is, then what is being changed.
    return sorted((Reference(role, path) for path, role in by_path.items()),
                  key=lambda r: (ROLES.index(r.role), r.path.name))


def prompt_block(references: list[Reference]) -> str:
    """The numbered lines a prompt needs so the attachments mean something."""
    if not references:
        return ""
    return "References:\n" + "\n".join(
        ref.line(i) for i, ref in enumerate(references, 1)
    )


def codex_args(references: list[Reference]) -> list[str]:
    """`-i` arguments, in the order the numbering assumes."""
    out: list[str] = []
    for ref in references:
        out += ["-i", str(ref.path.resolve())]
    return out
