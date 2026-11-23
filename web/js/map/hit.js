// Which area a point lies in.

/** Whether point `xy` (map file units) lies in area `key` of `shapes`: inside an odd number of its rings. */
export function inArea(shapes, key, [x, y]) {
  const rings = shapes?.areas?.[key]?.rings ?? [];
  let inside = false;
  for (const ring of rings) {
    const pts = ring.map((i) => shapes.vertices[i]);
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i, i += 1) {
      const [xi, yi] = pts[i];
      const [xj, yj] = pts[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
  }
  return inside;
}

/**
 * The first of areas `keys` under point `xy` of the drawing made with projection `proj`, or null.
 * The point is turned back into map coordinates first: the area test runs on the map file's own.
 */
export function areaAt(shapes, proj, xy, keys) {
  const at = proj.invert(xy);
  return keys.find((key) => inArea(shapes, key, at)) ?? null;
}

