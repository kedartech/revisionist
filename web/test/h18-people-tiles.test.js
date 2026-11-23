// The People roster as portrait tiles: the portrait the roster line names, or the person's own
// initials, with the name, the office and the meters of today; three groups; a tile opens the card.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';
import { PEOPLE_TABS, peopleRoster } from '../js/views/realism-people.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
const people = JSON.parse(read('test/fixtures/realism-seat.json')).people;

const roster = (p, tab, extra = {}) => peopleRoster(p, { tab, onTab() {}, onOpen() {}, ...extra });
const tiles = (panel) => panel.querySelectorAll('.rl-pp-tile');

test('each person is a tile: the portrait they name, the name, the office and the meters of today', () => {
  installDom();
  const panel = roster(people, 'opponents');
  const [hitler, stalin] = tiles(panel);
  assert.equal(tiles(panel).length, people.opponents.length);
  const img = hitler.querySelector('img.rl-pp-portrait');
  assert.equal(img.getAttribute('src'), '/assets/portraits/hitler.jpg');
  assert.equal(img.getAttribute('alt'), 'Adolf Hitler');
  assert.equal(stalin.querySelector('img.rl-pp-portrait').getAttribute('src'), '/assets/portraits/stalin.jpg');
  assert.equal(hitler.querySelector('.rl-pp-mono'), null, 'a portrait draws no initials');
  assert.equal(words(hitler.querySelector('.rl-pp-name')), 'Adolf Hitler');
  assert.equal(words(hitler.querySelector('.rl-pp-office')), 'Fuehrer and Reich Chancellor');
  assert.deepEqual(hitler.querySelectorAll('.rl-pp-meter .rl-pp-label').map(words), ['Stance', 'Regard', 'Reliability']);
});

test('a person with no portrait draws their own initials and no image', () => {
  installDom();
  const panel = roster(people, 'yours');
  assert.ok(people.yours.length > 1);
  assert.equal(tiles(panel).length, people.yours.length);
  tiles(panel).forEach((tile, i) => {
    const line = people.yours[i];
    assert.equal(tile.querySelector('img'), null, line.name);
    const mono = tile.querySelector('.rl-pp-mono');
    assert.ok(mono, line.name);
    const parts = line.name.split(/\s+/);
    assert.equal(words(mono), (parts[0][0] + (parts.length > 1 ? parts.at(-1)[0] : '')).toUpperCase(), line.name);
    assert.equal(mono.getAttribute('aria-hidden'), 'true');
  });
});

test('a portrait value that is not a bare image file name draws initials', () => {
  installDom();
  const bad = { opponents: ['../x.jpg', 'https://e.test/a.jpg', 'a b.jpg', ''].map((portrait, i) => ({ ...people.opponents[0], person: `p${i}`, portrait })), yours: [], others: [] };
  assert.equal(tiles(roster(bad, 'opponents')).length, 4);
  for (const tile of tiles(roster(bad, 'opponents'))) {
    assert.equal(tile.querySelector('img'), null);
    assert.equal(words(tile.querySelector('.rl-pp-mono')), 'AH');
  }
});

test('the tiles keep the three groups and their order, each tab listing its own group', () => {
  assert.deepEqual(PEOPLE_TABS.map((t) => t.label), ['Opponents', 'Your people', 'Others']);
  installDom();
  for (const key of ['opponents', 'yours', 'others']) {
    const panel = roster(people, key);
    const grid = panel.querySelector('ul.rl-pp-tiles');
    assert.ok(grid, key);
    assert.deepEqual(tiles(grid).map((t) => words(t.querySelector('.rl-pp-name'))), people[key].map((l) => l.name), key);
  }
});

test('a tile opens the person\'s figure card: one button each, with the line and the tab', () => {
  installDom();
  const opened = [];
  const panel = roster(people, 'yours', { onOpen: (l, tab) => opened.push([l.name, tab]) });
  const all = tiles(panel);
  assert.ok(all.every((t) => t.tagName.toLowerCase() === 'button'));
  all[1].click();
  assert.deepEqual(opened, [[people.yours[1].name, 'yours']]);
});

test('at 390 px the tiles are two to a row and every tile is a 44 px target', () => {
  const css = uncomment(read('css/p9-people.css'));
  const phone = css.match(/@media \(max-width: (\d+)px\) \{([\s\S]*?)\n\}/);
  assert.ok(phone, 'a phone block');
  assert.ok(Number(phone[1]) >= 390 && Number(phone[1]) < 600);
  assert.match(phone[2], /\.rl-pp-tiles\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
  assert.match(css, /\.rl-pp-tile\s*\{[^}]*min-height:\s*44px/, 'a target on every pointer, not only coarse');
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/);
});

test('the portrait is greyscale by the theme, drawn from the stylesheet and not by script', () => {
  assert.doesNotMatch(uncomment(read('js/views/realism-people.js')), /innerHTML|style=|\.style\./);
  assert.match(uncomment(read('css/p9-people.css')), /\.rl-pp-portrait\s*\{[^}]*filter:\s*grayscale\(1\)/);
});
