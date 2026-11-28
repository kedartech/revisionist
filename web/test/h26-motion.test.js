// Motion that means something (MOT), one test or more per rule: 1. a motion sheet lists every
// motion in the room: what change it shows, how long it runs, and what reduced motion shows in its
// place; 2. one module (web/js/motion.js) gives the durations and the reduced-motion check, and
// every motion in the board lane's files uses it; 3. the first set: the battle sheet plays a day's
// round as its two bars growing; a mark on the season's timeline that came due marks itself once,
// and a new mark drops into place; a sheet slides in and out in at most 200 ms; a nation's bar on
// the chart runs to a new length when its figure changes; a five-step meter that moved a step shows
// the step it left for a moment; 4. the sheet names what is not built and why, among them supply
// and aid moving along their routes; 5. a test fails a motion in the board lane's files that does
// not go through the module.
// Keeps: nothing moves to decorate; no motion delays a control or holds a tap; every motion has
// its end state under reduced motion.
// Mutant: a motion with no reduced-motion state.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { beforeEach, mock, test } from 'node:test';

import { capitalLines } from './capital-line.js';
import { installDom, words } from './dom-fake.js';

const proto = Object.getPrototypeOf(installDom().createElement('div'));
// the fake has no CSSOM, no layout and no animations: each element keeps what is set on its
// style, every box is 300 by 400 at (10, 20), and `animate` is recorded
let played = [];
Object.defineProperty(proto, 'style', {
  configurable: true,
  get() {
    this._style ??= { props: {}, setProperty(k, v) { this.props[k] = String(v); }, getPropertyValue(k) { return this.props[k] ?? ''; } };
    return this._style;
  },
});
proto.animate = function animate(frames, opts) {
  const a = { el: this, frames, opts, onfinish: null, cancel() {} };
  played.push(a);
  return a;
};
proto.getBoundingClientRect = function rect() { return { left: 10, top: 20, width: 300, height: 400 }; };
proto.scrollIntoView = function scrollIntoView() {};
let reduce = false;
globalThis.matchMedia = (q) => ({ matches: q.includes('reduce') ? reduce : q.includes('min-width: 1024px'), media: q, addEventListener() {} });
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const FLAGS = JSON.parse(readFileSync(new URL('../assets/flags/index.json', import.meta.url), 'utf8'));
globalThis.fetch = async () => ({ ok: true, json: async () => FLAGS });

const motion = await import('../js/motion.js');
const { api } = await import('../js/api.js');
const { battleSheet } = await import('../js/views/realism-battle.js');
const { timelineStrip } = await import('../js/views/realism-timeline.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { setRoomLayout } = await import('../js/views/realism-sheets.js');
const { forgetShapes } = await import('../js/views/realism-theatre.js');
const { setFlagIndex } = await import('../js/flags.js');
const nb = await import('../js/views/realism-nations.js');
const { pieceCard } = await import('../js/views/realism-piece.js');
const cap = await import('../js/views/realism-capital.js');
const tracks = await import('../js/views/realism-tracks.js');
const playback = await import('../js/views/realism-playback.js');
const crawl = await import('../js/views/realism-crawl.js');
const rules = await import('../js/realism-rules.js');
const mapMotion = await import('../js/map/motion.js');

const WEB = new URL('../', import.meta.url);
const read = (rel) => readFileSync(new URL(rel, WEB), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const settle = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  played = [];
  reduce = false;
  motion.forgetDrawn();
  mock.timers.reset();
});

const onEl = (el) => played.filter((p) => p.el === el);

// --- rule 1: the motion sheet -------------------------------------------------------------

const SHEET = (() => { try { return read('../docs/web-design/motion.md'); } catch { return ''; } })();
/** The sheet's table rows as { name, cells }: a row whose first cell is a motion's name in code. */
const sheetRows = () => SHEET.split('\n')
  .filter((l) => /^\|\s*`[a-z-]+`\s*\|/.test(l))
  .map((l) => {
    const cells = l.split('|').slice(1, -1).map((c) => c.trim());
    return { name: cells[0].replace(/`/g, ''), cells };
  });

test('the sheet lists every motion in the module, each with what it shows, its time and what reduced motion shows', () => {
  const rows = new Map(sheetRows().map((r) => [r.name, r.cells]));
  for (const [name, m] of Object.entries(motion.MOTIONS)) {
    const cells = rows.get(name);
    assert.ok(cells, `${name} is a row of the sheet`);
    assert.equal(cells.length, 5, `${name}: name, what it shows, time, reduced motion, where`);
    assert.ok(cells[1].length > 10, `${name} says what change it shows`);
    assert.ok(cells[2].includes(`${m.ms} ms`), `${name} runs ${m.ms} ms on the sheet`);
    assert.ok(cells[3].length > 3, `${name} says what reduced motion shows`);
  }
});

test('the sheet lists no motion the module does not', () => {
  for (const { name } of sheetRows()) assert.ok(motion.MOTIONS[name], `${name} is in web/js/motion.js`);
});

test('every motion in the module says what it shows and what reduced motion shows in its place', () => {
  for (const [name, m] of Object.entries(motion.MOTIONS)) {
    assert.ok(typeof m.shows === 'string' && m.shows.length > 10, `${name}: what it shows`);
    assert.ok(typeof m.reduced === 'string' && m.reduced.length > 3, `${name}: its reduced-motion state`);
    assert.ok(Number.isFinite(m.ms) && m.ms > 0, `${name}: its time`);
  }
});

// --- rule 4: what is not built ------------------------------------------------------------

test('the sheet names what is not built and why, supply and aid along their routes among them', () => {
  const part = SHEET.split(/^## /m).find((s) => s.startsWith('Not built'));
  assert.ok(part, 'a Not built section');
  assert.match(part, /supply/i);
  assert.match(part, /aid/i);
  assert.match(part, /route's progress|progress along/i, 'why: the reply sends no progress along a route');
  assert.ok(part.split('\n').filter((l) => l.startsWith('- ')).length >= 3, 'each thing not built is a line');
});

// --- rule 2: one module gives the durations and the reduced-motion check -----------------

test('play runs a listed motion for its time, and nothing under reduced motion', () => {
  installDom();
  const el = document.createElement('div');
  const a = motion.play(el, [{ opacity: 0 }, { opacity: 1 }], 'timeline-new');
  assert.equal(a.opts.duration, motion.MOTIONS['timeline-new'].ms);
  reduce = true;
  assert.equal(motion.play(el, [{ opacity: 0 }, { opacity: 1 }], 'timeline-new'), null);
  assert.equal(played.length, 1, 'reduced motion plays nothing');
  assert.throws(() => motion.play(el, [], 'sparkle'), /not on the motion sheet/);
});

test('a count run ends on the server\'s count, and under reduced motion is written at once', () => {
  installDom();
  mock.timers.enable({ apis: ['setTimeout'] });
  const el = document.createElement('span');
  motion.runCount(el, [10], [20], ([n]) => `${n} yea`);
  assert.equal(el.textContent, '10 yea');
  mock.timers.tick(motion.motionMs('count-run'));
  assert.equal(el.textContent, '20 yea');
  reduce = true;
  motion.runCount(el, [20], [30], ([n]) => `${n} yea`);
  assert.equal(el.textContent, '30 yea');
});

test('the board lane\'s motions take their times from the module, and the map\'s are listed at theirs', () => {
  const ms = motion.motionMs;
  assert.equal(tracks.MOVE_MS, ms('track-marker'));
  assert.equal(tracks.MARK_MS, ms('promise-due'));
  assert.equal(tracks.reducedMotion, motion.reducedMotion);
  assert.equal(tracks.lastDrawn, motion.lastDrawn);
  assert.equal(playback.DAY_MS, ms('wake-day'));
  assert.equal(playback.WAKE_MS, ms('wake-cap'));
  assert.equal(crawl.CHARS_PER_SECOND, 1000 / ms('crawl-char'));
  assert.equal(crawl.PAUSE_MS, ms('crawl-pause'));
  assert.equal(rules.SLIDE_MS, ms('map-slide'));
  assert.equal(mapMotion.COURSE_DRAW_MS, ms('map-course'));
  assert.equal(mapMotion.FILL_MS, ms('map-fill'));
  assert.match(read('js/map/gestures.js'), new RegExp(`FRICTION_MS = ${ms('map-glide')};`));
});

// --- rule 5: a motion that does not go through the module fails --------------------------

/** The surface lane's files: the map's own motions are its, listed on the sheet, not checked here. */
const SURFACE = [/^js\/map\//, /^js\/views\/realism-territory\.js$/, /^js\/shell\.js$/, /^sw\.js$/, /^test\//, /^css\/c-map\.css$/];
/** Timers that move nothing: a poll, a slow call's limit, a search's pause after typing. */
const NOT_MOTION = [
  ['js/app.js', 'setInterval(() => {'],
  ['js/views/realism-cast.js', 'setTimeout(() => reject(new Error(BEGIN_SLOW)), BEGIN_WAIT_MS)'],
  ['js/views/realism-intro.js', 'timer = setInterval(() => {'],
  ['js/views/realism-castlist.js', 'setTimeout(() => run(input.value.trim()), wait)'],
];
const OWN_MOTION = [
  [/\.animate\??\.?\(/, 'an animation played on its own'],
  [/prefers-reduced-motion/, 'its own reduced-motion check'],
  [/requestAnimationFrame/, 'its own frames'],
  [/\bset(?:Timeout|Interval)\(/, 'its own timer'],
  [/style\.(?:transition|animation)|['"](?:transition|animation)['"]\s*[,:]/, 'a transition set from script'],
  [/svg\(\s*['"]animate/, 'an SVG animation'],
];

/** Each line of `src` (file `rel`) with a motion that does not go through the module: [line, why]. */
function ownMotions(rel, src) {
  if (rel === 'js/motion.js' || SURFACE.some((re) => re.test(rel))) return [];
  const out = [];
  src.split('\n').forEach((line, i) => {
    if (/^\s*(\/\/|\*|\/\*\*)/.test(line)) return;
    for (const [re, why] of OWN_MOTION) {
      if (!re.test(line)) continue;
      if (NOT_MOTION.some(([f, text]) => f === rel && line.includes(text))) continue;
      out.push(`${rel}:${i + 1}: ${why}`);
    }
  });
  return out;
}

function walk(dir, base = dir) {
  const out = [];
  for (const name of readdirSync(new URL(dir, WEB))) {
    const rel = `${dir}${name}`;
    if (statSync(new URL(rel, WEB)).isDirectory()) out.push(...walk(`${rel}/`, base));
    else out.push(rel);
  }
  return out;
}

test('no script in the board lane\'s files moves anything but through the module', () => {
  const found = walk('js/').filter((f) => f.endsWith('.js')).flatMap((f) => ownMotions(f, read(f)));
  assert.deepEqual(found, []);
});

test('the check fails a motion of a view\'s own: an animation, a frame, a timer, its own reduced-motion check', () => {
  assert.equal(ownMotions('js/views/x.js', 'el.animate([{ opacity: 0 }], 300);').length, 1);
  assert.equal(ownMotions('js/views/x.js', "const r = matchMedia('(prefers-reduced-motion: reduce)');").length, 1);
  assert.equal(ownMotions('js/views/x.js', 'requestAnimationFrame(step);').length, 1);
  assert.equal(ownMotions('js/views/x.js', 'setTimeout(() => el.remove(), 300);').length, 1);
  assert.equal(ownMotions('js/views/x.js', "el.style.transition = 'width .3s';").length, 1);
  assert.equal(ownMotions('js/motion.js', 'el.animate(frames, { duration: ms });').length, 0);
  assert.equal(ownMotions('js/map/view.js', 'requestAnimationFrame(step);').length, 0);
});

const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');
const boardCss = () => readdirSync(new URL('css/', WEB)).filter((f) => f.endsWith('.css') && !SURFACE.some((re) => re.test(`css/${f}`)));

/** A stylesheet's time in ms: \"2.4s\", \"900ms\", or a custom property set in any stylesheet. */
function cssMs(token, all) {
  const v = token.match(/^var\((--[\w-]+)\)$/);
  if (v) {
    const set = all.match(new RegExp(`${v[1]}\\s*:\\s*([\\d.]+m?s)\\s*;`));
    return set ? cssMs(set[1], all) : Number.NaN;
  }
  const m = token.match(/^([\d.]+)(ms|s)$/);
  return m ? Number(m[1]) * (m[2] === 's' ? 1000 : 1) : Number.NaN;
}

/** Each stylesheet animation and transition: { file, name, ms } or { file, transition }. */
function cssMotions(file, all) {
  const css = stripComments(read(`css/${file}`));
  const out = [];
  for (const [, value] of css.matchAll(/(?<![\w-])animation\s*:\s*([^;}]+)/g)) {
    if (/^\s*none\b/.test(value)) continue;
    const parts = value.trim().split(/\s+/);
    const time = parts.find((p) => /^([\d.]+m?s|var\(--[\w-]+\))$/.test(p));
    const name = parts.find((p) => /^[a-z][\w-]*$/i.test(p) && !/^(linear|ease|ease-in|ease-out|ease-in-out|infinite|both|forwards|backwards|alternate|normal|reverse|step-end|step-start|running|paused)$/.test(p));
    out.push({ file, name, ms: cssMs(time ?? '', all) });
  }
  for (const [, value] of css.matchAll(/(?<![\w-])transition(?:-duration)?\s*:\s*([^;}]+)/g)) {
    if (!/^\s*none\b/.test(value)) out.push({ file, transition: value.trim() });
  }
  for (const [, name] of css.matchAll(/@keyframes\s+([\w-]+)/g)) out.push({ file, keyframes: name });
  return out;
}

test('every animation in the board lane\'s stylesheets is a listed motion, at the time the module gives it', () => {
  const files = boardCss();
  const all = files.map((f) => stripComments(read(`css/${f}`))).join('\n');
  const byCss = new Map(Object.entries(motion.MOTIONS).filter(([, m]) => m.css).map(([name, m]) => [m.css, { name, ...m }]));
  const problems = [];
  for (const f of files) {
    for (const m of cssMotions(f, all)) {
      if (m.transition) { problems.push(`${f}: a transition (${m.transition}) the sheet does not list`); continue; }
      const listed = byCss.get(m.name ?? m.keyframes);
      if (!listed) { problems.push(`${f}: ${m.name ?? m.keyframes} is not on the motion sheet`); continue; }
      if (m.ms !== undefined && m.ms !== listed.ms) problems.push(`${f}: ${m.name} runs ${m.ms} ms, the sheet gives ${listed.ms}`);
      if (listed.file !== f) problems.push(`${f}: ${m.name ?? m.keyframes} is listed in ${listed.file}`);
    }
  }
  assert.deepEqual(problems, []);
});

test('the stylesheet check fails an animation the module does not list or times otherwise', () => {
  const byCss = new Set(Object.values(motion.MOTIONS).map((m) => m.css).filter(Boolean));
  assert.ok(!byCss.has('rl-sparkle'));
  assert.ok(Number.isNaN(cssMs('var(--nowhere)', '')));
  assert.equal(cssMs('2.4s', ''), 2400);
  assert.equal(cssMs('var(--rl-intro-fade)', '--rl-intro-fade: 600ms;'), 600);
});

test('reduced motion stops every stylesheet motion of the room', () => {
  const base = stripComments(read('css/c-base.css'));
  const block = base.match(/@media \(prefers-reduced-motion: reduce\)\s*\{([^}]*\})/);
  assert.ok(block, 'c-base.css has a reduced-motion block');
  assert.match(block[1], /\*\s*\{\s*transition:\s*none !important;\s*animation:\s*none !important;\s*\}/);
  assert.match(read('index.html'), /href="\/css\/c-base\.css"/);
});

// --- rule 3: the first set ----------------------------------------------------------------

// the battle sheet: a day's round as its two bars growing

const battleView = (rounds) => {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.clock = { ...rv.clock, world_date: '1900-04-16' };
  rv.battles[0].rounds = rounds;
  return rv;
};
const R14 = { on: '1900-04-14', own_lost: 1, enemy_lost: 1 };
const R15 = { on: '1900-04-15', own_lost: 0, enemy_lost: 2 };
const R16 = { on: '1900-04-16', own_lost: 1, enemy_lost: 3 };
const fills = (round) => round.querySelectorAll('rect.rl-mark-fill');
const grown = () => played.filter((p) => p.opts.duration === motion.motionMs('battle-round'));

test('the battle sheet grows the day\'s round as its two bars from the foot, once', () => {
  installDom();
  let sheet = battleSheet(battleView([R14, R15]), 'sudland_coast', { today: '1900-04-15' });
  let days = sheet.querySelectorAll('.rl-bt-round');
  assert.deepEqual(grown().map((p) => p.el), fills(days[1]), 'drawn first, the latest round grows');
  assert.equal(grown()[0].frames[0].transform, 'scaleY(0)');
  played = [];
  sheet = battleSheet(battleView([R14, R15]), 'sudland_coast', { today: '1900-04-15' });
  assert.equal(grown().length, 0, 'drawn again with nothing new, nothing moves');
  sheet = battleSheet(battleView([R14, R15, R16]), 'sudland_coast', { today: '1900-04-16' });
  days = sheet.querySelectorAll('.rl-bt-round');
  assert.deepEqual(grown().map((p) => p.el), fills(days[2]), 'the new day\'s two bars grow, the others stand');
});

test('under reduced motion the round\'s bars stand at their length', () => {
  installDom();
  reduce = true;
  const sheet = battleSheet(battleView([R14, R15, R16]), 'sudland_coast', { today: '1900-04-16' });
  assert.equal(played.length, 0);
  const last = sheet.querySelectorAll('.rl-bt-round')[2];
  assert.deepEqual(fills(last).map((r) => r.getAttribute('data-share')), ['33.33', '100']);
});

// the season's timeline: a mark that came due marks itself once; a new mark drops into place

const tlSeat = (days, extra = []) => {
  const rv = structuredClone(fixture);
  rv.clock = { ...rv.clock, world_date: '1900-04-10' };
  rv.locks = null;
  rv.conferences = { conferences: [] };
  rv.agenda = { items: [] };
  rv.stakes = { contests: [{ name: 'The bill', days_left: days }, ...extra.map((name) => ({ name, days_left: 9 }))], mandates: [], season_days_left: 30 };
  return rv;
};
const tlMark = (strip, key) => strip.querySelectorAll('svg.rl-tl-mark').find((m) => m.getAttribute('data-tl-key') === key);

test('a mark on the timeline that came due marks itself once', () => {
  installDom();
  timelineStrip(tlSeat(1), []);
  assert.equal(played.length, 0, 'a day to go: nothing');
  let strip = timelineStrip(tlSeat(0), []);
  const due = tlMark(strip, 'contest:The bill');
  assert.ok(due.hasAttribute('data-came-due'));
  assert.deepEqual(onEl(due).map((p) => p.opts.duration), [motion.motionMs('timeline-due')]);
  played = [];
  strip = timelineStrip(tlSeat(0), []);
  assert.equal(played.length, 0, 'drawn again, it does not mark itself again');
});

test('a new mark drops into place; the marks there before stand', () => {
  installDom();
  timelineStrip(tlSeat(5), []);
  assert.equal(played.length, 0, 'the first draw drops nothing');
  const strip = timelineStrip(tlSeat(5, ['The treaty']), []);
  const fresh = tlMark(strip, 'contest:The treaty');
  assert.deepEqual(played.map((p) => p.el), [fresh]);
  assert.equal(played[0].opts.duration, motion.motionMs('timeline-new'));
  assert.match(played[0].frames[0].transform, /translateY\(-/);
});

test('under reduced motion the timeline\'s marks stand: due and new alike', () => {
  installDom();
  reduce = true;
  timelineStrip(tlSeat(1), []);
  const strip = timelineStrip(tlSeat(0, ['The treaty']), []);
  assert.equal(played.length, 0);
  assert.ok(tlMark(strip, 'contest:The bill').getAttribute('class').includes('rl-tl-mark'));
  assert.ok(tlMark(strip, 'contest:The treaty'));
});

// a sheet slides in and out in at most 200 ms

async function room(rv) {
  const doc = installDom();
  setRoomLayout('map');
  forgetShapes();
  api.realism = async () => ({});
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const game = { id: `h26-${Math.random()}`, name: 'Autumn 1941', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {}, signOut: () => {} };
  const root = realismRoom(ctx);
  doc.body.append(root);
  await settle();
  return { root, doc };
}
const roomSeat = () => {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.documents = structuredClone(fixture.listing);
  rv.wake_tick = 1;
  rv.style = 'free';
  return rv;
};
const worldTab = (root) => root.querySelectorAll('.rl-sheettabs button').find((b) => b.getAttribute('data-group') === 'world');

test('a sheet opening slides in, in at most 200 ms, and its controls are there at once', async () => {
  const { root } = await room(roomSeat());
  played = [];
  worldTab(root).click();
  const sheet = root.querySelector('.rl-over');
  assert.ok(sheet, 'the sheet is in the page at once');
  const slid = onEl(sheet);
  assert.equal(slid.length, 1);
  assert.ok(slid[0].opts.duration <= 200, 'at most 200 ms');
  assert.equal(slid[0].opts.duration, motion.motionMs('sheet-in'));
  assert.equal(slid[0].frames[0].transform, 'translateX(24px)', 'at 1024 px and over, from the side it opens at');
  assert.ok(sheet.querySelector('button.rl-over-close'), 'Close is there to press at once');
  played = [];
  root.querySelectorAll('.rl-over .rl-parts button')[1]?.click();
  assert.equal(onEl(root.querySelector('.rl-over')).length, 0, 'another part of the same sheet does not slide in again');
});

test('a sheet closing slides out as a picture that holds nothing: the map is live at once', async () => {
  const { root } = await room(roomSeat());
  worldTab(root).click();
  played = [];
  mock.timers.enable({ apis: ['setTimeout'] });
  root.querySelector('.rl-over button.rl-over-close').click();
  assert.equal(root.querySelector('.rl-over'), null, 'the sheet is closed at once');
  const ghost = root.querySelector('.rl-over-ghost');
  assert.ok(ghost, 'its picture slides out');
  assert.equal(ghost.getAttribute('aria-hidden'), 'true');
  assert.ok(ghost.hasAttribute('inert'), 'no one can press it');
  assert.equal(ghost.querySelectorAll('[id]').length, 0, 'it takes no id from the page');
  assert.equal(ghost.style.getPropertyValue('width'), '300px', 'it stands where the sheet stood');
  const out = onEl(ghost);
  assert.equal(out.length, 1);
  assert.ok(out[0].opts.duration <= 200);
  assert.equal(out[0].frames.at(-1).opacity, 0);
  mock.timers.tick(motion.motionMs('sheet-out') + 100);
  assert.equal(root.querySelector('.rl-over-ghost'), null, 'gone once it has played');
});

test('under reduced motion a sheet opens and closes at once, with no picture left behind', async () => {
  reduce = true;
  const { root } = await room(roomSeat());
  worldTab(root).click();
  assert.equal(played.length, 0);
  root.querySelector('.rl-over button.rl-over-close').click();
  assert.equal(root.querySelector('.rl-over'), null);
  assert.equal(root.querySelector('.rl-over-ghost'), null);
  assert.equal(played.length, 0);
});

// a nation's bar on the chart runs to its new length when its figure changes

const nbSeat = (figure) => {
  const rv = structuredClone(fixture);
  rv.world_key = 'autumn-1941';
  rv.economy = { ...rv.economy, figures: [
    { nation: { key: 'A', name: 'Norra', relation: 'own' }, figure: 200 },
    { nation: { key: 'B', name: 'Sudland', relation: 'enemy' }, figure },
  ] };
  rv.home = { ...rv.home, standings: [] };
  return rv;
};
const nbFill = (panel, key) => panel.querySelectorAll('button.rl-nb-row').find((b) => b.getAttribute('data-nation') === key).querySelector('rect.rl-nb-fill');

test('a nation\'s bar runs from its old length to its new one when its figure changes; the others stand', () => {
  installDom();
  setFlagIndex(FLAGS);
  nb.nationsPanel(nbSeat(100), { state: {} });
  assert.equal(played.length, 0, 'the first draw runs nothing');
  const panel = nb.nationsPanel(nbSeat(150), { state: {} });
  const fill = nbFill(panel, 'B');
  assert.equal(fill.getAttribute('width'), '75');
  assert.deepEqual(played.map((p) => p.el), [fill]);
  assert.equal(played[0].opts.duration, motion.motionMs('nation-bar'));
  assert.equal(played[0].frames[0].transform, 'scaleX(0.6667)', 'from 50 of 100 to 75');
  assert.equal(played[0].frames.at(-1).transform, 'none');
});

test('under reduced motion a nation\'s bar stands at its new length', () => {
  installDom();
  setFlagIndex(FLAGS);
  reduce = true;
  nb.nationsPanel(nbSeat(100), { state: {} });
  const panel = nb.nationsPanel(nbSeat(150), { state: {} });
  assert.equal(played.length, 0);
  assert.equal(nbFill(panel, 'B').getAttribute('width'), '75');
});

// a five-step meter that moved a step shows the step it left for a moment

const levy = (attack) => ({
  key: 'levy-1', name: 'The Norra Levy', side: 'own',
  piece: { figures: { key: 'levy', name: 'Levy', picture: 'infantry', figures: { attack: 3, defence: 3 }, here: { attack, defence: 3 }, changes: [] } },
});
const meterSteps = (el, sel) => el.querySelector(sel).querySelectorAll('span').filter((s) => !s.querySelector('span') && s.getAttribute('class')?.includes('step'));

test('a piece\'s figure that moved a step shows the step it left for a moment', () => {
  installDom();
  mock.timers.enable({ apis: ['setTimeout'] });
  pieceCard(fixture.territory_map, levy(3));
  let card = pieceCard(fixture.territory_map, levy(3));
  assert.equal(card.querySelectorAll('.rl-motion-left').length, 0, 'no step moved: nothing shows');
  card = pieceCard(fixture.territory_map, levy(2));
  const steps = meterSteps(card, '.rl-pc-meter[data-figure="attack"]');
  assert.deepEqual(steps.map((s) => s.classList.contains('rl-motion-left')), [false, false, true, false, false], 'the third step, the one it left');
  mock.timers.tick(motion.motionMs('step-left'));
  assert.equal(card.querySelectorAll('.rl-motion-left').length, 0, 'for a moment');
});

test('a nation\'s standing at home that moved a step shows the step it left', () => {
  installDom();
  setFlagIndex(FLAGS);
  mock.timers.enable({ apis: ['setTimeout'] });
  const banded = (band) => {
    const rv = nbSeat(100);
    rv.home = { ...rv.home, standings: [{ nation: { key: 'B', name: 'Sudland', relation: 'enemy' }, band }] };
    return rv;
  };
  const state = { open: 'B' };
  nb.nationsPanel(banded('firm'), { state });
  const panel = nb.nationsPanel(banded('shaken'), { state });
  const meter = panel.querySelector('.rl-nb-meter');
  const left = meter.querySelectorAll('.rl-nb-step').findIndex((s) => s.classList.contains('rl-motion-left'));
  assert.ok(left >= 0, 'the step it left is shown');
  assert.ok(Number(meter.getAttribute('data-step')) !== left + 1, 'it is not the step it stands at');
});

test('a bloc\'s support that moved a step on the Capital board shows the step it left', () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  const seat = (support) => {
    const rv = structuredClone(fixture);
    rv.map = structuredClone(fixture.territory_map);
    rv.clock = { ...rv.clock, world_date: '1900-04-10' };
    rv.locks = null;
    rv.conferences = { conferences: [] };
    rv.stakes = { ...rv.stakes, contests: [], mandates: [] };
    const blocs = [['b0', 'Bloc Zero', 100, support], ['b1', 'Bloc One', 60, 50]].map(([group, name, seats, s]) => ({ group, name, seats, support: s }));
    rv.home = {
      ...structuredClone(fixture.home),
      groups: blocs.map((b) => ({ key: b.group, name: b.name, kind: 'party', support: b.support, last_moved: null, feeds: { votes: 1 } })),
      chambers: [{ key: 'assembly', blocs, measures: [{ order_id: 'o-neutrality', key: 'neutrality', title: 'Revising the Neutrality Act', votes: [{
        vote: 'assembly', yeas: 120, nays: 40, carries: 150, blocs: [{ group: 'b0', yeas: 90, nays: 0 }, { group: 'b1', yeas: 30, nays: 40 }],
      }] }] }],
      themes: [], offers: [], promises: [],
    };
    rv.capitals = capitalLines(rv);
    return rv;
  };
  const draw = (support) => { installDom(); return cap.capitalBoard(seat(support), { q: 'vote:o-neutrality' }, {}); };
  draw(50);
  const el = draw(95);
  const piece = el.querySelectorAll('button.rl-cap-piece').find((b) => b.getAttribute('data-group') === 'b0');
  const steps = piece.querySelector('.rl-cap-steps5').querySelectorAll('.rl-cap-step');
  const left = steps.findIndex((s) => s.classList.contains('rl-motion-left'));
  assert.ok(left >= 0, 'the step it left is shown');
  assert.notEqual(left + 1, Number(piece.querySelector('.rl-cap-steps5').getAttribute('data-step')));
  const other = el.querySelectorAll('button.rl-cap-piece').find((b) => b.getAttribute('data-group') === 'b1');
  assert.equal(other.querySelectorAll('.rl-motion-left').length, 0, 'a bloc that did not move shows nothing');
});

test('under reduced motion a meter shows its new step only', () => {
  installDom();
  reduce = true;
  pieceCard(fixture.territory_map, levy(3));
  const card = pieceCard(fixture.territory_map, levy(2));
  assert.equal(card.querySelectorAll('.rl-motion-left').length, 0);
  assert.equal(words(card.querySelector('.rl-pc-meter[data-figure="attack"] .rl-mark-num')), '2');
});

test('the step it left is drawn by outline and place, from the theme\'s tokens', () => {
  const css = stripComments(read('css/c-motion.css'));
  const rule = css.match(/\.rl-motion-left[^{]*\{([^}]*)\}/);
  assert.ok(rule, 'c-motion.css draws the step it left');
  assert.match(rule[1], /outline:[^;]*var\(--/);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/, 'colours come from tokens');
  assert.match(css, /\.rl-over-ghost\s*\{[^}]*pointer-events:\s*none/, 'the leaving sheet holds no tap');
  assert.match(css, /\.rl-mapfirst\.sheeted, \.rl-mapfirst:has\(> \.rl-over-ghost\) \{ overflow: clip; \}/, 'a sliding sheet never widens the page');
  assert.match(css, /\.rl-over-ghost\s*\{[^}]*position:\s*absolute/, 'the picture stands in the clipped frame');
});
