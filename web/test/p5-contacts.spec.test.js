// Spec for the Contacts tab, rewritten with contract KM for wave M unit M5: the unit makes it
// pass and never edits it. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';
import { contactDetail, contactRows, contactsTab } from '../js/views/realism-contacts.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const inner = fixture.desk.inner_circle.map((c) => c.person);
const NOTE = 'A message changes nothing in the world and files no order.';

test('the groups in order, rows with how to reach them and what the seat can do', () => {
  const out = contactRows(fixture.reach, inner);
  assert.deepEqual(out.map((g) => g.key), ['inner_circle', 'government', 'foreign', 'other']);
  assert.deepEqual(out.map((g) => g.heading), ['Inner circle', 'Government', 'Foreign', 'Other']);
  assert.deepEqual(out[0].rows[0], {
    name: 'Harry Hopkins', title: 'Special Assistant to the President', how: 'In person · Letter',
    can: { message: true, order: true },
  });
  assert.deepEqual(out[1].rows[0], {
    name: 'Harold R. Stark', title: 'Chief of Naval Operations', how: 'In person · Cable',
    can: { message: true, order: true },
  });
  assert.equal(out[3].rows[0].title, null);
});

test('anyone with a channel can be messaged; an order needs a channel to send it by', () => {
  const reach = {
    inner_circle: [], government: [], foreign: [],
    other: [
      { name: 'A. Reader', title: null, channels: ['Letter'], powers: [], channel_keys: [] },
      { name: 'B. Nobody', title: null, channels: [], powers: [], channel_keys: [] },
    ],
  };
  const [group] = contactRows(reach, []);
  assert.deepEqual(group.rows.map((r) => r.can), [{ message: true, order: false }, { message: false, order: false }]);
});

test('empty groups are dropped', () => {
  const out = contactRows({ inner_circle: [], government: [], foreign: fixture.reach.foreign, other: [] }, []);
  assert.deepEqual(out.map((g) => g.key), ['foreign']);
  assert.deepEqual(contactRows({ inner_circle: [], government: [], foreign: [], other: [] }, []), []);
});

test('the detail: office, powers as a sentence, how', () => {
  const d = contactDetail(fixture.reach.government[0]);
  assert.equal(d.office, 'Chief of Naval Operations');
  assert.equal(d.powers, 'Command the fleet at sea and advise the President on the Navy.');
  assert.equal(d.how, 'In person · Cable');
  assert.deepEqual(contactDetail(fixture.reach.other[0]), { office: null, powers: null, how: 'Letter' });
});

function tab(selected) {
  installDom();
  const calls = { message: [], order: [] };
  const node = contactsTab(fixture.reach, {
    inner, selected, onSelect: () => {},
    onMessage: (n) => calls.message.push(n), onOrder: (c) => calls.order.push(c.name),
  });
  return { node, calls };
}

test('the picker is headed New message', () => {
  const { node } = tab(null);
  assert.equal(words(node.querySelector('h2')), 'New message');
});

test('someone outside the inner circle: Message and an order both, and what a message is', () => {
  const { node, calls } = tab('Harold R. Stark');
  const by = (label) => node.querySelectorAll('button').find((b) => words(b) === label);
  assert.ok(by('Message') && by('Write them an order'));
  assert.match(words(node), /Chief of Naval Operations/);
  assert.ok(words(node).includes(NOTE));
  by('Message').click();
  by('Write them an order').click();
  assert.deepEqual(calls, { message: ['Harold R. Stark'], order: ['Harold R. Stark'] });
});

test('the inner circle: both actions, no note', () => {
  const { node } = tab('Harry Hopkins');
  const labels = node.querySelectorAll('button').map(words);
  assert.ok(labels.includes('Message') && labels.includes('Write them an order'));
  assert.ok(!words(node).includes(NOTE));
});
