"""Measuring what ships against what the spec asks for.

This is the verb that has to work before anything else exists, because its job
is to report on art that predates the tool. It answers one question per
subject: how far is this stretched on the screen it is drawn on?

The reference frame matters. A game scales a character by one frame and applies
that scale to the whole set -- AXI does it at `game.js:699`, `1.15 /
atlas.axi.idle[0][3]`. So the number that decides how big everything looks is
the height of *idle frame 0*, not the tallest frame in the set. Measuring the
max would quietly flatter every subject whose idle is its smallest pose.
"""

from __future__ import annotations

from dataclasses import dataclass

from art.measure import Group
from art.profile import Profile, Subject
from art.spec import DEVICES, Device, upscale

# The frame a game most likely scales from, in preference order.
_REFERENCE = ("idle", "walk", "run")


def reference_frame(group: Group, subject_prefix: str = "") -> tuple[str, int, int]:
    """The (anim, w, h) a game would derive its scale from."""
    names = list(group.anims)
    for want in _REFERENCE:
        for n in names:
            if n == want or n == f"{subject_prefix}{want}" or n.endswith(f"_{want}"):
                f = group.anims[n].frames[0]
                return (n, f.w, f.h)
    n = names[0]
    f = group.anims[n].frames[0]
    return (n, f.w, f.h)


@dataclass
class Row:
    name: str
    state: str
    anim: str
    src_w: int
    src_h: int
    drawn_tiles: float
    required_px: int | None
    factors: dict[str, float]

    @property
    def worst(self) -> float:
        return max(self.factors.values(), default=0.0)

    def verdict(self, tolerance: float = 1.05) -> str:
        if self.worst <= 1.0:
            return "ok"
        if self.worst <= tolerance:
            return "soft"
        return "UPSCALED"


def drawn_px(subject: Subject, device: Device) -> float:
    """How tall this subject is drawn, in device pixels, on this screen."""
    tiles = subject.height_tiles if subject.kind != "tile" else 1.0
    return (tiles or 1.0) * device.px_per_tile


def rows(
    profile: Profile,
    groups: dict[str, Group],
    devices: tuple[Device, ...] = DEVICES,
) -> list[Row]:
    out: list[Row] = []
    for name, subject in profile.subjects.items():
        source = subject.raw.get("source") or {}
        group_name = source.get("group", name)
        prefix = source.get("prefix", "")
        group = groups.get(group_name)
        if group is None:
            continue
        entry = source.get("entry")
        if entry:
            # A subject carved out of a shared group -- one of AXI's four
            # enemies, or a single terrain entry.
            if entry not in group.anims:
                continue
            group = Group(entry, {entry: group.anims[entry]})
        anim, w, h = reference_frame(group, prefix)
        if subject.kind == "prop":
            # A prop is sized by width, so that is the axis that stretches.
            measure_src, tiles = w, (subject.width_tiles or 1.0)
        else:
            measure_src, tiles = h, (subject.height_tiles or 1.0)
        factors = {
            d.name: upscale(measure_src, tiles * d.px_per_tile) for d in devices
        }
        _, req = subject.min_size(profile.tile_px)
        if subject.kind == "prop":
            req = subject.min_size(profile.tile_px)[0]
        out.append(
            Row(name, subject.state, anim, w, h, tiles, req, factors)
        )
    out.sort(key=lambda r: -r.worst)
    return out
