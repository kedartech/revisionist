// The Board view, the room's first view: a Theatre or Court switch, the chosen board, and to
// its right the selected piece's panel above the order form; on a phone a picked piece's panel
// is a sheet from the bottom (c-board.css). The Desk view is the room's columns
// (realism-room.js); one switch picks between the two. Nothing here touches the page on import.

import { h } from '../dom.js';
import { certaintyWord, markKindWord, sideLine, sightedLine, whereLine } from '../realism-rules.js';
import { courtBoard } from './realism-court.js';
import { theatreBoard } from './realism-theatre.js';

const VIEWS = [['board', 'Board'], ['desk', 'Desk']];
const BOARDS = [['theatre', 'Theatre'], ['court', 'Court']];

function pressGroup(cls, label, options, current, on) {
  return h('div', { class: cls, role: 'group', 'aria-label': label },
    ...options.map(([value, word]) => h('button', {
      type: 'button',
      class: 'rl-btn',
      'aria-pressed': current === value ? 'true' : 'false',
      onclick: () => on(value),
    }, word)));
}

/** `viewSwitch(ui, pick)`: Board or Desk, pressed by `ui.view`; a click calls `pick({ view })`. */
export function viewSwitch(ui, pick) {
  return pressGroup('rl-viewswitch', 'View', VIEWS, ui.view, (view) => pick({ view }));
}

/**
 * `withBoard(bar, ui, pick)`: the phone's tab bar with a Board tab first. On the Board view
 * that tab is the open one (unless the messenger is) and the desk's panel tabs are not; a tap
 * calls `pick({ tab: 'board' })`.
 */
export function withBoard(bar, ui, pick) {
  const onBoard = ui.view === 'board' && ui.tab !== 'messages';
  if (ui.view === 'board') {
    for (const b of bar.querySelectorAll('button')) if (!words(b).startsWith('Messages')) b.removeAttribute('aria-current');
  }
  bar.classList.add('rl-tabbar-board');
  bar.prepend(h('button', {
    type: 'button',
    class: 'rl-tab',
    'aria-current': onBoard ? 'page' : null,
    onclick: () => pick({ tab: 'board' }),
  }, 'Board'));
  return bar;
}

const words = (el) => el.textContent.trim();

/** The mark a selected force names on the seat's map, or null once the map no longer holds it. */
function selectedMark(rv, piece) {
  if (piece?.kind !== 'force') return null;
  return (rv.map?.marks ?? []).find((m) => m.name === piece.name) ?? null;
}

const NOTHING = {
  theatre: 'Nothing is selected. Pick a force on the map to see it here.',
  court: 'Nothing is selected. Pick a person on the court to see their card here.',
};

/** What can be picked on either board: a force's mark, a person's square or chip. */
const PICKABLE = '.rl-board-main .rl-mk, .rl-board-main .rl-court-sq, .rl-board-main .rl-court-chip';

/** Close drops the pick, then puts focus back on what was picked, so a keyboard keeps its place. */
function closePick(pick) {
  const all = () => [...(document.body?.querySelectorAll(PICKABLE) ?? [])];
  const at = all().findIndex((el) => el.getAttribute('aria-pressed') === 'true');
  pick?.({ piece: null });
  if (at >= 0) all()[at]?.focus?.();
}

/** A picked piece's panel, with a Close that drops the pick (shown on a phone, where it is a sheet). */
function sheet(attrs, pick, ...body) {
  return h('section', { class: 'rl-piece rl-sheet', ...attrs },
    h('button', { type: 'button', class: 'rl-btn rl-sheet-close', onclick: () => closePick(pick) }, 'Close'),
    ...body);
}

/**
 * The selected piece's panel: what it is and where, or how to pick one on `board`; `open` opens
 * its page. `card` is a picked person's card from the Court, shown in place of a force.
 */
export function piecePanel(rv, piece, open, { board = 'theatre', card = null, pick } = {}) {
  if (card) return sheet({ 'aria-label': 'Selected' }, pick, card);
  const mark = selectedMark(rv, piece);
  if (!mark) {
    return h('section', { class: 'rl-piece', 'aria-label': 'Selected' },
      h('p', { class: 'muted' }, NOTHING[board] ?? NOTHING.theatre));
  }
  return sheet({ 'aria-labelledby': 'rl-piece-h' }, pick,
    h('h2', { id: 'rl-piece-h' }, mark.name),
    h('dl', {},
      h('dt', {}, 'What'), h('dd', {}, markKindWord(mark.kind)),
      h('dt', {}, 'Side'), h('dd', {}, sideLine(mark)),
      h('dt', {}, 'Certainty'), h('dd', {}, certaintyWord(mark.certainty)),
      h('dt', {}, 'Where'), h('dd', {}, whereLine(mark))),
    h('p', { class: 'muted' }, sightedLine(mark)),
    mark.document
      ? h('button', { type: 'button', class: 'rl-btn', onclick: () => open?.({ id: mark.document }) }, 'Open the page')
      : null);
}

/**
 * The Court draws a picked person's card in its own column; the Board takes it out for the side
 * panel, and drops that column when the card was all it held. Null when no one is picked.
 */
function liftCard(court) {
  const card = court.querySelector('.rl-court-sel');
  if (!card) return null;
  const column = card.parentNode;
  card.remove();
  if (column?.classList.contains('rl-court-aside') && !column.children.length) {
    column.parentNode?.classList.add('single');
    column.remove();
  }
  return card;
}

/**
 * `boardView(rv, ui, { pick, act, write, open })`: the Board. `ui.board` picks Theatre or Court
 * (`pick({ board })`); `ui.piece` is the selected piece; `write` is the room's order form;
 * `open({ id })` opens a paper.
 */
export function boardView(rv, ui, { pick, act, write, open }) {
  const which = ui.board === 'court' ? 'court' : 'theatre';
  const board = which === 'court'
    ? courtBoard(rv, ui, { pick, act })
    : theatreBoard(rv, ui, { pick, act });
  const card = which === 'court' ? liftCard(board) : null;
  return h('main', { class: 'rl-board', 'data-board': which },
    h('section', { class: 'rl-board-main', 'aria-label': 'Board' },
      pressGroup('rl-boardswitch', 'Board', BOARDS, which, (b) => pick({ board: b })),
      board),
    h('aside', { class: 'rl-board-side', 'aria-label': 'Selected piece and order' },
      piecePanel(rv, ui.piece, open, { board: which, card, pick }),
      write));
}
