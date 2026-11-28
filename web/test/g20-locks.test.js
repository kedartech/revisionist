// Locks on the map, and the ask (LKM). With the game's `locks` rule on, a picked piece shows a
// locked order beside its allowed ones, marked with a padlock and who can allow it; choosing a
// locked order runs the check and offers two things, file it to be held and ask; a held order
// shows in the seat's "what needs you" list, asked or not asked; the decider sees each ask in his
// list and opens it on the order's plain words and the forms of his own that would allow it.
// Every lock shown is the server's answer: the `check` call's, or the seat's `locks` block.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { fire, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { theatreBoard, forgetShapes } = await import('../js/views/realism-theatre.js');
const { forgetMarks } = await import('../js/views/realism-territory.js');
const { piecePanel } = await import('../js/views/realism-board.js');
const { needLines, needsList } = await import('../js/views/realism-needs.js');
const { standardForm } = await import('../js/views/realism-forms.js');
const locks = await import('../js/views/realism-locks.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const TMAP = fixture.territory_map;
const LEVY = 'The Norra Levy';
const ILSE = 'Ilse Varg';

/** The toy world's movement form, as a desk lists it. */
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
/** Ilse's own form: set a watch on a water. */
const WATCH = {
  name: 'set_watch',
  label: 'Set watch',
  summary: 'Set a watch on a water.',
  pipeline: 'field_order',
  params: [
    { name: 'zone', label: 'Zone', kind: 'enum', lo: null, hi: null, places: [], choices: [
      { value: 'gulf', label: 'The Gulf' }, { value: 'open', label: 'The open sea' }] },
    { name: 'order', label: 'Order', kind: 'enum', lo: null, hi: null, places: [], choices: [
      { value: 'guard', label: 'Guard' }, { value: 'stand_down', label: 'Stand down' }] },
  ],
};
const COURT = { load_limit: 2, ring: [], chambers: [], paths: [{ id: 'field_order', name: 'A field order', forms: ['Move a piece'], steps: [
  { person: 'P-ILSE', name: 'Ilse', office: 'Marshal of Norra', kind: 'decision', days: 1, you: false, orders: [] }] }] };

/** The seat's data for the toy map, with `locks` on (the fixture's block) unless `change` drops it. */
function seat(change = () => {}) {
  const rv = {
    ...fixture,
    map: structuredClone(TMAP),
    desk: { ...fixture.desk, levers: [MOVE, WATCH] },
    court: structuredClone(COURT),
    clock: { ...fixture.clock, world_date: '1900-04-02' },
    orders: { orders: [] },
    agenda: { ...fixture.agenda, items: [] },
    documents: { ...fixture.documents, documents: [] },
    record: null,
    battles: [],
    home: null,
    locks: structuredClone(fixture.locks),
  };
  change(rv);
  return rv;
}
const unlocked = (rv) => { delete rv.locks; };

const LOCKED = { check: 'locked', who: ILSE, reason: 'Held until Ilse Varg allows it.' };
const ALLOWED = { check: 'allowed', who: null, reason: '' };

/** The server: `check` answered by `answer(body)`; every call recorded. */
function stubApi(answer = (b) => (b.params.to === 'isle' ? LOCKED : ALLOWED)) {
  const calls = [];
  api.realism = async (action, body) => {
    if (action === 'map') return { reply: '', refused: false, file: TMAP.file, map: SHAPES };
    calls.push({ action, body });
    return action === 'check' ? answer(body) : { reply: '', refused: false };
  };
  return calls;
}
const checks = (calls) => calls.filter((c) => c.action === 'check');
const settle = async () => { for (let i = 0; i < 6; i += 1) await new Promise((ok) => setTimeout(ok, 0)); };

/** A small room: `pick` redraws the board as the room does; `act` is recorded. */
async function room(rv) {
  const acts = [];
  const ui = { piece: null, theatre: { mode: 'map', scope: 'reports' } };
  const r = {
    ui, acts, view: null,
    draw() {
      r.view?.remove();
      r.view = theatreBoard(rv, ui, {
        pick: (p) => { if (p.theatre) ui.theatre = p.theatre; if (p.piece !== undefined) ui.piece = p.piece; r.draw(); },
        act: (message, action, body, then) => { acts.push({ message, action, body, then }); },
      });
      document.body.append(r.view);
      return r.view;
    },
  };
  forgetShapes();
  forgetMarks();
  locks.forgetChecks();
  r.draw();
  await settle();
  r.draw();
  return r;
}
const pickLevy = async (r) => {
  r.ui.piece = { kind: 'force', name: LEVY };
  r.draw();
  await settle();
  return r.view;
};
const litArea = (view, key) => view.querySelectorAll('g.rl-map-target').find((g) => g.getAttribute('data-area') === key);
const chip = (view) => view.querySelector('.rl-pup-chip');
const buttonsOf = (el) => el.querySelectorAll('button').map((b) => words(b));
/** Submit a form's lever form as the browser does (the fake has no `#id` selector). */
const submit = (item) => {
  const form = item.querySelector('form');
  const query = form.querySelector.bind(form);
  form.querySelector = (q) => (q.startsWith('#') ? form.querySelectorAll('[id]').find((e) => e.id === q.slice(1)) ?? null : query(q));
  fire(form, 'submit');
};

// --- rule 1: a picked piece shows a locked order beside its allowed ones ---------------------

test('a picked piece marks the lit move the server says is locked, with a padlock and who can allow it', async () => {
  const calls = stubApi();
  const r = await room(seat());
  const view = await pickLevy(r);
  const isle = litArea(view, 'isle');
  const coast = litArea(view, 'sudland_coast');
  assert.ok(isle && coast, 'both moves are lit');
  assert.ok(isle.classList.contains('locked'), 'the locked move is marked');
  assert.ok(isle.querySelector('.rl-tm-lock .rl-lock-glyph'), 'with the padlock');
  assert.equal(words(isle.querySelector('.rl-tm-lock')), ILSE, 'and the decider\'s name beside it');
  assert.match(isle.getAttribute('aria-label'), /Locked: Ilse Varg can allow it/);
  assert.ok(!coast.classList.contains('locked'), 'the allowed move beside it is not');
  assert.equal(coast.querySelector('.rl-tm-lock'), null);
  assert.deepEqual(checks(calls).map((c) => c.body).sort((a, b) => (a.params.to < b.params.to ? -1 : 1)), [
    { lever: 'move_piece', params: { force: 'norra_levy', to: 'isle' } },
    { lever: 'move_piece', params: { force: 'norra_levy', to: 'sudland_coast' } },
  ], 'one check per lit move, each as the order would be filed');
});

test('the piece sheet lists the piece\'s locked move with who can allow it, and no allowed one', async () => {
  stubApi();
  const rv = seat();
  const r = await room(rv);
  await pickLevy(r);
  const panel = piecePanel(rv, { kind: 'force', name: LEVY }, () => {}, {});
  document.body.append(panel);
  await settle();
  const rows = panel.querySelectorAll('.rl-piece-moves li');
  assert.deepEqual(rows.map((li) => li.getAttribute('data-area')), ['isle']);
  assert.equal(words(rows[0].querySelector('.rl-lock-who')), ILSE);
  assert.ok(rows[0].querySelector('.rl-lock-icon'), 'with the padlock');
  panel.remove();
  stubApi(() => ALLOWED);
  locks.forgetChecks();
  const none = piecePanel(rv, { kind: 'force', name: LEVY }, () => {}, {});
  await settle();
  assert.equal(none.querySelectorAll('.rl-piece-moves li').length, 0, 'none locked: nothing listed');
});

test('with locks off a picked piece asks nothing and draws as today', async () => {
  const calls = stubApi();
  const rv = seat(unlocked);
  const r = await room(rv);
  const view = await pickLevy(r);
  assert.equal(checks(calls).length, 0, 'no check is asked');
  assert.equal(view.querySelectorAll('g.rl-map-target.locked').length, 0);
  assert.equal(view.querySelectorAll('.rl-tm-lock').length, 0);
  const panel = piecePanel(rv, { kind: 'force', name: LEVY }, () => {}, {});
  assert.equal(panel.querySelector('.rl-piece-moves'), null, 'the piece sheet holds no lock list');
});

// --- rule 2: choosing a locked order runs the check and offers file or ask --------------------

test('choosing a locked move runs the check again and offers file it to be held, and ask', async () => {
  const calls = stubApi();
  const r = await room(seat());
  await pickLevy(r);
  const before = checks(calls).length;
  litArea(r.view, 'isle').click();
  await settle();
  assert.equal(checks(calls).length, before + 1, 'choosing runs the check');
  assert.deepEqual(checks(calls).at(-1).body, { lever: 'move_piece', params: { force: 'norra_levy', to: 'isle' } });
  const c = chip(r.view);
  assert.ok(c, 'the chip opens');
  assert.deepEqual(buttonsOf(c.querySelector('.rl-lock-acts')), ['File it to be held', 'Ask Ilse Varg']);
  assert.equal(c.querySelectorAll('button').filter((b) => words(b) === 'Send it').length, 0, 'no plain Send it');
  assert.match(words(c), /Held until Ilse Varg allows it\./);
  c.querySelector('.rl-lock-file').click();
  c.querySelector('.rl-lock-ask').click();
  const body = { lever: 'move_piece', params: { force: 'norra_levy', to: 'isle' } };
  assert.deepEqual(r.acts.map((a) => [a.action, a.body]), [['lever', body], ['lever-ask', body]]);
});

test('choosing an allowed move keeps Send it', async () => {
  stubApi();
  const r = await room(seat());
  await pickLevy(r);
  litArea(r.view, 'sudland_coast').click();
  await settle();
  const c = chip(r.view);
  assert.equal(c.querySelector('.rl-lock-acts'), null);
  assert.ok(buttonsOf(c).includes('Send it'));
});

test('a form whose check says locked offers file it to be held and ask; an allowed one is sent at once', async () => {
  const sent = [];
  const asked = [];
  let answer = LOCKED;
  const item = standardForm(WATCH, {
    onSubmit: (v) => sent.push(v), check: async () => answer, onAsk: (v) => asked.push(v), entities: [],
  });
  document.body.append(item);
  submit(item);
  await settle();
  assert.equal(sent.length, 0, 'a locked form is not filed before the seat chooses');
  const choice = item.querySelector('.rl-lock-choice');
  assert.ok(choice, 'the lock and its two choices show');
  assert.deepEqual(buttonsOf(choice.querySelector('.rl-lock-acts')), ['File it to be held', 'Ask Ilse Varg']);
  choice.querySelector('.rl-lock-ask').click();
  assert.equal(asked.length, 1);
  assert.equal(asked[0].lever, 'set_watch');
  answer = ALLOWED;
  submit(item);
  await settle();
  assert.equal(sent.length, 1, 'allowed: filed at once');
  assert.equal(item.querySelector('.rl-lock-choice'), null, 'and the lock line goes');
  item.remove();
});

// --- rule 3: a held order in the seat's list, asked or not asked ------------------------------

test('each held order is a line in what needs you, asked or not asked; only the unasked one offers Ask', () => {
  const rv = seat();
  const held = needLines(rv).filter((l) => l.kind === 'held');
  assert.equal(held.length, 2);
  const [asked, open] = [held.find((l) => l.key === fixture.locks.held[0].id), held.find((l) => l.key === fixture.locks.held[1].id)];
  assert.equal(asked.what, 'March (Force Norra levy, To Isle)');
  assert.equal(asked.status, 'Asked');
  assert.equal(asked.action, null);
  assert.equal(open.status, 'Not asked');
  assert.deepEqual(open.action, { word: 'Ask', to: 'ask-for', id: fixture.locks.held[1].id });
  const seen = [];
  const list = needsList(rv, needLines(rv), { onAction: (line) => seen.push(line.key) });
  const rows = list.querySelectorAll('li.rl-need').filter((li) => li.getAttribute('data-kind') === 'held');
  assert.equal(rows.length, 2);
  const askedRow = rows.find((li) => li.getAttribute('data-need') === asked.key);
  const openRow = rows.find((li) => li.getAttribute('data-need') === open.key);
  assert.match(words(askedRow), /Asked/);
  assert.ok(askedRow.querySelector('.rl-lock'), 'the lock mark with who can allow it');
  assert.equal(askedRow.querySelectorAll('.rl-need-act').length, 0, 'an asked order has nothing to press');
  assert.match(words(openRow), /Not asked/);
  openRow.querySelector('button.rl-need-act').click();
  assert.deepEqual(seen, [open.key]);
});

/** The mark on the map whose name is `name`, as drawn (the piece's own marker, not a stack). */
const markOn = (view, name) => view.querySelectorAll('g.rl-tm-mark').find((g) => g.getAttribute('aria-label')?.startsWith(`${name}:`));

test('a held order shows on its piece: on the map mark and in the piece sheet, with who and asked or not asked', async () => {
  stubApi(() => ALLOWED);
  const rv = seat();
  const r = await room(rv);
  const stack = r.view.querySelector('g.rl-tm-stack');
  assert.ok(stack.querySelector('.rl-tm-held .rl-lock-glyph'), 'the closed stack carries the padlock');
  assert.match(stack.getAttribute('aria-label'), /held order on The Norra Levy/);
  const levy = markOn(await pickLevy(r), LEVY);
  assert.ok(levy.querySelector('.rl-tm-held .rl-lock-glyph'), 'the padlock on the levy');
  assert.equal(words(levy.querySelector('.rl-tm-held .rl-lock-note')), ILSE);
  assert.match(levy.getAttribute('aria-label'), /Held order: March \(Force Norra levy, To Isle\), Ilse Varg can allow it, asked/);
  assert.equal(markOn(r.view, 'The Norra Kites').querySelector('.rl-tm-held'), null, 'a piece with nothing held has no lock');
  const panel = piecePanel(rv, { kind: 'force', name: LEVY }, () => {}, {});
  const rows = panel.querySelectorAll('.rl-piece-held li');
  assert.equal(rows.length, 1);
  assert.match(words(rows[0]), /March \(Force Norra levy, To Isle\)/);
  assert.equal(words(rows[0].querySelector('.rl-lock-who')), ILSE);
  assert.match(words(rows[0]), /Asked/);
  assert.equal(piecePanel(rv, { kind: 'force', name: 'The Norra Kites' }, () => {}, {}).querySelector('.rl-piece-held'), null);
});

test('a held order not yet asked for shows on its piece as not asked', () => {
  const rv = seat((x) => { x.locks.held[0].asked = false; });
  const panel = piecePanel(rv, { kind: 'force', name: LEVY }, () => {}, {});
  assert.match(words(panel.querySelector('.rl-piece-held li')), /Not asked/);
});

test('a held order is drawn on the piece the server names only: a written order and an unknown piece go nowhere', async () => {
  stubApi(() => ALLOWED);
  const rv = seat((x) => { x.locks.held[0].piece = 'm-not-on-this-map'; });
  const r = await room(rv);
  assert.equal(r.view.querySelectorAll('.rl-tm-held').length, 0);
  await pickLevy(r);
  assert.equal(r.view.querySelectorAll('.rl-tm-held').length, 0);
  for (const name of [LEVY, 'The Norra Kites', 'The Norra Herald']) {
    assert.equal(piecePanel(rv, { kind: 'force', name }, () => {}, {}).querySelector('.rl-piece-held'), null, name);
  }
});

test('with locks off no piece carries a held order', async () => {
  stubApi();
  const rv = seat(unlocked);
  const r = await room(rv);
  assert.equal(r.view.querySelectorAll('.rl-tm-held').length, 0);
  assert.doesNotMatch(r.view.querySelector('g.rl-tm-stack').getAttribute('aria-label'), /held/);
  await pickLevy(r);
  assert.equal(r.view.querySelectorAll('.rl-tm-held').length, 0);
  assert.doesNotMatch(markOn(r.view, LEVY).getAttribute('aria-label'), /Held/);
  assert.equal(piecePanel(rv, { kind: 'force', name: LEVY }, () => {}, {}).querySelector('.rl-piece-held'), null);
});

// --- rule 4: the decider's ask, opened on the words and his own forms -------------------------

test('the decider sees each ask in his list and opens it on the order\'s words and his own form', () => {
  const rv = seat();
  const [line] = needLines(rv).filter((l) => l.kind === 'ask');
  const ask = fixture.locks.asks[0];
  assert.equal(line.key, ask.id);
  assert.equal(line.what, ask.words);
  assert.equal(line.from, 'Kara Lind');
  assert.deepEqual(line.action, { word: 'Open', to: 'ask', id: ask.id });
  const filed = [];
  const sheet = locks.askSheet(rv, ask.id, { onFile: (v) => filed.push(v) });
  assert.match(words(sheet), /Kara Lind asks for your leave/);
  assert.equal(words(sheet.querySelector('.rl-ask-words')), 'March (Force Norra levy, To Isle)');
  assert.equal(words(sheet.querySelector('.rl-ask-form')), 'Set watch (Zone The Gulf, Order Guard)');
  sheet.querySelector('button.rl-ask-file').click();
  assert.deepEqual(filed, [{ lever: 'set_watch', params: { zone: 'gulf', order: 'guard' } }]);
});

test('an ask with no form of his own that would allow it says so', () => {
  const rv = seat((x) => { x.locks.asks[0].forms = []; });
  const sheet = locks.askSheet(rv, rv.locks.asks[0].id, {});
  assert.equal(sheet.querySelectorAll('button').length, 0);
  assert.match(words(sheet), /None of your own forms allows it\./);
  assert.equal(locks.askSheet(rv, 'gone', {}), null, 'an ask no longer there opens nothing');
});

// --- rule 5: the client decides nothing ------------------------------------------------------

test('a lock is never worked out on the client: a move the server allows is not marked, whatever is held', async () => {
  stubApi(() => ALLOWED);
  const rv = seat();
  assert.ok(rv.locks.held.some((l) => /To Isle/.test(l.words)), 'a held march to the Isle is in the block');
  const r = await room(rv);
  const view = await pickLevy(r);
  assert.equal(view.querySelectorAll('g.rl-map-target.locked').length, 0);
  litArea(view, 'isle').click();
  await settle();
  assert.equal(chip(r.view).querySelector('.rl-lock-acts'), null);
});

test('a move the server locks is marked though nothing is held yet', async () => {
  stubApi((b) => (b.params.to === 'sudland_coast' ? { check: 'locked', who: 'Norra\'s assembly', reason: 'Held until Norra\'s assembly allows it.' } : ALLOWED));
  const r = await room(seat((x) => { x.locks = { held: [], asks: [] }; }));
  const view = await pickLevy(r);
  assert.deepEqual(view.querySelectorAll('g.rl-map-target.locked').map((g) => g.getAttribute('data-area')), ['sudland_coast']);
  assert.equal(words(litArea(view, 'sudland_coast').querySelector('.rl-tm-lock')), 'Norra\'s assembly');
});

test('another seat\'s held order is never drawn as the seat\'s own: an ask is only an ask', () => {
  const rv = seat((x) => { x.locks.held = []; });
  const lines = needLines(rv);
  assert.equal(lines.filter((l) => l.kind === 'held').length, 0, 'no held line of anyone else\'s');
  assert.equal(lines.filter((l) => l.kind === 'ask').length, 1);
  const list = needsList(rv, lines, {});
  assert.equal(list.querySelectorAll('li.rl-need').filter((li) => li.getAttribute('data-kind') === 'held').length, 0);
});

test('model text reaches the page as text only', () => {
  const rv = seat((x) => {
    x.locks.held[0].words = '<b>March</b> <img src=x onerror=alert(1)>';
    x.locks.asks[0].words = '<script>bad()</script>';
    x.locks.asks[0].by = '<i>Kara</i>';
  });
  const list = needsList(rv, needLines(rv), {});
  assert.equal(list.querySelectorAll('b').length + list.querySelectorAll('img').length + list.querySelectorAll('i').length, 0);
  assert.match(words(list), /<b>March<\/b>/);
  const sheet = locks.askSheet(rv, rv.locks.asks[0].id, {});
  assert.equal(sheet.querySelectorAll('script').length + sheet.querySelectorAll('i').length, 0);
  assert.match(words(sheet), /<script>bad\(\)<\/script>/);
});

// --- send it anyway (DFB): a third choice with the server's price, and a confirm step -----------

const PRICE = fixture.lock_check[0].price;
const PRICED = { ...LOCKED, price: PRICE };
const ANYWAY = 'Send it anyway';

test('a form whose check offers sending anyway shows a third choice with the server\'s price, sent only after the confirm', async () => {
  const anyway = [];
  const item = standardForm(WATCH, {
    onSubmit: () => {}, check: async () => PRICED, onAsk: () => {}, onAnyway: (v) => anyway.push(v), entities: [],
  });
  document.body.append(item);
  submit(item);
  await settle();
  const choice = item.querySelector('.rl-lock-choice');
  assert.deepEqual(buttonsOf(choice.querySelector('.rl-lock-acts')), ['File it to be held', 'Ask Ilse Varg', ANYWAY]);
  assert.equal(words(choice.querySelector('.rl-lock-price')), PRICE, 'the price as the server worded it');
  choice.querySelector('.rl-lock-anyway').click();
  assert.equal(anyway.length, 0, 'the first press sends nothing');
  const confirm = choice.querySelector('.rl-lock-confirm');
  assert.ok(confirm, 'it asks to be sure');
  assert.match(words(confirm), /without leave/);
  confirm.querySelector('.rl-lock-back').click();
  assert.equal(choice.querySelector('.rl-lock-confirm'), null, 'Back leaves the three choices');
  assert.deepEqual(buttonsOf(choice.querySelector('.rl-lock-acts')), ['File it to be held', 'Ask Ilse Varg', ANYWAY]);
  choice.querySelector('.rl-lock-anyway').click();
  choice.querySelector('.rl-lock-confirm .rl-lock-yes').click();
  assert.equal(anyway.length, 1, 'sent once, after the confirm');
  assert.equal(anyway[0].lever, 'set_watch');
  assert.equal(item.querySelector('.rl-lock-choice'), null, 'and the choice goes');
  item.remove();
});

test('no third choice is drawn when the server did not offer sending anyway', async () => {
  const item = standardForm(WATCH, {
    onSubmit: () => {}, check: async () => LOCKED, onAsk: () => {}, onAnyway: () => {}, entities: [],
  });
  document.body.append(item);
  submit(item);
  await settle();
  const choice = item.querySelector('.rl-lock-choice');
  assert.deepEqual(buttonsOf(choice.querySelector('.rl-lock-acts')), ['File it to be held', 'Ask Ilse Varg']);
  assert.equal(choice.querySelector('.rl-lock-price'), null);
  item.remove();
  const bare = locks.lockedChoice({ ...LOCKED, price: '' }, { file: () => {}, ask: () => {}, send: () => {} });
  assert.equal(bare.querySelector('.rl-lock-anyway'), null, 'an empty price offers nothing');
});

test('a locked move the server lets the seat send anyway offers it on the chip, filed as lever-anyway after the confirm', async () => {
  stubApi((b) => (b.params.to === 'isle' ? PRICED : ALLOWED));
  const r = await room(seat());
  await pickLevy(r);
  litArea(r.view, 'isle').click();
  await settle();
  const c = chip(r.view);
  assert.deepEqual(buttonsOf(c.querySelector('.rl-lock-acts')), ['File it to be held', 'Ask Ilse Varg', ANYWAY]);
  assert.equal(words(c.querySelector('.rl-lock-price')), PRICE);
  c.querySelector('.rl-lock-anyway').click();
  assert.deepEqual(r.acts, [], 'nothing before the confirm');
  c.querySelector('.rl-lock-confirm .rl-lock-yes').click();
  assert.deepEqual(r.acts.map((a) => [a.action, a.body]), [['lever-anyway', { lever: 'move_piece', params: { force: 'norra_levy', to: 'isle' } }]]);
});

test('a held order the seat may send anyway carries the price in its line, and sends only after the confirm', () => {
  const rv = seat();
  const [priced, plain] = rv.locks.held;
  const seen = [];
  const list = needsList(rv, needLines(rv), { onAction: (line) => seen.push(line.action) });
  const row = (id) => list.querySelectorAll('li.rl-need').find((li) => li.getAttribute('data-kind') === 'held' && li.getAttribute('data-need') === id);
  assert.equal(row(plain.id).querySelector('.rl-lock-choice'), null, 'no price, no third choice');
  const r = row(priced.id);
  assert.equal(words(r.querySelector('.rl-lock-price')), PRICE);
  r.querySelector('.rl-lock-anyway').click();
  assert.deepEqual(seen, []);
  r.querySelector('.rl-lock-confirm .rl-lock-yes').click();
  assert.deepEqual(seen, [{ word: ANYWAY, to: 'send-anyway', id: priced.id }]);
});

// --- the incident (DFB rule 2): the superior's three answers, the commander's outcome -----------

const incidentRow = (list, id) => list.querySelectorAll('li.rl-need').find((li) => li.getAttribute('data-kind') === 'incident' && li.getAttribute('data-need') === id);

test('an open incident is in the superior\'s list with its three answers, each sent as the server names it', () => {
  const rv = seat();
  const [inc] = rv.locks.incidents;
  const [line] = needLines(rv).filter((l) => l.kind === 'incident');
  assert.equal(line.key, inc.id);
  assert.equal(line.what, inc.words);
  assert.equal(line.due, inc.due);
  const seen = [];
  const list = needsList(rv, needLines(rv), { onAction: (l) => seen.push(l.action) });
  const r = incidentRow(list, inc.id);
  assert.ok(r, 'the incident is a row');
  assert.match(words(r), /Kara Lind: Sent an order without leave\./);
  assert.equal(r.querySelector('.rl-need-from'), null, 'the incident names its sender in its own words');
  const acts = r.querySelectorAll('button.rl-need-answer');
  assert.deepEqual(acts.map((b) => words(b)), ['Back it', 'Disown it', 'Dismiss it']);
  acts[1].click();
  assert.deepEqual(seen, [{ word: 'Disown it', to: 'incident', id: inc.id, verdict: 'disowned' }]);
});

test('the commander\'s incident shows with its outcome and nothing to press', () => {
  const told = { id: 'INC2', words: 'Ilse Varg was asked to answer for your order sent without leave.', due: '1900-04-04', verdict: 'backed', answers: [] };
  const waiting = { ...told, id: 'INC3', verdict: null };
  const rv = seat((x) => { x.locks.incidents = [told, waiting]; });
  const list = needsList(rv, needLines(rv), {});
  const done = incidentRow(list, 'INC2');
  assert.match(words(done), /was asked to answer/);
  assert.match(words(done.querySelector('.rl-need-outcome')), /backed/);
  assert.equal(done.querySelectorAll('button.rl-need-answer').length, 0);
  assert.match(words(incidentRow(list, 'INC3').querySelector('.rl-need-outcome')), /Not answered yet/);
});

test('answers are drawn only as the server sends them: an incident with none offers none', () => {
  const rv = seat((x) => { x.locks.incidents[0].answers = ['backed']; });
  const list = needsList(rv, needLines(rv), {});
  assert.deepEqual(incidentRow(list, rv.locks.incidents[0].id).querySelectorAll('button.rl-need-answer').map((b) => words(b)), ['Back it']);
  const off = seat((x) => { delete x.locks.incidents; });
  assert.equal(needLines(off).filter((l) => l.kind === 'incident').length, 0, 'no incidents block, no line');
});
