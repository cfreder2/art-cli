/* Sprite reader for an art-cli atlas. Emitted by `art runtime`, so it always
 * matches the format the packer writes -- there is no version to keep in step.
 *
 * Two layers, and the seam between them is state:
 *
 *   Sheet.drawFrame()  stateless. The caller owns the frame index and the
 *                      clock. This is the ONLY place the atlas format is
 *                      decoded, and a game with its own entity system should
 *                      use it directly.
 *   Actor              a clock on top, for the one-actor case -- a menu
 *                      preview, a simple game. It calls drawFrame.
 *
 * That split is not decoration. AXI drives dozens of enemies from their own
 * timers, could not use a reader that owned the clock, and so reimplemented
 * the frame math instead. The copy drifted: it flipped before rotating, which
 * reversed a sway whenever a sprite faced left, and nothing caught it because
 * nothing ran it. Take the layer you need; never rewrite this one.
 *
 * The four things a trimmed, mixed-resolution atlas needs, which a naive
 * reader gets wrong:
 *
 *   scales   a row redrawn at higher resolution than the frame this character
 *            was measured by would draw that much bigger.
 *   anchor   frames of differing widths cannot be placed by centring their
 *            boxes; the sixth number is where the character stands.
 *   lift     how far a frame rides above its row's groundline, which is what
 *            gives a run its bounce after trimming.
 *   effects  metadata the packer carries, so a breathing idle costs a line of
 *            YAML instead of six drawn frames.
 */

/** `phase` NAMES how an offset is chosen -- 'none', 'x', 'random' -- so it is
 *  a string as often as a number. `e.phase || 0` let 'none' through, and
 *  `2 * Math.PI * hz * t + 'none'` is string concatenation: the whole wave
 *  became NaN and the effect vanished with no error. Numbers only. */
const phaseOf = e => (typeof e.phase === 'number' ? e.phase : 0);

/** Resolve one animation's effects into the transform they imply.
 *  `now` is milliseconds, passed in rather than read from performance.now(),
 *  so a caller can drive it and a test can freeze it. */
function effectsAt(fx, now, tile) {
  let pulse = 1, tilt = 0, rise = 0, fade = 1;
  if (fx) {
    const t = now / 1000;
    const wave = e => Math.sin(2 * Math.PI * e.hz * t + phaseOf(e));
    if (fx.breathe) pulse = 1 + fx.breathe.amount * wave(fx.breathe);
    if (fx.sway)    tilt  = (fx.sway.degrees * Math.PI / 180) * wave(fx.sway);
    if (fx.bob)     rise  = fx.bob.amount * tile * wave(fx.bob);
    if (fx.throb)   fade  = 1 - fx.throb.amount * (0.5 + 0.5 * wave(fx.throb));
  }
  return { pulse, tilt, rise, fade };
}

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

  /** A terrain entry: ONE frame written flat, not a list of them. */
  tile(name) { return (this.d.tiles || {})[name]; }

  /** The packer's metadata for a row -- fps, loop, effects. */
  meta(group, name) { return (this.d.anims || {})[group + '/' + name] || {}; }

  /** How many source pixels are one tile, for this group. */
  unit(group, refRow, tiles) {
    const f = this.row(group, refRow)[0];
    return f ? f[3] / tiles : 1;
  }

  actor(group, opts = {}) { return new Actor(this, group, opts); }

  /** How far frame `index` reaches to the LEFT and RIGHT of where the
   *  character stands, in the same units as `scale * tile`.
   *
   * A trimmed frame is not centred on its character -- f[5] is where they
   * stand within it -- so half its width is not how far it sticks out either
   * way. AXI needs the two apart: Masie's collision box is 0.72 tiles wide and
   * her swim pose is 2.07, nearly a tile of it in front of her, so swimming up
   * to a wall drew her head inside it.
   *
   * In WORLD directions, not "ahead" and "behind". The art is drawn facing one
   * way and mirrored for the other, so the character's front is always
   * `w - anchor` from where they stand -- what the flip changes is which side
   * of the world that lands on. Naming the sides after the character invites
   * the caller to work that out, and working it out backwards is exactly the
   * bug that reversed every sway on a left-facing sprite.
   */
  extent(group, name, index, { scale = 1, tile = 1, flip = 1 } = {}) {
    const list = this.row(group, name);
    if (!list.length) return null;
    const f = list[Math.min(index, list.length - 1)];
    const s = scale * ((this.d.scales || {})[group + '/' + name] || 1) * tile;
    const back = (f.length > 5 ? f[5] : f[2] / 2) * s;   // behind them, as drawn
    const front = f[2] * s - back;                        // and in front of them
    return flip < 0 ? { left: front, right: back } : { left: back, right: front };
  }


  /**
   * Draw frame `index` of one row, standing at (x, y).
   *
   * (x, y) is the GROUNDLINE, not a corner: effects pivot and swell from
   * there, so a breath lifts the top of the sprite and leaves the feet planted.
   *
   * `scale` is tiles per source pixel (what the game measured this character
   * at) and `tile` is pixels per tile; their product converts the frame's
   * stored box to screen pixels.
   *
   * `flat` means "this pose is not part of the cycle it was measured in", and
   * it refuses BOTH the lift and the effects. A squashed enemy is the case: it
   * borrows the last frame of the walk row, and that frame's lift is the bob
   * of a bug mid-stride. A corpse does not bob, and it does not breathe.
   *
   * `effects` overrides the packer's metadata for callers that carry their own.
   */
  drawFrame(ctx, group, name, index, {
    x = 0, y = 0, tile = 1, scale = 1, flip = 1, now = 0,
    flat = false, effects = null,
  } = {}) {
    const list = this.row(group, name);
    if (!list.length) return false;
    const f = list[Math.min(index, list.length - 1)];

    // A row redrawn at a higher resolution than the frame this character's
    // scale came from would draw that much bigger. `scales` carries the
    // correction per row, so a sharper row lands at the size it always had.
    // A row with no entry -- which is most of them -- is unchanged.
    const mul = (this.d.scales || {})[group + '/' + name] || 1;
    // Folded into `scale` and multiplied by `tile` at each use, rather than
    // pre-multiplied once. Same value in exact arithmetic; not the same in
    // floating point, and this is the association the game already shipped.
    scale *= mul;
    const w = f[2] * scale * tile, h = f[3] * scale * tile;
    const lift = flat ? 0 : (f[4] || 0) * scale * tile;
    // f[5] is where the character stands within the frame. Centring the box
    // instead is only right while every frame is the same width: Masie's run
    // varies by 10% as her tail swings, and centring it would slide her along
    // the ground. Frames without it are older ones, drawn to be centred.
    const anchor = (f.length > 5 ? f[5] : f[2] / 2) * scale * tile;

    const fx = flat ? null
      : (effects || this.meta(group, name).effects || null);
    const { pulse, tilt, rise, fade } = effectsAt(fx, now, tile);

    ctx.save();
    ctx.translate(x, y - rise);
    // The flip goes LAST. Flipping first puts the rotation inside the mirror,
    // which negates it -- and a sway is wind. Wind does not change direction
    // because the character turned around, but facing left it leaned the head
    // the opposite way from facing right.
    if (tilt) ctx.rotate(tilt);
    if (pulse !== 1) ctx.scale(pulse, pulse);
    if (fade !== 1) ctx.globalAlpha = fade;
    if (flip < 0) ctx.scale(-1, 1);
    ctx.drawImage(this.img, f[0], f[1], f[2], f[3], -anchor, -h - lift, w, h);
    ctx.restore();
    return true;
  }
}

/**
 * One actor with its own animation clock.
 *
 * For a game that already stores animation state on its entities, this is the
 * wrong layer -- use `Sheet.drawFrame` and keep your own index.
 */
export class Actor {
  constructor(sheet, group, { ref = 'idle', tiles = 1, effects = null } = {}) {
    this.s = sheet; this.g = group; this.tiles = tiles;
    this.base = tiles / (sheet.row(group, ref)[0]?.[3] || 1);
    this.effects = effects;
    this.anim = null; this.t = 0; this.frame = 0; this.fps = 12; this.loop = true;
  }

  /** The file carries defaults; the call site wins. */
  play(name, { fps, loop, restart = false } = {}) {
    if (this.anim !== name || restart) { this.anim = name; this.t = 0; this.frame = 0; }
    const meta = this.s.meta(this.g, name);
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

  draw(ctx, x, y, { tile = 1, flip = 1, now = 0, flat = false } = {}) {
    return this.s.drawFrame(ctx, this.g, this.anim, this.frame, {
      x, y, tile, scale: this.base, flip, now, flat,
      effects: this.effects ? (this.effects[this.anim] ||
                               this.effects.default || null) : null,
    });
  }
}
