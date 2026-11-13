// The shared console parts (contract C6): pure builders through h(), tones as words.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
const kit = await import('../js/views/ui-kit.js');
const { TONES, alertBox, chip, panelHead, seg, stepper, tag, tile } = kit;

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const css = read('css/ui-kit.css').replace(/\/\*[\s\S]*?\*\//g, '');

test('tones are words, and an unknown tone reads as quiet', () => {
  assert.deepEqual([...TONES], ['ok', 'info', 'warn', 'danger', 'intel', 'quiet']);
  for (const t of TONES) assert.ok(chip('x', t).classList.contains(`tone-${t}`), t);
  assert.ok(chip('x', '#ff0000').classList.contains('tone-quiet'));
  assert.ok(tag('x', undefined).classList.contains('tone-quiet'));
});

test('panelHead: a title, a count badge only when given, and the extras after', () => {
  const extra = document.createElement('button');
  const head = panelHead('Papers', 3, [extra]);
  assert.ok(head.classList.contains('panel-head'));
  assert.equal(words(head.querySelector('h2')), 'Papers');
  assert.equal(words(head.querySelector('.badge')), '3');
  assert.equal(head.children.at(-1), extra);
  assert.equal(panelHead('Desk', null).querySelector('.badge'), null);
  assert.equal(words(panelHead('Desk', 0).querySelector('.badge')), '0');
});

test('tile: number, label and sub in words; a button only when it can be picked', () => {
  const picked = [];
  const t = tile(4, 'Unread', 'since yesterday', 'info', () => picked.push('unread'));
  assert.equal(t.tagName.toLowerCase(), 'button');
  assert.equal(t.getAttribute('type'), 'button');
  assert.ok(t.classList.contains('tile') && t.classList.contains('tone-info'));
  assert.equal(words(t.querySelector('.tile-n')), '4');
  assert.equal(words(t.querySelector('.tile-label')), 'Unread');
  assert.equal(words(t.querySelector('.tile-sub')), 'since yesterday');
  t.click();
  assert.deepEqual(picked, ['unread']);
  const still = tile(0, 'Threats', null, 'danger');
  assert.notEqual(still.tagName.toLowerCase(), 'button');
  assert.equal(still.querySelector('.tile-sub'), null);
});

test('chip and tag carry their word', () => {
  assert.equal(words(chip('Under way', 'info')), 'Under way');
  assert.ok(chip('a', 'ok').classList.contains('chip'));
  assert.equal(words(tag('Cable', 'intel')), 'Cable');
  assert.ok(tag('a', 'ok').classList.contains('tag'));
});

test('seg: one pressed option, a click names its key, counts in words', () => {
  const picked = [];
  const s = seg([{ key: 'all', label: 'All', count: 6 }, { key: 'unread', label: 'Unread', count: 2 }, { key: 'read', label: 'Read' }], 'unread', (k) => picked.push(k));
  assert.ok(s.classList.contains('seg'));
  assert.equal(s.getAttribute('role'), 'group');
  const all = s.querySelectorAll('button');
  assert.equal(all.length, 3);
  assert.deepEqual(all.map((b) => b.getAttribute('aria-pressed')), ['false', 'true', 'false']);
  assert.deepEqual(all.map((b) => b.getAttribute('type')), ['button', 'button', 'button']);
  assert.equal(words(all[0]), 'All 6');
  assert.equal(words(all[2]), 'Read');
  all[0].click();
  assert.deepEqual(picked, ['all']);
});

test('stepper: the order\'s real steps by person, done, here now and still to come', () => {
  const steps = [
    { step: 0, person: 'Franklin D. Roosevelt', kind: 'decision', action: 'pass', on: '1941-10-03' },
    { step: 1, person: 'Sam Rayburn', kind: 'decision', action: null, on: null },
    { step: 2, person: 'Cordell Hull', kind: 'clerical', action: null, on: null },
  ];
  const s = stepper(steps, 1);
  assert.ok(s.classList.contains('stepper'));
  const items = s.querySelectorAll('li');
  assert.equal(items.length, 3);
  assert.deepEqual(items.map((li) => ['done', 'now', 'next'].find((c) => li.classList.contains(c))), ['done', 'now', 'next']);
  assert.equal(items[1].getAttribute('aria-current'), 'step');
  assert.equal(items[0].getAttribute('aria-current'), null);
  assert.match(words(items[0]), /Franklin D\. Roosevelt/);
  assert.match(words(items[1]), /Sam Rayburn: has it now/);
  assert.match(words(items[2]), /Cordell Hull/);
  assert.match(words(items[2]), /to come/);
  assert.equal(stepper([], 0).querySelectorAll('li').length, 0);
});

test('alertBox: a named region with its title, body and actions', () => {
  const act = document.createElement('button');
  const a = alertBox('Crisis at Reykjavik', 'The convoy is under attack.', [act]);
  assert.ok(a.classList.contains('alert'));
  assert.equal(a.getAttribute('aria-label'), 'Crisis at Reykjavik');
  assert.match(words(a), /Crisis at Reykjavik/);
  assert.match(words(a), /The convoy is under attack\./);
  assert.ok(a.querySelector('.alert-acts').children.includes(act));
  assert.equal(alertBox('T', 'B').querySelector('.alert-acts'), null);
});

test('nothing in the kit touches the page on import or writes inline style', () => {
  const src = read('js/views/ui-kit.js');
  assert.doesNotMatch(src, /innerHTML|\.style\b|style:|document\.|window\.|localStorage/);
});

test('ui-kit.css: every part has its class, accents through --c, tokens only, 44 px on touch', () => {
  for (const cls of ['btn-1', 'btn-2', 'btn-3', 'panel', 'panel-head', 'badge', 'tag', 'chip', 'seg', 'tile', 'stepper', 'alert', 'lbl']) {
    assert.match(css, new RegExp(`\\.${cls}\\b(?![-\\w])`), cls);
  }
  for (const t of ['ok', 'info', 'warn', 'danger', 'intel', 'quiet']) assert.match(css, new RegExp(`\\.tone-${t}\\s*\\{[^}]*--c\\s*:`), t);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/);
  const coarse = /@media \(pointer: coarse\)\s*\{([\s\S]*?)\n\}/.exec(css);
  assert.ok(coarse, 'a coarse-pointer block');
  assert.match(coarse[1], /min-height:\s*44px/);
  assert.match(read('index.html'), /href="\/css\/ui-kit\.css"/);
  assert.ok(buttons, 'dom-fake loaded');
});
