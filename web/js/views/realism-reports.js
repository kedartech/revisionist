// Reports on the map (RPC): each report of an enemy piece the seat's nation holds, drawn from
// the `reports` block of the seat's map and nothing else, so a wrong report draws exactly like a
// right one. A report is a mark: its kind's glyph (or an unknown one), its range as pips (solid
// to the low end, hollow to the high end) and an age badge; it fades as it ages. A picked report
// opens its sheet and, when it carries a ring, draws the ring's outline; the threats switch draws
// every ring faintly and marks the seat's own areas the server names in reach. The intelligence
// orders are placed like pieces (a recon or agent token on an area), or switched on a piece's
// sheet (concealment) or the economy sheet (codebreaking); each files its form. List mode has a
// twin for every report and ring. Nothing here touches the page on import.

import { h, svg } from '../dom.js';
import {
  LABEL_PX, MIN_MARK_PX, MIN_TAP_PX, choiceFor, confidenceWord, intelForm, rangePips, rangeWords, reportAge, reportAgeWord,
  reportAgoWords, reportFade, reportGlyph, reportMarkLine, reportWhat, reportWhere, ringEdges, ringWords, shortDate, sourceWord,
} from '../realism-rules.js';
import { forceGlyph, markSwatch, pictureOf, pipGlyph } from './realism-map.js';
import { reportHead } from './realism-piece.js';

/** How far below its area's label point a report is drawn, and the gap between reports side by side, in pixels. [proposed] */
const REPORT_DROP = 34;
const REPORT_GAP = 44;

const r2 = (n) => Math.round(n * 100) / 100;

/** The map's regions by key, to name the region a decrypt gives. */
export const regionNames = (map) => new Map((map.regions ?? []).map((r) => [r.key, r.name]));

/** The map's areas' names by key. */
const areaNames = (map) => new Map((map.areas ?? []).map((a) => [a.key, a.name]));

/** The reports of a map block; none in a game without them. */
export const reportsOf = (map) => map?.reports ?? [];

/** The report keyed `key`, or null when the data no longer holds it. */
export const reportByKey = (map, key) => (key ? reportsOf(map).find((r) => r.key === key) ?? null : null);

/** The middle of a region's areas' label points, for a decrypt that names only a region; null for a region with none drawn. */
function regionAt(map, key, labelAt) {
  const under = new Set([key]);
  for (let grew = true; grew;) {
    grew = false;
    for (const r of map.regions ?? []) if (r.parent && under.has(r.parent) && !under.has(r.key)) { under.add(r.key); grew = true; }
  }
  const pts = (map.areas ?? []).filter((a) => under.has(a.region) && labelAt.has(a.key)).map((a) => labelAt.get(a.key));
  if (!pts.length) return null;
  return [r2(pts.reduce((s, p) => s + p[0], 0) / pts.length), r2(pts.reduce((s, p) => s + p[1], 0) / pts.length)];
}

/** A report as a mark: another's, as reported, with its domain's glyph and the picture the report carries. */
const reportMark = (r, glyph) => ({ side: 'other', kind: glyph === 'unknown' ? null : glyph, certainty: 'reported', picture: r.picture ?? null });

/** One report's marker, centred on (0, 0): the diamond with its glyph, its range as pips, its age badge. */
function reportBody(r, glyph, age, chosen) {
  const pips = rangePips(r);
  const pip = Math.max(MIN_MARK_PX / 4, 4);
  const below = MIN_MARK_PX / 2 + 6;
  const badge = reportAgeWord(age);
  const bw = 8 + badge.length * 7;
  return [
    svg('rect', { x: -MIN_TAP_PX / 2, y: -MIN_TAP_PX / 2, width: MIN_TAP_PX, height: MIN_TAP_PX, class: 'rl-tm-hit' }),
    chosen ? svg('circle', { r: MIN_MARK_PX * 0.95, class: 'rl-mk-ring' }) : null,
    forceGlyph(reportMark(r, glyph), MIN_MARK_PX),
    glyph === 'unknown' && !pictureOf(r) ? svg('text', { y: 4, 'text-anchor': 'middle', 'font-size': LABEL_PX, class: 'rl-rp-unknown' }, '?') : null,
    pips ? pipGlyph(pips, pip * 5, below) : null,
    svg('g', { class: 'rl-rp-age', transform: `translate(${r2(MIN_MARK_PX * 0.8)} ${r2(LABEL_PX * 0.3)})` },
      svg('rect', { x: 0, y: -LABEL_PX * 0.8, width: bw, height: LABEL_PX * 1.1, rx: 2, class: 'rl-rp-badge' }),
      svg('text', { x: r2(bw / 2), y: 0, 'text-anchor': 'middle', 'font-size': LABEL_PX * 0.85 }, badge)),
  ];
}

/**
 * Every report as a mark, under its area's label point (a decrypt at its region's middle),
 * side by side where several share an area. `ctx`: { map, labelAt, atPx, activate, opts }.
 */
export function reportMarks(ctx) {
  const { map, labelAt, atPx, activate, opts } = ctx;
  const regions = regionNames(map);
  const spots = new Map();
  for (const r of reportsOf(map)) {
    const where = r.area ? `a:${r.area.key}` : `r:${r.bound_for}`;
    const xy = r.area ? labelAt.get(r.area.key) : regionAt(map, r.bound_for, labelAt);
    if (!xy) continue;
    spots.set(where, { xy, here: [...(spots.get(where)?.here ?? []), r] });
  }
  const out = [];
  for (const { xy, here } of spots.values()) {
    here.forEach((r, i) => {
      const age = reportAge(r.seen, opts.today);
      const fade = reportFade(age);
      const glyph = reportGlyph(r, map.marks);
      const chosen = opts.report === r.key;
      const words = reportMarkLine(r, opts.today, regions);
      const dx = (i - (here.length - 1) / 2) * REPORT_GAP;
      const attrs = opts.still ? {} : { 'aria-label': words, 'aria-pressed': String(chosen), ...activate(() => opts.onReport?.(chosen ? null : r.key)) };
      out.push(atPx({
        class: `rl-rp-mark rl-side-other rl-rp-fade-${fade}${chosen ? ' selected' : ''}`, 'data-report': r.key, 'data-glyph': glyph,
        'data-fade': fade, 'data-area': r.area?.key ?? null, 'data-region': r.area ? null : r.bound_for, ...attrs,
      }, xy[0], xy[1], svg('g', { transform: `translate(${r2(dx)} ${REPORT_DROP})` }, reportBody(r, glyph, age, chosen)), svg('title', {}, words)));
    });
  }
  return out;
}

/** One report's ring as its outline over its areas; `faint` under the threats switch. */
function ringOutline(r, shapes, at, names, faint) {
  const d = ringEdges(r.ring, shapes).map(([p, q]) => `M${at(shapes.vertices[p]).join(' ')}L${at(shapes.vertices[q]).join(' ')}`).join('');
  return svg('g', {
    class: `rl-rp-ring${faint ? ' faint' : ''}`, role: 'img', 'data-report': r.key, 'data-areas': r.ring.join(' '),
    'aria-label': `${reportWhat(r)}: ${ringWords(r, names)}`,
  }, svg('path', { d, class: 'rl-rp-ring-line' }));
}

/**
 * The rings drawn: the picked report's, when it carries one; with the threats switch on, every
 * other report's faintly, and each of the seat's own areas the server names in reach of one
 * marked over its shape. `ctx`: { map, shapes, at, areaPath, opts }.
 */
export function ringsAndThreats(ctx) {
  const { map, shapes, at, areaPath, opts } = ctx;
  const names = areaNames(map);
  const reports = reportsOf(map).filter((r) => r.ring?.length);
  const picked = reports.find((r) => r.key === opts.report) ?? null;
  const out = [];
  if (opts.threats) {
    const byKey = new Map(reportsOf(map).map((r) => [r.key, r]));
    for (const a of map.areas ?? []) {
      const from = (a.threatened_from ?? []).map((k) => byKey.get(k)).filter(Boolean);
      if (!from.length || !shapes.areas?.[a.key]) continue;
      out.push(svg('path', {
        d: areaPath(a.key), class: 'rl-rp-threat', 'data-area': a.key, role: 'img',
        'aria-label': `${a.name}: in reach of ${from.map((r) => `${reportWhat(r)}, ${rangeWords(r)}`).join('; ')}`,
      }));
    }
    for (const r of reports) if (r !== picked) out.push(ringOutline(r, shapes, at, names, true));
  }
  if (picked) out.push(ringOutline(picked, shapes, at, names, false));
  return out;
}

/** The threats switch, for the Military layer of a map with reports: a pressed button. */
export function threatsSwitch(map, on, onThreats) {
  if (!reportsOf(map).length) return null;
  return h('button', {
    type: 'button', class: 'rl-filter rl-rp-threats', 'aria-pressed': String(Boolean(on)), onclick: () => onThreats?.(!on),
  }, 'Threats');
}

/** The report's sheet: what, range, where, seen and age, source, the person, confidence, ring and the paper. */
export function reportSheet(map, key, { today, onReport, onOpen } = {}) {
  const r = reportByKey(map, key);
  if (!r) return null;
  const age = reportAge(r.seen, today);
  const pips = rangePips(r);
  const ring = ringWords(r, areaNames(map));
  const where = reportWhere(r, regionNames(map));
  const rows = [
    ['What', reportWhat(r)],
    ['Strength', [pips ? svg('svg', { class: 'rl-rp-pips', viewBox: '-30 -2 60 10', width: 60, height: 10, 'aria-hidden': 'true' }, pipGlyph(pips, 30, 0)) : null, ` ${rangeWords(r)}`]],
    ['Where', where[0].toUpperCase() + where.slice(1)],
    ['Seen', `${shortDate(r.seen)}, ${reportAgoWords(age)}`],
    ['Source', sourceWord(r.source)],
    ['Reported by', r.person || 'No one named'],
    ['Confidence', confidenceWord(r.confidence).replace(/^./, (c) => c.toUpperCase())],
    ring ? ['Could be now', ring.replace(/^./, (c) => c.toUpperCase())] : null,
  ].filter(Boolean);
  return h('section', { class: 'rl-rp-sheet', 'aria-labelledby': 'rl-rp-sheet-h', 'data-report': r.key },
    h('h3', { id: 'rl-rp-sheet-h' }, `Report: ${reportWhat(r)}`),
    reportHead(r, today),
    h('dl', {}, rows.map(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])),
    h('p', { class: 'muted rl-rp-caveat' }, 'A report can be wrong. A wrong one looks exactly like a right one.'),
    r.document ? null : h('p', { class: 'muted' }, 'No paper: seen in contact by your own forces.'),
    h('div', { class: 'rl-rp-acts' },
      r.document ? h('button', { type: 'button', class: 'rl-btn', onclick: () => onOpen?.({ id: r.document }) }, 'Open the paper') : null,
      h('button', { type: 'button', class: 'rl-find', onclick: () => onReport?.(null) }, 'Close')));
}

/** List mode's twins: a row for every report, with its ring, and one for each own area in reach of one. */
export function reportTables(map, { today, onReport } = {}) {
  const reports = reportsOf(map);
  if (!reports.length) return null;
  const regions = regionNames(map);
  const names = areaNames(map);
  const byKey = new Map(reports.map((r) => [r.key, r]));
  const inReach = (map.areas ?? []).filter((a) => (a.threatened_from ?? []).some((k) => byKey.has(k)));
  const cap = (s) => s.replace(/^./, (c) => c.toUpperCase());
  return [
    h('table', { class: 'rl-map-list rl-rp-list' },
      h('caption', {}, 'Every report on your map'),
      h('thead', {}, h('tr', {}, ['Report', 'Strength', 'Where', 'Seen', 'Source', 'Reported by', 'Confidence', 'Ring', ''].map((c) => h('th', { scope: 'col' }, c)))),
      h('tbody', {}, reports.map((r) => h('tr', { 'data-report': r.key, class: `rl-rp-fade-${reportFade(reportAge(r.seen, today))}` },
        h('th', { scope: 'row' }, markSwatch(reportMark(r, reportGlyph(r, map.marks))), reportWhat(r)),
        h('td', {}, rangeWords(r)),
        h('td', {}, cap(reportWhere(r, regions))),
        h('td', {}, `${shortDate(r.seen)}, ${reportAgoWords(reportAge(r.seen, today))}`),
        h('td', {}, sourceWord(r.source)),
        h('td', {}, r.person || 'No one named'),
        h('td', {}, cap(confidenceWord(r.confidence))),
        h('td', {}, cap(ringWords(r, names)) || 'Where it was seen'),
        h('td', {}, h('button', { type: 'button', class: 'rl-find', onclick: () => onReport?.(r.key, 'map') }, 'Find on map')))))),
    inReach.length
      ? h('table', { class: 'rl-map-list rl-rp-threat-list' },
        h('caption', {}, 'Your areas in reach of a report'),
        h('thead', {}, h('tr', {}, ['Area', 'In reach of'].map((c) => h('th', { scope: 'col' }, c)))),
        h('tbody', {}, inReach.map((a) => h('tr', { 'data-area': a.key },
          h('th', { scope: 'row' }, a.name),
          h('td', {}, a.threatened_from.map((k) => byKey.get(k)).filter(Boolean)
            .map((r) => `${reportWhat(r)}, ${rangeWords(r)} (${reportWhere(r, regions)})`).join('; '))))))
      : null,
  ];
}

// --- the intelligence orders, placed like pieces ------------------------------------------

/**
 * The tokens the seat can put down: a recon token for each air piece the recon form lists and
 * the map holds, and an agent token when the agent form has areas. `[{ id, label, intel, lever, piece?, mark? }]`.
 */
export function intelTokens(rv) {
  const out = [];
  const recon = intelForm(rv.desk?.levers, 'recon');
  if (recon?.params.some((p) => p.name === 'area')) {
    for (const m of rv.map?.marks ?? []) {
      if (m.side !== 'own' || !m.piece?.moves?.length) continue;
      const c = choiceFor(recon, 'piece', m);
      if (c) out.push({ id: `recon:${c.value}`, label: `Recon with ${m.name}`, intel: 'recon', lever: recon, piece: c.value, mark: m });
    }
  }
  const agent = intelForm(rv.desk?.levers, 'agent');
  if (agent?.params.some((p) => p.name === 'area')) out.push({ id: 'agent', label: 'Place an agent', intel: 'agent', lever: agent });
  return out;
}

/**
 * Where token `t` may be put down, as lit areas at their label points in `shapes`: a recon
 * token on the wing's lit moves the form offers an area for, an agent token on any area the
 * form offers. `chosen` is the area it stands on.
 */
export function tokenTargets(t, shapes, chosen) {
  const offered = new Set(t.lever.params.find((p) => p.name === 'area')?.choices.map((c) => c.value) ?? []);
  const areas = t.intel === 'recon'
    ? t.mark.piece.moves.map((mv) => mv.area)
    : t.lever.params.find((p) => p.name === 'area').choices.map((c) => ({ key: c.value, name: c.label }));
  return areas.filter((a) => offered.has(a.key) && shapes.areas?.[a.key]).map((a) => {
    const [lon, lat] = shapes.areas[a.key].label;
    return {
      place: { name: a.name, lon, lat }, value: a.key, area: a.key, days: null, lift: null, chosen: chosen === a.key,
      words: t.intel === 'recon' ? `Recon over ${a.name} with ${t.mark.name}` : `Place an agent in ${a.name}`,
    };
  });
}

/** What token `t` put down on area `area` files: its form, with the order kind, the piece and the area. */
export function tokenOrder(t, area) {
  const intel = t.lever.params.find((p) => p.name === 'intel')?.choices[0]?.value ?? t.intel;
  return { lever: t.lever.name, params: { intel, ...(t.piece ? { piece: t.piece } : {}), area } };
}

/** The token picker: one button per token, pressed while it is picked up. */
export function tokenBar(tokens, picked, onToken) {
  if (!tokens.length) return null;
  return h('section', { class: 'rl-rp-tokens', 'aria-label': 'Intelligence orders to place' },
    h('h3', {}, 'Find out more'),
    h('div', { class: 'rl-filters', role: 'group' }, tokens.map((t) => h('button', {
      type: 'button', class: 'rl-filter rl-rp-token-pick', 'data-token': t.id, 'aria-pressed': String(picked === t.id),
      onclick: () => onToken?.(picked === t.id ? null : t.id),
    }, t.label))));
}

/** The token standing on its area, drawn like a piece put down: `atPx` places it. */
export function tokenMark(t, xy, atPx) {
  if (!xy) return null;
  return atPx({ class: `rl-rp-token rl-rp-token-${t.intel}`, 'data-area': t.at, role: 'img', 'aria-label': `${t.label}: put down` },
    xy[0], xy[1], svg('g', { transform: `translate(${-REPORT_GAP / 2} ${REPORT_DROP})` },
      svg('circle', { r: MIN_MARK_PX / 2, class: 'rl-rp-token-disc' }),
      t.intel === 'recon'
        ? svg('path', { d: 'M-5 1L0 -4L5 1M0 -4L0 5', class: 'rl-rp-token-glyph' })
        : svg('path', { d: 'M0 -5A3 3 0 1 1 0 1A3 3 0 1 1 0 -5M-5 6Q0 0 5 6', class: 'rl-rp-token-glyph' })));
}

/** The confirm chip for a token put down: what it files; Send it files the form, Back (or Escape) picks it up again. */
export function tokenChip(t, areaName, { send, back }) {
  const what = t.intel === 'recon'
    ? `Fly a reconnaissance flight over ${areaName} with ${t.mark.name}`
    : `Place an agent in ${areaName}`;
  const esc = { onkeyup: (e) => { if (e.key === 'Escape') { e.preventDefault(); back(); } } };
  return h('section', { class: 'rl-rp-chip rl-pup-chip', role: 'group', 'aria-label': what },
    h('h3', { class: 'rl-pup-h' }, what),
    h('p', { class: 'muted' }, `Files ${t.lever.label}. It is carried like any order and acts when it lands.`),
    h('div', { class: 'rl-pup-acts' },
      h('button', { type: 'button', class: 'primary', onclick: send, ...esc }, 'Send it'),
      h('button', { type: 'button', onclick: back, ...esc }, 'Back')));
}

/** Concealment on a piece's sheet: Conceal and Stop concealing, each filing the conceal form for that piece; null when the form does not list it. */
export function concealSwitch(levers, mark, act) {
  const form = intelForm(levers, 'conceal');
  const c = choiceFor(form, 'piece', mark);
  if (!c || !act) return null;
  const intel = form.params.find((p) => p.name === 'intel')?.choices[0]?.value ?? 'conceal';
  const file = (yes) => act(yes ? 'Concealing it…' : 'Ending its concealment…', 'lever',
    { lever: form.name, params: { intel, piece: c.value, concealed: yes ? 'yes' : 'no' } });
  return h('section', { class: 'rl-rp-conceal', 'aria-label': 'Concealment' },
    h('h4', {}, 'Concealment'),
    h('p', { class: 'muted' }, 'A concealed piece is harder for the other side to find. It is an order, and takes hold when it lands.'),
    h('div', { class: 'rl-filters', role: 'group' },
      h('button', { type: 'button', class: 'rl-filter', onclick: () => file(true) }, 'Conceal'),
      h('button', { type: 'button', class: 'rl-filter', onclick: () => file(false) }, 'Stop concealing')));
}

/** Codebreaking on the economy sheet: one button filing the codebreaking form; null without the form. */
export function codebreakingBlock(levers, act) {
  const form = intelForm(levers, 'codebreaking');
  if (!form || !act) return null;
  const intel = form.params.find((p) => p.name === 'intel')?.choices[0]?.value ?? 'codebreaking';
  return h('section', { class: 'rl-rp-codebreaking', 'aria-label': 'Codebreaking' },
    h('h4', {}, 'Codebreaking'),
    h('p', { class: 'muted' }, 'Codebreakers read the other side\'s signals: what they find comes as reports bound for a region.'),
    h('button', { type: 'button', class: 'rl-btn', onclick: () => act('Funding codebreaking…', 'lever', { lever: form.name, params: { intel } }) },
      'Fund codebreaking'));
}
