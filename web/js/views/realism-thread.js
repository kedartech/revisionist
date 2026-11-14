// One conversation in the messenger: the items in order, grouped by side, as text-message
// bubbles with a composer at the foot.

import { h } from '../dom.js';
import { worldDate } from '../rules.js';
import { portraitNode } from './realism-dossier.js';

/**
 * The thread's items, oldest first, each `{ side, kind, text, day, iso, docId, lever, label }`:
 * `side` 'mine' or 'theirs'; `kind` 'counsel', 'reply', 'letter' or 'help'; `day` the in-world
 * date in words and `iso` the same date as YYYY-MM-DD (both '' when unknown); `docId` the paper
 * an item opens, else null; `lever` and `label` only on an aide line that offers a form.
 * `person` 'aide' reads `help`; any other name reads `counsel` (their answers and the seat's
 * questions) and the papers in `documents` (a listing) that they wrote.
 */
export function threadItems({ person, counsel, documents, help } = {}) {
  const items = person === 'aide' ? aideItems(help) : contactItems(person, counsel, documents);
  return items.map((it, i) => ({ it, i })).sort((a, b) => compare(a.it.iso, b.it.iso) || a.i - b.i).map(({ it }) => it);
}

function aideItems(help) {
  return (help ?? []).map((line) => {
    const item = {
      side: line.from === 'you' ? 'mine' : 'theirs',
      kind: 'help',
      text: line.text,
      day: worldDate(line.on),
      iso: line.on ?? '',
      docId: null,
    };
    if (line.lever) {
      item.lever = line.lever;
      item.label = line.label ?? line.lever;
    }
    return item;
  });
}

function contactItems(person, counsel, documents) {
  const out = [];
  // Papers first: on one day they arrive when the wake opens, before any consult.
  for (const d of (documents?.documents ?? []).filter((d) => d.author === person)) {
    const reply = d.ack || d.answer;
    out.push({
      side: 'theirs',
      kind: reply ? 'reply' : 'letter',
      text: reply ? d.title : `Letter received: ${d.title}`,
      day: worldDate(d.arrives),
      iso: d.arrives ?? '',
      docId: d.id,
    });
  }
  const lines = (counsel ?? []).filter((c) => c.person === person).reverse();
  for (const c of lines) {
    if (c.question?.trim()) out.push({ side: 'mine', kind: 'counsel', text: c.question, day: c.day ?? '', iso: c.day_iso ?? '', docId: null });
    out.push({ side: 'theirs', kind: 'counsel', text: c.answer, day: c.day ?? '', iso: c.day_iso ?? '', docId: null });
  }
  return out;
}

function compare(a, b) {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** Consecutive items from one side as `{ side, day, items }`, `day` that of the group's last item. */
export function groupItems(items) {
  const groups = [];
  for (const item of items ?? []) {
    const last = groups.at(-1);
    if (last && last.side === item.side) last.items.push(item);
    else groups.push({ side: item.side, day: item.day, items: [item] });
  }
  for (const g of groups) g.day = g.items.at(-1).day;
  return groups;
}

/** How far above the foot (px) a reader still counts as reading the newest message. */
export const FOLLOW_SLACK = 24;

/**
 * Where the thread scrolls after a redraw. `prev` is the saved box `{ thread, top, height,
 * client }` (scrollTop, scrollHeight, clientHeight), null when none was saved; `next` the new
 * box. A reader at the foot (within FOLLOW_SLACK), or one opening the thread, goes to the new
 * foot; a reader who scrolled back keeps the offset.
 */
export function followNew(prev, next) {
  const foot = Math.max(0, next.height - next.client);
  if (!prev || prev.thread !== next.thread) return foot;
  if (prev.height - prev.client - prev.top <= FOLLOW_SLACK) return foot;
  return Math.min(prev.top, foot);
}

/**
 * Scroll a freshly drawn `.rl-th` (null when no thread is drawn) to the place `chat.scroll`
 * holds, and keep `chat.scroll` current as the reader scrolls. With no thread drawn the place
 * is dropped, so the next open lands at the newest message.
 */
export function followThread(chat, el) {
  if (!el) {
    chat.scroll = null;
    return;
  }
  const box = () => ({ thread: chat.thread, top: el.scrollTop, height: el.scrollHeight, client: el.clientHeight });
  el.scrollTop = followNew(chat.scroll, box());
  // the scroll event of a set scrollTop can land after a redraw has replaced this element
  el.addEventListener('scroll', () => { if (el.isConnected) chat.scroll = box(); });
}

/**
 * The open thread: `{ name, title, tie, dossier, lead, items, pending, draft, typing, onSend,
 * onBack, onOpen, onDraft, onType }`, as an array of nodes for the panel. `onType(text)` hears
 * every keystroke so the room keeps the draft across a redraw. While a message is out the
 * field is read-only, not disabled, so focus (and Esc) stay in the dock.
 */
export function threadView({ name, title, tie, dossier, lead, items, pending, draft, typing, onSend, onBack, onOpen, onDraft, onType }) {
  const head = h('div', { class: 'rl-th-head' },
    h('button', { type: 'button', class: 'rl-th-back', onclick: () => onBack?.() }, 'Back'),
    portraitNode(name, dossier, 'rl-th'),
    h('div', { class: 'rl-th-who' },
      h('span', { class: 'rl-th-name' }, name),
      title ? h('span', { class: 'rl-th-title' }, title) : null));

  const groups = groupItems(items).map((g) => h('div', { class: `rl-th-group ${g.side}` },
    g.items.map((item) => bubble(item.side, item, onOpen, onDraft)),
    h('div', { class: 'rl-th-day' }, g.day)));
  if (pending) groups.push(h('div', { class: 'rl-th-group mine' }, bubble('mine', { text: pending.text }, onOpen, onDraft)));

  // The lead (the aide's brief) scrolls with the lines, so the composer stays in the dock.
  const thread = h('div', { class: 'rl-th' }, lead ?? null, groups, typing ?? null);

  const send = (text) => {
    const t = String(text ?? '').trim();
    if (t) onSend?.(t);
  };
  const ta = h('textarea', { class: 'rl-th-input', rows: 1, 'aria-label': 'Message', value: draft ?? '', 'aria-disabled': pending ? 'true' : null });
  ta.readOnly = Boolean(pending);
  ta.addEventListener('input', () => onType?.(ta.value));
  ta.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || e.shiftKey || e.isComposing || ta.readOnly) return;
    e.preventDefault();
    send(ta.value);
  });
  const compose = h('form', {
    class: 'rl-th-compose',
    onsubmit: (e) => {
      e.preventDefault();
      send(ta.value);
    },
  }, ta, h('button', { type: 'submit', class: 'rl-th-send', disabled: Boolean(pending) }, 'Send'));

  return [
    head,
    tie === 'outer' ? h('p', { class: 'rl-th-tie' }, 'A message changes nothing in the world and files no order.') : null,
    thread,
    compose,
  ];
}

function bubble(side, item, onOpen, onDraft) {
  const body = item.docId
    ? h('button', { type: 'button', class: 'rl-th-open', onclick: () => onOpen?.({ id: item.docId }) }, item.text)
    : item.text;
  return h('div', { class: `rl-th-bubble ${side}` },
    body,
    item.lever ? h('button', { type: 'button', class: 'rl-th-offer', onclick: () => onDraft?.({ lever: item.lever }) }, `Open “${item.label}”`) : null);
}
