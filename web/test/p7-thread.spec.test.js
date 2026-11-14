// Spec for wave M unit M2 (a thread), written with contract KM: the unit makes it pass and
// never edits it. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';
import { settleMarks, threadCounts, unread } from '../js/views/realism-chat.js';
import { groupItems, threadItems, threadView } from '../js/views/realism-thread.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const base = { counsel: fixture.counsel, documents: fixture.listing, help: fixture.help };

const item = (side, kind, text, iso, docId = null) => ({
  side, kind, text, day: `${Number(iso.slice(8))} October 1941`, iso, docId,
});

const HOPKINS = [
  item('mine', 'counsel', 'How much did we ship in September?', '1941-10-13'),
  item('theirs', 'counsel', 'Short of the promise by a third. My memo has the figures.', '1941-10-13'),
  item('theirs', 'letter', 'Letter received: Lend-Lease shipments, September tonnage', '1941-10-16', 'd-memo-1015'),
  item('mine', 'counsel', 'Will Moscow hold through the winter?', '1941-10-17'),
  item('theirs', 'counsel', 'Harriman thinks so, if the tanks arrive before the ports freeze.', '1941-10-17'),
];

test('a contact: questions and answers oldest first; a memo they wrote stays in the In-Tray', () => {
  assert.deepEqual(threadItems({ ...base, person: 'Harry Hopkins' }), [HOPKINS[0], HOPKINS[1], HOPKINS[3], HOPKINS[4]]);
});

const paper = (id, kind, title, arrives, extra = {}) => ({ id, kind, title, author: 'Harry Hopkins', arrives, ack: false, answer: false, ...extra });
const PAPERS = { documents: [
  paper('d-memo', 'memo', 'Shipping figures', '1941-10-14'),
  paper('d-report', 'report', 'Escorts in the North Atlantic', '1941-10-15'),
  paper('d-ack', 'letter', 'On your order: Send a bill to Congress', '1941-10-15', { ack: true }),
  paper('d-answer', 'memo', 'On your order: Speak to the Speaker', '1941-10-16', { answer: true }),
  paper('d-letter', 'letter', 'From Moscow, privately', '1941-10-16'),
] };
const COUNSEL = [
  { person: 'Harry Hopkins', question: 'Will Moscow hold?', answer: 'If the tanks arrive.', day: '17 October 1941', day_iso: '1941-10-17' },
  { person: 'Harry Hopkins', question: 'How much did we ship?', answer: 'A third short.', day: '13 October 1941', day_iso: '1941-10-13' },
];

test('a thread holds the conversation and one line for each letter; memos, reports, acknowledgements and answers stay out', () => {
  assert.deepEqual(threadItems({ person: 'Harry Hopkins', counsel: COUNSEL, documents: PAPERS }), [
    item('mine', 'counsel', 'How much did we ship?', '1941-10-13'),
    item('theirs', 'counsel', 'A third short.', '1941-10-13'),
    item('theirs', 'letter', 'Letter received: From Moscow, privately', '1941-10-16', 'd-letter'),
    item('mine', 'counsel', 'Will Moscow hold?', '1941-10-17'),
    item('theirs', 'counsel', 'If the tanks arrive.', '1941-10-17'),
  ]);
});

test('papers that acknowledge or answer an order, or report, are not in the thread', () => {
  assert.deepEqual(threadItems({ ...base, person: 'Sam Rayburn' }), []);
  assert.deepEqual(threadItems({ ...base, person: 'Admiral Ernest King' }), []);
  assert.deepEqual(threadItems({ ...base, person: 'Burton K. Wheeler' }), []);
});

test('the letter line opens the letter', () => {
  const items = threadItems({ person: 'Harry Hopkins', counsel: COUNSEL, documents: PAPERS });
  const { box, calls } = view({ items });
  const open = box.querySelectorAll('.rl-th-open');
  assert.equal(open.length, 1);
  assert.equal(words(open[0]), 'Letter received: From Moscow, privately');
  open[0].click();
  assert.deepEqual(calls.open, [{ id: 'd-letter' }]);
});

test('unread for a contact is their unread answers and letter lines; a mark kept from the papers settles down', () => {
  const threads = { 'Harry Hopkins': threadItems({ person: 'Harry Hopkins', counsel: COUNSEL, documents: PAPERS }) };
  const counts = threadCounts(threads);
  assert.deepEqual(counts, { 'Harry Hopkins': 3 });
  // Read when the thread still held every paper Hopkins wrote: 2 answers and 5 papers.
  const marks = settleMarks(counts, { 'Harry Hopkins': 7 });
  assert.deepEqual(marks, { 'Harry Hopkins': 3 });
  const counsel = [{ person: 'Harry Hopkins', question: 'And the ports?', answer: 'Open until December.', day: '18 October 1941', day_iso: '1941-10-18' }, ...COUNSEL];
  const next = threadCounts({ 'Harry Hopkins': threadItems({ person: 'Harry Hopkins', counsel, documents: PAPERS }) });
  assert.deepEqual(unread(next, marks), { total: 1, fresh: ['Harry Hopkins'] });
});

test('on one day, the papers that arrived come before a consult held that day', () => {
  // Papers arrive when the wake opens; the seat consults after reading them.
  const counsel = [{ person: 'Harry Hopkins', channel: 'telephone', question: 'Is the memo right?', answer: 'It is.', day: '16 October 1941', day_iso: '1941-10-16', tie: 'inner' }];
  const documents = { documents: [{ id: 'd-letter-1016', kind: 'letter', author: 'Harry Hopkins', title: 'Lend-Lease shipments, September tonnage', arrives: '1941-10-16' }] };
  assert.deepEqual(threadItems({ counsel, documents, person: 'Harry Hopkins' }).map((i) => i.kind), ['letter', 'counsel', 'counsel']);
});

test('an answer with no question on record shows the answer alone', () => {
  const counsel = [{ ...fixture.counsel[3], question: '' }];
  assert.deepEqual(threadItems({ counsel, documents: { documents: [] }, person: 'Harry Hopkins' }), [HOPKINS[1]]);
});

test('the aide: the help lines in order, a form offered where there is one', () => {
  const out = threadItems({ ...base, person: 'aide' });
  assert.deepEqual(out, [
    item('mine', 'help', 'How do I get a bill to the floor?', '1941-10-14'),
    { ...item('theirs', 'help', 'Through the Speaker: Sam Rayburn schedules it. The bill form does it.', '1941-10-14'), lever: 'send_bill', label: 'Send a bill to Congress' },
    item('theirs', 'help', 'Your order to Wheeler did not go through: he would not take it while the rallies go on.', '1941-10-16'),
  ]);
  assert.deepEqual(threadItems({ person: 'aide' }), []);
});

test('consecutive lines from one side make a group, labelled with its last day', () => {
  assert.deepEqual(groupItems(HOPKINS), [
    { side: 'mine', day: '13 October 1941', items: [HOPKINS[0]] },
    { side: 'theirs', day: '16 October 1941', items: [HOPKINS[1], HOPKINS[2]] },
    { side: 'mine', day: '17 October 1941', items: [HOPKINS[3]] },
    { side: 'theirs', day: '17 October 1941', items: [HOPKINS[4]] },
  ]);
  assert.deepEqual(groupItems([]), []);
});

function view(over = {}) {
  installDom();
  const calls = { send: [], back: 0, open: [], draft: [], type: [] };
  const out = threadView({
    name: 'Harry Hopkins', title: 'Special Assistant to the President', tie: 'inner', dossier: null,
    lead: null, items: HOPKINS, pending: null, draft: '', typing: null,
    onSend: (t) => calls.send.push(t), onBack: () => { calls.back += 1; },
    onOpen: (d) => calls.open.push(d), onDraft: (d) => calls.draft.push(d),
    onType: (t) => calls.type.push(t),
    ...over,
  });
  assert.ok(Array.isArray(out) && out.length, 'an array of nodes');
  const box = document.createElement('div');
  box.append(...out);
  return { box, calls };
}

test('the header: portrait or monogram, name, office, and Back', () => {
  const { box, calls } = view();
  const head = box.querySelector('.rl-th-head');
  assert.ok(head);
  assert.ok(head.querySelector('.portrait-mono'), 'a monogram with no portrait');
  assert.match(words(head), /Harry Hopkins/);
  assert.match(words(head), /Special Assistant to the President/);
  box.querySelector('.rl-th-back').click();
  assert.equal(calls.back, 1);
  assert.doesNotMatch(words(box), /changes nothing in the world/);
});

test('someone outside the inner circle: the thread says what a message is', () => {
  const { box } = view({ name: 'Harold R. Stark', title: 'Chief of Naval Operations', tie: 'outer', items: [] });
  assert.match(words(box), /A message changes nothing in the world and files no order\./);
});

test('bubbles by side, grouped, a day under each group; papers open from the thread', () => {
  const { box, calls } = view();
  const bubbles = box.querySelectorAll('.rl-th-bubble');
  assert.equal(bubbles.length, 5);
  assert.deepEqual(bubbles.map((b) => (b.classList.contains('mine') ? 'mine' : 'theirs')), ['mine', 'theirs', 'theirs', 'mine', 'theirs']);
  const groups = box.querySelectorAll('.rl-th-group');
  assert.equal(groups.length, 4);
  assert.deepEqual(groups.map((g) => words(g.querySelector('.rl-th-day'))), ['13 October 1941', '16 October 1941', '17 October 1941', '17 October 1941']);
  const letter = bubbles[2].querySelector('button');
  assert.ok(letter, 'a paper opens from its line');
  letter.click();
  assert.deepEqual(calls.open, [{ id: 'd-memo-1015' }]);
});

test('an aide line with a form offers it; the lead sits above the lines', () => {
  installDom();
  const lead = document.createElement('div');
  lead.className = 'rl-brief-slot';
  const items = threadItems({ ...base, person: 'aide' });
  const { box, calls } = view({ name: 'Your aide', title: null, items, lead });
  assert.ok(box.querySelector('.rl-brief-slot'));
  const offer = box.querySelectorAll('button').find((b) => words(b) === 'Open “Send a bill to Congress”');
  assert.ok(offer);
  offer.click();
  assert.deepEqual(calls.draft, [{ lever: 'send_bill' }]);
});

test('the lead scrolls with the lines, so a long brief never pushes the composer out of the dock', () => {
  installDom();
  const lead = document.createElement('div');
  lead.className = 'rl-brief-slot';
  const { box } = view({ name: 'Your aide', title: null, items: threadItems({ ...base, person: 'aide' }), lead });
  const th = box.querySelector('.rl-th');
  assert.equal(box.querySelector('.rl-brief-slot').parentNode, th);
  assert.equal(th.children[0].className, 'rl-brief-slot');
});

test('a message going out: shown as sent, the other side writing, the composer held', () => {
  installDom();
  const typing = document.createElement('div');
  typing.className = 'rl-typing';
  const { box } = view({ pending: { thread: 'Harry Hopkins', text: 'And the tanks?' }, typing });
  const mine = box.querySelectorAll('.rl-th-bubble.mine');
  assert.equal(words(mine[mine.length - 1]), 'And the tanks?');
  assert.ok(box.querySelector('.rl-typing'));
  const form = box.querySelector('.rl-th-compose');
  // Held, not disabled: a disabled field drops focus to the page, and Esc stops closing the dock.
  const ta = form.querySelector('textarea');
  assert.equal(ta.disabled, false);
  assert.equal(ta.readOnly, true);
  assert.equal(ta.getAttribute('aria-disabled'), 'true');
  assert.equal(form.querySelector('button').disabled, true);
});

test('the words being typed go to the room as they are typed, so a redraw keeps them', () => {
  const { box, calls } = view();
  const ta = box.querySelector('.rl-th-compose textarea');
  ta.value = 'Will the tan';
  ta.dispatchEvent({ type: 'input', stopPropagation() {} });
  assert.deepEqual(calls.type, ['Will the tan']);
});

test('Enter while an input method is composing does not send', () => {
  const { box, calls } = view();
  const ta = box.querySelector('.rl-th-compose textarea');
  ta.value = '戦車';
  ta.dispatchEvent({ type: 'keydown', key: 'Enter', shiftKey: false, isComposing: true, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} });
  assert.deepEqual(calls.send, []);
});

test('the composer: the draft kept, Enter sends, Shift+Enter does not, and submit sends', () => {
  const { box, calls } = view({ draft: 'Will the' });
  const form = box.querySelector('.rl-th-compose');
  const ta = form.querySelector('textarea');
  assert.equal(ta.value, 'Will the');
  assert.equal(ta.disabled, false);
  const key = (shiftKey) => ({ type: 'keydown', key: 'Enter', shiftKey, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} });
  ta.value = 'Will the tanks go?';
  const shifted = key(true);
  ta.dispatchEvent(shifted);
  assert.deepEqual(calls.send, []);
  assert.equal(shifted.defaultPrevented, false);
  const plain = key(false);
  ta.dispatchEvent(plain);
  assert.deepEqual(calls.send, ['Will the tanks go?']);
  assert.equal(plain.defaultPrevented, true);
  ta.value = '   ';
  ta.dispatchEvent(key(false));
  assert.equal(calls.send.length, 1, 'blank text is not sent');
  ta.value = 'By convoy?';
  const submit = { type: 'submit', defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} };
  form.dispatchEvent(submit);
  assert.equal(submit.defaultPrevented, true);
  assert.deepEqual(calls.send, ['Will the tanks go?', 'By convoy?']);
});

test('bubbles are rounded and coloured from the tokens, and fit a phone', () => {
  const css = read('css/p5-thread.css');
  assert.doesNotMatch(css, /contract stub/);
  assert.match(css, /\.rl-th-bubble\s*\{[^}]*border-radius/);
  assert.match(css, /\.rl-th-bubble\.mine\s*\{[^}]*var\(--accent/);
  assert.match(css, /\.rl-th-compose\s*\{/);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b/);
  assert.doesNotMatch(read('js/views/realism-thread.js'), /innerHTML|setTimeout|\.style\./);
});
