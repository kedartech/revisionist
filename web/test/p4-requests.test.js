// Unit tests for requests from named leaders in the in-tray. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { requestChoices, requestTitle, requests } from '../js/views/realism-requests.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const { agenda } = JSON.parse(readFileSync(join(WEB, 'test', 'fixtures', 'realism-seat.json'), 'utf8'));
const item = agenda.items[0];

test('the module imports under node with no document', () => {
  assert.equal(typeof document, 'undefined');
  assert.equal(typeof requests, 'function');
});

test('only a matter from a named leader is a request', () => {
  const crisis = { ...item, id: 'c1', kind: 'Crisis', issuer: null };
  assert.deepEqual(requests({ ...agenda, items: [item, crisis] }).map((r) => r.id), [item.id]);
  assert.deepEqual(requests(undefined), []);
  assert.deepEqual(requests({ style: 'free', items: [] }), []);
});

test('a free player still receives the request, with nothing to choose from', () => {
  const free = { ...agenda, style: 'free' };
  assert.deepEqual(requests(free).map((r) => r.id), [item.id]);
  assert.deepEqual(requestChoices(free.style, item), { kind: 'none', options: [] });
});

test('a beginner chooses among options; a guided player sees the plan to file', () => {
  assert.deepEqual(requestChoices('beginner', item), { kind: 'options', options: item.options });
  assert.deepEqual(requestChoices('guided', item), { kind: 'plan', options: item.plan });
  assert.deepEqual(requestChoices('beginner', { ...item, options: [] }), { kind: 'none', options: [] });
});

test('the request reads as a paper from the leader', () => {
  assert.equal(requestTitle(item), 'Keep the convoys moving to Iceland.');
  const long = { ...item, text: 'x'.repeat(200) };
  assert.ok(requestTitle(long).length <= 120);
  assert.ok(requestTitle(long).endsWith('…'));
});
