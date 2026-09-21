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
from art import pack as pack_mod
from art import review as review_mod
from art import prompt as prompt_mod
from art import rules as rules_mod
from art import scene as scene_mod
from art import seamless as seamless_mod
from art import template as tpl_mod
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

    data = [r for r in audit_rows(prof, groups, devices) if r.state != "retired"]
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
    for st in ("todo", "drawn", "accepted", "legacy", "retired"):
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
    chosen = [s for n, s in prof.subjects.items()
              if (everything or n in wanted) and s.state != "retired"]
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


def _check_subject(prof, name, subject):
    """Run every rule over one subject's accepted sheet."""
    import numpy as np
    from PIL import Image

    findings = []
    accepted = subject.raw.get("accepted") or {}
    if not accepted:
        return findings, 0

    checked = 0
    for sheet_name, rec in accepted.items():
        path = prof.root / rec.get("file", "")
        if not path.is_file():
            findings.append(rules_mod.Finding("missing", sheet_name,
                                              f"{rec.get('file')} is gone"))
            continue
        pl = plan_subject(prof, subject, _groups_or_empty(prof))
        sh = next((x for x in pl.sheets if x.name == sheet_name), None)
        if sh is None:
            continue

        key = cut_mod.hex_to_rgb(backdrop_for(prof, subject))
        rgb = np.asarray(Image.open(path).convert("RGB"))
        alpha, rows = cut_mod.detect(rgb, key, expect=sh.cols,
                                     anchor=subject.raw.get("anchor", "centroid"))
        # Check the KEYED art, not the plate. Every anti-aliased edge on a raw
        # sheet is a blend of the drawing and the backdrop, so measuring the
        # plate says every outline is at risk -- including a navy one two
        # hundred units away from the key once the spill is pulled back.
        rgb = cut_mod.keyed(rgb, key)[..., :3]
        retired = set(subject.raw.get("retired") or [])

        if sh.wrapped:
            groups = {sh.anims[0]: [b for r in rows for b in r.boxes]}
            expected = {sh.anims[0]: sh.wrapped}
        elif sh.gallery:
            # One cell per entry, row-major -- the reading `pack` uses. Mapping
            # ROWS to names instead handed both cells of a two-across water
            # sheet to `water_surface` and never looked at `water_body` at all.
            cells = [b for r in rows for b in r.boxes]
            groups = {n: [b] for n, b in zip(sh.anims, cells)}
            expected = {a: 1 for a in sh.anims}
        else:
            groups = {sh.anims[i]: r.boxes for i, r in enumerate(rows)
                      if i < len(sh.anims)}
            expected = {a: sh.cols for a in sh.anims}

        # A violation someone accepted on purpose, with the reason written
        # down, should not fail the build every time afterwards. It is still
        # reported -- as a warning, so it stays visible.
        waived = set(rec.get("accepted_despite") or [])

        for anim, boxes in groups.items():
            if anim in retired or not boxes:
                continue
            checked += 1
            where = f"{name}/{anim}"
            # Per ANIM: a crouch is not held to the height she stands at.
            _, minimum = subject.min_size(prof.tile_px, anim)
            findings += rules_mod.undersized(
                boxes, subject.kind, minimum, prof.tile_px, where,
                square=bool(subject.raw.get("square", True)))
            findings += rules_mod.merged_frames(len(boxes), expected.get(anim), where)
            findings += rules_mod.baseline_spread(boxes, where)
            if subject.kind == "prop":
                # A prop is one drawing, not a cycle, so its single box IS its
                # shape -- and shape is the thing that drifted unnoticed.
                findings += rules_mod.prop_shape(
                    boxes[0],
                    prompt_mod.prop_size_px((subject.raw.get("anims") or {})
                                            .get(anim), subject, prof.tile_px),
                    where)
            for i, b in enumerate(boxes):
                sub_rgb = rgb[b.y:b.y + b.h, b.x:b.x + b.w]
                sub_a = alpha[b.y:b.y + b.h, b.x:b.x + b.w]
                findings += rules_mod.halo(sub_rgb, sub_a, key, f"{where}[{i}]")
                # A tile must NOT have an outline -- one becomes a grid line
                # ruled across the world every time it repeats -- so checking
                # for one is backwards.
                if subject.kind != "tile":
                    findings += rules_mod.outline(sub_rgb, sub_a, key, f"{where}[{i}]")
                if subject.kind == "tile":
                    findings += rules_mod.tile_margin(sub_a, f"{where}[{i}]")

        for f in findings:
            if f.fatal and f"{f.rule}: {f.detail}" in waived:
                f.fatal = False
    return findings, checked


@main.command()
@click.argument("names", nargs=-1)
@click.option("--all", "everything", is_flag=True, help="Every subject.")
@click.option("--seams", "seams_only", is_flag=True,
              help="Only the tiling check: does each seamless tile repeat without a line?")
@click.pass_context
def check(ctx, names, everything, seams_only) -> None:
    """Verify accepted art against every rule. Nonzero exit on a violation.

    Strict about `accepted` subjects and quiet about `legacy` ones, so a build
    can stay green through a migration that takes weeks. `audit` ignores that
    distinction and always reports the truth.
    """
    prof = _load(ctx.obj["project"])
    wanted = set(names)
    chosen = {n: s for n, s in prof.subjects.items()
              if everything or not wanted or n in wanted}

    if seams_only:
        _check_seams(ctx, prof, chosen)
        return

    all_findings, checked, subjects = [], 0, 0
    for name, subject in chosen.items():
        if subject.state != "accepted":
            continue
        subjects += 1
        found, n = _check_subject(prof, name, subject)
        all_findings += found
        checked += n

    if not subjects:
        console.print("[yellow]Nothing accepted to check.[/yellow] "
                      "[dim]`check` holds accepted art to the rules; "
                      "`audit` reports on everything.[/dim]")
        return

    fatal = [f for f in all_findings if f.fatal]
    if all_findings:
        table = Table(header_style="bold", title="Findings")
        table.add_column("rule"); table.add_column("where"); table.add_column("detail")
        for f in sorted(all_findings, key=lambda f: (not f.fatal, f.rule)):
            style = "red" if f.fatal else "yellow"
            table.add_row(f"[{style}]{f.rule}[/{style}]", f.where, f.detail)
        console.print(table)

    console.print(f"[dim]{subjects} accepted subject(s), {checked} animation(s) "
                  f"checked[/dim]")
    if fatal:
        console.print(f"[bold red]{len(fatal)} violation(s).[/bold red]")
        raise SystemExit(1)
    warn = len(all_findings)
    console.print("[green]clean[/green]" + (f" [dim]({warn} warning(s))[/dim]" if warn else ""))


def _check_seams(ctx, prof, chosen) -> None:
    """The tiling check, kept separate: it needs the packed atlas, not a sheet."""
    import numpy as np
    from PIL import Image

    atlas_json = _atlas_path(prof)
    groups = read_legacy(atlas_json)
    image_path = atlas_json.parent / (__import__("json").loads(
        atlas_json.read_text()).get("image") or "atlas.png")
    if not image_path.is_file():
        raise click.ClickException(f"Atlas image not found: {image_path}")
    px = np.asarray(Image.open(image_path).convert("RGBA"))

    failures, checked = 0, 0
    table = Table(title="Seams", header_style="bold")
    table.add_column("tile"); table.add_column("size", justify="right")
    table.add_column("margin", justify="right")
    table.add_column("h-wrap", justify="right"); table.add_column("v-wrap", justify="right")
    table.add_column("joint", justify="right")
    table.add_column("verdict")

    wanted = []
    for name, subject in chosen.items():
        if not subject.raw.get("seamless") or subject.state == "retired":
            continue
        source = subject.raw.get("source") or {}
        group = groups.get(source.get("group", name))
        if not group:
            continue
        entry = source.get("entry")
        if entry:
            keys = [entry] if entry in group.anims else []
        elif subject.sheets:
            # A grouped tile subject: every entry on its sheets tiles, so every
            # entry is checked, not whichever happened to be first.
            keys = [a for sh in subject.sheets.values()
                    for a in (sh.get("anims") if isinstance(sh, dict) else sh)
                    if a in group.anims]
        else:
            keys = [k for k in group.anims if k == name]
        wanted += [(k, subject, group) for k in keys]

    for name, subject, group in wanted:
        frame = group.anims[name].frames[0]
        crop = px[frame.y:frame.y + frame.h, frame.x:frame.x + frame.w]
        if crop.size == 0:
            continue
        checked += 1
        rgb, alpha = crop[..., :3], crop[..., 3]
        margin = seams_mod.transparent_margin(alpha)
        prefix = (subject.raw.get("source") or {}).get("prefix", "")
        short = name[len(prefix):] if prefix else name
        axes = seams_mod.axes_for(seams_mod.axis_for(
            subject.raw.get("seamless"), short))
        scores = {s.axis: s for s in seams_mod.score(rgb, alpha, axes)}

        # A tile that is STACKED on another has one more edge to get right, and
        # scoring it against itself never looks at that edge: both tiles pass
        # while the line between them is the one actually on screen.
        under = (subject.raw.get("joins") or {}).get(short)
        below = group.anims.get(f"{prefix}{under}") if under else None
        if below is not None and below.frames:
            b = below.frames[0]
            other = px[b.y:b.y + b.h, b.x:b.x + b.w]
            scores["joint"] = seams_mod.junction(crop[..., :3], other[..., :3])
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
            f"{scores['joint'].ratio:.1f}×" if "joint" in scores else "[dim]—[/dim]",
            ("[green]" if not bad else ("[bold red]" if strict else "[yellow]"))
            + worst.verdict() + ("[/green]" if not bad else ("[/bold red]" if strict else "[/yellow]")),
        )

    if not checked:
        console.print("[yellow]No subjects marked `seamless: true`.[/yellow]")
        return
    console.print(table)
    console.print("[dim]h-wrap/v-wrap: the step across the wrap over the tile's own "
                  "median step. ~1× reads as continuous; large is a line.\n"
                  "joint: the same step where this tile is stacked on the one it "
                  "`joins`.[/dim]")
    if failures:
        console.print(f"[bold red]{failures} accepted tile(s) failed.[/bold red]")
        raise SystemExit(1)


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
    # Including the flagged frames, because `draw` includes them. A preview
    # that leaves them out is not a preview: it says a note was not sent when
    # it was about to be, and the one thing this command promises is that what
    # it prints is what goes.
    flagged = _issue_note(subject, sh)
    if flagged:
        note = (note + " " if note else "") + flagged
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

def _candidate_rows(path, backdrop, names, expect, write_to, wrapped=0,
                    gallery=False):
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

    if gallery:
        # One cell per entry, row-major: the detector reads rows top to bottom
        # and cells left to right within a row, which is the order they were
        # asked for.
        boxes = [b for row in rows for b in row.boxes]
        for i, b in enumerate(boxes):
            if i < len(names):
                out[names[i]] = [b.as_list()]
        if len(boxes) != len(names):
            short.append(f"{len(boxes)} of {len(names)} entries")
        return out, short, extra

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
@click.option("--candidate", "candidates", multiple=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="A sheet to compare (repeatable). Defaults to the accepted "
                   "sheet if there is one, else the newest candidate.")
@click.option("--port", default=8731, show_default=True)
@click.option("--no-open", "no_open", is_flag=True, help="Serve, but do not open a browser.")
@click.pass_context
def view(ctx, subject, candidates, port, no_open) -> None:
    """Preview the animations in a browser, at real device sizes.

    Shows what ships today beside the candidate, both scaled the way the game
    scales them, so the comparison is the one the player would see.
    """
    import http.server, socketserver, threading, webbrowser
    import shutil as shutil_mod

    prof = _load(ctx.obj["project"])
    if subject not in prof.subjects:
        raise click.ClickException(f"Unknown subject: {subject}")
    sub = prof.subjects[subject]
    source = sub.raw.get("source") or {}
    prefix = source.get("prefix", "")

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

    # Every version to compare. A subject now has one sheet PER ANIMATION, so
    # each source carries its own layout -- taking the names from the first
    # sheet and applying them to all of them piled nine animations onto one row.
    plan_for = plan_subject(prof, sub, groups)
    by_name = {x.name: x for x in plan_for.sheets}

    sources: list[tuple[str, Path, object]] = []
    accepted = (sub.raw.get("accepted") or {})
    for sheet_name, rec in accepted.items():
        f = prof.root / rec.get("file", "")
        sh = by_name.get(sheet_name)
        if f.is_file() and sh is not None:
            sources.append((sheet_name, f, sh))
    for c in candidates:
        sh = by_name.get(c.stem.rsplit("-", 1)[0]) or next(iter(by_name.values()), None)
        if sh is not None:
            sources.append((c.stem, c, sh))
    if not sources:
        pool = sorted((prof.root / "art" / "candidates").glob(f"{subject}*.png"))
        if pool:
            sh = by_name.get(pool[-1].stem.rsplit("-", 1)[0]) or next(iter(by_name.values()), None)
            if sh is not None:
                sources.append((pool[-1].stem, pool[-1], sh))

    seen: set[Path] = set()
    for n, (label, path, sh) in enumerate(sources):
        if path.resolve() in seen:
            continue
        seen.add(path.resolve())
        served = f"version{n}.png"
        detected, short, extra = _candidate_rows(
            path, backdrop_for(prof, sub), sh.anims, sh.cols,
            serve / served, wrapped=sh.wrapped)
        if short:
            console.print(f"[yellow]{label}: incomplete rows[/yellow] " + ", ".join(short))
        ref = next(iter(detected.values()))[0][3] if detected else 1
        for name, frames in detected.items():
            per_row.setdefault(name, []).append(
                {"label": label, "image": served, "frames": frames, "ref_h": ref})

    if not per_row:
        raise click.ClickException("Nothing to preview: no atlas entry and no candidate.")
    rows = []

    # Rows with something to compare first, then in the order the profile
    # lists its animations, so the sheet order and the page order agree.
    authored = [a for sh in plan_for.sheets for a in sh.anims]

    def order(item):
        name = item[0]
        has_new = len(item[1]) > 1
        rank = authored.index(name) if name in authored else len(authored)
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
        # Normalise on the TALLEST frame, not the mean. A cycle's mean height
        # depends on how many stretched poses it happens to contain, so a
        # ten-frame version with more low frames would look smaller than a
        # six-frame one drawn at the same size. The tallest frame is the most
        # upright pose in the set, which is the closest thing to the idle frame
        # a game would really scale by.
        base = variants[0]
        base_top = max(f[3] for f in base["frames"])
        for v in variants[1:]:
            top = max(f[3] for f in v["frames"])
            if base_top > 0 and top > 0:
                v["ref_h"] = top * base["ref_h"] / base_top
        rows.append({"name": name, "frames": first["frames"],
                     "src_h": max(f[3] for f in first["frames"]),
                     "spread": max(f[4] for f in first["frames"]),
                     "variants": variants})

    try:
        normalised = fx_mod.normalise(sub.raw.get("effects") or {})
    except fx_mod.EffectError as exc:
        raise click.ClickException(f"art.yaml effects: {exc}") from exc

    # Hand edits already saved for this subject, so a reopened preview shows
    # the cleaned frames rather than the raw ones.
    edits_dir = prof.root / "art" / "edits" / subject
    edits = {}
    if edits_dir.is_dir():
        for f in sorted(edits_dir.glob("*.png")):
            shutil_mod.copy2(f, serve / f"edit-{f.name}")
            edits[f.stem] = f"edit-{f.name}"

    # The version a hand edit applies to: the last one added, which is the one
    # being worked on. Earlier versions are there to compare against.
    editable = sources[-1][0] if sources else ""

    data = {"devices": view_mod.device_list(),
            "subject": subject,
            "editable": editable,
            "nudges": (sub.raw.get("nudge") or {}),
            "anchorMode": sub.raw.get("anchor", "centroid"),
            "available": [
                {"file": str(f.relative_to(prof.root)), "label": f.stem}
                for f in sorted((prof.root / "art" / "candidates").glob(f"{subject}*.png"))
                + sorted((prof.root / "art" / "sheets").glob(f"{subject}*.png"))
            ],
            "sheet": (plan_for.sheets[0].name if plan_for.sheets else subject),
            "edits": edits,
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
            if self.path == "/unflag":
                self._unflag(); return
            if self.path == "/edit":
                self._save_edit(); return
            if self.path == "/compare":
                self._add_version(); return
            if self.path == "/nudge":
                self._save_nudge(); return
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

        def _unflag(self):
            try:
                body = self._body()
                anim, frame = str(body["anim"]), int(body["frame"])
            except Exception as exc:
                self.send_error(400, str(exc)); return
            kept = [i for i in (sub.raw.get("issues") or [])
                    if not (i.get("anim") == anim and i.get("frame") == frame)]
            sub.raw["issues"] = kept
            profile_mod.save(prof)
            console.print(f"[dim]unflagged {subject}/{anim} frame {frame}[/dim]")
            self.send_response(204); self.end_headers()

        def _save_edit(self):
            """Keep a frame someone cleaned up by hand.

            Regenerating a sheet to remove one stray stub costs an image and
            rerolls five frames that were already right. The edit is stored per
            frame, beside the candidate rather than inside it, so the generated
            sheet stays the untouched record of what came back.
            """
            import base64
            try:
                body = self._body()
                anim, frame = str(body["anim"]), int(body["frame"])
                raw = str(body["png"]).split(",", 1)[1]
                png = base64.b64decode(raw)
            except Exception as exc:
                self.send_error(400, f"bad edit: {exc}"); return
            if not png.startswith(b"\x89PNG"):
                self.send_error(400, "not a PNG"); return

            name = f"{anim}-{frame}.png"
            dest = prof.root / "art" / "edits" / subject / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(png)
            served = serve / f"edit-{name}"
            served.write_bytes(png)
            console.print(f"[green]edited[/green] {subject}/{anim} frame {frame} "
                          f"[dim]→ {dest.relative_to(prof.root)}[/dim]")
            payload = __import__("json").dumps({"url": f"edit-{name}"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers(); self.wfile.write(payload)

        def _save_nudge(self):
            """Shift one frame's registration point.

            Stored per frame in art.yaml and applied by `pack`, so the sheet
            itself is never rewritten -- the drawing is fine, it was hung a few
            pixels off.
            """
            try:
                body = self._body()
                anim, frame = str(body["anim"]), int(body["frame"])
                dx, dy = int(body.get("dx", 0)), int(body.get("dy", 0))
            except Exception as exc:
                self.send_error(400, str(exc)); return
            block = dict(sub.raw.get("nudge") or {})
            per = dict(block.get(anim) or {})
            if dx or dy:
                per[str(frame)] = [dx, dy]
            else:
                per.pop(str(frame), None)
            if per:
                block[anim] = per
            else:
                block.pop(anim, None)
            sub.raw["nudge"] = block
            profile_mod.save(prof)
            console.print(f"[dim]nudged {subject}/{anim} frame {frame} "
                          f"by {dx:+d},{dy:+d}[/dim]")
            self.send_response(204); self.end_headers()

        def _add_version(self):
            """Serve one more sheet to compare against, cut on demand.

            Comparison is open-ended on purpose: which two versions matter is
            not knowable when the page is built, and relaunching to see a third
            loses whatever was set up on the page.
            """
            try:
                body = self._body()
                rel = str(body["file"])
            except Exception as exc:
                self.send_error(400, str(exc)); return
            path = (prof.root / rel).resolve()
            if not path.is_file() or prof.root.resolve() not in path.parents:
                self.send_error(400, "not a file in this project"); return

            served = f"version-{abs(hash(rel)) % 10**8}.png"
            # Which sheet this file belongs to decides how it is cut. It used to
            # read a single set of names captured from the enclosing scope,
            # which stopped existing when a subject grew a sheet per animation.
            sh = by_name.get(path.stem.rsplit("-", 1)[0]) or by_name.get(path.stem)
            if sh is None:
                self.send_error(400, "no sheet in this project matches that file")
                return
            try:
                detected, short, _ = _candidate_rows(
                    path, backdrop_for(prof, sub), sh.anims, sh.cols,
                    serve / served, wrapped=sh.wrapped, gallery=sh.gallery)
            except Exception as exc:
                self.send_error(400, f"could not cut it: {exc}"); return
            ref = next((v[0][3] for k, v in detected.items() if k == "idle"),
                       next(iter(detected.values()))[0][3] if detected else 1)
            payload = __import__("json").dumps({
                "label": path.stem, "image": served, "ref_h": ref,
                "rows": detected, "short": short}).encode()
            console.print(f"[dim]comparing {rel}[/dim]")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers(); self.wfile.write(payload)

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


# ------------------------------------------------------------ template --

@main.command()
@click.argument("sheet")
@click.option("--anchor", default=0.5, show_default=True,
              help="Where in each cell the standing mark sits, 0..1 across.")
@click.pass_context
def template(ctx, sheet, anchor) -> None:
    """Draw a guide sheet for a generation to draw into.

    Cells, a groundline per cell, and a vertical mark showing where the
    character stands. The mark is the point of it: the horizontal standing
    position is the one thing `cut` cannot recover afterwards without guessing.
    """
    prof = _load(ctx.obj["project"])
    subject, sh, pl = _sheet_for(prof, sheet)
    out = prof.root / "art" / "templates" / f"{sh.name}.png"
    t = tpl_mod.build(out, prof.canvas, sh.cols, sh.rows,
                      cut_mod.hex_to_rgb(backdrop_for(prof, subject)), anchor)
    console.print(f"[green]wrote[/green] {out}  "
                  f"[dim]{t.cols}×{t.rows}, cells {t.cell_w}×{t.cell_h}, "
                  f"groundline at {int(t.baseline_y * 100)}% of each cell[/dim]")
    console.print("[dim]point the subject at it: "
                  f"reference: {{template: art/templates/{sh.name}.png}}[/dim]")


# -------------------------------------------------------------- accept --

@main.command()
@click.argument("sheet")
@click.argument("candidate", type=int, required=False)
@click.option("--note", default="", help="Why this one. Kept in art.yaml.")
@click.option("--force", is_flag=True,
              help="Accept despite violations. Recorded in art.yaml, so the "
                   "next person can see it was a decision.")
@click.pass_context
def accept(ctx, sheet, candidate, note, force) -> None:
    """Keep a candidate as the sheet for real.

    A generator produces variations and picking one is a judgement; this
    records it rather than makes it. The chosen file is COPIED to
    `art/sheets/<sheet>.png`, and every candidate stays where it is -- the
    point of accepting is to have something that cannot be lost by the next
    `art draw`.
    """
    import shutil

    prof = _load(ctx.obj["project"])
    subject, sh, pl = _sheet_for(prof, sheet)
    # Archived candidates count. A rejected sheet is often the best `pose`
    # reference for the next attempt, and re-accepting an earlier one after a
    # later attempt went wrong is exactly why they are kept.
    hunt = [prof.root / "art" / "candidates",
            prof.root / "art" / "archive" / "candidates"]
    pool = sorted((f for d in hunt if d.is_dir()
                   for f in d.glob(f"{sh.name}-*.png")),
                  key=lambda f: int(f.stem.rsplit("-", 1)[1]))
    if not pool:
        raise click.ClickException(f"No candidates for {sh.name}. Run `art draw {sh.name}`.")

    if candidate is None:
        chosen = pool[-1]
        candidate = int(chosen.stem.rsplit("-", 1)[1])
    else:
        chosen = next((f for f in pool
                       if int(f.stem.rsplit("-", 1)[1]) == candidate), None)
        if chosen is None:
            have = ", ".join(f.stem.rsplit("-", 1)[1] for f in pool)
            raise click.ClickException(
                f"No candidate {candidate} for {sh.name}. Have: {have}.")

    dest = prof.root / "art" / "sheets" / f"{sh.name}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(chosen, dest)

    # Check BEFORE recording it, so a sheet that breaks a rule cannot be
    # packed without someone having seen the reason. Everything found in this
    # project so far was found by a person squinting at a 1254px sheet, which
    # does not survive 68 subjects.
    accepted = dict(subject.raw.get("accepted") or {})
    accepted[sh.name] = {
        "candidate": candidate,
        "file": str(dest.relative_to(prof.root)),
        **({"note": note} if note else {}),
    }
    subject.raw["accepted"] = accepted
    was_state, subject.state = subject.state, "accepted"

    findings, _ = _check_subject(prof, subject.name, subject)
    fatal = [f for f in findings if f.fatal and f.where.startswith(f"{subject.name}/")]
    if fatal and not force:
        subject.raw["accepted"] = ({k: v for k, v in accepted.items()
                                    if k != sh.name} or None)
        if subject.raw["accepted"] is None:
            del subject.raw["accepted"]
        subject.state = was_state
        dest.unlink(missing_ok=True)
        for f in fatal:
            console.print(f"  [red]{f.rule}[/red] {f.where}: {f.detail}")
        raise click.ClickException(
            f"{len(fatal)} violation(s) — not accepted. Fix the sheet, or "
            "`--force` if it is the best that can be had.")
    if fatal:
        accepted[sh.name]["accepted_despite"] = [
            f"{f.rule}: {f.detail}" for f in fatal]
        console.print(f"[yellow]forced past {len(fatal)} violation(s)[/yellow]"
                      " [dim]— recorded in art.yaml[/dim]")
    profile_mod.save(prof)

    console.print(f"[green]accepted[/green] {sh.name} candidate {candidate} "
                  f"[dim]→ {dest.relative_to(prof.root)}[/dim]")
    console.print(f"[dim]{subject.name} is now state=accepted; "
                  f"`art check` holds it to the rules from here.[/dim]")


# ---------------------------------------------------------------- pack --

def _apply_joins(prof, healed: dict) -> list[str]:
    """Blend every declared join, and say what moved.

    `joins: {water_surface: water_body}` means the surface's bottom edge has to
    continue into the body's top. Two tiles can each wrap perfectly and still
    draw a line where one is stacked on the other, because making a tile
    seamless only ever made it agree with ITSELF.

    Runs after every tile has been healed, never during: a join to a tile whose
    own wrap has not been closed yet copies an edge that is about to change.
    """
    import numpy as np
    from PIL import Image as _Image

    out: list[str] = []
    for name, subject in prof.subjects.items():
        for anim, under in (subject.raw.get("joins") or {}).items():
            upper = healed.get((name, anim))
            lower = healed.get((name, under))
            if upper is None:
                continue
            if lower is None:
                raise click.ClickException(
                    f"{name}: `joins: {{{anim}: {under}}}` -- there is no "
                    f"accepted `{under}` to join to. A tile can only be joined "
                    f"to another tile of the same subject."
                )
            a = np.asarray(upper.images[0].convert("RGBA"))
            b = np.asarray(lower.images[0].convert("RGBA"))
            before, typical = seamless_mod.junction_step(a, b)
            joined = seamless_mod.join_below(a, b)
            after, _ = seamless_mod.junction_step(joined, b)
            upper.images[0] = _Image.fromarray(joined)
            ratio = lambda v: v / typical if typical > 1e-6 else 0.0
            out.append(f"[dim]join[/dim] {anim} on {under}: "
                       f"{ratio(before):.1f}\u00d7 \u2192 {ratio(after):.1f}\u00d7")
    return out


@main.command()
@click.option("--format", "fmt", type=click.Choice(["webp", "png"]),
              default="webp", show_default=True,
              help="WebP is 4-6x smaller than PNG for painterly art and the "
                   "game hands the file to drawImage, which does not care.")
@click.option("--quality", default=90, show_default=True, help="WebP quality.")
@click.option("--dry-run", is_flag=True, help="Report what would change; write nothing.")
@click.pass_context
def pack(ctx, fmt, quality, dry_run) -> None:
    """Merge every accepted sheet into the atlas the game loads.

    The existing atlas is kept whole and the new frames are appended below it,
    because a redraw happens one character at a time and most of the art is
    still the old art. Only the animations that were redrawn are repointed.
    """
    from PIL import Image

    prof = _load(ctx.obj["project"])
    atlas_json = _atlas_path(prof)
    atlas_png = atlas_json.parent / (__import__("json").loads(
        atlas_json.read_text()).get("image") or "atlas.png")
    existing = __import__("json").loads(atlas_json.read_text())

    # Cut every accepted sheet first, because the row a character's scale is
    # measured from now lives on its OWN sheet -- one animation per sheet is
    # what made the frames big enough. Looking for it inside the sheet being
    # processed finds nothing and silently falls back to the old height, which
    # scaled the frog's jump to a seventh of its size.
    cut_sheets = []
    for name, subject in prof.subjects.items():
        for sheet_name, rec in (subject.raw.get("accepted") or {}).items():
            sheet_file = prof.root / rec.get("file", "")
            if not sheet_file.is_file():
                console.print(f"[yellow]missing[/yellow] {rec.get('file')}"); continue
            pl = plan_subject(prof, subject, _groups_or_empty(prof))
            sh = next((x for x in pl.sheets if x.name == sheet_name), None)
            if sh is None:
                continue
            keyed, rows = pack_mod.cut_sheet(
                sheet_file, backdrop_for(prof, subject), sh.anims,
                sh.cols, sh.wrapped, gallery=sh.gallery)
            cut_sheets.append((name, subject, sh, keyed, rows))

    # What each row looked like BEFORE this tool first touched it, written by
    # the packer and never overwritten. Asking `existing` instead asks the
    # last pack's output, so every scale comes back 1.0 and the correction
    # does nothing -- see the note beside base_rows in pack.merge.
    def _original(group: str, key: str) -> list[list[int]]:
        return pack_mod.original_row(existing, group, key)

    # Each character's reference row, after redrawing. Every other row of that
    # subject is measured against it, and the game measures the character
    # against it too -- `1.15 / atlas.axi.idle[0][3]` -- which is why its own
    # multiplier is 1.0 and not something computed.
    #
    # Resolved across the SUBJECT, not within one sheet. Masie is drawn one
    # sheet per animation, so `rows` in the loop below never holds more than
    # the sheet's own row: looking for `idle` there found it only while
    # packing idle itself, and uniform scale silently did nothing.
    ref_boxes: dict[str, list] = {}
    for name, subject, sh, keyed, rows in cut_sheets:
        prefix = (subject.raw.get("source") or {}).get("prefix", "")
        ref_key = subject.raw.get("scale_ref") or f"{prefix}idle"
        short = ref_key[len(prefix):] if prefix else ref_key
        if short in rows and rows[short]:
            ref_boxes[name] = rows[short]

    replacements = []
    healed: dict[tuple[str, str], pack_mod.Replacement] = {}
    for name, subject, sh, keyed, rows in cut_sheets:
        source = subject.raw.get("source") or {}
        group, prefix = source.get("group", name), source.get("prefix", "")
        retired = set(subject.raw.get("retired") or [])
        ref_key = subject.raw.get("scale_ref") or f"{prefix}idle"
        ref_old = _original(group, ref_key)
        ref_new = ref_boxes.get(name) or []

        nudges = (subject.raw.get("nudge") or {})
        ref_short = ref_key[len(prefix):] if prefix else ref_key
        for anim, boxes in rows.items():
            if anim in retired:
                continue
            cut_mod.apply_nudges(boxes, nudges.get(anim) or {})
            atlas_key = f"{prefix}{anim}"
            old = _original(group, atlas_key)
            images = [keyed.crop((b.x, b.y, b.x + b.w, b.y + b.h)) for b in boxes]

            # A generator cannot draw a seamless tile from a description -- the
            # ground family came back at 13x, 10x and 6x the tile's own step
            # across the wrap. It is an image-processing problem, so it is done
            # here rather than asked for again.
            #
            # The axis is resolved per TILE, not per subject: one sheet can
            # carry a water surface that only repeats sideways and the water
            # under it, which is stacked as well.
            axis = seams_mod.axis_for(subject.raw.get("seamless"), anim)
            if axis and subject.kind == "tile" and subject.raw.get("fill") is not False:
                # A repeating tile is laid on a SQUARE grid cell, so a tile cut
                # 604x660 is stretched by different amounts on each axis and
                # its wrap no longer meets itself: AXI's pond drew a line down
                # every column boundary. Squared BEFORE the wrap is computed,
                # so the edges that are blended are the edges that will touch.
                from PIL import Image as _I
                side = max(im.width for im in images) if images else 0
                images = [im if im.size == (side, side)
                          else im.resize((side, side), _I.LANCZOS)
                          for im in images]
            if axis and subject.kind == "tile":
                import numpy as np
                from PIL import Image as _Image
                # A solid tile can blend across a third of itself and only get
                # softer. A STRIP cannot: blending a vine with a half-rolled
                # copy of itself paints a pale ghost vine through the gaps.
                # 0.35 ghosted 8.3% of the vine, 0.04 ghosts 1.6% and still
                # closes the wrap.
                feather = 0.04 if subject.raw.get("fill") is False else 0.35
                images = [_Image.fromarray(
                    seamless_mod.make_seamless(np.asarray(im.convert("RGBA")),
                                               axis if isinstance(axis, str) else "both",
                                               feather=feather))
                    for im in images]

            # The reference row is 1.0 by definition: the game sizes the
            # character BY that row, read out of this very atlas, so a
            # multiplier on it would correct a redraw that has already been
            # accounted for. It used to be computed like any other row and came
            # out at 0.85 for Masie -- who then drew 15% smaller than the 1.15
            # tiles the game asks for, in every state at once.
            #
            # Every other row keeps its size RELATIVE to that reference...
            if anim == ref_short:
                scale = 1.0
            elif subject.raw.get("uniform_scale") and ref_new:
                # ...unless the subject asks for uniform scale, in which case
                # it is pulled to the reference instead of to what it used to
                # be. AXI's original art had jump at 0.96x her idle and landing
                # at 0.90x, and preserving that faithfully preserved a
                # character who shrank every time she left the ground.
                scale = pack_mod.uniform_scale_for(boxes, ref_new, 1.0)
            else:
                scale = pack_mod.scale_for(boxes, old, ref_new, ref_old)
            # ...and a row may say no. Uniform scale reads a row's size from
            # the MIDDLE of its frames, which asks that most of them be near a
            # neutral pose. Sir Croaks' landing is half pancake, so the middle
            # measured the squash rather than the drawing and pulled the whole
            # row up 9% -- he swelled to 3.3 tiles every time he touched down.
            #
            # Measuring at the top of the frames instead fixes his landing and
            # breaks Masie: her jump row's tallest frame is a full stretch, so
            # matching tops shrinks everything around it, which is the "she
            # gets smaller when she jumps" bug this was built to remove. A row
            # of mostly-extreme poses cannot be told from a sheet drawn small
            # without knowing which pose is neutral, and nothing here knows
            # that. So it is said out loud, per row, and recorded.
            override = (subject.raw.get("scale_override") or {}).get(anim)
            if override is not None:
                scale = float(override)

            try:
                normalised = fx_mod.normalise(subject.raw.get("effects") or {})
            except fx_mod.EffectError as exc:
                raise click.ClickException(f"{name} effects: {exc}") from exc
            effects = fx_mod.for_anim(normalised, anim)
            meta = {k: v for k, v in (
                ("frames", len(boxes)),
                ("effects", {n: {k: v for k, v in vals.items() if k != "anchor"}
                             for n, vals in effects.items()} or None),
            ) if v}

            rep = pack_mod.Replacement(
                group=group, anim=atlas_key, frames=boxes, images=images,
                scale=scale, old_frames=len(old), meta=meta, ref=ref_key)
            replacements.append(rep)
            healed[(name, anim)] = rep

    # Joins, in a second pass: a tile that sits on another is blended toward
    # the HEALED copy of it, and the first pass is what heals it. Blending
    # toward the raw cut would copy an edge that is about to change.
    for line in _apply_joins(prof, healed):
        console.print(line)

    if not replacements:
        raise click.ClickException("Nothing accepted to pack. Run `art accept` first.")

    table = Table(header_style="bold", title="Into the atlas")
    table.add_column("row"); table.add_column("frames", justify="right")
    table.add_column("tallest", justify="right")
    table.add_column("scale", justify="right"); table.add_column("was", justify="right")
    for r in replacements:
        table.add_row(f"{r.group}/{r.anim}",
                      f"{r.old_frames} → {len(r.frames)}",
                      f"{max(b.h for b in r.frames)}px",
                      f"×{r.scale}", f"{r.old_frames} frames")
    console.print(table)
    console.print("[dim]scale cancels the new resolution, so each row lands at "
                  "the size it already had — sharper, not bigger.[/dim]")
    if dry_run:
        return

    out_img = atlas_png.with_suffix(f".{fmt}")
    before = atlas_png.stat().st_size
    result = pack_mod.merge(atlas_png, atlas_json, replacements,
                            out_img, atlas_json, quality=quality)
    after = out_img.stat().st_size
    console.print(f"[green]packed[/green] {result.image.name} "
                  f"[dim]{result.width}×{result.height}, "
                  f"+{result.added_px}px of new art[/dim]")
    console.print(f"[dim]{before / 1e6:.1f}MB → [/dim]"
                  f"[bold]{after / 1e6:.1f}MB[/bold]"
                  + (f" [dim]({before / after:.1f}× smaller)[/dim]"
                     if after < before else ""))
    if out_img.suffix != atlas_png.suffix and atlas_png.exists():
        console.print(f"[dim]{atlas_png.name} is now unused — "
                      f"atlas.json points at {out_img.name}.[/dim]")


# ----------------------------------------------------------------- cut --

@main.command()
@click.argument("sheet")
@click.option("--from", "source", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None, help="A sheet to cut. Defaults to the accepted one.")
@click.option("--out", "out_dir", type=click.Path(file_okay=False, path_type=Path),
              default=None, help="Where the frames go. Defaults to art/frames/<sheet>/.")
@click.pass_context
def cut(ctx, sheet, source, out_dir) -> None:
    """Key a sheet and write its frames out one file each.

    `view` and `pack` cut in memory; this is for looking at a frame, handing one
    to another tool, or checking what the detector actually found.
    """
    import numpy as np
    from PIL import Image

    prof = _load(ctx.obj["project"])
    subject, sh, pl = _sheet_for(prof, sheet)
    if source is None:
        rec = (subject.raw.get("accepted") or {}).get(sh.name) or {}
        source = prof.root / rec.get("file", "")
        if not source.is_file():
            raise click.ClickException(
                f"No accepted sheet for {sh.name}. Pass --from, or `art accept`.")

    key = cut_mod.hex_to_rgb(backdrop_for(prof, subject))
    rgb = np.asarray(Image.open(source).convert("RGB"))
    _, rows = cut_mod.detect(rgb, key, expect=sh.cols,
                             anchor=subject.raw.get("anchor", "centroid"))
    keyed = Image.fromarray(cut_mod.keyed(rgb, key))
    out_dir = out_dir or (prof.root / "art" / "frames" / sh.name)
    out_dir.mkdir(parents=True, exist_ok=True)

    boxes = [b for r in rows for b in r.boxes]
    if sh.wrapped:
        names = [sh.anims[0]] * len(boxes)
    elif sh.gallery:
        # One cell per entry, row-major -- the same reading `pack` uses. Naming
        # by ROW instead, which is right for a sheet of animations, called both
        # cells of a two-across water sheet `water_surface` and wrote the body
        # out over the surface.
        names = [sh.anims[i] if i < len(sh.anims) else f"cell{i + 1}"
                 for i in range(len(boxes))]
    else:
        names = [sh.anims[i] if i < len(sh.anims) else f"row{i + 1}"
                 for i, r in enumerate(rows) for _ in r.boxes]
    n = 0
    counts: dict[str, int] = {}
    for name, b in zip(names, boxes):
        i = counts.get(name, 0); counts[name] = i + 1
        keyed.crop((b.x, b.y, b.x + b.w, b.y + b.h)).save(out_dir / f"{name}-{i}.png")
        n += 1
    console.print(f"[green]cut[/green] {n} frames → {out_dir}"
                  f"  [dim]{', '.join(f'{k}×{v}' for k, v in counts.items())}[/dim]")


# ------------------------------------------------------------- runtime --

@main.command()
@click.option("--emit", "dest", type=click.Path(dir_okay=False, path_type=Path),
              default=None, help="Where to write it. Defaults to web/sprite.js.")
@click.pass_context
def runtime(ctx, dest) -> None:
    """Write the reader for the format this tool writes.

    Vended rather than published, so the generator and its reader cannot drift
    and each game keeps a copy it is free to edit.
    """
    import shutil
    from importlib.resources import files

    prof = _load(ctx.obj["project"])
    dest = dest or (prof.root / "web" / "sprite.js")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(files("art").joinpath("runtime.js")), dest)
    console.print(f"[green]wrote[/green] {dest.relative_to(prof.root)} "
                  f"[dim]{dest.stat().st_size // 1024}KB[/dim]")
    console.print("[dim]it applies scales, anchor, lift and effects — "
                  "the four things a naive reader gets wrong.[/dim]")


# --------------------------------------------------------------- review --

@main.command()
@click.argument("sheet")
@click.option("--from", "source", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None, help="A sheet to review. Defaults to the accepted one.")
@click.option("--flag", "do_flag", is_flag=True,
              help="Write the findings into art.yaml as frame flags, so they "
                   "become art direction on the next draw.")
@click.option("--model", "-m", default=None, help="The agent model to review with.")
@click.option("--dry-run", is_flag=True, help="Show the contact sheet and the prompt; ask nothing.")
@click.pass_context
def review(ctx, sheet, source, do_flag, model, dry_run) -> None:
    """Have a model look at the sheet and say what is wrong with it.

    `check` catches what a formula can. Every defect that actually cost a
    generation here was outside that set -- a stub at the tail root, a doubled
    tail, five legs, gills that drifted blue. Those are visual judgements, and
    a person made every one of them by squinting at a 1254px sheet.
    """
    import numpy as np
    from PIL import Image

    prof = _load(ctx.obj["project"])
    subject, sh, pl = _sheet_for(prof, sheet)
    if source is None:
        rec = (subject.raw.get("accepted") or {}).get(sh.name) or {}
        source = prof.root / rec.get("file", "")
        if not source.is_file():
            pool = sorted((prof.root / "art" / "candidates").glob(f"{sh.name}-*.png"))
            if not pool:
                raise click.ClickException(
                    f"Nothing to review for {sh.name}. `art draw` or `art accept` first.")
            source = pool[-1]

    key = cut_mod.hex_to_rgb(backdrop_for(prof, subject))
    rgb = np.asarray(Image.open(source).convert("RGB"))
    _, rows = cut_mod.detect(rgb, key, expect=sh.cols,
                             anchor=subject.raw.get("anchor", "centroid"))
    keyed = Image.fromarray(cut_mod.keyed(rgb, key))
    boxes = [b for r in rows for b in r.boxes]
    frames = [keyed.crop((b.x, b.y, b.x + b.w, b.y + b.h)) for b in boxes]
    anim = sh.anims[0] if sh.anims else sh.name

    contact = prof.root / "art" / "review" / f"{sh.name}.png"
    review_mod.contact_sheet(frames, contact)
    prompt = review_mod.build_prompt(
        subject.raw.get("description", ""), anim, len(frames))

    console.print(f"[dim]reviewing[/dim] [bold]{sh.name}[/bold] "
                  f"[dim]— {len(frames)} frames from {source.name}[/dim]")
    console.print(f"[dim]contact sheet: {contact.relative_to(prof.root)}[/dim]")
    if dry_run:
        click.echo(prompt)
        return

    try:
        notes = review_mod.ask(contact, prompt, model=model)
    except review_mod.ReviewError as exc:
        raise click.ClickException(str(exc)) from exc

    if not notes:
        console.print("[green]the model found nothing.[/green] "
                      "[dim]Worth a look anyway — it is a second opinion, "
                      "not a replacement for one.[/dim]")
        return

    table = Table(header_style="bold", title="What the model sees")
    table.add_column("frame", justify="right"); table.add_column("severity")
    table.add_column("issue")
    for n in sorted(notes, key=lambda n: (not n.high, n.frame if n.frame is not None else -1)):
        table.add_row("all" if n.frame is None else str(n.frame + 1),
                      f"[red]high[/red]" if n.high else "[yellow]low[/yellow]",
                      n.issue)
    console.print(table)

    if not do_flag:
        console.print("[dim]`--flag` writes these into art.yaml, so the next "
                      "`art draw` is told to fix them.[/dim]")
        return

    issues = list(subject.raw.get("issues") or [])
    added = 0
    for n in notes:
        if n.frame is None or not n.high:
            continue
        issues = [i for i in issues
                  if not (i.get("anim") == anim and i.get("frame") == n.frame)]
        issues.append({"anim": anim, "frame": n.frame, "note": n.issue})
        added += 1
    issues.sort(key=lambda i: (i["anim"], i["frame"]))
    subject.raw["issues"] = issues
    profile_mod.save(prof)
    console.print(f"[green]flagged {added} frame(s)[/green] "
                  f"[dim]— they ride into the next `art draw {sh.name}`[/dim]")


# ---------------------------------------------------------------- scene --

@main.command()
@click.option("--port", default=8733, show_default=True)
@click.option("--no-open", "no_open", is_flag=True, help="Serve, but do not open a browser.")
@click.pass_context
def scene(ctx, port, no_open) -> None:
    """Preview terrain, props and sky the way a landscape is seen.

    `view` is built for animation. None of the questions you ask about
    landscape art fit that shape: a tile's question is what happens when it
    REPEATS, a prop's is how big it is beside the character, and a band's is
    whether it seams across a whole screen. So this composes them instead, from
    the packed atlas -- what ships is what matters.
    """
    import http.server, socketserver, tempfile, threading, webbrowser
    import numpy as np
    from PIL import Image

    prof = _load(ctx.obj["project"])
    atlas_json = _atlas_path(prof)
    raw = __import__("json").loads(atlas_json.read_text())
    image = atlas_json.parent / (raw.get("image") or "atlas.png")
    if not image.is_file():
        raise click.ClickException(f"Atlas image not found: {image}. Run `art pack`.")
    px = np.asarray(Image.open(image).convert("RGBA"))
    entries = raw.get("tiles") or {}

    def rect(name):
        f = entries.get(name)
        return None if not f else {"x": f[0], "y": f[1], "w": f[2], "h": f[3]}

    tiles, props, bands = [], [], []
    for name, subject in prof.subjects.items():
        if subject.state == "retired":
            continue
        for sh in (subject.sheets or {}).values():
            keys = sh.get("anims") if isinstance(sh, dict) else sh
            for key in keys or []:
                r = rect(key)
                if not r:
                    continue
                # Size is per ENTRY, not per group: a group shares a material,
                # not a width. A tree is 3.6 tiles across and a gem is 0.6.
                note = (subject.raw.get("anims") or {}).get(key) or {}
                note = note if isinstance(note, dict) else {}
                tall = note.get("tiles_tall") or subject.raw.get("height_tiles_drawn")
                if tall:
                    # The game's own parallax numbers: the hill band drifts at
                    # 0.35 and never repeats vertically; a cloud layer drifts at
                    # 0.15 * mul, sits at 0.5 + 0.7 * mul tiles down, and is
                    # spaced 3.4 * mul of its own widths apart.
                    mul = {"cloud": 1.0, "cloud_face": 1.7}.get(key)
                    bands.append({
                        **r, "name": key, "tilesTall": tall,
                        "band": mul is not None, "mul": mul or 1.0,
                        "alpha": 0.95 if mul else 1.0,
                        "speed": 0.35 if mul is None else 0.15 * mul,
                    })
                elif subject.kind == "tile":
                    crop = px[r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]]
                    axis = seams_mod.axis_for(
                        subject.raw.get("seamless"), key) or "both"
                    got = seams_mod.score(crop[..., :3], crop[..., 3],
                                          seams_mod.axes_for(axis))
                    tiles.append({**r, "name": key, "seamless": str(axis),
                                  "seam": max(s.ratio for s in got)})
                else:
                    props.append({**r, "name": key,
                                  "tiles": float(note.get("width_tiles")
                                                 or subject.raw.get("width_tiles")
                                                 or 1.0)})

    if not (tiles or props or bands):
        raise click.ClickException(
            "No terrain in this project. `art pack` first, or check art.yaml.")

    hero = (raw.get("axi") or {}).get("idle")
    ground = rect("ground") or (tiles[0] if tiles else None)
    data = {
        "devices": view_mod.device_list(),
        "tiles": sorted(tiles, key=lambda t: t["name"]),
        "props": sorted(props, key=lambda p: -p["tiles"]),
        "bands": bands,
        "ground": ground,
        "hero": ({"x": hero[0][0], "y": hero[0][1], "w": hero[0][2], "h": hero[0][3]}
                 if hero else None),
    }

    serve = Path(tempfile.mkdtemp(prefix="art-scene-"))
    scene_mod.build(serve, "landscape",
                    f"{len(tiles)} tiles \u00b7 {len(props)} props \u00b7 "
                    f"{len(bands)} sky bands, from {image.name}", data, image)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k): super().__init__(*a, directory=str(serve), **k)
        def log_message(self, *a): pass

    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = socketserver.TCPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        raise click.ClickException(
            f"Port {port} is already in use. Try `--port {port + 1}`.") from exc
    with httpd:
        url = f"http://127.0.0.1:{port}/"
        console.print(f"[green]scene[/green] {url}  [dim]ctrl-c to stop[/dim]")
        if not no_open:
            threading.Timer(0.3, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            console.print("[dim]stopped[/dim]")
