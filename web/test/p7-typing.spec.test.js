// Spec for wave M unit M3 (the typing indicator), written with contract KM: the unit makes it pass and
// never edits it. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';
import { typingBubble, typingFor } from '../js/views/realism-typing.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');

test('who is writing: the thread the pending message went to, and no other', () => {
  const pending = { thread: 'Harry Hopkins', text: 'Will Moscow hold?' };
  assert.equal(typingFor(pending, 'Harry Hopkins'), 'Harry Hopkins');
  assert.equal(typingFor(pending, 'Sam Rayburn'), null);
  assert.equal(typingFor(null, 'Harry Hopkins'), null);
  assert.equal(typingFor({ thread: 'aide', text: 'How?' }, 'aide'), 'Your aide');
});

test('three dots in their bubble, and a hidden status line for a screen reader', () => {
  installDom();
  const b = typingBubble('Harry Hopkins');
  assert.ok(b, 'a bubble');
  for (const c of ['rl-typing', 'rl-th-bubble', 'theirs']) assert.ok(b.classList.contains(c), c);
  assert.equal(b.querySelectorAll('.rl-typing-dot').length, 3);
  for (const d of b.querySelectorAll('.rl-typing-dot')) assert.equal(d.getAttribute('aria-hidden'), 'true');
  const status = b.querySelector('[role="status"]');
  assert.ok(status);
  assert.ok(status.classList.contains('sr-only'));
  assert.equal(words(status), 'Harry Hopkins is writing');
});

test('the dots move by CSS, and stand still under reduced motion', () => {
  const css = read('css/p5-typing.css');
  assert.doesNotMatch(css, /contract stub/);
  assert.match(css, /@keyframes/);
  assert.match(css, /\.rl-typing-dot\s*\{[^}]*animation/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[^{]*\{[^}]*\.rl-typing-dot[^}]*animation:\s*none/);
  const src = read('js/views/realism-typing.js');
  assert.doesNotMatch(src, /setTimeout|setInterval|requestAnimationFrame/);
});
