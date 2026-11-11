// Spec for Train 2 unit M3, written with contract K2: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { formsSummary } from '../js/views/realism-forms.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

test('the summary counts the forms', () => {
  assert.equal(formsSummary(fixture.desk.levers), `Standard forms (${fixture.desk.levers.length})`);
  assert.equal(formsSummary([]), 'Standard forms (0)');
});

test('the folded list draws each form as the desk did, with the closing line', () => {
  const src = read('js/views/realism-forms.js');
  assert.match(src, /import \{[^}]*\binstrument\b[^}]*\} from '\.\/realism\.js'/);
  assert.match(src, /'details'/);
  assert.ok(src.includes("'For anything a form does not cover, write the order in your own words.'"));
});
