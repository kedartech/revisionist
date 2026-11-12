// Undo a pick: until the host begins, a player can give up their person and choose again.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { api } from '../js/api.js';
import { CONFIRM_NOTE, release, releaseControl } from '../js/views/realism-cast.js';
import { buttons, installDom, words } from './dom-fake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');

const control = () => {
  const doc = installDom();
  const calls = [];
  const el = releaseControl({ name: 'Winston Churchill', onRelease: () => calls.push(1) });
  doc.body.append(el);
  return { el, calls };
};

test('the confirm note says a pick can change until the host begins', () => {
  assert.equal(CONFIRM_NOTE, 'You can change your mind until the host begins the game.');
});

test('Choose someone else asks first and releases nothing on its own', () => {
  const { el, calls } = control();
  const [open] = buttons(el, 'Choose someone else');
  assert.ok(open);
  open.click();
  assert.deepEqual(calls, []);
  assert.match(words(el), /Give up Winston Churchill and choose again\?/);
  assert.equal(buttons(el, 'Choose someone else').length, 0);
});

test('Keep returns to the button without a release', () => {
  const { el, calls } = control();
  buttons(el, 'Choose someone else')[0].click();
  buttons(el, 'Keep Winston Churchill')[0].click();
  assert.deepEqual(calls, []);
  assert.equal(buttons(el, 'Choose someone else').length, 1);
  assert.doesNotMatch(words(el), /Give up/);
});

test('Yes releases once', () => {
  const { el, calls } = control();
  buttons(el, 'Choose someone else')[0].click();
  buttons(el, 'Yes, choose again')[0].click();
  assert.deepEqual(calls, [1]);
});

test('a release posts unpick, says the reply and redraws only when it landed', async () => {
  installDom();
  const was = api.newGame;
  const posted = [];
  let refreshed = 0;
  try {
    for (const [answer, redraws] of [[{ reply: 'You no longer play Winston Churchill. Choose again.', refused: false }, 1], [{ reply: 'You have not chosen anyone yet.', refused: true }, 0]]) {
      refreshed = 0;
      api.newGame = async (action, body) => { posted.push([action, body]); return answer; };
      const out = document.createElement('div');
      await release(out, async () => { refreshed += 1; });
      assert.equal(words(out), answer.reply);
      assert.equal(refreshed, redraws);
    }
  } finally {
    api.newGame = was;
  }
  assert.deepEqual(posted, [['unpick', {}], ['unpick', {}]]);
});

test('a release that throws says why and frees the pick lock', async () => {
  installDom();
  const was = api.newGame;
  try {
    api.newGame = async () => { throw new Error('This game is not choosing its people.'); };
    const out = document.createElement('div');
    await release(out, async () => {});
    assert.equal(words(out), 'This game is not choosing its people.');
    api.newGame = async () => ({ reply: 'ok', refused: true });
    await release(out, async () => {});
    assert.equal(words(out), 'ok');
  } finally {
    api.newGame = was;
  }
});

test('the seated screen offers the release, and only before the game begins', () => {
  const cast = read('js/views/realism-cast.js');
  assert.match(cast, /releaseControl\(\{ name: mine, onRelease: \(\) => release\(out, refresh\) \}\)/);
  assert.match(cast, /api\.newGame\('unpick', \{\}\)/);
});
