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
from art.profile import backdrop_for
from art.refs import resolve as resolve_refs
from art import draw as draw_mod
from art import effects as fx_mod
from art import seams as seams_mod
from art.prompt import build as build_prompt
from art import cut as cut_mod
from art import view as view_mod
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
        subj = prof.subjects[pl.subject]
        warn = _backdrop_warning(prof, subj)
        if warn:
            console.print(f"  [bold red]backdrop:[/bold red] {warn}")
        refs = resolve_refs(prof, subj)
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


def _issue_note(subject, sheet) -> str:
    """Flagged frames, phrased as instructions for the next generation."""
    rows = set(sheet.anims)
    items = [i for i in (subject.raw.get("issues") or []) if i["anim"] in rows]
    if not items:
        return ""
    parts = []
    for i in items:
        where = f"in the {i['anim']} row, frame {i['frame']} (counting from 0)"
        parts.append(f"{where}: {i['note']}" if i.get("note")
                     else f"{where} needs redrawing")
    return ("Fix these specifically and keep everything else identical -- "
            + "; ".join(parts) + ".")


def _backdrop_warning(prof, subject) -> str:
    """Whether this subject's backdrop would be keyed out of the character."""
    ref = next((r for r in resolve_refs(prof, subject) if r.role == "identity"), None)
    if ref is None:
        return ""
    try:
        import numpy as np
        from PIL import Image
        a = np.asarray(Image.open(ref.path).convert("RGB"))
    except Exception:
        return ""
    art = ~((a > 235).all(axis=-1))
    key = backdrop_for(prof, subject)
    bad = cut_mod.spill_conflict(a, cut_mod.hex_to_rgb(key), art)
    if bad <= 0.30:
        return ""
    ranked = cut_mod.best_backdrop(a, art)
    safe = ", ".join(f"{n} ({v})" for n, v, score in ranked[:2] if score <= 0.10)
    return (f"{key} would despill {bad * 100:.0f}% of this character's own pixels "
            f"-- its dominant channel is the character's too."
            + (f" Try {safe}." if safe else ""))


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
    flagged = _issue_note(subject, sh)
    if flagged:
        note = (note + " " if note else "") + flagged
        console.print(f"[dim]carrying {len(subject.raw.get('issues') or [])} "
                      f"flagged frame(s) into the prompt[/dim]")
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


# ---------------------------------------------------------------- view --

def _candidate_rows(path, backdrop, names, expect, write_to, wrapped=0):
    """Detect the frames on a generated sheet, and write it out KEYED.

    Writing the raw sheet would leave every frame sitting in a rectangle of
    backdrop, which is what the preview showed before this did the keying.
    """
    import numpy as np
    from PIL import Image

    key = cut_mod.hex_to_rgb(backdrop)
    rgb = np.asarray(Image.open(path).convert("RGB"))
    _, rows = cut_mod.detect(rgb, key, expect=expect)
    write_to.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(cut_mod.keyed(rgb, key)).save(write_to)

    out, short, extra = {}, [], []

    if wrapped:
        # The whole grid is ONE animation. Rows are a layout, not a list of
        # animations, so they concatenate -- left to right, then top to bottom,
        # which is the order they were asked for and the order find_rows returns.
        boxes = [b for row in rows for b in row.boxes]
        name = names[0] if names else "frames"
        out[name] = [b.as_list() for b in boxes]
        if len(boxes) != wrapped:
            short.append(f"{name} ({len(boxes)} of {wrapped})")
        return out, short, extra

    for i, row in enumerate(rows):
        # A sheet can hold rows the profile no longer wants -- the frog's
        # candidate still carries the `sit` row that was retired after it was
        # drawn. Naming it `row3` hides that; saying it is unassigned does not.
        named = i < len(names)
        name = names[i] if named else f"unassigned row {i + 1}"
        out[name] = [b.as_list() for b in row.boxes]
        if not named:
            extra.append(name)
        if not row.complete:
            short.append(f"{name} ({len(row.boxes)} of {expect})")
    return out, short, extra


@main.command()
@click.argument("subject")
@click.option("--candidate", "candidate", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None, help="A sheet to preview. Defaults to the newest candidate.")
@click.option("--port", default=8731, show_default=True)
@click.option("--no-open", "no_open", is_flag=True, help="Serve, but do not open a browser.")
@click.pass_context
def view(ctx, subject, candidate, port, no_open) -> None:
    """Preview the animations in a browser, at real device sizes.

    Shows what ships today beside the candidate, both scaled the way the game
    scales them, so the comparison is the one the player would see.
    """
    import http.server, socketserver, threading, webbrowser

    prof = _load(ctx.obj["project"])
    if subject not in prof.subjects:
        raise click.ClickException(f"Unknown subject: {subject}")
    sub = prof.subjects[subject]
    source = sub.raw.get("source") or {}
    prefix = source.get("prefix", "")
    first_sheet = next(iter(sub.sheets.values()), None) if sub.sheets else None
    if isinstance(first_sheet, dict):
        anim_names = list(first_sheet.get("anims") or [])
    else:
        anim_names = list(first_sheet or [])

    serve = Path(__import__("tempfile").mkdtemp(prefix="art-view-"))
    images, per_row = {}, {}

    # What ships today.
    groups = _groups_or_empty(prof)
    group = groups.get(source.get("group", subject))
    if group:
        atlas_json = _atlas_path(prof)
        img = atlas_json.parent / (__import__("json").loads(atlas_json.read_text()).get("image") or "atlas.png")
        if img.is_file():
            images["today.png"] = img
            ref = None
            retired = set(sub.raw.get("retired") or [])
            for anim_name, anim in group.anims.items():
                short = anim_name[len(prefix):] if prefix else anim_name
                if short in retired:
                    continue
                frames = [[f.x, f.y, f.w, f.h, f.lift] for f in anim.frames]
                if ref is None or short == "idle":
                    ref = anim.frames[0].h
                per_row.setdefault(short, []).append(
                    {"label": "today", "image": "today.png", "frames": frames, "ref_h": ref})
            for variants in per_row.values():
                for v in variants:
                    if v["label"] == "today":
                        v["ref_h"] = ref

    # The candidate.
    if candidate is None:
        pool = sorted((prof.root / "art" / "candidates").glob(f"{subject}*.png"))
        candidate = pool[-1] if pool else None
    if candidate:
        pl = plan_subject(prof, sub, groups)
        expect = pl.sheets[0].cols if pl.sheets else None
        detected, short, extra = _candidate_rows(
            candidate, backdrop_for(prof, sub), anim_names, expect,
            serve / "candidate.png",
            wrapped=(pl.sheets[0].wrapped if pl.sheets else 0))
        if short:
            console.print("[yellow]incomplete rows:[/yellow] " + ", ".join(short)
                          + " [dim]— frames touching, below the 24px the rules ask for[/dim]")
        if extra:
            console.print(f"[yellow]{len(extra)} row(s) on the sheet the profile "
                          f"does not name[/yellow] [dim]— drawn before the "
                          f"animation list changed; harmless, and dropped by pack[/dim]")
        ref = next((v[0][3] for k, v in detected.items() if k == "idle"),
                   next(iter(detected.values()))[0][3] if detected else 1)
        for name, frames in detected.items():
            per_row.setdefault(name, []).append(
                {"label": "candidate", "image": "candidate.png",
                 "frames": frames, "ref_h": ref})

    if not per_row:
        raise click.ClickException("Nothing to preview: no atlas entry and no candidate.")

    def order(item):
        name = item[0]
        has_new = any(v["label"] == "candidate" for v in item[1])
        rank = anim_names.index(name) if name in anim_names else len(anim_names)
        return (0 if has_new else 1, rank, name)

    rows = []
    for name, variants in sorted(per_row.items(), key=order):
        first = variants[0]
        # A game scales a character by its IDLE frame and applies that scale to
        # every row. `today` has an idle to measure. A candidate that is only
        # one animation does not, so scaling it by its own first frame would
        # render it at an unrelated size and the comparison would be about
        # scale rather than about sharpness -- which is the whole point here.
        #
        # So each later variant is normalised to render at the same apparent
        # size as the first, and only the pixel density differs.
        base = variants[0]
        base_mean = sum(f[3] for f in base["frames"]) / len(base["frames"])
        for v in variants[1:]:
            mean = sum(f[3] for f in v["frames"]) / len(v["frames"])
            if base_mean > 0 and mean > 0:
                v["ref_h"] = mean * base["ref_h"] / base_mean
        rows.append({"name": name, "frames": first["frames"],
                     "src_h": max(f[3] for f in first["frames"]),
                     "spread": max(f[4] for f in first["frames"]),
                     "variants": variants})

    try:
        normalised = fx_mod.normalise(sub.raw.get("effects") or {})
    except fx_mod.EffectError as exc:
        raise click.ClickException(f"art.yaml effects: {exc}") from exc

    data = {"devices": view_mod.device_list(),
            "subject": subject,
            "issues": list(sub.raw.get("issues") or []),
            "effects": {r["name"]: fx_mod.for_anim(normalised, r["name"]) for r in rows},
            "catalogue": fx_mod.catalogue(),
            "height_tiles": sub.height_tiles or 1.0, "rows": rows}
    view_mod.build(serve, f"{subject}",
                   f"{len(rows)} animations · {sub.height_tiles or 1.0} tiles tall "
                   f"· target {prof.tile_px}px per tile", data, images)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k): super().__init__(*a, directory=str(serve), **k)
        def log_message(self, *a): pass

        def _body(self):
            size = int(self.headers.get("Content-Length") or 0)
            return __import__("json").loads(self.rfile.read(size) or b"{}")

        def do_POST(self):
            """Write back to art.yaml.

            The page is where a bad frame is noticed and where a sway is tuned,
            so it is where both are recorded -- into art.yaml, which is source,
            so they survive, show up in `art issues`, and reach the generator.
            """
            if self.path == "/effects":
                self._save_effects(); return
            if self.path != "/flag":
                self.send_error(404); return
            try:
                body = self._body()
                anim, frame = str(body["anim"]), int(body["frame"])
                note = str(body.get("note") or "").strip()
            except Exception as exc:
                self.send_error(400, f"bad flag: {exc}"); return

            issues = list(sub.raw.get("issues") or [])
            issues = [i for i in issues
                      if not (i.get("anim") == anim and i.get("frame") == frame)]
            issues.append({"anim": anim, "frame": frame, "note": note})
            issues.sort(key=lambda i: (i["anim"], i["frame"]))
            sub.raw["issues"] = issues
            profile_mod.save(prof)
            console.print(f"[yellow]flagged[/yellow] {subject}/{anim} frame {frame}"
                          + (f" — {note}" if note else ""))
            self.send_response(204); self.end_headers()

        def _save_effects(self):
            try:
                body = self._body()
                anim = str(body["anim"])
                given = body.get("effects") or {}
                # Strip what the tool fills in, so art.yaml keeps only what was
                # actually chosen and a later default change still reaches it.
                trimmed = {
                    name: {k: v for k, v in vals.items()
                           if k != "anchor" and not (k == "phase" and v == "none")}
                    for name, vals in given.items()
                }
                fx_mod.normalise({anim: trimmed})
            except Exception as exc:
                self.send_error(400, str(exc)); return

            block = dict(sub.raw.get("effects") or {})
            if trimmed:
                block[anim] = trimmed
            else:
                block.pop(anim, None)
            sub.raw["effects"] = block
            profile_mod.save(prof)
            names = ", ".join(trimmed) or "none"
            console.print(f"[green]effects saved[/green] {subject}/{anim}: {names}")
            self.send_response(204); self.end_headers()

    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = socketserver.TCPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        # Errno 48 on a live listener, which allow_reuse_address does not help
        # with -- it only covers TIME_WAIT. A stack trace here tells the user
        # nothing they can act on.
        raise click.ClickException(
            f"Port {port} is already in use — another `art view` is probably "
            f"still running. Try `--port {port + 1}`, or stop the other one."
        ) from exc
    with httpd:
        url = f"http://127.0.0.1:{port}/"
        console.print(f"[green]preview[/green] {url}  [dim]ctrl-c to stop[/dim]")
        if not no_open:
            threading.Timer(0.3, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            console.print("[dim]stopped[/dim]")


# -------------------------------------------------------------- issues --

@main.command()
@click.argument("subject", required=False)
@click.option("--clear", "clear_spec", metavar="ANIM[:FRAME]",
              help="Drop flags for an animation, or one frame of it.")
@click.pass_context
def issues(ctx, subject, clear_spec) -> None:
    """Frames flagged in the preview as wrong.

    These ride along as art direction the next time the sheet is drawn, so a
    note written while looking at a bad frame reaches the generator.
    """
    prof = _load(ctx.obj["project"])
    names = [subject] if subject else list(prof.subjects)
    if subject and subject not in prof.subjects:
        raise click.ClickException(f"Unknown subject: {subject}")

    if clear_spec:
        if not subject:
            raise click.UsageError("Name the subject whose flags to clear.")
        anim, _, frame = clear_spec.partition(":")
        sub = prof.subjects[subject]
        kept = [i for i in (sub.raw.get("issues") or [])
                if not (i["anim"] == anim and (not frame or i["frame"] == int(frame)))]
        dropped = len(sub.raw.get("issues") or []) - len(kept)
        sub.raw["issues"] = kept
        profile_mod.save(prof)
        console.print(f"[green]cleared {dropped} flag(s)[/green] on {subject}/{clear_spec}")
        return

    table = Table(header_style="bold")
    table.add_column("subject"); table.add_column("animation")
    table.add_column("frame", justify="right"); table.add_column("note")
    total = 0
    for name in names:
        for i in sorted(prof.subjects[name].raw.get("issues") or [],
                        key=lambda i: (i["anim"], i["frame"])):
            table.add_row(name, i["anim"], str(i["frame"]),
                          i.get("note") or "[dim](no note)[/dim]")
            total += 1
    if not total:
        console.print("[green]No flagged frames.[/green]")
        return
    console.print(table)
    console.print(f"[dim]{total} flagged — they become art direction on the next "
                  f"`art draw`.[/dim]")


# ------------------------------------------------------------- effects --

@main.command(name="effects")
@click.argument("subject", required=False)
@click.pass_context
def effects_cmd(ctx, subject) -> None:
    """Procedural motion applied at draw time, and what is available.

    An effect is metadata, not pixels: a breathing idle costs one drawn frame
    and a line of YAML instead of six drawn frames. Tune them live in
    `art view`, which saves back here.
    """
    prof = _load(ctx.obj["project"])
    names = [subject] if subject else list(prof.subjects)
    if subject and subject not in prof.subjects:
        raise click.ClickException(f"Unknown subject: {subject}")

    table = Table(header_style="bold", title="In use")
    table.add_column("subject"); table.add_column("applies to")
    table.add_column("effect"); table.add_column("settings")
    used = 0
    for name in names:
        sub = prof.subjects[name]
        try:
            normalised = fx_mod.normalise(sub.raw.get("effects") or {})
        except fx_mod.EffectError as exc:
            raise click.ClickException(f"{name}: {exc}") from exc
        for anim, effects in normalised.items():
            for fx_name, values in effects.items():
                shown = " ".join(f"{k}={v}" for k, v in values.items()
                                 if k not in ("anchor",))
                table.add_row(name, anim, fx_name, shown); used += 1
    if used:
        console.print(table)
    else:
        console.print("[dim]No effects set.[/dim]")

    cat = Table(header_style="bold", title="Available")
    cat.add_column("effect"); cat.add_column("anchor", style="dim")
    cat.add_column("parameters"); cat.add_column("what it is for")
    for e in fx_mod.catalogue():
        cat.add_row(e["name"], e["anchor"],
                    ", ".join(f'{p["name"]} ({p["low"]}–{p["high"]}{p["unit"]})'
                              for p in e["params"]), e["help"])
    console.print(cat)
