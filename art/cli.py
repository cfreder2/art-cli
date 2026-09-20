"""The `art` entry point.

A flat list of verbs, because the pipeline is the mental model and you run them
left to right: audit, plan, prompt, draw, accept, cut, check, pack. `DnD-CLI`
moved away from a flat surface, but it had grown two jobs sharing one list.
This has one.

Every verb takes a selector -- names, `--all`, `--stale`, `--tag` -- because
the job that motivated this tool is nineteen sheets, and a surface that only
addresses one at a time is one you drive with a shell loop.
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from art import profile as profile_mod
from art.audit import rows as audit_rows
from art.measure import read_legacy
from art.spec import DEVICES, DEVICE_BY_KEY, TARGET_TILE_PX

console = Console()


def _load(project: Path | None) -> profile_mod.Profile:
    path = (project / profile_mod.FILENAME) if project else profile_mod.find()
    if path is None or not path.is_file():
        raise click.ClickException(
            "No art.yaml here or above. Run `art init` in the game folder."
        )
    return profile_mod.load(path)


def _atlas_path(prof: profile_mod.Profile) -> Path:
    declared = prof.raw.get("atlas")
    if declared:
        return prof.root / declared
    for guess in ("web/atlas.json", "atlas.json", "dist/atlas.json"):
        p = prof.root / guess
        if p.is_file():
            return p
    raise click.ClickException(
        "No atlas.json found. Set `atlas:` in art.yaml to point at it."
    )


@click.group(invoke_without_command=True)
@click.option("--project", "-p", type=click.Path(file_okay=False, path_type=Path),
              default=None, help="The folder holding art.yaml. Defaults to the nearest one above $PWD.")
@click.pass_context
def main(ctx: click.Context, project: Path | None) -> None:
    """Sprites and concept art for games.

    Run it inside a game folder. With no subcommand it opens the preview.
    """
    ctx.ensure_object(dict)
    ctx.obj["project"] = project
    if ctx.invoked_subcommand is None:
        console.print("[yellow]`art view` is not built yet.[/yellow] "
                      "Try [bold]art audit[/bold] or [bold]art status[/bold].")


# ---------------------------------------------------------------- init --

@main.command()
@click.option("--from-atlas", "from_atlas", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None, help="An existing atlas.json to draft subjects from.")
@click.option("--split", "splits", multiple=True,
              help="Explode a group into one subject per entry (repeatable). "
                   "AXI's `enemy` holds four characters, not four animations.")
@click.option("--height", "heights", multiple=True, metavar="NAME=TILES",
              help="Set a subject's height in tiles (repeatable).")
@click.option("--tile-px", default=TARGET_TILE_PX, show_default=True, help="The target tile size.")
@click.option("--force", is_flag=True, help="Overwrite an existing art.yaml.")
@click.option("--dry-run", is_flag=True, help="Print the draft; write nothing.")
@click.pass_context
def init(ctx, from_atlas, splits, heights, tile_px, force, dry_run) -> None:
    """Draft an art.yaml for this project.

    The draft is a starting point, not an answer: which entries are separate
    characters and how tall each one stands are art decisions the atlas cannot
    state. What it does get right is the inventory, so nothing is forgotten.
    """
    root = ctx.obj["project"] or Path.cwd()
    out = root / profile_mod.FILENAME
    if out.exists() and not force and not dry_run:
        raise click.ClickException(f"{out} exists. Pass --force to overwrite.")

    if from_atlas is None:
        for guess in ("web/atlas.json", "atlas.json"):
            if (root / guess).is_file():
                from_atlas = root / guess
                break

    overrides = {}
    for h in heights:
        name, _, value = h.partition("=")
        overrides[name.strip()] = float(value)

    subjects: dict[str, dict] = {}
    if from_atlas:
        groups = read_legacy(from_atlas)
        for gname, group in groups.items():
            if gname in splits:
                for entry, anim in group.anims.items():
                    kind = "tile" if len(anim.frames) == 1 else "character"
                    subjects[entry] = {
                        "kind": kind, "state": "legacy",
                        "source": {"group": gname, "entry": entry},
                    }
                continue
            single = all(len(a.frames) == 1 for a in group.anims.values())
            if single:
                # 61 terrain and decor entries, each one frame. Every one is
                # its own subject; the kind is a judgement left to the author.
                for entry in group.anims:
                    subjects[entry] = {
                        "kind": "tile", "state": "legacy",
                        "source": {"group": gname, "entry": entry},
                    }
                continue
            prefix = _common_prefix(list(group.anims))
            name = prefix.rstrip("_") or gname
            subjects[name] = {
                "kind": "character", "state": "legacy",
                "source": {"group": gname, "prefix": prefix},
                "sheets": {name: [a[len(prefix):] for a in group.anims]},
            }

    for name, body in subjects.items():
        if body["kind"] == "character":
            body["height_tiles"] = overrides.get(name, 1.0)
        elif body["kind"] == "prop":
            body["width_tiles"] = overrides.get(name, 1.0)

    data = {
        "tile_px": tile_px,
        "canvas": 2048,
        "backdrop": "#FC309B",
        "atlas": str(from_atlas.relative_to(root)) if from_atlas else "web/atlas.json",
        "style": "",
        "subjects": subjects,
    }
    import yaml
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    if dry_run:
        console.print(text)
        return
    out.write_text(text)
    chars = sum(1 for b in subjects.values() if b["kind"] == "character")
    console.print(f"[green]wrote[/green] {out}  "
                  f"[dim]{len(subjects)} subjects ({chars} characters), all state=legacy[/dim]")
    console.print("[dim]Set height_tiles per character, then re-run `art audit`.[/dim]")


def _common_prefix(names: list[str]) -> str:
    """The shared `frog_` in frog_idle, frog_walk. Empty when there is none."""
    if len(names) < 2:
        return ""
    first = names[0]
    for i in range(len(first), 0, -1):
        cand = first[:i]
        if cand.endswith("_") and all(n.startswith(cand) for n in names):
            return cand
    return ""


# --------------------------------------------------------------- audit --

@main.command()
@click.argument("names", nargs=-1)
@click.option("--device", "device_keys", multiple=True,
              help="Limit the columns to these devices (repeatable).")
@click.option("--at-tile-px", type=int, default=None,
              help="Report as if a tile were this many pixels, instead of the real devices.")
@click.pass_context
def audit(ctx, names, device_keys, at_tile_px) -> None:
    """Measure what ships against what the spec asks for.

    Reports the truth regardless of a subject's state: a `legacy` subject is
    still upscaled, and pretending otherwise is how it stays that way.
    """
    prof = _load(ctx.obj["project"])
    groups = read_legacy(_atlas_path(prof))

    devices = DEVICES
    if device_keys:
        chosen = []
        for k in device_keys:
            d = DEVICE_BY_KEY.get(k.lower())
            if d is None:
                raise click.ClickException(
                    f"Unknown device {k!r}. Known: {', '.join(DEVICE_BY_KEY)}")
            chosen.append(d)
        devices = tuple(chosen)

    data = audit_rows(prof, groups, devices)
    if names:
        wanted = set(names)
        data = [r for r in data if r.name in wanted]
    if not data:
        console.print("[yellow]Nothing to audit.[/yellow]")
        return

    table = Table(title=f"Upscale at {prof.tile_px} px per tile", header_style="bold")
    table.add_column("subject"); table.add_column("state", style="dim")
    table.add_column("source", justify="right")
    table.add_column("needs", justify="right")
    for d in devices:
        table.add_column(f"{d.name}\n{d.px_per_tile}px", justify="right")
    table.add_column("verdict")

    for r in data:
        cells = []
        for d in devices:
            f = r.factors[d.name]
            style = "green" if f <= 1.0 else ("yellow" if f <= 2 else "red")
            cells.append(f"[{style}]{f:.1f}×[/{style}]")
        v = r.verdict()
        vstyle = {"ok": "green", "soft": "yellow"}.get(v, "bold red")
        table.add_row(r.name, r.state, f"{r.src_w}×{r.src_h}",
                      f"{r.required_px}px" if r.required_px else "—",
                      *cells, f"[{vstyle}]{v}[/{vstyle}]")
    console.print(table)
    worst = data[0]
    console.print(f"[dim]worst: [/dim][bold]{worst.name}[/bold] "
                  f"[dim]at[/dim] {worst.worst:.1f}× [dim]— fix this one first[/dim]")


# -------------------------------------------------------------- status --

@main.command()
@click.pass_context
def status(ctx) -> None:
    """The board: every subject, its state, and what it is waiting on."""
    prof = _load(ctx.obj["project"])
    by_state: dict[str, list[str]] = {}
    for name, s in prof.subjects.items():
        by_state.setdefault(s.state, []).append(name)
    table = Table(header_style="bold")
    table.add_column("state"); table.add_column("n", justify="right"); table.add_column("subjects")
    for st in ("todo", "drawn", "accepted", "legacy"):
        got = sorted(by_state.get(st, []))
        if not got:
            continue
        shown = ", ".join(got[:8]) + (f" … +{len(got) - 8}" if len(got) > 8 else "")
        table.add_row(st, str(len(got)), shown)
    console.print(table)
    console.print(f"[dim]tile target {prof.tile_px}px · canvas {prof.canvas}² · "
                  f"backdrop {prof.backdrop}[/dim]")


if __name__ == "__main__":
    main()
