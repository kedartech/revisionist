// Spec for Train 2 unit H, written with contract K2: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { DONE_HINT, RUN_NOW, commitCount, commitLabel } from '../js/views/realism-wake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

test('the commit button says done for today, then who is still out', () => {
  assert.equal(commitLabel({ committed: 0, humans: 2, you_committed: false }), 'Done for today');
  assert.equal(commitLabel({ committed: 1, humans: 3, you_committed: true }), 'Done, waiting on 2 of 3');
  assert.equal(commitLabel({ committed: 2, humans: 2, you_committed: true }), 'Done');
  assert.equal(commitLabel({ committed: 1, humans: 1, you_committed: true }), 'Done');
});

test('the count says players done', () => {
  assert.equal(commitCount({ committed: 1, humans: 2 }), '1 of 2 players done');
  assert.equal(commitCount({ committed: 0, humans: 1 }), '0 of 1 player done');
});

test('the hint and the host confirm', () => {
  assert.equal(DONE_HINT, 'The day runs when everyone is done.');
  assert.deepEqual({ ...RUN_NOW }, {
    button: 'Run the day now',
    heading: 'Run the day now?',
    text: 'It runs with every order as it stands. Your aide plays anyone who is not done. This can take a minute.',
    cancel: 'Cancel',
    confirm: 'Run it',
  });
});

test('the views use the words, and the old ones are gone', () => {
  const src = read('js/views/realism-wake.js');
  const views = src.slice(src.indexOf('function commitControl'));
  assert.match(views, /commitLabel\(wake\)/);
  assert.match(views, /DONE_HINT/);
  assert.match(views, /RUN_NOW\.heading/);
  assert.match(views, /act\(RUNNING, 'close'/);
  assert.match(src, /`Wake \$\{wake\.wake\}`/);
  for (const old of ['Close the wake now', 'Close this wake?', 'Commit my orders', 'players committed']) assert.ok(!src.includes(old), old);
});
