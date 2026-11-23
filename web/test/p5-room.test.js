// The room hub (contract K2): the parts of realism-room.js that run without a page.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { beginSend, endSend, happenedDue, orderContacts, uiFor, whileSending } from '../js/views/realism-room.js';
import { happenedStore } from '../js/views/realism-happened.js';
import { wakeOverlay } from '../js/views/realism-overlay.js';
import { forgetShapes } from '../js/views/realism-theatre.js';
import { installDom } from './dom-fake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');

const inner = [{ person: 'Harry Hopkins', channel: 'in_person', channels: ['in_person', 'letter'] }];

test('a contact from the messenger joins the order form with its channels', () => {
  const stark = { name: 'Harold R. Stark', title: 'Chief of Naval Operations', channel_keys: ['in_person', 'cable'] };
  assert.deepEqual(orderContacts(inner, stark), [...inner,
    { person: 'Harold R. Stark', title: 'Chief of Naval Operations', channel: 'in_person', channels: ['in_person', 'cable'] }]);
  assert.equal(orderContacts(inner, null), inner);
  assert.equal(orderContacts(inner, { name: 'Harry Hopkins', channel_keys: ['letter'] }), inner);
});

test('a contact with no channel is left off the order form', () => {
  assert.equal(orderContacts(inner, { name: 'Burton K. Wheeler', title: null, channel_keys: [] }), inner);
  assert.equal(orderContacts(inner, { name: 'Burton K. Wheeler', title: null }), inner);
});

test('the room keeps its picks for one game and starts clean in another', () => {
  const ui = uiFor('g1');
  ui.draft = { to: 'Harry Hopkins', channel: 'letter', text: 'Come at once' };
  ui.orderTo = { name: 'Harold R. Stark', channel_keys: ['cable'] };
  assert.equal(uiFor('g1').draft.text, 'Come at once');
  const other = uiFor('g2');
  assert.equal(other.draft, null);
  assert.equal(other.orderTo, null);
  assert.equal(other.contact, null);
  assert.deepEqual(other.chat, { open: false, tab: 'chats', thread: null });
  assert.equal(other.pending, null);
  assert.deepEqual(other.drafts, {});
});

test('closing the What happened sheet by any means counts as seen', () => {
  const room = read('js/views/realism-room.js');
  assert.match(room, /happened\?\.addEventListener\('close', \(\) => \{[^}]*shown\.write\(page\.number\)/);
  assert.match(room, /happened\?\.addEventListener\('close', \(\) => \{[^}]*ui\.happenedSeen = page\.number/);
});

test('the page reads browser storage only through browserStorage', () => {
  // the shell read storage only for the screen effects setting, gone since 14 Nov
  for (const f of ['js/app.js', 'js/views/realism-room.js']) assert.doesNotMatch(read(f), /window\.localStorage/, f);
  assert.match(read('js/views/realism-room.js'), /browserStorage\(window\)/);
});

test('What happened shows once per wake even where storage is blocked', () => {
  const blocked = happenedStore({ getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } }, 'c1');
  assert.equal(happenedDue({ number: 3 }, blocked, null), true);
  assert.equal(happenedDue({ number: 3 }, blocked, 3), false);
  assert.equal(happenedDue({ number: 4 }, blocked, 3), true);
  assert.equal(happenedDue(null, blocked, null), false);
  assert.equal(happenedDue({ number: 0 }, blocked, null), false);
});

test('the desk foot repeats Done for today without a second live count', () => {
  const src = read('js/views/realism-wake.js');
  const foot = src.slice(src.indexOf('export function commitPanel'), src.indexOf('/** The order the aide read'));
  assert.doesNotMatch(foot, /aria-live/);
});

test('a message send holds only its own thread, and one at a time', () => {
  const ui = { busy: null, pending: null, drafts: { 'Harry Hopkins': 'old' }, error: 'stale' };
  assert.equal(beginSend(ui, 'Harry Hopkins', '   '), false, 'blank text is not sent');
  assert.equal(ui.pending, null);
  assert.equal(beginSend(ui, 'Harry Hopkins', ' Will Moscow hold? '), true);
  assert.deepEqual(ui.pending, { thread: 'Harry Hopkins', text: 'Will Moscow hold?' });
  assert.equal(ui.error, null);
  assert.equal(beginSend(ui, 'aide', 'And the bill?'), false, 'a second send waits');
  assert.equal(beginSend({ busy: 'Running the day…', pending: null, drafts: {} }, 'aide', 'Hello'), false, 'not while the room is busy');
});

test('a sent message clears its draft; a failed or refused one keeps the words and says why', () => {
  const ui = { busy: null, pending: null, drafts: { 'Harry Hopkins': 'old', aide: 'keep' }, error: null };
  beginSend(ui, 'Harry Hopkins', 'Will Moscow hold?');
  endSend(ui, { refused: false, reply: 'Harry Hopkins has answered.' });
  assert.equal(ui.pending, null);
  assert.deepEqual(ui.drafts, { aide: 'keep' });
  assert.equal(ui.error, null);

  beginSend(ui, 'Fumimaro Konoe', 'Will Tokyo talk?');
  endSend(ui, { refused: true, reply: 'Fumimaro Konoe did not answer.' });
  assert.equal(ui.pending, null);
  assert.equal(ui.drafts['Fumimaro Konoe'], 'Will Tokyo talk?');
  assert.equal(ui.error, 'Fumimaro Konoe did not answer.');

  beginSend(ui, 'aide', 'How do I send a bill?');
  endSend(ui, { error: 'The model cannot be reached just now.' });
  assert.equal(ui.drafts.aide, 'How do I send a bill?');
  assert.equal(ui.error, 'The model cannot be reached just now.');
});

test('the room holds a wake and every other call while a message is out', () => {
  const room = read('js/views/realism-room.js');
  assert.match(room, /if \(ui\.busy\) return;\n    if \(ui\.pending\) \{[^}]*ui\.error = whileSending\(ui\);\n      showStatus\(\);\n      return;/);
  assert.match(room, /work\.idle = \(\) => !ui\.busy && !ui\.pending;/);
  assert.match(room, /beginSend\(ui, thread, text\)/);
  assert.match(room, /endSend\(ui, /);
});

test('while a message is out, any other action says why it waits instead of doing nothing', () => {
  assert.equal(whileSending({ pending: null }), null);
  assert.equal(whileSending({ pending: { thread: 'Harold R. Stark', text: 'Iceland?' } }),
    'Harold R. Stark is answering your message. Try again when the answer is in.');
  assert.equal(whileSending({ pending: { thread: 'aide', text: 'How?' } }),
    'Your aide is answering your message. Try again when the answer is in.');
});

// --- the wake overlay on a territory game draws the game's own map ---------------------------

const seat = JSON.parse(read('test/fixtures/realism-seat.json'));
const TOY = JSON.parse(read('test/fixtures/toy.map.json'));
const COAST = { rings: [[[0, 0], [10, 0], [10, 10], [0, 10]]] };

/** A fake `fetch` answering the shapes and the coarse coastline, recording every address asked. */
function serve(shapes = TOY, file = seat.territory_map.file) {
  const asked = [];
  const was = globalThis.fetch;
  globalThis.fetch = async (url) => {
    asked.push(url);
    const body = url === '/api/realism/map' ? { reply: '', refused: false, file, map: shapes } : COAST;
    return { ok: true, status: 200, json: async () => structuredClone(body) };
  };
  return { asked, done: () => { globalThis.fetch = was; } };
}
const settle = async () => { for (let i = 0; i < 4; i += 1) await new Promise((ok) => setTimeout(ok, 0)); };
const wake = (map) => wakeOverlay({ message: 'Running', lines: [], map, orders: [] });
const placed = (el) => { document.body.append(el); return el; };

test('a territory game draws the wake overlay from its own map object, and never asks for the coarse coastline', async () => {
  installDom();
  forgetShapes();
  const net = serve();
  try {
    const ovl = placed(wake(structuredClone(seat.territory_map)));
    await settle();
    assert.ok(ovl.querySelector('figure.rl-ovl-map svg.rl-tm-svg'), 'the territory map is drawn in the overlay');
    assert.ok(ovl.querySelector('path.rl-area'), 'with the game\'s own areas');
    assert.deepEqual(net.asked, ['/api/realism/map'], 'only the map object is fetched');
    ovl.remove();
  } finally { net.done(); }
});

test('the game\'s map object is fetched by its hash once and kept for the next overlay', async () => {
  installDom();
  forgetShapes();
  const net = serve();
  try {
    placed(wake(structuredClone(seat.territory_map)));
    placed(wake(structuredClone(seat.territory_map)));
    await settle();
    const later = placed(wake(structuredClone(seat.territory_map)));
    await settle();
    assert.equal(net.asked.filter((u) => u === '/api/realism/map').length, 1);
    assert.ok(later.querySelector('svg.rl-tm-svg'), 'a later overlay draws at once from the kept shapes');
  } finally { net.done(); }
});

test('a game with no territories draws the coarse coastline under its own forces as before', async () => {
  installDom();
  forgetShapes();
  const net = serve();
  try {
    const ovl = placed(wake(structuredClone(seat.map)));
    await settle();
    assert.deepEqual(net.asked, ['/assets/land-110m.json']);
    assert.ok(ovl.querySelector('svg.rl-map-svg'));
    assert.equal(ovl.querySelector('svg.rl-tm-svg'), null);
  } finally { net.done(); }
});

test('land not in play is still drawn from the coarse coastline for a map with a backdrop', async () => {
  installDom();
  forgetShapes();
  const shapes = { ...structuredClone(TOY), coords: 'lonlat', backdrop: [[4, 5, 8, 7, 4]] };
  const net = serve(shapes);
  try {
    const ovl = placed(wake({ ...structuredClone(seat.territory_map), coords: 'lonlat' }));
    await settle();
    assert.ok(ovl.querySelector('path.rl-tm-notland'), 'the coastline is drawn under the areas');
  } finally { net.done(); }
});
