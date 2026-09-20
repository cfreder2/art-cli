"""`art.yaml` — the source of truth, and the only file a person edits.

`atlas.json` is build output and is overwritten by `pack`, so nothing is ever
authored there. Tuning a walk cycle in the preview writes back to here.

The load/save pair is deliberately asymmetric, the way `DnD-CLI`'s
`artsource.py` is: saving puts back the whole mapping it loaded, so a key this
version of the tool does not understand survives a round trip instead of being
silently dropped. `meta:` is the blessed place for that, but the guarantee is
not limited to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from art.spec import KINDS, TARGET_TILE_PX, min_drawn_px, prop_width_px, tile_size_px

FILENAME = "art.yaml"

# What a subject is waiting on. `legacy` is the one that makes a migration
# possible: `check` stays quiet about it, `audit` counts it anyway. `retired`
# is a whole subject nothing draws any more -- 34 of AXI's 61 terrain entries
# are in the atlas and referenced nowhere -- so it is planned, audited, checked
# and packed by nothing, but kept on the books with the reason.
STATES = ("todo", "drawn", "accepted", "legacy", "retired")


class ProfileError(RuntimeError):
    pass


@dataclass
class Subject:
    name: str
    kind: str = "character"
    state: str = "todo"
    height_tiles: float | None = None   # characters
    width_tiles: float | None = None    # props
    sheets: dict[str, list[str]] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def min_size(self, tile_px: int) -> tuple[int | None, int | None]:
        """The minimum this subject may be drawn at, as (w, h). None where the
        kind does not constrain that axis."""
        if self.kind == "tile":
            return tile_size_px(tile_px)
        if self.kind == "prop":
            if self.width_tiles is None:
                return (None, None)
            override = self.raw.get("min_size")
            if override:
                return (int(override[0]), int(override[1]))
            return (prop_width_px(self.width_tiles, tile_px), None)
        if self.height_tiles is None:
            return (None, None)
        return (None, min_drawn_px(self.height_tiles, tile_px))


def backdrop_for(profile: "Profile", subject: "Subject") -> str:
    """The key colour to draw this subject on.

    Per subject, not per project, because the rule it serves is "a colour the
    artwork never uses" and that is a fact about the character. Magenta is
    right for a green frog and destroys a pink axolotl.
    """
    return subject.raw.get("backdrop") or profile.backdrop


@dataclass
class Profile:
    path: Path
    tile_px: int = TARGET_TILE_PX
    canvas: int = 2048
    backdrop: str = "#FC309B"
    style: str = ""
    subjects: dict[str, Subject] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def root(self) -> Path:
        return self.path.parent


def find(start: Path | None = None) -> Path | None:
    """The nearest `art.yaml` at or above `start`. This is what lets `art` be
    run from anywhere inside a game folder."""
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        candidate = d / FILENAME
        if candidate.is_file():
            return candidate
    return None


def load(path: Path) -> Profile:
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ProfileError(f"{path} is not a mapping.")

    subjects: dict[str, Subject] = {}
    for name, body in (data.get("subjects") or {}).items():
        body = body or {}
        kind = body.get("kind", "character")
        if kind not in KINDS:
            raise ProfileError(
                f"{path}: subject {name!r} has kind {kind!r}; "
                f"expected one of {', '.join(KINDS)}."
            )
        state = body.get("state", "todo")
        if state not in STATES:
            raise ProfileError(
                f"{path}: subject {name!r} has state {state!r}; "
                f"expected one of {', '.join(STATES)}."
            )
        subjects[name] = Subject(
            name=name,
            kind=kind,
            state=state,
            height_tiles=body.get("height_tiles"),
            width_tiles=body.get("width_tiles"),
            sheets=body.get("sheets") or {},
            meta=body.get("meta") or {},
            raw=body,
        )

    return Profile(
        path=path,
        tile_px=int(data.get("tile_px", TARGET_TILE_PX)),
        canvas=int(data.get("canvas", 2048)),
        backdrop=data.get("backdrop", "#FC309B"),
        style=data.get("style", ""),
        subjects=subjects,
        raw=data,
    )


def save(profile: Profile) -> Path:
    """Write the profile back, keeping every key it did not understand.

    `raw` is the mapping as it was read, so unknown keys ride along. Comments do
    not survive — pyyaml cannot round-trip them — which is why this is only
    called for machine-made edits like a state change or a tuned fps.
    """
    data = dict(profile.raw)
    data["tile_px"] = profile.tile_px
    data["canvas"] = profile.canvas
    data["backdrop"] = profile.backdrop
    if profile.style:
        data["style"] = profile.style

    out_subjects = dict(data.get("subjects") or {})
    for name, s in profile.subjects.items():
        body = dict(s.raw)
        body["kind"] = s.kind
        body["state"] = s.state
        if s.height_tiles is not None:
            body["height_tiles"] = s.height_tiles
        if s.width_tiles is not None:
            body["width_tiles"] = s.width_tiles
        if s.sheets:
            body["sheets"] = s.sheets
        if s.meta:
            body["meta"] = s.meta
        out_subjects[name] = body
    data["subjects"] = out_subjects

    profile.path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return profile.path
