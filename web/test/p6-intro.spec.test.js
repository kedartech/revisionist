// Spec for Train 3 unit P4 (contract K3), revised for unit Q8 (contract KQ): the splash says
// how the seat starts. The crawl's spec is p6-crawl.spec.test.js. The unit makes it pass and
// never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { INTRO_PREFIX, NOT_BINDING, TAKE_DESK, introStage, markIntro, seatSplash, splashModel, startOverview } from '../js/views/realism-intro.js';
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
const { setting, desk } = fixture;
const fdr = fixture.roster[0];

test('the splash from the desk and the dossier', () => {
  const m = splashModel('Franklin D. Roosevelt', desk, fdr.dossier);
  assert.deepEqual(m, {
    title: 'You are Franklin D. Roosevelt',
    office: 'President of the United States',
    answersTo: 'Answers to The electorate, Congress',
    arena: fdr.dossier.arena,
    history: fdr.dossier.history,
    note: NOT_BINDING,
    action: TAKE_DESK,
    overview: null,
  });
  assert.equal(TAKE_DESK, 'Take your desk');
});

test('the splash hides what it does not have', () => {
  const m = splashModel('Burton K. Wheeler', { office: '', principals: [] }, null);
  assert.equal(m.office, null);
  assert.equal(m.answersTo, null);
  assert.equal(m.arena, null);
  assert.deepEqual(m.history, []);
  assert.equal(m.note, null);
  assert.equal(m.title, 'You are Burton K. Wheeler');
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

test('the splash dialog: Take your desk, Esc', () => {
  const src = read('js/views/realism-intro.js');
  for (const s of [/'dialog'/, /TAKE_DESK/, /'cancel'|oncancel/, /portraitNode\(/, /As history had it/]) assert.match(src, s);
});

const OVERVIEW = {
  forces: ['US Atlantic Fleet: Reykjavik'],
  figures: [
    'Allied merchant losses to U-boats, Sep 1941: 209,835 GRT',
    "Gallup, Roosevelt's course 'about right': 56 percent",
    'House votes for Neutrality revision: 220 votes',
  ],
  first: 'Keep the convoys moving to Iceland (due 26 October 1941)',
};

test('the starting overview: own forces, the figures on the desk, the first matter', () => {
  assert.deepEqual(startOverview(room), OVERVIEW);
  assert.deepEqual(startOverview({ map: room.map, situation: room.situation, agenda: room.agenda }), OVERVIEW);
  assert.deepEqual(startOverview({}), { forces: [], figures: [], first: null });
  assert.deepEqual(startOverview({ map: null, situation: null, agenda: null }), { forces: [], figures: [], first: null });
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
  assert.deepEqual(startOverview({ situation: { ...room.situation, figures } }).figures, [
    "Gallup, Roosevelt's course 'about right': 56 percent",
    'House votes for Neutrality revision: 220 votes',
    'Allied merchant losses to U-boats, Sep 1941: 209,835 GRT',
  ]);
  const oil = room.situation.figures.filter((f) => f.label === 'Japanese oil stocks');
  assert.deepEqual(startOverview({ situation: { figures: oil } }).figures, []);
  const item = { ...room.agenda.items[0], deadline: null };
  assert.equal(startOverview({ agenda: { ...room.agenda, items: [item] } }).first, 'Keep the convoys moving to Iceland');
  assert.equal(startOverview({ agenda: { ...room.agenda, items: [] } }).first, null);
});

test('the splash carries the overview; null when it has nothing', () => {
  assert.deepEqual(splashModel('Franklin D. Roosevelt', desk, fdr.dossier, OVERVIEW).overview, OVERVIEW);
  assert.equal(splashModel('Franklin D. Roosevelt', desk, fdr.dossier, { forces: [], figures: [], first: null }).overview, null);
  assert.equal(splashModel('Franklin D. Roosevelt', desk, fdr.dossier).overview, null);
});

test('"How you start" sits between the arena and the history, each part hidden when empty', () => {
  installDom();
  const splash = (overview) => seatSplash({
    name: 'Franklin D. Roosevelt', dossier: null,
    model: splashModel('Franklin D. Roosevelt', desk, fdr.dossier, overview),
  });
  const full = splash(OVERVIEW);
  const section = full.querySelector('section.rl-intro-overview');
  assert.ok(section, 'section.rl-intro-overview');
  assert.equal(words(section.querySelector('h3')), 'How you start');
  assert.deepEqual(section.querySelectorAll('h4').map(words), ['Your forces', 'On your desk', 'First matter']);
  for (const line of [...OVERVIEW.forces, ...OVERVIEW.figures, OVERVIEW.first]) assert.ok(words(section).includes(line), line);
  const order = full.children.map((c) => c.className.split(' ')[0]);
  const at = (cls) => order.indexOf(cls);
  assert.ok(at('rl-intro-arena') >= 0 && at('rl-intro-arena') < at('rl-intro-overview'), order.join(' '));
  assert.ok(at('rl-intro-overview') < at('rl-intro-history'), order.join(' '));
  const some = splash({ forces: [], figures: OVERVIEW.figures, first: null }).querySelector('section.rl-intro-overview');
  assert.deepEqual(some.querySelectorAll('h4').map(words), ['On your desk']);
  assert.equal(splash(null).querySelector('section.rl-intro-overview'), null);
  assert.match(read('css/p5-intro.css'), /\.rl-intro-overview/);
});

test('no HTML parsing, no inline style, no stub left, linked and scoped', () => {
  const src = read('js/views/realism-intro.js');
  assert.doesNotMatch(src, /innerHTML|outerHTML|insertAdjacentHTML|style=|\.style\.|contract stub/);
  const css = read('css/p5-intro.css').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(read('css/p5-intro.css'), /contract stub/);
  assert.ok(css.trim().length > 0, 'the stylesheet has rules');
  assert.ok(read('index.html').includes('href="/css/p5-intro.css"'), 'linked from the page');
  const outer = css.replace(/@(media|container|supports)[^{]+\{/g, '').replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, '');
  const sels = [...outer.matchAll(/([^{}]+)\{/g)].flatMap((m) => m[1].split(',')).map((s) => s.trim()).filter(Boolean);
  for (const sel of sels) assert.match(sel, /\.rl-intro/, sel);
});
