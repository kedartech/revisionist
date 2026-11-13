// The opponents list of the room: one line per person set against the seat, as the staff believe it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';
import { threatLines, threatsPanel } from '../js/views/realism-threats.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const threat = (over) => ({
  person: 'e-hitler', name: 'Adolf Hitler', office: 'Führer and Reich Chancellor', stance: 'obstructing',
  stance_label: 'Obstructing', trend: 'steady', as_of: '1941-09-01', confidence: 'firm', over: [],
  cause: 'As things stood at the start.', ...over,
});

test('a line says who, how they stand, how the staff know and why', () => {
  const [line] = threatLines([threat({ trend: 'worse', confidence: 'old', over: ['Command of the Atlantic', 'The war itself'] })]);
  assert.deepEqual(line, {
    person: 'e-hitler',
    name: 'Adolf Hitler',
    office: 'Führer and Reich Chancellor',
    stance: 'obstructing',
    label: 'Obstructing',
    trend: 'Hardening',
    known: 'As of 1 September 1941. Old news: it may have changed.',
    over: 'Over: Command of the Atlantic; The war itself',
    cause: 'As things stood at the start.',
  });
});

test('the trend and the age of the evidence each have their words', () => {
  const by = (over) => threatLines([threat(over)])[0];
  assert.equal(by({ trend: 'steady' }).trend, '');
  assert.equal(by({ trend: 'better' }).trend, 'Easing');
  assert.equal(by({ confidence: 'firm' }).known, 'As of 1 September 1941.');
  assert.equal(by({ confidence: 'dated' }).known, 'As of 1 September 1941. Some weeks old.');
  assert.equal(by({ over: [] }).over, '');
});

test('no opponents, no panel', () => {
  installDom();
  assert.equal(threatsPanel(undefined), null);
  assert.equal(threatsPanel([]), null);
});

test('the panel lists each opponent under its heading, in the order sent', () => {
  installDom();
  const panel = threatsPanel([threat({ stance: 'hostile', stance_label: 'Hostile', trend: 'worse' }), threat({ person: 'e-m', name: 'Benito Mussolini' })]);
  assert.equal(panel.querySelector('h2').textContent, 'Opponents');
  const rows = panel.querySelectorAll('li');
  assert.equal(rows.length, 2);
  assert.match(words(rows[0]), /^Adolf Hitler Führer and Reich Chancellor ?Hostile ↗ Hardening ?As of 1 September 1941\. As things stood at the start\. ?Firm$/);
  assert.match(words(rows[1]), /^Benito Mussolini/);
  assert.ok(rows[0].querySelector('.rl-threat-stance').className.includes('rl-threat-hostile'));
});

test('the fixture carries the block and the room draws it above the orders', () => {
  assert.ok(Array.isArray(fixture.threats) && fixture.threats.length);
  assert.deepEqual(Object.keys(fixture.threats[0]).sort(), Object.keys(threat()).sort());
  const room = read('js/views/realism-room.js');
  assert.ok(room.includes("from './realism-threats.js'"));
  assert.ok(room.indexOf('threatsPanel(rv.threats)') < room.indexOf('orderCards(rv.record'));
  assert.ok(room.indexOf('threatsPanel(rv.threats)') > 0);
  assert.ok(read('index.html').includes('/css/p8-threats.css'));
});

test('the stylesheet uses tokens only', () => {
  const css = read('css/p8-threats.css');
  assert.ok(!/#[0-9a-fA-F]{3,8}\b/.test(css));
  for (const cls of ['.rl-threats', '.rl-threat-stance', '.rl-threat-hostile', '.rl-threat-obstructing']) assert.ok(css.includes(cls), cls);
});
