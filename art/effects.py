"""Procedural motion applied to a sprite at draw time.

An effect is **metadata, not pixels**. A breathing idle costs one drawn frame
and a line of YAML instead of six drawn frames, which matters when every frame
is paid for out of a finite generation allowance. It is also steadier than
drawn motion: a sine has no seam when it loops.

AXI already does this by hand. The Frog King breathes at `game.js:2470` --
"he breathes rather than floats: the sprite is anchored at his feet, so a small
pulse in scale swells him upwards and leaves him planted" -- and that comment
is the whole design. Anchoring is what separates an effect that reads as life
from one that reads as a bug: a sprite that scales about its centre lifts off
the ground, and a cattail that rotates about its middle detaches from the soil.

The set is CLOSED, like `kind`. Every effect here has to be implemented by
whatever draws the sprite, so inventing one in a YAML file would produce
motion in the preview that the game does not have.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Param:
    name: str
    default: float
    low: float
    high: float
    unit: str
    help: str


@dataclass(frozen=True)
class Effect:
    name: str
    anchor: str
    params: tuple[Param, ...]
    help: str

    def defaults(self) -> dict[str, float]:
        return {p.name: p.default for p in self.params}


HZ = Param("hz", 0.5, 0.05, 4.0, "Hz", "cycles per second")

EFFECTS: dict[str, Effect] = {
    "breathe": Effect(
        "breathe", "feet",
        (Param("amount", 0.02, 0.0, 0.15, "×", "how far the scale pulses"), HZ),
        "A scale pulse about the feet, so the sprite swells upward and stays "
        "planted. Idles, and anything alive standing still.",
    ),
    "sway": Effect(
        "sway", "feet",
        (Param("degrees", 3.0, 0.0, 25.0, "°", "peak rotation each way"), HZ),
        "Rotation about the base. Wind in a cattail, a reed, a tree. The pivot "
        "is the bottom, because a plant is attached to the ground.",
    ),
    "bob": Effect(
        "bob", "free",
        (Param("amount", 0.06, 0.0, 0.6, "tiles", "peak vertical travel"), HZ),
        "A vertical float. Things that are NOT standing on anything -- a lily "
        "pad on water, a drifting mote, a hovering enemy.",
    ),
    "throb": Effect(
        "throb", "free",
        (Param("amount", 0.25, 0.0, 1.0, "α", "how far opacity dips"), HZ),
        "An opacity pulse. Glow, an aura, something charging.",
    ),
}

# How a phase offset is chosen, so a row of identical props does not move in
# lockstep -- which is the thing that makes a field of cattails read as a
# texture rather than as a wind.
PHASE_SOURCES = ("none", "x", "random")


class EffectError(ValueError):
    pass


def normalise(spec: dict) -> dict:
    """Validate a subject's `effects:` block and fill in every default.

    Returns {anim_or_default: {effect: {param: value, ..., phase: source}}}.
    """
    out: dict[str, dict] = {}
    for anim, effects in (spec or {}).items():
        if not isinstance(effects, dict):
            raise EffectError(f"effects for {anim!r} must be a mapping.")
        resolved: dict[str, dict] = {}
        for name, given in effects.items():
            effect = EFFECTS.get(name)
            if effect is None:
                raise EffectError(
                    f"unknown effect {name!r} for {anim!r}. "
                    f"Known: {', '.join(sorted(EFFECTS))}. "
                    "The set is closed because whatever draws the sprite has to "
                    "implement it."
                )
            given = given if isinstance(given, dict) else {}
            values = effect.defaults()
            for key, value in given.items():
                if key == "phase":
                    if value not in PHASE_SOURCES:
                        raise EffectError(
                            f"{anim}.{name}.phase must be one of "
                            f"{', '.join(PHASE_SOURCES)}.")
                    values["phase"] = value
                    continue
                param = next((p for p in effect.params if p.name == key), None)
                if param is None:
                    raise EffectError(
                        f"{anim}.{name} has no parameter {key!r}. "
                        f"Takes: {', '.join(p.name for p in effect.params)}.")
                v = float(value)
                if not param.low <= v <= param.high:
                    raise EffectError(
                        f"{anim}.{name}.{key} is {v}{param.unit}, outside "
                        f"{param.low}-{param.high}{param.unit}.")
                values[key] = v
            values.setdefault("phase", "none")
            values["anchor"] = effect.anchor
            resolved[name] = values
        out[anim] = resolved
    return out


def for_anim(normalised: dict, anim: str) -> dict:
    """The effects that apply to one animation, `default` falling through."""
    return {**normalised.get("default", {}), **normalised.get(anim, {})}


def catalogue() -> list[dict]:
    """The registry, for the preview's controls."""
    return [
        {"name": e.name, "anchor": e.anchor, "help": e.help,
         "params": [{"name": p.name, "default": p.default, "low": p.low,
                     "high": p.high, "unit": p.unit, "help": p.help}
                    for p in e.params]}
        for e in EFFECTS.values()
    ]
