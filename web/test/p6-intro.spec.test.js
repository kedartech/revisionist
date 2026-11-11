// Spec for Train 3 unit P4, written with contract K3: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { INTRO_PREFIX, NOT_BINDING, TAKE_DESK, crawlParagraphs, introStage, markIntro, splashModel } from '../js/views/realism-intro.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-cast.json'));
const ISO = /\b\d{4}-\d{2}-\d{2}\b/;

const memory = () => {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), m };
};
const broken = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
const { setting, desk } = fixture;
const fdr = fixture.roster[0];

test('the crawl: trimmed paragraphs, empties dropped, three at most', () => {
  assert.deepEqual(crawlParagraphs(setting), setting.crawl);
  assert.deepEqual(crawlParagraphs({ crawl: [' One. ', '', '  ', 'Two.', 'Three.', 'Four.'] }), ['One.', 'Two.', 'Three.']);
  assert.deepEqual(crawlParagraphs(null), []);
  assert.deepEqual(crawlParagraphs({ crawl: null }), []);
});

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

test('the dialogs: Continue, Take your desk, Esc, reduced motion', () => {
  const src = read('js/views/realism-intro.js');
  for (const s of [/'dialog'/, /'Continue'/, /TAKE_DESK/, /'cancel'|oncancel/, /'status'/, /portraitNode\(/, /As history had it/]) assert.match(src, s);
  const css = read('css/p5-intro.css');
  assert.match(css, /@keyframes/);
  assert.match(css, /prefers-reduced-motion: reduce/);
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
