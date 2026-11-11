// Unit tests for the desk's wording (Phase 4 unit C1), against the fixture. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  STYLES, agendaItems, agendaList, deskMatters, answerWord, commitBusy, commitCount, commitHint, deadlineWords, itemDates,
  itemHeading, optionLines, orderAddress, orderHeading, partLines,
} from '../js/views/realism-wake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const fixture = JSON.parse(readFileSync(join(WEB, 'test', 'fixtures', 'realism-seat.json'), 'utf8'));
const { wake, agenda, results, proposal } = fixture;
const item = agenda.items[0];
const part = results[0].parts[0];

test('the deadline reads in words, in the given time zone', () => {
  assert.equal(deadlineWords(wake.deadline, 'UTC'), 'Closes Monday 20 October, 9 pm');
  assert.equal(deadlineWords(wake.deadline, 'Asia/Tokyo'), 'Closes Tuesday 21 October, 6 am');
  assert.equal(deadlineWords('2026-11-03T02:00:00Z', 'America/New_York'), 'Closes Monday 2 November, 9 pm');
  assert.equal(deadlineWords('2026-11-03T02:30:00+00:00', 'UTC'), 'Closes Tuesday 3 November, 2:30 am');
  assert.equal(deadlineWords('2026-11-03T00:00:00Z', 'UTC'), 'Closes Tuesday 3 November, 12 am');
});

test('no deadline, no line', () => {
  assert.equal(deadlineWords(null), null);
  assert.equal(deadlineWords('not a time'), null);
});

test('the commit line is a count, and the last commit says the wake runs', () => {
  assert.equal(commitCount(wake), '1 of 2 players done');
  assert.equal(commitCount({ committed: 0, humans: 1 }), '0 of 1 player done');
  assert.match(commitBusy({ committed: 1, humans: 2 }), /wake is running/);
  assert.match(commitBusy({ committed: 0, humans: 1 }), /wake is running/);
  assert.doesNotMatch(commitBusy({ committed: 0, humans: 2 }), /wake is running/);
});

test('the commit hint shows only while a wake is open and you have not committed', () => {
  const hint = 'Your aide plays any seat that has not committed when the wake closes.';
  assert.equal(commitHint({ deadline: wake.deadline, you_committed: false }), hint);
  assert.equal(commitHint({ deadline: wake.deadline, you_committed: true }), null);
  assert.equal(commitHint({ deadline: null, you_committed: false }), null);
  assert.equal(commitHint(wake), null);
});

test('the three play styles say what they do', () => {
  assert.deepEqual(STYLES.map(([value, word]) => [value, word]),
    [['beginner', 'Beginner'], ['guided', 'Guided'], ['free', 'Free']]);
  assert.deepEqual(STYLES.map(([, , note]) => note), [
    'Your aide offers a few ready orders for each matter.',
    'Your aide offers a plan for each matter; you write the orders.',
    'You write every order yourself.',
  ]);
});

test('each style shows its own list, and free shows no agenda', () => {
  assert.equal(agendaList('beginner', item), item.options);
  assert.equal(agendaList('guided', item), item.plan);
  assert.deepEqual(agendaList('free', item), []);
  assert.equal(agendaItems(agenda), agenda.items);
  assert.deepEqual(agendaItems({ ...agenda, style: 'free' }), []);
});

test('the desk keeps only matters with no issuer; a leader\'s request goes to the tray', () => {
  const crisis = { ...item, id: 'c1', kind: 'Crisis', issuer: null };
  assert.deepEqual(deskMatters({ ...agenda, items: [item, crisis] }).map((i) => i.id), ['c1']);
  assert.deepEqual(deskMatters({ ...agenda, style: 'free', items: [crisis] }), []);
});

test('an agenda item reads in words, whether the date comes as a day or as words', () => {
  assert.equal(itemHeading(item), 'Order from Franklin D. Roosevelt');
  assert.equal(itemHeading({ ...item, issuer: null }), 'Order');
  assert.equal(itemDates(item), 'Issued 12 October 1941 · Due by 26 October 1941');
  assert.equal(itemDates({ issued: '12 October 1941', deadline: '26 October 1941' }),
    'Issued 12 October 1941 · Due by 26 October 1941');
});

test('an option says to whom and the risk, and hides a missing one', () => {
  assert.deepEqual(optionLines(agenda.initiative[0]),
    ['To Sam Rayburn', 'Risk: Word of the count may get out.']);
  assert.deepEqual(optionLines({ to: null, risk: '' }), []);
});

test('the answer is a word, or nothing', () => {
  assert.equal(answerWord(true), 'Agreed');
  assert.equal(answerWord(false), 'Declined');
  assert.equal(answerWord(null), null);
});

test('a result part shows what is known and hides the rest', () => {
  assert.deepEqual(partLines(part), [
    'To Harold R. Stark', 'Your command', 'Carried out loosely', 'Stark read the order narrowly.',
    'Landed 14 October 1941',
  ]);
  assert.deepEqual(partLines({ ...part, accepted: false, applied: '14 October 1941' }).slice(-2),
    ['Declined', 'Landed 14 October 1941']);
  assert.deepEqual(partLines({
    to: null, route: 'Through Congress', fidelity: null, refused_under: 'Refused under standing rule',
    reason: '', accepted: true, applied: null,
  }), ['Through Congress', 'Refused under standing rule', 'Agreed']);
});

test('the order card heads itself by whether there is anything to sign', () => {
  assert.equal(orderHeading(proposal), 'Ready to sign');
  assert.equal(orderHeading({ ...proposal, parts: [], reason: 'Name who should act on it.' }), 'This cannot be sent');
});

test('the order address is in words, and hides what is missing', () => {
  assert.equal(orderAddress(proposal), 'To Harold R. Stark, by cable');
  assert.equal(orderAddress({ person: 'Harold R. Stark', channel: 'In person' }), 'To Harold R. Stark, in person');
  assert.equal(orderAddress({ person: 'Harold R. Stark', channel: null }), 'To Harold R. Stark');
  assert.equal(orderAddress({ person: null, channel: null }), null);
});

test('nothing the helpers say holds an underscore or an ISO date', () => {
  const said = [
    deadlineWords(wake.deadline, 'UTC'), commitCount(wake), commitBusy(wake),
    STYLES.flat(), itemHeading(item), itemDates(item),
    [...item.options, ...item.plan, ...agenda.initiative].flatMap(optionLines),
    partLines(part), orderHeading(proposal), orderAddress(proposal),
  ].flat();
  for (const line of said) {
    assert.doesNotMatch(line, /_/);
    assert.doesNotMatch(line, /\d{4}-\d{2}-\d{2}/);
  }
});
