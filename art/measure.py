"""Reading frame sizes out of an atlas, old format or new.

`audit` has to work before anything has been redrawn — its whole job is to
report on art that predates this tool. So it reads the atlas a game already
ships, and AXI's is the legacy shape:

    {"image": "...", "w": .., "h": .., "<group>": {"<anim>": [[x, y, w, h, lift], ...]}}

The fifth number is how far the frame rides above its row's baseline. It is the
best idea in the pipeline being replaced and it survives into `format: 1`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Keys at the top of a legacy atlas that are not groups of animations.
_SCALARS = {"image", "w", "h", "format", "size", "tile_px", "subjects"}


@dataclass(frozen=True)
class Frame:
    x: int
    y: int
    w: int
    h: int
    lift: int = 0


@dataclass
class Anim:
    name: str
    frames: list[Frame]

    @property
    def max_h(self) -> int:
        return max((f.h for f in self.frames), default=0)

    @property
    def max_w(self) -> int:
        return max((f.w for f in self.frames), default=0)

    @property
    def baseline_spread(self) -> int:
        """How far apart this row's baselines are. A spread means a bob."""
        if not self.frames:
            return 0
        bottoms = [f.lift for f in self.frames]
        return max(bottoms) - min(bottoms)


@dataclass
class Group:
    name: str
    anims: dict[str, Anim]

    @property
    def max_h(self) -> int:
        return max((a.max_h for a in self.anims.values()), default=0)

    @property
    def max_w(self) -> int:
        return max((a.max_w for a in self.anims.values()), default=0)

    @property
    def frame_count(self) -> int:
        return sum(len(a.frames) for a in self.anims.values())


def read_legacy(path: Path) -> dict[str, Group]:
    """Parse an AXI-shaped atlas.json into groups of animations."""
    data = json.loads(path.read_text())
    groups: dict[str, Group] = {}
    for key, body in data.items():
        if key in _SCALARS or not isinstance(body, dict):
            continue
        anims: dict[str, Anim] = {}
        for anim_name, frames in body.items():
            if not isinstance(frames, list) or not frames:
                continue
            # A terrain entry is ONE frame written flat -- `tiles.tree` is
            # [x, y, w, h, inset], not a list of frames. A character animation
            # is a list of those. Tell them apart by the first element.
            rows = [frames] if isinstance(frames[0], (int, float)) else frames
            parsed = [
                Frame(*(list(f)[:4] + [f[4] if len(f) > 4 else 0]))
                for f in rows
                if isinstance(f, (list, tuple)) and len(f) >= 4
            ]
            if parsed:
                anims[anim_name] = Anim(anim_name, parsed)
        if anims:
            groups[key] = Group(key, anims)
    return groups


def image_ref(path: Path) -> str:
    return json.loads(path.read_text()).get("image", "")
