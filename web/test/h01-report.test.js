// The report control and what became of the report (RPB), one test or more per rule: 1. the header's
// control offers a bug, an idea or something confusing in one dialog and files through the realism
// action `report`, not the seat family's `report` or `bug`, and its hint says who reads it; 2. "Your
// reports" lists the player's own with their status and the host's reply; 3. the host's game menu
// opens an inbox of the game's reports with a control to mark each seen or acted on.
// Keeps: report words and replies reach the page as text only. Mutant: the inbox drawn for a seat
// that is not the host.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, fire, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { header, reportDialog } = await import('../js/views/frame.js');
const { gameMenu } = await import('../js/views/realism-room.js');

const css = readFileSync(new URL('../css/c-header.css', import.meta.url), 'utf8');
const tick = () => new Promise((r) => setTimeout(r, 0));
const calls = [];
const REPORTS = [
  { id: 7, kind: 'idea', status: 'new', reply: '', words: 'A <b>bold</b> idea', wake: 2, filed: '2026-11-23T10:00:00+00:00' },
  { id: 6, kind: 'bug', status: 'acted', reply: 'Fixed in the next build.', words: 'The map froze', wake: 1, filed: '2026-11-22T10:00:00+00:00' },
];

function wire(over = {}) {
  calls.length = 0;
  api.realism = async (action, body) => {
    calls.push(['realism', action, body]);
    if (action === 'reports') return { reply: '', refused: false, inbox: Boolean(body.inbox), reports: REPORTS };
    return over[action] ?? { reply: 'Report 8 filed. Only the host and the makers read it.', refused: false, report: 8 };
  };
  api.seat = async (action, body) => { calls.push(['seat', action, body]); return { reply: 'x', refused: false }; };
  api.game = async (action, body) => { calls.push(['game', action, body]); return { reply: '', leaders: [] }; };
}

// rule 1

test('the dialog offers a bug, an idea and something confusing, and says who reads it', () => {
  installDom();
  wire();
  const dialog = reportDialog();
  const kinds = dialog.querySelectorAll('input[type="radio"]');
  assert.deepEqual(kinds.map((k) => k.value), ['bug', 'idea', 'confusing']);
  assert.match(words(dialog.querySelector('.hint')), /The host of this game reads what you write here\./);
});

test('filing sends the kind and the words through the realism action report, never the seat family', async () => {
  installDom();
  wire();
  const dialog = reportDialog();
  const kinds = dialog.querySelectorAll('input[type="radio"]');
  kinds[0].checked = false;
  kinds[1].checked = true;
  dialog.querySelector('textarea').value = 'Let me zoom the map';
  fire(dialog.querySelector('form'), 'submit');
  await tick();
  assert.deepEqual(calls, [['realism', 'report', { kind: 'idea', text: 'Let me zoom the map' }]]);
  assert.match(words(dialog), /Report 8 filed/);
  assert.equal(dialog.querySelector('textarea').value, '', 'the words are cleared once filed');
});

test('the header names the control as a report, and it opens the dialog', () => {
  installDom();
  wire();
  const head = header({ me: { account: { handle: 'josh' } }, game: { name: 'G' }, role: 'Campaign', refresh() {}, signOut() {} });
  const btn = head.querySelector('button.icon-btn');
  assert.equal(btn.getAttribute('aria-label'), 'Report a bug, an idea or something confusing');
  btn.click();
  assert.ok(head.querySelector('dialog.sheet').open);
});

// rule 2

test('"Your reports" lists the player\'s own reports with their status and the host\'s reply', async () => {
  installDom();
  wire();
  const dialog = reportDialog();
  const open = buttons(dialog, 'Your reports')[0];
  assert.ok(open, 'a Your reports control');
  open.click();
  await tick();
  assert.deepEqual(calls, [['realism', 'reports', {}]]);
  const rows = dialog.querySelectorAll('li');
  assert.equal(rows.length, 2);
  assert.match(words(rows[0]), /Idea/);
  assert.match(words(rows[0]), /New/);
  assert.match(words(rows[1]), /Acted on/);
  assert.match(words(rows[1]), /Fixed in the next build\./);
});

test('a report\'s words reach the page as text, never as markup', async () => {
  installDom();
  wire();
  const dialog = reportDialog();
  buttons(dialog, 'Your reports')[0].click();
  await tick();
  assert.equal(dialog.querySelector('b'), null);
  assert.ok(words(dialog).includes('A <b>bold</b> idea'));
});

// rule 3

const menuOf = (host) => {
  installDom();
  wire();
  const game = { id: `h01-${Math.random()}`, name: 'Autumn 1941', host };
  const [open, dialog] = gameMenu(game, { go() {}, refresh: async () => {} }, { idle: () => true });
  return { open, dialog };
};

test('the host\'s game menu opens an inbox of the game\'s reports and marks each seen or acted on', async () => {
  const { open, dialog } = menuOf(true);
  open.click();
  await tick();
  assert.ok(calls.some((c) => c[1] === 'reports' && c[2].inbox === true), 'the inbox is asked for');
  const rows = dialog.querySelectorAll('li.rl-report');
  assert.equal(rows.length, 2);
  buttons(rows[0], 'Seen')[0].click();
  await tick();
  assert.deepEqual(calls.find((c) => c[1] === 'report-mark'), ['realism', 'report-mark', { id: 7, status: 'seen' }]);
  buttons(rows[1], 'Acted on')[0].click();
  await tick();
  assert.deepEqual(calls.filter((c) => c[1] === 'report-mark').at(-1), ['realism', 'report-mark', { id: 6, status: 'acted', reply: 'Fixed in the next build.' }]);
});

test('an inbox row draws no office, even when a reply carries one', async () => {
  const { open, dialog } = menuOf(true);
  REPORTS[0].office = 'Chief of Staff';
  try {
    open.click();
    await tick();
    assert.ok(!/Chief of Staff/.test(words(dialog)));
  } finally {
    delete REPORTS[0].office;
  }
});

test('a seat that is not the host gets no inbox and asks for none', async () => {
  const { open, dialog } = menuOf(false);
  open.click();
  await tick();
  assert.equal(calls.filter((c) => c[1] === 'reports').length, 0);
  assert.equal(dialog.querySelectorAll('li.rl-report').length, 0);
  assert.ok(!/Reports from players/.test(words(dialog)));
});

// colour

test('the report styles take their colours from tokens only', () => {
  const bare = css.replace(/\/\*[\s\S]*?\*\//g, '');
  assert.equal(/#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(/.test(bare), false);
  assert.match(bare, /\.rl-report-status\[data-status="new"\][^}]*var\(--warn\)/);
});
