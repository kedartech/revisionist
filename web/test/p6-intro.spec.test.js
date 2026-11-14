// Spec for Train 3 unit P4 (contract K3), revised for unit Q8 (contract KQ) and item I2: the
// splash is the aide greeting the seat with how it starts, its first papers and its open
// matters. The crawl's spec is p6-crawl.spec.test.js.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  BRIEF_POLL_MS, INTRO_PREFIX, PAPERS_MAX, TAKE_DESK, aideGreeting, introStage, markIntro, openMatters, openingPapers,
  seatSplash, splashModel, startOverview,
} from '../js/views/realism-intro.js';
import { installDom, words } from './dom-fake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-cast.json'));
const room = JSON.parse(read('test/fixtures/realism-seat.json'));
const ISO = /\b\d{4}-\d{2}-\d{2}\b/;

const memory = () => {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), m };
};
const broken = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
const { desk } = fixture;
const fdr = fixture.roster[0];
// the room's view carries the tray's listing (`{ documents, unread, flagged }`) as `documents`
const view = { ...room, documents: room.listing };

const FORCES = ['US Atlantic Fleet: Reykjavik'];
const FIGURES = [
  'Allied merchant losses to U-boats, Sep 1941: 209,835 GRT',
  "Gallup, Roosevelt's course 'about right': 56 percent",
  'House votes for Neutrality revision: 220 votes',
];
const FIRST = 'Keep the convoys moving to Iceland (due 26 October 1941)';
const PAPERS = [
  { id: 'd-magic-0919', label: 'Signal Intelligence Service: Japanese Foreign Ministry traffic, Tokyo to Washington embassy' },
  { id: 'd-whip-1017', label: 'Sam Rayburn: House count on the Neutrality Act revision' },
  { id: 'd-cable-1016', label: 'Laurence Steinhardt: Moscow situation, week ending 16 October' },
  { id: 'd-memo-1015', label: 'Harry Hopkins: Lend-Lease shipments, September tonnage' },
  { id: 'd-press-1014', label: 'New York Times: Editorial: Convoys and the Congress' },
];
const MATTERS = ['Order from Franklin D. Roosevelt: Keep the convoys moving to Iceland (due 26 October 1941)'];
const OVERVIEW = { forces: FORCES, figures: FIGURES, first: FIRST, papers: PAPERS, matters: MATTERS, day: '20 October 1941' };
const EMPTY = { forces: [], figures: [], first: null, papers: [], matters: [], day: null };

test('the splash from the desk and the overview; the dossier is not drawn', () => {
  const m = splashModel('Franklin D. Roosevelt', desk, fdr.dossier, OVERVIEW);
  assert.deepEqual(m, {
    title: 'You are Franklin D. Roosevelt',
    office: 'President of the United States',
    answersTo: 'Answers to The electorate, Congress',
    greeting: aideGreeting('20 October 1941'),
    overview: { forces: FORCES, figures: FIGURES },
    papers: PAPERS,
    matters: MATTERS,
    action: TAKE_DESK,
  });
  assert.equal(TAKE_DESK, 'Take your desk');
});

test('the splash hides what it does not have', () => {
  const m = splashModel('Burton K. Wheeler', { office: '', principals: [] }, null);
  assert.equal(m.office, null);
  assert.equal(m.answersTo, null);
  assert.equal(m.overview, null);
  assert.deepEqual(m.papers, []);
  assert.deepEqual(m.matters, []);
  assert.equal(m.title, 'You are Burton K. Wheeler');
  assert.equal(m.greeting, aideGreeting(null));
});

test('the greeting is one line from the aide, the day in words', () => {
  const g = aideGreeting('20 October 1941');
  assert.ok(g.includes('20 October 1941'), g);
  assert.doesNotMatch(g, ISO);
  assert.doesNotMatch(g, /\n/);
  assert.ok(aideGreeting(null).length > 0);
  assert.ok(!aideGreeting(null).includes('null') && !aideGreeting(null).includes('undefined'));
});

test('stages: crawl, then splash, then nothing, per campaign', () => {
  const s = memory();
  assert.equal(introStage(s, 'c1', true), 'crawl');
  markIntro(s, 'c1', 'crawl');
  assert.equal(s.getItem(`${INTRO_PREFIX}c1`), 'crawl');
  assert.equal(introStage(s, 'c1', true), 'splash');
  markIntro(s, 'c1', 'splash');
  assert.equal(s.getItem(`${INTRO_PREFIX}c1`), 'done');
  assert.equal(introStage(s, 'c1', true), null);
  assert.equal(introStage(s, 'c2', true), 'crawl');
  assert.equal(INTRO_PREFIX, 'rv.intro.');
});

test('a game under way gets no intro; a blocked store never blocks the player', () => {
  assert.equal(introStage(memory(), 'c1', false), null);
  assert.equal(introStage(broken, 'c1', true), null);
  assert.doesNotThrow(() => markIntro(broken, 'c1', 'crawl'));
  assert.equal(introStage(null, 'c1', true), null);
});

test('the splash dialog: Take your desk, Esc, no portrait', () => {
  const src = read('js/views/realism-intro.js');
  for (const s of [/'dialog'/, /TAKE_DESK/, /'cancel'|oncancel/, /aideBriefing\(/]) assert.match(src, s);
  assert.doesNotMatch(src, /portraitNode|As history had it/);
});

test('the starting overview: forces, figures, first matter, first papers, open matters, the day', () => {
  assert.deepEqual(startOverview(view), OVERVIEW);
  assert.deepEqual(startOverview({}), EMPTY);
  assert.deepEqual(startOverview({ map: null, situation: null, agenda: null, documents: null, clock: null }), EMPTY);
});

test('forces: own fleets, armies and air only, three at most, a force under way reads from and to', () => {
  const own = (name, kind, place) => ({ ...room.map.marks[3], name, kind, places: [{ name: place, lat: 0, lon: 0 }] });
  const marks = [
    own('Route A', 'route', 'Halifax'), own('Front A', 'front', 'Moscow'), room.map.marks[0],
    own('First Army', 'army', 'Fort Bragg'), own('Air Wing', 'air', 'Iceland'), own('Second Fleet', 'fleet', 'Norfolk'), own('Fourth Fleet', 'fleet', 'Recife'),
  ];
  assert.deepEqual(startOverview({ map: { ...room.map, marks, orders: [] } }).forces,
    ['First Army: Fort Bragg', 'Air Wing: Iceland', 'Second Fleet: Norfolk']);
  const moving = { ...room.map, orders: [{ ...room.map.orders[0], status: 'under_way' }] };
  assert.deepEqual(startOverview({ map: moving }).forces, ['US Atlantic Fleet: Reykjavik to Argentia']);
  assert.deepEqual(startOverview({ map: room.map }).forces, ['US Atlantic Fleet: Reykjavik'], 'an order still awaiting is not under way');
});

test('figures: a figure with no value is left out; first matter without a deadline', () => {
  const figures = room.situation.figures.slice(1).concat(room.situation.figures.slice(0, 1));
  assert.deepEqual(startOverview({ situation: { ...room.situation, figures } }).figures, [FIGURES[1], FIGURES[2], FIGURES[0]]);
  const oil = room.situation.figures.filter((f) => f.label === 'Japanese oil stocks');
  assert.deepEqual(startOverview({ situation: { figures: oil } }).figures, []);
  const item = { ...room.agenda.items[0], deadline: null };
  assert.equal(startOverview({ agenda: { ...room.agenda, items: [item] } }).first, 'Keep the convoys moving to Iceland');
  assert.equal(startOverview({ agenda: { ...room.agenda, items: [] } }).first, null);
});

test('first matter: a deadline the text already names is not repeated', () => {
  const named = { ...room.agenda.items[0], text: 'Answer the Navy on the convoy by 15 September 1941.', deadline: '15 September 1941' };
  assert.equal(startOverview({ agenda: { items: [named] } }).first, 'Answer the Navy on the convoy by 15 September 1941');
  const other = { ...named, deadline: '20 September 1941' };
  assert.equal(startOverview({ agenda: { items: [other] } }).first,
    'Answer the Navy on the convoy by 15 September 1941 (due 20 September 1941)', 'a different date still shows');
});

test('first papers: no acknowledgements or answers, one row per feed, at most PAPERS_MAX, in tray order', () => {
  assert.deepEqual(openingPapers(room.listing.documents), PAPERS);
  assert.equal(PAPERS_MAX, 5);
  const paper = (id, group = null, extra = {}) => ({ id, title: `Paper ${id}`, author: 'Harry Hopkins', group, ack: false, answer: false, ...extra });
  const docs = [
    paper('a', 'MAGIC intercepts'), paper('b', 'MAGIC intercepts'), paper('c'), paper('d', null, { ack: true }),
    paper('e', null, { answer: true }), paper('f'), paper('g'), paper('h'), paper('i'),
  ];
  assert.deepEqual(openingPapers(docs).map((p) => p.id), ['a', 'c', 'f', 'g', 'h']);
  assert.deepEqual(openingPapers([paper('x', null, { author: '' })]), [{ id: 'x', label: 'Paper x' }]);
  assert.deepEqual(openingPapers([paper('y', null, { title: ' ' })]), []);
  assert.deepEqual(openingPapers(null), []);
});

test('open matters: every live mandate, its kind and issuer, the deadline once', () => {
  assert.deepEqual(openMatters(room.agenda), MATTERS);
  const item = (text, extra = {}) => ({ ...room.agenda.items[0], text, ...extra });
  assert.deepEqual(openMatters({ items: [
    item('Answer the Navy by 15 September 1941.', { deadline: '15 September 1941', kind: 'Crisis', issuer: null }),
    item('Hold the line.', { issuer: 'Harold R. Stark', kind: '' }),
    item(' '),
  ] }), [
    'Crisis: Answer the Navy by 15 September 1941',
    'Matter from Harold R. Stark: Hold the line (due 26 October 1941)',
  ]);
  assert.deepEqual(openMatters(null), []);
});

const splash = (overview, opts = {}) => seatSplash({
  name: 'Franklin D. Roosevelt', dossier: fdr.dossier,
  model: splashModel('Franklin D. Roosevelt', desk, fdr.dossier, overview),
  ...opts,
});

test("the select card's biography is not on the splash", () => {
  installDom();
  const d = splash(OVERVIEW);
  const text = words(d);
  const bio = [fdr.dossier.bio, fdr.dossier.arena, ...fdr.dossier.history, 'As history had it'];
  for (const line of bio.filter(Boolean)) assert.ok(!text.includes(line.trim()), line);
  assert.equal(d.querySelector('img'), null);
  assert.equal(d.querySelector('figure'), null);
});

test('the aide greets the seat: the greeting, then the overview, the papers and the matters', () => {
  installDom();
  const d = splash(OVERVIEW);
  const aide = d.querySelector('section.rl-brief');
  assert.ok(aide, 'the aide briefing');
  assert.ok(words(aide).includes(aideGreeting('20 October 1941')));
  assert.equal(words(d.querySelector('h2')), 'You are Franklin D. Roosevelt');
  const section = d.querySelector('section.rl-intro-overview');
  assert.equal(words(section.querySelector('h3')), 'How you start');
  assert.deepEqual(section.querySelectorAll('h4').map(words), ['Your forces', 'On your desk']);
  for (const line of [...FORCES, ...FIGURES]) assert.ok(words(section).includes(line), line);
  const papers = d.querySelector('section.rl-intro-papers');
  assert.deepEqual(papers.querySelectorAll('button').map(words), PAPERS.map((p) => p.label));
  const matters = d.querySelector('section.rl-intro-matters');
  assert.deepEqual(matters.querySelectorAll('li').map(words), MATTERS);
  const order = d.children.map((c) => c.className.split(' ')[0]);
  const at = (cls) => order.indexOf(cls);
  assert.ok(at('rl-brief') >= 0, order.join(' '));
  assert.ok(at('rl-brief') < at('rl-intro-overview'), order.join(' '));
  assert.ok(at('rl-intro-overview') < at('rl-intro-papers'), order.join(' '));
  assert.ok(at('rl-intro-papers') < at('rl-intro-matters'), order.join(' '));
  assert.ok(at('rl-intro-matters') < at('rl-intro-take'), order.join(' '));
  assert.doesNotMatch(words(d), ISO);
});

test('each block hides when empty, with no filler in its place', () => {
  installDom();
  const bare = splash(EMPTY);
  for (const sel of ['section.rl-intro-overview', 'section.rl-intro-papers', 'section.rl-intro-matters', '.rl-brief-lines']) {
    assert.equal(bare.querySelector(sel), null, sel);
  }
  assert.ok(bare.querySelector('section.rl-brief'), 'the greeting always shows');
  assert.deepEqual(bare.querySelectorAll('button').map(words), [TAKE_DESK]);
  const some = splash({ ...EMPTY, figures: FIGURES });
  assert.deepEqual(some.querySelector('section.rl-intro-overview').querySelectorAll('h4').map(words), ['On your desk']);
  assert.equal(some.querySelector('section.rl-intro-papers'), null);
  const onlyPapers = splash({ ...EMPTY, papers: PAPERS.slice(0, 1) });
  assert.equal(onlyPapers.querySelector('section.rl-intro-overview'), null);
  assert.equal(onlyPapers.querySelector('section.rl-intro-matters'), null);
  assert.equal(onlyPapers.querySelectorAll('section.rl-intro-papers li').length, 1);
});

test('a paper title closes the splash and opens that paper', () => {
  installDom();
  const calls = [];
  const d = splash(OVERVIEW, { onDone: () => calls.push('done'), onPaper: (p) => calls.push(p.id) });
  d.querySelector('section.rl-intro-papers').querySelectorAll('button')[2].click();
  assert.deepEqual(calls, ['done', 'd-cable-1016']);
  d.querySelector('.rl-intro-take').click();
  assert.deepEqual(calls, ['done', 'd-cable-1016'], 'the splash finishes once');
});

test("the wake's aide brief fills in while the splash is open", (t) => {
  installDom();
  t.mock.timers.enable({ apis: ['setInterval'] });
  const held = { brief: null };
  const d = splash(OVERVIEW, { brief: () => held.brief });
  assert.equal(d.querySelector('.rl-brief-lines'), null, 'nothing yet');
  t.mock.timers.tick(BRIEF_POLL_MS);
  assert.equal(d.querySelector('.rl-brief-lines'), null);
  held.brief = { summary: 'The Speaker counts you short on the Neutrality revision.', decisions: 0, drafts: [] };
  t.mock.timers.tick(BRIEF_POLL_MS);
  const lines = d.querySelectorAll('.rl-brief-lines li').map(words);
  assert.deepEqual(lines, ['The Speaker counts you short on the Neutrality revision.']);
  assert.ok(words(d.querySelector('section.rl-brief')).includes(aideGreeting('20 October 1941')), 'the greeting stays');
  const ready = splash(OVERVIEW, { brief: () => held.brief });
  assert.deepEqual(ready.querySelectorAll('.rl-brief-lines li').map(words), lines, 'a brief already in shows at once');
});

test('the brief stops being watched once the splash is done', (t) => {
  installDom();
  t.mock.timers.enable({ apis: ['setInterval'] });
  let asked = 0;
  const d = splash(OVERVIEW, { brief: () => { asked += 1; return null; } });
  d.querySelector('.rl-intro-take').click();
  const before = asked;
  t.mock.timers.tick(BRIEF_POLL_MS * 5);
  assert.equal(asked, before);
});

test('no HTML parsing, no inline style, no stub left, linked and scoped', () => {
  const src = read('js/views/realism-intro.js');
  assert.doesNotMatch(src, /innerHTML|outerHTML|insertAdjacentHTML|style=|\.style\.|contract stub/);
  const css = read('css/p5-intro.css').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(read('css/p5-intro.css'), /contract stub/);
  assert.ok(css.trim().length > 0, 'the stylesheet has rules');
  assert.ok(read('index.html').includes('href="/css/p5-intro.css"'), 'linked from the page');
  for (const cls of ['.rl-intro-overview', '.rl-intro-papers', '.rl-intro-matters', '.rl-intro-paper']) assert.ok(css.includes(cls), cls);
  const outer = css.replace(/@(media|container|supports)[^{]+\{/g, '').replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, '');
  const sels = [...outer.matchAll(/([^{}]+)\{/g)].flatMap((m) => m[1].split(',')).map((s) => s.trim()).filter(Boolean);
  for (const sel of sels) assert.match(sel, /\.rl-intro/, sel);
});

// I3: the crawl fades into the splash; focus lands on the splash heading.
const uncomment = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');
const bodyOf = (css, sel) => {
  const at = css.search(new RegExp(`(^|\\})\\s*${sel.replace(/[.*>()[\]]/g, '\\$&')}\\s*\\{`));
  if (at < 0) return null;
  const open = css.indexOf('{', at + 1);
  return css.slice(open + 1, css.indexOf('}', open));
};

test('the splash fades in over about 600 ms, from a named token', () => {
  const css = uncomment(read('css/p5-intro.css'));
  const frame = bodyOf(css, '.rl-intro');
  assert.match(frame, /--rl-intro-fade:\s*600ms;/);
  const kids = bodyOf(css, '.rl-intro-splash > *');
  assert.ok(kids, 'a rule fades the splash content');
  const [, name] = kids.match(/animation:\s*([\w-]+)\s+var\(--rl-intro-fade\)[^;]*\bboth\b/) ?? [];
  assert.ok(name, kids);
  const keys = css.match(new RegExp(`@keyframes ${name}\\s*\\{\\s*from\\s*\\{\\s*opacity:\\s*0;\\s*\\}\\s*to\\s*\\{\\s*opacity:\\s*1;\\s*\\}\\s*\\}`));
  assert.ok(keys, `@keyframes ${name} from opacity 0 to 1`);
  assert.doesNotMatch(bodyOf(css, '.rl-intro-splash') ?? '', /animation|opacity/, 'the dialog itself stays opaque, so the room never shows through');
});

test('under reduced motion the splash does not fade', () => {
  const css = uncomment(read('css/p5-intro.css'));
  const at = css.indexOf('@media (prefers-reduced-motion: reduce)');
  assert.ok(at >= 0, 'a reduced-motion block');
  const block = css.slice(at, css.indexOf('}\n}', at) + 3);
  assert.match(block, /\.rl-intro-splash > \*\s*\{\s*animation:\s*none;\s*\}/);
});

test('the splash heading takes focus when the dialog opens', () => {
  installDom();
  const d = splash(OVERVIEW);
  const head = d.querySelector('h2');
  assert.equal(head.getAttribute('tabindex'), '-1', 'focusable from code only');
  assert.ok(head.hasAttribute('autofocus'), 'the dialog focuses it on showModal');
  assert.equal(d.querySelectorAll('[autofocus]').length, 1, 'nothing else claims the first focus');
});
