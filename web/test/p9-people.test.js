// The People roster: one panel with Opponents, Your people and Others, each row a name, an office
// and the meters the view holds for that tab; a row opens the person's dossier.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { buttons, installDom, words } from './dom-fake.js';
import { PEOPLE_TABS, meter, peopleRoster, personDossier, rowMeters } from '../js/views/realism-people.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const people = fixture.people;

const m = (step, word, asOf = '1941-09-20', confidence = 'firm') => ({ step, word, as_of: asOf, confidence });

/** The fixture's roster with loyalty and competence on every line, as a server that held them would send. */
function withCard(p) {
  const add = (l) => ({ ...l, loyalty: m(5, 'Devoted'), competence: m(2, 'Weak') });
  return { opponents: p.opponents.map(add), yours: p.yours.map(add), others: p.others.map(add) };
}

const roster = (p, tab, extra = {}) => peopleRoster(p, { tab, onTab() {}, onOpen() {}, ...extra });
const rows = (panel) => panel.querySelectorAll('.rl-pp-row');
const labels = (row) => row.querySelectorAll('.rl-pp-meter .rl-pp-label').map(words);

test('three tabs, Opponents first, and each tab lists its own group only', () => {
  assert.deepEqual(PEOPLE_TABS.map((t) => t.label), ['Opponents', 'Your people', 'Others']);
  installDom();
  for (const [key, group] of [['opponents', people.opponents], ['yours', people.yours], ['others', people.others]]) {
    const panel = roster(people, key);
    assert.deepEqual(rows(panel).map((r) => words(r.querySelector('.rl-pp-name'))), group.map((l) => l.name), key);
    const pressed = panel.querySelectorAll('.seg button').filter((b) => b.getAttribute('aria-pressed') === 'true');
    assert.equal(pressed.length, 1);
    assert.match(words(pressed[0]), new RegExp(PEOPLE_TABS.find((t) => t.key === key).label));
  }
  const panel = roster(people, 'opponents');
  assert.deepEqual(rows(panel).map((r) => words(r.querySelector('.rl-pp-office'))), people.opponents.map((l) => l.office));
  const picked = [];
  const tabbed = roster(people, 'opponents', { onTab: (k) => picked.push(k) });
  buttons(tabbed, 'Your people 2')[0].click();
  assert.deepEqual(picked, ['yours']);
});

test('an opponent row has stance, regard and reliability; others have no stance', () => {
  installDom();
  const [hitler] = rows(roster(people, 'opponents'));
  assert.deepEqual(labels(hitler), ['Stance', 'Regard', 'Reliability']);
  assert.match(words(hitler), /Hostile/);
  const [hull] = rows(roster(people, 'others'));
  assert.deepEqual(labels(hull), ['Regard', 'Reliability'], 'stance is null for others: not drawn');
});

test('a field absent from the view is not drawn', () => {
  const line = { ...people.opponents[1] };
  delete line.regard;
  assert.deepEqual(rowMeters(line, 'opponents').map((x) => x.key), ['stance', 'reliability']);
  assert.deepEqual(rowMeters({ ...line, stance: null }, 'opponents').map((x) => x.key), ['reliability']);
  installDom();
  const dos = personDossier({ ...people.others[0], last_answer: null, over: [] }, 'others', {});
  assert.doesNotMatch(words(dos), /Last answer|At odds over|Stance/);
  assert.match(words(dos), /Regard/);
});

test('loyalty and competence only for your own people', () => {
  installDom();
  const full = withCard(people);
  const [eden] = rows(roster(full, 'yours'));
  assert.deepEqual(labels(eden), ['Loyalty', 'Competence', 'Reliability', 'Regard']);
  for (const tab of ['opponents', 'others']) {
    for (const r of rows(roster(full, tab))) assert.doesNotMatch(words(r), /Loyalty|Competence|Devoted|Weak/, tab);
    assert.doesNotMatch(words(personDossier(full[tab][0], tab, {})), /Loyalty|Competence/, `${tab} dossier`);
  }
  assert.match(words(personDossier(full.yours[0], 'yours', {})), /Loyalty Devoted.*Competence Weak/);
  assert.deepEqual(labels(rows(roster(people, 'yours'))[0]), ['Reliability', 'Regard'], 'the view on main holds neither');
});

test('untested reliability is the word, not a zero bar; a held step is a five-step bar by class', () => {
  installDom();
  const none = meter('Reliability', people.opponents[0].reliability);
  assert.equal(words(none), 'Reliability Untested');
  assert.equal(none.querySelector('.rl-pp-bar'), null, 'no bar');
  const held = meter('Stance', people.opponents[1].stance);
  const bar = held.querySelector('.rl-pp-bar');
  assert.ok(bar.classList.contains('step-4'));
  assert.equal(bar.querySelectorAll('.rl-pp-cell').length, 5);
  assert.equal(bar.querySelectorAll('.rl-pp-cell.on').length, 4);
  assert.equal(bar.getAttribute('aria-hidden'), 'true', 'the word carries it; the bar is decoration');
  assert.match(words(held), /Stance Cooperative/);
});

test('an empty tab shows a plain line', () => {
  installDom();
  const empty = { opponents: [], yours: [], others: [] };
  for (const t of PEOPLE_TABS) {
    const panel = roster(empty, t.key);
    assert.equal(rows(panel).length, 0);
    const line = panel.querySelector('p.rl-none');
    assert.ok(line, t.key);
    assert.ok(words(line).length > 0 && words(line).length < 60, t.key);
  }
  assert.equal(rows(roster(undefined, 'opponents')).length, 0, 'a view with no roster draws no rows');
});

test('a row opens the dossier: the full set and the stance with its trend and date', () => {
  installDom();
  const opened = [];
  const panel = roster(people, 'opponents', { onOpen: (l, tab) => opened.push([l.name, tab]) });
  rows(panel)[0].click();
  assert.deepEqual(opened, [['Adolf Hitler', 'opponents']]);
  const line = { ...people.opponents[0], trend: 'worse', at_war: true, last_answer: 'Refused your note, 3 October 1941.' };
  const closed = [];
  const dos = personDossier(line, 'opponents', { onClose: () => closed.push(1) });
  assert.equal(dos.tagName.toLowerCase(), 'dialog');
  const text = words(dos);
  assert.match(text, /Adolf Hitler/);
  assert.match(text, /Fuehrer and Reich Chancellor/);
  assert.match(text, /Stance Hostile.*Hardening.*1 September 1941/);
  assert.match(text, /At odds over\s*the blockade and the war at sea/);
  assert.match(text, /At war with you/);
  assert.match(text, /Refused your note/);
  assert.match(text, /Regard Unknown/);
  assert.match(text, /Reliability Untested/);
  dos.showModal();
  buttons(dos, 'Close')[0].click();
  assert.equal(dos.open, false);
  assert.deepEqual(closed, [1]);
});

test('the room draws the roster above the orders, and the stylesheet is linked and clean', () => {
  const room = read('js/views/realism-room.js');
  assert.ok(room.includes("from './realism-people.js'"));
  assert.ok(room.indexOf('peopleRoster(rv.people') > 0);
  assert.ok(room.indexOf('peopleRoster(rv.people') < room.indexOf('orderCards(rv.record'));
  assert.ok(read('index.html').includes('/css/p9-people.css'));
  const css = uncomment(read('css/p9-people.css'));
  for (const cls of ['.rl-pp-row', '.rl-pp-bar', '.rl-pp-cell.on', '.step-1', '.step-5']) assert.ok(css.includes(cls), cls);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/);
  assert.doesNotMatch(uncomment(read('js/views/realism-people.js')), /innerHTML|style=|\.style\./);
});
