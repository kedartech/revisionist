// A paper whose letter could not be written shows as a plain summary sheet, not as a letter.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';
import { sheetLines } from '../js/realism-rules.js';
import { documentPage } from '../js/views/realism.js';

const item = {
  id: 'd-raeder-1', kind: 'memo', title: 'Your request: carried out late', author: 'Erich Raeder',
  issued: '1941-09-10', arrives: '1941-09-10', channel: 'in_person', classification: 'confidential',
  unread: true, flagged: false, group: null, ack: false,
};
const body = [
  { label: 'Ordered', value: 'Your request', unit: null },
  { label: 'Carried out', value: 'slow', unit: null },
  { label: 'Account', value: 'I have sent the U-boat arm', unit: null },
  { label: 'Account (cont.)', value: 'from Lorient to patrol those waters.', unit: null },
  { label: 'Escorts', value: null, unit: null },
];

test('a continued line joins the line it continues, and a line with no figure is left off', () => {
  assert.deepEqual(sheetLines(body), [
    { label: 'Ordered', value: 'Your request', unit: null },
    { label: 'Carried out', value: 'slow', unit: null },
    { label: 'Account', value: 'I have sent the U-boat arm from Lorient to patrol those waters.', unit: null },
  ]);
});

test('a continuation with no line before it keeps its own label', () => {
  assert.deepEqual(sheetLines([{ label: 'Answer (cont.)', value: 'in return.', unit: null }]),
    [{ label: 'Answer (cont.)', value: 'in return.', unit: null }]);
});

test('a page with no letter reads as a plain summary sheet', () => {
  installDom();
  const page = documentPage({ item, prose: null, body });
  const said = words(page);
  assert.match(said, /Summary sheet/);
  assert.match(said, /No covering letter came with this paper\./);
  assert.match(said, /I have sent the U-boat arm from Lorient to patrol those waters\./);
  assert.doesNotMatch(said, /\(cont\.\)/);
  assert.ok(page.querySelector('.rl-sheet'));
});

test('a page with a letter keeps its lines under it, joined, and is not called a sheet', () => {
  installDom();
  const page = documentPage({ item, prose: 'Mein Fuehrer,\n\nThe boats are sailing.', body });
  const said = words(page);
  assert.match(said, /The boats are sailing\./);
  assert.match(said, /Particulars/);
  assert.doesNotMatch(said, /Summary sheet|No covering letter|\(cont\.\)/);
  assert.equal(page.querySelector('.rl-sheet'), null);
});
