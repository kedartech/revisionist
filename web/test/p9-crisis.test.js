// A crisis on the desk is an alert that says what caused it and what failing costs; every
// dated agenda item carries a deadline chip toned by the days left.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';

installDom();
const { needsAnswer } = await import('../js/views/realism-answer.js');
const { DUE_DANGER_DAYS, DUE_WARN_DAYS, FAIL_SENTENCES, daysLeft, deadlineChip } = await import('../js/views/realism-ideas.js');

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

const TODAY = '1941-10-20';
const item = (id, kind, extra = {}) => ({ id, kind, issuer: null, text: `Text ${id}`, issued: '12 October 1941',
  deadline: '26 October 1941', cause: null, options: [], plan: [], ...extra });
const desk = (items, today = TODAY) => needsAnswer({ style: 'free', items, initiative: [] }, { act: () => {}, today });
const rows = (section) => section.querySelectorAll('.rl-ans-item');

test('a crisis is drawn as an alert with its text and the cause behind it', () => {
  const s = desk([item('c', 'Crisis', { cause: 'USS Greer and U-652 exchange fire south of Iceland' })]);
  const alert = rows(s)[0].querySelector('.alert');
  assert.ok(alert, 'the crisis sits in an alert');
  assert.equal(words(alert.querySelector('.alert-title')), 'Crisis');
  assert.match(words(alert), /Text c/);
  const cause = alert.querySelector('.rl-crisis-cause');
  assert.ok(cause, 'a cause line');
  assert.equal(words(cause), 'Behind it: USS Greer and U-652 exchange fire south of Iceland');
});

test('a crisis with no cause shows no cause line and no filler', () => {
  const alert = rows(desk([item('c', 'Crisis')]))[0].querySelector('.alert');
  assert.ok(alert, 'still an alert');
  assert.equal(alert.querySelector('.rl-crisis-cause'), null);
  assert.doesNotMatch(words(alert), /Behind it|null|undefined|unknown/i);
});

test('each kind carries its own sentence on what failing costs', () => {
  assert.deepEqual(Object.keys(FAIL_SENTENCES).sort(), ['blowback', 'crisis', 'opportunity', 'order']);
  assert.match(FAIL_SENTENCES.order, /fails/);
  assert.match(FAIL_SENTENCES.crisis, /fails/);
  assert.match(FAIL_SENTENCES.opportunity, /costs nothing/);
  assert.match(FAIL_SENTENCES.blowback, /lapses/);
  assert.equal(new Set(Object.values(FAIL_SENTENCES)).size, 4, 'four different sentences');
  const s = desk(['Order', 'Crisis', 'Blowback', 'Opportunity'].map((k) => item(k, k)));
  for (const row of rows(s)) {
    const kind = words(row.querySelector('.alert-title, h3')).toLowerCase();
    const line = row.querySelector('.rl-crisis-fail');
    assert.ok(line, `${kind}: a failure line`);
    assert.equal(words(line), FAIL_SENTENCES[kind], kind);
  }
});

test('only a crisis is an alert: an opportunity, an order and blowback never are', () => {
  const s = desk([item('o', 'Opportunity', { cause: 'A headline' }), item('r', 'Order'), item('b', 'Blowback'), item('c', 'Crisis')]);
  assert.equal(s.querySelectorAll('.alert').length, 1);
  const [opp] = rows(s);
  assert.equal(opp.querySelector('.alert'), null, 'the opportunity is no alert');
  assert.equal(words(opp.querySelector('h3')), 'Opportunity');
});

test('days left from the world date to a deadline in words or as an ISO day', () => {
  assert.equal(daysLeft('26 October 1941', '1941-10-20'), 6);
  assert.equal(daysLeft('1941-11-01', '1941-10-20'), 12);
  assert.equal(daysLeft('20 October 1941', '1941-10-20'), 0);
  assert.equal(daysLeft('3 January 1942', '1941-12-31'), 3);
  assert.equal(daysLeft('', TODAY), null);
  assert.equal(daysLeft('soon', TODAY), null);
  assert.equal(daysLeft('26 October 1941', undefined), null);
});

test('the chip tone turns at the named thresholds', () => {
  assert.equal(DUE_DANGER_DAYS, 7);
  assert.equal(DUE_WARN_DAYS, 21);
  const tone = (days) => {
    const due = new Date(Date.UTC(1941, 9, 20 + days)).toISOString().slice(0, 10);
    const c = deadlineChip(due, TODAY);
    return c.className.split(' ').find((k) => k.startsWith('tone-'));
  };
  assert.equal(tone(0), 'tone-danger');
  assert.equal(tone(DUE_DANGER_DAYS), 'tone-danger');
  assert.equal(tone(DUE_DANGER_DAYS + 1), 'tone-warn');
  assert.equal(tone(DUE_WARN_DAYS), 'tone-warn');
  assert.equal(tone(DUE_WARN_DAYS + 1), 'tone-info');
});

test('the chip says the days left in words', () => {
  assert.equal(words(deadlineChip('20 October 1941', TODAY)), 'Due today');
  assert.equal(words(deadlineChip('21 October 1941', TODAY)), '1 day left');
  assert.equal(words(deadlineChip('26 October 1941', TODAY)), '6 days left');
  assert.ok(deadlineChip('26 October 1941', TODAY).classList.contains('chip'));
  assert.equal(deadlineChip('', TODAY), null);
  assert.equal(deadlineChip('26 October 1941', null), null);
});

test('every dated item on the desk carries its chip; an undated one or no world date, none', () => {
  const s = desk([item('c', 'Crisis'), item('r', 'Order', { deadline: '5 November 1941' }), item('u', 'Order', { deadline: '' })]);
  const [crisis, order, undated] = rows(s);
  assert.equal(words(crisis.querySelector('.chip')), '6 days left');
  assert.equal(words(order.querySelector('.chip')), '16 days left');
  assert.equal(undated.querySelector('.chip'), null);
  assert.equal(rows(desk([item('r', 'Order')], null))[0].querySelector('.chip'), null);
});

test('the room passes the world date to the desk list', () => {
  const room = read('js/views/realism-room.js');
  assert.match(room, /needsAnswer\(rv\.agenda, \{ act, today: rv\.clock\.world_date \}\)/);
});

test('the crisis and chip styles use tokens only, and no view writes markup or inline style', () => {
  const css = uncomment(read('css/p5-ideas.css'));
  for (const sel of ['.rl-crisis-cause', '.rl-crisis-fail']) assert.match(css, new RegExp(sel.replace('.', '\\.')), sel);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/);
  for (const f of ['js/views/realism-ideas.js', 'js/views/realism-answer.js']) {
    assert.doesNotMatch(uncomment(read(f)), /innerHTML|style=|\.style\./, f);
  }
});
