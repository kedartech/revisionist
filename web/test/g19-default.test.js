// The map-first room is the default for a territory game, with today's room reachable from the game
// menu as "Classic layout"; a game without territories opens today's room and offers no switch.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { roomLayout, setRoomLayout } = await import('../js/views/realism-sheets.js');
const { forgetShapes } = await import('../js/views/realism-theatre.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const settle = () => new Promise((r) => setTimeout(r, 0));

/** The seat's view: on the toy territory board, or on the point map of a game without territories. */
function seat(territory) {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(territory ? fixture.territory_map : fixture.map);
  rv.battles = [];
  rv.documents = structuredClone(fixture.listing);
  rv.wake_tick = 1;
  return rv;
}

/** The room for a fresh game, drawn as the page does, with nothing chosen from the menu. */
async function room(territory, id = `g-${Math.random()}`) {
  const doc = installDom();
  forgetShapes();
  api.realism = async (action) => (action === 'map' ? { reply: '', refused: false, file: fixture.territory_map.file, map: SHAPES } : {});
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const game = { id, name: 'Salt Strait', ruleset: 'realism', phase: 'play', host: true, view: { realism: seat(territory), seat: { name: 'Franklin D. Roosevelt' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  await settle();
  await settle();
  return root;
}

const layoutButtons = (root) => {
  root.querySelector('.rl-menu-btn').click();
  return root.querySelector('dialog.rl-menu .rl-layout');
};

test('a territory game opens the map-first room, with no choice made', async () => {
  const root = await room(true);
  assert.equal(roomLayout(), 'map');
  assert.ok(root.querySelector('.rl-mapfirst'), 'the map-first screen');
  assert.equal(root.querySelector('.rl-viewswitch'), null, 'no Board and Desk switch');
});

test('a game without territories opens today\'s room and offers no layout switch', async () => {
  const root = await room(false);
  assert.equal(roomLayout(), 'room');
  assert.equal(root.querySelector('.rl-mapfirst'), null);
  assert.ok(root.querySelector('.rl-viewswitch'), 'the Board and Desk switch');
  assert.equal(layoutButtons(root), null, 'no layout choice in the menu');
});

test('a point game opened after a territory game\'s choice of the map is still today\'s room', async () => {
  setRoomLayout('map');
  const root = await room(false);
  assert.equal(root.querySelector('.rl-mapfirst'), null);
});

test('the menu of a territory game offers Map first, pressed, and Classic layout, which brings back today\'s room', async () => {
  const root = await room(true);
  const group = layoutButtons(root);
  assert.deepEqual(group.querySelectorAll('button').map(words), ['Map first', 'Classic layout']);
  assert.deepEqual(group.querySelectorAll('button[aria-pressed="true"]').map(words), ['Map first']);
  buttons(group, 'Classic layout')[0].click();
  assert.equal(roomLayout(), 'room');
  assert.equal(root.querySelector('.rl-mapfirst'), null);
  assert.ok(root.querySelector('.rl-viewswitch'), 'today\'s room is back');
  buttons(layoutButtons(root), 'Map first')[0].click();
  assert.ok(root.querySelector('.rl-mapfirst'));
});

test('the classic choice holds for the page: another territory game opens in it', async () => {
  setRoomLayout('room');
  const root = await room(true);
  assert.equal(root.querySelector('.rl-mapfirst'), null);
});
