// Spec for unit Q5, written with contract KQ: the unit makes it pass and never edits it.
// The crawl fades in, Continue waits until the game is ready, and the phrases say what
// Begin is doing. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import * as crawlView from '../js/views/realism-crawl.js';
import { beginStatus, crawlParagraphs, introCrawl, markReady } from '../js/views/realism-crawl.js';
import { buttons, fire, installDom, words } from './dom-fake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-cast.json'));
const noComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');

const PHRASES = [
  'Drawing up the opening papers.',
  'Seating the cabinet and the staff.',
  'Setting the calendar.',
  "Sorting the first day's in-tray.",
  'Briefing your aide.',
  'Opening the first day.',
];

const crawlOf = (opts) => {
  const doc = installDom();
  const done = [];
  const dialog = introCrawl({ title: 'Autumn 1941', paragraphs: fixture.setting.crawl, onDone: () => done.push(1), ...opts });
  doc.body.append(dialog);
  dialog.showModal();
  const cont = buttons(dialog, 'Continue')[0];
  return { doc, dialog, done, cont };
};

test('the crawl: trimmed paragraphs, empties dropped, three at most', () => {
  assert.deepEqual(crawlParagraphs(fixture.setting), fixture.setting.crawl);
  assert.deepEqual(crawlParagraphs({ crawl: [' One. ', '', '  ', 'Two.', 'Three.', 'Four.'] }), ['One.', 'Two.', 'Three.']);
  assert.deepEqual(crawlParagraphs(null), []);
  assert.deepEqual(crawlParagraphs({ crawl: null }), []);
});

test('ready by default: Continue and Esc each finish once', () => {
  const { dialog, done, cont } = crawlOf({});
  assert.equal(dialog.querySelectorAll('.rl-intro-crawl p').length, fixture.setting.crawl.length);
  assert.ok(cont, 'a Continue button');
  assert.equal(cont.disabled, false);
  cont.click();
  assert.equal(fire(dialog, 'cancel').defaultPrevented, true);
  assert.equal(done.length, 1);
});

test('not ready: Continue is held and Esc is swallowed', () => {
  const { dialog, done, cont } = crawlOf({ ready: false });
  assert.equal(cont.disabled, true);
  cont.click();
  const esc = fire(dialog, 'cancel');
  assert.equal(esc.defaultPrevented, true, 'Esc does not close the dialog');
  assert.equal(done.length, 0);
});

test('markReady: Continue enabled and focused, the status says so, the phrases go', () => {
  const { doc, dialog, done, cont } = crawlOf({ ready: false });
  dialog.querySelector('.rl-intro-status').before(beginStatus());
  markReady(dialog);
  assert.equal(cont.disabled, false);
  assert.equal(doc.activeElement, cont);
  assert.equal(words(dialog.querySelector('.rl-intro-status')), 'Ready. Continue when you are.');
  assert.equal(dialog.querySelector('.rl-intro-phrases'), null);
  fire(dialog, 'cancel');
  cont.click();
  assert.equal(done.length, 1);
  const other = crawlOf({ ready: false });
  markReady(other.dialog, 'Your game is ready.');
  assert.equal(words(other.dialog.querySelector('.rl-intro-status')), 'Your game is ready.');
});

test('the phrases: six fixed lines, one item each, hidden from screen readers', () => {
  assert.deepEqual(crawlView.BEGIN_PHRASES, PHRASES);
  assert.ok(Object.isFrozen(crawlView.BEGIN_PHRASES));
  installDom();
  const list = beginStatus();
  assert.ok(list.matches('ul.rl-intro-phrases'));
  assert.equal(list.getAttribute('aria-hidden'), 'true');
  assert.deepEqual(list.querySelectorAll('li').map(words), PHRASES);
  assert.deepEqual(beginStatus(['One.', 'Two.']).querySelectorAll('li').map(words), ['One.', 'Two.']);
  assert.equal(list.getAttribute('role'), null, 'the status line stays the one live region');
});

test('the crawl fades in turn and stays: opacity only, no movement', () => {
  const css = noComments(read('css/p5-crawl.css'));
  const frames = [...css.matchAll(/@keyframes\s+([\w-]+)\s*\{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}/g)];
  const used = css.match(/\.rl-intro-crawl p\s*\{[^}]*animation:\s*([\w-]+)[^;]*\bboth\b[^;]*;/);
  assert.ok(used, 'the paragraphs run a keyframes animation with fill both');
  const body = frames.find((m) => m[1] === used[1])?.[2] ?? '';
  assert.match(body, /opacity:\s*0\b/);
  assert.match(body, /opacity:\s*1\b/);
  assert.doesNotMatch(body, /transform|translate|top:|margin/);
  assert.doesNotMatch(css, /\.rl-intro-crawl p:nth-child/, 'the hold classes time the paragraphs, not their position');
});

test('holdClass: about 3.5 words a second, at least 4 s and at most 14 s, by band', () => {
  const { holdClass, HOLD_SECONDS, SHORT_MAX_WORDS, MEDIUM_MAX_WORDS, LONG_MAX_WORDS } = crawlView;
  assert.deepEqual(Object.keys(HOLD_SECONDS), ['short', 'medium', 'long', 'xlong']);
  assert.ok(Object.isFrozen(HOLD_SECONDS));
  assert.equal(HOLD_SECONDS.short, 4);
  assert.equal(HOLD_SECONDS.xlong, 14);
  assert.equal(SHORT_MAX_WORDS / 3.5, HOLD_SECONDS.short);
  assert.equal(MEDIUM_MAX_WORDS / 3.5, HOLD_SECONDS.medium);
  assert.equal(LONG_MAX_WORDS / 3.5, HOLD_SECONDS.long);
  assert.ok(LONG_MAX_WORDS / 3.5 < HOLD_SECONDS.xlong);
  const cases = [
    [0, 'short'], [1, 'short'], [SHORT_MAX_WORDS, 'short'],
    [SHORT_MAX_WORDS + 1, 'medium'], [MEDIUM_MAX_WORDS, 'medium'],
    [MEDIUM_MAX_WORDS + 1, 'long'], [LONG_MAX_WORDS, 'long'],
    [LONG_MAX_WORDS + 1, 'xlong'], [400, 'xlong'],
    [Number.NaN, 'short'], [undefined, 'short'], [-3, 'short'],
  ];
  for (const [n, want] of cases) assert.equal(holdClass(n), want, `${n} words`);
});

test('each paragraph carries its hold class and starts when the ones before it have held', () => {
  const { HOLD_SECONDS } = crawlView;
  const say = (n) => Array.from({ length: n }, (_, i) => `w${i}`).join(' ');
  const { dialog } = crawlOf({ paragraphs: [say(10), say(40), say(20)] });
  const ps = dialog.querySelectorAll('.rl-intro-crawl p');
  assert.deepEqual(ps.map((p) => p.className), [
    'rl-hold-short rl-at-0',
    `rl-hold-long rl-at-${HOLD_SECONDS.short}`,
    `rl-hold-medium rl-at-${HOLD_SECONDS.short + HOLD_SECONDS.long}`,
  ]);
  assert.equal(words(ps[1]), say(40));
  const autumn = crawlOf({}).dialog.querySelectorAll('.rl-intro-crawl p').map((p) => p.className.split(' ')[0]);
  assert.deepEqual(autumn, fixture.setting.crawl.map((p) => `rl-hold-${crawlView.holdClass(p.split(/\s+/).length)}`));
});

test('the stylesheet has a delay rule for every start the classes can reach, and no others', () => {
  const { HOLD_SECONDS } = crawlView;
  const css = noComments(read('css/p5-crawl.css'));
  const holds = Object.values(HOLD_SECONDS);
  const max = crawlParagraphs({ crawl: Array(10).fill('x') }).length;
  let starts = new Set([0]);
  const reach = new Set();
  for (let i = 1; i < max; i += 1) {
    starts = new Set([...starts].flatMap((s) => holds.map((h) => s + h)));
    for (const s of starts) reach.add(s);
  }
  for (const s of reach) {
    assert.match(css, new RegExp(`\\.rl-intro-crawl p\\.rl-at-${s}\\s*\\{\\s*animation-delay:\\s*${s}s;\\s*\\}`), `start ${s}s`);
  }
  const rules = [...css.matchAll(/\.rl-at-(\d+)\b/g)].map((m) => Number(m[1]));
  assert.deepEqual([...new Set(rules)].sort((a, b) => a - b), [...reach].sort((a, b) => a - b), 'capped at the reachable starts');
});

for (const how of ['click', 'keydown']) {
  test(`a ${how} on the crawl shows every paragraph at once; Continue still waits on Begin`, () => {
    const { dialog, done, cont } = crawlOf({ ready: false });
    assert.equal(dialog.hasAttribute('data-shown'), false);
    fire(dialog, how);
    assert.equal(dialog.hasAttribute('data-shown'), true);
    assert.equal(cont.disabled, true);
    assert.equal(done.length, 0);
    const css = noComments(read('css/p5-crawl.css'));
    assert.match(css, /\.rl-intro\[data-shown\] \.rl-intro-crawl p\s*\{\s*animation:\s*none;\s*\}/);
  });
}

test('the phrases show one at a time by CSS, a still first line under reduced motion', () => {
  const css = noComments(read('css/p5-crawl.css'));
  for (let i = 1; i <= PHRASES.length; i += 1) {
    assert.match(css, new RegExp(`\\.rl-intro-phrases li:nth-child\\(${i}\\)\\s*\\{\\s*animation-delay:`), `delay rule ${i}`);
  }
  const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'));
  assert.match(reduced, /\.rl-intro-crawl p/);
  assert.match(reduced, /\.rl-intro-phrases li:first-child/);
});

test('no timers, no HTML parsing, no inline style, no stub left, linked and scoped', () => {
  const src = read('js/views/realism-crawl.js');
  assert.doesNotMatch(src, /setInterval|setTimeout|requestAnimationFrame/);
  assert.doesNotMatch(src, /innerHTML|outerHTML|insertAdjacentHTML|style=|\.style\.|'style'|contract stub/);
  const raw = read('css/p5-crawl.css');
  assert.doesNotMatch(raw, /contract stub/);
  assert.ok(read('index.html').includes('href="/css/p5-crawl.css"'), 'linked from the page');
  const outer = noComments(raw).replace(/@(media|container|supports)[^{]+\{/g, '').replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, '');
  const sels = [...outer.matchAll(/([^{}]+)\{/g)].flatMap((m) => m[1].split(',')).map((s) => s.trim()).filter(Boolean);
  assert.ok(sels.length > 0, 'the stylesheet has rules');
  for (const sel of sels) assert.match(sel, /\.rl-intro/, sel);
});
