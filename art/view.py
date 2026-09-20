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
  .strip { display:flex; gap:10px; align-items:center; margin-top:12px;
    padding-top:12px; border-top:1px solid var(--line); flex-wrap:wrap; }
  .strip input[type=range] { width:180px; }
  .n { font-variant-numeric:tabular-nums; font-size:13px; min-width:74px; }
  .step { padding:3px 9px; font-size:14px; line-height:1.2; }
  .flagbox { display:flex; gap:6px; align-items:center; flex:1 1 260px; }
  .flagbox input[type=text] { flex:1; min-width:120px; font:inherit; font-size:13px;
    padding:5px 9px; border-radius:7px; border:1px solid var(--line);
    background:var(--bg); color:var(--fg); }
  .issues { margin-top:10px; display:flex; flex-direction:column; gap:4px; }
  .issue { font-size:12px; color:var(--dim); display:flex; gap:8px; }
  .issue b { color:var(--accent); font-weight:600; font-variant-numeric:tabular-nums; }
  .flagged { outline:2px solid var(--accent); outline-offset:3px; border-radius:4px; }
  .edited { outline:2px solid var(--good); outline-offset:3px; border-radius:4px; }
  canvas { cursor:zoom-in; }
  .issue button { font-size:11px; padding:1px 7px; border-radius:6px; }
  .hint { color:var(--dim); font-size:11px; margin-top:6px; }
  .ovl { position:fixed; inset:0; background:rgba(8,8,12,.86); z-index:50;
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    gap:12px; padding:20px; }
  .ovl .sheetwrap { background:
      conic-gradient(#d8d8d8 0 25%, #fff 0 50%, #d8d8d8 0 75%, #fff 0) 0 0/24px 24px;
    border-radius:8px; box-shadow:0 10px 40px rgba(0,0,0,.5); overflow:auto;
    max-width:94vw; max-height:70vh; }
  .ovl canvas { cursor:crosshair; display:block; }
  .ovlbar { display:flex; gap:12px; align-items:center; flex-wrap:wrap;
    background:var(--card); border:1px solid var(--line); border-radius:10px;
    padding:10px 14px; }
  .ovlbar .t { color:var(--fg); font-size:13px; }
  .fx { margin-top:10px; padding-top:10px; border-top:1px dashed var(--line);
    display:flex; flex-direction:column; gap:8px; }
  .fxrow { display:flex; gap:10px; align-items:center; flex-wrap:wrap;
    font-size:13px; }
  .fxname { font-weight:600; min-width:70px; }
  .fxp { display:flex; gap:6px; align-items:center; color:var(--dim); font-size:12px; }
  .fxp input[type=range] { width:108px; }
  .fxv { font-variant-numeric:tabular-nums; min-width:56px; }
  select { font:inherit; font-size:13px; padding:4px 8px; border-radius:7px;
    border:1px solid var(--line); background:var(--card); color:var(--fg); }
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
    <select id="addver"></select>
    <button id="sync" aria-pressed="true" title="Every version completes its loop in the same time, whatever its frame count">Sync speed</button>
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
let fps = 8, showBase = false, showGrid = false, playing = true, syncSpeed = true;

const images = {};
function load(src){ return new Promise(r => { const i = new Image();
  i.onload = () => r(i); i.src = src; }); }

const devs = document.getElementById('devs');
DATA.devices.forEach(d => {
  const b = document.createElement('button');
  b.textContent = d.name + ' · ' + d.px;
  b.onclick = () => { device = d; syncDeviceButtons(); };
  b.dataset.px = d.px; devs.appendChild(b);
});
function syncDeviceButtons(){ [...devs.children].forEach(b =>
  b.setAttribute('aria-pressed', String(+b.dataset.px === device.px))); }
syncDeviceButtons();

document.getElementById('fps').oninput = e => {
  fps = +e.target.value; document.getElementById('fpsv').textContent = fps + ' fps'; };
const toggle = (id, set) => { const b = document.getElementById(id);
  b.onclick = () => { const v = b.getAttribute('aria-pressed') !== 'true';
    b.setAttribute('aria-pressed', String(v)); set(v); }; };
toggle('sync', v => syncSpeed = v);
toggle('base', v => showBase = v);
toggle('grid', v => showGrid = v);
document.getElementById('play').onclick = () => { playing = !playing;
  const b = document.getElementById('play');
  b.setAttribute('aria-pressed', String(playing));
  b.textContent = playing ? 'Pause' : 'Play'; };

// Add another version to compare, without relaunching. Which two versions
// matter is not knowable when the page is built.
const addver = document.getElementById('addver');
function fillAdd(){
  const shown = new Set(DATA.rows.flatMap(r => r.variants.map(v => v.label)));
  addver.innerHTML = '<option value="">compare another version…</option>' +
    DATA.available.filter(a => !shown.has(a.label))
      .map(a => `<option value="${a.file}">${a.label}</option>`).join('');
}
addver.onchange = async () => {
  if (!addver.value) return;
  const file = addver.value; addver.disabled = true;
  try {
    const r = await fetch('/compare', { method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({ file }) });
    if (!r.ok) throw new Error(await r.text());
    const v = await r.json();
    images[v.image] = await load(v.image);
    for (const row of DATA.rows) {
      const frames = v.rows[row.name];
      if (!frames) continue;
      const base = row.variants[0];
      const bm = base.frames.reduce((a,f)=>a+f[3],0)/base.frames.length;
      const m = frames.reduce((a,f)=>a+f[3],0)/frames.length;
      row.variants.push({ label: v.label, image: v.image, frames,
                          ref_h: (bm>0&&m>0) ? m*base.ref_h/bm : v.ref_h });
      addCell(row);
    }
    fillAdd();
  } catch (e) { alert('Could not add: ' + e.message); }
  addver.disabled = false; addver.value = '';
};

const host = document.getElementById('rows');
const players = [];

function addCell(row){
  const v = row.variants[row.variants.length - 1];
  const cell = document.createElement('div'); cell.className = 'cell';
  const c = document.createElement('canvas'); cell.appendChild(c);
  const cap = document.createElement('div'); cap.className = 'cap'; cell.appendChild(cap);
  c.title = 'Click to clean this frame up by hand';
  c.onclick = () => openEditor(row, v);
  row.stage.appendChild(cell);
  players.push({ canvas:c, cap, variant:v, row });
  // A longer version makes the scrub finer, so its frames are all reachable.
  const n = Math.max(...row.variants.map(x => x.frames.length));
  if (n !== row.ui.n) {
    row.ui.n = n; row.ui.scrub.max = n - 1;
    row.ui.scrub.value = Math.floor(row.ui.phase * n);
  }
  const head = row.el.querySelector('.rowhead .meta');
  if (head) head.textContent = row.variants.map(x =>
    `${x.label} ${x.frames.length}f @${Math.round(x.ref_h)}px`).join(' · ');
}

for (const row of DATA.rows) {
  const el = document.createElement('div'); el.className = 'row';
  const head = document.createElement('div'); head.className = 'rowhead';
  head.innerHTML = `<span class="name">${row.name}</span>
    <span class="meta">${row.variants.map(v =>
      `${v.label} ${v.frames.length}f @${v.ref_h}px`).join(' · ')}
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
    c.title = 'Click to clean this frame up by hand';
    c.onclick = () => openEditor(row, v);
    players.push({ canvas:c, cap, variant:v, row });
  }
  row.stage = stage; row.el = el;
  el.appendChild(stage);

  // Per-row transport. Rows have different frame counts, so stepping is per
  // row rather than global -- "frame 3" only means something inside one row.
  // Versions of the same action can have different frame counts -- six drawn
  // frames and ten drawn frames are the same run. So the transport is the
  // cycle's PHASE, and each version maps that phase onto its own frames.
  // Indexing every version by the first one's frame count is why a ten-frame
  // cycle only ever showed its first six.
  const n = Math.max(...row.variants.map(v => v.frames.length));
  const strip = document.createElement('div'); strip.className = 'strip';
  strip.innerHTML = `
    <button class="step" title="Previous frame (\u2190)">&#9664;</button>
    <input type="range" min="0" max="${n - 1}" value="0">
    <button class="step" title="Next frame (\u2192)">&#9654;</button>
    <span class="n"></span>
    <span class="flagbox">
      <input type="text" placeholder="What is wrong with this frame?">
      <button>Flag</button>
    </span>`;
  const [prev, scrub, next, label] = [
    strip.children[0], strip.children[1], strip.children[2], strip.children[3]];
  const note = strip.querySelector('input[type=text]');
  const flag = strip.querySelector('.flagbox button');

  row.ui = { scrub, label, n, phase: 0, manual: false };
  scrub.oninput = () => { row.ui.manual = true; setPlaying(false);
    row.ui.phase = (+scrub.value) / row.ui.n; };
  prev.onclick = () => stepRow(row, -1);
  next.onclick = () => stepRow(row, +1);
  flag.onclick = async () => {
    // A flag names a frame of the version being worked on, since that is the
    // one the next generation will be told to fix.
    const target = row.variants.find(v => v.label === DATA.editable)
                   || row.variants[row.variants.length - 1];
    const frame = Math.min(target.frames.length - 1,
                           Math.floor(row.ui.phase * target.frames.length));
    const body = { subject: DATA.subject, anim: row.name,
                   frame, note: note.value.trim() };
    flag.disabled = true;
    try {
      const r = await fetch('/flag', { method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
      if (!r.ok) throw new Error(await r.text());
      note.value = ''; DATA.issues.push(body); renderIssues(row, el);
    } catch (e) { alert('Could not save the flag: ' + e.message); }
    flag.disabled = false;
  };

  el.appendChild(strip);
  renderIssues(row, el);
  row.fx = JSON.parse(JSON.stringify(DATA.effects[row.name] || {}));
  renderEffects(row, el);
  host.appendChild(el);
}

function renderEffects(row, el){
  let box = el.querySelector('.fx');
  if (!box) { box = document.createElement('div'); box.className = 'fx';
    el.appendChild(box); }
  box.innerHTML = '';

  for (const [name, values] of Object.entries(row.fx)) {
    const def = DATA.catalogue.find(c => c.name === name); if (!def) continue;
    const line = document.createElement('div'); line.className = 'fxrow';
    line.innerHTML = `<span class="fxname" title="${def.help}">${name}</span>`;
    for (const pd of def.params) {
      const wrap = document.createElement('span'); wrap.className = 'fxp';
      const step = (pd.high - pd.low) / 200;
      wrap.innerHTML = `<label>${pd.name}</label>`;
      const r = document.createElement('input');
      r.type = 'range'; r.min = pd.low; r.max = pd.high; r.step = step;
      r.value = values[pd.name];
      const out = document.createElement('span'); out.className = 'fxv';
      const show = () => out.textContent =
        (+r.value).toFixed(pd.high <= 1 ? 3 : 2) + pd.unit;
      r.oninput = () => { values[pd.name] = +r.value; show(); };
      show(); wrap.appendChild(r); wrap.appendChild(out); line.appendChild(wrap);
    }
    const drop = document.createElement('button');
    drop.textContent = 'Remove'; drop.className = 'step';
    drop.onclick = () => { delete row.fx[name]; renderEffects(row, el); };
    line.appendChild(drop);
    box.appendChild(line);
  }

  const add = document.createElement('div'); add.className = 'fxrow';
  const sel = document.createElement('select');
  sel.innerHTML = '<option value="">add an effect…</option>' +
    DATA.catalogue.filter(c => !row.fx[c.name])
      .map(c => `<option value="${c.name}" title="${c.help}">${c.name}</option>`).join('');
  sel.onchange = () => {
    if (!sel.value) return;
    const def = DATA.catalogue.find(c => c.name === sel.value);
    row.fx[def.name] = Object.fromEntries(
      def.params.map(p => [p.name, p.default]).concat([['phase', 'none']]));
    renderEffects(row, el);
  };
  const save = document.createElement('button');
  save.textContent = 'Save to art.yaml';
  save.onclick = async () => {
    save.disabled = true;
    try {
      const r = await fetch('/effects', { method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ anim: row.name, effects: row.fx }) });
      if (!r.ok) throw new Error(await r.text());
      save.textContent = 'Saved';
      setTimeout(() => save.textContent = 'Save to art.yaml', 1200);
    } catch (e) { alert('Could not save: ' + e.message); }
    save.disabled = false;
  };
  add.appendChild(sel); add.appendChild(save);
  box.appendChild(add);
}

function renderIssues(row, el) {
  let box = el.querySelector('.issues');
  if (!box) { box = document.createElement('div'); box.className = 'issues';
    el.appendChild(box); }
  const mine = DATA.issues.filter(i => i.anim === row.name);
  box.innerHTML = '';
  for (const i of mine) {
    const line = document.createElement('div'); line.className = 'issue';
    const b = document.createElement('b'); b.textContent = 'frame ' + i.frame;
    const t = document.createElement('span'); t.textContent = i.note || '(no note)';
    const rm = document.createElement('button'); rm.textContent = 'remove';
    rm.onclick = async () => {
      rm.disabled = true;
      try {
        const r = await fetch('/unflag', { method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ anim: row.name, frame: i.frame }) });
        if (!r.ok) throw new Error(await r.text());
        DATA.issues = DATA.issues.filter(
          x => !(x.anim === i.anim && x.frame === i.frame));
        renderIssues(row, el);
      } catch (e) { alert('Could not remove: ' + e.message); rm.disabled = false; }
    };
    line.appendChild(b); line.appendChild(t); line.appendChild(rm);
    box.appendChild(line);
  }
  if (mine.length) {
    const hint = document.createElement('div'); hint.className = 'hint';
    hint.textContent = mine.length + ' flag(s) on this row will be sent to the '
      + 'generator as art direction on the next `art draw ' + DATA.sheet + '`.';
    box.appendChild(hint);
  }
}

// --------------------------------------------------------------- editor --
// Regenerating a sheet to remove one stray stub costs an image and rerolls
// five frames that were already right. Erasing it by hand costs a few seconds
// and touches nothing else, so the frame is editable where it is looked at.

function openEditor(row, variant){
  // The frame index is per version: phase 40% is frame 4 of ten and frame 3
  // of six.
  const idx = Math.min(variant.frames.length - 1,
                       Math.floor(row.ui.phase * variant.frames.length));
  const f = variant.frames[idx];
  const src = images[variant.image];
  if (!src) return;
  setPlaying(false);

  const ovl = document.createElement('div'); ovl.className = 'ovl';
  const wrap = document.createElement('div'); wrap.className = 'sheetwrap';
  const cv = document.createElement('canvas');
  cv.width = f[2]; cv.height = f[3];
  const g = cv.getContext('2d', { willReadFrequently: true });
  // Start from whatever is currently shown for this frame: a previous edit if
  // there is one, otherwise the region of the sheet.
  const prior = DATA.edits[row.name + '-' + idx];
  const start = () => {
    g.clearRect(0, 0, cv.width, cv.height);
    if (prior && images[prior]) g.drawImage(images[prior], 0, 0);
    else g.drawImage(src, f[0], f[1], f[2], f[3], 0, 0, f[2], f[3]);
  };
  start();

  // Fit to the screen but never below 1:1 detail -- the point is high
  // resolution, so it scrolls rather than shrinking past readable.
  const fit = Math.min((window.innerWidth * 0.9) / cv.width,
                       (window.innerHeight * 0.62) / cv.height, 2);
  cv.style.width = Math.round(cv.width * Math.max(fit, 0.5)) + 'px';
  cv.style.height = Math.round(cv.height * Math.max(fit, 0.5)) + 'px';
  wrap.appendChild(cv);

  const undo = [];
  const push = () => { undo.push(g.getImageData(0, 0, cv.width, cv.height));
    if (undo.length > 24) undo.shift(); };

  let size = Math.max(8, Math.round(cv.width / 26)), erasing = false;
  const at = (e) => {
    const r = cv.getBoundingClientRect();
    return [(e.clientX - r.left) * cv.width / r.width,
            (e.clientY - r.top) * cv.height / r.height];
  };
  const dab = (x, y) => {
    g.save(); g.globalCompositeOperation = 'destination-out';
    g.beginPath(); g.arc(x, y, size / 2, 0, Math.PI * 2); g.fill(); g.restore();
  };
  cv.onpointerdown = (e) => { push(); erasing = true; cv.setPointerCapture(e.pointerId);
    dab(...at(e)); };
  cv.onpointermove = (e) => { if (erasing) dab(...at(e)); };
  cv.onpointerup = () => erasing = false;

  const bar = document.createElement('div'); bar.className = 'ovlbar';
  bar.innerHTML = `<span class="t"><b>${row.name}</b> frame ${idx}
    · ${f[2]}×${f[3]}px · erase to clean up</span>`;
  const mk = (label, fn) => { const b = document.createElement('button');
    b.textContent = label; b.onclick = fn; bar.appendChild(b); return b; };
  const sz = document.createElement('input');
  sz.type = 'range'; sz.min = 4; sz.max = Math.round(cv.width / 5); sz.value = size;
  sz.oninput = () => size = +sz.value;
  bar.appendChild(sz);
  mk('Undo', () => { const d = undo.pop(); if (d) g.putImageData(d, 0, 0); });
  mk('Reset', () => { push(); start(); });
  mk('Cancel', () => ovl.remove());
  const save = mk('Save frame', async () => {
    save.disabled = true;
    try {
      const r = await fetch('/edit', { method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ anim: row.name, frame: idx,
                               png: cv.toDataURL('image/png') }) });
      if (!r.ok) throw new Error(await r.text());
      const { url } = await r.json();
      const img = new Image();
      img.onload = () => { images[url] = img;
        DATA.edits[row.name + '-' + idx] = url; ovl.remove(); };
      img.src = url + '?t=' + Date.now();
    } catch (e) { alert('Could not save: ' + e.message); save.disabled = false; }
  });
  save.setAttribute('aria-pressed', 'true');

  ovl.appendChild(wrap); ovl.appendChild(bar);
  ovl.onclick = (e) => { if (e.target === ovl) ovl.remove(); };
  addEventListener('keydown', function esc(e){
    if (e.key === 'Escape') { ovl.remove(); removeEventListener('keydown', esc); } });
  document.body.appendChild(ovl);
}

function stepRow(row, d){
  setPlaying(false); row.ui.manual = true;
  const n = row.ui.n;
  const at = ((Math.round(row.ui.phase * n) + d) % n + n) % n;
  row.ui.phase = at / n;
  row.ui.scrub.value = at;
}

function setPlaying(v){
  playing = v; const b = document.getElementById('play');
  b.setAttribute('aria-pressed', String(playing));
  b.textContent = playing ? 'Pause' : 'Play';
}

addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT') return;
  if (e.key === 'ArrowLeft')  { DATA.rows.forEach(r => stepRow(r, -1)); e.preventDefault(); }
  if (e.key === 'ArrowRight') { DATA.rows.forEach(r => stepRow(r, +1)); e.preventDefault(); }
  if (e.key === ' ') { setPlaying(!playing); e.preventDefault(); }
});

fillAdd();
(async () => {
  for (const p of players)
    if (!images[p.variant.image]) images[p.variant.image] = await load(p.variant.image);
  for (const url of Object.values(DATA.edits))
    if (!images[url]) images[url] = await load(url);
  requestAnimationFrame(tick);
})();

let t0 = performance.now(), acc = 0;
function tick(now){
  const dt = now - t0; t0 = now;
  if (playing) {
    for (const r of DATA.rows) {
      if (!r.ui) continue;
      // Sync: every version finishes its loop in the time the FIRST version
      // takes at this fps, so the same action is compared at the same speed
      // however many frames it is drawn in. Off: each version advances a frame
      // per tick, which is what a game with a fixed fps would do.
      const base = r.variants[0].frames.length;
      const cyclesPerSec = fps / (syncSpeed ? base : r.ui.n);
      r.ui.phase = (r.ui.phase + (dt / 1000) * cyclesPerSec) % 1;
      r.ui.scrub.value = Math.floor(r.ui.phase * r.ui.n);
    }
  }
  for (const p of players) draw(p);
  for (const r of DATA.rows) if (r.ui)
    r.ui.label.textContent = `${(r.ui.phase * 100).toFixed(0)}% of cycle`;
  requestAnimationFrame(tick);
}

function draw(p){
  const img = images[p.variant.image]; if (!img) return;
  const c = p.canvas, g = c.getContext('2d');
  const v = p.variant, frames = v.frames;
  if (!frames.length) return;
  // Phase -> this version's own frame. A ten-frame cycle at 40% is on its
  // fourth frame; a six-frame cycle at 40% is on its third.
  const phase = p.row.ui ? p.row.ui.phase : 0;
  const idx = Math.min(frames.length - 1, Math.floor(phase * frames.length));
  const f = frames[idx];
  const flagged = DATA.issues.some(i => i.anim === p.row.name && i.frame === idx);
  c.classList.toggle('flagged', flagged && v.label === DATA.editable);
  // Exactly what the game does: one scale for the whole set, derived from the
  // reference frame, with lift applied per frame.
  const scale = (DATA.height_tiles * device.px) / v.ref_h;
  const w = f[2] * scale, h = f[3] * scale, lift = f[4] * scale;
  // Place by the frame's ANCHOR -- the middle of its footprint -- not by the
  // middle of its bounding box. A tail streaming out behind lengthens the box
  // without moving the character, and centring the box would swing her body
  // back and forth. Legacy frames carry no anchor, so they fall back to the
  // centring the old atlas assumed.
  const anchorOf = (fr) => (fr.length > 5 ? fr[5] : fr[2] / 2) * scale;
  const a = anchorOf(f);
  // Wide enough for the whole cycle, so the canvas itself does not shift.
  let left = 0, right = 0;
  for (const fr of frames) {
    left = Math.max(left, anchorOf(fr));
    right = Math.max(right, fr[2] * scale - anchorOf(fr));
  }
  const boxH = DATA.height_tiles * device.px * 1.7;
  const cw = Math.max(90, Math.ceil(left + right) + 24), ch = Math.ceil(boxH) + 16;
  if (c.width !== cw || c.height !== ch) { c.width = cw; c.height = ch;
    c.style.width = cw + 'px'; c.style.height = ch + 'px'; }
  g.clearRect(0, 0, cw, ch);
  const baseY = ch - 10;
  const fx = p.row.fx || {};
  const T = performance.now() / 1000;
  // Phase keeps identical props out of lockstep; in the preview the two
  // variants share a phase so they can be compared honestly.
  const wave = (e) => Math.sin(2 * Math.PI * e.hz * T + (e.phaseOffset || 0));
  let sScale = 1, rot = 0, bobPx = 0, alpha = 1;
  if (fx.breathe) sScale = 1 + fx.breathe.amount * wave(fx.breathe);
  if (fx.sway)    rot = (fx.sway.degrees * Math.PI / 180) * wave(fx.sway);
  if (fx.bob)     bobPx = fx.bob.amount * device.px * wave(fx.bob);
  if (fx.throb)   alpha = 1 - fx.throb.amount * (0.5 + 0.5 * wave(fx.throb));
  if (showBase) { g.strokeStyle = 'rgba(184,51,106,.55)'; g.lineWidth = 1;
    g.beginPath(); g.moveTo(0, baseY + .5); g.lineTo(cw, baseY + .5); g.stroke();
    // The anchor line: her x position. If the body drifts off it, the sprite
    // will slide in the game.
    g.strokeStyle = 'rgba(80,140,220,.6)';
    g.beginPath(); g.moveTo(left + 12.5, 0); g.lineTo(left + 12.5, ch); g.stroke(); }
  const x = left + 12 - a, y = baseY - h - lift;
  g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
  g.save();
  // Anchored at the feet: scale swells the sprite upward and rotation pivots
  // where it meets the ground, so neither lifts it off.
  const pivot = left + 12;
  g.translate(pivot, baseY - bobPx);
  g.rotate(rot); g.scale(sScale, sScale);
  g.translate(-pivot, -(baseY - bobPx));
  g.globalAlpha = alpha;
  const editUrl = v.label === DATA.editable ? DATA.edits[p.row.name + '-' + idx] : null;
  const edited = editUrl && images[editUrl];
  if (edited) g.drawImage(edited, 0, 0, f[2], f[3], x, y - bobPx, w, h);
  else g.drawImage(img, f[0], f[1], f[2], f[3], x, y - bobPx, w, h);
  g.restore();
  c.classList.toggle('edited', !!edited);
  if (showGrid) { g.strokeStyle = 'rgba(128,128,128,.5)';
    g.setLineDash([3,3]); g.strokeRect(x, y, w, h); g.setLineDash([]); }
  const up = (DATA.height_tiles * device.px) / v.ref_h;
  p.cap.innerHTML = `${v.label} · frame ${idx + 1}/${frames.length} · `
    + `<span class="${up > 1.05 ? 'bad' : 'good'}">${up.toFixed(1)}×</span>`;
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
