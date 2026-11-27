// Raising a piece on screen (RNB). A place of the seat's own that can raise shows "Raise a piece
// here" in its sheet, and the war economy sheet lists every such place. It opens the kinds the
// place can raise as tiles: the picture, the five figures, the cost as two bars against the pools
// and the day it would arrive. Choosing one runs the server's check; only an allowed answer shows
// the pools as they would stand and the confirm chip, and only the chip files the order. A refusal
// shows the check's words on the tile. Pieces being raised are a list in the war economy sheet, each
// with its place and day, and each opens that place on the map. Every kind, cost, day, pool and
// word is the server's (`economy.own.places`, `economy.own.raising`, the check): nothing here works
// one out. Nothing here touches the page on import.

import { h } from '../dom.js';
import { shortDate } from '../realism-rules.js';
import { checkNow, lockedChoice } from './realism-locks.js';
import { markSwatch } from './realism-map.js';
import { bar, markNum, meter } from './realism-marks.js';
import { FIGURES } from './realism-piece.js';

/** The words of the button that opens the tiles. */
export const RAISE_HERE = 'Raise a piece here';

/** The places the seat's nation can raise at, as the server sent them; [] with `raising` off. */
export const raisePlaces = (rv) => rv?.economy?.own?.places ?? [];

/** The pieces the seat's nation is raising, as the server sent them; [] with `raising` off. */
export const raisingLines = (rv) => rv?.economy?.own?.raising ?? [];

/** The places that can raise in map area `area`. */
export const placesIn = (rv, area) => raisePlaces(rv).filter((p) => p.area === area);

/** The order filed for `kind` at `place`: the place's own form, with the kind and the place as its terms. */
export const raiseOrder = (place, kind) => ({ lever: place.form, params: { kind: kind.kind, place: place.place } });

/** The world's name of the pool with `role`, from the seat's own income lines: "Grain, Iron". */
function poolName(rv, role) {
  const names = (rv?.economy?.own?.income ?? []).filter((r) => r.role === role).map((r) => r.name);
  return names.length ? names.join(', ') : role.charAt(0).toUpperCase() + role.slice(1);
}

const POOLS = Object.freeze(['output', 'manpower']);

/**
 * The line a place's sheet carries for each place in it that can raise: its name and "Raise a
 * piece here", which calls `onRaise(place)`. `[]` for an area with none.
 */
export function raiseEntries(rv, area, onRaise) {
  return placesIn(rv, area).map((p) => h('div', { class: 'rl-rs-entry', 'data-place': p.place },
    h('span', { class: 'rl-rs-entry-name' }, p.name),
    h('button', { type: 'button', class: 'rl-btn rl-rs-open', 'aria-label': `${RAISE_HERE}: ${p.name}`, onclick: () => onRaise?.(p) }, RAISE_HERE)));
}

/** The kind's five figures as meters, as the server sent them; none with `kinds_in_battle` off. */
function figureMeters(kind) {
  if (!kind.figures) return null;
  const rows = FIGURES.filter(([key]) => Number.isInteger(kind.figures[key])).map(([key, name]) => h('div', { class: 'rl-pc-row', 'data-figure': key },
    h('span', { class: 'rl-pc-fig' }, name),
    meter({ step: kind.figures[key], of: 5, name: `${kind.name}: ${name.toLowerCase()}` })));
  return rows.length ? h('div', { class: 'rl-pc-figs rl-rs-figs' }, rows) : null;
}

/** The kind's cost as one bar a pool: the cost against what is in the pool now. */
function costBars(rv, kind) {
  const pools = rv.economy.own.pools ?? {};
  return h('div', { class: 'rl-rs-costs' }, POOLS.filter((role) => kind.cost?.[role] !== undefined).map((role) => {
    const name = poolName(rv, role);
    const cost = Number(kind.cost[role]);
    const now = Number(pools[role] ?? 0);
    return h('div', { class: 'rl-rs-cost', 'data-pool': role },
      h('span', { class: 'rl-rs-pool' }, name),
      // a cost past the pool fills its track, so an empty pool still shows the cost as a mark
      bar({
        value: cost, limit: Math.max(now, cost), name, tone: cost > now ? 'hostile' : null, label: `${markNum(cost)}/${markNum(now)}`,
        words: `${name}: costs ${markNum(cost)} of ${markNum(now)} in the pool`,
      }));
  }));
}

/** The pools as they would stand after raising `kind` (the server's `pools_after`), each against the pool now. */
function poolsAfter(rv, kind) {
  const pools = rv.economy.own.pools ?? {};
  return h('div', { class: 'rl-rs-after' }, POOLS.filter((role) => kind.pools_after?.[role] !== undefined).map((role) => {
    const name = poolName(rv, role);
    const after = Number(kind.pools_after[role]);
    const now = Number(pools[role] ?? 0);
    return h('div', { class: 'rl-rs-cost', 'data-pool': role },
      h('span', { class: 'rl-rs-pool' }, `${name} after`),
      bar({
        value: Math.max(0, after), limit: now, name: `${name} after`, tone: after < 0 ? 'hostile' : null, label: `${markNum(after)}/${markNum(now)}`,
        words: `${name}: ${markNum(now)} now, ${markNum(after)} after`,
      }));
  }));
}

/** The words a tile shows for why it may not be raised: the check's, else the reply's. */
function refusalOf(kind, chosen, answer) {
  if (chosen && answer && answer.check === 'beyond') return answer.reason;
  return kind.refusal || '';
}

/** One kind as a tile: a button that chooses it, its picture, name, figures, cost and day. */
function tile(rv, kind, { chosen, answer, onChoose }) {
  const refusal = refusalOf(kind, chosen, answer);
  return h('button', {
    type: 'button', class: `rl-rs-tile${refusal ? ' rl-rs-refused' : ''}`, 'data-kind': kind.kind,
    'aria-pressed': String(chosen), onclick: () => onChoose(kind),
  },
  h('span', { class: 'rl-rs-head' },
    markSwatch({ side: 'own', certainty: 'known', kind: null, picture: kind.picture ?? null }),
    h('span', { class: 'rl-rs-kind' }, kind.name)),
  figureMeters(kind),
  costBars(rv, kind),
  h('span', { class: 'rl-rs-day' }, `${kind.lead_days} days to raise · arrives ${shortDate(kind.arrives)}`),
  refusal ? h('span', { class: 'rl-rs-why' }, refusal) : null);
}

/**
 * The confirm for the chosen kind, once the check is in: allowed, the pools after and Raise it;
 * locked, the lock's choices; refused, nothing (the tile says why). While the check is out, or
 * when it failed, there is no way to file.
 */
function confirmBox(rv, place, kind, state, { send, ask, anyway, back, retry }) {
  const answer = state.answer;
  if (state.out) return h('p', { class: 'rl-rs-checking', role: 'status' }, `Checking ${kind.name} at ${place.name}…`);
  if (!answer) {
    return h('div', { class: 'rl-rs-confirm', role: 'group', 'aria-label': `Raise ${kind.name} at ${place.name}` },
      h('p', { role: 'status' }, 'The check could not be run, so nothing can be sent yet.'),
      h('div', { class: 'rl-pup-acts' },
        h('button', { type: 'button', class: 'primary', onclick: retry }, 'Check again'),
        h('button', { type: 'button', onclick: back }, 'Back')));
  }
  if (answer.check === 'beyond') return null;
  const head = h('p', { class: 'rl-rs-ask' }, h('strong', {}, `Raise ${kind.name} at ${place.name}?`),
    ` It arrives on ${shortDate(kind.arrives)}. Nothing is filed until you send it.`);
  if (answer.check === 'locked') {
    return h('section', { class: 'rl-pup-chip rl-rs-confirm', role: 'group', 'aria-label': `Raise ${kind.name} at ${place.name}` },
      head, poolsAfter(rv, kind),
      lockedChoice(answer, { file: send, ask, send: anyway }),
      h('div', { class: 'rl-pup-acts' }, h('button', { type: 'button', onclick: back }, 'Back')));
  }
  return h('section', { class: 'rl-pup-chip rl-rs-confirm', role: 'group', 'aria-label': `Raise ${kind.name} at ${place.name}` },
    head,
    answer.reason ? h('p', { class: 'rl-rs-note' }, answer.reason) : null,
    poolsAfter(rv, kind),
    h('div', { class: 'rl-pup-acts' },
      h('button', { type: 'button', class: 'primary rl-rs-send', onclick: send }, 'Raise it'),
      h('button', { type: 'button', onclick: back }, 'Back')));
}

/**
 * The sheet of place `state.place` (a key of `economy.own.places`): the kinds it can raise as
 * tiles, and, for the chosen one, the confirm. `state` is kept by the caller across redraws
 * (`{ place, kind, answer, out, on }`); the sheet sets its own fields and redraws itself in place.
 * `act(message, action, body, then)` files; `onClose()` closes it. Null for a place the reply
 * does not list.
 */
export function raiseSheet(rv, state, { act, onClose } = {}) {
  const place = raisePlaces(rv).find((p) => p.place === state?.place);
  if (!place) return null;
  const box = h('section', {
    class: 'rl-rs-sheet', 'aria-labelledby': 'rl-rs-sheet-h', 'data-place': place.place,
    // Escape in the confirm goes back to the tiles, as a move's chip does; elsewhere it closes the sheet
    onkeydown: (e) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      e.preventDefault();
      e.stopPropagation();
      if (state.kind && e.target?.closest?.('.rl-rs-confirm')) back();
      else onClose?.();
    },
  });
  // an answer is kept for the day it was asked on; on a later day the check is asked again
  const day = rv.economy?.day ?? null;
  const ask = (kind) => {
    const order = raiseOrder(place, kind);
    state.kind = kind.kind;
    state.answer = null;
    state.out = true;
    state.on = day;
    checkNow(order).then((answer) => {
      if (state.kind !== kind.kind || state.on !== day) return;
      state.answer = answer;
      state.out = false;
      state.redraw?.('.rl-rs-send, .rl-lock-file, .rl-rs-confirm button, .rl-rs-tile[aria-pressed="true"]');
    });
  };
  const choose = (kind) => {
    if (state.kind === kind.kind && !state.out && state.answer) return;
    ask(kind);
    draw(`.rl-rs-tile[data-kind="${kind.kind}"]`);
  };
  const back = () => {
    const was = state.kind;
    state.kind = null;
    state.answer = null;
    state.out = false;
    draw(was ? `.rl-rs-tile[data-kind="${was}"]` : null);
  };
  const sent = (r) => { if (!r?.refused) { state.kind = null; state.answer = null; onClose?.(); } };
  const draw = (focus = null) => {
    const kind = place.kinds.find((k) => k.kind === state.kind) ?? null;
    if (kind && state.on !== day && !state.out) ask(kind);
    const order = kind ? raiseOrder(place, kind) : null;
    box.replaceChildren(...[
      h('div', { class: 'rl-rs-top' },
        h('h3', { id: 'rl-rs-sheet-h', tabindex: '-1' }, `Raise a piece at ${place.name}`),
        h('button', { type: 'button', class: 'rl-find rl-rs-close', onclick: () => onClose?.() }, 'Close')),
      h('p', { class: 'muted' }, 'What this place can raise, and what each costs against your pools.'),
      kind ? confirmBox(rv, place, kind, state, {
        send: () => act?.('Sending it…', 'lever', order, sent),
        ask: () => act?.('Asking…', 'lever-ask', order, sent),
        anyway: () => act?.('Sending it anyway…', 'lever-anyway', order, sent),
        back,
        retry: () => choose(kind),
      }) : null,
      h('div', { class: 'rl-rs-tiles' }, place.kinds.map((k) => tile(rv, k, {
        chosen: k.kind === state.kind, answer: k.kind === state.kind ? state.answer : null, onChoose: choose,
      })))].filter(Boolean));
    if (focus) box.querySelector(focus)?.focus?.();
  };
  // the sheet drawn last is the one an answer arriving redraws
  state.redraw = draw;
  draw();
  return box;
}

/**
 * The war economy sheet's part for raising: every place that can raise, each with "Raise a piece
 * here" (`onRaise(place)`), and the pieces being raised, each with its place and day, which open
 * that place on the map (`onMap(area)`). Without a hook its buttons are not drawn. `[]` with
 * `raising` off.
 */
export function economyRaising(own, { onRaise = null, onMap = null } = {}) {
  if (!own?.places && !own?.raising) return [];
  const places = own.places ?? [];
  const raising = own.raising ?? [];
  return [
    h('h4', {}, 'Where you can raise'),
    places.length
      ? h('ul', { class: 'rl-rs-places', role: 'list' }, places.map((p) => h('li', { 'data-place': p.place },
        h('span', { class: 'rl-rs-entry-name' }, p.name),
        h('span', { class: 'muted rl-rs-kinds' }, p.kinds.map((k) => k.name).join(', ')),
        onRaise ? h('button', { type: 'button', class: 'rl-btn rl-rs-open', 'aria-label': `${RAISE_HERE}: ${p.name}`, onclick: () => onRaise(p) }, RAISE_HERE) : null)))
      : h('p', { class: 'muted rl-rs-none' }, 'No place of yours can raise a piece now.'),
    h('h4', {}, 'Pieces being raised'),
    raising.length
      ? h('ul', { class: 'rl-rs-raising', role: 'list' }, raising.map((r) => h('li', { 'data-place': r.place },
        markSwatch({ side: 'own', certainty: 'known', kind: null, picture: r.picture ?? null }),
        h('span', { class: 'rl-rs-line' }, `${r.name} at ${r.place_name}, arrives ${shortDate(r.day)}${r.fixed ? '' : ' if each step is taken on its day'}`),
        onMap && r.area ? h('button', { type: 'button', class: 'rl-btn rl-rs-map', 'aria-label': `Show ${r.place_name} on the map`, onclick: () => onMap(r.area, r) }, 'Show on map') : null)))
      : h('p', { class: 'muted rl-rs-none' }, 'No piece is being raised.'),
  ];
}
