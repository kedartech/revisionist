// Spec for 15a unit U2 (responsive shell), written with the console contract: the unit makes
// it pass and never edits it. Three columns at 1200 px and up; desk plus one switchable side
// panel (Papers or Your orders, opening on Papers) from 768 to 1199 px; one panel at a time with
// a bottom tab bar under 768 px, where the messenger launcher moves into the tab bar.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
const { sideSwitch, tabBar } = await import('../js/views/realism-tabs.js');

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const OWNS = ['js/views/realism-tabs.js', 'css/c-shell.css', 'css/p5-launcher.css'];
const rv = { ...fixture, documents: { ...fixture.listing, unread: 5 } };
const ui = (tab = 'desk', side = 'papers') => ({ tab, side, chat: { open: false } });

/** The body of the first `@media <query> { ... }` block in `css`, or null. */
function media(css, query) {
  const at = css.indexOf(`@media ${query}`);
  if (at < 0) return null;
  let depth = 0;
  for (let i = css.indexOf('{', at); i < css.length; i++) {
    if (css[i] === '{') depth++;
    else if (css[i] === '}' && --depth === 0) return css.slice(css.indexOf('{', at) + 1, i);
  }
  return null;
}

test('the tab bar names the four panels and marks the open one', () => {
  const bar = tabBar(rv, ui('desk'), () => {});
  assert.equal(bar.tagName.toLowerCase(), 'nav');
  assert.ok(bar.getAttribute('aria-label'), 'a named navigation region');
  const all = bar.querySelectorAll('button');
  assert.equal(all.length, 4);
  assert.deepEqual(all.map((b) => words(b).split(' ')[0]), ['Papers', 'Desk', 'Orders', 'Messages']);
  assert.deepEqual(all.map((b) => b.getAttribute('aria-current')), [null, 'page', null, null]);
  assert.deepEqual(all.map((b) => b.getAttribute('type')), ['button', 'button', 'button', 'button']);
});

test('a tap picks its panel by tab', () => {
  const picked = [];
  const bar = tabBar(rv, ui('desk'), (p) => picked.push(p));
  for (const b of bar.querySelectorAll('button')) b.click();
  assert.deepEqual(picked, [{ tab: 'papers' }, { tab: 'desk' }, { tab: 'orders' }, { tab: 'messages' }]);
});

test('counts in words: unread papers and the orders that need you', () => {
  const orders = { orders: fixture.orders.orders.map((o, i) => ({ ...o, decision_needed: i === 1 })) };
  const bar = tabBar({ ...rv, orders }, ui('desk'), () => {});
  assert.equal(bar.querySelectorAll('button').length, 4, 'four tabs');
  const [papers, , mine] = bar.querySelectorAll('button');
  assert.match(words(papers), /\b5\b/);
  assert.match(words(mine), /\b1\b/);
  const quiet = tabBar({ ...rv, documents: { ...fixture.listing, unread: 0 }, orders: { orders: [] } }, ui('desk'), () => {});
  const [p0, , o0] = quiet.querySelectorAll('button');
  assert.equal(words(p0), 'Papers');
  assert.equal(words(o0), 'Orders');
});

test('the side switch: Papers or Your orders, pressed by ui.side, picks by side', () => {
  const picked = [];
  const sw = sideSwitch(ui('desk', 'papers'), (p) => picked.push(p));
  const [papers] = buttons(sw, 'Papers');
  const [orders] = buttons(sw, 'Your orders');
  assert.ok(papers && orders, 'two buttons, Papers and Your orders');
  assert.equal(papers.getAttribute('aria-pressed'), 'true');
  assert.equal(orders.getAttribute('aria-pressed'), 'false');
  orders.click();
  papers.click();
  assert.deepEqual(picked, [{ side: 'orders' }, { side: 'papers' }]);
  const flipped = sideSwitch(ui('desk', 'orders'), () => {});
  assert.equal(buttons(flipped, 'Your orders')[0].getAttribute('aria-pressed'), 'true');
});

test('the shell: three columns from 1200 px, desk and a side panel from 768, one panel under 768', () => {
  const css = uncomment(read('css/c-shell.css'));
  assert.doesNotMatch(css, /max-width:\s*1100px/, 'the old one-column break is gone');
  assert.ok(media(css, '(min-width: 1200px)'), 'a block from 1200 px');
  const tablet = media(css, '(min-width: 768px) and (max-width: 1199px)');
  assert.ok(tablet, 'a block from 768 to 1199 px');
  assert.match(tablet, /\[data-side/, 'the tablet shows the side panel ui.side names');
  assert.match(tablet, /\.rl-sideswitch/);
  const phone = media(css, '(max-width: 767px)');
  assert.ok(phone, 'a block under 768 px');
  assert.match(phone, /\[data-view/, 'the phone shows the panel ui.tab names');
  assert.match(phone, /\.rl-tabbar/);
  assert.match(css, /\.rl-tabbar\s*\{[^}]*display:\s*none/, 'no tab bar outside the phone');
  assert.match(css, /\.rl-sideswitch\s*\{[^}]*display:\s*none/, 'no side switch outside the tablet');
});

test('on a phone the messenger launcher leaves the corner for the tab bar', () => {
  const phone = media(uncomment(read('css/p5-launcher.css')), '(max-width: 767px)');
  assert.ok(phone, 'a block under 768 px');
  assert.match(phone, /\.rl-msgr-btn\s*\{[^}]*display:\s*none/);
});

test('owned files: no HTML parsing, no inline style, no colour literal', () => {
  for (const f of OWNS) {
    const src = uncomment(read(f));
    assert.doesNotMatch(src, /innerHTML|style=|\.style\./, f);
    if (f.endsWith('.css')) assert.doesNotMatch(src, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, f);
  }
});
