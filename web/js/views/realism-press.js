// The press desk: a newspaper icon beside Messages with the unread count, and a modal with one
// tab per paper (outlet), its pages newest first. A page opens as the paper view does in the
// tray. The press is not In-Tray, so the tray leaves it out. Unread follows the messenger: a
// mark per paper of the pages seen, kept in this browser. After the papers, "The world": the
// public developments that have fired, each with the orders it suggests (DV2).

import { h, svg } from '../dom.js';
import { worldDate } from '../rules.js';
import { SEEN_PREFIX, seenStore, settleMarks, unread } from './realism-chat.js';
import { dossier } from './realism.js';

export const PRESS_SEEN_PREFIX = `${SEEN_PREFIX}press.`;

/** The tab value of "The world"; no paper is named so. */
export const WORLD_TAB = '#world';

/** The press marks for `campaignId`: the messenger's store under its own key. */
export function pressSeen(storage, campaignId) {
  return seenStore(storage, `press.${campaignId}`);
}

/** `[{ outlet, pages }]`: one entry per paper, by name; each paper's pages newest first. */
export function pressPapers(documents) {
  const by = new Map();
  for (const d of documents ?? []) {
    if (d.kind !== 'press') continue;
    if (!by.has(d.author)) by.set(d.author, []);
    by.get(d.author).push(d);
  }
  const newest = (a, b) => b.arrives.localeCompare(a.arrives) || b.issued.localeCompare(a.issued) || b.id.localeCompare(a.id);
  return [...by.keys()].sort((a, b) => a.localeCompare(b))
    .map((outlet) => ({ outlet, pages: by.get(outlet).slice().sort(newest) }));
}

/** Pages per paper, the counts the marks are kept against. */
export function pressCounts(papers) {
  return Object.fromEntries(papers.map((p) => [p.outlet, p.pages.length]));
}

/** Pages newer than the marks, over every paper. */
export function pressUnread(papers, marks) {
  return unread(pressCounts(papers), marks).total;
}

/**
 * The tab on show: "The world" when picked and `world` (the server sends it), else `picked` while
 * that paper is there, else the first paper; null with no paper.
 */
export function pressTab(papers, picked, world = false) {
  if (world && picked === WORLD_TAB) return WORLD_TAB;
  return papers.some((p) => p.outlet === picked) ? picked : papers[0]?.outlet ?? null;
}

/** The marks after a draw: settled to the counts, and the paper on show, while the desk is open, seen. */
export function pressMarks(counts, marks, state) {
  const settled = settleMarks(counts, marks ?? {});
  const tab = state.open ? state.tab : null;
  if (!tab || !(tab in counts) || settled[tab] === counts[tab]) return settled;
  return { ...settled, [tab]: counts[tab] };
}

/** Put focus on the newspaper icon (the desk has closed and the room redrawn). */
export function pressFocus(root) {
  root.querySelector('.rl-press-btn')?.focus();
}

function paperIcon() {
  return svg('svg', {
    width: 20, height: 20, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 2,
    'aria-hidden': 'true', focusable: 'false',
  },
  svg('path', { d: 'M4 5h13v13a2 2 0 0 0 2 2H6a2 2 0 0 1-2-2z' }),
  svg('path', { d: 'M17 9h3v9a2 2 0 0 1-2 2' }),
  svg('path', { d: 'M7 9h7M7 13h7M7 16h4' }));
}

function launcher(state, total, onState) {
  const count = total > 0
    ? h('span', { class: 'rl-press-count' }, String(total), h('span', { class: 'sr-only' }, ' unread'))
    : null;
  return h('button', {
    type: 'button', class: 'rl-press-btn', 'aria-expanded': String(Boolean(state.open)), 'aria-haspopup': 'dialog',
    onclick: () => onState({ ...state, open: !state.open }),
  }, paperIcon(), h('span', { class: 'sr-only' }, 'Newspapers'), count);
}

function pageRow(d, onOpen) {
  return h('li', {},
    h('button', {
      type: 'button', class: `rl-row rl-row-paper${d.unread ? ' unread' : ''}`, onclick: () => onOpen?.(d),
    },
    h('span', { class: 'rl-row-main' }, h('span', { class: 'rl-row-title' }, d.title)),
    d.unread ? h('span', { class: 'rl-row-unread' }, 'Unread') : null,
    h('span', { class: 'rl-row-date' }, worldDate(d.arrives))));
}

function askRow(text, onAsk) {
  return h('li', {},
    h('span', { class: 'rl-world-ask' }, text),
    onAsk
      ? h('button', {
        type: 'button', class: 'rl-btn', 'aria-label': `Write it as an order: ${text}`, onclick: () => onAsk(text),
      }, 'Write it as an order')
      : null);
}

/** The public developments, newest first; each ask hands its words to `onAsk`. */
function worldList(world, onAsk) {
  if (!world.length) return h('p', { class: 'rl-none' }, 'Nothing in the world has made the news yet.');
  const newest = world.slice().sort((a, b) => b.on.localeCompare(a.on) || b.id.localeCompare(a.id));
  return h('ul', { class: 'rl-rows rl-pd-world', 'aria-label': 'The world' },
    newest.map((d) => h('li', { class: 'rl-world-item' },
      h('p', { class: 'rl-world-meta' }, `${worldDate(d.on)} · ${d.category}`),
      h('h3', { class: 'rl-world-head' }, d.headline),
      d.asks.length ? h('ul', { class: 'rl-world-asks', 'aria-label': 'It suggests' }, d.asks.map((a) => askRow(a, onAsk))) : null)));
}

function desk(opts, tab) {
  const { state, onState, papers, marks } = opts;
  const paper = papers.find((p) => p.outlet === tab);
  const world = Array.isArray(opts.world) ? opts.world : null;
  const onWorld = world !== null && tab === WORLD_TAB;
  const fresh = (p) => Math.max(0, p.pages.length - (marks?.[p.outlet] ?? 0));
  const worldTab = world !== null
    ? h('button', {
      type: 'button', role: 'tab', 'aria-selected': String(onWorld), onclick: () => onState({ ...state, tab: WORLD_TAB }),
    }, 'The world')
    : null;
  const tabs = papers.length || worldTab
    ? h('div', { class: 'seg rl-pd-tabs', role: 'tablist', 'aria-label': 'Papers' },
      papers.map((p) => h('button', {
        type: 'button', role: 'tab', 'aria-selected': String(p.outlet === tab),
        onclick: () => onState({ ...state, tab: p.outlet }),
      }, p.outlet, fresh(p) && p.outlet !== tab ? h('span', { class: 'n' }, ` ${fresh(p)}`) : null)),
      worldTab)
    : null;
  let body;
  if (opts.page) body = dossier(opts.page, { onClose: opts.onClosePage, onFlag: opts.onFlag });
  else if (onWorld) body = worldList(world, opts.onAsk);
  else if (paper) body = h('ul', { class: 'rl-rows rl-pd-list', 'aria-label': paper.outlet }, paper.pages.map((d) => pageRow(d, opts.onOpen)));
  else body = h('p', { class: 'rl-none' }, 'No paper has reached you yet.');

  const dialog = h('dialog', {
    class: 'rl-pd', 'aria-labelledby': 'rl-pd-title',
    onkeydown: (e) => {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      dialog.close();
    },
    // a redraw removes the open desk from the page; only a close the reader made shuts it
    onclose: () => { if (dialog.isConnected) onState({ ...state, open: false }); },
  },
  h('div', { class: 'rl-pd-head' },
    h('h2', { id: 'rl-pd-title' }, 'Newspapers'),
    h('button', { type: 'button', class: 'rl-btn rl-pd-close', onclick: () => dialog.close() }, 'Close')),
  tabs,
  h('div', {
    class: 'rl-pd-body', role: paper || onWorld ? 'tabpanel' : null, 'aria-label': onWorld ? 'The world' : paper?.outlet ?? null,
  }, body));
  return dialog;
}

/**
 * The icon and, while `state.open`, the desk. `opts`: `{ state, onState(next), papers, marks,
 * page, onOpen(doc), onClosePage(), onFlag(on), world, onAsk(text) }`; `state` is `{ open, tab }`,
 * kept by the room; `page` is the open page (as the tray's reading pane holds it) or null;
 * `world` is the server's list of developments (no tab when absent).
 */
export function pressDock(opts) {
  const { state, onState, papers, marks } = opts;
  const tab = pressTab(papers, state.tab, Array.isArray(opts.world));
  return h('div', { class: 'rl-press' },
    launcher(state, pressUnread(papers, marks), onState),
    state.open ? desk(opts, tab) : null);
}
