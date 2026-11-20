// Pure helpers for the realism views: sorting, counting and the plain-words
// lines. No DOM here, and no figure that reads as a chance of anything.

import { worldDate } from './rules.js';

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const CLASSIFICATION = Object.freeze({
  open: 'Open',
  restricted: 'Restricted',
  confidential: 'Confidential',
  secret: 'Secret',
  most_secret: 'Most Secret',
});

const CHANNEL = Object.freeze({
  in_person: 'In person',
  telephone: 'Telephone',
  cable: 'Cable',
  letter: 'Letter',
  courier: 'Courier',
  radio: 'Radio',
  press: 'Press',
});

const STEP_DONE = Object.freeze({
  pass: 'passed it on',
  expedite: 'pressed it forward',
  amend: 'amended it',
  refuse: 'refused it',
  stall: 'held it back',
  leak: 'let word of it out',
});

const SETTLED = Object.freeze({ enacted: 'Enacted', refused: 'Refused', lapsed: 'Lapsed', withdrawn: 'Withdrawn' });

function pick(table, value) {
  if (!Object.hasOwn(table, value)) throw new Error(`unknown word: ${value}`);
  return table[value];
}

export const classificationWord = (c) => pick(CLASSIFICATION, c);
export const channelWord = (ch) => pick(CHANNEL, ch);

/** Newest arrival first (or oldest first with 'oldest'); ties keep their given order. Does not mutate. */
export function sortInTray(items, order = 'newest') {
  const sign = order === 'oldest' ? -1 : 1;
  return items
    .map((item, i) => [item, i])
    .sort(([a, i], [b, j]) => (a.arrives < b.arrives ? sign : a.arrives > b.arrives ? -sign : i - j))
    .map(([item]) => item);
}

export function unreadCount(items) {
  return items.filter((d) => !d.ack && d.unread).length;
}

/** The in-tray filters, in the order the bar shows them. An acknowledgement (`ack`) is in none:
 * its order's ledger line carries it as a receipt. */
export const TRAY_FILTERS = Object.freeze([
  ['all', 'All'], ['unread', 'Unread'], ['read', 'Read'], ['flagged', 'Flagged'], ['news', 'News'],
]);

const KEEP = Object.freeze({
  all: (d) => !d.ack,
  unread: (d) => !d.ack && d.unread,
  read: (d) => !d.ack && !d.unread,
  flagged: (d) => !d.ack && d.flagged,
  news: (d) => !d.ack && !d.group,
});

export function filterInTray(items, filter) {
  return items.filter(pick(KEEP, filter));
}

export function trayCounts(items) {
  return Object.fromEntries(TRAY_FILTERS.map(([key]) => [key, filterInTray(items, key).length]));
}

/** "You plan about a week ahead" for 7 days, "about a month" for 28 to 31, else "about N days". */
export function horizonWords(days) {
  if (days === 7) return 'You plan about a week ahead';
  if (days >= 28 && days <= 31) return 'You plan about a month ahead';
  return `You plan about ${days} ${days === 1 ? 'day' : 'days'} ahead`;
}

/** The desk's aims block: heading, lines and a note that they bind nothing. Null when there
 * are none, which is also how an older payload without `aims` reads. */
export function aimsBlock(aims) {
  const lines = Array.isArray(aims) ? aims.filter(Boolean) : [];
  if (!lines.length) return null;
  return {
    heading: 'As history had it',
    lines,
    note: 'What this person was set on at the start. Not binding.',
  };
}

/** Powers as one sentence: "Commander in chief, veto and executive orders." */
export function powersSentence(powers) {
  const items = powers.map((p) => p.trim().replace(/\.$/, '')).filter(Boolean);
  if (!items.length) return '';
  const joined = items.length > 1 ? `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}` : items[0];
  return `${joined[0].toUpperCase()}${joined.slice(1)}.`;
}

/** "Sam Rayburn: passed it on, 4 Sep 1941" or "Sam Rayburn: has it now". */
export function stepLine(step) {
  if (!step.action) return `${step.person}: has it now`;
  const [y, m, d] = (step.on ?? '').split('-').map(Number);
  const when = step.on ? `, ${d} ${MONTHS_SHORT[m - 1]} ${y}` : '';
  return `${step.person}: ${pick(STEP_DONE, step.action)}${when}`;
}

/** "16 Oct". */
export function shortDate(iso) {
  const [, m, d] = iso.split('-').map(Number);
  return `${d} ${MONTHS_SHORT[m - 1]}`;
}

/** Where an order stands, in words. */
export function trackerLine(order) {
  if (order.status === 'moving') {
    if (order.decision_needed) return 'Awaiting your decision';
    return order.with_person ? `With ${order.with_person} since ${worldDate(order.since)}` : 'Moving';
  }
  const last = [...order.steps].reverse().find((s) => s.on);
  const when = last ? ` ${worldDate(last.on)}` : '';
  return `${pick(SETTLED, order.status)}${when}`;
}

/** "Monday 20 October 1941 · next: Rayburn's count, about 24 Oct · 9 quiet days passed". */
export function paceLine(clock) {
  const [y, m, d] = clock.world_date.split('-').map(Number);
  const weekday = WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
  const parts = [`${weekday} ${worldDate(clock.world_date)}`];
  if (clock.waiting_on) {
    const about = clock.next_world_date ? shortDate(clock.next_world_date) : null;
    // a reason named with its own date ("... (4 Sep)") is not given the date again
    const named = about && new RegExp(`(^|\\D)${about}\\b`).test(clock.waiting_on);
    parts.push(about && !named ? `next: ${clock.waiting_on}, about ${about}` : `next: ${clock.waiting_on}`);
  } else if (clock.next_world_date) {
    parts.push(`nothing due before about ${shortDate(clock.next_world_date)}`);
  }
  if (clock.days_collapsed > 0) {
    parts.push(`${clock.days_collapsed} quiet ${clock.days_collapsed === 1 ? 'day' : 'days'} passed`);
  }
  return parts.join(' · ');
}

/** What a player may do at a step they hold (core/realism/pipeline.py `StepAction`), in the order offered. */
export const STEP_ACTIONS = Object.freeze([
  ['pass', 'Pass it on'],
  ['expedite', 'Expedite'],
  ['amend', 'Amend'],
  ['stall', 'Stall'],
  ['leak', 'Leak'],
  ['refuse', 'Refuse'],
]);

/** How a directive travels, as the form offers it: a letter to someone at hand is a memo. */
export function directiveChannel(ch) {
  return ch === 'letter' ? 'Memo' : channelWord(ch);
}

/** The line above a directive's reading: who it goes to and how. */
export function addressLine(p) {
  const how = directiveChannel(p.channel).toLowerCase();
  return `To ${p.to}, ${p.channel === 'in_person' ? how : `by ${how}`}`;
}

/** Names to offer for entity parameters: contacts and principals, once each, sorted. */
export function entityChoices(desk) {
  return [...new Set([...desk.inner_circle.map((c) => c.person), ...desk.principals])].sort();
}

/**
 * A page's lines as one entry per label: a long line the engine broke into "Label (cont.)"
 * pieces is joined back onto its first piece, and a line with no figure is left off.
 */
export function sheetLines(lines) {
  const out = [];
  for (const b of lines) {
    if (b.value === null) continue;
    const head = b.label.endsWith(' (cont.)') ? b.label.slice(0, -' (cont.)'.length) : null;
    const last = out[out.length - 1];
    if (head !== null && last && last.label === head) {
      out[out.length - 1] = { ...last, value: `${last.value} ${b.value}` };
    } else {
      out.push({ ...b });
    }
  }
  return out;
}

/** What a page's structured lines are called: figures when they are numbers, particulars when they are words. */
export function linesHeading(lines) {
  return lines.some((b) => typeof b.value === 'string') ? 'Particulars' : 'Figures quoted';
}

const NUMBER = new Intl.NumberFormat('en-US');

/** "209,835 GRT" or "56 percent"; null for a gap, which the board says in words. */
export function figureValue(value, unit) {
  if (value === null) return null;
  return `${NUMBER.format(value)}${unit ? ` ${unit}` : ''}`;
}

const TREND = Object.freeze({ up: 'Up', down: 'Down', level: 'Unchanged' });

/** The latest figure against the one given before it: "Up from 55", "Unchanged", "First figure given". */
export function trendLine(source) {
  if (source.value === null) return '';
  if (!source.trend) return 'First figure given';
  if (source.trend === 'level') return pick(TREND, 'level');
  const given = source.history.filter((r) => r.value !== null);
  const before = given.length > 1 ? given[given.length - 2] : null;
  return `${pick(TREND, source.trend)}${before ? ` from ${NUMBER.format(before.value)}` : ''}`;
}

/** A gap in words, with the date a figure was last given; never an estimate. */
export function gapLine(source) {
  return source.last_given ? `No figure given; last given ${worldDate(source.last_given)}` : 'No figure given yet';
}

/** "Reported by Sam Rayburn, 13 October 1941; arrived the same day". */
export function reportLine(source) {
  const arrived = source.arrives === source.issued ? 'arrived the same day' : `arrived ${worldDate(source.arrives)}`;
  return `Reported by ${source.author}, ${worldDate(source.issued)}; ${arrived}`;
}

/** The recent reports, oldest first: "55 · 56 · no figure · 56". */
export function runLine(history) {
  return history.map((r) => (r.value === null ? 'no figure' : NUMBER.format(r.value))).join(' · ');
}

/** The host's line while the cast is being chosen: who is still to pick. */
export function castLine(waiting) {
  if (!waiting) return 'Everyone has chosen. You can begin.';
  return waiting === 1 ? 'Waiting for 1 player to choose.' : `Waiting for ${waiting} players to choose.`;
}

// --- the map ---------------------------------------------------------------------

const MARK_KIND = Object.freeze({ fleet: 'Fleet', army: 'Army', air: 'Air group', front: 'Front', route: 'Convoy route' });
const MARK_SIDE = Object.freeze({ own: 'Yours', other: 'Foreign', none: 'Both sides' });
const CERTAINTY = Object.freeze({ known: 'Known', reported: 'Reported', stale: 'Stale' });

export const markKindWord = (k) => pick(MARK_KIND, k);
/** What a picked mark is: a world piece's own kind (as the territory view says it), else the mark's kind. */
export const markWhatWord = (m) => (m.kind === 'piece' ? (m.piece?.kind ?? 'Piece') : markKindWord(m.kind));
export const certaintyWord = (c) => pick(CERTAINTY, c);

/** "Foreign · Germany", or "Both sides" for a front. */
export function sideLine(mark) {
  const word = pick(MARK_SIDE, mark.side);
  return mark.side_name ? `${word} · ${mark.side_name}` : word;
}

/** "Smolensk", or "Leningrad – Smolensk – Odessa" for a line. */
export const whereLine = (mark) => mark.places.map((p) => p.name).join(' – ');

/** "Reported 1 October 1941 by Alfred Jodl": where it was then, not now. */
export const sightedLine = (mark) => `Reported ${worldDate(mark.reported)} by ${mark.source}`;

/** One of the seat's own movement orders, in words: "Ordered to Argentia: with Harold R. Stark". */
export function mapOrderLine(o) {
  const head = o.status === 'awaiting' ? `${o.force}: ordered to ${o.to.name}` : `${o.force}: under way to ${o.to.name}`;
  const tail = o.status === 'awaiting'
    ? (o.with_person ? `, the order is with ${o.with_person}` : ', the order is moving')
    : ', not yet reported there';
  return `${head}${tail} (filed ${worldDate(o.filed)})`;
}

/** Lines first, then forces, by name: forces are drawn over the lines they sit on. */
export function sortMarks(marks) {
  const rank = (m) => (m.places.length > 1 ? 0 : 1);
  return [...marks].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
}

/** The box, in degrees, around a set of places. */
function placesBox(places) {
  const lons = places.map((p) => p.lon);
  const lats = places.map((p) => p.lat);
  return { west: Math.min(...lons), east: Math.max(...lons), south: Math.min(...lats), north: Math.max(...lats) };
}

/**
 * Each theatre the places name, by name, with the box (in degrees) around its places. A
 * theatre whose places lie closer across the date line than around the map has two parts,
 * one each side of it. A place with no theatre is in none.
 */
export function theatreAreas(places) {
  const by = new Map();
  for (const p of places) if (p.theatre) by.set(p.theatre, [...(by.get(p.theatre) ?? []), p]);
  return [...by.keys()].sort((a, b) => a.localeCompare(b)).map((name) => {
    const group = by.get(name);
    const lons = [...new Set(group.map((p) => p.lon))].sort((a, b) => a - b);
    let gap = lons[0] + 360 - lons.at(-1);
    let cut = null;
    for (let i = 1; i < lons.length; i += 1) {
      if (lons[i] - lons[i - 1] > gap) { gap = lons[i] - lons[i - 1]; cut = lons[i]; }
    }
    if (cut === null) return { name, parts: [placesBox(group)] };
    return { name, parts: [placesBox(group.filter((p) => p.lon >= cut)), placesBox(group.filter((p) => p.lon < cut))] };
  });
}

/** A stance's word, with its step when the staff hold one: "Hostile, 1 of 5", or "Unknown". */
export function stanceWords(stance) {
  const step = Number.isInteger(stance?.step) && stance.step >= 1 && stance.step <= 5 ? stance.step : null;
  return step ? `${stance.word}, ${step} of 5` : stance.word;
}

/** A capital on the map in words: "Adolf Hitler, Berlin: Hostile, 1 of 5", then ", at war" when it is. */
export function capitalLine(c) {
  return `${c.name}, ${c.place.name}: ${stanceWords(c.stance)}${c.at_war ? ', at war' : ''}`;
}

/** A form's force choice in words as a name: its label without a leading "The". */
const choiceName = (label) => label.replace(/^The /, '');

/**
 * The seat's forms that can move the force a map mark names: each form with a force list and
 * a destination that carries places, where one force's label is the mark's name, or that
 * name's last words once a leading "The" is dropped ("The Atlantic Fleet" for "US Atlantic
 * Fleet"). `[{ lever, force }]`, `force` being the choice's value; a foreign mark has none.
 */
export function formsMoving(levers, mark) {
  if (mark?.side !== 'own' || mark.places?.length !== 1) return [];
  const out = [];
  for (const lever of levers ?? []) {
    const param = lever.params.find((p) => p.name === 'force' && p.kind === 'enum');
    if (!param || !lever.params.some((p) => p.places?.length)) continue;
    const exact = param.choices.find((c) => c.label === mark.name);
    const named = exact ?? param.choices.find((c) => {
      const words = choiceName(c.label);
      return mark.name === words || mark.name.endsWith(` ${words}`);
    });
    if (named) out.push({ lever, force: named.value });
  }
  return out;
}

const MIN_SPAN = Object.freeze({ lon: 30, lat: 18 });

/** The box to draw, in degrees: what the marks (or, with none, the places) span,
 *  padded, never narrower than MIN_SPAN. 'world' is the whole map. */
export function mapBox(map, scope = 'reports') {
  if (scope === 'world') return { west: -180, east: 180, south: -60, north: 80 };
  const marked = [...map.marks.flatMap((m) => m.places), ...(map.orders ?? []).map((o) => o.to)];
  const pts = marked.length ? marked : map.places;
  if (!pts.length) return mapBox(map, 'world');
  const lons = pts.map((p) => p.lon);
  const lats = pts.map((p) => p.lat);
  const grow = (lo, hi, min) => {
    const pad = Math.max((hi - lo) * 0.15, (min - (hi - lo)) / 2, 5);
    return [lo - pad, hi + pad];
  };
  const [west, east] = grow(Math.min(...lons), Math.max(...lons), MIN_SPAN.lon);
  const [south, north] = grow(Math.min(...lats), Math.max(...lats), MIN_SPAN.lat);
  return { west: Math.max(west, -180), east: Math.min(east, 180), south: Math.max(south, -85), north: Math.min(north, 85) };
}

/** An equirectangular projection for ``box``, squeezed by the cosine of its middle
 *  latitude so the high north is not drawn twice as wide as it is. */
export function projection(box) {
  const k = Math.cos(((box.north + box.south) / 2) * (Math.PI / 180));
  const x = (lon) => (lon - box.west) * k;
  const y = (lat) => box.north - lat;
  return { x, y, width: (box.east - box.west) * k, height: box.north - box.south };
}

const r1 = (n) => Math.round(n * 10) / 10;

/** One SVG path for the land rings that touch ``box`` (draw it even-odd: inner rings are lakes). */
export function landPath(rings, box, proj) {
  const out = [];
  for (const ring of rings) {
    let w = 180; let e = -180; let s = 90; let n = -90;
    for (const [lon, lat] of ring) {
      w = Math.min(w, lon); e = Math.max(e, lon); s = Math.min(s, lat); n = Math.max(n, lat);
    }
    if (e < box.west || w > box.east || n < box.south || s > box.north) continue;
    out.push(`M${ring.map(([lon, lat]) => `${r1(proj.x(lon))} ${r1(proj.y(lat))}`).join('L')}Z`);
  }
  return out.join('');
}

// --- the territory map ------------------------------------------------------------

/** The zoom steps within a frame. [proposed] */
export const ZOOMS = Object.freeze([1, 2, 4]);
/** The smallest a mark is drawn, and the smallest tap target, in CSS pixels. [proposed] */
export const MIN_MARK_PX = 24;
export const MIN_TAP_PX = 44;
/** An area's name, in CSS pixels. */
export const LABEL_PX = 12;

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

/** The box around every vertex of the rings given (vertex indices into `vertices`). */
function ringsBox(vertices, rings) {
  let west = Infinity; let east = -Infinity; let south = Infinity; let north = -Infinity;
  for (const ring of rings) {
    for (const i of ring) {
      const [x, y] = vertices[i];
      west = Math.min(west, x); east = Math.max(east, x); south = Math.min(south, y); north = Math.max(north, y);
    }
  }
  return { west, south, east, north };
}

/** The keys of `key` and every region under it in the world's tree. */
function regionSubtree(regions, key) {
  const out = new Set([key]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const r of regions) if (r.parent !== null && out.has(r.parent) && !out.has(r.key)) { out.add(r.key); grew = true; }
  }
  return out;
}

/**
 * Each region's fixed frame, by key, worked out from its areas' shapes alone: the box around
 * every area in the region or a region under it. A region with no area has none. The whole
 * map's frame, under `''`, is the map's own box.
 */
export function regionFrames(map, shapes) {
  const frames = new Map([['', boxOf(map.box ?? shapes.box)]]);
  for (const r of map.regions ?? []) {
    const within = regionSubtree(map.regions, r.key);
    const rings = (map.areas ?? []).filter((a) => within.has(a.region) && shapes.areas[a.key])
      .flatMap((a) => shapes.areas[a.key].rings);
    if (rings.length) frames.set(r.key, ringsBox(shapes.vertices, rings));
  }
  return frames;
}

/** The regions from the top down to `key` (empty for the whole map). */
export function regionTrail(regions, key) {
  const by = new Map((regions ?? []).map((r) => [r.key, r]));
  const out = [];
  for (let r = by.get(key); r && !out.includes(r); r = by.get(r.parent)) out.unshift(r);
  return out;
}

/** The regions directly under `key` (`''` or null: the top regions), in the world's order. */
export const regionChildren = (regions, key) => (regions ?? []).filter((r) => (r.parent ?? '') === (key ?? ''));

/** A frame (a box in map coordinates) as a rectangle in the projection's units. */
export function frameRect(frame, proj) {
  const x0 = proj.x(frame.west); const x1 = proj.x(frame.east);
  const y0 = proj.y(frame.north); const y1 = proj.y(frame.south);
  return { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) };
}

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

/**
 * The labels to hide: `labels` ([{ key, x, y, text }], at their label points in the drawing's
 * units) are taken in order, and one whose box, at LABEL_PX for `k` units a pixel, would
 * overlap a label already kept is hidden. A Set of keys.
 */
export function hiddenLabels(labels, k) {
  const kept = [];
  const hidden = new Set();
  for (const l of labels) {
    const w = (String(l.text).length * LABEL_PX * 0.6 + 4) * k;
    const h = LABEL_PX * 1.3 * k;
    const b = { x0: l.x - w / 2, x1: l.x + w / 2, y0: l.y - h / 2, y1: l.y + h / 2 };
    if (kept.some((o) => b.x0 < o.x1 && o.x0 < b.x1 && b.y0 < o.y1 && o.y0 < b.y1)) hidden.add(l.key);
    else kept.push(b);
  }
  return hidden;
}

/**
 * Every border of the map file, by the areas on each side: `[{ between: [a, b], edges }]`
 * with `b` null on the map's edge or where the backdrop lies; `a` sorts before `b`; each
 * edge is a pair of vertex indices. A shared edge is found once, from both of its areas.
 */
export function borders(shapes) {
  const users = new Map();
  for (const [key, area] of Object.entries(shapes.areas ?? {})) {
    for (const ring of area.rings) {
      for (let i = 1; i < ring.length; i += 1) {
        const [p, q] = [ring[i - 1], ring[i]];
        if (p === q) continue;
        const edge = p < q ? `${p} ${q}` : `${q} ${p}`;
        users.set(edge, [...(users.get(edge) ?? []).filter((u) => u !== key), key]);
      }
    }
  }
  const by = new Map();
  for (const [edge, keys] of users) {
    const [a, b = null] = [...keys].sort();
    const id = `${a} ${b ?? ''}`;
    if (!by.has(id)) by.set(id, { between: [a, b], edges: [] });
    by.get(id).edges.push(edge.split(' ').map(Number));
  }
  return [...by.values()].sort((x, y) => `${x.between}`.localeCompare(`${y.between}`));
}

// --- pieces on the territory map ---------------------------------------------------

/** The pips a piece's strength is drawn against when it has no more: the engine's default most. [proposed] */
export const PIP_SLOTS = 5;
/** How long a mark takes to slide to its new area, in milliseconds. [proposed] */
export const SLIDE_MS = 600;

const POSTURE = Object.freeze({ patrol: 'Patrol', escort: 'Escort', hold: 'Hold', attack: 'Attack', withdraw: 'Withdraw' });

/** A piece's posture as a word; '' when it has none. */
export const postureWord = (posture) => (posture ? pick(POSTURE, posture) : '');

/** An own piece's strength as pips: `filled` solid ones of `slots`; null for an envoy, which has none. */
export function pipsOf(piece) {
  if (!piece || piece.domain === 'envoy') return null;
  const filled = Math.max(0, Math.floor(Number(piece.strength) || 0));
  return { filled, slots: Math.max(PIP_SLOTS, filled) };
}

/** What a mark is keyed by from one render to the next: its piece's key, else its own. */
export const markKey = (m) => m.piece?.key ?? m.key;

/** Where a mark stands, for sliding: its piece's area, else its place. */
export const markArea = (m) => m.piece?.area?.key ?? m.piece?.area?.name ?? m.places?.[0]?.name ?? null;

/**
 * Note in `memory` (a Map) that the mark keyed `key` stands in `area` at point `xy`, and give
 * the point it should slide from: where it last stood when its area has changed since, else null.
 */
export function slideFrom(memory, key, area, xy) {
  const was = memory.get(key);
  memory.set(key, { area, xy });
  return was && was.area !== area ? was.xy : null;
}

/** An order still with its holder, as the ghost says it: "with Stavka to 16 Oct". */
export function waitWords(wait) {
  const who = wait.with_person ? `with ${wait.with_person}` : 'the order is moving';
  return wait.until ? `${who} to ${shortDate(wait.until)}` : who;
}

/** A piece under way, in words: the step it is on, then the rest of its path. */
export function courseLine(course) {
  const [step, ...rest] = course.path;
  if (!step) return '';
  const due = course.step_due ? `, in ${shortDate(course.step_due)}` : '';
  const then = rest.length ? `; then ${rest.map((a) => a.name).join(', ')}` : '';
  const arrives = course.arrives && rest.length ? `; arrives ${shortDate(course.arrives)}` : '';
  return `Under way: on the step into ${step.name}${due}${then}${arrives}`;
}

// --- holders and the front line ----------------------------------------------------

/** How a holder stands to the seat, in a word; the same words the tint's pattern stands for. */
const HOLDER_RELATION = Object.freeze({ own: 'yours', ally: 'ally', enemy: 'enemy', neutral: 'neutral' });

/** A holder's relation key (own, ally, enemy, neutral) for an area; null when nobody holds it. */
export const holderRelation = (area) => (area?.holder ? area.holder.relation : null);

/** "Norra (yours)", or "Sudland (enemy)"; "No holder" for an area nobody holds (a sea zone too). */
export function holderWords(area) {
  if (!area?.holder) return 'No holder';
  return `${area.holder.name} (${pick(HOLDER_RELATION, area.holder.relation)})`;
}

/**
 * Whether two holders are at war, as the seat's payload says it: a nation at war with the
 * seat's own is an enemy, and an ally is at war with a common enemy. Two of the same
 * standing, or a neutral, are not known to be at war.
 */
export function holdersAtWar(a, b) {
  const [x, y] = [holderRelation(a), holderRelation(b)];
  if (x === null || y === null) return false;
  return (x === 'enemy' && (y === 'own' || y === 'ally')) || (y === 'enemy' && (x === 'own' || x === 'ally'));
}

/** Whether the border between land areas `a` and `b` (objects of the map block) is a front. */
export const isFront = (a, b) => a?.kind === 'land' && b?.kind === 'land' && holdersAtWar(a, b);

/** "Changed hands 12 Oct, taken from Sudland"; '' for an area that never changed hands. */
export function changedLine(area) {
  if (!area?.held_since) return '';
  const from = area.taken_from ? `, taken from ${area.taken_from.name}` : '';
  return `Changed hands ${shortDate(area.held_since)}${from}`;
}

/** The line for a capital marked to fall; '' for an area that carries none. */
export function fallingLine(area) {
  if (!area?.falling) return '';
  return `Capital marked to fall: it falls at the close of the wake after ${shortDate(area.falling)}`;
}

/** Printed yields as words, "grain 10, levies 2000"; "None printed" for none. */
export function yieldsLine(yields) {
  const rows = Object.entries(yields ?? {});
  if (!rows.length) return 'None printed';
  return rows.map(([key, amount]) => `${key.replace(/_/g, ' ')} ${Number.isInteger(amount) ? amount : Number(amount.toFixed(2))}`).join(', ');
}

/** "On the front with The Sudland Coast": the land neighbours of `area` held by a nation at war with its holder; '' for none. */
export function frontLine(area, areas) {
  const by = new Map((areas ?? []).map((a) => [a.key, a]));
  const foes = (area.neighbours ?? []).map((k) => by.get(k)).filter((n) => n && isFront(area, n));
  return foes.length ? `On the front with ${foes.map((n) => n.name).join(', ')}` : '';
}

// --- pick up and put down -----------------------------------------------------------

/** `iso` (a world date) `n` days on. */
export function addDays(iso, n) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/**
 * The form that moves the seat's own piece `mark` on a territory map: the first whose force
 * list names it (as `formsMoving` matches a name) and that has a destination. `{ lever, force }`,
 * or null for a foreign mark or one no form moves.
 */
export function pieceForm(levers, mark) {
  if (mark?.side !== 'own' || !mark.piece) return null;
  for (const lever of levers ?? []) {
    const param = lever.params.find((p) => p.name === 'force' && p.kind === 'enum');
    if (!param || !lever.params.some((p) => p.name === 'to')) continue;
    const named = param.choices.find((c) => c.label === mark.name)
      ?? param.choices.find((c) => {
        const words = choiceName(c.label);
        return mark.name === words || mark.name.endsWith(` ${words}`);
      });
    if (named) return { lever, force: named.value };
  }
  return null;
}

/**
 * Where `lever` can send `force`, by area key: each `to` choice under the area its `areas` entry
 * names for that force (a place's area), else under its own value (an area key). The first choice
 * in the form's order wins an area; `place` is its label when it is a place, `count` how many
 * choices lie in that area.
 */
export function formDestinations(lever, force) {
  const to = lever.params.find((p) => p.name === 'to');
  const areas = to?.areas?.[force] ?? {};
  const out = new Map();
  for (const c of to?.choices ?? []) {
    const area = areas[c.value] ?? c.value;
    const seen = out.get(area);
    if (seen) seen.count += 1;
    else out.set(area, { value: c.value, place: area === c.value ? null : c.label, count: 1 });
  }
  return out;
}

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
 * The day a move arrives: `today`, then the days the order's court path states (`steps`), then
 * the move's own `days`. `{ on, earliest }`: earliest when a step states no time or the path is
 * not known, so the day is the soonest it can be.
 */
export function arrival(today, steps, days) {
  const stated = (steps ?? []).reduce((n, s) => n + (Number.isFinite(s.days) ? s.days : 0), 0);
  const earliest = !steps || steps.some((s) => !Number.isFinite(s.days));
  return { on: addDays(today, stated + days), earliest };
}

/** Each nation the seat's data names with its standing to the seat (own, ally, enemy, neutral), by name. */
export function standings(rv) {
  const out = new Map();
  for (const f of rv?.economy?.figures ?? []) if (f.nation?.name) out.set(f.nation.name, f.nation.relation);
  for (const a of rv?.map?.areas ?? []) if (a.holder?.name) out.set(a.holder.name, a.holder.relation);
  return out;
}

/** The marks the seat has a report of, of a nation its data names as an enemy, standing in area `key`. */
export function reportedEnemies(map, shapes, key, standing) {
  return (map.marks ?? []).filter((m) => m.side === 'other' && standing.get(m.side_name) === 'enemy'
    && m.places?.length === 1 && inArea(shapes, key, [m.places[0].lon, m.places[0].lat]));
}

// --- reports on the map (RPC) ------------------------------------------------------------
// Every helper here reads only the fields a report is sent with: a wrong report is sent as a
// right one, and so reads as one.

/** Whole days from world date `seen` to world date `today`; 0 when either is missing. */
export function reportAge(seen, today) {
  if (!seen || !today) return 0;
  const day = (iso) => { const [y, m, d] = iso.split('-').map(Number); return Date.UTC(y, m - 1, d); };
  return Math.max(0, Math.round((day(today) - day(seen)) / 86400000));
}

/** The age badge: "now" on the day seen, else "9d". */
export const reportAgeWord = (days) => (days === 0 ? 'now' : `${days}d`);

/** The age in words: "today", "1 day ago", "9 days ago". */
export const reportAgoWords = (days) => (days === 0 ? 'today' : days === 1 ? '1 day ago' : `${days} days ago`);

/** A report fades as it ages: 0 fresh, 1 from FADE_DAYS[0] days, 2 from FADE_DAYS[1]. [proposed] */
export const FADE_DAYS = Object.freeze([5, 9]);
export const reportFade = (days) => (days >= FADE_DAYS[1] ? 2 : days >= FADE_DAYS[0] ? 1 : 0);

/** A report's range as pips: solid to the low end, hollow to the high end; null when it gives no strength. */
export function rangePips(r) {
  if (!Number.isInteger(r?.strength_low) || !Number.isInteger(r?.strength_high)) return null;
  const filled = Math.max(0, r.strength_low);
  return { filled, slots: Math.max(filled, r.strength_high) };
}

/** A report's range in words: "strength 2 to 3", "strength 4", "strength not given". */
export function rangeWords(r) {
  const p = rangePips(r);
  if (!p) return 'strength not given';
  return p.filled === p.slots ? `strength ${p.filled}` : `strength ${p.filled} to ${p.slots}`;
}

const CONFIDENCE = Object.freeze({ A: 'confirmed', B: 'probable', C: 'possible' });
const SOURCE = Object.freeze({ contact: 'Contact', air: 'Air search', patrol: 'Patrol', codebreaking: 'Codebreaking', agent: 'Agent' });

/** The confidence letter as the papers word it. */
export const confidenceWord = (c) => pick(CONFIDENCE, c);
/** The source as a word. */
export const sourceWord = (s) => pick(SOURCE, s);

/** What a report says it is: its kind as the world names it, else "Unknown piece". */
export const reportWhat = (r) => (r.kind && r.kind_name && r.kind_name !== 'unknown' ? r.kind_name : 'Unknown piece');

/** Where a report puts the piece, in words: its area, or the region a decrypt says it is bound for. */
export function reportWhere(r, regions) {
  if (r.area) return `in ${r.area.name}`;
  if (r.bound_for) return `bound for ${regions?.get?.(r.bound_for) ?? r.bound_for}`;
  return 'place not given';
}

/** Who reported it: "by Brann Hollis (Air search)", or the source alone for a contact no one is named for. */
export const reportWho = (r) => (r.person ? `by ${r.person} (${sourceWord(r.source)})` : `from ${sourceWord(r.source).toLowerCase()}`);

/** The whole report in one line, for its mark's label. */
export function reportMarkLine(r, today, regions) {
  const age = reportAge(r.seen, today);
  return `Report: ${reportWhat(r)}, ${rangeWords(r)}, ${reportWhere(r, regions)}, seen ${shortDate(r.seen)}, ${reportAgoWords(age)}, `
    + `${reportWho(r)}, ${confidenceWord(r.confidence)}`;
}

/** A ring in words: "could be in 3 areas: A, B, C"; '' for a report with none. */
export function ringWords(r, names) {
  if (!r.ring?.length) return '';
  const n = r.ring.length;
  return `could be in ${n === 1 ? '1 area' : `${n} areas`}: ${r.ring.map((k) => names.get(k) ?? k).join(', ')}`;
}

/**
 * The outline of the areas `keys` in `shapes`: every border edge with one of those areas on one
 * side and none on the other (the map's edge counts as none). Pairs of vertex indices.
 */
export function ringEdges(keys, shapes) {
  const inRing = new Set(keys);
  const out = [];
  for (const { between: [a, b], edges } of borders(shapes)) {
    if (inRing.has(a) !== (b !== null && inRing.has(b))) out.push(...edges);
  }
  return out;
}

/** The glyph a report draws with: the domain of the seat's own pieces of its kind, by the kind's name; else unknown. */
export function reportGlyph(r, marks) {
  if (!r.kind) return 'unknown';
  const own = (marks ?? []).find((m) => m.side === 'own' && m.piece?.kind === r.kind_name);
  return { land: 'army', sea: 'fleet', air: 'air' }[own?.piece?.domain] ?? 'unknown';
}

/** The seat's form for intelligence order `kind`: the first lever whose rule is `intel` and whose order kind is `kind`. */
export const intelForm = (levers, kind) => (levers ?? []).find((l) => l.rule === 'intel' && l.intel === kind) ?? null;

/** The choice of a form's `name` parameter that names map mark `mark`, as `pieceForm` matches a name; null when none. */
export function choiceFor(lever, name, mark) {
  const param = lever?.params?.find((p) => p.name === name);
  if (!param || !mark) return null;
  return param.choices.find((c) => c.label === mark.name)
    ?? param.choices.find((c) => { const w = choiceName(c.label); return mark.name === w || mark.name.endsWith(` ${w}`); })
    ?? null;
}
