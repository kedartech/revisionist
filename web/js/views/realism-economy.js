// The war economy on screen (ECO): one figure per nation in the top strip; a tap on the
// seat's own opens a sheet of its components under the world's own resource names (income,
// pools, months of fuel, the territories that pay less than they print, with why); a tap on
// another nation's gives its figure and says it is read from the map; the economy layer of the
// territory map draws each territory's printed yields as pips, with the numbers on a tap.
// Another nation's components are never drawn: the server does not send them. No resource is
// named here: names, units and roles come from the seat's own `economy.own.income`.
// Nothing here touches the page on import.

import { h, svg } from '../dom.js';
import { codebreakingBlock } from './realism-reports.js';

const num = (n) => (Number.isInteger(n) ? String(n) : String(Number(Number(n).toFixed(2))));
const rel = (n) => n?.relation;

/** "Grain 10 tons" from an income row. */
const incomeLine = (r) => `${r.name} ${num(r.amount)}${r.unit ? ` ${r.unit}` : ''}`;

/** The world's names of the resources that have `role`, in the world's order: "Grain, Iron". */
function namesOf(income, role) {
  return (income ?? []).filter((r) => r.role === role).map((r) => r.name).join(', ');
}

const shortDay = (iso) => {
  const d = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', timeZone: 'UTC' });
};

/**
 * Why a territory pays less than it prints, in words, from what the seat is sent: the share
 * of each role it pays (`factors`), what it yields now against what the board prints, and the
 * map's own held-since line. `[]` for a territory that pays all it prints.
 */
export function shortfalls(own, printedByArea, areaByKey) {
  const roleOf = new Map((own?.income ?? []).map((r) => [r.key, r]));
  const out = [];
  for (const t of own?.territories ?? []) {
    const printed = printedByArea.get(t.area) ?? {};
    const a = areaByKey.get(t.area);
    const since = a?.held_since ? `, taken ${shortDay(a.held_since)}${a.taken_from ? ` from ${a.taken_from.name}` : ''}` : '';
    const lines = [];
    const keys = new Set([...Object.keys(printed), ...Object.keys(t.yields ?? {})]);
    for (const key of [...keys].sort()) {
      const res = roleOf.get(key);
      if (!res) continue;
      const want = Number(printed[key] ?? 0);
      const now = Number(t.yields?.[key] ?? 0);
      const share = Number(t.factors?.[res.role] ?? 1);
      const paid = now * share;
      if (paid >= want - 1e-9) continue;
      let why;
      if (now < want && share >= 1) why = 'its industry has moved, so it yields less than printed';
      else if (res.role === 'supply' && share < 1) why = `its links to you are not joined yet${since}`;
      else if (share <= 0) why = `it pays nothing yet${since}`;
      else why = `only ${num(Math.round(share * 100))} in 100 of it reaches you${since}`;
      lines.push({ resource: res.name, paid, want, why });
    }
    if (lines.length) out.push({ area: t.area, name: t.name, lines });
  }
  return out;
}

/** The stock mark's cells: one per month the stock lasts, up to a year. */
const STOCK_CELLS = 12;

let folded = false;

/** Whether the seat's own sheet keeps its components behind "More" (Beginner's room); set at each draw of the room. */
export function foldEconomy(on) { folded = Boolean(on); }

/** The seat's own sheet: components under the world's names. `map` is the seat's map block. */
export function ownSheet(economy, map, { levers, act } = {}) {
  const own = economy.own;
  const income = own.income ?? [];
  const areas = new Map((map?.areas ?? []).map((a) => [a.key, a]));
  const printed = new Map((map?.areas ?? []).map((a) => [a.key, a.yields ?? {}]));
  const less = shortfalls(own, printed, areas);
  const pools = [['output', own.pools?.output], ['manpower', own.pools?.manpower]]
    .filter(([, v]) => v !== undefined)
    .map(([role, v]) => h('li', { 'data-pool': role }, `${namesOf(income, role) || role}: ${num(v)} in the pool`));
  const fuel = namesOf(income, 'fuel');
  const fuelLine = own.fuel_months === null || own.fuel_months === undefined
    ? `${fuel || 'Fuel'}: no stock is kept in this game`
    : `${fuel || 'Fuel'} lasts ${num(own.fuel_months)} months at this income`;
  const stock = own.pools?.fuel;
  const filled = Math.ceil(Math.min(Math.max(Number(own.fuel_months) || 0, 0), STOCK_CELLS));
  const stockMark = stock === undefined ? null : h('span', { class: 'rl-eco-stock' },
    `${fuel || 'Fuel'} stock ${num(stock)}`,
    h('span', { class: 'rl-eco-stockbar', 'aria-hidden': 'true' },
      Array.from({ length: STOCK_CELLS }, (_, i) => h('i', { 'data-on': String(i < filled) }))));
  const parts = [
    h('h4', {}, 'Income'),
    h('ul', { class: 'rl-eco-income' }, income.map((r) => h('li', { 'data-resource': r.key }, incomeLine(r)))),
    h('h4', {}, 'Pools'),
    h('ul', { class: 'rl-eco-pools' }, pools),
    h('div', { class: 'rl-eco-fuelrow' }, stockMark, h('p', { class: 'rl-eco-fuel' }, fuelLine)),
    h('h4', {}, 'Territories that pay less than they print'),
    less.length
      ? h('ul', { class: 'rl-eco-less' }, less.map((t) => h('li', { 'data-area': t.area },
        h('strong', {}, t.name),
        t.lines.map((l) => h('span', { class: 'rl-eco-why' }, ` ${l.resource}: pays ${num(l.paid)} of ${num(l.want)} printed, because ${l.why}.`)))))
      : h('p', { class: 'muted rl-eco-none' }, 'Every territory you hold pays what it prints.'),
  ];
  const components = folded ? h('details', { class: 'rl-eco-more' }, h('summary', {}, 'More'), parts) : parts;
  return h('section', { class: 'rl-eco-sheet', 'aria-label': `${own.nation.name}: the war economy`, 'data-nation': own.nation.key },
    h('h3', {}, `${own.nation.name}: your war economy`),
    h('p', { class: 'muted' }, `Counted for ${economy.day}.`),
    components,
    codebreakingBlock(levers, act));
}

/** Another nation's sheet: its figure, and that it is read from the map. */
export function otherSheet(figure) {
  return h('section', { class: 'rl-eco-sheet rl-eco-other', 'aria-label': `${figure.nation.name}: war economy`, 'data-nation': figure.nation.key },
    h('h3', {}, figure.nation.name),
    h('p', { class: 'rl-eco-figure' }, `War-economy figure ${num(figure.figure)}`),
    h('p', { class: 'muted' }, 'Read from the map: what it holds, at what the board prints. You see no more of it.'));
}

/**
 * The strip's chips and the sheet under them: `economyStrip(rv)`. One button per nation, the
 * seat's own marked; a tap opens that nation's sheet below, a second tap closes it. `null`
 * when the game keeps no economy.
 */
export function economyStrip(rv, { act } = {}) {
  const economy = rv.economy;
  if (!economy?.figures?.length) return null;
  let open = null;
  const sheet = h('div', { class: 'rl-eco-slot' });
  const chips = h('div', { class: 'rl-eco-chips', role: 'group', 'aria-label': 'War economy by nation' });
  const draw = () => {
    chips.replaceChildren(...economy.figures.map((f) => h('button', {
      type: 'button', class: `rl-eco-chip rl-eco-${rel(f.nation) ?? 'neutral'}`, 'aria-expanded': String(open === f.nation.key),
      'data-nation': f.nation.key, onclick: () => { open = open === f.nation.key ? null : f.nation.key; draw(); },
    }, h('span', { class: 'rl-eco-name' }, rel(f.nation) === 'own' ? `${f.nation.name} (yours)` : f.nation.name),
    ' ', h('span', { class: 'rl-eco-num' }, num(f.figure)))));
    const f = economy.figures.find((x) => x.nation.key === open);
    if (!f) sheet.replaceChildren();
    else sheet.replaceChildren(rel(f.nation) === 'own' && economy.own ? ownSheet(economy, rv.map, { levers: rv.desk?.levers, act }) : otherSheet(f));
  };
  draw();
  return h('div', { class: 'rl-eco' }, chips, sheet);
}

/** What a territory's printed yields say, "grain 10, levies 2000": numbers, for a tap. */
const yieldWords = (yields) => Object.entries(yields).map(([k, v]) => `${k.replace(/_/g, ' ')} ${num(v)}`).join(', ');

/** Whether the board prints a yield on any land territory: the economy layer is worth offering. */
export const hasYields = (map) => (map?.areas ?? []).some((a) => a.kind === 'land' && Object.keys(a.yields ?? {}).length);

/**
 * The economy layer: for each land territory that prints yields, one pip per resource (one to
 * three, by how large the yield is against the largest of that resource on the board), coloured
 * by the resource's place in the board's own sorted list: no resource is named. The numbers are
 * not drawn: a tap on a territory's pips adds them as text and a second tap removes them. The
 * pips carry the numbers in their name for a screen reader. `place(attrs, x, y, ...children)`
 * draws a group in pixels at a point; `labelAt` maps area key to [x, y].
 */
export function economyPips(areas, labelAt, place) {
  const land = areas.filter((a) => a.kind === 'land' && Object.keys(a.yields ?? {}).length);
  const keys = [...new Set(land.flatMap((a) => Object.keys(a.yields)))].sort();
  const top = new Map(keys.map((k) => [k, Math.max(...land.map((a) => Number(a.yields[k] ?? 0)))]));
  return land.map((a) => {
    const [x, y] = labelAt.get(a.key);
    const entries = Object.entries(a.yields).filter(([, v]) => v > 0).sort(([p], [q]) => (p < q ? -1 : 1));
    const words = `${a.name}: ${yieldWords(a.yields)}`;
    let note = null;
    const g = place({
      class: 'rl-eco-pips', 'data-area': a.key, role: 'button', tabindex: 0, 'aria-label': words,
    }, x, y);
    const tap = () => {
      if (note) { note.remove(); note = null; return; }
      note = svg('text', { class: 'rl-eco-note', y: 66, 'text-anchor': 'middle', 'font-size': 12 }, yieldWords(a.yields));
      g.append(note);
    };
    g.addEventListener('click', tap);
    g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); tap(); } });
    entries.forEach(([key, v], i) => {
      const n = Math.min(3, Math.max(1, Math.ceil((3 * v) / (top.get(key) || 1))));
      const cx = (i - (entries.length - 1) / 2) * 16;
      for (let p = 0; p < n; p += 1) {
        g.append(svg('circle', {
          class: `rl-eco-pip rl-eco-r${keys.indexOf(key) % 5}`, 'data-resource': key, cx, cy: 46 - p * 9, r: 4,
        }));
      }
    });
    return g;
  });
}
