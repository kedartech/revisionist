// Pick up and put down, by adjacency (PUP): on the territory map a picked own piece lights the
// areas its moves reach; a tap on a lit area draws the path with the days of each step and opens
// a confirm chip (the days, the arrival day, the first carrier, that carrier's load, the lift);
// confirming files the order. A piece whose order may still be withdrawn shows a ghost with a
// Withdraw button; Withdraw calls the server and the ghost goes only when the room is redrawn
// from the reply. Where the destination holds an enemy the seat has a report of, the chip sets
// the seat's own strength and posture beside the report, and says nothing of odds beyond its Odds button. Keyboard:
// Enter on a piece, arrows cycle the lit areas, Enter opens the chip, Enter confirms, Escape
// backs out one step.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { fire, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { theatreBoard, forgetShapes } = await import('../js/views/realism-theatre.js');
const { forgetMarks } = await import('../js/views/realism-territory.js');
const rules = await import('../js/realism-rules.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const TMAP = fixture.territory_map;
const LEVY = 'The Norra Levy';
const AREAS = Object.fromEntries(TMAP.areas.map((a) => [a.key, { key: a.key, name: a.name, place: null }]));

/** The toy world's movement form, as a desk lists it: its forces and the areas it sends to. */
const MOVE = {
  name: 'move_piece',
  label: 'Move a piece',
  summary: 'Send a piece to another area.',
  pipeline: 'field_order',
  params: [
    { name: 'force', label: 'Which piece', kind: 'enum', lo: null, hi: null, places: [], choices: [
      { value: 'norra_levy', label: 'The Norra Levy' }, { value: 'norra_kites', label: 'The Norra Kites' },
      { value: 'norra_herald', label: 'The Norra Herald' }] },
    { name: 'to', label: 'To', kind: 'enum', lo: null, hi: null, places: [], choices: [
      { value: 'isle', label: 'The Isle' }, { value: 'sudland_coast', label: 'The Sudland Coast' },
      { value: 'the_gulf', label: 'The Gulf' }, { value: 'open_sea', label: 'The Open Sea' }] },
  ],
};
const COURT = {
  load_limit: 2,
  ring: [],
  chambers: [],
  paths: [{ id: 'field_order', name: 'A field order', forms: ['Move a piece'], steps: [
    { person: 'P-ILSE', name: 'Ilse', office: 'Marshal of Norra', kind: 'decision', days: 1, you: false,
      orders: [{ id: 'o-a', label: 'Move a piece', since: '1900-04-01', held_days: 1 }, { id: 'o-b', label: 'Move a piece', since: '1900-04-01', held_days: 1 }] }] }],
};

/** The seat's data for the toy map: the map block, the form, the court and the day. */
function seat(change = () => {}) {
  const map = structuredClone(TMAP);
  const rv = {
    ...fixture,
    map,
    desk: { ...fixture.desk, levers: [MOVE] },
    court: structuredClone(COURT),
    clock: { ...fixture.clock, world_date: '1900-04-02' },
    orders: { orders: [] },
  };
  change(rv);
  return rv;
}
const markOf = (rv, name) => rv.map.marks.find((m) => m.name === name);

/** A Sudland levy the seat's own paper reported at Sudby, which lies in the Sudland Coast. */
const REPORTED = {
  key: 'm-sudland-levy', name: 'Sudland Levy', kind: 'army', side: 'other', side_name: 'Sudland', certainty: 'reported',
  places: [{ name: 'Sudby', lat: 40, lon: 60, theatre: null }], reported: '1900-04-01', source: 'Ilse', document: 'd-1',
  strength: 3, piece: null,
};

/** A small room: `pick` redraws the board as the room does; `act` is recorded and never answered unless asked. */
async function room(rv, ui = { piece: null, theatre: { mode: 'map', scope: 'reports' } }) {
  const acts = [];
  const was = globalThis.fetch;
  globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => (url === '/api/realism/map' ? { reply: '', refused: false, file: TMAP.file, map: SHAPES } : {}) });
  const r = {
    ui,
    acts,
    view: null,
    draw() {
      r.view?.remove();
      r.view = theatreBoard(rv, ui, {
        pick: (p) => {
          if (p.theatre) ui.theatre = p.theatre;
          if (p.piece !== undefined) ui.piece = p.piece;
          r.draw();
          if (p.piece) r.view.querySelector('.rl-mk[aria-pressed="true"]')?.focus();
        },
        act: (message, action, body, then) => { acts.push({ message, action, body, then }); },
      });
      document.body.append(r.view);
      return r.view;
    },
  };
  try {
    forgetShapes();
    forgetMarks();
    r.draw();
    await new Promise((ok) => setTimeout(ok, 0));
    await new Promise((ok) => setTimeout(ok, 0));
  } finally { globalThis.fetch = was; }
  r.draw();
  return r;
}
const pickLevy = (r) => {
  r.ui.piece = { kind: 'force', name: LEVY };
  return r.draw();
};
const lit = (view) => view.querySelectorAll('g.rl-map-target');
const litArea = (view, key) => lit(view).find((g) => g.getAttribute('data-area') === key);
const chip = (view) => view.querySelector('.rl-pup-chip');
const key = (k) => ({ type: 'keydown', key: k, preventDefault() {}, stopPropagation() {} });
/** A key as a browser presses it: keydown on `el`, then keyup on whatever has focus by then. */
const press = (el, k) => {
  el.dispatchEvent(key(k));
  (document.activeElement ?? el).dispatchEvent({ ...key(k), type: 'keyup' });
};
const ghosts = (view) => view.querySelectorAll('g.rl-tm-ghost');
const withdrawButtons = (view) => view.querySelectorAll('.rl-pup-ghosts button');

// --- the rules ------------------------------------------------------------------

test('days are added to a world date across a month', () => {
  assert.equal(rules.addDays('1900-04-02', 8), '1900-04-10');
  assert.equal(rules.addDays('1941-10-28', 7), '1941-11-04');
  assert.equal(rules.addDays('1941-10-28', 0), '1941-10-28');
});

test('the form that moves a piece is the one whose force list names it, whatever the mark\'s places', () => {
  const rv = seat();
  assert.deepEqual(rules.pieceForm([MOVE], markOf(rv, LEVY)), { lever: MOVE, force: 'norra_levy' });
  assert.equal(rules.pieceForm([MOVE], REPORTED), null, 'a foreign mark has none');
  assert.equal(rules.pieceForm([], markOf(rv, LEVY)), null);
});

test('a point lies in the area whose rings hold it; a hole in a ring is outside', () => {
  assert.equal(rules.inArea(SHAPES, 'sudland_coast', [60, 40]), true);
  assert.equal(rules.inArea(SHAPES, 'norra_plain', [60, 40]), false);
  assert.equal(rules.inArea(SHAPES, 'isle', [250, 100]), true);
  assert.equal(rules.inArea(SHAPES, 'open_sea', [250, 100]), false, 'the isle is a hole in the open sea');
  assert.equal(rules.inArea(SHAPES, 'open_sea', [280, 180]), true);
  assert.equal(rules.inArea(SHAPES, 'nowhere', [1, 1]), false);
});

test('the arrival day is today, the path\'s stated days and the move\'s days; an open step makes it the earliest', () => {
  const steps = COURT.paths[0].steps;
  assert.deepEqual(rules.arrival('1900-04-02', steps, 7), { on: '1900-04-10', earliest: false });
  assert.deepEqual(rules.arrival('1900-04-02', [...steps, { days: null }], 7), { on: '1900-04-10', earliest: true });
  assert.deepEqual(rules.arrival('1900-04-02', null, 7), { on: '1900-04-09', earliest: true }, 'no path known: the move alone, at the earliest');
});

// --- rule 1: tap a piece, then a lit area; the path and the chip ---------------

test('a picked own piece lights the areas its moves reach, each with its days, and no other', async () => {
  const r = await room(seat());
  assert.equal(lit(r.view).length, 0, 'nothing lit before a pick');
  const view = pickLevy(r);
  assert.deepEqual(lit(view).map((g) => g.getAttribute('data-area')).sort(), ['isle', 'sudland_coast']);
  assert.match(litArea(view, 'isle').getAttribute('aria-label'), /The Isle: 7 days/);
  assert.equal(chip(view), null, 'no chip until an area is chosen');
});

test('tapping a lit area draws the path with the days of each step and opens the confirm chip', async () => {
  const r = await room(seat());
  pickLevy(r);
  litArea(r.view, 'sudland_coast').click();
  const path = r.view.querySelector('g.rl-pup-path');
  assert.ok(path, 'the path is drawn');
  assert.deepEqual(path.querySelectorAll('text.rl-pup-step').map((t) => t.textContent), ['2 days', '5 days']);
  assert.equal(path.querySelector('polyline').getAttribute('points').split(' ').length, 3, 'from the piece through each step');
  const c = chip(r.view);
  assert.ok(c, 'the chip opens');
  const said = words(c);
  assert.match(said, /Send The Norra Levy to The Sudland Coast/);
  assert.match(said, /7 days on the move/);
  assert.match(said, /Arrives 10 Apr/);
  assert.match(said, /Carried first by Ilse, Marshal of Norra/);
  assert.match(said, /Ilse already holds 2 of your orders/);
  assert.match(said, /Lift: 50,000 tons of Galley/);
  assert.equal(litArea(r.view, 'sudland_coast').getAttribute('aria-pressed'), 'true');
});

test('a move with no lift says so, and an open step on the path makes the arrival the earliest', async () => {
  const r = await room(seat((rv) => { rv.court.paths[0].steps.push({ person: 'P-X', name: 'Clerk', office: '', kind: 'clerical', days: null, you: false, orders: [] }); }));
  pickLevy(r);
  litArea(r.view, 'isle').click();
  const said = words(chip(r.view));
  assert.match(said, /No lift needed/);
  assert.match(said, /Arrives 10 Apr at the earliest/);
  assert.equal(r.view.querySelectorAll('g.rl-pup-path text.rl-pup-step').length, 1);
});

test('an unlit area chooses nothing: tapping it opens no chip and files nothing', async () => {
  const r = await room(seat());
  pickLevy(r);
  const hills = r.view.querySelector('path.rl-area[data-area="norra_hills"]');
  hills.click();
  assert.equal(chip(r.view), null);
  assert.equal(r.view.querySelector('g.rl-pup-path'), null);
  assert.equal(r.acts.filter((a) => a.action === 'lever').length, 0);
});

test('tapping a lit area\'s own shape chooses it, as its ring does', async () => {
  const r = await room(seat());
  pickLevy(r);
  r.view.querySelector('path.rl-area[data-area="isle"]').click();
  assert.match(words(chip(r.view)), /to The Isle/);
});

test('an area the form cannot send to is not lit', async () => {
  const narrow = { ...MOVE, params: [MOVE.params[0], { ...MOVE.params[1], choices: [{ value: 'isle', label: 'The Isle' }] }] };
  const r = await room(seat((rv) => { rv.desk.levers = [narrow]; }));
  pickLevy(r);
  assert.deepEqual(lit(r.view).map((g) => g.getAttribute('data-area')), ['isle']);
});

test('a piece no form moves lights nothing', async () => {
  const r = await room(seat((rv) => { rv.desk.levers = []; }));
  pickLevy(r);
  assert.equal(lit(r.view).length, 0);
});

// --- rule 2: confirming files the order; the ghost and its Withdraw ------------

test('confirming files the order through the movement form, naming the piece and the area', async () => {
  const r = await room(seat());
  pickLevy(r);
  litArea(r.view, 'sudland_coast').click();
  const send = chip(r.view).querySelectorAll('button').find((b) => words(b) === 'Send it');
  send.click();
  const filed = r.acts.filter((a) => a.action === 'lever');
  assert.equal(filed.length, 1);
  assert.deepEqual(filed[0].body, { lever: 'move_piece', params: { force: 'norra_levy', to: 'sudland_coast' } });
  filed[0].then?.({ reply: 'Sent to Ilse: Move a piece.', refused: false });
  r.draw();
  assert.equal(chip(r.view), null, 'the chip closes once the order is filed');
});

/** The Levy with an order still with Ilse to the Isle; withdrawable or not. */
function waiting(withdrawable) {
  return seat((rv) => {
    markOf(rv, LEVY).piece.waiting = { order: 'o-move-7', with_person: 'Ilse', until: '1900-04-03', withdrawable };
    rv.orders.orders = [{ id: 'o-move-7', lever: 'move_piece', label: 'Move a piece', params: { force: 'norra_levy', to: 'isle' }, status: 'moving' }];
  });
}

test('a piece whose order may still be withdrawn shows a ghost at its goal with a Withdraw button', async () => {
  const r = await room(waiting(true));
  assert.equal(ghosts(r.view).length, 1, 'the ghost is drawn');
  assert.match(r.view.querySelector('.rl-tm-ghost-note').textContent, /with Ilse to 3 Apr/);
  const buttons = withdrawButtons(r.view);
  assert.equal(buttons.length, 1);
  assert.equal(words(buttons[0]), 'Withdraw');
  assert.match(words(r.view.querySelector('.rl-pup-ghosts li')), /The Norra Levy to The Isle: with Ilse to 3 Apr/);
});

test('an order that can no longer be withdrawn keeps its ghost and has no Withdraw button', async () => {
  const r = await room(waiting(false));
  assert.equal(ghosts(r.view).length, 1);
  assert.equal(withdrawButtons(r.view).length, 0);
});

// --- rule 3: Withdraw calls the server; the ghost goes when the reply lands -----

test('Withdraw calls the server, and the ghost stays until the room is drawn from the reply', async () => {
  const rv = waiting(true);
  const r = await room(rv);
  withdrawButtons(r.view)[0].click();
  const asked = r.acts.filter((a) => a.action === 'withdraw');
  assert.equal(asked.length, 1);
  assert.deepEqual(asked[0].body, { order_id: 'o-move-7' });
  assert.equal(ghosts(r.view).length, 1, 'no reply yet: the ghost stays');
  asked[0].then?.({ reply: 'There is no such held order of yours to withdraw.', refused: true });
  r.draw();
  assert.equal(ghosts(r.view).length, 1, 'a refusal leaves it');
  markOf(rv, LEVY).piece.waiting = null;
  rv.orders.orders[0].status = 'withdrawn';
  r.draw();
  assert.equal(ghosts(r.view).length, 0, 'the room drawn from the reply has none');
  assert.equal(withdrawButtons(r.view).length, 0);
});

// --- rule 4: a reported enemy at the destination --------------------------------

test('where the destination holds an enemy the seat has a report of, the chip sets the seat\'s own strength and posture beside the report', async () => {
  const r = await room(seat((rv) => {
    rv.map.marks.push(structuredClone(REPORTED));
    Object.assign(markOf(rv, LEVY).piece, { strength: 2, posture: 'hold' });
  }));
  pickLevy(r);
  litArea(r.view, 'sudland_coast').click();
  const there = chip(r.view).querySelector('.rl-pup-there');
  assert.ok(there, 'the report is on the chip');
  const said = words(there);
  assert.match(said, /Yours: The Norra Levy, strength 2, Hold/);
  assert.match(said, /Reported there: Sudland Levy \(Sudland\), strength 3; Reported 1 April 1900 by Ilse/);
  assert.doesNotMatch(said, /odds|chance|likely|%|win|lose/i);
  // the odds are only behind the chip's Odds button (ODC): nothing of them shows until it is asked
  assert.equal(chip(r.view).querySelector('.rl-odds'), null);
  const shown = [...chip(r.view).children].filter((el) => !el.classList.contains('rl-pup-acts')).map(words).join(' ');
  assert.doesNotMatch(shown, /odds|chance|likely|%|win|lose/i);
});

test('an area with no reported enemy, or a report of a nation not at war with the seat, shows no report', async () => {
  const r = await room(seat((rv) => {
    rv.map.marks.push({ ...structuredClone(REPORTED), side_name: 'Lune' });
  }));
  pickLevy(r);
  litArea(r.view, 'sudland_coast').click();
  assert.equal(chip(r.view).querySelector('.rl-pup-there'), null, 'Lune is not an enemy of the seat');
  litArea(r.view, 'isle').click();
  assert.equal(chip(r.view).querySelector('.rl-pup-there'), null);
});

// --- rule 5: the keyboard ------------------------------------------------------

test('keyboard: Enter on a piece, arrows cycle the lit areas, Enter opens the chip, Enter confirms', async () => {
  const r = await room(seat());
  r.ui.theatre.fanned = 'norra_plain';
  r.draw();
  const levy = r.view.querySelectorAll('g.rl-tm-mark').find((g) => g.getAttribute('aria-label').startsWith(`${LEVY}:`));
  press(levy, 'Enter');
  assert.deepEqual(r.ui.piece, { kind: 'force', name: LEVY });
  const picked = document.activeElement;
  assert.ok(picked.classList.contains('rl-tm-mark'), 'focus on the picked piece');
  press(picked, 'ArrowRight');
  const first = document.activeElement;
  assert.ok(first.classList.contains('rl-map-target'), 'an arrow moves focus to a lit area');
  press(first, 'ArrowRight');
  const second = document.activeElement;
  assert.ok(second.classList.contains('rl-map-target'));
  assert.notEqual(second.getAttribute('data-area'), first.getAttribute('data-area'), 'and on to the next');
  press(second, 'ArrowRight');
  assert.equal(document.activeElement.getAttribute('data-area'), first.getAttribute('data-area'), 'it wraps');
  press(document.activeElement, 'ArrowLeft');
  assert.equal(document.activeElement.getAttribute('data-area'), second.getAttribute('data-area'), 'and back');
  press(document.activeElement, 'Enter');
  assert.ok(chip(r.view), 'Enter opens the chip');
  assert.equal(words(document.activeElement), 'Send it', 'focus on the confirm button');
  document.activeElement.click();
  assert.equal(r.acts.filter((a) => a.action === 'lever').length, 1, 'Enter on it confirms');
});

test('keyboard: Escape backs out one step, from the chip to its area, from the area to the piece', async () => {
  const r = await room(seat());
  pickLevy(r);
  litArea(r.view, 'isle').focus();
  press(litArea(r.view, 'isle'), 'Enter');
  assert.ok(chip(r.view));
  press(document.activeElement, 'Escape');
  assert.equal(chip(r.view), null, 'the chip closes');
  assert.equal(document.activeElement.getAttribute('data-area'), 'isle', 'focus back on the area');
  press(document.activeElement, 'Escape');
  assert.ok(document.activeElement.classList.contains('rl-tm-mark'), 'focus back on the piece');
  assert.equal(document.activeElement.getAttribute('aria-pressed'), 'true');
  assert.ok(document.activeElement.isConnected, 'on the piece as drawn, not one a redraw dropped');
});

test('a lit area keeps the chosen area across a redraw of the board (a poll)', async () => {
  const r = await room(seat());
  pickLevy(r);
  litArea(r.view, 'isle').click();
  r.draw();
  assert.match(words(chip(r.view)), /to The Isle/);
});

test('a game without territories draws no chip and no path, and its forms stay as they were', async () => {
  const rv = { ...fixture };
  const ui = { piece: { kind: 'force', name: 'US Atlantic Fleet' }, theatre: { mode: 'map', scope: 'reports' } };
  const view = theatreBoard(rv, ui, { pick: () => {}, act: () => {} });
  assert.equal(chip(view), null);
  assert.equal(view.querySelector('g.rl-pup-path'), null);
  assert.ok(view.querySelector('.rl-theatre-forms'), 'the point map\'s forms still show');
});

test('a point game\'s withdrawable order shows its Withdraw button too', () => {
  const rv = structuredClone(fixture);
  rv.map.marks.find((m) => m.name === 'US Atlantic Fleet').piece.waiting.withdrawable = true;
  const view = theatreBoard(rv, { piece: null, theatre: { mode: 'map', scope: 'reports' } }, { pick: () => {}, act: () => {} });
  assert.equal(withdrawButtons(view).length, 1);
  rv.map.marks.find((m) => m.name === 'US Atlantic Fleet').piece.waiting.withdrawable = false;
  const again = theatreBoard(rv, { piece: null, theatre: { mode: 'map', scope: 'reports' } }, { pick: () => {}, act: () => {} });
  assert.equal(withdrawButtons(again).length, 0);
});
