// Spec for Train 2 unit C2, written with contract K2: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { contactDetail, contactRows } from '../js/views/realism-contacts.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const inner = fixture.desk.inner_circle.map((c) => c.person);

test('the groups in order, rows with how to reach them and what the seat can do', () => {
  const out = contactRows(fixture.reach, inner);
  assert.deepEqual(out.map((g) => g.key), ['inner_circle', 'government', 'foreign', 'other']);
  assert.deepEqual(out.map((g) => g.heading), ['Inner circle', 'Government', 'Foreign', 'Other']);
  assert.deepEqual(out[0].rows[0], { name: 'Harold R. Stark', title: 'Chief of Naval Operations', how: 'In person · Cable', can: 'order' });
  assert.equal(out[1].rows[0].can, 'message');
  assert.equal(out[2].rows[0].can, 'message');
  assert.equal(out[3].rows[0].title, null);
});

test('empty groups are dropped', () => {
  const out = contactRows({ inner_circle: [], government: [], foreign: fixture.reach.foreign, other: [] }, []);
  assert.deepEqual(out.map((g) => g.key), ['foreign']);
  assert.deepEqual(contactRows({ inner_circle: [], government: [], foreign: [], other: [] }, []), []);
});

test('the detail: office, powers as a sentence, how', () => {
  const stark = fixture.reach.inner_circle[0];
  const d = contactDetail(stark);
  assert.equal(d.office, 'Chief of Naval Operations');
  assert.equal(d.powers, 'Command the fleet at sea and advise the President on the Navy.');
  assert.equal(d.how, 'In person · Cable');
  assert.deepEqual(contactDetail(fixture.reach.other[0]), { office: null, powers: null, how: 'Letter' });
});

test('the tab words', () => {
  const src = read('js/views/realism-contacts.js');
  for (const words of ['Message', 'Write them an order']) assert.ok(src.includes(`'${words}'`), words);
  assert.match(src, /onOrder\??\.?\(/);
});
