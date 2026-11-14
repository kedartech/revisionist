// Train 2 wiring (contract K2): the room reaches every unit's entry point, every unit has
// replaced its contract stub, and every unit stylesheet is linked. Red until the wave lands.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');

const UNITS = {
  T: ['js/views/realism-tray.js', 'css/p4-tray.css'],
  O: ['js/views/realism-orders.js', 'css/p4-orders.css'],
  M1: ['js/views/realism-answer.js', 'css/p5-answer.css'],
  M2: ['js/views/realism-ideas.js', 'css/p5-ideas.css'],
  M3: ['js/views/realism-forms.js', 'css/p5-forms.css'],
  C1: ['js/views/realism-chat.js', 'css/p5-chat.css'],
  C2: ['js/views/realism-contacts.js', 'css/p5-contacts.css'],
  H: ['js/views/realism-wake.js', 'css/p5-wake.css'],
  D: ['js/views/realism-dossier.js', 'css/p5-dossier.css'],
  W: ['js/views/realism-happened.js', 'css/p5-happened.css'],
  V: ['js/views/realism-overlay.js', 'css/p5-overlay.css'],
  TH2: [null, 'css/effects.css'],
  TH3: [null, 'css/p5-press.css'],
};

test('the room calls each unit with the data the server sends', () => {
  const room = read('js/views/realism-room.js');
  for (const call of [
    /trayView\(rv\.documents, open/,
    /needsAnswer\(rv\.agenda, \{ act \}\)/,
    /ideasPanel\(rv\.agenda, rv\.brief, \{ act, useDraft \}\)/,
    /standardForms\(rv\.desk, \{/,
    /commitPanel\(rv\.wake, \{ act \}\)/,
    /orderCards\(rv\.record, rv\.orders, /,
    /chatDock\(\{/,
    /contactsTab\(rv\.reach, \{/,
    /characterDossier\(\{ name: seatName, desk: rv\.desk, dossier: rv\.dossier/,
    /settingDossier\(\{ name: game\.name, setting: rv\.setting/,
    /happenedSheet\(\{/,
    /happenedDue\(page, shown, ui\.happenedSeen\)/,
    /wakeOverlay\(\{ message, lines: overlayLines\(rv\.setting, rv\.wake\.wake\), map: rv\.map, orders: rv\.record\?\.orders \}\)/,
    /seenStore\(storage\(\), game\.id\)/,
    /happenedStore\(storage\(\), game\.id\)/,
  ]) assert.match(room, call);
  for (const gone of ['PANELS', 'loadLand', 'mapView', 'board(', 'pendingOrders', 'conversations(', 'reachPanel', 'requestsPanel']) {
    assert.ok(!room.includes(gone), gone);
  }
});

test('the room wires the console strip, tiles and panel switches once, for every unit', () => {
  const room = read('js/views/realism-room.js');
  for (const call of [
    /import \{ statusStrip, summaryTiles \} from '\.\/realism-status\.js';/,
    /import \{ sideSwitch, tabBar \} from '\.\/realism-tabs\.js';/,
    /statusStrip\(rv, ui, \{ act \}\)/,
    /summaryTiles\(rv, pick\)/,
    /sideSwitch\(ui, pick\)/,
    /tabBar\(rv, ui, pick\)/,
    /'data-view': ui\.tab/,
    /'data-side': ui\.side/,
    /class: 'rl-col rl-papers', 'data-tab': 'papers'/,
    /class: 'rl-col rl-desk-col', 'data-tab': 'desk'/,
    /class: 'rl-col rl-side', 'data-tab': 'orders'/,
    /tab: 'desk', side: 'papers'/,
    /onState: \(next\) => \{ if \(!next\.open && ui\.tab === 'messages'\) ui\.tab = 'desk';/,
    /ui\.chat = \{ \.\.\.ui\.chat, open: false \};\n\s*ui\.tab = 'desk';/,
  ]) assert.match(room, call);
  for (const css of ['c-base', 'ui-kit', 'c-header', 'c-shell', 'c-map']) {
    assert.match(read('index.html'), new RegExp(`href="/css/${css}\\.css"`), css);
  }
});

test('the header opens the dossiers and carries the Screen effects toggle', () => {
  const frame = read('js/views/frame.js');
  assert.match(frame, /effectsControl\(effects\)/);
  assert.match(frame, /onSetting/);
  assert.match(frame, /onIdentity/);
  assert.match(frame, /Answers to \$\{identity\.principal\}/);
  const app = read('js/app.js');
  assert.match(app, /saveEffects\(storage, on\)/);
  assert.match(app, /applyEffects\(document\.documentElement, storage\)/);
});

test('every unit has replaced its contract stub', () => {
  for (const [unit, files] of Object.entries(UNITS)) {
    for (const f of files.filter(Boolean)) assert.doesNotMatch(read(f), /contract stub/, `${unit}: ${f}`);
  }
});

test('every unit stylesheet is linked from the page', () => {
  const page = read('index.html');
  for (const [, css] of Object.values(UNITS)) assert.match(page, new RegExp(`href="/${css.replace('.', '\\.')}"`), css);
});
