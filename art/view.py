"""The browser preview.

A terminal cannot answer the question this tool exists to answer. "Is this
pixelated?" is only answerable at a real device size, with the frames actually
moving, so the preview serves a page and the page draws to a canvas exactly the
way the game does: scale derived from one reference frame, `lift` applied per
frame, nearest-neighbour off.

The resolution picker is not a zoom slider. It is the device table the spec is
built on, so the number on screen is the number `audit` reports.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from art.spec import DEVICES

PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg:#f6f5f3; --fg:#1b1a19; --dim:#6d6a66; --line:#dbd7d2;
    --card:#fff; --accent:#b8336a; --good:#2f7d4f; --bad:#c0392b;
  }
  :root:not([data-theme="light"]) { @media (prefers-color-scheme: dark) {
    --bg:#16151a; --fg:#eceaf0; --dim:#9a96a3; --line:#312e39;
    --card:#1e1d24; --accent:#ff7ab6; --good:#5fd08a; --bad:#ff7a6b;
  }}
  :root[data-theme="dark"] {
    --bg:#16151a; --fg:#eceaf0; --dim:#9a96a3; --line:#312e39;
    --card:#1e1d24; --accent:#ff7ab6; --good:#5fd08a; --bad:#ff7a6b;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
    font:15px/1.5 ui-sans-serif,-apple-system,"Segoe UI",sans-serif; }
  .wrap { max-width:1100px; margin:0 auto; padding:24px 16px 64px; }
  h1 { font-size:22px; margin:0 0 2px; letter-spacing:-.01em; }
  .sub { color:var(--dim); font-size:13px; margin-bottom:20px; }
  .bar { position:sticky; top:0; z-index:5; background:var(--bg);
    border-bottom:1px solid var(--line); padding:12px 0; margin-bottom:20px;
    display:flex; flex-wrap:wrap; gap:16px; align-items:center; }
  .group { display:flex; gap:6px; align-items:center; flex-wrap:wrap; }
  label { font-size:12px; color:var(--dim); text-transform:uppercase;
    letter-spacing:.06em; }
  button { font:inherit; font-size:13px; padding:5px 11px; border-radius:7px;
    border:1px solid var(--line); background:var(--card); color:var(--fg);
    cursor:pointer; }
  button[aria-pressed="true"] { background:var(--accent); border-color:var(--accent);
    color:#fff; }
  input[type=range] { width:130px; accent-color:var(--accent); }
  .row { background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:16px; margin-bottom:14px; }
  .rowhead { display:flex; justify-content:space-between; align-items:baseline;
    gap:12px; margin-bottom:12px; flex-wrap:wrap; }
  .name { font-weight:600; }
  .meta { color:var(--dim); font-size:12px; font-variant-numeric:tabular-nums; }
  .stage { display:flex; gap:28px; align-items:flex-end; overflow-x:auto;
    padding-bottom:6px; }
  .cell { text-align:center; flex:0 0 auto; }
  .cap { color:var(--dim); font-size:11px; margin-top:6px;
    font-variant-numeric:tabular-nums; }
  canvas { display:block; image-rendering:auto; }
  .good { color:var(--good); } .bad { color:var(--bad); }
  @media (max-width:640px){ .wrap{padding-left:16px;padding-right:16px;} }
</style></head><body><div class="wrap">
<h1>__TITLE__</h1>
<div class="sub">__SUB__</div>

<div class="bar">
  <div class="group"><label>Device</label><span id="devs"></span></div>
  <div class="group"><label>Speed</label>
    <input id="fps" type="range" min="1" max="24" value="8">
    <span class="meta" id="fpsv">8 fps</span></div>
  <div class="group">
    <button id="base" aria-pressed="false">Baseline</button>
    <button id="grid" aria-pressed="false">Frame box</button>
    <button id="play" aria-pressed="true">Pause</button>
  </div>
</div>
<div id="rows"></div>
</div>
<script>
const DATA = __DATA__;
let device = DATA.devices.find(d => d.px === 192) || DATA.devices[0];
let fps = 8, showBase = false, showGrid = false, playing = true;

const images = {};
function load(src){ return new Promise(r => { const i = new Image();
  i.onload = () => r(i); i.src = src; }); }

const devs = document.getElementById('devs');
DATA.devices.forEach(d => {
  const b = document.createElement('button');
  b.textContent = d.name + ' · ' + d.px;
  b.onclick = () => { device = d; sync(); };
  b.dataset.px = d.px; devs.appendChild(b);
});
function sync(){ [...devs.children].forEach(b =>
  b.setAttribute('aria-pressed', String(+b.dataset.px === device.px))); }
sync();

document.getElementById('fps').oninput = e => {
  fps = +e.target.value; document.getElementById('fpsv').textContent = fps + ' fps'; };
const toggle = (id, set) => { const b = document.getElementById(id);
  b.onclick = () => { const v = b.getAttribute('aria-pressed') !== 'true';
    b.setAttribute('aria-pressed', String(v)); set(v); }; };
toggle('base', v => showBase = v);
toggle('grid', v => showGrid = v);
document.getElementById('play').onclick = () => { playing = !playing;
  const b = document.getElementById('play');
  b.setAttribute('aria-pressed', String(playing));
  b.textContent = playing ? 'Pause' : 'Play'; };

const host = document.getElementById('rows');
const players = [];

for (const row of DATA.rows) {
  const el = document.createElement('div'); el.className = 'row';
  const head = document.createElement('div'); head.className = 'rowhead';
  head.innerHTML = `<span class="name">${row.name}</span>
    <span class="meta">${row.frames.length} frames · source ${row.src_h}px tall
    · baseline spread ${row.spread}px</span>`;
  el.appendChild(head);
  const stage = document.createElement('div'); stage.className = 'stage';
  for (const v of row.variants) {
    const cell = document.createElement('div'); cell.className = 'cell';
    const c = document.createElement('canvas');
    cell.appendChild(c);
    const cap = document.createElement('div'); cap.className = 'cap';
    cell.appendChild(cap);
    stage.appendChild(cell);
    players.push({ canvas:c, cap, variant:v, row });
  }
  el.appendChild(stage); host.appendChild(el);
}

(async () => {
  for (const p of players)
    if (!images[p.variant.image]) images[p.variant.image] = await load(p.variant.image);
  requestAnimationFrame(tick);
})();

let t0 = performance.now(), frame = 0, acc = 0;
function tick(now){
  const dt = now - t0; t0 = now;
  if (playing) { acc += dt; while (acc > 1000 / fps) { acc -= 1000 / fps; frame++; } }
  for (const p of players) draw(p);
  requestAnimationFrame(tick);
}

function draw(p){
  const img = images[p.variant.image]; if (!img) return;
  const c = p.canvas, g = c.getContext('2d');
  const v = p.variant, frames = v.frames;
  if (!frames.length) return;
  const f = frames[frame % frames.length];
  // Exactly what the game does: one scale for the whole set, derived from the
  // reference frame, with lift applied per frame.
  const scale = (DATA.height_tiles * device.px) / v.ref_h;
  const w = f[2] * scale, h = f[3] * scale, lift = f[4] * scale;
  const boxH = DATA.height_tiles * device.px * 1.7;
  const cw = Math.max(90, Math.ceil(w) + 24), ch = Math.ceil(boxH) + 16;
  if (c.width !== cw || c.height !== ch) { c.width = cw; c.height = ch;
    c.style.width = cw + 'px'; c.style.height = ch + 'px'; }
  g.clearRect(0, 0, cw, ch);
  const baseY = ch - 10;
  if (showBase) { g.strokeStyle = 'rgba(184,51,106,.55)'; g.lineWidth = 1;
    g.beginPath(); g.moveTo(0, baseY + .5); g.lineTo(cw, baseY + .5); g.stroke(); }
  const x = (cw - w) / 2, y = baseY - h - lift;
  g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
  g.drawImage(img, f[0], f[1], f[2], f[3], x, y, w, h);
  if (showGrid) { g.strokeStyle = 'rgba(128,128,128,.5)';
    g.setLineDash([3,3]); g.strokeRect(x, y, w, h); g.setLineDash([]); }
  const up = (DATA.height_tiles * device.px) / v.ref_h;
  p.cap.innerHTML = `${v.label} · <span class="${up > 1.05 ? 'bad' : 'good'}">`
    + `${up.toFixed(1)}×</span>`;
}
</script></body></html>
"""


def build(out_dir: Path, title: str, subtitle: str, data: dict,
          images: dict[str, Path]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, src in images.items():
        shutil.copy2(src, out_dir / name)
    page = (PAGE.replace("__TITLE__", title)
                .replace("__SUB__", subtitle)
                .replace("__DATA__", json.dumps(data)))
    index = out_dir / "index.html"
    index.write_text(page)
    return index


def device_list() -> list[dict]:
    return [{"name": d.name.split("/")[0], "px": d.px_per_tile} for d in DEVICES]
