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

/**
 * The projection a territory map is drawn in, from its `coords` and its own box: today's for
 * `lonlat`, a plain scale for `flat` (x right, y up, as the map file has them).
 */
export function territoryProjection(coords, box) {
  if (coords === 'lonlat') return projection(box);
  return { x: (x) => x - box.west, y: (y) => box.north - y, width: box.east - box.west, height: box.north - box.south };
}

/** A frame (a box in map coordinates) as a rectangle in the projection's units. */
export function frameRect(frame, proj) {
  const x0 = proj.x(frame.west); const x1 = proj.x(frame.east);
  const y0 = proj.y(frame.north); const y1 = proj.y(frame.south);
  return { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) };
}

