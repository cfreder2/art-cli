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

ROLES = ("style", "identity", "revise", "pose")

# What the prompt says about each role, once the images are numbered.
ROLE_INSTRUCTION = {
    "style": "match its brushwork, palette, line weight and outline; "
             "do not copy its subject or composition",
    "identity": "this is the character. Keep the markings, colours, silhouette "
                "and costume exactly. IGNORE its resolution and framing -- it is "
                "the reference for who, not for how big",
    "revise": "this is the sheet being changed. Keep every row not named below "
              "identical, including costume and palette",
    "pose": "follow this layout and posing",
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
    found: list[Reference] = []
    root = profile.root

    def add(role: str, raw) -> None:
        if not raw:
            return
        for item in ([raw] if isinstance(raw, (str, Path)) else list(raw)):
            p = Path(item)
            p = p if p.is_absolute() else root / p
            if p.exists() and not any(r.path == p for r in found):
                found.append(Reference(role, p))

    add("style", profile.raw.get("style_ref"))

    declared = subject.raw.get("reference") or {}
    if isinstance(declared, dict):
        for role in ROLES:
            add(role, declared.get(role))
    else:
        add("identity", declared)

    # A subject still on its old art is its own best identity reference, and
    # forgetting to pass it is how a redraw comes back as a different frog.
    if not any(r.role == "identity" for r in found) and subject.state == "legacy":
        add("identity", (subject.raw.get("source") or {}).get("sheet"))

    for role, paths in (extra or {}).items():
        add(role, paths)
    return found


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
