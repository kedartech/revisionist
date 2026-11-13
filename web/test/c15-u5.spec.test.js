// Spec for 15a unit U5 (desk), written with the console contract: the unit makes it pass and
// never edits it. Ideas are cards under a kit panel head with one primary button each; the
// standard forms and the directive composer sit on the console grounds.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';

installDom();
const { ideasPanel } = await import('../js/views/realism-ideas.js');
const { standardForms } = await import('../js/views/realism-forms.js');

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const OWNS = ['css/p4-desk.css', 'css/p5-ideas.css', 'css/p5-forms.css', 'js/views/realism-ideas.js', 'js/views/realism-forms.js'];
const brief = { drafts: [{ label: 'Ask Hull for the Tokyo cables', terms: ['To: Cordell Hull'], lever: 'consult' }] };
const panel = () => ideasPanel({ ...fixture.agenda, style: 'beginner' }, brief, { act: () => {}, useDraft: () => {} });
/** The body of every rule whose selector list names `sel` exactly. */
const rule = (css, sel) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
  .filter((m) => m[1].split(',').some((s) => s.trim() === sel)).map((m) => m[2]).join(';');

test('the ideas sit under a kit panel head', () => {
  const p = panel();
  assert.ok(p, 'an ideas panel');
  const head = p.querySelector('.panel-head');
  assert.ok(head, 'a .panel-head');
  assert.equal(words(head.querySelector('h2')), 'Ideas');
});

test('each idea card has one primary button, and a filed one says so in words', () => {
  const rows = panel().querySelectorAll('.rl-idea-row');
  assert.ok(rows.length >= 2, 'an option and a draft');
  for (const row of rows) {
    const btns = row.querySelectorAll('button');
    if (!btns.length) {
      assert.match(words(row), /Filed/);
      continue;
    }
    assert.equal(btns.length, 1, words(row));
    assert.ok(btns[0].classList.contains('btn-1'), `${words(btns[0])}: a .btn-1`);
  }
});

test('idea cards, forms and the composer sit on the console grounds', () => {
  const ideas = uncomment(read('css/p5-ideas.css'));
  const card = rule(ideas, '.rl-idea-row');
  assert.match(card, /background:\s*var\(--surface-2\)/);
  assert.match(card, /border:\s*1px solid var\(--rule\)/);
  assert.match(card, /border-radius:\s*var\(--radius\)/);
  const desk = uncomment(read('css/p4-desk.css'));
  assert.match(rule(desk, '.rl-instrument'), /background:\s*var\(--surface-2\)/);
  assert.match(desk, /\.rl-write textarea\s*\{[^}]*border:\s*1px solid var\(--field-border\)/, 'the composer field');
  const forms = uncomment(read('css/p5-forms.css'));
  assert.match(forms, /\.rl-forms > summary\s*\{[^}]*var\(--font-chrome\)/, 'the forms fold reads as a label');
});

test('the standard forms still fold, one per lever', () => {
  const f = standardForms(fixture.desk, { onSubmit: () => {}, entities: [] });
  assert.equal(f.tagName.toLowerCase(), 'details');
  assert.equal(f.querySelectorAll('.rl-instrument').length, fixture.desk.levers.length);
});

test('owned files: no HTML parsing, no inline style, no colour literal', () => {
  for (const f of OWNS) {
    const src = uncomment(read(f));
    assert.doesNotMatch(src, /innerHTML|style=|\.style\./, f);
    if (f.endsWith('.css')) assert.doesNotMatch(src, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, f);
  }
});
