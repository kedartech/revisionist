// What the room counts is drawn, not written (VIZ), one test or more per rule: 1. one module holds
// four marks, a bar (a value against a limit), a five-step meter (a band), a track (time left) and
// pips (a small count), each an image named with its number, the number on the mark; 3. the seat's
// own war economy draws paid against printed for each territory that pays less than it prints, and
// months of fuel against twelve; 5. the entries of docs/web-design/marks.md built here: the staff's
// record as a bar; 6. the odds panel draws the chance to take the place and the risk of being forced
// back as bars, and the win share at each strength as columns with the reported range marked, its
// outcome beside every share and every text twin kept; 7. the battle sheet draws each day's round
// as a pair of bars, the seat's losses and the enemy's as reported. And every mark in the room has
// its accessible name. Rule 2 (the stakes strip's tracks) is struck: the season's timeline draws
// those days.
// Keeps: no number the view did not send; nothing rests on colour alone; colour from tokens only.
// Mutants: a track measured against a fixed number of days; a mark with no accessible name; a number
// the view did not send drawn on a mark.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

const FLAGS = JSON.parse(readFileSync(new URL('../assets/flags/index.json', import.meta.url), 'utf8'));
globalThis.fetch = async () => ({ ok: true, json: async () => FLAGS });
Object.defineProperty(Object.getPrototypeOf(installDom().createElement('div')), 'hidden', {
  configurable: true,
  get() { return this.hasAttribute('hidden'); },
  set(on) { this.toggleAttribute('hidden', Boolean(on)); },
});
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const marks = await import('../js/views/realism-marks.js');
const eco = await import('../js/views/realism-economy.js');
const { oddsPanel, foldOdds } = await import('../js/views/realism-odds.js');
const { battleSheet } = await import('../js/views/realism-battle.js');
const { forecastRecord } = await import('../js/views/realism-estimate.js');
const { api } = await import('../js/api.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { forgetShapes } = await import('../js/views/realism-theatre.js');
const { setRoomLayout } = await import('../js/views/realism-sheets.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
const settle = async () => { for (let i = 0; i < 4; i += 1) await new Promise((ok) => setTimeout(ok, 0)); };
const all = (el) => [el, ...el.children.flatMap(all)];
const named = (el) => el.getAttribute('aria-label') ?? '';
const fills = (el) => Number(el.querySelector('.rl-mark-fill').getAttribute('data-share'));

// --- rule 1: one module, four marks -------------------------------------------------------

test('a bar draws a value against its limit, named with both numbers, the value on the mark', () => {
  const b = marks.bar({ value: 3.5, limit: 12, name: 'Pitch lasts', unit: 'months' });
  assert.ok(b.classList.contains('rl-mark') && b.classList.contains('rl-mark-bar'));
  assert.equal(b.getAttribute('role'), 'img');
  assert.equal(named(b), 'Pitch lasts: 3.5 of 12 months');
  assert.equal(words(b.querySelector('.rl-mark-num')), '3.5');
  assert.equal(fills(b), 29.17);
  assert.equal(fills(marks.bar({ value: 20, limit: 12, name: 'x' })), 100, 'never past its limit');
  assert.equal(fills(marks.bar({ value: -2, limit: 12, name: 'x' })), 0, 'never under nought');
  assert.equal(fills(marks.bar({ value: 2, limit: 0, name: 'x' })), 0, 'no limit, no length');
});

test('a bar may be a column, filled from the foot, and may leave its number to the words beside it', () => {
  const c = marks.bar({ value: 40, limit: 100, name: 'Win at strength 4', column: true, num: false });
  assert.ok(c.classList.contains('rl-mark-col'));
  const fill = c.querySelector('.rl-mark-fill');
  assert.equal(fill.getAttribute('y'), '60');
  assert.equal(fill.getAttribute('height'), '40');
  assert.equal(c.querySelector('.rl-mark-num'), null);
  assert.equal(named(c), 'Win at strength 4: 40 of 100');
});

test('a meter draws a band as five steps, its own and those under it on', () => {
  const m = marks.meter({ step: 3, name: 'Support', word: 'steady' });
  assert.ok(m.classList.contains('rl-mark-meter'));
  assert.equal(m.getAttribute('role'), 'img');
  assert.equal(named(m), 'Support: steady, 3 of 5');
  const cells = m.querySelectorAll('.rl-mark-step');
  assert.equal(cells.length, 5);
  assert.deepEqual(cells.map((c) => c.classList.contains('on')), [true, true, true, false, false]);
  assert.equal(words(m.querySelector('.rl-mark-num')), '3');
});

test('a track draws time left against the span it is given, so the nearer end is the shorter', () => {
  const near = marks.track({ left: 6, span: 24, name: 'The vote' });
  const far = marks.track({ left: 18, span: 24, name: 'The talks' });
  assert.ok(near.classList.contains('rl-mark-track'));
  assert.equal(named(near), 'The vote: 6 days left of 24');
  assert.equal(words(near.querySelector('.rl-mark-num')), '6 days');
  assert.equal(fills(near), 25);
  assert.equal(fills(far), 75);
  assert.ok(fills(near) < fills(far));
  // the same days left against another span is another length: the span is the one sent
  assert.equal(fills(marks.track({ left: 6, span: 60, name: 'x' })), 10);
  assert.equal(named(marks.track({ left: 1, span: 3, name: 'x' })), 'x: 1 day left of 3');
});

test('pips draw a small count, as many on as the count', () => {
  const p = marks.pips({ count: 2, of: 5, name: 'Escalation' });
  assert.ok(p.classList.contains('rl-mark-pips'));
  assert.equal(named(p), 'Escalation: 2 of 5');
  const dots = p.querySelectorAll('.rl-mark-pip');
  assert.equal(dots.length, 5);
  assert.equal(dots.filter((d) => d.classList.contains('on')).length, 2);
  assert.equal(words(p.querySelector('.rl-mark-num')), '2');
});

test('a mark is drawn from the tokens only, and the pieces of its drawing are hidden from a reader', () => {
  const css = read('css/c-marks.css');
  assert.equal(css.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/g), null);
  assert.match(read('index.html'), /<link rel="stylesheet" href="\/css\/c-marks\.css">/);
  for (const m of [marks.bar({ value: 1, limit: 2, name: 'a' }), marks.meter({ step: 1, name: 'b' }),
    marks.track({ left: 1, span: 2, name: 'c' }), marks.pips({ count: 1, of: 2, name: 'd' })]) {
    for (const el of all(m).slice(1)) {
      if (el.tagName === 'svg' || el.classList?.contains('rl-mark-num')) assert.equal(el.getAttribute('aria-hidden'), 'true');
    }
  }
});

test('a tone sets a class, and a hostile mark is hatched as well as red, so it never rests on colour', () => {
  const b = marks.bar({ value: 1, limit: 2, name: 'Theirs', tone: 'hostile' });
  assert.ok(b.classList.contains('rl-mark-hostile'));
  const id = b.querySelector('pattern').getAttribute('id');
  assert.equal(b.querySelector('.rl-mark-fill').getAttribute('fill'), `url(#${id})`);
  assert.notEqual(marks.bar({ value: 1, limit: 2, name: 'Again', tone: 'hostile' }).querySelector('pattern').getAttribute('id'), id, 'each hatch its own id');
  assert.equal(marks.bar({ value: 1, limit: 2, name: 'Ours', tone: 'own' }).querySelector('pattern'), null);
  const css = read('css/c-marks.css');
  assert.match(css, /\.rl-mark-hatch-bg \{[^}]*fill: var\(--danger\)/);
  // a fill rule in CSS beats the pattern's fill attribute, so every colour rule skips a fill that has one
  assert.doesNotMatch(css, /\.rl-mark-fill \{[^}]*fill:/);
  assert.match(css, /\.rl-mark-fill:not\(\[fill\]\) \{ fill: var\(--fg-muted\); \}/);
});

// --- rule 3: the seat's own war economy ---------------------------------------------------

const economyView = () => {
  const v = structuredClone(fixture);
  v.map = structuredClone(fixture.territory_map);
  const hills = v.map.areas.find((a) => a.key === 'norra_hills');
  hills.yields = { grain: 4 };
  v.economy.own.territories.find((t) => t.area === 'norra_hills').factors.output = 0.5;
  return v;
};

test('a territory that pays less than it prints shows paid against printed as a bar, its reason kept in words', () => {
  const v = economyView();
  const sheet = eco.ownSheet(v.economy, v.map);
  const row = sheet.querySelectorAll('.rl-eco-less li').find((r) => r.getAttribute('data-area') === 'norra_hills');
  const bar = row.querySelector('.rl-mark-bar');
  assert.ok(bar, 'a bar on the row');
  assert.equal(named(bar), 'Grain in The Norra Hills: pays 2 of 4 printed');
  assert.equal(fills(bar), 50);
  assert.equal(words(bar.querySelector('.rl-mark-num')), '2');
  assert.match(words(row), /Grain: pays 2 of 4 printed, because only 50 in 100 of it reaches you/);
});

test('months of fuel are a bar against twelve months, and no bar where no stock is kept', () => {
  const v = economyView();
  v.economy.own.fuel_months = 3.5;
  v.economy.own.pools.fuel = 420;
  const bar = eco.ownSheet(v.economy, v.map).querySelector('.rl-eco-fuelrow .rl-mark-bar');
  assert.equal(named(bar), 'Pitch lasts: 3.5 of 12 months');
  assert.equal(fills(bar), 29.17);
  v.economy.own.fuel_months = 30;
  assert.equal(fills(eco.ownSheet(v.economy, v.map).querySelector('.rl-eco-fuelrow .rl-mark-bar')), 100);
  v.economy.own.fuel_months = null;
  assert.equal(eco.ownSheet(v.economy, v.map).querySelector('.rl-eco-fuelrow .rl-mark-bar'), null);
  assert.equal(eco.FUEL_BAR_MONTHS, 12);
});

// --- rule 5: the staff's record -----------------------------------------------------------

test('the staff\'s record is a bar of the forecasts checked, beside its words', () => {
  const forecast = { ...structuredClone(fixture.agenda.forecast), checked: 4, held: 3 };
  const el = forecastRecord(forecast);
  const bar = el.querySelector('.rl-mark-bar');
  assert.equal(named(bar), 'Your staff were right: 3 of 4');
  assert.equal(fills(bar), 75);
  assert.equal(words(el.querySelector('.rl-fc-record')), 'Your staff were right 3 of 4');
  const none = forecastRecord({ ...forecast, checked: 0, held: 0 });
  assert.equal(none.querySelector('.rl-mark-bar'), null, 'no bar while none has settled');
});

// --- rule 6: the odds panel ---------------------------------------------------------------

const KNOWN = () => ({ reply: 'The odds as your own picture has them.', refused: false, odds: structuredClone(fixture.spread) });
const ODDS_VIEW = { ...fixture, map: fixture.territory_map };
const odds = (out = KNOWN()) => { foldOdds(false); return oddsPanel(ODDS_VIEW, out, { what: 'the Isle' }); };

test('the chance to take the place and the risk of being forced back are bars of 100, each beside its words', () => {
  const take = odds().querySelector('.rl-odds-take');
  const [taken, back] = take.querySelectorAll('.rl-mark-bar');
  assert.equal(named(taken), 'Taken: 76.7 in 100 runs');
  assert.equal(fills(taken), 76.7);
  assert.equal(named(back), 'Forced back: 23.3 in 100 runs');
  assert.equal(fills(back), 23.3);
  assert.match(words(take), /Chance77 in 100/);
  assert.match(words(take), /Forced back23 in 100, to The Norra Hills/);
});

test('a battle that takes no territory draws no bar for taking it', () => {
  const out = KNOWN();
  Object.assign(out.odds, { taken: null, taken_days: null });
  const bars = odds(out).querySelectorAll('.rl-odds-take .rl-mark-bar');
  assert.deepEqual(bars.map(named), ['Forced back: 23.3 in 100 runs']);
});

test('the win share at each strength is a column, the strengths reported marked, the table kept as its twin', () => {
  const out = KNOWN();
  out.odds.by_strength.push({ strength: 6, win: null });
  const p = odds(out);
  const cols = p.querySelector('.rl-odds-cols');
  assert.ok(cols, 'columns');
  assert.equal(cols.getAttribute('role'), 'group');
  const bars = cols.querySelectorAll('.rl-mark-bar');
  assert.deepEqual(bars.map(named), [
    'You win at The Sudland Coast if their strength is 3: 100 in 100 runs',
    'You win at The Sudland Coast if their strength is 4: 90.5 in 100 runs',
    'You win at The Sudland Coast if their strength is 5: 38.1 in 100 runs',
    'You win at The Sudland Coast if their strength is 6: no run drew it',
  ]);
  assert.deepEqual(bars.map(fills), [100, 90.5, 38.1, 0]);
  assert.deepEqual(cols.querySelectorAll('.rl-odds-col-s').map(words), ['3', '4', '5', '6']);
  assert.match(words(cols.querySelector('.rl-odds-col-range')), /^Your reports: strength 3 to 6$/);
  assert.equal(p.querySelectorAll('.rl-odds-table tbody tr').length, 4, 'the table stays');
});

test('the columns stay in view on Beginner, with the table behind More', () => {
  foldOdds(true);
  const p = oddsPanel(ODDS_VIEW, KNOWN(), { what: 'the Isle' });
  foldOdds(false);
  assert.ok(p.querySelector('.rl-odds-cols'));
  assert.equal(p.querySelector('details.rl-odds-more .rl-odds-cols'), null);
  assert.ok(p.querySelector('details.rl-odds-more .rl-odds-table'));
});

test('no share on the panel stands without its outcome: every bar is named for what it counts', () => {
  for (const m of odds().querySelectorAll('.rl-mark')) {
    assert.match(named(m), /^(Taken|Forced back|You win at [^:]+): /);
  }
});

// --- rule 7: the battle sheet -------------------------------------------------------------

const battleView = () => {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.clock = { ...rv.clock, world_date: '1900-04-16' };
  rv.battles[0].rounds = [
    { on: '1900-04-14', own_lost: 1, enemy_lost: 1 },
    { on: '1900-04-15', own_lost: 0, enemy_lost: 2 },
    { on: '1900-04-16', own_lost: 1, enemy_lost: 0 },
  ];
  return rv;
};

test('each day\'s round is a pair of bars, the seat\'s losses and the enemy\'s as reported, against the largest loss', () => {
  const sheet = battleSheet(battleView(), 'sudland_coast', { today: '1900-04-16' });
  const days = sheet.querySelectorAll('.rl-bt-round');
  assert.equal(days.length, 3);
  const pairs = days.map((d) => d.querySelectorAll('.rl-mark-bar').map(named));
  assert.deepEqual(pairs, [
    ['14 Apr, your losses: 1 of 2 steps', '14 Apr, theirs as reported: 1 of 2 steps'],
    ['15 Apr, your losses: 0 of 2 steps', '15 Apr, theirs as reported: 2 of 2 steps'],
    ['16 Apr, your losses: 1 of 2 steps', '16 Apr, theirs as reported: 0 of 2 steps'],
  ]);
  assert.deepEqual(days.map((d) => d.querySelectorAll('.rl-mark-fill').map((f) => Number(f.getAttribute('data-share')))),
    [[50, 50], [0, 100], [50, 0]]);
  assert.ok(days[0].querySelectorAll('.rl-mark-bar')[1].classList.contains('rl-mark-hostile'), 'the enemy\'s bar is hatched');
  assert.deepEqual(days.map((d) => words(d.querySelector('.rl-bt-round-day'))), ['14 Apr', '15 Apr', '16 Apr']);
  assert.equal(sheet.querySelectorAll('table.rl-bt-days tbody tr').length, 3, 'the table stays as the twin');
});

test('a battle with no round yet draws no pairs', () => {
  const rv = battleView();
  rv.battles[0].rounds = [];
  assert.equal(battleSheet(rv, 'sudland_coast', { today: '1900-04-16' }).querySelector('.rl-bt-rounds'), null);
});

// --- every mark in the room has its accessible name ------------------------------------------

/** The map-first room on the fixture's seat, with its World sheet open at the seat's own card. */
async function room() {
  const doc = installDom();
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.documents = structuredClone(fixture.listing);
  rv.wake_tick = 1;
  rv.style = 'free';
  setRoomLayout('map');
  forgetShapes();
  api.realism = async () => ({});
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const game = { id: `h13-${Math.random()}`, name: 'Autumn 1941', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {}, signOut: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  await settle();
  return doc.body.firstElementChild;
}

const ANY_MARK = (el) => el.getAttribute('role') === 'img' || el.classList?.contains('rl-mark');

test('every mark in the room is an image with a name that carries its number', async () => {
  const el = await room();
  const found = all(el).filter(ANY_MARK);
  const sheets = [
    eco.ownSheet(economyView().economy, economyView().map),
    odds(), battleSheet(battleView(), 'sudland_coast', { today: '1900-04-16' }),
    forecastRecord({ ...fixture.agenda.forecast, checked: 2, held: 1 }),
  ].flatMap((s) => all(s).filter(ANY_MARK));
  const every = [...found, ...sheets];
  assert.ok(sheets.filter((m) => m.classList.contains('rl-mark')).length >= 10, 'the sheets draw their marks');
  for (const m of every) {
    assert.equal(m.getAttribute('role'), 'img', `${m.getAttribute('class')} is an image`);
    assert.ok(named(m).trim(), `${m.getAttribute('class')} has a name`);
  }
  for (const m of every.filter((x) => x.classList.contains('rl-mark'))) assert.match(named(m), /\d|no run drew it/, named(m));
});

test('a mark with no name is refused when it is made', () => {
  assert.throws(() => marks.bar({ value: 1, limit: 2 }), /name/);
  assert.throws(() => marks.pips({ count: 1, of: 2, name: '' }), /name/);
});

test('the room\'s marks open nothing by colour alone: the battle\'s pair differs by hatching and place', () => {
  const css = read('css/c-marks.css');
  assert.match(css, /\.rl-mark-hostile/);
  assert.match(read('css/c-battle.css'), /\.rl-bt-round \{/);
  assert.equal(read('css/c-battle.css').match(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/g), null);
  assert.equal(read('css/c-odds.css').match(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/g), null);
});
