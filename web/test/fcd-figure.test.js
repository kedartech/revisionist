// The figure card: one card for any person on the People roster, in fixed groups (Now, Toward
// you, What they can do, Their record with you, What moves them, Between you), each drawn only
// when it holds something, from the figure card's data in the view.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { buttons, installDom, words } from './dom-fake.js';
import { figureCard } from '../js/views/realism-figure.js';
import { personDossier } from '../js/views/realism-people.js';
import { monogram } from '../js/views/realism-dossier.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
const { people } = JSON.parse(read('test/fixtures/realism-seat.json'));

const byName = (group, name) => people[group].find((l) => l.name === name);
const hitler = byName('opponents', 'Adolf Hitler');
const stalin = byName('opponents', 'Joseph Stalin');
const pound = { ...byName('yours', 'Sir Dudley Pound'), wants: ['the Atlantic convoys'], holds_to: ['the fleet kept whole'] };
const eden = byName('yours', 'Anthony Eden');
const hull = byName('others', 'Cordell Hull');

const heads = (card) => card.querySelectorAll('.rl-fc-h').map(words);
const group = (card, title) => card.querySelectorAll('.rl-fc-grp').find((g) => words(g.querySelector('.rl-fc-h')) === title);
const rowFor = (card, label) => card.querySelectorAll('.rl-fc-row').find((r) => words(r.querySelector('.rl-fc-label')) === label);

test('groups come in the fixed order, and a group with nothing in it is not drawn', () => {
  installDom();
  assert.deepEqual(heads(figureCard(pound, 'yours')),
    ['Now', 'Toward you', 'What they can do', 'Their record with you', 'What moves them']);
  assert.deepEqual(heads(figureCard(hitler, 'opponents')),
    ['Toward you', 'What they can do', 'Their record with you', 'Between you']);
  assert.deepEqual(heads(figureCard(hull, 'others')), ['Toward you', 'What they can do', 'Their record with you']);
  assert.deepEqual(heads(figureCard(eden, 'yours')),
    ['Toward you', 'What they can do', 'Their record with you'], 'no holds and no topics: no Now, no What moves them');
});

test('Now lists each order of yours they hold, with its days and the staff read', () => {
  installDom();
  const now = group(figureCard(pound, 'yours'), 'Now');
  const text = words(now);
  assert.match(text, /Holds your order: Move the Home Fleet/);
  assert.match(text, /since 14 October 1941, 6 days; the step takes about 2 days/);
  assert.match(text, /Staff read: may hold it/);
  assert.match(text, /a read, not a promise/);
  const unstated = { ...pound, holds: [{ ...pound.holds[0], days: null, held_days: 1, read: null }] };
  const bare = words(group(figureCard(unstated, 'yours'), 'Now'));
  assert.match(bare, /since 14 October 1941, 1 day/);
  assert.doesNotMatch(bare, /takes about|Staff read/, 'no stated days and no read: neither is drawn');
});

test('an own person: loyalty, regard, competence, standing, load, record and what moves them', () => {
  installDom();
  const card = figureCard(pound, 'yours');
  assert.deepEqual(group(card, 'Toward you').querySelectorAll('.rl-fc-label').map(words), ['Loyalty', 'Regard']);
  assert.deepEqual(group(card, 'What they can do').querySelectorAll('.rl-fc-label').map(words),
    ['Competence', 'Standing', 'Load']);
  assert.match(words(rowFor(card, 'Loyalty')), /Loyal/);
  assert.match(words(rowFor(card, 'Competence')), /Capable/);
  assert.match(words(rowFor(card, 'Standing')), /Established|Senior|Paramount|Junior|Minor/);
  assert.match(words(rowFor(card, 'Load')), /^Load 1 of your orders$/);
  const rec = group(card, 'Their record with you');
  assert.deepEqual(rec.querySelectorAll('.rl-fc-label').map(words), ['Reliability', 'Pace']);
  assert.match(words(rec.querySelector('.rl-fc-tally')), /2 passed.*0 hurried.*1 held.*0 amended.*0 refused.*0 leaked/);
  const moves = group(card, 'What moves them');
  assert.match(words(moves), /Wants\s*the Atlantic convoys/);
  assert.match(words(moves), /Holds to\s*the fleet kept whole/);
  assert.equal(group(card, 'Between you'), undefined);
  assert.match(words(rowFor(figureCard(eden, 'yours'), 'Load')), /none of your orders/, 'an own person shows a free hand');
});

test('a leader: stance with its trend, power in place of standing, and Between you', () => {
  installDom();
  const line = { ...hitler, trend: 'worse', last_answer: 'Refused your note, 3 October 1941.' };
  const card = figureCard(line, 'opponents');
  assert.deepEqual(group(card, 'Toward you').querySelectorAll('.rl-fc-label').map(words), ['Stance', 'Regard']);
  assert.match(words(rowFor(card, 'Stance')), /Stance Hostile.*Hardening, as of 1 September 1941/);
  assert.deepEqual(group(card, 'What they can do').querySelectorAll('.rl-fc-label').map(words), ['Power']);
  assert.match(words(rowFor(card, 'Power')), /Overwhelming/);
  const between = words(group(card, 'Between you'));
  assert.match(between, /At odds over\s*the blockade and the war at sea/);
  assert.match(between, /War\s*Not at war with you\./);
  assert.match(between, /Last answer\s*Refused your note/);
  assert.match(words(group(figureCard({ ...stalin, at_war: true }, 'opponents'), 'Between you')), /War\s*At war with you\./);
  assert.match(words(group(figureCard(stalin, 'opponents'), 'Between you')), /^Between you\s*War Not at war with you\.$/,
    'a leader with nothing at issue still has Between you');
  assert.equal(group(card, 'What moves them'), undefined, 'a leader shows nothing of what moves them');
  assert.equal(card.querySelector('.rl-fc-tally'), null, 'no order of yours went through them: no tally');
});

test('an outsider: regard, standing and record only; Between you is a leader\'s alone', () => {
  installDom();
  const card = figureCard(hull, 'others');
  assert.deepEqual(card.querySelectorAll('.rl-fc-label').map(words), ['Regard', 'Standing', 'Reliability', 'Pace']);
  const warred = figureCard({ ...hull, at_war: true, last_answer: 'Declined, 2 October 1941.' }, 'others');
  assert.equal(group(warred, 'Between you'), undefined);
  assert.match(words(warred.querySelector('.rl-fc-sub')), /At war with you/, 'a war shows in the head');
  assert.match(words(group(warred, 'Their record with you')), /Last answer\s*Declined, 2 October 1941\./);
  const ownAnswer = figureCard({ ...eden, last_answer: 'Agreed, 9 October 1941.' }, 'yours');
  assert.equal(group(ownAnswer, 'Between you'), undefined);
  assert.match(words(group(ownAnswer, 'Their record with you')), /Last answer\s*Agreed/);
});

test('a meter with nothing to go on shows its word and no bar; a held step is a five-cell bar', () => {
  installDom();
  const card = figureCard(hitler, 'opponents');
  const rel = rowFor(card, 'Reliability');
  assert.match(words(rel), /Untested/);
  assert.equal(rel.querySelector('.rl-pp-bar'), null);
  assert.ok(rel.classList.contains('none'));
  const power = rowFor(card, 'Power').querySelector('.rl-pp-bar');
  assert.ok(power.classList.contains('step-5'));
  assert.equal(power.querySelectorAll('.rl-pp-cell').length, 5);
  assert.equal(power.querySelectorAll('.rl-pp-cell.on').length, 5);
  assert.equal(power.getAttribute('aria-hidden'), 'true');
});

test('card values and topics show only on the Your people tab, whatever the line carries', () => {
  installDom();
  const smuggled = { loyalty: pound.loyalty, competence: pound.competence, wants: ['x'], holds_to: ['y'] };
  for (const [line, tab] of [[hitler, 'opponents'], [hull, 'others']]) {
    const text = words(figureCard({ ...line, ...smuggled }, tab));
    assert.doesNotMatch(text, /Loyalty|Competence|Wants|Holds to|What moves them/, tab);
  }
});

test('the head: name, office, body, how you stand and how they are reached', () => {
  installDom();
  const head = (line, tab) => words(figureCard(line, tab).querySelector('.rl-fc-head'));
  assert.match(head(pound, 'yours'), /Sir Dudley Pound.*First Sea Lord.*Chiefs of Staff Committee · One of your people · Reached in person, within a day/);
  assert.match(head(stalin, 'opponents'), /Soviet Union · Set against you · Reached by cable, the same day/);
  assert.match(head(hull, 'others'), /Department of State$/);
});

test('a portrait where one exists, otherwise a tile with the initials', () => {
  installDom();
  const tile = figureCard(pound, 'yours').querySelector('.portrait-mono');
  assert.equal(words(tile), monogram('Sir Dudley Pound'), 'the shared monogram, as every other portrait tile');
  assert.equal(tile.getAttribute('aria-hidden'), 'true', 'the name beside it carries it');
  const card = figureCard(hitler, 'opponents', { dossier: { portrait: 'hitler.jpg', credit: 'Bundesarchiv' } });
  const img = card.querySelector('img');
  assert.equal(img.getAttribute('src'), '/assets/portraits/hitler.jpg');
  assert.equal(img.getAttribute('alt'), 'Adolf Hitler');
  assert.equal(card.querySelector('.portrait-mono'), null);
});

test('a dialog named by its title; Close closes it and calls onClose', () => {
  installDom();
  const closed = [];
  const card = figureCard(hull, 'others', { onClose: () => closed.push(1) });
  assert.equal(card.tagName.toLowerCase(), 'dialog');
  assert.equal(words(card.querySelector(`[id="${card.getAttribute('aria-labelledby')}"]`)), 'Cordell Hull');
  card.showModal();
  buttons(card, 'Close')[0].click();
  assert.equal(card.open, false);
  assert.deepEqual(closed, [1]);
});

test('a roster row opens the figure card; text nodes only; the stylesheet is linked and clean', () => {
  installDom();
  assert.ok(personDossier(hull, 'others', {}).classList.contains('rl-fc'));
  const framed = personDossier(hull, 'others', { dossier: { portrait: 'roosevelt.jpg', credit: 'x' } });
  assert.equal(framed.querySelector('img').getAttribute('src'), '/assets/portraits/roosevelt.jpg', 'the roster passes a portrait on');
  assert.doesNotMatch(uncomment(read('js/views/realism-figure.js')), /innerHTML|style=|\.style\./);
  assert.ok(read('index.html').includes('<link rel="stylesheet" href="/css/c-figure.css">'));
  const css = uncomment(read('css/c-figure.css'));
  for (const cls of ['.rl-fc-grp', '.rl-fc-row', '.rl-fc-tag', '.rl-fc-now']) assert.ok(css.includes(cls), cls);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/);
});
