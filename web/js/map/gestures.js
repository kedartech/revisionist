// Live pan and zoom on the map's drawing: the finger, the mouse, the wheel and the keys.

import { GIVE_PX, KEY_ZOOM, centreBounds, centreFor, clampCentre, clampZoom, unitsPerPx, windowAt } from './view.js';

/** A press that moves less than TAP_PX pixels and lifts within TAP_MS is a tap. [proposed] */
export const TAP_PX = 8;
export const TAP_MS = 300;
/** A slide's speed falls by a factor of e every FRICTION_MS. [proposed] */
const FRICTION_MS = 325;
/** Past the frame's edge a slide brakes this much faster, then the view comes back. */
const BRAKE_MS = 40;
/** How quickly the view comes back to the edge, and a smooth zoom or a key's pan reaches its goal. */
const SETTLE_MS = 90;
/** Labels are recomputed at most once in this many ms during a gesture. */
const LABELS_MS = 100;
/** The release speed is read over the last VELOCITY_MS of the drag. */
const VELOCITY_MS = 100;
/** A slide slower than this (px a ms), and back within half a pixel of the edge, stops. */
const STOP_PX_MS = 0.02;
/** The zoom a wheel's pixel of scroll multiplies by: e to the minus this. */
const WHEEL_PER_PX = 0.0015;
/** How much of the view's width or height an arrow key moves it. [proposed] */
const KEY_PAN = 0.15;
const PAN_KEYS = Object.freeze({ ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] });

/** `d` units past the edge, shown as at most `give` units: a spring that stiffens. */
const softly = (d, give) => (give > 0 ? give * (1 - Math.exp(-d / give)) : 0);

/**
 * Live pan and zoom on drawing `root`, whose frame is `rect` (units) drawn into `px` until it is
 * measured. While a finger or the mouse drags, or a pinch, the wheel, the plus and minus keys or
 * the arrow keys move the view, each frame is drawn as `opts.onLive(window, { labels, end })`,
 * with `labels` true at most ten times a second; on release a drag slides on and slows to a stop
 * inside the frame. The view is told once, when the gesture ends, as `opts.onView({ zoom,
 * centre })`. A tap on no control of the drawing is told as `opts.onTap([x, y])`, in units.
 * `opts`: { zoom, centre, selected (a piece is picked: the arrow keys are its), reduced (no
 * slide and no animated zoom; a value or a function), now, frame (an animation-frame scheduler) }.
 */
export function gestures(root, rect, opts = {}, px = { width: 1, height: 1 }) {
  const now = opts.now ?? (() => globalThis.performance?.now?.() ?? Date.now());
  const frame = opts.frame ?? (typeof globalThis.requestAnimationFrame === 'function' ? (cb) => globalThis.requestAnimationFrame(cb) : null);
  const reduced = () => (typeof opts.reduced === 'function' ? opts.reduced() : Boolean(opts.reduced));
  let zoom = clampZoom(opts.zoom ?? 1);
  // the middle of the view as the finger puts it, past the frame's edge as well
  let raw = clampCentre(rect, zoom, opts.centre ?? [rect.x + rect.w / 2, rect.y + rect.h / 2]);
  let box = null;
  let active = false;
  let pending = false;
  let lastLabels = -Infinity;
  let anim = null;
  let press = null;
  let pinch = null;
  let samples = [];
  let swallow = false;
  const down = new Map();

  const measure = () => root.getBoundingClientRect?.() ?? { left: 0, top: 0, width: px.width, height: px.height };
  // measured once a gesture starts: the drawing's own box moves with it while it is live
  const at = () => box ?? measure();
  const kNow = () => unitsPerPx(windowAt(rect, zoom, raw), at());
  const shown = () => {
    const { lo, hi } = centreBounds(rect, zoom);
    const give = GIVE_PX * kNow();
    return [0, 1].map((i) => (raw[i] < lo[i] ? lo[i] - softly(lo[i] - raw[i], give)
      : raw[i] > hi[i] ? hi[i] + softly(raw[i] - hi[i], give) : raw[i]));
  };
  const win = () => windowAt(rect, zoom, shown());
  const local = ([x, y]) => { const b = at(); return [x - b.left, y - b.top]; };
  const toUnits = (x, y) => {
    const w = win(); const b = at();
    const k = unitsPerPx(w, b);
    return [w.x + (x - b.left - (b.width - w.w / k) / 2) * k, w.y + (y - b.top - (b.height - w.h / k) / 2) * k];
  };
  const past = (i) => {
    const { lo, hi } = centreBounds(rect, zoom);
    return raw[i] < lo[i] ? raw[i] - lo[i] : raw[i] > hi[i] ? raw[i] - hi[i] : 0;
  };

  const begin = () => {
    if (active) return;
    active = true;
    box = measure();
    lastLabels = -Infinity;
  };
  const end = () => {
    anim = null;
    raw = clampCentre(rect, zoom, raw);
    opts.onLive?.(win(), { labels: true, end: true });
    active = false;
    box = null;
    opts.onView?.({ zoom, centre: [...raw] });
  };

  /** One step of the running animation, `dt` ms on; true when it has reached its end. */
  const step = (dt) => {
    const a = 1 - Math.exp(-dt / SETTLE_MS);
    if (anim.kind === 'zoom') {
      zoom = Math.exp(Math.log(zoom) + (Math.log(anim.target) - Math.log(zoom)) * a);
      if (Math.abs(Math.log(anim.target / zoom)) < 1e-3) zoom = anim.target;
      raw = clampCentre(rect, zoom, anim.u ? centreFor(rect, zoom, anim.u, anim.at, at()) : anim.keep);
      return zoom === anim.target;
    }
    const k = kNow();
    if (anim.kind === 'pan') {
      raw = raw.map((v, i) => v + (anim.goal[i] - v) * a);
      return raw.every((v, i) => Math.abs(anim.goal[i] - v) / k < 0.5);
    }
    let moving = false;
    for (const i of [0, 1]) {
      raw[i] += anim.v[i] * dt;
      if (past(i)) {
        anim.v[i] *= Math.exp(-dt / BRAKE_MS);
        if (Math.abs(anim.v[i]) / k <= STOP_PX_MS) { anim.v[i] = 0; raw[i] -= past(i) * a; }
      } else anim.v[i] *= Math.exp(-dt / FRICTION_MS);
      if (Math.abs(anim.v[i]) / k > STOP_PX_MS || Math.abs(past(i)) / k > 0.5) moving = true;
    }
    return !moving;
  };

  const paint = () => {
    const t = now();
    if (anim) {
      const done = step(Math.min(Math.max(t - anim.t, 0), 64));
      anim.t = t;
      if (done) { end(); return; }
    }
    const labels = t - lastLabels >= LABELS_MS;
    if (labels) lastLabels = t;
    opts.onLive?.(win(), { labels, end: false });
    if (anim) schedule();
  };
  function schedule() {
    if (!frame) { paint(); return; }
    if (pending) return;
    pending = true;
    frame(() => { pending = false; if (active) paint(); });
  }
  const animate = (a) => {
    begin();
    if (!frame || reduced()) {
      if (a.kind === 'zoom') {
        zoom = a.target;
        raw = clampCentre(rect, zoom, a.u ? centreFor(rect, zoom, a.u, a.at, at()) : a.keep);
      } else if (a.kind === 'pan') raw = [...a.goal];
      end();
      return;
    }
    anim = { ...a, t: now() };
    schedule();
  };

  const spread = () => {
    const [a, b] = [...down.values()];
    return { d: Math.hypot(a.x - b.x, a.y - b.y), mid: [(a.x + b.x) / 2, (a.y + b.y) / 2] };
  };
  const drag = (p, moved) => {
    press = { x: p.x, y: p.y, t: now(), centre: [...raw], moved };
    samples = [{ x: p.x, y: p.y, t: press.t }];
  };

  root.addEventListener('pointerdown', (e) => {
    if (e.button > 0) return;
    swallow = false;
    // a press during a slide catches the map where it is
    const caught = Boolean(anim);
    anim = null;
    begin();
    down.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (down.size === 1) drag(down.get(e.pointerId), caught);
    else if (down.size === 2) {
      const s = spread();
      pinch = { d: s.d, zoom, u: toUnits(...s.mid) };
      if (press) press.moved = true;
    }
  });

  root.addEventListener('pointermove', (e) => {
    if (!down.has(e.pointerId)) return;
    down.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch && down.size >= 2) {
      const s = spread();
      if (pinch.d > 0) zoom = clampZoom(pinch.zoom * (s.d / pinch.d));
      raw = clampCentre(rect, zoom, centreFor(rect, zoom, pinch.u, local(s.mid), at()));
      schedule();
      return;
    }
    if (!press || down.size !== 1) return;
    const dx = e.clientX - press.x; const dy = e.clientY - press.y;
    if (!press.moved && Math.hypot(dx, dy) < TAP_PX) return;
    if (!press.moved) {
      press.moved = true;
      try { root.setPointerCapture?.(e.pointerId); } catch { /* a pointer the page no longer has */ }
    }
    const k = kNow();
    raw = [press.centre[0] - dx * k, press.centre[1] - dy * k];
    const t = now();
    samples = [...samples.filter((s) => t - s.t <= VELOCITY_MS), { x: e.clientX, y: e.clientY, t }];
    schedule();
  });

  const lift = (e) => {
    if (!down.has(e.pointerId)) return;
    down.delete(e.pointerId);
    if (pinch && down.size === 1) {
      // one finger left: the gesture goes on as a drag from it
      pinch = null;
      drag([...down.values()][0], true);
      return;
    }
    if (down.size) return;
    pinch = null;
    const p = press;
    press = null;
    if (!p?.moved) {
      if (p && e.type === 'pointerup' && now() - p.t <= TAP_MS && !e.target?.closest?.('[role="button"]')) {
        // a tap that no control of the drawing took: the drawing finds what lies under it
        opts.onTap?.(toUnits(e.clientX, e.clientY));
      }
      active = false;
      box = null;
      return;
    }
    swallow = true;
    if (!frame || reduced()) { end(); return; }
    const t = now();
    const recent = samples.filter((s) => t - s.t <= VELOCITY_MS);
    const [first, last] = [recent[0], recent.at(-1)];
    const span = first && last ? last.t - first.t : 0;
    const k = kNow();
    const v = span > 0 ? [-(last.x - first.x) / span * k, -(last.y - first.y) / span * k] : [0, 0];
    anim = { kind: 'slide', v, t };
    schedule();
  };
  root.addEventListener('pointerup', lift);
  root.addEventListener('pointercancel', lift);

  // the click that ends a pan is not a press of the mark under the finger
  root.addEventListener('click', (e) => {
    if (!swallow) return;
    swallow = false;
    e.preventDefault();
    e.stopPropagation();
  }, true);

  const zoomBy = (factor, point) => {
    const target = clampZoom((anim?.kind === 'zoom' ? anim.target : zoom) * factor);
    if (target === zoom && !anim) return;
    begin();
    const b = at();
    animate({ kind: 'zoom', target, keep: [...raw], u: point ? toUnits(point[0] + b.left, point[1] + b.top) : null, at: point });
  };

  root.addEventListener('wheel', (e) => {
    if (down.size) return;
    e.preventDefault();
    const perLine = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? at().height : 1;
    zoomBy(Math.exp(-e.deltaY * perLine * WHEEL_PER_PX), local([e.clientX, e.clientY]));
  }, { passive: false });

  root.addEventListener('keydown', (e) => {
    if (e.defaultPrevented || down.size || e.altKey || e.ctrlKey || e.metaKey) return;
    const dir = PAN_KEYS[e.key];
    if (dir) {
      if (opts.selected) return;
      e.preventDefault();
      const from = anim?.kind === 'pan' ? anim.goal : raw;
      const w = rect.w / zoom; const h = rect.h / zoom;
      animate({ kind: 'pan', goal: clampCentre(rect, zoom, [from[0] + dir[0] * w * KEY_PAN, from[1] + dir[1] * h * KEY_PAN]) });
    } else if (e.key === '+' || e.key === '=') {
      e.preventDefault();
      zoomBy(KEY_ZOOM, null);
    } else if (e.key === '-' || e.key === '_') {
      e.preventDefault();
      zoomBy(1 / KEY_ZOOM, null);
    }
  });
}
