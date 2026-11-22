// The window on a map: zoom steps, the part of a frame shown, pixel sizing and the pinch rule.

/** The zoom steps within a frame. [proposed] */
export const ZOOMS = Object.freeze([1, 2, 4]);
/**
 * What is shown of `rect` at `zoom` (one of ZOOMS), around `centre` ([x, y] in the
 * projection's units; the frame's middle when null), never outside the frame.
 */
export function viewWindow(rect, zoom = 1, centre = null) {
  const z = ZOOMS.includes(zoom) ? zoom : 1;
  const w = rect.w / z; const h = rect.h / z;
  const [cx, cy] = centre ?? [rect.x + rect.w / 2, rect.y + rect.h / 2];
  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
  return { x: clamp(cx - w / 2, rect.x, rect.x + rect.w - w), y: clamp(cy - h / 2, rect.y, rect.y + rect.h - h), w, h };
}

/** Units of the drawing per CSS pixel, for a window drawn into `px` ({ width, height }) to fit. */
export const unitsPerPx = (win, px) => Math.max(win.w / Math.max(px.width, 1), win.h / Math.max(px.height, 1));

/** The zoom step nearest `zoom * ratio` (a pinch's spread over its start), by halvings. */
export function pinchZoom(zoom, ratio) {
  const want = Math.log2(Math.max(zoom * ratio, 1e-6));
  return ZOOMS.reduce((best, z) => (Math.abs(Math.log2(z) - want) < Math.abs(Math.log2(best) - want) ? z : best), ZOOMS[0]);
}

