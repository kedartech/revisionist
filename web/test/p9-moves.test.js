// Where forces moved (wake-run plan, W2): What happened replays the marks that changed place
// between the map before the run and the map after, drawn as routes with a list beside them.
// Newly sighted and lost-from-sight marks are not moves, and nothing is drawn that the seat's
// map after the run does not hold.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';
import { movedMarks, movesBlock, moveLine, runMoves } from '../js/views/realism-moves.js';
import { happenedSheet } from '../js/views/realism-happened.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');

const P = {
  norfolk: { name: 'Norfolk', lat: 36.9, lon: -76.3 },
  argentia: { name: 'Argentia', lat: 47.3, lon: -54.0 },
  reykjavik: { name: 'Reykjavik', lat: 64.1, lon: -21.9 },
  lorient: { name: 'Lorient', lat: 47.7, lon: -3.4 },
  brest: { name: 'Brest', lat: 48.4, lon: -4.5 },
  scapa: { name: 'Scapa Flow', lat: 58.9, lon: -3.1 },
};
const mark = (name, side, places, extra = {}) => ({
  name, kind: 'fleet', side, side_name: side === 'own' ? 'United States' : 'Germany',
  certainty: side === 'own' ? 'known' : 'reported', reported: '1941-10-13', source: 'Harold R. Stark',
  document: 'd-1', places, ...extra,
});
const map = (marks) => ({ places: Object.values(P), marks, orders: [] });

const atlantic = mark('US Atlantic Fleet', 'own', [P.norfolk]);
const pacific = mark('US Pacific Fleet', 'own', [{ name: 'Pearl Harbor', lat: 21.4, lon: -157.9 }]);
const uboats = mark('U-boat arm', 'other', [P.lorient]);
const home = mark('Home Fleet', 'other', [P.scapa], { side_name: 'United Kingdom' });
const before = map([atlantic, pacific, uboats]);
const after = map([
  { ...atlantic, places: [P.argentia], reported: '1941-10-20' }, // moved
  pacific, // unchanged
  home, // newly sighted
  // U-boat arm: lost from sight
]);

test('a mark that changed place is a move, from where it was to where it is', () => {
  const moves = movedMarks(before, after);
  assert.equal(moves.length, 1);
  assert.equal(moves[0].name, 'US Atlantic Fleet');
  assert.deepEqual(moves[0].from, [P.norfolk]);
  assert.deepEqual(moves[0].to, [P.argentia]);
  assert.equal(moves[0].side, 'own');
  assert.equal(moveLine(moves[0]), 'US Atlantic Fleet: Norfolk to Argentia');
});

test('an unchanged mark is not a move, even with a newer report', () => {
  const later = map([{ ...pacific, reported: '1941-10-20', document: 'd-2' }]);
  assert.deepEqual(movedMarks(map([pacific]), later), []);
});

test('a newly sighted mark is not a move', () => {
  assert.deepEqual(movedMarks(map([]), map([home])), []);
  assert.ok(!movedMarks(before, after).some((m) => m.name === 'Home Fleet'));
});

test('a mark lost from sight is not a move', () => {
  assert.deepEqual(movedMarks(map([uboats]), map([])), []);
  assert.ok(!movedMarks(before, after).some((m) => m.name === 'U-boat arm'));
});

test('another side\'s mark seen in both maps at different places is a move, as the papers have it', () => {
  const moves = movedMarks(map([uboats]), map([{ ...uboats, places: [P.brest] }]));
  assert.deepEqual(moves.map((m) => [m.name, m.side]), [['U-boat arm', 'other']]);
});

test('a line that changed its course is a move; missing maps give none', () => {
  const route = mark('HX convoys', 'other', [P.norfolk, P.argentia], { kind: 'route' });
  const moved = movedMarks(map([route]), map([{ ...route, places: [P.norfolk, P.reykjavik] }]));
  assert.equal(moveLine(moved[0]), 'HX convoys: Norfolk – Argentia to Norfolk – Reykjavik');
  for (const [b, a] of [[null, after], [before, null], [undefined, undefined], [{}, {}], [{ marks: null }, after]]) {
    assert.deepEqual(movedMarks(b, a), []);
  }
});

test('the moves of a run are kept only for the wake right after it', () => {
  const from = { wake: 3, map: before };
  assert.equal(runMoves(from, { number: 4 }, after).length, 1);
  assert.deepEqual(runMoves(from, { number: 5 }, after), [], 'a later wake someone else ran');
  assert.deepEqual(runMoves(from, { number: 3 }, after), [], 'the run did not open a wake');
  assert.deepEqual(runMoves(null, { number: 4 }, after), [], 'no run started in this room');
  assert.deepEqual(runMoves(from, null, after), []);
});

test('movesBlock: one route on the map and one line beside it per move', () => {
  installDom();
  const block = movesBlock({ moves: movedMarks(before, after), places: after.places });
  assert.ok(block.classList.contains('rl-moves'));
  assert.equal(words(block.querySelector('h3')), 'Where forces moved');
  assert.deepEqual(block.querySelectorAll('.rl-moves-list li').map(words), ['US Atlantic Fleet: Norfolk to Argentia']);
  const svgEl = block.querySelector('svg.rl-map-svg');
  assert.ok(svgEl, 'drawn with the map view\'s drawing');
  const routes = svgEl.querySelectorAll('polyline.rl-mk-line');
  assert.equal(routes.length, 1, 'one route');
  assert.equal(routes[0].getAttribute('points').split(' ').length, 2, 'from the old place to the new');
  // the map view's own controls are not part of the replay
  assert.equal(block.querySelector('.rl-bar'), null);
  assert.equal(block.querySelector('.rl-legend'), null);
});

test('movesBlock draws only the moved marks: no other side\'s mark the seat no longer sees', () => {
  installDom();
  const block = movesBlock({ moves: movedMarks(before, after), places: after.places });
  const drawn = block.querySelectorAll('svg .rl-mk').map((g) => g.getAttribute('aria-label') ?? '');
  assert.ok(drawn.length > 0);
  for (const name of ['U-boat arm', 'Home Fleet', 'US Pacific Fleet']) {
    assert.ok(!drawn.some((l) => l.startsWith(`${name}:`)), name);
    assert.ok(!words(block).includes(name), name);
  }
});

test('movesBlock with no moves draws nothing', () => {
  installDom();
  assert.equal(movesBlock({ moves: [], places: after.places }), null);
  assert.equal(movesBlock({}), null);
});

test('What happened carries the block when the room passes moves, and none without', () => {
  installDom();
  const base = { record: fixture.record, situation: fixture.situation, agenda: fixture.agenda, date: '20 October 1941', onClose: () => {} };
  const sheet = happenedSheet({ ...base, moves: movedMarks(before, after), places: after.places });
  const block = sheet.querySelector('.rl-moves');
  assert.ok(block, 'the block is in the sheet');
  const kids = sheet.children;
  assert.ok(kids.indexOf(block) < kids.indexOf(sheet.querySelector('.rl-hap-actions')), 'above the button');
  assert.equal(happenedSheet(base).querySelector('.rl-moves'), null);
});

test('the room keeps the map from before the run and passes the moves to the sheet', () => {
  const room = read('js/views/realism-room.js');
  assert.match(room, /if \(message === RUNNING\) \{\s*ui\.runFrom = \{ wake: rv\.record\?\.wake\?\.number \?\? 0, map: rv\.map \?\? null \};/);
  assert.match(room, /happenedSheet\(\{[^)]*moves: runMoves\(ui\.runFrom, page, rv\.map\), places: rv\.map\?\.places/);
  assert.match(room, /runFrom: null/, 'a new game starts with no run kept');
  assert.match(read('index.html'), /<link rel="stylesheet" href="\/css\/p5-moves\.css">/);
});

test('the replay map draws no names; the list beside it names each move', () => {
  const css = uncomment(read('css/p5-moves.css'));
  assert.match(css, /\.rl-moves \.rl-map-svg text \{ display: none; \}/);
});

test('routes draw in by CSS; reduced motion shows them still', () => {
  const css = uncomment(read('css/p5-moves.css'));
  const animated = [...css.matchAll(/([^{}]+)\{[^{}]*\banimation:\s*(?!none)[^;]+;/g)].map((m) => m[1].trim());
  assert.ok(animated.length > 0, 'something animates');
  assert.ok(animated.every((sel) => sel.includes('.rl-moves')), 'scoped to the block');
  const reduced = css.match(/@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\}/)?.[1] ?? '';
  for (const sel of animated) assert.ok(reduced.includes(sel) && /animation:\s*none/.test(reduced), `${sel} is still under reduced motion`);
  // the keyframes start from the hidden state and end at the drawn one, so a still route is drawn
  for (const [, body] of css.matchAll(/@keyframes [\w-]+ \{([\s\S]*?)\n\}/g)) assert.doesNotMatch(body, /\bto\s*\{/);
});
