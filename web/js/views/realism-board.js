// The Board view, the room's first view: a Theatre or Court switch, the chosen board, and to
// its right the selected piece's panel above the order form; on a phone a picked piece's panel
// is a sheet from the bottom (c-board.css). The Desk view is the room's columns
// (realism-room.js); one switch picks between the two. Nothing here touches the page on import.

import { h } from '../dom.js';
import { aimList } from './realism-stakes.js';
import { aimsBlock, certaintyWord, markWhatWord, sideLine, sightedLine, whereLine } from '../realism-rules.js';
import { courtBoard } from './realism-court.js';
import { contingencyPicker } from './realism-battle.js';
import { concealSwitch } from './realism-reports.js';
import { moveOrder, pieceMoves, theatreBoard } from './realism-theatre.js';
import { daysLabel } from './realism-forms.js';
import { heldOn, heldStatus, isLocked, lockCheck, lockTag, locksOn } from './realism-locks.js';

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December'];
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
 * its page. `card` is a picked person's card from the Court, shown in place of a force. An own
 * piece's sheet holds its contingency picker; `theatre` is the map's state, where a fall-back
 * area being picked is kept.
 */
export function piecePanel(rv, piece, open, { board = 'theatre', card = null, pick, act, theatre = {} } = {}) {
  if (card) return sheet({ 'aria-label': 'Selected' }, pick, card);
  const mark = selectedMark(rv, piece);
  if (!mark) {
    return h('section', { class: 'rl-piece', 'aria-label': 'Selected' },
      h('p', { class: 'muted' }, NOTHING[board] ?? NOTHING.theatre));
  }
  return sheet({ 'aria-labelledby': 'rl-piece-h' }, pick,
    h('h2', { id: 'rl-piece-h' }, mark.name),
    h('dl', {},
      h('dt', {}, 'What'), h('dd', {}, markWhatWord(mark)),
      h('dt', {}, 'Side'), h('dd', {}, sideLine(mark)),
      h('dt', {}, 'Certainty'), h('dd', {}, certaintyWord(mark.certainty)),
      h('dt', {}, 'Where'), h('dd', {}, whereLine(mark) || (mark.piece?.area?.name ?? ''))),
    h('p', { class: 'muted' }, sightedLine(mark)),
    mark.document
      ? h('button', { type: 'button', class: 'rl-btn', onclick: () => open?.({ id: mark.document }) }, 'Open the page')
      : null,
    pieceHeld(rv, mark),
    pieceLocks(rv, mark),
    concealSwitch(rv.desk?.levers, mark, act),
    contingencyPicker(rv, mark, { act, pick, theatre }));
}

/**
 * With `locks` on, the seat's held orders on this piece, as the server names their piece (LKM):
 * each order's words, who can allow it, and asked or not asked. Null when none is held.
 */
function pieceHeld(rv, mark) {
  const held = locksOn(rv) ? heldOn(rv, mark) : [];
  if (!held.length) return null;
  return h('section', { class: 'rl-piece-held' },
    h('h3', {}, held.length === 1 ? 'A held order' : 'Held orders'),
    h('ul', { role: 'list' }, held.map((l) => h('li', { 'data-held': l.id },
      h('span', { class: 'rl-held-words' }, l.words), ' ', lockTag(l.who), ' ',
      h('span', { class: 'rl-held-status' }, heldStatus(l))))));
}

/**
 * With `locks` on, the piece's moves on the territory map that the server's check locks, each
 * marked with who can allow it (LKM); the map draws them beside the allowed ones. Redrawn in place
 * as the checks come in; empty while none is locked, so the sheet is no taller. Null with `locks`
 * off, or when no form moves the piece.
 */
function pieceLocks(rv, mark) {
  if (!locksOn(rv)) return null;
  const p = pieceMoves(rv, mark);
  if (!p?.moves.length) return null;
  const box = h('section', { class: 'rl-piece-moves', 'aria-live': 'polite' });
  const show = () => {
    const locked = p.moves.map((mv) => [mv, lockCheck(rv, moveOrder(p, mv))]).filter(([, c]) => isLocked(c));
    box.replaceChildren(...(locked.length ? [
      h('h3', {}, locked.length === 1 ? 'A locked move' : 'Locked moves'),
      h('ul', { role: 'list' }, locked.map(([mv, c]) => h('li', { 'data-area': mv.area.key },
        h('span', { class: 'rl-move-to' }, `${mv.area.name}, ${daysLabel(mv.days)}`), ' ', lockTag(c.who)))),
    ] : []));
  };
  for (const mv of p.moves) lockCheck(rv, moveOrder(p, mv), (changed) => { if (changed) show(); });
  show();
  return box;
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

/** A history-clock date in words ("20 September 1941") as [year, month, day], or null. */
function parts(on) {
  const m = /^(\d{1,2}) ([A-Za-z]+) (\d{4})$/.exec(String(on ?? '').trim());
  const month = m ? MONTHS.indexOf(m[2]) + 1 : 0;
  return month ? [Number(m[3]), month, Number(m[1])] : null;
}

const key = ([y, m, d]) => y * 10000 + m * 100 + d;

/**
 * `nextHistoryDate(setting, today)`: the earliest date on history's clock after `today` (an ISO
 * world date) as `{ on, what, iso }`, whatever order the dates come in; null when none is left.
 */
export function nextHistoryDate(setting, today) {
  const now = String(today ?? '').split('-').map(Number);
  if (now.length !== 3 || now.some((n) => !n)) return null;
  let best = null;
  for (const entry of Array.isArray(setting?.dates) ? setting.dates : []) {
    const at = parts(entry?.on);
    if (at && key(at) > key(now) && (!best || key(at) < key(best.at))) best = { at, entry };
  }
  if (!best) return null;
  const iso = best.at.map((n, i) => String(n).padStart(i ? 2 : 4, '0')).join('-');
  return { on: String(best.entry.on).trim(), what: String(best.entry.what ?? '').trim(), iso };
}

/**
 * The pin: the seat's aims and the next date on history's clock, the first thing on the Board.
 * A focus stop of its own so a keyboard reaches it before the board. Null with neither to show.
 */
export function pinBlock(rv, { ownAim = null, onAimSet = null } = {}) {
  const scored = aimList(rv.stakes?.aims, 'rl-pin-aims', { ownAim, onSet: onAimSet });
  const aims = scored ? { lines: [], note: 'Your own aims and where they stand. Tap one for its rule and evidence.' } : aimsBlock(rv.desk?.aims);
  const next = nextHistoryDate(rv.setting, rv.clock?.world_date);
  if (!aims && !next) return null;
  return h('section', { class: 'rl-pin', tabindex: '0', 'aria-label': 'Pinned: your aims and the next date in history' },
    aims
      ? h('div', { class: 'rl-pin-part' },
        h('h2', { class: 'rl-pin-h' }, 'Your aims'),
        scored ?? h('ul', { class: 'rl-pin-aims' }, aims.lines.map((line) => h('li', {}, line))),
        h('p', { class: 'rl-pin-note muted' }, aims.note))
      : null,
    next
      ? h('div', { class: 'rl-pin-part' },
        h('h2', { class: 'rl-pin-h' }, 'Next on history\'s clock'),
        h('p', { class: 'rl-pin-next' }, h('time', { datetime: next.iso }, next.on), next.what ? `: ${next.what}` : null))
      : null);
}

/**
 * `boardView(rv, ui, { pick, act, write, open })`: the Board. `ui.board` picks Theatre or Court
 * (`pick({ board })`); `ui.piece` is the selected piece; `write` is the room's order form;
 * `open({ id })` opens a paper.
 */
export function boardView(rv, ui, { pick, act, write, open, ownAim = null, onAimSet = null }) {
  const which = ui.board === 'court' ? 'court' : 'theatre';
  const board = which === 'court'
    ? courtBoard(rv, ui, { pick, act })
    : theatreBoard(rv, ui, { pick, act, open });
  const card = which === 'court' ? liftCard(board) : null;
  return h('main', { class: 'rl-board', 'data-board': which },
    h('section', { class: 'rl-board-main', 'aria-label': 'Board' },
      pinBlock(rv, { ownAim, onAimSet }),
      pressGroup('rl-boardswitch', 'Board', BOARDS, which, (b) => pick({ board: b })),
      board),
    h('aside', { class: 'rl-board-side', 'aria-label': 'Selected piece and order' },
      piecePanel(rv, ui.piece, open, { board: which, card, pick, act, theatre: ui.theatre ?? {} }),
      write));
}
