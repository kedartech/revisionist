// Pinch and drag on the map's drawing.

import { pinchZoom, unitsPerPx } from './view.js';

/**
 * Pinch and drag on drawing `root`: a pinch picks the zoom step nearest its spread, around its
 * middle; a drag at a zoom past 1 moves the window. Each is told once, when the gesture ends,
 * as `onView({ zoom, centre })`. A tap on no control of the drawing is told as `onTap([x, y])`,
 * in the drawing's units.
 */
export function gestures(root, win, opts, px) {
  const down = new Map();
  let start = null;
  const box = () => root.getBoundingClientRect?.() ?? { left: 0, top: 0, width: px.width, height: px.height };
  const toUnits = (cx, cy) => {
    const b = box();
    const k = unitsPerPx(win, b);
    const ox = (b.width - win.w / k) / 2; const oy = (b.height - win.h / k) / 2;
    return [win.x + (cx - b.left - ox) * k, win.y + (cy - b.top - oy) * k];
  };
  const spread = () => {
    const [a, b] = [...down.values()];
    return { d: Math.hypot(a.x - b.x, a.y - b.y), mid: [(a.x + b.x) / 2, (a.y + b.y) / 2] };
  };
  const zoom = opts.zoom ?? 1;
  const centre = opts.centre ?? [win.x + win.w / 2, win.y + win.h / 2];
  root.addEventListener('pointerdown', (e) => {
    down.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (down.size === 2) start = { kind: 'pinch', ...spread() };
    else if (down.size === 1) start = { kind: 'drag', x: e.clientX, y: e.clientY };
  });
  root.addEventListener('pointermove', (e) => {
    if (down.has(e.pointerId)) down.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (start?.kind === 'pinch' && down.size === 2) start.now = spread();
  });
  const end = (e) => {
    const was = start;
    const at = down.get(e.pointerId) ?? { x: e.clientX, y: e.clientY };
    down.delete(e.pointerId);
    if (!was || down.size) return;
    start = null;
    if (was.kind === 'pinch' && was.now && was.d > 0) {
      opts.onView?.({ zoom: pinchZoom(zoom, was.now.d / was.d), centre: toUnits(...was.now.mid) });
    } else if (was.kind === 'drag' && zoom > 1 && Math.hypot(at.x - was.x, at.y - was.y) > 8) {
      const k = unitsPerPx(win, box());
      opts.onView?.({ zoom, centre: [centre[0] - (at.x - was.x) * k, centre[1] - (at.y - was.y) * k] });
    } else if (was.kind === 'drag' && Math.hypot(at.x - was.x, at.y - was.y) <= 8 && !e.target?.closest?.('[role="button"]')) {
      // a tap that no control of the drawing took: the drawing finds what lies under it
      opts.onTap?.(toUnits(at.x, at.y));
    }
  };
  root.addEventListener('pointerup', end);
  root.addEventListener('pointercancel', end);
}
