// True playback: when the room opens on a wake the seat has not watched, it plays that wake's
// steps from the catch-up reply on the map, day by day: on each day what moved against the seat
// first (papers, holders), then its own orders and pieces, then the stakes. Several missed wakes play in turn inside the
// What you missed sheet and end on the "when you come back" line. The range comes from the
// server; the played mark lives in the page only. The reel that ran before the wake is gone.
// Reduced motion shows still frames; Skip ends it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const overlay = await import('../js/views/realism-overlay.js');
const play = await import('../js/views/realism-playback.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { missedSheet } = await import('../js/views/realism-happened.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const TMAP = fixture.territory_map;
const [HERALD, KITES, LEVY] = TMAP.marks;
const keyOf = (m) => m.piece?.key ?? m.key;
const ORDER = fixture.record.orders[0];

// PBF's two-moves case: a missed wake with two of the seat's own moves between two papers (the
// second a scripted leg, shaped exactly like an ordered one); the enemy's move gave no step
const paper = (on, title) => ({ kind: 'paper', on, paper: `p-${on}`, title });
const move = (on, m, left, entered) => ({ kind: 'move', on, piece: keyOf(m), left, entered });
const TWO_MOVES = {
  number: 2, opened: '16 April 1900', days_passed: 14, papers: 2, filed: [], settled: [],
  steps: [
    paper('1900-04-03', 'The harbour count, 2 April'),
    move('1900-04-07', LEVY, 'norra_plain', 'norra_hills'),
    move('1900-04-09', HERALD, 'norra_plain', 'the_gulf'),
    paper('1900-04-16', 'The harbour count, 15 April'),
  ],
};
const ALL_KINDS = [
  { kind: 'stake', on: '1900-04-02', name: 'The Gulf crossing', what: 'moved' },
  move('1900-04-03', LEVY, 'norra_plain', 'norra_hills'),
  { kind: 'order', on: '1900-04-04', order: ORDER.id, what: 'filed' },
  { kind: 'holder', on: '1900-04-05', area: 'isle', holder: { key: 's', name: 'Sudland', relation: 'enemy' }, was: { key: 'n', name: 'Norra', relation: 'own' } },
  { kind: 'halt', on: '1900-04-06', piece: keyOf(KITES), area: 'norra_plain', to: 'the_gulf', reason: 'too little fuel' },
  paper('1900-04-07', 'A battle report: the Isle'),
];
const page = (number, steps, extra = {}) => ({
  number, opened: `${number} May 1900`, days_passed: 7, papers: 0, filed: [], settled: [], steps, ...extra,
});
const player = (pages, more = {}) => play.wakePlayer({
  pages, map: TMAP, shapes: SHAPES, record: fixture.record, comeBack: 'When you come back: nothing is due.', reduced: true, ...more,
});
/** A fake clock and animation-frame queue: `flush(ms)` runs one frame `ms` later. */
function clock() {
  let t = 0;
  let queue = [];
  return {
    now: () => t,
    frame: (cb) => { queue.push(cb); return queue.length; },
    flush(ms = 20) {
      t += ms;
      const run = queue;
      queue = [];
      for (const cb of run) cb(t);
    },
    waiting: () => queue.length,
  };
}
const frames = (el) => el.querySelectorAll('li.rl-plb-step');
const kinds = (el) => frames(el).map((li) => li.getAttribute('data-kind'));
// the feed's own steps: a room also plays the rounds of the seat's battles fought in a wake
const fed = (el) => frames(el).filter((li) => li.getAttribute('data-kind') !== 'round');
const fedKinds = (el) => fed(el).map((li) => li.getAttribute('data-kind'));

// rule 1: against the seat first, then its own orders and pieces, then the stakes

test('a wake plays its days in order, and on one day what moved against the seat, then its own orders and pieces, then the stakes', () => {
  assert.deepEqual(play.playOrder(ALL_KINDS).map((s) => s.kind), ['holder', 'paper', 'move', 'order', 'halt', 'stake']);
  installDom();
  assert.deepEqual(kinds(player([page(4, ALL_KINDS)])), ['stake', 'move', 'order', 'holder', 'halt', 'paper']);
  const oneDay = ALL_KINDS.map((s) => ({ ...s, on: '1900-04-05' }));
  assert.deepEqual(kinds(player([page(4, oneDay)])), ['holder', 'paper', 'move', 'order', 'halt', 'stake']);
});

test('PBF\'s two-moves case: both own moves in order, the papers first, and no enemy move', () => {
  installDom();
  // the enemy's piece changed place on the seat's map too: the playback reads steps, never the map
  const enemy = { ...LEVY, key: 'm-enemy', name: 'The Sudland Levy', side: 'enemy', piece: null };
  const el = player([TWO_MOVES], { map: { ...TMAP, marks: [...TMAP.marks, enemy] } });
  assert.deepEqual(kinds(el), ['paper', 'move', 'move', 'paper']);
  const lines = frames(el).map((li) => words(li.querySelector('.rl-plb-cap')));
  assert.deepEqual(lines.slice(1, 3), ['The Norra Levy moved from The Norra Plain to The Norra Hills', 'The Norra Herald moved from The Norra Plain to The Gulf']);
  assert.ok(!words(el).includes('Sudland Levy'));
  assert.equal(frames(el).length, TWO_MOVES.steps.length);
});

test('each kind of step reads as a plain line, with the record\'s words for an order', () => {
  installDom();
  const lines = frames(player([page(4, ALL_KINDS)])).map((li) => words(li.querySelector('.rl-plb-cap')));
  assert.deepEqual(lines, [
    'The Gulf crossing: moved',
    'The Norra Levy moved from The Norra Plain to The Norra Hills',
    `Your order “${ORDER.asked}”: filed`,
    'The Isle passed to Sudland from Norra',
    'The Norra Kites held in The Norra Plain: the step to The Gulf was refused (too little fuel)',
    'A paper reached you: A battle report: the Isle',
  ]);
});

test('a move lights where the piece left and where it entered on the seat\'s own map', () => {
  installDom();
  const c = clock();
  const el = player([TWO_MOVES], { reduced: false, clock: c });
  const map = el.querySelector('figure.rl-plb-map svg');
  assert.ok(map, 'the territory map is drawn');
  const lit = () => [map.querySelectorAll('.rl-plb-from').map((p) => p.getAttribute('data-area')), map.querySelectorAll('.rl-plb-to').map((p) => p.getAttribute('data-area'))];
  assert.deepEqual(lit(), [[], []]);
  c.flush(play.DAY_MS * 1 + 10); // 3 April: a paper first, nothing lit
  assert.deepEqual(lit(), [[], []]);
  c.flush(play.DAY_MS * 4); // 7 April: the Levy entered the hills
  assert.deepEqual(lit().map((a) => [...new Set(a)]), [['norra_plain'], ['norra_hills']]);
  c.flush(play.DAY_MS * 2); // 9 April: the Herald entered the gulf
  assert.deepEqual(lit().map((a) => [...new Set(a)]), [['norra_plain'], ['the_gulf']]);
});

/**
 * The room for the toy seat, in the page, with `catchup` behind it. `seen`: the What happened
 * sheet of wake 3 already shown in this browser. `days`: the latest page's days passed.
 */
function toyRoom(catchup, { seen = false, days = 6 } = {}) {
  const doc = installDom();
  const id = `g-${Math.random()}`;
  const asked = [];
  const writes = [];
  const store = new Map(seen ? [[`rv.happened.${id}`, '3']] : []);
  globalThis.localStorage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => { writes.push(k); store.set(k, v); }, removeItem: () => {} };
  api.realism = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  api.catchup = async (body = {}) => { asked.push(body); return catchup(body); };
  const rv = { ...structuredClone(fixture), documents: fixture.listing, map: TMAP, wake_tick: 1 };
  rv.record.wake.days_passed = days;
  const game = { id, name: 'Toy', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Ilse' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {} };
  doc.body.append(realismRoom(ctx));
  return { doc, ctx, asked, writes };
}
const latestOnly = (body) => (body.first === 3 ? { first: 3, last: 3, pages: [page(3, TWO_MOVES.steps)] } : { first: 3, last: 2, pages: [] });
const settle = async () => { await flush(); await flush(); };

test('a room that opens on a wake it has not watched plays it inside that wake\'s What happened sheet', async () => {
  const { doc, ctx, asked } = toyRoom(latestOnly);
  await settle();
  // rule 3: the server names the missed range; the wake just opened is the record's own page
  assert.deepEqual(asked, [{}, { first: 3, last: 3 }]);
  const sheet = doc.body.querySelector('dialog.rl-hap');
  assert.ok(sheet.open);
  const played = sheet.querySelector('section.rl-plb');
  assert.ok(played, 'where forces moved is the playback');
  assert.deepEqual(fedKinds(sheet), ['paper', 'move', 'move', 'paper']);
  assert.ok(sheet.children.indexOf(played) < sheet.children.indexOf(sheet.querySelector('.rl-hap-actions')), 'above To the desk');
  assert.equal(doc.body.querySelectorAll('dialog.rl-plb-dialog').length, 0, 'no second dialog over the sheet');
  // the minute poll's re-read keeps the playback where it stands, and asks nothing more
  await ctx.refresh();
  await settle();
  assert.equal(doc.body.querySelector('dialog.rl-hap section.rl-plb'), played);
  assert.equal(asked.length, 2);
  buttons(doc.body.querySelector('dialog.rl-hap'), 'To the desk')[0].click();
  await ctx.refresh();
  await settle();
  assert.equal(doc.body.querySelectorAll('section.rl-plb').length, 0, 'not played again in this page');
  assert.equal(asked.length, 2);
  delete globalThis.localStorage;
});

test('the played mark is never stored: a wake whose sheet this browser has seen plays again in a fresh page, in its own dialog', async () => {
  const { doc, ctx, asked, writes } = toyRoom(latestOnly, { seen: true });
  await settle();
  assert.equal(doc.body.querySelector('dialog.rl-hap'), null);
  const shown = doc.body.querySelectorAll('dialog.rl-plb-dialog');
  assert.equal(shown.length, 1);
  assert.ok(shown[0].open);
  assert.deepEqual(fedKinds(shown[0]), ['paper', 'move', 'move', 'paper']);
  for (const k of writes) assert.ok(!/play|plb|watch/i.test(k), k);
  const played = shown[0].querySelector('section.rl-plb');
  await ctx.refresh();
  await settle();
  const kept = doc.body.querySelectorAll('dialog.rl-plb-dialog');
  assert.equal(kept.length, 1);
  assert.equal(kept[0].querySelector('section.rl-plb'), played);
  kept[0].close();
  await ctx.refresh();
  await settle();
  assert.equal(doc.body.querySelectorAll('dialog.rl-plb-dialog').length, 0);
  assert.equal(asked.length, 2);
  delete globalThis.localStorage;
});

test('a room drawn again while the catch-up reply is out still plays the wake, in the newest draw', async () => {
  let answer;
  const { doc, ctx } = toyRoom((body) => (body.first === 3 ? new Promise((r) => { answer = r; }) : { pages: [] }), { seen: true });
  await flush();
  await ctx.refresh();
  answer({ pages: [page(3, TWO_MOVES.steps)] });
  await settle();
  const shown = doc.body.querySelectorAll('dialog.rl-plb-dialog');
  assert.equal(shown.length, 1);
  assert.ok(shown[0].open);
  delete globalThis.localStorage;
});

test('the game\'s start plays nothing: no days have passed on the first page', async () => {
  const { doc, asked } = toyRoom(latestOnly, { days: 0 });
  await settle();
  assert.deepEqual(asked, [{}]);
  assert.equal(doc.body.querySelectorAll('section.rl-plb').length, 0);
  delete globalThis.localStorage;
});

// rule 2: several wakes, each in turn, inside the missed-wakes pages

test('a seat away for several wakes gets each wake in turn, ending on the "when you come back" line', () => {
  installDom();
  const el = player([page(4, [paper('1900-05-04', 'Four')]), page(2, TWO_MOVES.steps), page(3, [])]);
  const items = el.querySelectorAll('ol.rl-plb-frames li');
  assert.deepEqual(items.filter((li) => li.classList.contains('rl-plb-wake')).map((li) => li.getAttribute('data-wake')), ['2', '4']);
  assert.deepEqual(frames(el).map((li) => li.getAttribute('data-wake')), ['2', '2', '2', '2', '4']);
  assert.ok(items.at(-1).classList.contains('rl-plb-end'));
  assert.equal(words(items.at(-1)), 'When you come back: nothing is due.');
});

test('the What you missed sheet holds the playback, over its pages', () => {
  installDom();
  const play = player([page(2, TWO_MOVES.steps), page(3, [paper('1900-05-03', 'Three')])]);
  const sheet = missedSheet({ pages: [page(2, TWO_MOVES.steps), page(3, [])], record: fixture.record, play, onClose: () => {} });
  assert.equal(sheet.querySelector('section.rl-plb'), play);
  assert.equal(sheet.children.indexOf(play), 1);
  assert.equal(sheet.querySelectorAll('section.rl-missed-page').length, 2);
});

test('several missed wakes and the one just opened play in turn in the missed sheet, and nowhere else', async () => {
  const doc = installDom();
  api.realism = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  api.catchup = async (body = {}) => (body.first === 3
    ? { first: 3, last: 3, pages: [page(3, [paper('1900-05-03', 'Now')])] }
    : { first: 1, last: 2, pages: [page(2, TWO_MOVES.steps), page(1, [paper('1900-05-01', 'One')])] });
  const game = { id: `g-${Math.random()}`, name: 'Toy', ruleset: 'realism', phase: 'play', host: true,
    view: { realism: { ...structuredClone(fixture), documents: fixture.listing, map: TMAP, wake_tick: 1 }, seat: { name: 'Ilse' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => {}, go: () => {} };
  doc.body.append(realismRoom(ctx));
  await flush();
  await flush();
  const sheet = doc.body.querySelector('dialog.rl-missed');
  assert.ok(sheet?.open);
  assert.deepEqual(fed(sheet).map((li) => li.getAttribute('data-wake')), ['1', '2', '2', '2', '2', '3']);
  assert.equal(doc.body.querySelectorAll('dialog.rl-plb-dialog').length, 0);
});

// rule 3: the played mark is the page's alone

// rule 4: the pre-run reel and ui.runFrom are gone

test('the room keeps no map from before the run and lays no reel over a running wake', () => {
  const room = read('js/views/realism-room.js');
  assert.ok(!room.includes('runFrom'));
  assert.ok(!room.includes('withPlayback('));
  assert.equal(overlay.withPlayback, undefined);
  installDom();
  const layer = overlay.wakeOverlay({ message: 'The day is running', lines: ['A line.'], map: fixture.map, orders: fixture.record.orders });
  assert.equal(layer.querySelector('section.rl-ovl-play'), null);
  assert.equal(layer.querySelectorAll('li.rl-ovl-step').length, 0);
});

// rule 5: reduced motion and Skip

test('under reduced motion every frame stands still on screen, the end line too, and nothing is timed', () => {
  installDom();
  const c = clock();
  const el = player([TWO_MOVES], { reduced: true, clock: c });
  assert.ok(el.classList.contains('still'));
  assert.equal(c.waiting(), 0);
  assert.ok(el.querySelectorAll('ol.rl-plb-frames li').every((li) => !li.hasAttribute('hidden')));
});

test('with motion, each frame on its day; Skip ends it at once and the end line shows', () => {
  installDom();
  const c = clock();
  let ended = 0;
  const el = player([TWO_MOVES], { reduced: false, clock: c, onEnd: () => { ended += 1; } });
  const shown = () => el.querySelectorAll('ol.rl-plb-frames li').filter((li) => !li.hasAttribute('hidden'));
  c.flush(play.DAY_MS + 10);
  assert.equal(frames(el).filter((li) => !li.hasAttribute('hidden')).length, 1);
  assert.equal(el.querySelector('li[aria-current="step"]'), frames(el)[0]);
  c.flush(play.DAY_MS * 4);
  assert.equal(frames(el).filter((li) => !li.hasAttribute('hidden')).length, 2);
  const skip = buttons(el, 'Skip')[0];
  skip.click();
  assert.equal(ended, 1);
  assert.equal(shown().length, el.querySelectorAll('ol.rl-plb-frames li').length);
  assert.ok(el.querySelector('li.rl-plb-end'));
  for (let n = 0; n < 40; n += 1) c.flush(play.DAY_MS); // a frame still due after Skip changes nothing
  assert.equal(ended, 1);
});

test('in the missed sheet, which has its own way out, Skip shows everything and then goes', () => {
  installDom();
  const el = player([TWO_MOVES], { reduced: false, clock: clock() });
  buttons(el, 'Skip')[0].click();
  assert.equal(el.querySelectorAll('button').length, 0);
  assert.ok(el.querySelectorAll('ol.rl-plb-frames li').every((li) => !li.hasAttribute('hidden')));
  assert.equal(player([TWO_MOVES]).querySelectorAll('button').length, 0, 'reduced: nothing to skip');
});

test('the dialog\'s Skip closes it', () => {
  installDom();
  let closed = 0;
  const d = play.playbackDialog({ pages: [TWO_MOVES], map: TMAP, shapes: SHAPES, record: fixture.record, reduced: false, clock: clock(), onClose: () => { closed += 1; } });
  d.showModal();
  buttons(d, 'Skip')[0].click();
  assert.equal(closed, 1);
  assert.ok(!d.open);
});

// nothing says who closed a wake or how a seat was played

test('the playback never says who closed a wake or who played the seat', () => {
  installDom();
  const el = player([page(3, TWO_MOVES.steps, { aide_filed: ['Hold the line'], held_dropped: ['A late order'] })]);
  const said = words(el);
  for (const w of ['closed', 'aide', 'Aide', 'committed', 'Hold the line', 'A late order']) assert.ok(!said.includes(w), w);
});

test('a wake with no steps plays nothing', () => {
  installDom();
  assert.equal(player([page(3, [])]), null);
  assert.equal(player([]), null);
});

// PBH: when a wake's steps hold the seat's own groups moving or a count changing, the playback
// plays the floor: the groups' tokens shifting and the counts changing, from the feed alone

const grp = (on, group, name, change, support, why = 'a battle lost', reach = 'felt') => ({ kind: 'group', on, group, name, change, support, why, reach });
const cnt = (on, yeas, nays, was, vote = 'house') => ({ kind: 'count', on, order_id: 'o-9', key: 'harbour_bill', title: 'The Harbour Bill', vote, yeas, nays, was });
// the Smiths fed at 47 though the seat's home block holds 50: the floor reads the feed, never the home block
const POLITICAL = [
  paper('1900-04-02', 'The harbour count, 1 April'),
  grp('1900-04-03', 'smiths', "The Smiths' Guild", -3, 47),
  cnt('1900-04-03', 38, 62, [40, 60]),
  grp('1900-04-05', 'greens', 'The Greens', 2, 62, 'a statement', 'reported'),
  cnt('1900-04-05', 41, 59, [38, 62]),
];
const floorOf = (el) => el.querySelector('figure.rl-plb-floor');
const support = (el, g) => Number(floorOf(el).querySelector(`.rl-plb-token[data-group="${g}"]`).getAttribute('data-support'));
const tally = (el) => words(floorOf(el).querySelector('.rl-plb-vote .rl-plb-tally'));
const shownFig = (el, cls) => { const f = el.querySelector(`figure.${cls}`); return Boolean(f) && !f.hasAttribute('hidden'); };

test('PBH rule 1: a wake of group moves and counts with no piece moving plays the floor, in the order sent', () => {
  installDom();
  const c = clock();
  const el = player([page(5, POLITICAL)], { reduced: false, clock: c });
  assert.ok(floorOf(el), 'the floor is drawn');
  assert.ok(shownFig(el, 'rl-plb-floor'));
  assert.ok(!shownFig(el, 'rl-plb-map'), 'the map does not play a wake with nothing moving on it');
  assert.deepEqual(kinds(el), ['paper', 'group', 'count', 'group', 'count']);
  // only the groups and the vote the feed carried, each where the feed puts it before its move
  assert.deepEqual(floorOf(el).querySelectorAll('.rl-plb-token').map((t) => t.getAttribute('data-group')), ['smiths', 'greens']);
  assert.ok(!words(floorOf(el)).includes('The Greys'));
  assert.deepEqual([support(el, 'smiths'), support(el, 'greens')], [50, 60]);
  assert.equal(tally(el), '40 yea · 60 nay');
  // 7 days to 5 April: the Smiths move over 3 April, the Greens over 5 April
  c.flush(play.DAY_MS * 4.5);
  assert.ok(support(el, 'smiths') < 50 && support(el, 'smiths') > 47, 'the token shifts over its day');
  assert.equal(support(el, 'greens'), 60);
  // while a token shifts and a track moves, the figures written are the ones the feed sent, never one between
  assert.equal(words(floorOf(el).querySelector('.rl-plb-token[data-group="smiths"] .rl-plb-tfig')), '50');
  assert.equal(tally(el), '40 yea · 60 nay');
  c.flush(play.DAY_MS * 0.6);
  assert.equal(support(el, 'smiths'), 47);
  assert.equal(tally(el), '38 yea · 62 nay');
  assert.equal(support(el, 'greens'), 60);
  assert.equal(el.querySelector('li[aria-current="step"]').getAttribute('data-kind'), 'count');
  c.flush(play.DAY_MS * 2);
  assert.equal(support(el, 'greens'), 62);
  assert.equal(tally(el), '41 yea · 59 nay');
});

test('PBH: a group move and a count change read as plain lines', () => {
  installDom();
  const lines = frames(player([page(5, POLITICAL)])).map((li) => words(li.querySelector('.rl-plb-cap')));
  assert.deepEqual(lines.slice(1, 3), [
    "The Smiths' Guild down 3: a battle lost, felt at home",
    'The Harbour Bill, house vote: 38 yea and 62 nay, from 40 and 60',
  ]);
  assert.equal(lines[3], 'The Greens up 2: a statement, by report');
});

test('PBH rule 2: a wake with pieces moving and the floor moving plays the map first and the floor second', () => {
  installDom();
  const c = clock();
  const both = page(6, [grp('1900-04-03', 'smiths', "The Smiths' Guild", -3, 47), cnt('1900-04-03', 38, 62, [40, 60]), move('1900-04-07', LEVY, 'norra_plain', 'norra_hills')]);
  const el = player([both], { reduced: false, clock: c });
  assert.deepEqual(kinds(el), ['move', 'group', 'count'], 'the map\'s steps first, though the group moved earlier');
  assert.ok(shownFig(el, 'rl-plb-map'));
  assert.ok(!shownFig(el, 'rl-plb-floor'));
  c.flush(play.DAY_MS * 7 + 10); // the map's clock ends, the floor's begins
  assert.ok(!frames(el)[0].hasAttribute('hidden'));
  assert.ok(frames(el)[1].hasAttribute('hidden'), 'the group has not played yet');
  assert.ok(shownFig(el, 'rl-plb-floor'));
  assert.ok(!shownFig(el, 'rl-plb-map'));
  assert.equal(support(el, 'smiths'), 50);
  c.flush(play.DAY_MS * 4);
  assert.equal(support(el, 'smiths'), 47);
  assert.equal(tally(el), '38 yea · 62 nay');
  assert.ok(!frames(el)[2].hasAttribute('hidden'));
});

test('PBH rule 3: a wake with no group move and no count change plays as before, with no floor', () => {
  installDom();
  const el = player([TWO_MOVES], { reduced: false, clock: clock() });
  assert.equal(floorOf(el), null);
  assert.ok(shownFig(el, 'rl-plb-map'));
});

test('PBH: reduced motion and Skip show the floor where the feed leaves it, with nothing timed', () => {
  installDom();
  const c = clock();
  const still = player([page(5, POLITICAL)], { reduced: true, clock: c });
  assert.equal(c.waiting(), 0);
  assert.deepEqual([support(still, 'smiths'), support(still, 'greens')], [47, 62]);
  assert.equal(tally(still), '41 yea · 59 nay');
  const both = page(6, [...POLITICAL, move('1900-04-07', LEVY, 'norra_plain', 'norra_hills')]);
  const el = player([both], { reduced: false, clock: clock() });
  buttons(el, 'Skip')[0].click();
  assert.ok(shownFig(el, 'rl-plb-map') && shownFig(el, 'rl-plb-floor'), 'both stand once all is shown');
  assert.deepEqual([support(el, 'smiths'), support(el, 'greens')], [47, 62]);
});
