// The window on a map: zoom steps, the part of a frame shown, pixel sizing, the pinch rule and
// the browser's own full screen.

/** The zoom buttons' stops within a frame. [proposed] */
export const ZOOMS = Object.freeze([1, 2, 4]);
/** The most a gesture zooms in. [proposed] */
export const MAX_ZOOM = 8;
/** How far past the frame's edge a drag or a slide may carry the view, in pixels. [proposed] */
export const GIVE_PX = 40;
/** The zoom a press of the plus or minus key multiplies or divides by. [proposed] */
export const KEY_ZOOM = Math.SQRT2;

/** `zoom` kept between 1 and MAX_ZOOM; 1 for anything that is not a number. */
export const clampZoom = (zoom) => Math.min(Math.max(Number(zoom) || 1, 1), MAX_ZOOM);

/** What is shown of `rect` at `zoom` with its middle at `centre`, wherever that is. */
export function windowAt(rect, zoom, [cx, cy]) {
  const w = rect.w / zoom; const h = rect.h / zoom;
  return { x: cx - w / 2, y: cy - h / 2, w, h };
}

/** The furthest the middle of the view goes each way at `zoom` and stays inside `rect`. */
export function centreBounds(rect, zoom) {
  const w = rect.w / zoom; const h = rect.h / zoom;
  return { lo: [rect.x + w / 2, rect.y + h / 2], hi: [rect.x + rect.w - w / 2, rect.y + rect.h - h / 2] };
}

/** `centre` moved the least that keeps the view inside `rect` at `zoom`. */
export function clampCentre(rect, zoom, centre) {
  const { lo, hi } = centreBounds(rect, zoom);
  return [0, 1].map((i) => Math.min(Math.max(centre[i], lo[i]), hi[i]));
}

/**
 * What is shown of `rect` at `zoom` (kept between 1 and MAX_ZOOM), around `centre` ([x, y] in
 * the projection's units; the frame's middle when null), never outside the frame.
 */
export function viewWindow(rect, zoom = 1, centre = null) {
  const z = clampZoom(zoom);
  return windowAt(rect, z, clampCentre(rect, z, centre ?? [rect.x + rect.w / 2, rect.y + rect.h / 2]));
}

/** Units of the drawing per CSS pixel, for a window drawn into `px` ({ width, height }) to fit. */
export const unitsPerPx = (win, px) => Math.max(win.w / Math.max(px.width, 1), win.h / Math.max(px.height, 1));

/** The zoom step nearest `zoom * ratio` (a pinch's spread over its start), by halvings. */
export function pinchZoom(zoom, ratio) {
  const want = Math.log2(Math.max(zoom * ratio, 1e-6));
  return ZOOMS.reduce((best, z) => (Math.abs(Math.log2(z) - want) < Math.abs(Math.log2(best) - want) ? z : best), ZOOMS[0]);
}

/** Whether the map asked the browser for its own full screen, and has not given it back. */
let askedFull = false;

/** Forget that the browser was asked (tests). */
export function forgetFull() { askedFull = false; }

/** Whether the browser's full screen now on is the one the map asked for. */
export const askedForFull = () => askedFull;

/**
 * Ask the browser for its own full screen (`on`), or give back the one the map asked for. A
 * browser that has none (an iPhone) or refuses, or a page already full for another reason, is
 * left as it is and nothing is thrown: the room fills the page with the map all the same.
 */
export function browserFull(on) {
  const doc = globalThis.document;
  const el = doc?.documentElement;
  const now = doc?.fullscreenElement ?? doc?.webkitFullscreenElement ?? null;
  try {
    if (on) {
      const ask = el?.requestFullscreen ?? el?.webkitRequestFullscreen;
      if (!ask || now) return;
      askedFull = true;
      Promise.resolve(ask.call(el)).catch(() => { askedFull = false; });
      return;
    }
    if (!askedFull) return;
    askedFull = false;
    const leave = doc.exitFullscreen ?? doc.webkitExitFullscreen;
    if (now && leave) Promise.resolve(leave.call(doc)).catch(() => {});
  } catch {
    askedFull = false;
  }
}

/**
 * The middle of the view at `zoom` that draws point `u` (units) at `at` ([x, y], pixels from
 * the top left of `px`), the window fitted to `px` and centred in it.
 */
export function centreFor(rect, zoom, u, at, px) {
  const w = rect.w / zoom; const h = rect.h / zoom;
  const k = unitsPerPx({ w, h }, px);
  const ox = (px.width - w / k) / 2; const oy = (px.height - h / k) / 2;
  return [u[0] - (at[0] - ox) * k + w / 2, u[1] - (at[1] - oy) * k + h / 2];
}
