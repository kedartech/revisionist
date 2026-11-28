import { test } from 'node:test';
import assert from 'node:assert/strict';

import * as rules from '../js/realism-rules.js';
import * as projection from '../js/map/projection.js';
import * as view from '../js/map/view.js';
import * as gestures from '../js/map/gestures.js';
import * as hit from '../js/map/hit.js';

const MOVED = {
  projection: ['projection', 'territoryProjection', 'boxOf', 'frameRect'],
  view: ['ZOOMS', 'viewWindow', 'unitsPerPx', 'pinchZoom'],
  hit: ['inArea'],
};
const MODULES = { projection, view, hit };

for (const [mod, names] of Object.entries(MOVED)) {
  for (const name of names) {
    test(`${name} lives in map/${mod}.js and realism-rules.js re-exports the same one`, () => {
      assert.notEqual(MODULES[mod][name], undefined);
      assert.equal(rules[name], MODULES[mod][name]);
    });
  }
}

test('the gesture code is its own module', () => {
  assert.equal(typeof gestures.gestures, 'function');
});

test('the moved maths still gives its answers', () => {
  const rect = projection.frameRect({ west: 0, south: 0, east: 10, north: 10 }, projection.territoryProjection('flat', { west: 0, south: 0, east: 10, north: 10 }));
  assert.deepEqual(rect, { x: 0, y: 0, w: 10, h: 10 });
  assert.deepEqual(view.viewWindow(rect, 2, [0, 0]), { x: 0, y: 0, w: 5, h: 5 });
  assert.equal(view.pinchZoom(1, 3.9), 4);
  const shapes = { vertices: [[0, 0], [4, 0], [4, 4], [0, 4]], areas: { a: { rings: [[0, 1, 2, 3]] } } };
  assert.equal(hit.inArea(shapes, 'a', [2, 2]), true);
  assert.equal(hit.inArea(shapes, 'a', [5, 2]), false);
});
