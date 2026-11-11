// In-Tray follow-up wiring: the room reaches each unit's entry point, and the stubs are gone.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');

test('the room draws the tray and the acknowledgement threads through the unit modules', () => {
  const room = read('js/views/realism-room.js');
  assert.match(room, /trayView\(rv\.documents/);
  assert.match(room, /ackThread\(rv\.documents, person, open\)/);
});

test('every unit has replaced its contract stub', () => {
  for (const f of ['js/views/realism-tray.js', 'js/views/realism-acks.js', 'js/views/realism-orders.js']) {
    assert.doesNotMatch(read(f), /contract stub/, f);
  }
});

test('each unit stylesheet is linked from the page', () => {
  const page = read('index.html');
  for (const css of ['p4-tray.css', 'p4-acks.css', 'p4-orders.css']) assert.match(page, new RegExp(css));
});
