// Two things the test DOM hides that a real browser trips on (SMK). The wake overlay draws its
// picture in degrees, so a game on a flat hand-written map (Salt Strait) gets no picture; and no
// view calls an array method on the NodeList querySelectorAll returns.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { wakeOverlay } from '../js/views/realism-overlay.js';
import { installDom } from './dom-fake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const fixture = JSON.parse(readFileSync(join(WEB, 'test/fixtures/realism-seat.json'), 'utf8'));

test('a flat map draws no picture in the wake overlay; a lon/lat map still does', () => {
  installDom();
  const flat = wakeOverlay({ message: 'm', lines: [], map: { ...fixture.map, coords: 'flat' }, orders: [] });
  assert.equal(flat.querySelectorAll('figure.rl-ovl-map').length, 0);
  const degrees = wakeOverlay({ message: 'm', lines: [], map: { ...fixture.map, coords: 'lonlat' }, orders: [] });
  assert.equal(degrees.querySelectorAll('figure.rl-ovl-map').length, 1);
});

test('no view calls an array method on a NodeList straight from querySelectorAll', () => {
  // the browser's NodeList has forEach but not find, map, filter, some, every or reduce; the
  // test DOM's lists are arrays, so only the browser smoke would catch one
  const bad = [];
  for (const dir of ['js', 'js/views']) {
    for (const f of readdirSync(join(WEB, dir)).filter((n) => n.endsWith('.js'))) {
      const src = readFileSync(join(WEB, dir, f), 'utf8');
      for (const m of src.matchAll(/querySelectorAll\([^()]*\)\.(find|map|filter|some|every|reduce|slice)\(/g)) bad.push(`${dir}/${f}: ${m[0]}`);
    }
  }
  assert.deepEqual(bad, []);
});
