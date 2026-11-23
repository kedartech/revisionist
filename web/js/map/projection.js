// Map projections and frames: degrees or map units to the drawing's units.

/** An equirectangular projection for ``box``, squeezed by the cosine of its middle
 *  latitude so the high north is not drawn twice as wide as it is. */
export function projection(box) {
  const k = Math.cos(((box.north + box.south) / 2) * (Math.PI / 180));
  const x = (lon) => (lon - box.west) * k;
  const y = (lat) => box.north - lat;
  return { x, y, width: (box.east - box.west) * k, height: box.north - box.south };
}

/** A `[west, south, east, north]` list as a box object. */
export const boxOf = ([west, south, east, north]) => ({ west, south, east, north });

const RAD = Math.PI / 180;
const DEG = 180 / Math.PI;
const EE = { A1: 1.340264, A2: -0.081106, A3: 0.000893, A4: 0.003796, M: Math.sqrt(3) / 2 };
const eeY = (t, t2, t6) => t * (EE.A1 + EE.A2 * t2 + t6 * (EE.A3 + EE.A4 * t2));
const eeDy = (t2, t6) => EE.A1 + 3 * EE.A2 * t2 + t6 * (7 * EE.A3 + 9 * EE.A4 * t2);
const neX = (p2) => 0.8707 + p2 * (-0.131979 + p2 * (-0.013791 + p2 * p2 * p2 * (0.003971 - 0.001529 * p2)));
const neY = (p, p2, p4) => p * (1.007226 + p2 * (0.015085 + p4 * (-0.044475 + 0.028874 * p2 - 0.005916 * p4)));
const neDy = (p2, p4) => 1.007226 + p2 * (0.015085 * 3 + p4 * (-0.044475 * 7 + 0.028874 * 9 * p2 - 0.005916 * 11 * p4));

/** Newton's method from `start`: `f(v)` gives the value less the target, and the slope. */
function solve(f, start) {
  let v = start;
  for (let i = 0; i < 25; i += 1) {
    const [d, slope] = f(v);
    v -= d / slope;
    if (Math.abs(d / slope) < 1e-12) break;
  }
  return v;
}

/**
 * The world projections a longitude-latitude map can be drawn in. Each `forward(dlon, lat)` takes
 * degrees east of the map's middle meridian and degrees north, and gives `[x, y]` in degree-sized
 * units with y up; `inverse(x, y)` turns that back.
 */
export const PROJECTIONS = Object.freeze({
  'equal-earth': {
    forward(l, p) {
      const t = Math.asin(EE.M * Math.sin(p * RAD));
      const t2 = t * t; const t6 = t2 * t2 * t2;
      return [((l * RAD * Math.cos(t)) / (EE.M * eeDy(t2, t6))) * DEG, eeY(t, t2, t6) * DEG];
    },
    inverse(x, y) {
      const want = y * RAD;
      const t = solve((v) => { const v2 = v * v; const v6 = v2 * v2 * v2; return [eeY(v, v2, v6) - want, eeDy(v2, v6)]; }, want);
      const t2 = t * t; const t6 = t2 * t2 * t2;
      return [((EE.M * x * RAD * eeDy(t2, t6)) / Math.cos(t)) * DEG, Math.asin(Math.sin(t) / EE.M) * DEG];
    },
  },
  'natural-earth': {
    forward(l, p) {
      const r = p * RAD; const p2 = r * r;
      return [l * neX(p2), neY(r, p2, p2 * p2) * DEG];
    },
    inverse(x, y) {
      const want = y * RAD;
      const r = solve((v) => { const v2 = v * v; return [neY(v, v2, v2 * v2) - want, neDy(v2, v2 * v2)]; }, want);
      return [x / neX(r * r), r * DEG];
    },
  },
  miller: {
    forward: (l, p) => [l, 1.25 * Math.log(Math.tan(Math.PI / 4 + 0.4 * p * RAD)) * DEG],
    inverse: (x, y) => [x, 2.5 * (Math.atan(Math.exp(0.8 * y * RAD)) - Math.PI / 4) * DEG],
  },
});

/** The projection every longitude-latitude map is drawn in. [proposed] */
export const MAP_PROJECTION = 'equal-earth';

/** `pts` with every edge longer than `step` cut into equal parts no longer than it; as given with no step. */
function cut(pts, step) {
  if (!step) return pts;
  const out = pts.length ? [pts[0]] : [];
  for (let i = 1; i < pts.length; i += 1) {
    const [a, b] = [pts[i - 1], pts[i]];
    const n = Math.max(1, Math.ceil(Math.max(Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])) / step));
    for (let s = 1; s <= n; s += 1) out.push([a[0] + ((b[0] - a[0]) * s) / n, a[1] + ((b[1] - a[1]) * s) / n]);
  }
  return out;
}

/** A box's outline, from its north-west corner round, in map coordinates. */
const outline = (box) => [[box.west, box.north], [box.east, box.north], [box.east, box.south], [box.west, box.south], [box.west, box.north]];

/**
 * A longitude-latitude map's projection: `f` (one of PROJECTIONS) centred on the middle meridian
 * of `box`, moved so the box's projected outline starts at (0, 0), y down. Longitudes are never
 * wrapped, so a shape that runs past the edge meridian is drawn whole on its own side of it.
 */
function curved(box, f) {
  const mid = (box.west + box.east) / 2;
  const raw = cut(outline(box), 1).map(([lon, lat]) => f.forward(lon - mid, lat));
  const x0 = Math.min(...raw.map(([x]) => x)); const x1 = Math.max(...raw.map(([x]) => x));
  const y0 = Math.min(...raw.map(([, y]) => y)); const y1 = Math.max(...raw.map(([, y]) => y));
  return {
    point([lon, lat]) { const [x, y] = f.forward(lon - mid, lat); return [x - x0, y1 - y]; },
    invert([x, y]) { const [l, p] = f.inverse(x + x0, y1 - y); return [l + mid, p]; },
    width: x1 - x0, height: y1 - y0, step: 1,
  };
}

/**
 * The projection a territory map is drawn in, from its `coords` and its own box: MAP_PROJECTION
 * for `lonlat`, a plain scale for `flat` (x right, y up, as the map file has them). Each has
 * `point` (map coordinates to the drawing's), `invert`, `width`, `height`, and `step`: the
 * longest edge, in map coordinates, drawn as a straight line (no limit on a flat map).
 */
export function territoryProjection(coords, box) {
  if (coords === 'lonlat') return curved(box, PROJECTIONS[MAP_PROJECTION]);
  return {
    point: ([x, y]) => [x - box.west, box.north - y],
    invert: ([x, y]) => [x + box.west, box.north - y],
    width: box.east - box.west, height: box.north - box.south, step: 0,
  };
}

/** The line through `pts` (map coordinates) in the drawing's units, its long edges cut first. */
export const trace = (proj, pts) => cut(pts, proj.step).map(proj.point);

/** A frame (a box in map coordinates) as a rectangle in the projection's units: the box around its corners and edges as projected. */
export function frameRect(frame, proj) {
  const pts = trace(proj, outline(frame));
  const xs = pts.map(([x]) => x); const ys = pts.map(([, y]) => y);
  const x = Math.min(...xs); const y = Math.min(...ys);
  return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
}
