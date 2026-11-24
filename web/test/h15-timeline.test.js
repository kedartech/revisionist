// The season on one timeline (STL), one test or more per rule, on a seat built here: 1. in the
// map-first room a strip at the foot of the map draws the season from today to its end as one
// line with a mark per dated thing, shaped by its kind; 2. a tap or Enter opens it to the same
// things as a list in date order, each with its date and its days from today, and a row opens
// its item where it lives; 3. a dated thing that comes or goes in the sitting is on or off the
// strip at the next redraw; 4. closed, the strip is 44 px tall; open, it covers at most 40
// percent of the map and the map's controls sit above it; 5. with no season's end the line runs
// to the latest day sent and says so, and with nothing dated the strip is not drawn; 6. the strip
// stays in full screen. Amended: a piece's arrival mark and the piece on the map light each
// other. Keeps: a mark is a dated thing the view sent; the client works out no day; the Classic
// layout draws no strip. Mutants: a mark for a day the view did not send; the strip covering the
// map's controls; a row that opens nothing.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { setRoomLayout } = await import('../js/views/realism-sheets.js');
const { hooksFor } = await import('../js/views/realism-theatre.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
const css = () => read('css/c-timeline.css').replace(/\/\*[\s\S]*?\*\//g, '');

const LEVY = 'The Norra Levy';

/**
 * The seat's view on 20 October 1941: the agenda's order due 26 October (also an open mandate
 * with 6 days left), three contests (24, 48 and 48 days left), the season's end in 48 days, a
 * conference opening on 25 October and voting on 30 October, and the levy under way to Harrow,
 * arriving 27 October; no battle waits. `change` edits it.
 */
function seat(change = () => {}) {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.documents = structuredClone(fixture.listing);
  rv.wake_tick = 1;
  rv.style = 'free';
  rv.wake = { ...rv.wake, deadline: '2999-01-01T00:00:00+00:00', you_committed: false, humans: 1, committed: 0 };
  rv.battles = [];
  // the fixture's incident is a dated line of the list too; these marks count the rest
  delete rv.locks.incidents;
  rv.conferences = { conferences: [{
    key: 'moscow', called_by: 'United Kingdom', invited: ['United Kingdom', 'United States'], text: 'Supply for Moscow', clauses: [],
    unanimous: false, called: '1941-10-25', voting_day: '1941-10-30', public: true, vote: null, can_vote: true, tallied: null, result: null, votes: [], agreement: null,
  }] };
  const levy = rv.map.marks.find((m) => m.name === LEVY);
  levy.piece.under_way = { path: [{ key: 'harrow', name: 'Harrow' }], step_due: '1941-10-27', arrives: '1941-10-27' };
  change(rv);
  return rv;
}

/** The whole room for view `rv` in `layout`, as the page draws it. */
function room(rv, layout = 'map', id = `h15-${Math.random()}`) {
  const doc = installDom();
  setRoomLayout(layout);
  api.realism = async () => ({});
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const game = { id, name: 'Autumn 1941', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {}, signOut: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  return { root, now: () => doc.body.firstElementChild, doc };
}

const strip = (root) => root.querySelector('.rl-tl');
const kinds = (el) => el.querySelectorAll('.rl-tl-axis .rl-tl-mark').map((m) => m.getAttribute('class').match(/k-(\w+)/)[1]);
const opened = (r) => { strip(r.root).querySelector('.rl-tl-head').click(); return strip(r.now()); };
const rows = (el) => el.querySelectorAll('.rl-tl-row');
const rowFor = (el, text) => rows(el).find((b) => words(b).includes(text));
const openSheet = (root) => root.querySelector('.rl-over')?.getAttribute('data-sheet') ?? null;

// rule 1: one line at the foot of the map, a mark per dated thing, shaped by its kind

test('the map-first room draws the season as one line at the foot of the map, a mark per dated thing', () => {
  const { root } = room(seat());
  const tl = strip(root);
  assert.ok(tl, 'the strip is drawn');
  assert.ok(tl.closest('.rl-mapfirst-map'), 'inside the map\'s own section');
  assert.equal(tl.querySelectorAll('.rl-tl-axis').length, 1, 'one line');
  assert.equal(tl.querySelectorAll('.rl-tl-axis .rl-tl-rule').length, 1);
  assert.ok(tl.querySelector('.rl-tl-axis .rl-tl-today'), 'today is its left end');
  // the order due 26 Oct (its mandate is the same thing), the levy's arrival, the conference's
  // opening and its vote, three contests and the season's end
  assert.deepEqual(kinds(tl), ['conf', 'own', 'own', 'conf', 'contest', 'contest', 'contest', 'end']);
  assert.match(words(tl.querySelector('.rl-tl-head')), /Season · 48 days/);
});

test('each kind has its own shape, not its own colour alone', () => {
  const { root } = room(seat());
  const shapeOf = (k) => strip(root).querySelector(`.rl-tl-axis .rl-tl-mark.k-${k}`).children[0];
  const drawn = ['own', 'conf', 'contest', 'end'].map((k) => {
    const s = shapeOf(k);
    return `${s.tagName.toLowerCase()} ${s.getAttribute('width') ?? ''}x${s.getAttribute('height') ?? ''}`;
  });
  assert.equal(new Set(drawn).size, 4, `four shapes: ${drawn.join(', ')}`);
});

test('a mark is only a day the view sent: each place is a count of days the view gives', () => {
  const { root } = room(seat());
  const at = strip(root).querySelectorAll('.rl-tl-axis .rl-tl-mark').map((m) => m.getAttribute('x'));
  // 6, 5 (25 Oct), 7 (27 Oct), 10 (30 Oct), 24, 48, 48 and 48 days of 48
  assert.deepEqual(at, ['10.42%', '12.50%', '14.58%', '20.83%', '50.00%', '100.00%', '100.00%', '100.00%']);
});

test('a decided contest, a tallied conference and a day before today are not marked', () => {
  const { root } = room(seat((rv) => {
    rv.conferences.conferences[0].tallied = '1941-10-19';
    rv.map.marks.find((m) => m.name === LEVY).piece.under_way.arrives = '1941-10-19';
  }));
  assert.deepEqual(kinds(strip(root)), ['own', 'contest', 'contest', 'contest', 'end']);
  assert.equal(words(strip(root)).includes('Kearny'), false, 'the decided contest has no mark');
});

test('a matter due at this wake\'s close is a mark of the seat\'s own at today', () => {
  const { root } = room(seat((rv) => { rv.battles = structuredClone(fixture.battles); }));
  const first = strip(root).querySelectorAll('.rl-tl-axis .rl-tl-mark')[0];
  assert.match(first.getAttribute('class'), /k-own due/);
  assert.equal(first.getAttribute('x'), '0.00%');
});

test('the Classic layout draws no strip', () => {
  const { root } = room(seat(), 'classic');
  assert.equal(strip(root), null);
});

// rule 2: a tap or Enter opens the list in date order; a row opens its item where it lives

test('the head is one button that opens and closes the list, focus kept on it', () => {
  const r = room(seat());
  const head = strip(r.root).querySelector('.rl-tl-head');
  assert.equal(head.tagName, 'BUTTON', 'a button: Enter and a tap both press it');
  assert.equal(head.getAttribute('aria-expanded'), 'false');
  assert.equal(strip(r.root).querySelector('.rl-tl-list'), null, 'closed, no list');
  head.click();
  const tl = strip(r.now());
  assert.equal(tl.querySelector('.rl-tl-head').getAttribute('aria-expanded'), 'true');
  assert.ok(tl.classList.contains('open'));
  assert.equal(document.activeElement, tl.querySelector('.rl-tl-head'), 'focus stays on the head');
  tl.querySelector('.rl-tl-head').click();
  assert.equal(strip(r.now()).querySelector('.rl-tl-list'), null, 'closed again');
});

test('open, the list holds the same things in date order, each with its date and days from today', () => {
  const tl = opened(room(seat()));
  const list = rows(tl).map((b) => [words(b.querySelector('.rl-tl-when')), words(b.querySelector('.rl-tl-what')), words(b.querySelector('.rl-tl-in'))]);
  assert.deepEqual(list, [
    ['25 Oct', 'Conference opens: Supply for Moscow', '5 d'],
    ['26 Oct', 'Keep the convoys moving to Iceland.', '6 d'],
    ['27 Oct', `${LEVY} arrives at Harrow`, '7 d'],
    ['30 Oct', 'Conference votes: Supply for Moscow', '10 d'],
    ['', 'Revising the Neutrality Act is decided', '24 d'],
    ['', 'The US-Japan negotiations is decided', '48 d'],
    ['', 'The war against Germany is decided', '48 d'],
    ['', 'The season ends', '48 d'],
  ]);
  assert.equal(rows(tl).length, kinds(tl).length, 'a row for every mark');
});

test('the list writes only days the view sent; its ticks count days, not dates', () => {
  const tl = opened(room(seat()));
  const sent = new Set(['25 Oct', '26 Oct', '27 Oct', '30 Oct', '']);
  for (const b of rows(tl)) assert.ok(sent.has(words(b.querySelector('.rl-tl-when'))), words(b));
  for (const t of tl.querySelectorAll('.rl-tl-tick')) assert.match(words(t), /^(Today|\d+ d)$/);
});

test('a row opens its item where it lives', () => {
  const cases = [
    ['Keep the convoys', 'matter'],
    ['Conference votes', 'diplomacy'],
    ['Revising the Neutrality Act', 'aims'],
    ['The season ends', 'aims'],
    [`${LEVY} arrives`, 'piece'],
  ];
  for (const [text, sheet] of cases) {
    const r = room(seat());
    const tl = opened(r);
    rowFor(tl, text).click();
    assert.equal(openSheet(r.now()), sheet, `${text} opens the ${sheet} sheet`);
    if (sheet === 'piece') assert.equal(words(r.now().querySelector('.rl-over-title')), LEVY);
  }
});

// rule 3: a dated thing that comes or goes in the sitting is on or off at the next redraw

test('a move filed adds its mark at the next redraw, and an answered matter takes its mark off', () => {
  const before = kinds(strip(room(seat()).root)).length;
  const filed = room(seat((rv) => {
    rv.map.marks.find((m) => m.name === 'The Norra Kites').piece.waiting = { order: 'o9', with_person: 'Harold R. Stark', until: '1941-10-22', withdrawable: true };
  }));
  assert.equal(kinds(strip(filed.root)).length, before + 1);
  assert.ok(rowFor(opened(filed), 'The Norra Kites: the order is with Harold R. Stark'), 'the filed move is a row');
  const answered = room(seat((rv) => { rv.agenda.items = []; rv.stakes.mandates = []; }));
  assert.equal(kinds(strip(answered.root)).length, before - 1);
  assert.equal(rowFor(opened(answered), 'Keep the convoys'), undefined);
});

test('a redraw in the same sitting rebuilds the strip from the view it reads', () => {
  const rv = seat();
  const r = room(rv);
  assert.equal(kinds(strip(r.root)).length, 8);
  rv.conferences.conferences = [];
  hooksFor(r.root.querySelector('.rl-mapfirst .rl-theatre')).onFull(false); // any redraw
  assert.equal(kinds(strip(r.now())).length, 6, 'the conference\'s two marks are gone');
});

// rule 4: 44 px closed; open over at most 40 percent of the map, the map's controls above it

test('c-timeline.css: the head is a 44 px target; open, the list is capped at 40 percent of the map; tokens only', () => {
  const sheet = css();
  assert.match(sheet, /\.rl-tl-head\s*\{[^}]*height:\s*44px/, 'closed, 44 px');
  assert.match(sheet, /\.rl-tl-body\s*\{[^}]*position:\s*absolute/, 'the list lies over the map');
  const caps = [...sheet.matchAll(/^\s*\.rl-tl-body\s*\{([^}]*)\}/gm)].map((m) => m[1]);
  assert.equal(caps.length, 2, 'the list\'s rule, and its place below 1024 px');
  for (const rule of caps) assert.match(rule, /max-height:\s*min\(var\(--rl-tl-cap, 100%\), calc\(0\.4 \* /, 'at most 40 percent of the map at every width');
  assert.match(sheet, /\.rl-mapfirst-map\.rl-tl-on\s*\{[^}]*--rl-tl-h:\s*44px/, 'the map is told how tall the strip is');
  assert.match(sheet, /\.rl-mapfirst-map\.rl-tl-open\s*\{[^}]*--rl-tl-h:/, 'and how far the open list reaches');
  assert.match(sheet, /\.rl-mapfirst-map\.rl-tl-on > \.rl-status\s*\{[^}]*bottom:\s*calc\(var\(--rl-tl-h\)/, 'the status line sits above it');
  assert.match(sheet, /\.rl-mapfirst\.sheeted \.rl-tl-body\s*\{[^}]*right:\s*calc\(440px \+ var\(--space-5\)\)/, 'the open list stops at a side sheet, as the map does');
  assert.doesNotMatch(sheet, /#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(/, 'colour from the tokens only');
  assert.doesNotMatch(sheet, /transition|animation/, 'nothing moves');
});

test('the strip\'s row is paid for by the map\'s own heading and line, kept for a screen reader', () => {
  assert.match(css(), /\.rl-mapfirst-map\.rl-tl-on \.rl-tmap > h2, \.rl-mapfirst-map\.rl-tl-on \.rl-tmap > h2 \+ p\.muted\s*\{[^}]*clip: rect\(0 0 0 0\)/);
});

test('the map section carries the strip\'s state, so the map and its controls make room above it', () => {
  const r = room(seat());
  const section = r.root.querySelector('.rl-mapfirst-map');
  assert.ok(section.classList.contains('rl-tl-on'));
  assert.ok(!section.classList.contains('rl-tl-open'));
  strip(r.root).querySelector('.rl-tl-head').click();
  assert.ok(r.now().querySelector('.rl-mapfirst-map').classList.contains('rl-tl-open'));
  const kids = r.now().querySelector('.rl-mapfirst-map').children.map((c) => c.getAttribute('class'));
  assert.ok(kids.indexOf('rl-tl open') > kids.findIndex((c) => c?.includes('rl-theatre')), 'the strip comes after the map, at its foot');
});

test('opened, the list is capped at 40 percent of the map\'s drawing as it is laid out', async () => {
  const set = [];
  const frames = [];
  globalThis.requestAnimationFrame = (fn) => frames.push(fn);
  try {
    const r = room(seat());
    strip(r.root).querySelector('.rl-tl-head').click();
    const section = r.now().querySelector('.rl-mapfirst-map');
    section.style = { setProperty: (k, v) => set.push([k, v]) };
    const drawing = document.createElement('svg');
    drawing.className = 'rl-map-svg';
    drawing.getBoundingClientRect = () => ({ height: 501 });
    section.querySelector('.rl-theatre').append(drawing);
    assert.ok(frames.length >= 1, 'measured once it is laid out');
    frames.at(-1)();
    assert.deepEqual(set, [['--rl-tl-cap', '200px']]);
  } finally {
    delete globalThis.requestAnimationFrame;
  }
});

// rule 5: no season's end, or nothing dated

test('with no season\'s end the line runs to the latest day sent and says so', () => {
  const { root } = room(seat((rv) => { delete rv.stakes.season_days_left; }));
  const tl = strip(root);
  assert.equal(kinds(tl).includes('end'), false);
  assert.match(words(tl.querySelector('.rl-tl-cap')), /Last dated day · 48 days/);
  assert.match(tl.querySelector('.rl-tl-head').getAttribute('aria-label'), /the season's end is not given/);
  assert.equal(tl.querySelectorAll('.rl-tl-axis .rl-tl-mark').at(-1).getAttribute('x'), '100.00%');
});

test('with nothing dated the strip is not drawn and the map takes no room for it', () => {
  const { root } = room(seat((rv) => {
    rv.agenda.items = [];
    rv.stakes = { ...rv.stakes, contests: [], mandates: [], season_days_left: null };
    rv.conferences = null;
    rv.map.marks.find((m) => m.name === LEVY).piece.under_way = null;
  }));
  assert.equal(strip(root), null);
  assert.ok(!root.querySelector('.rl-mapfirst-map').classList.contains('rl-tl-on'));
});

// rule 6: full screen

test('the strip stays in full screen', () => {
  const r = room(seat());
  hooksFor(r.root.querySelector('.rl-mapfirst .rl-theatre')).onFull(true);
  assert.ok(r.now().classList.contains('rl-full'));
  assert.ok(strip(r.now()), 'drawn in full screen');
  for (const sheet of [css(), read('css/c-sheets.css'), read('css/c-needs.css')]) {
    assert.doesNotMatch(sheet, /\.rl-full[^{]*\.rl-tl[^{]*\{[^}]*display:\s*none/, 'nothing hides it');
  }
});

// amended: a piece's arrival mark and the piece on the map light each other

test('a pointer or focus on the arrival lights the piece on the map, and the piece lights its mark', () => {
  const r = room(seat());
  const section = r.root.querySelector('.rl-mapfirst-map');
  const key = fixture.territory_map.marks.find((m) => m.name === LEVY).piece.key;
  const piece = document.createElement('g');
  piece.className = 'rl-tm-mark';
  piece.setAttribute('data-key', key);
  section.querySelector('.rl-theatre').append(piece);
  const mark = strip(r.root).querySelectorAll('.rl-tl-axis .rl-tl-mark').find((m) => m.getAttribute('data-tl-key') === key);
  assert.ok(mark, 'the arrival mark carries the piece\'s key');
  const over = (target, type) => section.dispatchEvent({ type, target });
  over(mark, 'pointerover');
  assert.ok(piece.classList.contains('rl-lit'), 'the mark lights the piece');
  over(mark, 'pointerout');
  assert.ok(!piece.classList.contains('rl-lit'));
  over(piece, 'focusin');
  assert.ok(mark.classList.contains('rl-lit'), 'the piece lights its mark');
  over(piece, 'focusout');
  assert.ok(!mark.classList.contains('rl-lit'));
  assert.match(css(), /\.rl-tm-mark\.rl-lit/, 'the lit piece is drawn');
});

test('index.html loads c-timeline.css', () => {
  assert.match(read('index.html'), /<link rel="stylesheet" href="\/css\/c-timeline\.css">/);
});

test('nothing the strip says reads another seat', () => {
  const tl = opened(room(seat()));
  assert.doesNotMatch(words(tl), /away|online|present|player|aide/i);
});
