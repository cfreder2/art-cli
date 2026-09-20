/* Sprite reader for an art-cli atlas. Emitted by `art runtime`, so it always
 * matches the format the packer writes -- there is no version to keep in step.
 *
 * The three things a trimmed, mixed-resolution atlas needs, which a naive
 * reader gets wrong:
 *
 *   scales   a row redrawn at higher resolution than the frame this character
 *            was measured by would draw that much bigger.
 *   anchor   frames of differing widths cannot be placed by centring their
 *            boxes; the sixth number is where the character stands.
 *   lift     how far a frame rides above its row's groundline, which is what
 *            gives a run its bounce after trimming.
 */
export class Sheet {
  static async load(url = 'atlas.json') {
    const data = await fetch(url).then(r => r.json());
    const base = url.replace(/[^/]*$/, '');
    const img = await new Promise((res, rej) => {
      const i = new Image();
      i.onload = () => res(i);
      i.onerror = () => rej(new Error('atlas image: ' + data.image));
      i.src = base + (data.image || 'atlas.png');
    });
    return new Sheet(data, img);
  }

  constructor(data, img) { this.d = data; this.img = img; }

  row(group, name) { return (this.d[group] || {})[name] || []; }

  /** How many source pixels are one tile, for this group. */
  unit(group, refRow, tiles) {
    const f = this.row(group, refRow)[0];
    return f ? f[3] / tiles : 1;
  }

  actor(group, opts = {}) { return new Actor(this, group, opts); }
}

export class Actor {
  constructor(sheet, group, { ref = 'idle', tiles = 1, effects = {} } = {}) {
    this.s = sheet; this.g = group; this.tiles = tiles;
    this.base = tiles / (sheet.row(group, ref)[0]?.[3] || 1);
    this.effects = effects;
    this.anim = null; this.t = 0; this.frame = 0; this.fps = 12; this.loop = true;
  }

  /** The file carries defaults; the call site wins. */
  play(name, { fps, loop, restart = false } = {}) {
    if (this.anim !== name || restart) { this.anim = name; this.t = 0; this.frame = 0; }
    const meta = (this.s.d.anims || {})[this.g + '/' + name] || {};
    this.fps = fps ?? meta.fps ?? this.fps;
    this.loop = loop ?? meta.loop ?? true;
    return this;
  }

  advance(dt) {
    const n = this.s.row(this.g, this.anim).length;
    if (!n) return this;
    this.t += dt * this.fps;
    this.frame = this.loop ? Math.floor(this.t) % n
                           : Math.min(n - 1, Math.floor(this.t));
    return this;
  }

  draw(ctx, x, y, { tile, flip = 1, now = 0, flat = false } = {}) {
    const list = this.s.row(this.g, this.anim);
    if (!list.length) return false;
    const f = list[Math.min(this.frame, list.length - 1)];
    const mul = (this.s.d.scales || {})[this.g + '/' + this.anim] || 1;
    const scale = this.base * mul * tile;
    const w = f[2] * scale, h = f[3] * scale;
    const lift = flat ? 0 : (f[4] || 0) * scale;
    const anchor = (f.length > 5 ? f[5] : f[2] / 2) * scale;

    const fx = (this.effects[this.anim] || this.effects.default || {});
    let sy = 1, rot = 0, bob = 0, alpha = 1;
    const wave = e => Math.sin(2 * Math.PI * e.hz * now / 1000 + (e.phase || 0));
    if (fx.breathe) sy = 1 + fx.breathe.amount * wave(fx.breathe);
    if (fx.sway)    rot = (fx.sway.degrees * Math.PI / 180) * wave(fx.sway);
    if (fx.bob)     bob = fx.bob.amount * tile * wave(fx.bob);
    if (fx.throb)   alpha = 1 - fx.throb.amount * (0.5 + 0.5 * wave(fx.throb));

    ctx.save();
    ctx.translate(x, y - bob);
    if (flip < 0) ctx.scale(-1, 1);
    // Anchored at the feet: scale swells upward and rotation pivots where the
    // character meets the ground, so neither lifts it off.
    ctx.rotate(rot); ctx.scale(sy, sy);
    ctx.globalAlpha = alpha;
    ctx.drawImage(this.s.img, f[0], f[1], f[2], f[3], -anchor, -h - lift, w, h);
    ctx.restore();
    return true;
  }
}
