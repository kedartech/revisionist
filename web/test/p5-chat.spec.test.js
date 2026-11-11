// Spec for Train 2 unit C1, written with contract K2: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { SEEN_PREFIX, seenStore, unread } from '../js/views/realism-chat.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const memory = () => {
  const data = new Map();
  return { data, getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)) };
};

test('unread counts lines newer than seen and names the threads that have them', () => {
  assert.deepEqual(unread({ aide: 3, 'Sam Rayburn': 1, 'Harry Hopkins': 0 }, { aide: 1 }), { total: 3, fresh: ['aide', 'Sam Rayburn'] });
  assert.deepEqual(unread({ aide: 2 }, { aide: 2 }), { total: 0, fresh: [] });
  assert.deepEqual(unread({ aide: 1 }, { aide: 5 }), { total: 0, fresh: [] });
  assert.deepEqual(unread({}, {}), { total: 0, fresh: [] });
});

test('seen marks are kept per campaign and read back', () => {
  const s = memory();
  const store = seenStore(s, 'c1');
  assert.deepEqual(store.read(), {});
  store.write({ aide: 2 });
  assert.deepEqual(store.read(), { aide: 2 });
  assert.ok(s.data.has(`${SEEN_PREFIX}c1`));
  assert.equal(SEEN_PREFIX, 'rv.chat.seen.');
  assert.deepEqual(seenStore(s, 'c2').read(), {});
});

test('a broken value reads as nothing seen, and no storage does nothing', () => {
  const s = memory();
  s.setItem(`${SEEN_PREFIX}c1`, '{not json');
  assert.deepEqual(seenStore(s, 'c1').read(), {});
  s.setItem(`${SEEN_PREFIX}c1`, '[1,2]');
  assert.deepEqual(seenStore(s, 'c1').read(), {});
  const none = seenStore(undefined, 'c1');
  assert.deepEqual(none.read(), {});
  assert.doesNotThrow(() => none.write({ aide: 1 }));
  const blocked = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
  assert.deepEqual(seenStore(blocked, 'c1').read(), {});
  assert.doesNotThrow(() => seenStore(blocked, 'c1').write({}));
});

test('the dock words and its parts', () => {
  const src = read('js/views/realism-chat.js');
  for (const words of ['Messages', 'Your aide', 'Chats', 'Contacts']) assert.ok(src.includes(`'${words}'`), words);
  assert.match(src, /import \{[^}]*\bhelpThread\b[^}]*\} from '\.\/realism\.js'/);
  assert.match(src, /import \{[^}]*\bcounselThread\b[^}]*\} from '\.\/realism\.js'/);
  assert.match(src, /'Escape'/);
  assert.match(read('css/p5-chat.css'), /@media[^{]*max-width:\s*480px/);
});
