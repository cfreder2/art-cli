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
from art.plan import plan_subject
from art.refs import resolve as resolve_refs
from art import draw as draw_mod
from art import seams as seams_mod
from art.prompt import build as build_prompt
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
@click.option("--seamless", "seamless_names", multiple=True, metavar="NAME",
              help="NAME or NAME=horizontal|vertical|both. Which wraps this tile "
                   "must make (repeatable). Ground repeats sideways but is never "
                   "stacked, so it is horizontal, not both.")
@click.option("--style-ref", "style_refs", multiple=True, metavar="PATH",
              help="Art that defines the look. Every prompt carries it (repeatable).")
@click.option("--sheet", "sheet_paths", multiple=True, metavar="GROUP=PATH",
              help="Where a group's source sheet lives (repeatable). A redraw "
                   "attaches it as the identity reference automatically.")
@click.option("--tile-px", default=TARGET_TILE_PX, show_default=True, help="The target tile size.")
@click.option("--canvas", default=1254, show_default=True,
              help="What the generator actually returns. gpt-image gives 1254 square, "
                   "whatever size the prompt asks for -- measured, not assumed.")
@click.option("--force", is_flag=True, help="Overwrite an existing art.yaml.")
@click.option("--dry-run", is_flag=True, help="Print the draft; write nothing.")
@click.pass_context
def init(ctx, from_atlas, splits, heights, seamless_names, style_refs,
         sheet_paths, tile_px, canvas, force, dry_run) -> None:
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

    group_sheets = {}
    for spec in sheet_paths:
        g, _, path = spec.partition("=")
        group_sheets[g.strip()] = path.strip()

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
                        "source": _source(gname, group_sheets, entry=entry),
                    }
                continue
            single = all(len(a.frames) == 1 for a in group.anims.values())
            if single:
                # 61 terrain and decor entries, each one frame. Every one is
                # its own subject; the kind is a judgement left to the author.
                for entry in group.anims:
                    subjects[entry] = {
                        "kind": "tile", "state": "legacy",
                        "source": _source(gname, group_sheets, entry=entry),
                    }
                continue
            prefix = _common_prefix(list(group.anims))
            name = prefix.rstrip("_") or gname
            subjects[name] = {
                "kind": "character", "state": "legacy",
                "source": _source(gname, group_sheets, prefix=prefix),
                "sheets": {name: [a[len(prefix):] for a in group.anims]},
            }

    for spec in seamless_names:
        name, _, axis = spec.partition("=")
        name, axis = name.strip(), (axis.strip() or "both")
        if name not in subjects:
            raise click.ClickException(f"--seamless {name}: no such entry in the atlas.")
        if axis not in ("horizontal", "vertical", "both"):
            raise click.ClickException(
                f"--seamless {name}={axis}: expected horizontal, vertical or both.")
        subjects[name]["seamless"] = axis

    for name, body in subjects.items():
        if body["kind"] == "character":
            body["height_tiles"] = overrides.get(name, 1.0)
            # Drawn facing right and mirrored at draw time. Set false only for a
            # subject whose art is asymmetric enough that flipping it is wrong.
            body["mirror"] = True
        elif body["kind"] == "prop":
            body["width_tiles"] = overrides.get(name, 1.0)

    data = {
        "tile_px": tile_px,
        "canvas": canvas,
        "backdrop": "#FC309B",
        "atlas": str(from_atlas.relative_to(root)) if from_atlas else "web/atlas.json",
        "style_ref": list(style_refs),
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


def _source(group: str, sheets: dict[str, str], **extra) -> dict:
    """Where this subject came from, and the sheet it was drawn on."""
    out = {"group": group, **{k: v for k, v in extra.items() if v}}
    if group in sheets:
        out["sheet"] = sheets[group]
    return out


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
@click.option("--json", "as_json", is_flag=True, help="Machine-readable, for CI.")
@click.pass_context
def audit(ctx, names, device_keys, at_tile_px, as_json) -> None:
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
        missing = wanted - set(prof.subjects)
        if missing:
            raise click.ClickException(
                f"Unknown subject(s): {', '.join(sorted(missing))}")
        data = [r for r in data if r.name in wanted]
    if not data:
        console.print("[yellow]Nothing to audit.[/yellow]")
        return

    if as_json:
        import json as _json
        click.echo(_json.dumps([
            {"subject": r.name, "state": r.state, "reference_anim": r.anim,
             "source": [r.src_w, r.src_h], "required_px": r.required_px,
             "upscale": {k: round(v, 3) for k, v in r.factors.items()},
             "verdict": r.verdict()} for r in data], indent=2))
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


# ---------------------------------------------------------------- plan --

@main.command()
@click.argument("names", nargs=-1)
@click.option("--all", "everything", is_flag=True, help="Every subject.")
@click.option("--budget", is_flag=True,
              help="Total the generations instead of laying each sheet out.")
@click.option("--tight", is_flag=True,
              help="Pack as many animation rows as clear the minimum height. "
                   "Fewer sheets to generate, less room for a tall pose.")
@click.pass_context
def plan(ctx, names, everything, budget, tight) -> None:
    """What to ask the generator for, and what it will cost.

    Counts one facing by default. A 2D game mirrors horizontally, so a sheet
    drawn facing right already covers left; only a subject marked
    `mirror: false` is asymmetric enough to need both, and it says so.
    """
    prof = _load(ctx.obj["project"])
    try:
        groups = read_legacy(_atlas_path(prof))
    except click.ClickException:
        groups = {}

    if not names and not everything:
        raise click.UsageError("Name a subject, or pass --all.")
    wanted = set(names)
    chosen = [s for n, s in prof.subjects.items() if everything or n in wanted]
    missing = wanted - set(prof.subjects)
    if missing:
        raise click.ClickException(f"Unknown subject(s): {', '.join(sorted(missing))}")
    plans = [plan_subject(prof, s, groups, tight=tight) for s in chosen]

    if budget:
        table = Table(title="Generation budget", header_style="bold")
        table.add_column("subject"); table.add_column("kind", style="dim")
        table.add_column("sheets", justify="right")
        table.add_column("facings", justify="right")
        table.add_column("images", justify="right")
        total = 0
        for pl in sorted(plans, key=lambda p: -p.generations):
            if pl.kind == "tile":
                continue
            total += pl.generations
            table.add_row(pl.subject, pl.kind, str(len(pl.sheets)),
                          str(pl.facings) + ("" if pl.mirrored else " [red]both[/red]"),
                          str(pl.generations))
        console.print(table)
        tiles = sum(1 for pl in plans if pl.kind == "tile")
        console.print(f"[bold]{total}[/bold] character/prop generations"
                      + (f" [dim]+ {tiles} terrain entries to pack into grids[/dim]" if tiles else ""))
        console.print("[dim]one image per sheet per facing — mirroring at draw time "
                      "is what keeps the second facing off this bill[/dim]")
        return

    for pl in plans:
        head = f"[bold]{pl.subject}[/bold] [dim]{pl.kind}[/dim]"
        if pl.kind != "tile":
            head += f"  min drawn [bold]{pl.min_drawn}px[/bold]"
        console.print(head)
        if pl.sheets:
            t = Table(box=None, header_style="dim", pad_edge=False)
            t.add_column("sheet"); t.add_column("grid"); t.add_column("cell")
            t.add_column("animations"); t.add_column("")
            for sh in pl.sheets:
                ok = "[green]fits[/green]" if sh.fits else "[red]TOO SMALL[/red]"
                t.add_row(sh.name, f"{sh.cols}×{sh.rows}", f"{sh.cell_w}×{sh.cell_h}",
                          ", ".join(sh.anims) or "—", ok)
            console.print(t)
        refs = resolve_refs(prof, prof.subjects[pl.subject])
        if refs:
            console.print("  [dim]references:[/dim] " + ", ".join(
                f"[bold]{r.role}[/bold]=" + r.path.name for r in refs))
        elif pl.kind != "tile":
            console.print("  [yellow]no references[/yellow][dim] — a redraw with "
                          "nothing attached comes back a different character[/dim]")
        for note in pl.notes:
            console.print(f"  [dim]· {note}[/dim]")
        if pl.kind != "tile":
            console.print(f"  [dim]→[/dim] [bold]{pl.generations}[/bold] "
                          f"[dim]generation(s) at {prof.canvas}² canvas[/dim]")
        console.print()


# --------------------------------------------------------------- check --

@main.command()
@click.argument("names", nargs=-1)
@click.option("--all", "everything", is_flag=True, help="Every subject.")
@click.option("--seams", "seams_only", is_flag=True,
              help="Only the tiling check: does each seamless tile repeat without a line?")
@click.pass_context
def check(ctx, names, everything, seams_only) -> None:
    """Verify art against the rules. Nonzero exit on a violation.

    Strict about `accepted` subjects and quiet about `legacy` ones, so a build
    can stay green through a migration that takes weeks. `audit` ignores that
    distinction and always reports the truth.
    """
    import numpy as np
    from PIL import Image

    prof = _load(ctx.obj["project"])
    atlas_json = _atlas_path(prof)
    groups = read_legacy(atlas_json)
    image_path = atlas_json.parent / (__import__("json").loads(atlas_json.read_text()).get("image") or "atlas.png")
    if not image_path.is_file():
        raise click.ClickException(f"Atlas image not found: {image_path}")
    sheet = Image.open(image_path).convert("RGBA")
    px = np.asarray(sheet)

    wanted = set(names)
    failures = 0
    table = Table(title="Seams", header_style="bold")
    table.add_column("tile"); table.add_column("size", justify="right")
    table.add_column("margin", justify="right")
    table.add_column("h-wrap", justify="right"); table.add_column("v-wrap", justify="right")
    table.add_column("verdict")
    checked = 0

    for name, subject in prof.subjects.items():
        if not everything and wanted and name not in wanted:
            continue
        if not subject.raw.get("seamless"):
            continue
        source = subject.raw.get("source") or {}
        group = groups.get(source.get("group", name))
        entry = source.get("entry")
        if not group or (entry and entry not in group.anims):
            continue
        frame = group.anims[entry or next(iter(group.anims))].frames[0]
        crop = px[frame.y:frame.y + frame.h, frame.x:frame.x + frame.w]
        if crop.size == 0:
            continue
        checked += 1
        rgb, alpha = crop[..., :3], crop[..., 3]
        margin = seams_mod.transparent_margin(alpha)
        axes = seams_mod.axes_for(subject.raw.get("seamless"))
        scores = {s.axis: s for s in seams_mod.score(rgb, alpha, axes)}
        worst = max(scores.values(), key=lambda s: s.ratio)
        bad = (not worst.seamless) or any(v > 0 for v in margin.values())
        strict = subject.state == "accepted"
        if bad and strict:
            failures += 1
        m = max(margin.values())
        table.add_row(
            name, f"{frame.w}×{frame.h}",
            f"[red]{m}px[/red]" if m else "[green]0[/green]",
            f"{scores['horizontal'].ratio:.1f}×" if "horizontal" in scores else "[dim]—[/dim]",
            f"{scores['vertical'].ratio:.1f}×" if "vertical" in scores else "[dim]—[/dim]",
            ("[green]" if not bad else ("[bold red]" if strict else "[yellow]"))
            + worst.verdict() + ("[/green]" if not bad else ("[/bold red]" if strict else "[/yellow]")),
        )

    if not checked:
        console.print("[yellow]No subjects marked `seamless: true`.[/yellow] "
                      "[dim]Terrain that tiles needs it; decor does not.[/dim]")
        return
    console.print(table)
    console.print("[dim]h-wrap/v-wrap: the step across the wrap over the tile's own "
                  "median step. ~1× reads as continuous; large is a line.[/dim]")
    if failures:
        console.print(f"[bold red]{failures} accepted tile(s) failed.[/bold red]")
        raise SystemExit(1)


def _sheet_for(prof, name):
    """Resolve `frog-1` or `frog` to (subject, sheet plan, whole plan)."""
    for sub_name, subject in prof.subjects.items():
        pl = plan_subject(prof, subject, _groups_or_empty(prof))
        for sh in pl.sheets:
            if sh.name == name or (sub_name == name and len(pl.sheets) == 1):
                return subject, sh, pl
    raise click.ClickException(
        f"No sheet named {name!r}. `art plan --all` lists them.")


def _groups_or_empty(prof):
    try:
        return read_legacy(_atlas_path(prof))
    except click.ClickException:
        return {}


# -------------------------------------------------------------- prompt --

@main.command()
@click.argument("sheet")
@click.option("--note", default="", help="Extra art direction for this sheet.")
@click.pass_context
def prompt(ctx, sheet, note) -> None:
    """The exact text a generation would be sent. Writes nothing, costs nothing."""
    prof = _load(ctx.obj["project"])
    subject, sh, pl = _sheet_for(prof, sheet)
    refs = resolve_refs(prof, subject)
    click.echo(build_prompt(prof, subject, sh, pl, refs, note))
    if refs:
        console.print("\n[dim]attachments, in order: "
                      + ", ".join(f"{i}. {r.role}={r.path.name}"
                                  for i, r in enumerate(refs, 1)) + "[/dim]")


# ---------------------------------------------------------------- draw --

@main.command()
@click.argument("sheet")
@click.option("--note", default="", help="Extra art direction for this sheet.")
@click.option("--model", "-m", default=None,
              help="The AGENT model. It relays the prompt; it is not the image "
                   "model, which the media service picks and no flag can pin.")
@click.option("--dry-run", is_flag=True, help="Show the prompt and the command; generate nothing.")
@click.pass_context
def draw(ctx, sheet, note, model, dry_run) -> None:
    """Generate a candidate sheet. This is the only verb that spends anything."""
    prof = _load(ctx.obj["project"])
    subject, sh, pl = _sheet_for(prof, sheet)
    refs = resolve_refs(prof, subject)
    text = build_prompt(prof, subject, sh, pl, refs, note)
    out, n = draw_mod.next_candidate(prof.root / "art" / "candidates", sh.name)

    if dry_run:
        click.echo(text)
        console.print(f"\n[dim]would write[/dim] {out}")
        console.print("[dim]attachments: [/dim]" + (", ".join(
            f"{i}. {r.role}={r.path.name}" for i, r in enumerate(refs, 1)) or "none"))
        return

    console.print(f"[dim]generating[/dim] [bold]{sh.name}[/bold] "
                  f"[dim]— {sh.cols}×{sh.rows}, ≥{sh.min_drawn}px, "
                  f"{len(refs)} reference(s)[/dim]")
    try:
        made = draw_mod.generate(text, [str(r.path) for r in refs], out, model=model)
    except draw_mod.DrawError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]candidate {n}[/green] → {made.path}  "
                  f"[dim]{made.seconds:.0f}s[/dim]")
    console.print(f"[dim]next:[/dim] art cut {sh.name} --from {made.path.name}")
