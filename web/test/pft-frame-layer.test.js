// While pieces move, a frame repaints the pieces alone: the group that holds the marks, their
// courses and the labels is a layer of its own (`will-change: transform`), and none of the land
// (areas, holders' tones, borders, the coastline) is drawn in it, so a piece placed by the
// playback leaves the land's picture as it was.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { territoryDrawing, forgetMarks } = await import('../js/views/realism-territory.js');
const { placeMark } = await import('../js/map/motion.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const CSS_TEXT = readFileSync(new URL('../css/c-map.css', import.meta.url), 'utf8');
const DESK = { width: 960, height: 740 };
const TMAP = fixture.territory_map;
/** The seat's map drawn with every mark on its own, as the playback draws it. */
const draw = () => territoryDrawing(structuredClone(TMAP), SHAPES, { px: DESK, apart: new Set(TMAP.marks.map((m) => m.key)) });

/** The declarations of every rule in `css` whose selector list names `selector` exactly. */
function declsOf(css, selector) {
  const out = [];
  for (const m of css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (m[1].split(',').map((s) => s.trim()).includes(selector)) out.push(m[2]);
  }
  return out.join(';');
}

test('the group of marks and labels is a layer of its own, so a moving piece repaints only that layer', () => {
  assert.match(declsOf(CSS_TEXT, '.rl-tm-over'), /will-change:\s*transform/);
});

test('none of the land is drawn in the layer the pieces move in', () => {
  forgetMarks();
  const pic = draw();
  const over = pic.querySelector('g.rl-tm-over');
  assert.ok(over, 'the drawing has the group');
  assert.ok(over.querySelectorAll('.rl-tm-mark').length > 0, 'the marks are in it');
  assert.equal(pic.querySelectorAll('.rl-tm-mark').length, over.querySelectorAll('.rl-tm-mark').length, 'every mark is in it');
  for (const land of ['.rl-area', '.rl-hold', '.rl-border', '.rl-tm-notland', '.rl-tm-backdrop', '.rl-map-sea']) {
    assert.equal(over.querySelectorAll(land).length, 0, `no ${land} in it`);
  }
});

test('placing a piece on its way changes the piece and nothing of the land', () => {
  forgetMarks();
  const pic = draw();
  const own = pic.querySelectorAll('g.rl-tm-mark.rl-side-own')[0];
  const labels = pic.querySelectorAll('.rl-tm-label');
  const [from, to] = [labels[0].getAttribute('data-area'), labels[1].getAttribute('data-area')];
  const land = () => pic.querySelectorAll('.rl-area, .rl-hold, .rl-border').map((p) => [p.getAttribute('d'), p.getAttribute('class'), p.getAttribute('fill-opacity')].join('|'));
  const before = land();
  const at = placeMark(pic, own.getAttribute('data-key'), from, to, 0.5);
  assert.ok(at, 'the piece is placed');
  assert.equal(own.getAttribute('data-x'), String(at[0]));
  assert.deepEqual(land(), before);
});
