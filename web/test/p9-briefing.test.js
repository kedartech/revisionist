// The aide's briefing (messenger plan, D4): at the head of What happened, the aide says how the
// wake went, built in code from the seat's own view (no model call). Lines: orders settled this
// wake that went slowly, loosely or in part (in the record's own sentences), figures that moved,
// and mandates issued since the wake before. `aideBriefing` draws them; with nothing to say it
// draws nothing.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';
import { aideBriefing, briefingLines, slowOrders } from '../js/views/realism-briefing.js';
import { changedFigures, happenedSheet } from '../js/views/realism-happened.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const view = { record: fixture.record, situation: fixture.situation, agenda: fixture.agenda };

const SLOW = [
  '“Give a naval order: Escort the HX convoys to the meeting point” has been carried out loosely.',
  '“Give a naval order: Base a destroyer squadron at Reykjavik” has been carried out late.',
  '“Allocate Lend-Lease aid: Soviet Union, 30” has been carried out in part.',
];
const noFigures = { figures: [] };
const mandate = (issued, extra = {}) => ({
  ...fixture.agenda.items[0], id: `m-${issued}`, kind: 'Crisis', issuer: 'Harold R. Stark',
  text: 'A U-boat has fired on a destroyer.', issued, ...extra,
});

test('orders settled this wake that went slowly, loosely or in part, in the record\'s sentences', () => {
  const lines = briefingLines({ record: fixture.record, situation: noFigures });
  assert.deepEqual(lines, SLOW);
});

test('an order carried out in full, refused, lapsed or agreed is not the aide\'s to report', () => {
  const lines = briefingLines({ record: fixture.record, situation: noFigures }).join(' ');
  for (const asked of ['Patrol the Denmark Strait', 'Pan American Highway', 'report on Pacific bases', 'hold the vote']) {
    assert.ok(!lines.includes(asked), asked);
  }
});

test('an order that went slowly in an earlier wake is not told again', () => {
  const late = fixture.record.orders.find((o) => o.status === 'carried out late');
  const earlier = { ...fixture.record, wake: { ...fixture.record.wake, settled: fixture.record.wake.settled.filter((id) => id !== late.id) } };
  const lines = briefingLines({ record: earlier, situation: noFigures });
  assert.deepEqual(lines, [SLOW[0], SLOW[2]]);
  assert.ok(!slowOrders(earlier).some((o) => o.id === late.id), 'slowOrders holds this wake\'s orders only');
});

test('the figures that moved come after the orders', () => {
  const lines = briefingLines(view);
  const figures = changedFigures(fixture.situation);
  assert.ok(figures.length > 0, 'the fixture has a moved figure');
  assert.deepEqual(lines.slice(0, 3), SLOW);
  assert.deepEqual(lines.slice(3, 3 + figures.length), figures);
});

test('mandates issued since the wake before are new; older ones are not', () => {
  // wake 3 opened 20 October 1941, 6 days after the wake before (14 October)
  const items = [mandate('18 October 1941'), mandate('20 October 1941', { kind: 'Opportunity', issuer: 'Cordell Hull', text: 'Tokyo asks for talks.' }),
    mandate('14 October 1941'), mandate('3 October 1941'), mandate('sometime soon')];
  const lines = briefingLines({ record: fixture.record, situation: noFigures, agenda: { items } });
  assert.deepEqual(lines.slice(3), [
    'New crisis from Harold R. Stark: A U-boat has fired on a destroyer.',
    'New opportunity from Cordell Hull: Tokyo asks for talks.',
  ]);
  // the fixture's own mandate was issued 12 October, before the wake before
  assert.deepEqual(briefingLines({ record: fixture.record, situation: noFigures, agenda: fixture.agenda }), SLOW);
});

test('a mandate with no issuer still reads', () => {
  const lines = briefingLines({ record: fixture.record, situation: noFigures, agenda: { items: [mandate('19 October 1941', { issuer: null })] } });
  assert.equal(lines.at(-1), 'New crisis: A U-boat has fired on a destroyer.');
});

test('a view with missing parts gives no lines rather than failing', () => {
  for (const v of [undefined, null, {}, { record: null }, { record: { orders: [] } }, { record: { wake: null } },
    { record: { ...fixture.record, wake: { number: 3 } } }, { agenda: { items: [mandate('19 October 1941')] } }]) {
    assert.deepEqual(briefingLines(v), [], JSON.stringify(v));
  }
});

test('nothing outside the seat\'s own record, figures and mandates reaches the briefing', () => {
  const rich = { ...view, reveal: fixture.reveal, people: fixture.people, map: fixture.map, threats: fixture.threats, counsel: fixture.counsel };
  assert.deepEqual(briefingLines(rich), briefingLines(view));
});

test('aideBriefing: the aide\'s name, the lead and one item per line, as text', () => {
  installDom();
  const node = aideBriefing({ aide: 'Harry Hopkins', lead: 'Mr. President, the week in brief.', lines: ['<b>one</b>', 'two'] });
  assert.ok(node.classList.contains('rl-brief'));
  assert.equal(node.getAttribute('aria-label'), 'Harry Hopkins: briefing');
  assert.equal(words(node.querySelector('.rl-brief-who')), 'Harry Hopkins');
  assert.equal(words(node.querySelector('.rl-brief-lead')), 'Mr. President, the week in brief.');
  assert.deepEqual(node.querySelectorAll('.rl-brief-lines li').map(words), ['<b>one</b>', 'two']);
  assert.equal(node.querySelector('b'), null, 'model text is never parsed');
  assert.equal(node.querySelector('img'), null, 'no portrait, no image');
});

test('aideBriefing: a portrait when one is given, beside the name', () => {
  installDom();
  const node = aideBriefing({ aide: 'Harry Hopkins', portrait: '/assets/portraits/hopkins.jpg', lines: ['one'] });
  const img = node.querySelector('img.rl-brief-portrait');
  assert.equal(img.getAttribute('src'), '/assets/portraits/hopkins.jpg');
  assert.equal(img.getAttribute('alt'), '');
});

test('aideBriefing: missing keys fall back to "Your aide" and no lead', () => {
  installDom();
  const node = aideBriefing({ lines: ['one'] });
  assert.equal(words(node.querySelector('.rl-brief-who')), 'Your aide');
  assert.equal(node.getAttribute('aria-label'), 'Your aide: briefing');
  assert.equal(node.querySelector('.rl-brief-lead'), null);
  assert.equal(aideBriefing({ lead: 'Only a lead.' }).querySelector('.rl-brief-lines'), null);
});

test('aideBriefing: nothing to say draws nothing', () => {
  installDom();
  assert.equal(aideBriefing({ aide: 'Harry Hopkins', lines: [] }), null);
  assert.equal(aideBriefing({}), null);
  assert.equal(aideBriefing(), null);
});

test('What happened opens with the briefing, and the figures are told once', () => {
  installDom();
  const sheet = happenedSheet({ ...view, date: '20 October 1941', onClose: () => {} });
  const kids = sheet.children;
  assert.equal(kids[0].tagName, 'H2');
  assert.ok(kids[1].classList.contains('rl-brief'), 'the briefing sits under the title');
  assert.deepEqual(kids[1].querySelectorAll('li').map(words).slice(0, 3), SLOW);
  const text = words(sheet);
  for (const f of [...changedFigures(fixture.situation), ...SLOW]) assert.equal(text.split(f).length - 1, 1, f);
  // the rest of the record's lines still follow, under the briefing
  assert.ok(text.includes('“Give a naval order: Patrol the Denmark Strait” has been carried out.'));
  assert.equal(sheet.querySelectorAll('.rl-hap-lines li').length, fixture.record.orders.length - SLOW.length);
});

test('What happened with nothing for the aide to say has no briefing', () => {
  installDom();
  const quiet = { ...fixture.record, wake: { ...fixture.record.wake, settled: [] } };
  const sheet = happenedSheet({ record: quiet, situation: noFigures, agenda: fixture.agenda, date: '20 October 1941', onClose: () => {} });
  assert.equal(sheet.querySelector('.rl-brief'), null);
});

test('the room passes the agenda to the sheet, and the briefing stylesheet is linked', () => {
  assert.match(read('js/views/realism-room.js'), /happenedSheet\(\{[^)]*agenda: rv\.agenda/);
  assert.match(read('index.html'), /<link rel="stylesheet" href="\/css\/p5-briefing\.css">/);
  const css = read('css/p5-briefing.css');
  for (const sel of ['.rl-brief', '.rl-brief-who', '.rl-brief-lead', '.rl-brief-lines', '.rl-brief-portrait']) assert.ok(css.includes(sel), sel);
});
