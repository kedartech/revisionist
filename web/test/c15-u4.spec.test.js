// Spec for 15a unit U4 (orders and threats), written with the console contract: the unit makes
// it pass and never edits it. Each order card shows the kit stepper of its real steps by person
// and its status as a kit chip; each opponent shows a stance chip, the trend word with an arrow,
// and three confidence pips with the confidence word. No five-step meter (decision 4).
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';

installDom();
const { orderCards } = await import('../js/views/realism-orders.js');
const { threatsPanel } = await import('../js/views/realism-threats.js');
const { TONES } = await import('../js/views/ui-kit.js');

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const OWNS = ['js/views/realism-orders.js', 'js/views/realism-threats.js', 'css/p4-orders.css', 'css/p8-threats.css', 'css/p5-answer.css'];
const cards = () => orderCards(fixture.record, fixture.orders, () => null).querySelectorAll('.rl-oc-card');
const toneOf = (el) => TONES.find((t) => el.classList.contains(`tone-${t}`));

test('every order card shows its status as one kit chip with a kit tone', () => {
  const all = cards();
  assert.ok(all.length >= 10);
  for (const card of all) {
    const chips = card.querySelectorAll('.chip');
    assert.equal(chips.length, 1, words(card));
    assert.ok(words(chips[0]).length > 0);
    assert.ok(toneOf(chips[0]), `a kit tone on "${words(chips[0])}"`);
  }
  const tone = (word) => toneOf(all.map((c) => c.querySelector('.chip')).find((c) => c && words(c) === word));
  assert.equal(tone('Needs you'), 'warn');
  assert.equal(tone('Under way'), 'info');
  assert.equal(tone('Carried out'), 'ok');
});

test('a card with a tracked order shows its real steps by person, the holder here now', () => {
  const steppers = cards().flatMap((c) => c.querySelectorAll('.stepper'));
  const tracked = fixture.record.orders.filter((o) => o.track && fixture.orders.orders.some((t) => t.id === o.track));
  assert.equal(steppers.length, tracked.length, 'one stepper per tracked order');
  const now = steppers.flatMap((s) => s.querySelectorAll('li.now')).map(words);
  assert.ok(now.some((w) => /Sam Rayburn/.test(w)), now.join(' | '));
  const settled = steppers.flatMap((s) => s.querySelectorAll('li.done'));
  assert.ok(settled.length >= 1, 'the steps already acted on read as done');
});

test('an opponent shows a stance chip, its trend with an arrow and three confidence pips', () => {
  const panel = threatsPanel(fixture.threats);
  const rows = panel.querySelectorAll('.rl-threat');
  assert.equal(rows.length, fixture.threats.length);
  const PIPS = { firm: 3, dated: 2, old: 1 };
  const WORD = { firm: /\bFirm\b/, dated: /\bDated\b/, old: /\bOld\b/ };
  fixture.threats.forEach((t, i) => {
    const row = rows[i];
    const chip = row.querySelector('.chip');
    assert.ok(chip, `${t.name}: a stance chip`);
    assert.equal(words(chip), t.stance_label);
    assert.equal(toneOf(chip), t.stance === 'hostile' ? 'danger' : 'warn');
    if (t.trend !== 'steady') {
      const trend = row.querySelector('.rl-threat-trend');
      assert.ok(trend, `${t.name}: a trend`);
      assert.ok(/[↑↓↗↘▲▼]/.test(words(trend)) || trend.querySelector('svg'), `${t.name}: an arrow with the trend`);
    }
    const pips = row.querySelector('.rl-pips');
    assert.ok(pips, `${t.name}: confidence pips`);
    assert.equal(pips.children.length, 3);
    assert.equal(pips.children.filter((p) => p.classList.contains('on')).length, PIPS[t.confidence]);
    assert.match(words(row), WORD[t.confidence]);
  });
});

test('no five-step stance meter', () => {
  for (const f of OWNS) assert.doesNotMatch(read(f), /\b(Cold|Warm|Close)\b.*\b(Cold|Warm|Close)\b|disposition\(/, f);
});

test('owned files: no HTML parsing, no inline style, no colour literal', () => {
  for (const f of OWNS) {
    const src = uncomment(read(f));
    assert.doesNotMatch(src, /innerHTML|style=|\.style\./, f);
    if (f.endsWith('.css')) assert.doesNotMatch(src, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, f);
  }
});
