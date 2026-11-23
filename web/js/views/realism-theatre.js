// The Theatre board: the seat's map, drawn from its own papers (view.realism.map), filling the
// board. Each theatre is a labelled box around its places. A layer switch shows the forces
// (Military) or the capitals of the leaders set against the seat (Diplomatic). A picked force
// of the seat's shows the forms that can move it; a picked capital opens its leader's card.
// Nothing here touches the page on import.

import { api } from '../api.js';
import { h } from '../dom.js';
import {
  arrival, formDestinations, formsMoving, pieceForm, pipsOf, postureWord, reportedEnemies, shortDate, sightedLine, standings, waitWords,
} from '../realism-rules.js';
import { heldBy } from './realism-estimate.js';
import { figureCard } from './realism-figure.js';
import { daysLabel, liftLabel, liftNote, standardForm, tierLabel } from './realism-forms.js';
import { mapDrawing, mapView } from './realism-map.js';
import { battleMarksOf, battlePickOrder, battleSheet, battleTargets } from './realism-battle.js';
import { oddsAsker } from './realism-odds.js';
import { intelTokens, tokenBar, tokenChip, tokenOrder, tokenTargets } from './realism-reports.js';
import { territoryDrawing, territoryView } from './realism-territory.js';
import { formCheck, heldOn, isLocked, keptCheck, lockCheck, lockedChoice, locksOn } from './realism-locks.js';
import { diplomacyKey } from './realism-diplomacy.js';

const LAND_URL = '/assets/land-110m.json';
let coast = null;
let landing = null;

/** The coastlines, fetched once; until they arrive (or if they never do) the map has none. */
function loadLand() {
  if (coast || landing || typeof fetch !== 'function') return landing;
  landing = Promise.resolve()
    .then(() => fetch(LAND_URL))
    .then((r) => (r.ok ? r.json() : null))
    .then((json) => { if (Array.isArray(json?.rings)) coast = json; })
    .catch(() => {})
    .finally(() => { landing = null; });
  return landing;
}

// A territory game's shapes, by the map file's hash: fetched once per hash, kept for the page.
const shapesBy = new Map();
const asking = new Map();

/** The shapes for map file `file` ({ name, sha256 }), when they are here; null until then. */
export const shapesFor = (file) => shapesBy.get(file?.sha256) ?? null;

/**
 * Fetch the shapes for `file` once: a promise while one is out, null once they are here or
 * when there is no file. A refusal or a reply for another hash keeps none (the next draw asks
 * again); a reply that fails to arrive is asked for again on the next draw too.
 */
export function loadShapes(file, ask = api.map) {
  const hash = file?.sha256;
  if (!hash || shapesBy.has(hash)) return null;
  if (asking.has(hash)) return asking.get(hash);
  const out = Promise.resolve()
    .then(() => ask())
    .then((r) => { if (!r?.refused && r?.file?.sha256 === hash && r.map) shapesBy.set(hash, r.map); })
    .catch(() => {})
    .finally(() => asking.delete(hash));
  asking.set(hash, out);
  return out;
}

/** Forget every fetched shape (tests). */
export function forgetShapes() { shapesBy.clear(); asking.clear(); }

// the hooks each drawn theatre was handed by its room
const hooksOf = new WeakMap();

/** The room's hooks a drawn theatre view was given (`overlay`, `onFull`), or null for any other element. */
export const hooksFor = (view) => (view ? hooksOf.get(view) ?? null : null);

/**
 * What a pick on capital `c` opens: its leader's figure card from the People roster's line,
 * as the roster shows it; null when the roster holds no line for that leader.
 */
function capitalOpener(people) {
  return (c) => {
    const line = (people?.opponents ?? []).find((l) => l.name === c.name);
    if (!line) return null;
    return () => {
      const from = document.activeElement;
      const card = figureCard(line, 'opponents', {
        onClose: () => {
          card.remove();
          if (from?.isConnected) from.focus();
        },
      });
      document.body.append(card);
      card.showModal();
    };
  };
}

/**
 * The forms that can move a force of the seat's that the map holds, each open on that force:
 * a `<section class="rl-theatre-forms">`, or null for a foreign force or one no form moves.
 * `onPlaces(n, state)` is told form n's place picker state (`standardForm`).
 */
function movingForms(rv, piece, act, onPlaces) {
  if (piece?.kind !== 'force') return null;
  const mark = (rv.map?.marks ?? []).find((m) => m.name === piece.name);
  const forms = formsMoving(rv.desk?.levers, mark);
  if (!forms.length) return null;
  const items = forms.map(({ lever, force }, n) => {
    const item = standardForm(lever, {
      force, onSubmit: (v) => act?.('Sending it…', 'lever', v), entities: [], onPlaces: (s) => onPlaces(n, s),
      check: formCheck(rv), onAsk: (v) => act?.(ASKING, 'lever-ask', v),
    });
    item.querySelector('.rl-instrument-head [aria-expanded="false"]')?.click();
    return item;
  });
  return h('section', { class: 'rl-theatre-forms', 'aria-labelledby': 'rl-theatre-forms-h' },
    h('h3', { id: 'rl-theatre-forms-h' }, `Move ${mark.name}`),
    h('ul', { class: 'rl-instruments', role: 'list' }, items));
}

/**
 * The map's lit places for an open form's picker state: each place it offers that the map
 * holds, with its days (or "Out of reach") and its lift line for the form's force. `from`:
 * where the seat's latest page places the force, the start of a sea leg.
 */
function litPlaces(map, s, from) {
  const at = new Map(map.places.map((p) => [p.name, p]));
  return s.places.filter((p) => at.has(p.label)).map((p) => {
    const reach = s.force ? p.reach?.[s.force] ?? null : null;
    const refused = reach?.tier === 'refused';
    return {
      place: at.get(p.label),
      value: p.value,
      days: !s.force ? null : refused ? tierLabel(reach) : daysLabel(p.days?.[s.force] ?? null),
      lift: s.force ? liftNote(p.lift?.[s.force] ?? null) : null,
      liftWords: s.force ? liftLabel(p.lift?.[s.force] ?? null) : null,
      refused,
      chosen: s.value === p.value,
      from,
    };
  });
}

// --- pick up and put down: a piece, a lit area, the chip -------------------------------

/** The busy line while a locked order is filed and asked for. */
const ASKING = 'Filing it and asking…';

/** The order a picked piece's move files: the form, the force and the move's destination. */
export const moveOrder = (p, mv) => ({ lever: p.lever.name, params: { force: p.force, to: mv.to.value } });

/** The seat's own piece picked on a territory map, with the form that moves it; null when none. */
function pickedPiece(rv, ui) {
  if (ui.piece?.kind !== 'force') return null;
  return pieceMoves(rv, (rv.map?.marks ?? []).find((m) => m.name === ui.piece.name));
}

/** Mark `mark`'s moves on a territory map, with the form that moves it: `{ mark, lever, force, moves }`, or null. */
export function pieceMoves(rv, mark) {
  if (!mark || !Array.isArray(rv.map?.areas) || !rv.map.areas.length) return null;
  const form = pieceForm(rv.desk?.levers, mark);
  if (!form || !mark.piece?.moves?.length) return null;
  // a form may offer places: each lights the area it lies in for this force, and files the place
  const dest = formDestinations(form.lever, form.force);
  const moves = mark.piece.moves.filter((mv) => dest.has(mv.area.key)).map((mv) => ({ ...mv, to: dest.get(mv.area.key) }));
  return { mark, ...form, moves };
}

/** The lit areas of picked piece `p`, at their label points in `shapes`; a move the server's check locks carries who can allow it. */
function pieceTargets(rv, p, shapes, goal) {
  return p.moves.filter((mv) => shapes.areas?.[mv.area.key]).map((mv) => {
    const [lon, lat] = shapes.areas[mv.area.key].label;
    const c = keptCheck(rv, moveOrder(p, mv));
    return {
      place: { name: mv.area.name, lon, lat }, value: mv.area.key, area: mv.area.key,
      days: daysLabel(mv.days), lift: mv.lift ? 'Needs lift' : null, liftWords: mv.lift ? liftWords(mv.lift) : null,
      chosen: goal === mv.area.key, lock: isLocked(c) ? c.who : null,
    };
  });
}

/** The place the form files for a lit area, when the form offers places: the first of its places there. */
function placeLine(mv) {
  const to = mv.to;
  if (!to?.place) return null;
  const more = to.count > 1 ? `, the first of ${to.count} places the form offers in ${mv.area.name}` : '';
  return h('p', { class: 'rl-pup-place' }, `Filed as ${to.place}${more}`);
}

const liftWords = (lift) => `Lift: ${lift.tons.toLocaleString('en-US')} tons of ${lift.carrier}`;

/** Who carries the order first, and how many of the seat's orders they already hold. */
function carrierLines(path, court) {
  const first = path?.steps?.[0];
  if (!first) return [];
  const held = heldBy(first.person, court);
  const who = first.you ? 'You' : first.name;
  const verb = first.you ? 'hold' : 'holds';
  return [
    first.you ? 'Carried first by you' : `Carried first by ${first.name}${first.office ? `, ${first.office}` : ''}`,
    held ? `${who} already ${verb} ${held} of your orders` : `${who} ${verb} none of your orders`,
  ];
}

/** The seat's own piece beside each enemy its papers report in the area; the odds are behind the chip's Odds. */
function thereBlock(p, enemies) {
  if (!enemies.length) return null;
  const own = p.mark.piece;
  const pips = pipsOf(own);
  const yours = [`Yours: ${p.mark.name}`, pips ? `strength ${pips.filled}` : null, postureWord(own.posture) || null].filter(Boolean).join(', ');
  return h('div', { class: 'rl-pup-there' },
    h('p', { class: 'rl-pup-yours' }, yours),
    h('ul', { class: 'rl-pup-reports', role: 'list' }, enemies.map((m) => h('li', {},
      `Reported there: ${m.name} (${m.side_name}), ${m.strength === null || m.strength === undefined ? 'strength not reported' : `strength ${m.strength}`}; ${sightedLine(m)}`))));
}

/**
 * The confirm chip for picked piece `p` sent to `mv`: the days, the arrival day, the first
 * carrier and their load, the lift; a reported enemy there beside the seat's own piece. Send it
 * files the order; Odds opens the odds panel, which files nothing; Back (or Escape) closes it.
 */
function confirmChip(rv, p, mv, shapes, { send, ask, back }) {
  const path = rv.court?.paths?.find((c) => c.id === p.lever.pipeline) ?? null;
  const due = arrival(rv.clock.world_date, path?.steps ?? null, mv.days);
  const esc = { onkeyup: (e) => { if (e.key === 'Escape') { e.preventDefault(); back(); } } };
  // the odds of this move from the seat's own picture (ODC): asking and closing file nothing
  const odds = oddsAsker(rv, { force: p.force, to: mv.area.key }, { what: () => `${p.mark.name} into ${mv.area.name}` });
  const c = keptCheck(rv, moveOrder(p, mv));
  const locked = isLocked(c) ? c : null;
  return h('section', { class: 'rl-pup-chip', role: 'group', 'aria-label': `Send ${p.mark.name} to ${mv.area.name}` },
    h('h3', { class: 'rl-pup-h' }, `Send ${p.mark.name} to ${mv.area.name}`),
    h('p', { class: 'rl-pup-days' }, `${daysLabel(mv.days)} on the move: ${mv.path.map((a, i) => `${a.name}, ${daysLabel(mv.step_days[i])}`).join('; ')}`),
    h('p', { class: 'rl-pup-arrives' }, `Arrives ${shortDate(due.on)}${due.earliest ? ' at the earliest' : ''}`),
    placeLine(mv),
    carrierLines(path, rv.court).map((line) => h('p', { class: 'rl-pup-carrier' }, line)),
    h('p', { class: 'rl-pup-lift' }, mv.lift ? liftWords(mv.lift) : 'No lift needed'),
    thereBlock(p, reportedEnemies(rv.map, shapes, mv.area.key, standings(rv))),
    // a move the server's check locks: file it to be held, or ask, in place of Send it (LKM)
    locked ? lockedChoice(locked, { file: send, ask, esc }) : null,
    h('div', { class: 'rl-pup-acts' },
      locked ? null : h('button', { type: 'button', class: 'primary', onclick: send, ...esc }, 'Send it'),
      odds.button,
      h('button', { type: 'button', onclick: back, ...esc }, 'Back')),
    odds.box);
}

/** Each own order still with a holder, as the ghost's line: where it goes, and its holder. */
function waitingOrders(rv) {
  const sent = new Map((rv.orders?.orders ?? []).map((o) => [o.id, o]));
  const byKey = new Map((rv.map.areas ?? []).map((a) => [a.key, a]));
  const out = [];
  for (const m of rv.map.marks ?? []) {
    const wait = m.piece?.waiting;
    if (m.side !== 'own' || !wait) continue;
    const known = (rv.map.orders ?? []).find((o) => o.order === wait.order);
    const to = known?.to ?? byKey.get(sent.get(wait.order)?.params?.to) ?? null;
    out.push({ mark: m, wait, to, known: Boolean(known) });
  }
  return out;
}

/** The map block with a ghost's order for each waiting piece the block's orders leave out (an area goal). */
function withGhosts(map, waits) {
  const extra = waits.filter((w) => !w.known && w.to).map((w) => ({
    order: w.wait.order, force: w.mark.name, mark: w.mark.name, to: { name: w.to.name, lat: null, lon: null, theatre: null },
    status: 'awaiting', with_person: w.wait.with_person, filed: null,
  }));
  return extra.length ? { ...map, orders: [...(map.orders ?? []), ...extra] } : map;
}

/** The Withdraw button of each ghost whose order may still be withdrawn; null with none. */
function ghostList(waits, act) {
  const open = waits.filter((w) => w.wait.withdrawable);
  if (!open.length) return null;
  return h('section', { class: 'rl-pup-ghosts', 'aria-label': 'Orders you can still withdraw' },
    h('ul', { role: 'list' }, open.map((w) => h('li', { 'data-order': w.wait.order },
      h('span', {}, `${w.mark.name}${w.to ? ` to ${w.to.name}` : ''}: ${waitWords(w.wait)}`), ' ',
      h('button', {
        type: 'button', class: 'rl-pup-withdraw', 'aria-label': `Withdraw the order for ${w.mark.name}`,
        onclick: () => act?.(`Withdrawing the order for ${w.mark.name}…`, 'withdraw', { order_id: w.wait.order }),
      }, 'Withdraw')))));
}

/**
 * `theatreBoard(rv, ui, { pick, act, open })`: the map for the board's main area. A mark picked on
 * the map or found from the list is `pick({ piece: { kind: 'force', name } })`; the Map or
 * List, the scope and the layer switches are `pick({ theatre })`, and so are a picked report
 * (`theatre.report`), the threats switch (`theatre.threats`) and an intelligence token picked up
 * and put down (`theatre.token`, `theatre.tokenAt`), an open battle (`theatre.battle`) and a fall-back
 * area being picked for a battle or a standing order (`theatre.battlePick`). A report's paper, and a
 * battle known only from the press, opens with `open({ id })`.
 * The piece's details are in the board's side panel, so the map view's own detail block is left out.
 * `hooks` are the room's for the map, handed to the map's own options as they are: `overlay`
 * (true in the map-first room: the map draws its controls over itself) and `onFull(on)` (the map
 * asks the room for the whole viewport). `hooksFor(view)` reads them back from the drawn view.
 */
export function theatreBoard(rv, ui, { pick, act, open, hooks = {} } = {}) {
  const map = rv.map;
  if (!map) {
    return h('section', { class: 'rl-map rl-theatre' },
      h('h2', {}, 'Map'), h('p', { class: 'muted' }, 'No page has placed anything yet.'));
  }
  const theatre = ui.theatre ?? { mode: 'map', scope: 'reports' };
  // each moving form's place picker state; the lit places follow the form told last while open
  const states = new Map();
  let active = null;
  let redraw = () => {};
  const onPlaces = (n, s) => {
    states.set(n, s);
    if (s.open) active = n;
    else if (active === n) active = [...states].reverse().find(([, v]) => v.open)?.[0] ?? null;
    redraw();
  };
  const from = (map.marks ?? []).find((m) => ui.piece?.kind === 'force' && m.name === ui.piece.name)?.places?.[0] ?? null;
  const lit = () => (active === null ? [] : litPlaces(map, states.get(active), from));
  const forms = theatre.layer === 'diplomatic' ? null : movingForms(rv, ui.piece, act, onPlaces);
  const opts = {
    ...theatre,
    ...hooks,
    theatres: true,
    selected: ui.piece?.kind === 'force' ? ui.piece.name : null,
    openCapital: capitalOpener(rv.people),
    standings: rv.home?.standings ?? null, // a held territory's sheet shows its holder's band at home
    diplomacy: () => diplomacyKey(rv), // the Diplomatic layer's key, drawn under the map on that layer
    held: locksOn(rv) ? (m) => heldOn(rv, m) : null, // the seat's held orders on each of its pieces, as the server names them (LKM)
    onTarget: (value) => (battlePick ? putBattle(value) : token ? putDown(value) : piece ? choose(value) : states.get(active)?.choose(value)),
    onMode: (mode) => pick?.({ theatre: { ...theatre, mode } }),
    onScope: (scope) => pick?.({ theatre: { ...theatre, scope } }),
    onLayer: (layer) => pick?.({ theatre: { ...theatre, layer } }),
    onSelect: (name, mode) => pick?.({ piece: { kind: 'force', name }, ...(mode ? { theatre: { ...theatre, mode } } : {}) }),
    today: rv.clock?.world_date ?? null,
    onReport: (report, mode) => pick?.({ theatre: { ...theatre, report, ...(mode ? { mode } : {}) } }),
    onThreats: (threats) => pick?.({ theatre: { ...theatre, threats } }),
    onOpen: (p) => open?.(p),
    battles: battleMarksOf(rv),
    battle: theatre.battle ?? null,
    onBattle: (m) => (m.kind === 'news' ? open?.({ id: m.paper })
      : pick?.({ theatre: { ...theatre, battle: theatre.battle === m.area ? null : m.area, battlePick: null } })),
  };
  const territorial = Array.isArray(map.areas) && map.areas.length > 0;
  const waits = waitingOrders(rv);
  const drawn = territorial ? withGhosts(map, waits) : map;
  // a picked piece on a territory map lights its moves; the chosen one opens the chip
  // on the Diplomatic layer only an envoy is picked up and put down
  const picked = territorial ? pickedPiece(rv, ui) : null;
  const piece = theatre.layer === 'diplomatic' && picked?.mark.piece?.domain !== 'envoy' ? null : picked;
  // an intelligence token picked up lights where it may go down; put down, it opens its chip
  const tokens = territorial && theatre.layer !== 'diplomatic' && theatre.layer !== 'economy' ? intelTokens(rv) : [];
  const token = tokens.find((t) => t.id === theatre.token) ?? null;
  const tokenLit = () => (token && shapesFor(map.file) ? tokenTargets(token, shapesFor(map.file), theatre.tokenAt ?? null) : []);
  const tokenAt = token && tokenLit().some((t) => t.area === theatre.tokenAt) ? theatre.tokenAt : null;
  if (token) opts.token = tokenAt ? { ...token, at: tokenAt } : null;
  const putDown = (area) => pick?.({ theatre: { ...theatre, tokenAt: area } });
  // a fall-back area picked for a battle's withdrawal or a piece's standing order: its lit areas take the map
  const battlePick = territorial && theatre.layer !== 'diplomatic' && theatre.layer !== 'economy' ? theatre.battlePick ?? null : null;
  const battleLit = () => (battlePick ? battleTargets(rv, battlePick, shapesFor(map.file)) : []);
  const putBattle = (to) => {
    if (!battleLit().some((t) => t.area === to)) return;
    const [action, body] = battlePickOrder(battlePick, to);
    act?.('Sending it…', action, body, (r) => { if (!r?.refused && ui.theatre) ui.theatre.battlePick = null; });
  };
  let goal = piece?.moves.some((mv) => mv.area.key === theatre.goal) ? theatre.goal : null;
  const chipBox = h('div', { class: 'rl-pup' });
  const move = () => piece?.moves.find((mv) => mv.area.key === goal) ?? null;
  const route = () => (move() ? { from: piece.mark.piece.area?.key, steps: move().path.map((a, i) => ({ key: a.key, name: a.name, days: move().step_days[i] })) } : null);
  const setGoal = (key, focus) => {
    goal = key;
    if (ui.theatre) ui.theatre.goal = key;
    redraw();
    showChip();
    if (focus === 'chip') chipBox.querySelector('button')?.focus();
    else if (focus) Array.from(view.querySelectorAll('.rl-map-target')).find((t) => t.getAttribute('data-area') === focus)?.focus();
  };
  const showChip = () => {
    const shapes = shapesFor(map.file);
    if (token) {
      const at = tokenAt ? tokenLit().find((t) => t.area === tokenAt) : null;
      chipBox.replaceChildren(at ? tokenChip(token, at.place.name, {
        send: () => act?.('Sending it…', 'lever', tokenOrder(token, tokenAt),
          (r) => { if (!r?.refused && ui.theatre) { ui.theatre.token = null; ui.theatre.tokenAt = null; } }),
        back: () => putDown(null),
      }) : '');
      return;
    }
    const mv = move();
    const sent = (r) => { if (!r?.refused) { goal = null; if (ui.theatre) ui.theatre.goal = null; } };
    chipBox.replaceChildren(mv && shapes ? confirmChip(rv, piece, mv, shapes, {
      send: () => act?.('Sending it…', 'lever', moveOrder(piece, mv), sent),
      ask: () => act?.(ASKING, 'lever-ask', moveOrder(piece, mv), sent),
      back: () => setGoal(null, mv.area.key),
    }) : '');
  };
  // the server's check of each lit move, asked once for this data; choosing a move asks again
  // a lit move's lock is drawn when its answer differs from what is shown; the chip is rebuilt
  // with focus kept on its first button when focus was in it
  const rechip = () => {
    const inChip = Boolean(document.activeElement?.closest?.('.rl-pup-chip'));
    showChip();
    if (inChip) (chipBox.querySelector('.rl-lock-file') ?? chipBox.querySelector('button.primary') ?? chipBox.querySelector('button'))?.focus();
  };
  const checked = (changed) => { if (changed && view.isConnected) { redraw(); rechip(); } };
  const choose = (key) => {
    const mv = piece?.moves.find((m) => m.area.key === key);
    if (!mv) return;
    lockCheck(rv, moveOrder(piece, mv), (changed) => { if (changed && view.isConnected && goal === key) { redraw(); rechip(); } }, { fresh: true });
    setGoal(key, 'chip');
  };
  const targets = () => (battlePick ? battleLit() : token ? tokenLit() : piece && shapesFor(map.file) ? pieceTargets(rv, piece, shapesFor(map.file), goal) : lit());
  // the stack fanned out, by its area: the view's own, redrawn in place, focus kept on the stack
  let fanned = theatre.fanned ?? null;
  let fanFocus = null;
  if (territorial) {
    Object.assign(opts, {
      fanned,
      onFan: (key) => {
        fanFocus = key ?? fanned;
        fanned = key;
        opts.fanned = key;
        // kept on the room's own theatre state, so the next poll's drawing keeps the fan
        if (ui.theatre) ui.theatre.fanned = key;
        redraw();
      },
      onArea: (area) => (battlePick ? putBattle(area) : token && tokenLit().some((t) => t.area === area) ? putDown(area)
        : !token && piece?.moves.some((mv) => mv.area.key === area) ? choose(area) : pick?.({ theatre: { ...theatre, area } })),
      onFrame: (frame) => pick?.({ theatre: { ...theatre, frame, zoom: 1, centre: null } }),
      onView: ({ zoom, centre }) => pick?.({ theatre: { ...theatre, zoom, centre } }),
    });
  }
  const drawing = territorial
    ? () => (shapesFor(map.file) ? territoryDrawing(drawn, shapesFor(map.file), { ...opts, coast, targets: targets(), route: route() }) : h('p', { class: 'muted rl-tm-wait' }, 'Drawing the map…'))
    : () => mapDrawing(map, coast, { ...opts, scope: theatre.scope ?? 'reports', targets: lit() });
  const view = territorial
    ? territoryView(drawn, shapesFor(map.file), { ...opts, coast, targets: targets(), route: route() })
    : mapView(map, coast, { ...opts, targets: lit() });
  view.classList.add('rl-theatre');
  hooksOf.set(view, hooks);
  view.querySelector('.rl-map-detail')?.remove();
  const ghosts = ghostList(waits, act);
  const bar = tokenBar(tokens, token?.id ?? null, (id) => pick?.({ theatre: { ...theatre, token: id, tokenAt: null } }));
  const battle = territorial && theatre.battle ? battleSheet(rv, theatre.battle, {
    act, pick, theatre, onClose: () => pick?.({ theatre: { ...theatre, battle: null, battlePick: null } }),
  }) : null;
  const below = [forms, bar, chipBox, battle, ghosts].filter(Boolean);
  const fig0 = view.querySelector('figure.rl-map-figure');
  if (fig0) fig0.after(...below);
  else view.append(...below);
  if (piece && locksOn(rv)) for (const mv of piece.moves) lockCheck(rv, moveOrder(piece, mv), checked);
  showChip();
  redraw = () => {
    const fig = view.querySelector('figure.rl-map-figure');
    if (!fig) return;
    const was = document.activeElement;
    const inFig = was?.closest?.('figure.rl-map-figure') === fig;
    const focused = inFig ? was.getAttribute('data-place') : null;
    const mark = inFig && !focused ? was.getAttribute('data-key') : null; // a picked piece keeps focus over a lock's redraw
    fig.replaceChildren(drawing());
    if (focused) Array.from(fig.querySelectorAll('.rl-map-target')).find((t) => t.getAttribute('data-place') === focused)?.focus();
    else if (mark) Array.from(fig.querySelectorAll('[data-key]')).find((t) => t.getAttribute('data-key') === mark && t.getAttribute('aria-pressed') !== null)?.focus();
    if (fanFocus !== null) {
      const here = Array.from(fig.querySelectorAll('[data-stack]')).filter((g) => g.getAttribute('data-stack') === fanFocus);
      (fanned === fanFocus ? here.find((g) => g.classList.contains('rl-tm-mark')) : here.find((g) => g.classList.contains('rl-tm-stack')))?.focus();
      fanFocus = null;
    }
  };
  if (territorial) {
    // land not in play: the coastline is fetched only for a map that has a backdrop to draw it under
    const landless = (shapes) => shapes?.coords === 'lonlat' && (shapes.backdrop ?? []).length > 0 && !coast;
    const landAfter = () => landless(shapesFor(map.file)) && loadLand()?.then(() => {
      if (coast && view.isConnected) redraw();
    });
    landAfter();
    if (!shapesFor(map.file) && theatre.mode !== 'list') {
      loadShapes(map.file)?.then(() => {
        if (!shapesFor(map.file) || !view.isConnected) return;
        const fresh = territoryView(drawn, shapesFor(map.file), { ...opts, coast, targets: targets(), route: route() });
        view.replaceChildren(...fresh.childNodes);
        view.querySelector('figure.rl-map-figure')?.after(...below);
        showChip();
        landAfter();
      });
    }
    return view;
  }
  if (!coast && theatre.mode === 'map') {
    loadLand()?.then(() => {
      const fig = view.querySelector('figure.rl-map-figure');
      if (coast && fig?.isConnected) fig.replaceChildren(drawing());
    });
  }
  return view;
}
