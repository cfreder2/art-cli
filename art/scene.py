"""Previewing landscape art the way a landscape is actually seen.

`view` is built for animation: rows of frames playing at device sizes. None of
the questions you ask about terrain fit that shape.

  A tile   -- has one frame, and the question is what happens when it REPEATS.
              A seam is invisible in a single tile and obvious in a field.
  A prop   -- has one frame, and the question is how big it is standing next to
              the character, at its real width in tiles.
  A band   -- repeats across a whole screen width at a parallax depth, and its
              seam shows once per screen rather than once per tile.

So this composes them instead: a field for each tile, a scene strip with the
horizon behind and props standing on real ground, and the character in it for
scale. It reads the PACKED atlas rather than the sheets, because what ships is
what matters and the packer is where tiles are made seamless.
"""

from __future__ import annotations

import json
from pathlib import Path

PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --bg:#f6f5f3; --fg:#1b1a19; --dim:#6d6a66; --line:#dbd7d2;
          --card:#fff; --accent:#b8336a; --good:#2f7d4f; --bad:#c0392b; }
  :root:not([data-theme="light"]) { @media (prefers-color-scheme: dark) {
    --bg:#16151a; --fg:#eceaf0; --dim:#9a96a3; --line:#312e39;
    --card:#1e1d24; --accent:#ff7ab6; --good:#5fd08a; --bad:#ff7a6b; } }
  :root[data-theme="dark"] { --bg:#16151a; --fg:#eceaf0; --dim:#9a96a3;
    --line:#312e39; --card:#1e1d24; --accent:#ff7ab6; --good:#5fd08a; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
    font:15px/1.5 ui-sans-serif,-apple-system,"Segoe UI",sans-serif; }
  .wrap { max-width:1200px; margin:0 auto; padding:24px 16px 64px; }
  h1 { font-size:22px; margin:0 0 2px; letter-spacing:-.01em; }
  h2 { font-size:15px; margin:28px 0 10px; letter-spacing:.01em; }
  .sub { color:var(--dim); font-size:13px; margin-bottom:18px; }
  .bar { position:sticky; top:0; z-index:5; background:var(--bg);
    border-bottom:1px solid var(--line); padding:12px 0; margin-bottom:8px;
    display:flex; flex-wrap:wrap; gap:14px; align-items:center; }
  label { font-size:12px; color:var(--dim); text-transform:uppercase;
    letter-spacing:.06em; }
  button { font:inherit; font-size:13px; padding:5px 11px; border-radius:7px;
    border:1px solid var(--line); background:var(--card); color:var(--fg);
    cursor:pointer; }
  button[aria-pressed="true"] { background:var(--accent);
    border-color:var(--accent); color:#fff; }
  .card { background:var(--card); border:1px solid var(--line);
    border-radius:12px; padding:14px; margin-bottom:14px; overflow:auto; }
  .head { display:flex; justify-content:space-between; align-items:baseline;
    gap:12px; margin-bottom:10px; flex-wrap:wrap; }
  .name { font-weight:600; }
  .meta { color:var(--dim); font-size:12px; font-variant-numeric:tabular-nums; }
  .good { color:var(--good); } .bad { color:var(--bad); }
  canvas { display:block; border-radius:6px; }
  .grid { display:flex; flex-wrap:wrap; gap:14px; }
  .cell { text-align:center; }
  .cap { color:var(--dim); font-size:11px; margin-top:5px; }
  @media (max-width:640px){ .wrap{padding-left:16px;padding-right:16px;} }
</style></head><body><div class="wrap">
<h1>__TITLE__</h1><div class="sub">__SUB__</div>
<div class="bar">
  <div><label>Device</label> <span id="devs"></span></div>
  <button id="edges" aria-pressed="false">Tile edges</button>
  <button id="motion" aria-pressed="true">Parallax</button>
</div>
<div id="out"></div>
</div>
<script>
const DATA = __DATA__;
let device = DATA.devices.find(d => d.px === 192) || DATA.devices[0];
let showEdges = false, moving = true;
const img = new Image();

const devs = document.getElementById('devs');
DATA.devices.forEach(d => {
  const b = document.createElement('button');
  b.textContent = d.name + ' \\u00b7 ' + d.px; b.dataset.px = d.px;
  b.onclick = () => { device = d; syncDevs(); rebuild(); };
  devs.appendChild(b);
});
function syncDevs(){ [...devs.children].forEach(b =>
  b.setAttribute('aria-pressed', String(+b.dataset.px === device.px))); }
const toggle = (id, set) => { const b = document.getElementById(id);
  b.onclick = () => { const v = b.getAttribute('aria-pressed') !== 'true';
    b.setAttribute('aria-pressed', String(v)); set(v); }; };
toggle('edges', v => showEdges = v);
toggle('motion', v => moving = v);
syncDevs();

/* Canvas defaults to 'low' smoothing, which is a cheap filter that aliases
   hard below about half scale. Masie is drawn at 0.38 of her source here and
   the props at 0.45-0.50, so she alone came out soft -- the art was fine and
   the preview was not. */
function crisp(g) { g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high'; }

const out = document.getElementById('out');
const painters = [];

function card(title, meta) {
  const c = document.createElement('div'); c.className = 'card';
  const h = document.createElement('div'); h.className = 'head';
  h.innerHTML = `<span class="name">${title}</span><span class="meta">${meta||''}</span>`;
  c.appendChild(h); out.appendChild(c); return c;
}

/* A tile's real question: what does a FIELD of it look like? */
function tileField(t) {
  const c = card(t.name, `${t.w}\\u00d7${t.h} source \\u00b7 wraps ${t.seamless}`
    + ` \\u00b7 <span class="${t.seam > 2 ? 'bad' : 'good'}">${t.seam.toFixed(1)}\\u00d7 at the wrap</span>`);
  const cv = document.createElement('canvas'); c.appendChild(cv);
  painters.push(() => {
    const ts = device.px, cols = Math.min(8, Math.ceil(760 / ts)), rows = 3;
    cv.width = cols * ts; cv.height = rows * ts;
    cv.style.width = cv.width + 'px'; cv.style.height = cv.height + 'px';
    const g = cv.getContext('2d');
    crisp(g);
    g.clearRect(0, 0, cv.width, cv.height);
    for (let y = 0; y < rows; y++)
      for (let x = 0; x < cols; x++)
        g.drawImage(img, t.x, t.y, t.w, t.h, x * ts, y * ts, ts + 1, ts + 1);
    if (showEdges) {
      g.strokeStyle = 'rgba(184,51,106,.75)'; g.lineWidth = 1;
      for (let x = 1; x < cols; x++) {
        g.beginPath(); g.moveTo(x * ts + .5, 0); g.lineTo(x * ts + .5, cv.height); g.stroke(); }
      for (let y = 1; y < rows; y++) {
        g.beginPath(); g.moveTo(0, y * ts + .5); g.lineTo(cv.width, y * ts + .5); g.stroke(); }
    }
  });
}

/* A prop's real question: how big is it next to her? */
function propRow(props) {
  const c = card('Props, on the ground, at their real width in tiles',
                 'the pale shape is Masie at 1.15 tiles, for scale');
  const cv = document.createElement('canvas'); c.appendChild(cv);
  painters.push(() => {
    const ts = device.px;
    const tall = Math.max(...props.map(p => p.tiles * (p.h / p.w))) ;
    cv.height = Math.ceil((tall + 1.6) * ts);
    let total = 1.4;
    for (const p of props) total += p.tiles + 0.35;
    cv.width = Math.ceil(total * ts);
    cv.style.width = cv.width + 'px'; cv.style.height = cv.height + 'px';
    const g = cv.getContext('2d');
    crisp(g);
    g.clearRect(0, 0, cv.width, cv.height);
    const base = cv.height - ts * 0.6;
    if (DATA.ground) {
      const t = DATA.ground;
      for (let x = 0; x < cv.width; x += ts)
        g.drawImage(img, t.x, t.y, t.w, t.h, x, base, ts + 1, ts + 1);
    }
    let x = 0.5 * ts;
    if (DATA.hero) {
      const hh = 1.15 * ts, hw = hh * (DATA.hero.w / DATA.hero.h);
      g.globalAlpha = .55;
      g.drawImage(img, DATA.hero.x, DATA.hero.y, DATA.hero.w, DATA.hero.h,
                  x, base - hh, hw, hh);
      g.globalAlpha = 1; x += hw + 0.35 * ts;
    }
    for (const p of props) {
      const w = p.tiles * ts, h = w * (p.h / p.w);
      g.drawImage(img, p.x, p.y, p.w, p.h, x, base - h, w, h);
      x += w + 0.35 * ts;
    }
  });
}

/* A band's real question: does it seam across a whole screen? */
function skyBand(bands) {
  const c = card('Sky and horizon', 'each band repeated across a screen width');
  const cv = document.createElement('canvas'); c.appendChild(cv);
  let t0 = performance.now(), drift = 0;
  painters.push(() => {
    const ts = device.px;
    cv.width = Math.min(1100, 14 * ts); cv.height = Math.ceil(5 * ts);
    cv.style.width = cv.width + 'px'; cv.style.height = cv.height + 'px';
  });
  const paint = (now) => {
    const ts = device.px, g = cv.getContext('2d');
    crisp(g);
    if (moving) drift += (now - t0) * 0.012; t0 = now;
    g.clearRect(0, 0, cv.width, cv.height);
    g.fillStyle = '#cfe9f5'; g.fillRect(0, 0, cv.width, cv.height);
    for (const b of bands) {
      const h = b.tilesTall * ts, w = h * (b.w / b.h);
      const off = -((drift * b.speed) % w);
      const y = b.name === 'hill' ? cv.height - h : cv.height * 0.08;
      for (let i = -1; off + i * w < cv.width + w; i++)
        g.drawImage(img, b.x, b.y, b.w, b.h, off + i * w, y, w, h);
    }
    requestAnimationFrame(paint);
  };
  requestAnimationFrame(paint);
}

function rebuild(){ for (const p of painters) p(); }

img.onload = () => {
  if (DATA.bands.length) skyBand(DATA.bands);
  if (DATA.props.length) propRow(DATA.props);
  if (DATA.tiles.length) {
    const h = document.createElement('h2');
    h.textContent = 'Tiles, repeated \\u2014 turn on "Tile edges" to see where they meet';
    out.appendChild(h);
    DATA.tiles.forEach(tileField);
  }
  rebuild();
};
img.src = DATA.image;
</script></body></html>
"""


def build(out_dir: Path, title: str, subtitle: str, data: dict,
          image: Path) -> Path:
    import shutil

    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(image, out_dir / image.name)
    data = {**data, "image": image.name}
    page = (PAGE.replace("__TITLE__", title).replace("__SUB__", subtitle)
                .replace("__DATA__", json.dumps(data)))
    index = out_dir / "index.html"
    index.write_text(page)
    return index
