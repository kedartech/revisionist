// Wake playback: the overlay laid over a running wake holds the room and plays nothing; what
// happened plays once the wake has run, from the catch-up reply's steps (realism-playback.js,
// web/test/g13-true-playback.test.js). The overlay sits over every fixed bar of the room.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import * as overlay from '../js/views/realism-overlay.js';
import { installDom } from './dom-fake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const css = () => read('css/p5-overlay.css');

test('the overlay over a running wake plays no reel: no step, no path copy, and the lines do not wait', () => {
  installDom();
  const layer = overlay.wakeOverlay({
    message: 'The day is running', lines: ['A line.'], map: fixture.map, orders: fixture.record.orders,
  });
  assert.equal(layer.querySelector('section.rl-ovl-play'), null);
  assert.equal(layer.querySelectorAll('li.rl-ovl-step').length, 0);
  assert.equal(layer.querySelector('.rl-ovl-path'), null);
  assert.ok(!layer.querySelector('ul.rl-ovl-lines').className.includes('rl-ovl-wait'));
  assert.equal(overlay.withPlayback, undefined);
  assert.doesNotMatch(css(), /rl-ovl-(step|reel|play|wait|tok)\b/);
});

test('the room hands the overlay its map and record only, and keeps no map from before the run', () => {
  const room = read('js/views/realism-room.js');
  assert.match(room, /root\.append\(wakeOverlay\(\{ message, lines: overlayLines\(rv\.setting, rv\.wake\.wake\), map: rv\.map, orders: rv\.record\?\.orders \}\)\);/);
  assert.doesNotMatch(room, /runFrom|withPlayback\(/);
});

test('the layer sits over every fixed bar and button of the room', async () => {
  const { readdirSync } = await import('node:fs');
  const z = (text) => [...text.matchAll(/z-index:\s*(\d+)/g)].map((m) => Number(m[1]));
  const own = Number(css().match(/\.rl-ovl \{[^}]*z-index:\s*(\d+)/)[1]);
  const others = readdirSync(join(WEB, 'css')).filter((f) => f.endsWith('.css') && f !== 'p5-overlay.css')
    .flatMap((f) => z(read(`css/${f}`)));
  assert.ok(others.length > 0);
  assert.ok(own > Math.max(...others), `${own} over ${Math.max(...others)}`);
});
