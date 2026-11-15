// Spec for the opening crawl: each paragraph types itself out letter by letter, Continue
// waits until the game is ready, and the phrases say what Begin is doing. Timers are a
// fake passed in, so a tick is one timer firing. Run: node --test web/test/
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

// A fake timer pair: `set` queues, `tick()` fires the oldest pending callback and returns its delay.
const fakeTimers = () => {
  const queue = [];
  let id = 0;
  return {
    sets: 0,
    set(fn, ms) {
      this.sets += 1;
      id += 1;
      queue.push({ id, fn, ms });
      return id;
    },
    clear(k) {
      const i = queue.findIndex((x) => x.id === k);
      if (i >= 0) queue.splice(i, 1);
    },
    get pending() { return queue.map((x) => x.ms); },
    tick() {
      const next = queue.shift();
      next?.fn();
      return next?.ms;
    },
  };
};

const crawlOf = (opts) => {
  const doc = installDom();
  const done = [];
  const timers = fakeTimers();
  const dialog = introCrawl({ title: 'Autumn 1941', paragraphs: fixture.setting.crawl, onDone: () => done.push(1), timers, ...opts });
  doc.body.append(dialog);
  dialog.showModal();
  const cont = buttons(dialog, 'Continue')[0];
  return { doc, dialog, done, cont, timers: opts?.timers ?? timers };
};

const paras = (dialog) => dialog.querySelectorAll('.rl-intro-crawl p');
const typed = (p) => p.querySelector('.rl-intro-typed').textContent;
const untyped = (p) => p.querySelector('.rl-intro-untyped').textContent;
const key = (el, k) => el.dispatchEvent({ type: 'keydown', key: k, target: null, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} });

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


test('typing: after k ticks the first paragraph shows its first k characters; the next waits for it and the pause', () => {
  const { CHARS_PER_SECOND, PAUSE_MS } = crawlView;
  assert.equal(CHARS_PER_SECOND, 40);
  assert.equal(PAUSE_MS, 600);
  const step = 1000 / CHARS_PER_SECOND;
  const one = 'Hello there.';
  const two = 'Second one.';
  const { dialog, timers } = crawlOf({ paragraphs: [one, two] });
  const [p1, p2] = paras(dialog);
  assert.equal(typed(p1), '');
  assert.equal(typed(p2), '');
  assert.deepEqual(timers.pending, [step], 'one timer out, at the typing rate');
  for (let k = 1; k <= one.length; k += 1) {
    assert.equal(timers.tick(), step);
    assert.equal(typed(p1), one.slice(0, k), `after ${k} ticks`);
    assert.equal(typed(p2), '', `the second paragraph waits (tick ${k})`);
  }
  assert.deepEqual(timers.pending, [PAUSE_MS], 'the pause comes after a whole paragraph');
  assert.equal(typed(p2), '');
  assert.equal(timers.tick(), PAUSE_MS);
  assert.equal(typed(p2), 'S');
  while (timers.pending.length) timers.tick();
  assert.equal(typed(p1), one);
  assert.equal(typed(p2), two);
});

test('the whole text is there for a screen reader from the start; the typed copy is hidden from it', () => {
  const text = 'Autumn, and the war is two years old.';
  const { dialog, timers } = crawlOf({ paragraphs: [text] });
  const [p] = paras(dialog);
  const said = p.querySelector('.rl-intro-said');
  assert.ok(said?.matches('.sr-only'), 'the full text sits in a screen-reader-only span');
  assert.equal(said.textContent, text);
  assert.equal(said.getAttribute('aria-hidden'), null);
  for (const cls of ['.rl-intro-typed', '.rl-intro-untyped']) assert.equal(p.querySelector(cls).getAttribute('aria-hidden'), 'true', cls);
  for (let k = 0; k <= text.length; k += 1) {
    assert.equal(typed(p) + untyped(p), text, 'typed and still to type make the whole paragraph, so nothing moves');
    assert.equal(said.textContent, text);
    timers.tick();
  }
  const css = noComments(read('css/p5-crawl.css'));
  assert.match(css, /\.rl-intro-untyped\s*\{[^}]*visibility:\s*hidden;/, 'the part still to type holds its place, unseen');
});

for (const [how, act] of [['Enter', (d) => key(d, 'Enter')], ['Space', (d) => key(d, ' ')], ['a click', (d) => fire(d, 'click')]]) {
  test(`${how} mid-paragraph shows the whole paragraph and starts the pause; Continue still waits on Begin`, () => {
    const { PAUSE_MS } = crawlView;
    const one = 'The first paragraph.';
    const two = 'The second.';
    const { dialog, done, cont, timers } = crawlOf({ ready: false, paragraphs: [one, two] });
    const [p1, p2] = paras(dialog);
    timers.tick();
    timers.tick();
    timers.tick();
    assert.equal(typed(p1), 'The');
    act(dialog);
    assert.equal(typed(p1), one);
    assert.equal(untyped(p1), '');
    assert.equal(typed(p2), '');
    assert.deepEqual(timers.pending, [PAUSE_MS], 'the typing timer is dropped and the pause starts');
    act(dialog);
    assert.equal(typed(p2), '', 'during the pause it does nothing');
    assert.deepEqual(timers.pending, [PAUSE_MS]);
    timers.tick();
    assert.equal(typed(p2), 'T');
    assert.equal(cont.disabled, true);
    assert.equal(done.length, 0);
  });
}

test('other keys leave the typing alone', () => {
  const { dialog, timers } = crawlOf({ paragraphs: ['Some words here.'] });
  const [p] = paras(dialog);
  timers.tick();
  for (const k of ['a', 'Tab', 'Shift', 'ArrowDown']) key(dialog, k);
  assert.equal(typed(p), 'S');
});

test('reduced motion: every paragraph whole on first draw, and no timer was set', () => {
  const was = globalThis.matchMedia;
  const asked = [];
  try {
    globalThis.matchMedia = (q) => {
      asked.push(q);
      return { matches: q === '(prefers-reduced-motion: reduce)' };
    };
    const { dialog, timers } = crawlOf({});
    assert.ok(asked.includes('(prefers-reduced-motion: reduce)'));
    assert.deepEqual(paras(dialog).map(typed), fixture.setting.crawl);
    assert.deepEqual(paras(dialog).map(untyped), fixture.setting.crawl.map(() => ''));
    assert.equal(timers.sets, 0);
    globalThis.matchMedia = () => ({ matches: false });
    const moving = crawlOf({});
    assert.equal(typed(paras(moving.dialog)[0]), '');
    assert.equal(moving.timers.sets, 1);
  } finally {
    globalThis.matchMedia = was;
  }
});

test('closing the crawl stops the typing', () => {
  const { dialog, timers } = crawlOf({});
  timers.tick();
  assert.equal(timers.pending.length, 1);
  dialog.close();
  assert.deepEqual(timers.pending, []);
});

test('no caret on the crawl; the phrases show one at a time by CSS, a still first line under reduced motion', () => {
  const { dialog } = crawlOf({});
  assert.equal(dialog.querySelectorAll('.rl-cursor').length, 0);
  const css = noComments(read('css/p5-crawl.css'));
  assert.doesNotMatch(css, /::?(after|before)|rl-cursor|caret/);
  for (let i = 1; i <= PHRASES.length; i += 1) {
    assert.match(css, new RegExp(`\\.rl-intro-phrases li:nth-child\\(${i}\\)\\s*\\{\\s*animation-delay:`), `delay rule ${i}`);
  }
  const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'));
  assert.match(reduced, /\.rl-intro-phrases li:first-child/);
});

test('one timer at a time and only the ones passed in; no HTML parsing, no inline style, linked and scoped', () => {
  const src = read('js/views/realism-crawl.js');
  assert.doesNotMatch(src, /setInterval|requestAnimationFrame/);
  assert.doesNotMatch(src, /innerHTML|outerHTML|insertAdjacentHTML|style=|\.style\.|'style'|contract stub/);
  const raw = read('css/p5-crawl.css');
  assert.doesNotMatch(raw, /contract stub/);
  assert.ok(read('index.html').includes('href="/css/p5-crawl.css"'), 'linked from the page');
  const outer = noComments(raw).replace(/@(media|container|supports)[^{]+\{/g, '').replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, '');
  const sels = [...outer.matchAll(/([^{}]+)\{/g)].flatMap((m) => m[1].split(',')).map((s) => s.trim()).filter(Boolean);
  assert.ok(sels.length > 0, 'the stylesheet has rules');
  for (const sel of sels) assert.match(sel, /\.rl-intro/, sel);
});
