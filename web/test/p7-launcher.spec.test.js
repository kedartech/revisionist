// Spec for wave M unit M1 (the launcher), written with contract KM: the unit makes it pass and
// never edits it. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';
import { chatLauncher } from '../js/views/realism-launcher.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');

test('a speech-bubble button named Messages, with the state it opens', () => {
  installDom();
  let toggled = 0;
  const b = chatLauncher({ open: false, total: 0, onToggle: () => { toggled += 1; }, onKey: null });
  assert.ok(b, 'a button');
  assert.equal(b.tagName, 'BUTTON');
  assert.equal(b.getAttribute('type'), 'button');
  assert.ok(b.classList.contains('rl-msgr-btn'));
  assert.equal(b.getAttribute('aria-expanded'), 'false');
  assert.ok(b.querySelector('svg'), 'the chat icon');
  assert.equal(words(b), 'Messages', 'the name is the only words with nothing unread');
  assert.ok(b.querySelector('.sr-only'), 'the name is visually hidden beside the icon');
  assert.equal(b.querySelector('.rl-msgr-count'), null);
  b.click();
  assert.equal(toggled, 1);
});

test('the unread count is a badge with a hidden word, and Esc reaches the room while open', () => {
  installDom();
  const keys = [];
  const b = chatLauncher({ open: true, total: 3, onToggle: () => {}, onKey: (e) => keys.push(e.key) });
  assert.equal(b.getAttribute('aria-expanded'), 'true');
  const count = b.querySelector('.rl-msgr-count');
  assert.ok(count);
  assert.equal(words(count), '3 unread');
  assert.equal(words(count.querySelector('.sr-only')), 'unread');
  b.dispatchEvent({ type: 'keydown', key: 'Escape', preventDefault() {}, stopPropagation() {} });
  assert.deepEqual(keys, ['Escape']);
});

test('a chat glyph, a large target, and clear of the tray on a phone', () => {
  assert.match(read('js/dom.js'), /\n\s+chat: \[/);
  const css = read('css/p5-launcher.css');
  assert.doesNotMatch(css, /contract stub/);
  assert.match(css, /\.rl-msgr-btn\s*\{[^}]*position:\s*fixed/);
  assert.match(css, /\.rl-msgr-btn\s*\{[^}]*min-width:\s*44px/);
  assert.match(css, /\.rl-msgr-btn\s*\{[^}]*min-height:\s*44px/);
  assert.match(css, /\.rl-msgr-count\s*\{/);
  assert.match(css, /@media[^{]*max-width:\s*480px[^{]*\{[^}]*\.rl-msgr-btn/);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b/, 'colours come from the tokens');
});

test('on a phone the open launcher stays, beside the title, as the full-screen panel\'s close', () => {
  const css = read('css/p5-launcher.css').replace(/\/\*[\s\S]*?\*\//g, '');
  const at = css.indexOf('@media (max-width: 767px)');
  assert.ok(at >= 0, 'a block under 768 px');
  const phone = css.slice(at, css.indexOf('\n}', at));
  const open = /\.rl-msgr-btn\[aria-expanded="true"\]\s*\{([^}]*)\}/.exec(phone);
  assert.ok(open, 'a rule for the open launcher under 768 px');
  assert.match(open[1], /display:\s*inline-flex/);
  assert.match(open[1], /top:\s*var\(--space-2\)/);
  assert.match(open[1], /bottom:\s*auto/);
});
