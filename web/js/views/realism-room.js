// The realism room: one surface for a seat in a realism game, in two views with one switch.
// Desk: the in-tray on the left; in the middle what needs an answer, ideas, the order being
// written or signed, the standard forms and the commit; the seat's orders on the right.
// Board, the view it opens on: the Theatre or the Court beside the selected piece and the
// order form. The messenger floats over either. The header's two names open the setting and
// the character dossiers. The map-first room has no header: one bar holds the day, the aims,
// the four groups' tabs, the chat button, Done and the game menu, and the menu holds the two
// names. Built from
// view.realism (realism_api.py).

import { api } from '../api.js';
import { h, icon } from '../dom.js';
import { afterLayout, reducedMotion } from '../motion.js';
import { STEP_ACTIONS, entityChoices } from '../realism-rules.js';
import { worldDate } from '../rules.js';
import { browserStorage } from '../theme.js';
import { briefBlock, directiveForm, paceHeader } from './realism.js';
import { battleAt, battleSheet, battleTitle } from './realism-battle.js';
import { boardView, piecePanel, viewSwitch, withBoard } from './realism-board.js';
import { courtBoard } from './realism-court.js';
import { BOARD_KEY, boardSwitch, capitalBoard, capitalSheet, hasCapital, startBoard } from './realism-capital.js';
import { header, reportDialog, reportInbox } from './frame.js';
import { homeSheet, speakNote, themeRead, withHome } from './realism-home.js';
import { needsAnswer } from './realism-answer.js';
import { DIPLOMACY_TITLE, diplomacySheet, freshDiplomacy, hasDiplomacy } from './realism-diplomacy.js';
import { areaCentre, matterOf, needLines, needsBar, needsList, sheetMarks } from './realism-needs.js';
import { ASK_TITLE, askOf, askSheet, formCheck, heldLines } from './realism-locks.js';
import { chatDock, seenStore, settleMarks, threadCounts, unread } from './realism-chat.js';
import { contactsTab } from './realism-contacts.js';
import { characterDossier, settingDossier } from './realism-dossier.js';
import { withCostStrips } from './realism-estimate.js';
import { standardForm, standardForms } from './realism-forms.js';
import { firstWakeCard, firstWakeWords } from './realism-firstwake.js';
import { MISSED_TITLE, happenedSheet, happenedStore, missedPages, missedSheet, shouldShow } from './realism-happened.js';
import { ideasPanel } from './realism-ideas.js';
import { crawlParagraphs, introCrawl } from './realism-crawl.js';
import { introStage, markIntro, seatSplash, splashModel, startOverview } from './realism-intro.js';
import { newsBlock, whatChanged } from './realism-news.js';
import { orderCards } from './realism-orders.js';
import { pressCounts, pressDock, pressFocus, pressMarks, pressPapers, pressSeen, pressTab, pressUnread } from './realism-press.js';
import { overlayLines, wakeOverlay } from './realism-overlay.js';
import { playbackDialog, wakePlayer } from './realism-playback.js';
import { peopleRoster, personDossier } from './realism-people.js';
import {
  closeSheet, forgetForm, layoutChoice, markFiled, openSheet, openSheetOf, overSheet, readForms, restoreForms, sheetMotion,
  returnTarget, roomLayout, setRoomLayout, setTerritorial,
} from './realism-sheets.js';
import {
  GROUPS, chatButton, formSearch, formsTaking, groupOf, groupTabs, partFor, partTabs, personMoves,
} from './realism-groups.js';
import { openAim, ownAimOf, stakesStrip } from './realism-stakes.js';
import { foldEconomy } from './realism-economy.js';
import { nationRows, nationsPanel, standingGrid } from './realism-nations.js';
import { foldOdds } from './realism-odds.js';
import { loadShapes, shapesFor, theatreBoard } from './realism-theatre.js';
import { aimMarks, roomBar, statusStrip, summaryTiles } from './realism-status.js';
import { sideSwitch, tabBar } from './realism-tabs.js';
import { noticesSection } from './realism-notices.js';
import { followThread, threadItems } from './realism-thread.js';
import { threatsPanel } from './realism-threats.js';
import { fitStrip, lightTogether, timelineStrip } from './realism-timeline.js';
import { sentTracks } from './realism-tracks.js';
import { trayView } from './realism-tray.js';
import { RUNNING, comeBackLine, commitBusy, commitPanel, orderCard, stylePicker, wakeHeader } from './realism-wake.js';

const freshUi = (game) => ({
  game, wide: false, page: null, said: null, error: null, busy: null,
  filter: 'all', sort: 'newest', draft: null, proposal: null, autoFor: null,
  chat: { open: false, tab: 'chats', thread: null }, contact: null, orderTo: null,
  happenedSeen: null, missed: null, missedAsked: false, refocusChat: false, brief: null, pending: null, drafts: {}, letters: [], playedTo: null, playing: null, missedPlay: null, offer: null, menuCall: false,
  tab: 'desk', side: 'papers', press: { open: false, tab: null }, pressPage: null, peopleTab: 'opponents',
  view: 'board', board: 'theatre', piece: null, theatre: { mode: 'map', scope: 'reports' },
  firstWakeOff: null, sheet: null, sheetFrom: null, sheetForms: {}, matter: null, full: false, timeline: false,
});
let ui = freshUi(null);
// the room last drawn: a re-read (the minute poll) keeps the values in its open sheet's forms
let lastRoot = null;

/** The room's picks and drafts: kept across redraws of one game, started clean for another. */
export function uiFor(gameId) {
  if (ui.game !== gameId) ui = freshUi(gameId);
  return ui;
}

/**
 * Who an order can go to: the inner circle, and a contact chosen from the messenger
 * ("Write them an order"), whose channels are the keys the order form posts. A contact
 * with no channel cannot be written to, so it is left off.
 */
export function orderContacts(inner, c) {
  const keys = c?.channel_keys ?? [];
  if (!c || !keys.length || inner.some((x) => x.person === c.name)) return inner;
  return [...inner, { person: c.name, title: c.title, channel: keys[0], channels: keys }];
}

/**
 * Whether the What happened sheet opens for this wake page: once per wake, kept in storage
 * and, where storage is blocked, in the room's memory (`seen`) so a redraw does not reopen it.
 */
export function happenedDue(page, store, seen) {
  return Boolean(page) && shouldShow(page, store) && page.number > (seen ?? 0);
}

/**
 * Start a message to `thread`: refused (false) while the room is busy, while another message
 * is out, or for blank text. Otherwise `ui.pending` holds `{ thread, text }`, the thread's
 * draft is dropped so its composer draws empty, and the old error clears. Only the composer
 * is held while it is out.
 */
export function beginSend(state, thread, text) {
  const said = (text ?? '').trim();
  if (state.busy || state.pending || !said) return false;
  state.pending = { thread, text: said };
  const { [thread]: _sent, ...others } = state.drafts ?? {};
  state.drafts = others;
  state.error = null;
  return true;
}

export const REPLACE_ASK = 'Replace your draft with this order?';

const putOrder = (state, text) => {
  state.offer = null;
  state.proposal = null;
  state.draft = { to: state.draft?.to ?? '', channel: state.draft?.channel ?? '', text };
};

/**
 * Words for the order form from outside it (an order a development or the news suggests).
 * Over a draft the player has typed they wait in `offer` until the player picks Replace
 * (false); with no typed draft they go straight into the form (true).
 */
export function offerOrder(state, text) {
  const typed = (state.draft?.text ?? '').trim();
  if (typed && typed !== text.trim()) {
    state.offer = text;
    return false;
  }
  putOrder(state, text);
  return true;
}

/** The player's answer to the offer: Replace puts its words in the form, Keep mine drops it. */
export function settleOffer(state, replace) {
  if (replace && state.offer != null) putOrder(state, state.offer);
  else state.offer = null;
}

/** The line under the order form that asks before a typed draft is replaced. */
export function offerLine({ onReplace, onKeep }) {
  return h('div', { class: 'rl-confirm rl-offer', role: 'group', 'aria-label': REPLACE_ASK },
    h('p', {}, REPLACE_ASK),
    h('div', { class: 'row' },
      h('button', { type: 'button', class: 'danger', onclick: onReplace }, 'Replace'),
      h('button', { type: 'button', class: 'ghost', onclick: onKeep }, 'Keep mine')));
}

/** Why another action waits while a message is out, or null when none is. */
export function whileSending(state) {
  const thread = state.pending?.thread;
  if (!thread) return null;
  const who = thread === 'aide' ? 'Your aide' : thread;
  return `${who} is answering your message. Try again when the answer is in.`;
}

/**
 * The message is answered or failed: `pending` clears. A sent message leaves that thread's
 * draft empty; a failed or refused one puts the words back in its composer and says why in `error`.
 */
export function endSend(state, outcome) {
  const { thread, text } = state.pending ?? {};
  state.pending = null;
  if (!thread) return;
  const { [thread]: _kept, ...others } = state.drafts ?? {};
  if (outcome.error || outcome.refused) {
    state.drafts = { ...others, [thread]: text };
    state.error = outcome.error ?? outcome.reply ?? 'The message was not sent.';
    if (outcome.thread) openLetter(state, outcome.thread);
  } else {
    state.drafts = others;
  }
}

/**
 * Counsel was refused because a player holds that leader: their thread opens, its composer now
 * writes a letter (`letters` lists them once), and the words typed stay in it.
 */
export function openLetter(state, name) {
  if (!state.letters.includes(name)) state.letters = [...state.letters, name];
  state.chat = { open: true, tab: 'chats', thread: name };
}

/** The order form's draft for a letter to `name`: the `letter` channel, so it reaches their desk. */
export const letterDraft = (name, text) => ({ to: name, channel: 'letter', text });

/**
 * A tab, tile or switch picks what to show. `view` is Board or Desk; the Board tab picks the
 * Board, and a desk panel's tab (Papers, Desk, Orders) the Desk. `board`, `piece` and `theatre`
 * are the board's switch, its selected piece and the map's switches. Messages opens the
 * messenger; on a phone, where the messenger covers the room, any other tab closes it so the
 * panel picked is the one seen.
 */
export function pickPanel(state, { tab, side, view, board, piece, theatre }, phone) {
  if (tab === 'board') state.view = 'board';
  else if (tab && tab !== 'messages') state.view = 'desk';
  if (view) state.view = view;
  if (board) state.board = board;
  if (piece !== undefined) state.piece = piece;
  if (theatre) state.theatre = theatre;
  if (tab) state.tab = tab === 'board' ? 'desk' : tab;
  if (side) state.side = side;
  if (tab === 'messages') state.chat = { ...state.chat, open: true };
  else if (tab && phone) state.chat = { ...state.chat, open: false };
}

/** Whether the room is at phone width, where the tab bar shows (c-shell.css). */
const phoneWidth = () => Boolean(globalThis.matchMedia?.('(max-width: 767px)').matches);

/** Whether "What needs you" is a rail beside the map (from 1024 px, c-needs.css) rather than a half sheet. */
const needsRail = () => globalThis.matchMedia?.('(min-width: 1024px)').matches ?? true;

/** Where focus goes when the messenger closes: its launcher, or on a phone (launcher hidden) the Messages tab. */
export function closedChatTarget(root, phone) {
  if (!phone) return root.querySelector('.rl-msgr-btn');
  return [...root.querySelectorAll('.rl-tabbar button')].find((b) => b.textContent.startsWith('Messages')) ?? null;
}

const SWITCHES = ['.rl-tabbar', '.rl-sideswitch', '.rl-tiles', '.rl-viewswitch', '.rl-board-main', '.rl-sheettabs', '.rl-mapfirst-map'];

/** The panel switch a focused button belongs to and its place there, or null for any other element. */
export function switchPlace(el) {
  for (const sel of SWITCHES) {
    const group = el?.closest?.(sel);
    if (group) return { sel, at: [...group.querySelectorAll('button')].indexOf(el) };
  }
  return null;
}

/** The button at that place in a redrawn room. */
export function switchAt(root, place) {
  if (!place) return null;
  return root.querySelector(place.sel)?.querySelectorAll('button')[place.at] ?? null;
}

/** The aide has written: its thread opens, and the phone tab bar marks Messages. */
export function openAide(state) {
  state.chat = { open: true, tab: 'chats', thread: 'aide' };
  state.tab = 'messages';
}

/** Browser storage, or nothing where it is blocked: the units take it as a parameter. */
const storage = () => browserStorage(window);

/** The title of the map-first room's aims sheet [proposed]. */
export const AIMS_TITLE = 'Your three aims';

/** The Write part's first line: most orders start from what they act on. */
const WRITE_HINT = 'Most orders start from what they act on: a piece on the map, a person\'s card, a nation\'s card. Here you write in your own words, or find a form by name.';

function stepForm(order, act) {
  const id = `rl-step-${order.id}`;
  const select = h('select', { id, name: 'action', required: true },
    STEP_ACTIONS.map(([value, label]) => h('option', { value }, label)));
  return h('form', {
    class: 'rl-form rl-step-form', 'aria-label': `Act on ${order.label}`,
    onsubmit: (e) => { e.preventDefault(); act({ order_id: order.id, action: select.value, params: {} }); },
  }, h('label', { for: id }, 'Your decision'), select,
  h('button', { type: 'submit', class: 'rl-submit' }, 'Take the step'));
}

/**
 * The host's "Hand a leader to a new player": the leaders nobody plays, each with a button that asks
 * the server for one invite code. `api.game('handover-list')` resolves to `{ reply, refused, leaders:
 * [{ key, name, office }] }` and `api.game('handover', { leader })` to `{ reply, refused, code,
 * from_wake }`. The list is read when the menu opens and is not held by `run`, so a slow read never
 * blocks Pause or Leave; the hand-over call goes through the menu's one-call guard.
 */
function handoverSection({ api, run }) {
  const says = h('p', { class: 'hint rl-handover-says', role: 'status', 'aria-live': 'polite' });
  const list = h('ul', { class: 'rl-handover-list' });
  const code = h('div', { class: 'rl-handover-code' });
  const hand = (leader) => run(async () => {
    const r = await api.game('handover', { leader: leader.key });
    says.replaceChildren(r.reply ?? '');
    if (r.refused || !r.code) { code.replaceChildren(); return; }
    const field = h('input', { id: 'rl-handover-code', name: 'code', type: 'text', readonly: true, value: r.code, onfocus: (e) => e.target.select?.() });
    code.replaceChildren(h('label', { for: 'rl-handover-code' }, 'Invite code'), field);
    field.focus();
  });
  const row = (leader) => {
    const id = `rl-handover-${leader.key}`;
    return h('li', {},
      h('span', { id }, h('strong', {}, leader.name), ` · ${leader.office}`),
      h('button', { type: 'button', class: 'ghost', 'aria-describedby': id, onclick: () => hand(leader) }, 'Hand to a new player'));
  };
  const load = async () => {
    try {
      const r = await api.game('handover-list');
      says.replaceChildren(r.reply ?? '');
      list.replaceChildren(...(r.refused ? [] : (r.leaders ?? []).map(row)));
    } catch (ex) {
      says.replaceChildren(ex.message);
    }
  };
  const nodes = h('section', { class: 'rl-handover' },
    h('h3', {}, 'Hand a leader to a new player'),
    h('p', { class: 'hint' }, 'The hand-over takes effect at the next wake. Send the code to the new player privately; it works once.'),
    list, code, says);
  return { nodes, load };
}

/**
 * The menu's quiet route to every sheet on Beginner: each group by name with one button per
 * part, `groups` as `[{ label, parts: [[key, label]] }]`; `onOpen(key)` on a press.
 */
export function allSheetsList(groups, onOpen) {
  return h('div', { class: 'rl-allsheets', role: 'group', 'aria-labelledby': 'rl-allsheets-h' },
    h('h3', { id: 'rl-allsheets-h' }, 'All sheets'),
    groups.map((g) => h('div', { class: 'rl-allsheets-group', role: 'group', 'aria-label': g.label },
      h('h4', {}, g.label),
      h('div', { class: 'row' }, g.parts.map(([key, label]) => h('button', {
        type: 'button', class: 'ghost', 'data-sheet': key, 'aria-label': `${g.label}: ${label}`, onclick: () => onOpen(key),
      }, label))))));
}

/**
 * The game menu: pause, resume and end for the host; how to start another game. `extra(close)`,
 * when given, answers nodes drawn under the game's name (the map-first room's names, wake and account).
 */
export function gameMenu(game, ctx, work, onLayout = null, allSheets = null, extra = null) {
  const out = h('div', { class: 'outcome', role: 'status', 'aria-live': 'polite' });
  const dialog = h('dialog', { class: 'sheet rl-menu', 'aria-labelledby': 'rl-menu-h' });
  const close = () => dialog.close();
  const closeBtn = h('button', { type: 'button', class: 'ghost', onclick: close }, 'Close');
  // One call at a time. The guard lives in the room's state, which outlasts a redraw of the
  // menu; the menu's buttons other than Close are held until the call is answered.
  const hold = (on) => {
    ui.menuCall = on;
    for (const b of dialog.querySelectorAll('button')) if (b !== closeBtn) b.disabled = on;
  };
  const run = async (fn) => {
    if (ui.menuCall) return;
    hold(true);
    out.replaceChildren('Working…');
    try {
      await fn();
      if (out.textContent === 'Working…') out.replaceChildren();
    } catch (ex) {
      out.replaceChildren(h('span', { class: 'form-error', role: 'alert' }, ex.message));
    } finally {
      hold(false);
    }
  };
  const call = (action) => run(async () => {
    const r = await api.game(action);
    if (r.refused) { out.replaceChildren(r.reply); return; }
    ui.said = r.reply;
    close();
    if (action === 'end') ctx.go('new');
    else if (action === 'leave') ctx.go('home');
    else await ctx.refresh();
  });
  const notices = noticesSection({ api, run });
  const handover = game.host ? handoverSection({ api, run }) : null;
  const inbox = game.host ? reportInbox() : null;
  const hours = h('input', { id: 'rl-wake-hours', name: 'hours', type: 'number', min: 1, max: 168, step: 1, required: true });
  const setHours = () => {
    if (!hours.reportValidity()) return;
    return run(async () => {
      const r = await api.game('wake-hours', { hours: Number(hours.value) });
      out.replaceChildren(r.reply);
    });
  };
  const confirmEnd = h('div', { class: 'rl-confirm', hidden: true },
    h('p', {}, h('strong', {}, `End ${game.name} for everyone?`),
      ' No one can play it again and its invite codes stop working. Its record is kept.'),
    h('div', { class: 'row' },
      h('button', { type: 'button', class: 'ghost', onclick: () => { confirmEnd.hidden = true; endBtn.hidden = false; } }, 'Keep playing'),
      h('button', { type: 'button', class: 'danger', onclick: () => call('end') }, 'End the game')));
  const confirmLeave = h('div', { class: 'rl-confirm', hidden: true },
    h('p', {}, h('strong', {}, `Leave ${game.name}?`),
      ' Your person stays in the game, played by no one. You can then join or start another game.'),
    h('div', { class: 'row' },
      h('button', { type: 'button', class: 'ghost', onclick: () => { confirmLeave.hidden = true; leaveBtn.hidden = false; } }, 'Stay'),
      h('button', { type: 'button', class: 'danger', onclick: () => call('leave') }, 'Leave the game')));
  const leaveBtn = h('button', {
    type: 'button', class: 'ghost', onclick: () => { leaveBtn.hidden = true; confirmLeave.hidden = false; },
  }, 'Leave game…');
  const endBtn = h('button', {
    type: 'button', class: 'ghost', onclick: () => { endBtn.hidden = true; confirmEnd.hidden = false; },
  }, 'End game…');
  const host = game.host
    ? [
      h('h3', {}, 'You are the host'),
      h('p', { class: 'hint' }, game.paused
        ? 'The game is paused: the calendar does not move on its own.'
        : 'The game is running.'),
      h('div', { class: 'row' },
        game.paused
          ? h('button', { type: 'button', class: 'ghost', onclick: () => call('resume') }, 'Resume')
          : h('button', { type: 'button', class: 'ghost', onclick: () => call('pause') }, 'Pause'),
        endBtn),
      confirmEnd,
      handover.nodes,
      inbox.nodes,
      h('div', { class: 'rl-field' }, h('label', { for: 'rl-wake-hours' }, 'Hours per wake'),
        h('div', { class: 'row' }, hours,
          h('button', { type: 'button', class: 'ghost', onclick: setHours }, 'Set'))),
    ]
    : [
      h('p', { class: 'hint' }, 'Only the host can pause or end this game.'),
      leaveBtn,
      confirmLeave,
    ];
  dialog.append(h('div', { class: 'rl-menu-body' },
    h('h2', { id: 'rl-menu-h' }, game.name),
    extra?.(close) ?? null,
    host,
    notices.nodes,
    onLayout ? layoutChoice((key) => { close(); onLayout(key); }) : null,
    allSheets ? allSheetsList(allSheets.sheets, (key) => { close(); allSheets.onOpen(key); }) : null,
    h('h3', {}, 'A new game'),
    h('p', { class: 'hint' }, game.host
      ? 'You play one game at a time. End this one, and you can start another straight away.'
      : 'You play one game at a time. Leave this one, and you can join or start another.'),
    out,
    h('div', { class: 'row end' }, closeBtn)));
  const open = h('button', {
    type: 'button', class: 'rl-menu-btn', 'aria-haspopup': 'dialog', onclick: () => { if (work.idle()) { dialog.showModal(); handover?.load(); inbox?.load(); notices.load(); } },
  }, 'Game', icon('chevron', 12));
  return [open, dialog];
}

export function realismRoom(ctx) {
  const { me, refresh } = ctx;
  const game = me.game;
  uiFor(game.id);
  if (lastRoot?.isConnected && roomLayout() === 'map') ui.sheetForms = readForms(lastRoot, ui.sheetForms);
  const rv = game.view.realism;
  setTerritorial(rv.map?.areas?.length > 0);
  if (!rv.brief && ui.brief?.tick === rv.wake_tick) rv.brief = ui.brief.brief;
  const seatName = game.view.seat?.name ?? '';
  const root = h('div', { class: 'screen war-screen realism-screen' });
  // a redraw rebuilds the open thread: put the reader back where they were reading
  const follow = () => followThread(ui.chat, root.querySelector('.rl-msgr-panel .rl-th'));
  // the desk is a modal dialog: a redraw rebuilds it, and it is shown again once in the page
  const showDesk = () => {
    const desk = root.querySelector('dialog.rl-pd');
    if (desk?.isConnected && !desk.open) desk.showModal();
  };
  const mapFirst = () => roomLayout() === 'map';
  const rerender = () => {
    if (mapFirst()) ui.sheetForms = readForms(root, ui.sheetForms);
    const was = mapFirst() ? root.querySelector('section.rl-over') : null;
    const rect = was?.getBoundingClientRect?.() ?? null;
    root.replaceChildren(...build());
    if (mapFirst()) sheetMotion(root, was, rect, needsRail());
    follow();
    showDesk();
    showMissed();
  };
  // a sheet left open stays open over a redraw or a re-read of the room
  const showMissed = () => {
    for (const sheet of root.querySelectorAll('dialog.rl-missed, dialog.rl-plb-dialog')) {
      if (sheet.isConnected && !sheet.open) sheet.showModal();
    }
  };
  const seen = seenStore(storage(), game.id);
  const shown = happenedStore(storage(), game.id);
  const pressSeenBy = pressSeen(storage(), game.id);

  /**
   * Run one slow call: the status line says what is happening in plain words, every
   * control is held until it is done, and the room is re-read after. A call that runs
   * the wake also lays the overlay over the room; the redraw removes it.
   */
  async function work(message, fn) {
    if (ui.busy) return;
    if (ui.pending) {
      // one call at a time: say why the click waits rather than drop it with no word
      ui.error = whileSending(ui);
      showStatus();
      return;
    }
    ui.busy = message;
    ui.error = null;
    const clicked = document.activeElement;
    ui.refocusChat = Boolean(clicked?.closest?.('.rl-msgr-panel'));
    root.setAttribute('aria-busy', 'true');
    if (clicked?.tagName === 'BUTTON') clicked.classList.add('rl-working');
    for (const el of root.querySelectorAll('button, select, textarea, input')) el.disabled = true;
    showStatus();
    if (message === RUNNING) {
      root.append(wakeOverlay({ message, lines: overlayLines(rv.setting, rv.wake.wake), map: rv.map, orders: rv.record?.orders }));
    }
    try {
      await fn();
    } catch (ex) {
      ui.error = ex.message;
    } finally {
      ui.busy = null;
    }
    try {
      await refresh();
    } catch (ex) {
      // the room was not re-read: drop the overlay and the hold, and say why
      ui.error = ex.message;
      root.removeAttribute('aria-busy');
      rerender();
      if (ui.refocusChat) refocus(ui.chat, true);
    }
  }
  work.idle = () => !ui.busy && !ui.pending;

  let status = null;
  function showStatus() {
    if (!status) return;
    if (ui.busy) {
      status.className = 'rl-status busy';
      status.replaceChildren(h('span', { class: 'rl-spinner', 'aria-hidden': 'true' }), ui.busy);
    } else if (ui.error) {
      status.className = 'rl-status error';
      status.replaceChildren(h('span', { role: 'alert' }, ui.error));
    } else {
      status.className = ui.said ? 'rl-status said' : 'rl-status';
      status.replaceChildren(ui.said ?? '');
    }
  }

  /** The idea behind "Choose" when it is an order the news suggests (pick `n.…`), else null. */
  const newsIdea = (action, body) => (action === 'option' && String(body?.pick ?? '').startsWith('n.')
    ? rv.agenda.initiative.find((o) => o.pick === body.pick) ?? null : null);

  const act = (message, action, body, then) => {
    // an order the news suggests is written, not filed: its words go into the order form
    const news = newsIdea(action, body);
    if (news) return writeOrder(news.label);
    return work(message, async () => {
      const r = await api.realism(action, body);
      ui.said = r.reply || null;
      // the aide has written: a failed order, or an answer; open its thread
      if (r.help) openAide(ui);
      then?.(r);
    });
  };

  /** The aide reads the order; nothing is filed until the player signs. */
  const ask = (draft) => {
    ui.draft = draft;
    ui.offer = null; // the player sent their own words: the offered ones no longer wait
    return act('Your aide is reading it…', 'order', draft, (r) => {
      ui.proposal = r.proposal ?? null;
      if (ui.proposal) ui.said = null; // the card says it
    });
  };

  /**
   * A letter to a leader a player holds: the order form's draft, read by the aide like any
   * order, with the signing card on the desk. The messenger closes so the card is in view.
   */
  const letter = (to, text) => {
    const words = (text ?? '').trim();
    if (!words || ui.busy || ui.pending) return;
    const { [to]: _sent, ...others } = ui.drafts;
    ui.drafts = others;
    ui.orderTo = Object.values(rv.reach ?? {}).flat().find((c) => c.name === to) ?? null;
    ui.proposal = null;
    ui.chat = { ...ui.chat, open: false };
    ui.tab = 'desk';
    toForms();
    return ask(letterDraft(to, words));
  };

  /** File the signed order, which the server holds; a refusal leaves it on the desk to revise. */
  const signed = (p) => act(p.person ? `Sending it to ${p.person}…` : 'Sending it…', 'file', {},
    (r) => { if (!r.refused) { ui.proposal = null; ui.draft = null; ui.orderTo = null; ui.speak = false; } });

  const open = (d) => work('Fetching the paper…', async () => {
    ui.page = await api.realism('read', { doc_id: d.id });
    ui.said = null;
    // the paper opens in the in-tray: the Papers sheet, or the Desk view of today's room
    if (mapFirst()) openSheet(ui, 'papers');
    else if (ui.view === 'board') pickPanel(ui, { tab: 'papers', side: 'papers' }, phoneWidth());
  });

  const flag = (on, page = ui.page) => work(on ? 'Flagging it…' : 'Unflagging it…', async () => {
    await api.realism('flag', { doc_id: page.item.id, flagged: on });
    page.item.flagged = on;
  });

  /** A press page opens on the newspaper desk, at its paper's tab. */
  const readPress = (d) => work('Fetching the paper…', async () => {
    const outlet = rv.documents.documents.find((x) => x.id === d.id)?.author ?? ui.press.tab;
    ui.press = { open: true, tab: outlet };
    ui.pressPage = await api.realism('read', { doc_id: d.id });
    ui.said = null;
  });

  function papers() {
    const widen = h('button', {
      type: 'button', class: 'rl-btn rl-widen', 'aria-pressed': String(ui.wide),
      onclick: () => { ui.wide = !ui.wide; rerender(); },
    }, ui.wide ? 'Narrow' : 'Widen');
    const choose = (key, focus) => {
      ui.filter = key;
      rerender();
      if (focus) root.querySelector(`#rl-filter-${key}`)?.focus();
    };
    return h('section', { class: 'rl-col rl-papers', 'data-tab': 'papers', 'aria-label': 'Papers' },
      h('div', { class: 'rl-col-head' }, widen),
      h('div', { class: 'rl-col-body' },
        trayView(rv.documents, open, {
          filter: ui.filter,
          sort: ui.sort,
          onFilter: choose,
          onSort: (value) => { ui.sort = value; rerender(); },
          page: ui.page,
          onClose: () => { ui.page = null; rerender(); },
          onFlag: flag,
          wide: ui.wide,
        })));
  }

  /** The directive form, its words kept as typed: a redraw or a refresh rebuilds it from ui.draft. */
  function orderForm() {
    const form = directiveForm(orderContacts(rv.desk.inner_circle, ui.orderTo), ui.draft, ask);
    form.addEventListener('input', () => {
      ui.draft = {
        to: form.querySelector('input[type="radio"]:checked')?.value ?? '',
        channel: form.querySelector('select').value,
        text: form.querySelector('textarea').value,
      };
    });
    return form;
  }

  // The aide briefs itself once a wake: the room asks when this wake has no brief yet, and
  // fills the brief and the ideas when it comes, without holding the desk.
  const briefOn = {
    brief: () => act('Your aide is reading your papers…', 'aide', { again: true }),
    useDraft,
  };
  const briefSlot = h('div', { class: 'rl-brief-slot' });
  const ideasSlot = h('div', { class: 'rl-ideas-slot' });
  const fillIdeas = () => ideasSlot.replaceChildren(...[ideasPanel(rv.agenda, rv.brief, { act, useDraft })].filter(Boolean));
  const fillBrief = (opts) => {
    briefSlot.replaceChildren(...[briefBlock(rv.brief, briefOn, opts)].flat().filter(Boolean));
    fillIdeas();
  };
  async function autoBrief() {
    ui.autoFor = rv.wake_tick;
    fillBrief({ reading: true });
    try {
      const r = await api.realism('aide', {});
      if (r.brief) {
        rv.brief = r.brief;
        ui.brief = { tick: rv.wake_tick, brief: r.brief }; // a redraw meanwhile reads it from here
      }
      fillBrief(r.brief ? {} : { said: r.reply });
    } catch (ex) {
      fillBrief({ said: ex.message });
    }
  }

  /** The order being written or signed, and the line that asks before a typed draft is replaced. */
  function writeBlock() {
    const directive = ui.proposal
      ? orderCard(ui.proposal, { onSign: signed, onRevise: () => { ui.proposal = null; ui.said = null; rerender(); } })
      : orderForm();
    // the staff's read of the groups a named theme speaks to: after the reading, before signing
    const read = ui.proposal && rv.home ? themeRead(rv.home, ui.proposal) : null;
    return h('section', { class: 'rl-write', 'aria-label': ui.proposal ? 'Your order, to sign' : 'Write an order' },
      ui.speak && rv.home && !ui.proposal ? speakNote(rv.home) : null, directive, read,
      ui.offer != null ? offerLine({ onReplace: () => answerOffer(true), onKeep: () => answerOffer(false) }) : null);
  }

  function deskColumn() {
    return h('section', { class: 'rl-col rl-desk-col', 'data-tab': 'desk', 'aria-label': 'Desk' },
      h('div', { class: 'rl-col-body' },
        stylePicker(rv.style, { act }),
        needsAnswer(rv.agenda, { act, today: rv.clock.world_date }),
        ideasSlot,
        writeBlock(),
        withCostStrips(standardForms(rv.desk, {
          onSubmit: (v) => act('Sending it…', 'lever', v),
          entities: entityChoices(rv.desk),
          check: sendCheck(), onAsk: fileAndAsk, onAnyway: fileAndSend,
        }), rv.desk?.levers, rv.court),
        hasDiplomacy(rv) ? h('section', { class: 'rl-dp-desk', 'aria-labelledby': 'rl-dp-desk-h' },
          h('h2', { id: 'rl-dp-desk-h' }, DIPLOMACY_TITLE), diplomacy()) : null,
        commitPanel(rv.wake, { act })));
  }

  /** The Diplomacy sheet (DPL), with the offer being built, its reading and the call kept on `ui` across redraws. */
  const diplomacy = () => diplomacySheet(rv, (ui.dpl ??= freshDiplomacy()), { act, redraw: rerender });

  /** Open a standard form on the desk, for a draft the aide suggested. */
  function useDraft(d) {
    if (mapFirst()) { // the standard forms are in the Forms sheet
      if (openSheetOf(ui) !== 'forms') {
        openSheet(ui, 'forms');
        rerender();
      }
    } else if (ui.view === 'board') { // the standard forms are on the Desk view
      ui.view = 'desk';
      rerender();
    }
    const item = root.querySelector(`.rl-instrument[data-lever="${CSS.escape(d.lever)}"]`);
    if (!item) return;
    const fold = item.closest('details');
    if (fold) fold.open = true;
    const toggle = item.querySelector('[aria-expanded]');
    if (toggle?.getAttribute('aria-expanded') === 'false') toggle.click();
    item.scrollIntoView({ block: 'center' });
    item.querySelector('input, select, textarea')?.focus();
  }

  /** A roster row opens that person's dossier over the room; closing it puts focus back on the row. */
  function openPerson(line, tab) {
    const from = document.activeElement;
    const dossier = personDossier(line, tab, {
      onClose: () => {
        dossier.remove();
        if (from?.isConnected) from.focus();
      },
    });
    if (mapFirst()) dossier.querySelector('.rl-dos-foot')?.prepend(personMoves(contactOf(line.name), { onAsk: askPerson(dossier), onWrite: writePerson(dossier) }));
    root.append(dossier);
    dossier.showModal();
  }

  /** The contact the seat reaches `name` by, or null. */
  const contactOf = (name) => ['inner_circle', 'government', 'foreign', 'other']
    .map((k) => (rv.reach?.[k] ?? []).find((c) => c.name === name)).find(Boolean) ?? null;

  /** A person's card's Ask: the card closes and the messenger opens on their thread. */
  const askPerson = (card) => (c) => {
    card.close();
    ui.chat = { open: true, tab: 'chats', thread: c.name };
    openSheet(ui, 'messages');
    rerender();
    refocus(ui.chat, true);
  };

  /** A person's card's Write an order: the card closes and Orders opens at Write, addressed to them. */
  const writePerson = (card) => (c) => {
    card.close();
    ui.orderTo = c;
    ui.proposal = null;
    ui.draft = { to: c.name, channel: c.channel_keys?.[0] ?? '', text: ui.draft?.text ?? '' };
    openSheet(ui, 'forms', { group: 'people' });
    rerender();
    root.querySelector('.rl-over .rl-write textarea')?.focus();
  };

  /** A roster tab is picked: the redraw keeps focus on that tab's button. */
  function pickPeople(key) {
    ui.peopleTab = key;
    rerender();
    root.querySelector('.rl-people .seg button[aria-pressed="true"]')?.focus();
  }

  // the People roster replaces the Opponents panel; a view without it keeps the old panel
  const peoplePanel = () => (rv.people
    ? peopleRoster(rv.people, { tab: ui.peopleTab, onTab: pickPeople, onOpen: openPerson })
    : threatsPanel(rv.threats));
  const yourOrders = () => orderCards(rv.record, rv.orders, (o) => stepForm(o, (v) => act('Recording your decision…', 'step', v)), open);
  /** The Sent part: the orders as tracks; a tap opens one in place, and the redraw keeps focus on it. */
  const sentPart = () => sentTracks(rv.record, rv.orders, heldLines(rv), {
    stepForm: (o) => stepForm(o, (v) => act('Recording your decision…', 'step', v)), onOpen: open, opened: ui.sentOpen,
    onToggle: (id) => {
      ui.sentOpen = ui.sentOpen === id ? null : id;
      rerender();
      root.querySelector(`.rl-sent-order[data-order="${CSS.escape(id)}"] .rl-sent-head`)?.focus();
    },
  });

  function sideColumn() {
    return h('aside', { class: 'rl-col rl-side', 'data-tab': 'orders', 'aria-label': 'Your orders' },
      h('div', { class: 'rl-col-body' }, peoplePanel(), yourOrders()));
  }

  /**
   * Every conversation: the aide's always, each contact the seat can reach with at least one
   * item (their answers, the seat's questions, papers they wrote), and the open one even if empty.
   */
  function threads() {
    const out = { aide: threadItems({ person: 'aide', help: rv.help ?? [] }) };
    const names = new Set(['inner_circle', 'government', 'foreign', 'other']
      .flatMap((k) => (rv.reach?.[k] ?? []).map((c) => c.name)));
    for (const name of names) {
      const items = threadItems({ person: name, counsel: rv.counsel ?? [], documents: rv.documents });
      if (items.length || ui.chat.thread === name) out[name] = items;
    }
    return out;
  }

  /** A redraw drops focus; put it back in the messenger so Esc and the keyboard keep working. */
  function refocus(chat, compose = false) {
    ui.refocusChat = false;
    const panel = root.querySelector('.rl-msgr-panel');
    const inThread = compose ? '.rl-th-compose textarea' : '.rl-th-back';
    const target = !chat.open ? closedChatTarget(root, phoneWidth())
      : panel?.querySelector(chat.thread ? inThread : '[role="tab"][aria-selected="true"]');
    target?.focus();
  }

  /**
   * Send a message: the thread shows it at once with the other side writing, only the
   * composer is held, and the room is re-read when the answer is in. A failure keeps the words.
   */
  async function send(thread, action, body, text) {
    if (!beginSend(ui, thread, text)) return;
    showStatus();
    rerender();
    refocus(ui.chat, true);
    let outcome;
    try {
      const r = await api.realism(action, { ...body, question: ui.pending.text });
      outcome = { refused: Boolean(r.refused), reply: r.reply || null, thread: r.thread ?? null };
      ui.said = r.refused ? null : outcome.reply;
    } catch (ex) {
      outcome = { error: ex.message };
    }
    endSend(ui, outcome);
    ui.refocusChat = true;
    try {
      await refresh();
    } catch (ex) {
      ui.error = ex.message;
      rerender();
      refocus(ui.chat, true);
    }
  }

  function dock() {
    const all = threads();
    const counts = threadCounts(all);
    const read = seen.read();
    const marks = settleMarks(counts, read);
    if (marks !== read) seen.write(marks);
    const thread = ui.chat.open ? ui.chat.thread : null;
    if (thread && thread in counts && marks[thread] !== counts[thread]) seen.write({ ...marks, [thread]: counts[thread] });
    const inner = rv.desk.inner_circle.map((c) => c.person);
    return chatDock({
      state: ui.chat,
      // in the map-first room the messenger is a sheet: closing it closes the sheet
      onState: (next) => { if (!next.open && ui.tab === 'messages') ui.tab = 'desk'; if (!next.open && mapFirst()) return closeOver(); ui.chat = next; rerender(); refocus(next); },
      threads: all,
      seen: seen.read(),
      reach: rv.reach,
      record: rv.record,
      pending: ui.pending,
      drafts: ui.drafts,
      brief: briefSlot,
      ask: (text) => send('aide', 'help', {}, text),
      consult: (to, text) => send(to, 'consult', { to }, text),
      letters: ui.letters,
      letter,
      onOpen: open,
      useDraft,
      // kept as typed, with no redraw, so a redraw or a thread switch keeps the words
      onType: (key, text) => { ui.drafts = { ...ui.drafts, [key]: text }; },
      contactsTab: contactsTab(rv.reach, {
        inner,
        selected: ui.contact,
        onSelect: (name) => {
          ui.contact = name;
          rerender();
          root.querySelector(name ? '.rl-msgr-panel .rl-ct-back' : '.rl-msgr-panel [role="tab"][aria-selected="true"]')?.focus();
        },
        onMessage: (name) => { ui.chat = { open: true, tab: 'chats', thread: name }; rerender(); refocus(ui.chat, true); },
        onOrder: (c) => {
          ui.orderTo = c;
          ui.proposal = null;
          ui.draft = { to: c.name, channel: c.channel_keys?.[0] ?? '', text: ui.draft?.text ?? '' };
          ui.chat = { ...ui.chat, open: false };
          ui.tab = 'desk';
          toForms();
          rerender();
          root.querySelector('.rl-write textarea')?.focus();
        },
      }),
    });
  }

  /** The newspaper icon beside Messages, and the desk while it is open; the paper on show is marked seen. */
  function pressDesk() {
    const papers = pressPapers(rv.documents.documents);
    const read = pressSeenBy.read();
    const marks = pressMarks(pressCounts(papers), read, { ...ui.press, tab: pressTab(papers, ui.press.tab, Array.isArray(rv.world)) });
    if (marks !== read) pressSeenBy.write(marks);
    return pressDock({
      state: ui.press,
      onState: (next) => {
        if (!next.open || next.tab !== ui.press.tab) ui.pressPage = null;
        if (!next.open && mapFirst()) return closeOver();
        ui.press = next;
        rerender();
        if (!next.open) pressFocus(root);
      },
      papers,
      marks,
      page: ui.pressPage,
      onOpen: readPress,
      onClosePage: () => { ui.pressPage = null; rerender(); },
      onFlag: (on) => flag(on, ui.pressPage),
      world: rv.world,
      onAsk: writeOrder,
    });
  }

  /** An order a development suggests: its words go into the order form on the desk, nothing is filed. */
  function writeOrder(text) {
    const written = offerOrder(ui, text);
    ui.press = { ...ui.press, open: false };
    ui.pressPage = null;
    ui.tab = 'desk';
    toForms();
    rerender();
    root.querySelector(written ? '.rl-write textarea' : '.rl-offer button.ghost')?.focus();
  }

  /** Replace or Keep mine on the offer line; focus goes back to the order's words. */
  function answerOffer(replace) {
    settleOffer(ui, replace);
    rerender();
    root.querySelector('.rl-write textarea')?.focus();
  }

  /** The wake player's own arguments: the seat's map, its shapes once here, the record and the line at Done. */
  function playArgs(pages) {
    const file = rv.map?.file;
    if (file && !shapesFor(file)) loadShapes(file);
    return {
      pages, map: rv.map, shapes: shapesFor(file), record: rv.record, comeBack: comeBackLine(rv), battles: rv.battles,
      reduced: reducedMotion(),
    };
  }

  /** The sheet of wakes this seat missed, while it has not been closed in this room; null otherwise. */
  function missedDialog() {
    if (!ui.missed) return null;
    // the player is made once: a redraw moves it into the new sheet where it stands
    ui.missedPlay ??= wakePlayer(playArgs(ui.missed));
    const sheet = missedSheet({ pages: ui.missed, record: rv.record, play: ui.missedPlay, onClose: () => sheet.close() });
    sheet.addEventListener('close', () => { ui.missed = null; ui.missedPlay = null; });
    return sheet;
  }

  /** The wake just opened, playing in its own dialog until it is closed; null otherwise. */
  function playingDialog() {
    if (!ui.playing || ui.playing.inSheet) return null;
    const d = playbackDialog({ pages: ui.playing.pages, play: ui.playing.play, onClose: () => { ui.playing = null; d.remove(); } });
    ui.playing.close = () => { if (d.open) d.close(); };
    return d;
  }

  /** The catch-up pages for `body`, or none; a server that did not answer is said in the status line. */
  async function catchupPages(body) {
    try {
      return missedPages(await api.catchup(body));
    } catch (ex) {
      if (ex.status === 0 || ex.status >= 500) {
        ui.error = `${MISSED_TITLE} could not be loaded. ${ex.message}`;
        showStatus();
      }
      return [];
    }
  }

  /**
   * Ask the server once for the wakes this seat missed (it names the range from the log), and,
   * once a page, for the wake just opened when this page has not played it. Missed wakes open
   * their sheet over whatever is open, the playback of each wake in turn inside it, so closing it
   * returns to the wake's own sheet; the wake just opened alone plays in its own dialog. What has
   * played is held in the page only (`ui.playedTo`), never in storage. A refusal plays nothing.
   */
  async function loadMissed() {
    const latest = rv.record?.wake?.number;
    // a wake page with no days passed is the game's start: nothing has happened to play
    const playLatest = Number.isInteger(latest) && rv.record.wake.days_passed > 0 && latest > (ui.playedTo ?? -1);
    if (ui.missedAsked && !playLatest) return;
    if (playLatest) ui.playedTo = latest;
    let pages = [];
    if (!ui.missedAsked) {
      ui.missedAsked = true;
      pages = await catchupPages();
    }
    if (playLatest && !pages.some((p) => p.number === latest)) {
      const now = (await catchupPages({ first: latest, last: latest })).filter((p) => p.number === latest);
      if (pages.length) pages = missedPages({ pages: [...pages, ...now] });
      else if (now.length) {
        // the room may have been drawn again while the reply was out: the newest draw shows it
        const live = root.isConnected ? root : lastRoot;
        // the What happened sheet of this wake, while it is up, holds the playback where forces moved
        const sheet = happenedDue(rv.record.wake, shown, ui.happenedSeen) ? live?.querySelector('dialog.rl-hap') : null;
        const playing = { pages: now, inSheet: Boolean(sheet) };
        playing.play = wakePlayer({ ...playArgs(now), onEnd: sheet ? undefined : () => playing.close?.() });
        if (!playing.play) return;
        ui.playing = playing;
        if (sheet) {
          sheet.querySelector('.rl-hap-actions')?.before(playing.play);
          return;
        }
        if (!live?.isConnected) return;
        const d = playingDialog();
        live.append(d);
        d.showModal();
        return;
      }
    }
    if (!pages.length) return;
    ui.missed = pages;
    const sheet = missedDialog();
    root.append(sheet);
    sheet.showModal();
  }

  /** The two dossiers behind the header's names, and the sheet a new wake opens with. */
  function sheets() {
    const date = worldDate(rv.clock.world_date);
    const close = (d) => () => d?.close();
    const character = characterDossier({ name: seatName, desk: rv.desk, dossier: rv.dossier, onClose: () => close(character)() });
    const setting = settingDossier({ name: game.name, setting: rv.setting, date, onClose: () => close(setting)() });
    const page = rv.record?.wake;
    const happened = happenedDue(page, shown, ui.happenedSeen)
      ? happenedSheet({
        record: rv.record, situation: rv.situation, agenda: rv.agenda, date,
        places: rv.map?.places, play: ui.playing?.inSheet ? ui.playing.play : null,
        onClose: () => happened?.close(),
      })
      : null;
    // Esc closes a dialog without its button: the close event counts either way
    happened?.addEventListener('close', () => {
      ui.happenedSeen = page.number;
      shown.write(page.number);
      if (ui.playing?.inSheet) ui.playing = null;
    });
    return { character, setting, happened, intro: intro(happened) };
  }

  /**
   * The opening, once per game in this browser and only before the seat's first order:
   * the crawl (unless the host already watched it at Begin), then the seat's splash. The
   * What happened sheet waits behind it.
   */
  function intro(after) {
    const stage = introStage(storage(), game.id, !rv.record?.orders?.length);
    if (!stage) return null;
    const drop = (d) => { if (d.open) d.close(); d.remove(); };
    const splash = () => {
      const s = seatSplash({
        name: seatName,
        model: splashModel(seatName, rv.desk, rv.dossier, startOverview(rv)),
        brief: () => rv.brief,
        onDone: () => {
          markIntro(storage(), game.id, 'splash');
          drop(s);
          if (after?.isConnected && !after.open) after.showModal();
        },
        onPaper: (p) => {
          pickPanel(ui, { tab: 'papers', side: 'papers' }, phoneWidth());
          open({ id: p.id });
        },
      });
      return s;
    };
    const paragraphs = crawlParagraphs(rv.setting);
    if (stage === 'splash' || !paragraphs.length) return splash();
    const crawl = introCrawl({
      title: game.name,
      paragraphs,
      ready: true,
      onDone: () => {
        markIntro(storage(), game.id, 'crawl');
        drop(crawl);
        const next = splash();
        root.append(next);
        next.showModal();
      },
    });
    return crawl;
  }

  /** Words for the order form, from a contact, a letter or the news: in the map-first room the Forms sheet holds it. */
  function toForms() {
    if (mapFirst()) openSheet(ui, 'forms');
  }

  /** Close the open sheet and put focus back on what opened it. */
  function closeOver() {
    if (!openSheetOf(ui)) return;
    const from = closeSheet(ui);
    if (ui.tab === 'messages') ui.tab = 'desk';
    // a sheet opened from a line of the list goes back to it: on a phone the list opens again
    if (from?.need && !needsRail()) openSheet(ui, 'needs', { tab: 'needs' });
    rerender();
    needsTarget(from)?.focus();
  }

  /** Where focus goes back to from a sheet opened by `from`: a line's action, the Needs button, or `returnTarget`. */
  function needsTarget(from) {
    if (from?.need) return [...root.querySelectorAll('.rl-needs .rl-need-act')].find((b) => b.getAttribute('data-need') === from.need) ?? null;
    if (from?.tab === 'needs') return root.querySelector('.rl-needsbar .rl-needs-btn');
    if (from?.home) return root.querySelector('.rl-strip .rl-home-own');
    if (from?.nations) return returnTarget(root, { group: 'world' });
    if (from?.aims) return root.querySelector('.rl-aimmark');
    if (from?.timeline) return root.querySelector('.rl-tl-head');
    if (from?.battle) return [...root.querySelectorAll('.rl-mapfirst g.rl-bt-mark')].find((g) => g.getAttribute('data-area') === from.battle) ?? null;
    return returnTarget(root, from);
  }

  /**
   * The nation's band in the strip: the home sheet over the map (map-first), or under the strip
   * (today's room); a second tap closes it, and focus stays on the band.
   */
  function toggleHome() {
    if (mapFirst()) {
      if (openSheetOf(ui) === 'home') return closeOver();
      openSheet(ui, 'home', { group: 'world' }); // its band is on the Nations part
      rerender();
      root.querySelector('.rl-over-title')?.focus();
      return;
    }
    ui.homeOpen = !ui.homeOpen;
    rerender();
    root.querySelector('.rl-strip .rl-home-own')?.focus();
  }

  /** The home sheet's options: Speak to the nation, and the days the last close walked (what it moved). */
  const homeOpts = () => ({ onSpeak: speak, days: rv.record?.wake?.days_passed ?? null });

  /** "Speak to the nation": the free-writing form, under the nation's themes and the cap, with focus in its words. */
  function speak() {
    ui.speak = true;
    ui.proposal = null;
    if (mapFirst()) openSheet(ui, 'forms');
    else ui.tab = 'desk'; // the Board holds the order form too; on a phone the Desk tab shows it
    rerender();
    const write = root.querySelector('.rl-write');
    write?.scrollIntoView?.({ block: 'start' });
    write?.querySelector('.rl-directive textarea')?.focus();
  }

  /** The phone's Needs button: opens the list as the one sheet, or closes it. */
  function toggleNeeds() {
    if (openSheetOf(ui) === 'needs') return closeOver();
    openSheet(ui, 'needs', { tab: 'needs' });
    rerender();
    root.querySelector('.rl-needs h2')?.focus();
  }

  /** A line's one action: its matter's sheet, a sheet of the room, the map centred on an area, or Done. */
  function needAction(line) {
    const { action } = line;
    if (action.to === 'commit') return act(commitBusy(rv.wake), 'commit', {});
    if (action.to === 'map') {
      if (openSheetOf(ui)) closeSheet(ui);
      const theatre = ui.theatre ?? { mode: 'map', scope: 'reports' };
      const centre = areaCentre(rv.map, shapesFor(rv.map?.file), action.area);
      ui.theatre = { ...theatre, mode: 'map', area: action.area, ...(centre ? { frame: '', zoom: 2, centre } : {}) };
      rerender();
      root.querySelector('.rl-mapfirst .rl-area-sheet button')?.focus();
      return;
    }
    if (action.to === 'battle') {
      ui.battle = action.area;
      openSheet(ui, 'battle', { need: line.key });
      rerender();
      root.querySelector('.rl-over-title')?.focus();
      return;
    }
    if (action.to === 'ask-for') return askFor(action.id);
    if (action.to === 'send-anyway') return act('Sending it anyway…', 'send-anyway', { order_id: action.id });
    if (action.to === 'incident') return act('Answering…', 'answer', { item: action.id, verdict: action.verdict });
    if (action.to === 'capital') return capitalAt(action.q);
    if (action.to === 'ask') {
      ui.ask = action.id;
      openSheet(ui, 'ask', { need: line.key });
      rerender();
      root.querySelector('.rl-over-title')?.focus();
      return;
    }
    if (action.to === 'matter') ui.matter = action.id;
    openSheet(ui, action.to === 'matter' ? 'matter' : action.sheet, { need: line.key });
    rerender();
    root.querySelector('.rl-over-title')?.focus();
  }

  /** A sheet's tab: opens it over the map with focus on its title; its own tab closes it again. `from` is what opened it. */
  function toggleOver(name, from = { tab: name }) {
    if (openSheetOf(ui) === name) return closeOver();
    openSheet(ui, name, from);
    rerender();
    root.querySelector('.rl-over-title')?.focus();
  }

  /** A standard form filed from a sheet: what was kept for it is dropped, so the redraw after does not fill it again. */
  function fileLever(v, then) {
    ui.sheetForms = forgetForm(ui.sheetForms, v.lever);
    markFiled(root, v.lever);
    return act('Sending it…', 'lever', v, then);
  }

  /**
   * A form's check before it is sent (LKM), with `locks` on; null with it off. The last reply on
   * the status line goes as the check starts, so it is never read as this form's answer.
   */
  const sendCheck = () => {
    const check = formCheck(rv);
    return check && ((v) => {
      ui.said = null;
      ui.error = null;
      showStatus();
      return check(v);
    });
  };

  /** Ask for the seat's held order `id` (LKM): the server files the ask and says so. */
  const askFor = (id) => act('Asking…', 'ask', { order_id: id });

  /**
   * File a locked order to be held, then ask for it (LKM), or send it anyway (DFB, `then` action
   * `send-anyway`): the order the server newly holds is the one held line in the re-read room that
   * was not there before; if the server held none (the seat is done for today, or it went out after
   * all), its own reply stands and nothing more is sent.
   */
  function fileAndThen(busy, action, v, then) {
    ui.sheetForms = forgetForm(ui.sheetForms, v.lever);
    markFiled(root, v.lever);
    const before = new Set(heldLines(rv).map((l) => l.id));
    return work(busy, async () => {
      const r = await api.realism('lever', v);
      ui.said = r.reply || null;
      then?.(r);
      if (r.refused) return;
      const now = (await api.me())?.game?.view?.realism;
      const fresh = heldLines(now).filter((l) => !before.has(l.id) && !l.asked);
      if (fresh.length !== 1) return;
      const next = await api.realism(action, { order_id: fresh[0].id });
      ui.said = [r.reply, next.reply].filter(Boolean).join(' ') || null;
    });
  }
  const fileAndAsk = (v, then) => fileAndThen('Filing it and asking…', 'ask', v, then);
  const fileAndSend = (v, then) => fileAndThen('Sending it anyway…', 'send-anyway', v, then);

  /** The board's calls: a form is filed through the sheet's bookkeeping, a locked one filed and asked for. */
  const boardAct = (m, a, b, t) => (a === 'lever' ? fileLever(b, t) : a === 'lever-ask' ? fileAndAsk(b, t)
    : a === 'lever-anyway' ? fileAndSend(b, t) : act(m, a, b, t));

  /** A pick in the map-first room: a force opens its sheet, the map's switches redraw it, a person stays on the Court. */
  function pickOnMap(p) {
    const place = switchPlace(document.activeElement);
    if (!Object.keys(p).length && ui.orderTo) { // the Court's "Write them an order"
      openSheet(ui, 'forms');
      rerender();
      root.querySelector('.rl-over .rl-write textarea')?.focus();
      return;
    }
    if (p.tab === 'messages') { // the Court's "Ask them a question"
      openSheet(ui, 'messages');
      rerender();
      refocus(ui.chat);
      return;
    }
    if (p.theatre?.battle) { // a battle's mark: its sheet opens over the map, as every sheet does
      ui.theatre = { ...p.theatre, battle: null };
      ui.battle = p.theatre.battle;
      openSheet(ui, 'battle', { battle: ui.battle });
      rerender();
      root.querySelector('.rl-over-title')?.focus();
      return;
    }
    if (p.theatre) ui.theatre = p.theatre;
    if (p.piece?.kind === 'force') {
      ui.piece = p.piece;
      openSheet(ui, 'piece', { mark: p.piece.name });
      rerender();
      root.querySelector('.rl-over-title')?.focus();
      return;
    }
    if (p.piece !== undefined) {
      if (p.piece === null && openSheetOf(ui) === 'piece') return closeOver();
      ui.piece = p.piece;
    }
    rerender();
    switchAt(root, place)?.focus();
  }

  let pending = null;
  const pick = (p) => {
    if (mapFirst()) return pickOnMap(p);
    // the Court's "Write them an order" (an empty pick): on a phone the card is a sheet over the form, so it closes first
    if (!Object.keys(p).length && phoneWidth() && ui.piece?.kind === 'person') p = { piece: null };
    const place = switchPlace(document.activeElement);
    pickPanel(ui, p, phoneWidth());
    rerender();
    if (p.tab === 'messages') refocus(ui.chat);
    else if (p.piece) root.querySelector('.rl-board .rl-mk[aria-pressed="true"]')?.focus();
    else switchAt(root, place)?.focus();
  };
  /** Hide the first-wake card for this wake, then put focus on the pin (Board) or the view switch. */
  function dismissFirstWake() {
    ui.firstWakeOff = rv.wake.wake;
    rerender();
    (root.querySelector('.rl-pin') ?? root.querySelector('.rl-viewswitch button') ?? root.querySelector('.rl-needs h2'))?.focus();
  }
  /** What the open sheet holds: one of the room's panels, built as today's room builds it. */
  function sheetBody(name) {
    if (name === 'papers') return papers();
    // what waits on the seat is in the list; its matters open their own sheet
    if (name === 'orders') return [ideasSlot, sentPart(), commitPanel(rv.wake, { act })];
    if (name === 'matter') {
      const found = matterOf(rv, ui.matter);
      if (!found) return null;
      const panel = needsAnswer({ ...rv.agenda, items: [found.item] }, { act, today: rv.clock.world_date });
      panel.querySelector('h2')?.remove();
      panel.removeAttribute('aria-labelledby');
      return panel;
    }
    if (name === 'forms') {
      const forms = standardForms(rv.desk, { onSubmit: fileLever, entities: entityChoices(rv.desk), check: sendCheck(), onAsk: fileAndAsk, onAnyway: fileAndSend });
      if (forms) forms.open = true;
      const find = formSearch(withCostStrips(forms, rv.desk?.levers, rv.court), rv.desk?.levers, ui.formQuery, (q) => { ui.formQuery = q; });
      return [h('p', { class: 'hint rl-write-hint' }, WRITE_HINT), writeBlock(), find, stylePicker(rv.style, { act })];
    }
    if (name === 'messages') {
      const panel = dock().querySelector('.rl-msgr-panel');
      panel?.querySelector('.rl-msgr-head')?.remove();
      panel?.removeAttribute('aria-labelledby');
      return panel;
    }
    if (name === 'ask') return askSheet(rv, ui.ask, { onFile: fileLever });
    if (name === 'home') return rv.home ? homeSheet(rv.home, homeOpts()) : null;
    if (name === 'diplomacy') return hasDiplomacy(rv) ? diplomacy() : null;
    if (name === 'court') return courtBoard(rv, ui, { pick, act });
    if (name === 'people') return peoplePanel();
    if (name === 'battle') {
      const sheet = battleSheet(rv, ui.battle, { act, pick, theatre: ui.theatre ?? {} });
      sheet?.querySelector('h3')?.remove();
      sheet?.removeAttribute('aria-labelledby');
      return sheet;
    }
    if (name === 'capital') return capitalOpen() ? capitalSheet(capitalOpen()) : null;
    if (name === 'nations') return nationsBody();
    if (name === 'standing') return standingGrid(rv, { onOpen: cardFromGrid });
    if (name === 'aims') return stakesStrip(rv.stakes, ownAimHooks()) ?? h('p', { class: 'hint' }, 'You hold no aims in this game.');
    if (name === 'press') {
      const desk = pressDesk().querySelector('dialog.rl-pd');
      desk?.querySelector('.rl-pd-head')?.remove();
      return desk ? [...desk.childNodes] : null;
    }
    return null;
  }

  /** A picked force's sheet: what it is and where, then the forms that move it, each with its cost strip. */
  function pieceBody(forms) {
    const panel = piecePanel(rv, ui.piece, open, { pick, act: boardAct, theatre: ui.theatre ?? {} });
    panel.querySelector('.rl-sheet-close')?.remove();
    panel.querySelector('h2')?.remove();
    panel.removeAttribute('aria-labelledby');
    if (hasCapital(rv)) { // a lock's line opens its question on the Capital board
      for (const li of panel.querySelectorAll('.rl-piece-held li[data-held]')) {
        li.append(' ', h('button', { type: 'button', class: 'rl-btn rl-held-capital', onclick: () => capitalAt(`held:${li.getAttribute('data-held')}`) }, 'Open in the Capital'));
      }
    }
    return [panel, withCostStrips(forms, rv.desk?.levers, rv.court), takingForms(forms)];
  }

  /**
   * The other forms that take the picked force, each open with it filled in: a
   * `<section class="rl-piece-forms">`, or null. `moving` is the section of the forms that move it.
   */
  function takingForms(moving) {
    const mark = (rv.map?.marks ?? []).find((m) => m.name === ui.piece?.name);
    const shown = new Set([...(moving?.querySelectorAll('.rl-instrument') ?? [])].map((i) => i.getAttribute('data-lever')));
    const found = formsTaking(rv.desk?.levers, mark, shown);
    if (!found.length) return null;
    const items = found.map(({ lever, param, value }) => {
      const item = standardForm(lever, {
        force: param === 'force' ? value : null, onSubmit: fileLever, entities: entityChoices(rv.desk), check: sendCheck(), onAsk: fileAndAsk, onAnyway: fileAndSend,
      });
      const field = item.querySelector(`select[name="${param}"]`);
      if (field) field.value = value;
      item.querySelector('.rl-instrument-head [aria-expanded="false"]')?.click();
      return item;
    });
    return withCostStrips(h('section', { class: 'rl-piece-forms', 'aria-labelledby': 'rl-piece-forms-h' },
      h('h3', { id: 'rl-piece-forms-h' }, `Forms for ${mark.name}`),
      h('ul', { class: 'rl-instruments', role: 'list' }, items)), rv.desk?.levers, rv.court);
  }

  /** The parts' counts: unread papers and newspapers. What waits on the seat is counted on the list. */
  const sheetCounts = () => ({
    papers: Number(rv.documents?.unread) || 0,
    press: pressUnread(pressPapers(rv.documents.documents), pressSeenBy.read()),
  });
  /** The messenger's unread count, on the bar's chat button. */
  const chatUnread = () => unread(threadCounts(threads()), seen.read()).total;

  /** Whether the room is the map-first room on Beginner, which folds away what a seat can open. */
  const beginner = () => mapFirst() && rv.style === 'beginner';
  /** The parts Beginner leaves out of their group until a line in the list is in them. */
  const QUIET = ['court', 'home', 'diplomacy'];
  /** Whether part `key` has a body in this game: Nations and Standing need a nation to list, Home and Diplomacy their blocks. */
  const hasPart = (key) => (key === 'nations' ? nationRows(rv).length > 0 : key === 'home' ? Boolean(rv.home)
    : key === 'diplomacy' ? hasDiplomacy(rv) : key === 'standing' ? nationRows(rv).length > 0 : true);
  /** Every part the room has, by group, for the menu's quiet route on Beginner. */
  const everyPart = () => GROUPS.map((g) => ({ ...g, parts: g.parts.filter(([key]) => hasPart(key)) })).filter((g) => g.parts.length);
  /** The parts drawn in their groups: on Beginner a quiet part only while a line is in it or it is open. */
  const drawnParts = (open, marks) => GROUPS.flatMap((g) => g.parts.map(([key]) => key))
    .filter((key) => hasPart(key) && (!beginner() || !QUIET.includes(key) || marks[key] || key === open));

  /** The Nations part: the nations as a bar chart, with a card each; null with neither an economy nor a home block. */
  function nationsBody() {
    const onOffer = mapFirst() && rv.agreements ? offerTo : null;
    ui.nations ??= {};
    return nationsPanel(rv, { state: ui.nations, act, onOffer, onHome: homeFromCard });
  }

  /** A tile of the Standing grid: World opens at Nations with that nation's card open. */
  function cardFromGrid(key) {
    ui.nations ??= {};
    ui.nations.open = key;
    ui.nations.eco = false;
    openSheet(ui, 'nations', { group: 'world' });
    rerender();
    root.querySelector('.rl-over .rl-nb-card-title')?.focus();
  }

  /** The seat's own card's At home: World opens at Home. */
  function homeFromCard() {
    openSheet(ui, 'home', { group: 'world' });
    rerender();
    root.querySelector('.rl-over-title')?.focus();
  }

  /** A nation's card's Make an offer: World opens at Diplomacy with the offer made out to that nation. */
  function offerTo(nation) {
    ui.dpl ??= freshDiplomacy();
    ui.dpl.offer.parties = [...new Set([...ui.dpl.offer.parties, nation.key])];
    ui.dpl.reading = null;
    openSheet(ui, 'diplomacy', { group: 'world' });
    rerender();
    root.querySelector('.rl-over .rl-dp-builder textarea')?.focus();
  }

  /** A group's tab: its sheet opens on the part last open in it; the tab of the open group closes it. */
  function toggleGroup(key, drawn) {
    const group = GROUPS.find((g) => g.key === key);
    if (groupOf(openSheetOf(ui)) === group) return closeOver();
    toggleOver(partFor(group, ui.parts?.[key], drawn), { group: key });
  }

  /** A part's tab in an open group's sheet: that part, with the focus kept on its tab. */
  function pickPart(key) {
    openSheet(ui, key, ui.sheetFrom ?? { group: groupOf(key)?.key });
    rerender();
    root.querySelector(`.rl-over .rl-parts button[data-sheet="${key}"]`)?.focus();
  }

  /** The bar's chat button: the messenger as a sheet; a second press closes it. */
  function toggleChat() {
    if (openSheetOf(ui) === 'messages') return closeOver();
    openSheet(ui, 'messages');
    rerender();
    refocus(ui.chat);
  }

  /** An aim's mark on the bar: the aims' sheet, with that aim's drill-down open; a second press closes it. */
  function toggleAims(aim) {
    if (openSheetOf(ui) !== 'aims') openAim(aim);
    toggleOver('aims', { aims: true });
  }

  /** The map asks for the whole viewport, or gives it back: the bar hides, the list, a sheet and Done stay. */
  function setFull(on) {
    ui.full = Boolean(on);
    rerender();
  }

  /**
   * The board the map-first room shows: the Capital only while it has something to show and no
   * piece's sheet is open (a piece lives on the map); else the map. The first is the one kept for
   * the device, else the Capital for a seat on the political path.
   */
  function shownBoard(name) {
    ui.mapBoard ??= startBoard({ stored: storage()?.getItem(BOARD_KEY) ?? null, path: rv.desk?.path ?? null });
    return ui.mapBoard === 'capital' && hasCapital(rv) && name !== 'piece' ? 'capital' : 'map';
  }

  /** The switch: the board picked is drawn and kept for the device, with focus on its button. */
  function setBoard(key) {
    ui.mapBoard = key;
    try { storage()?.setItem(BOARD_KEY, key); } catch { /* storage refused: kept for the page */ }
    rerender();
    root.querySelector(`.rl-board-switch button[data-board="${key}"]`)?.focus();
  }

  /** The Capital opened at question `q` (a held order's, from its piece's sheet), with focus on its row. */
  function capitalAt(q) {
    if (openSheetOf(ui)) closeSheet(ui);
    ui.cap = { q };
    setBoard('capital');
    root.querySelector(`.rl-cap button[data-key="${q}"]`)?.focus();
  }

  /**
   * A capital picked on the map: the seat's own opens the Capital board, another nation's its
   * public lines as a sheet over the map.
   */
  function openCapitalLine(line) {
    if (line.nation.relation === 'own') {
      if (openSheetOf(ui)) closeSheet(ui);
      ui.cap = {};
      return setBoard('capital');
    }
    ui.capital = line.nation.name;
    openSheet(ui, 'capital', { tab: 'capital' });
    rerender();
    root.querySelector('.rl-over-title')?.focus();
  }

  /** The server's capital line for the nation whose sheet is open; null once it is gone. */
  const capitalOpen = () => (rv.capitals ?? []).find((c) => c.nation.name === ui.capital && c.nation.relation !== 'own') ?? null;

  /** What the Capital board's controls open in the room. */
  const capitalHandlers = () => ({
    board: setBoard,
    person: openPerson,
    map: (mark) => { ui.mapBoard = 'map'; pickOnMap({ piece: { kind: 'force', name: mark.name } }); },
    ask: (l) => askFor(l.id),
    openAsk: (a) => { ui.ask = a.id; toggleOver('ask', { capital: a.id }); },
    conference: () => toggleOver('diplomacy', { group: 'world' }),
    speak,
    full: (on) => { setFull(on); root.querySelector('.rl-cap button.rl-cap-full')?.focus(); },
    offerCheck: (body) => api.realism('check', body),
    officeVote: (body) => work('Sealing your choice…', async () => {
      const r = await api.realism('office-vote', body);
      ui.said = r.reply || null;
    }),
    offer: (body) => work('Making the offer…', async () => {
      const r = await api.realism('offer', body);
      ui.said = r.reply || null;
    }),
  });

  /** The season's strip opens or closes, with the focus kept on its head. */
  function toggleTimeline() {
    ui.timeline = !ui.timeline;
    rerender();
    root.querySelector('.rl-tl-head')?.focus();
  }

  /** A row of the season's strip opens its item where it lives: the line's own action, the aims, a sheet or the piece. */
  function openMark({ open: to }) {
    ui.timeline = false;
    if (to.to === 'need') return to.line.action ? needAction(to.line) : toggleNeeds();
    if (to.to === 'piece') return pickOnMap({ piece: { kind: 'force', name: to.name } });
    openSheet(ui, to.to === 'aims' ? 'aims' : to.sheet, { timeline: true });
    rerender();
    root.querySelector('.rl-over-title')?.focus();
  }

  /** The own aim's ladder (from the server) and what follows a set: the room is read again. */
  function ownAimHooks() {
    return { ownAim: rv.own_aim ?? null, onAimSet: () => refresh() };
  }

  /** The first-day card's words with its Dismiss, for the list's first row; null when it is not due. */
  function firstWake() {
    const words = firstWakeWords(rv.wake, { dismissed: ui.firstWakeOff, beginner: beginner(), own: ownAimOf(rv.stakes) });
    return words && { ...words, onDismiss: dismissFirstWake };
  }

  /** The map-first room: one bar, the map filling the rest with the status line over its foot, and the open sheet over it. */
  function mapFirstRoom({ menuBtn, status }) {
    let name = openSheetOf(ui);
    const board = shownBoard(name);
    const map = board === 'map' ? theatreBoard(rv, ui, { pick, act: boardAct, open, onCapital: openCapitalLine, hooks: { overlay: true, onFull: setFull } }) : null;
    const forms = map?.querySelector('.rl-theatre-forms') ?? null;
    forms?.remove();
    if (map && hasCapital(rv)) (map.querySelector('.rl-tm-tools-start') ?? map.querySelector('.rl-bar') ?? map).prepend(boardSwitch('map', setBoard));
    const drawn = board === 'capital' ? capitalBoard(rv, ui.cap ??= {}, capitalHandlers()) : map;
    if (name === 'piece' && !(rv.map?.marks ?? []).some((m) => m.name === ui.piece.name)) { // the force left the map
      closeSheet(ui);
      name = null;
    }
    if (name === 'matter' && !matterOf(rv, ui.matter)) { // the matter is settled
      closeSheet(ui);
      name = null;
    }
    if (name === 'ask' && !askOf(rv, ui.ask)) { // the ask is settled
      closeSheet(ui);
      name = null;
    }
    if (name === 'battle' && !battleAt(rv, ui.battle)) { // the battle is over
      closeSheet(ui);
      name = null;
    }
    if (name === 'capital' && !capitalOpen()) { // the nation is out of the seat's view
      closeSheet(ui);
      name = null;
    }
    const piece = name === 'piece' ? ui.piece.name : null;
    const title = piece ?? (name === 'matter' ? matterOf(rv, ui.matter).title
      : name === 'ask' ? ASK_TITLE : name === 'battle' ? battleTitle(battleAt(rv, ui.battle), rv.clock?.world_date)
        : name === 'aims' ? AIMS_TITLE : name === 'capital' ? capitalOpen().nation.name : undefined);
    const lines = needLines(rv);
    const marks = Object.fromEntries(QUIET.map((key) => [key, sheetMarks(lines)[key] ?? 0]));
    const counts = beginner() ? { ...sheetCounts(), ...marks } : sheetCounts();
    const shown = drawnParts(name, marks);
    // the list is its own sheet on a phone, and a rail beside the map from 1024 px
    const sheet = name && name !== 'needs'
      ? overSheet({ name, title, piece, body: piece ? pieceBody(forms) : sheetBody(name), onClose: closeOver, parts: partTabs(name, counts, pickPart, shown) })
      : null;
    if (sheet) restoreForms(sheet, ui.sheetForms);
    const done = () => act(commitBusy(rv.wake), 'commit', {});
    const listed = needsList(rv, lines, {
      open: name === 'needs', onAction: needAction, onDone: done, onClose: closeOver, top: beginner() ? 1 : null,
      comeBack: comeBackLine(rv), first: firstWake(),
    });
    const tabs = [groupTabs(name, counts, (key) => toggleGroup(key, shown), shown), chatButton(name === 'messages', chatUnread(), toggleChat)];
    const aims = aimMarks(rv.stakes?.aims, { open: name === 'aims', onOpen: toggleAims });
    const season = timelineStrip(rv, lines, { open: ui.timeline, onToggle: toggleTimeline, onOpen: openMark });
    const at = season ? ` rl-tl-on${ui.timeline ? ' rl-tl-open' : ''}` : '';
    const section = lightTogether(h('section', { class: `rl-mapfirst-map${at}`, 'aria-label': board === 'capital' ? 'The Capital' : 'The map', 'data-board': board }, drawn, season, status));
    if (season && ui.timeline) afterLayout(() => fitStrip(section));
    return [roomBar(rv, { tabs, menu: menuBtn, aims, act }),
      h('main', { class: `rl-mapfirst${sheet ? ' sheeted' : ''}`, 'aria-label': 'Map' },
        listed, section, sheet),
      needsBar(rv, lines, { open: name === 'needs', onToggle: toggleNeeds, onDone: done })];
  }

  /**
   * The switch again in the game menu, shown on a phone only (c-capital.css), where the map's
   * controls have no room for it; the map has no focusable switch there, so Map gives the
   * keyboard back to the Game button.
   */
  function menuBoard(close) {
    if (!hasCapital(rv)) return null;
    const pick = (key) => {
      close();
      setBoard(key);
      if (key === 'map') root.querySelector('.rl-menu-btn')?.focus();
    };
    return h('div', { class: 'rl-menu-board' }, boardSwitch(shownBoard(openSheetOf(ui)), pick));
  }

  /** The map-first room's game menu adds what the page header holds in today's room. */
  const menuExtra = ({ character, setting, bug }) => (close) => h('section', { class: 'rl-menu-game', 'aria-labelledby': 'rl-menu-game-h' },
    h('h3', { id: 'rl-menu-game-h' }, 'This game'),
    menuBoard(close),
    h('div', { class: 'row' },
      h('button', { type: 'button', class: 'ghost', 'aria-haspopup': 'dialog', 'aria-label': `${game.name}: open the setting`, onclick: () => { close(); setting?.showModal(); } }, game.name),
      seatName ? h('button', { type: 'button', class: 'ghost', 'aria-haspopup': 'dialog', 'aria-label': `${seatName}: open the dossier`, onclick: () => { close(); character?.showModal(); } }, seatName) : null),
    rv.desk?.office ? h('p', { class: 'hint' }, [rv.desk.office, rv.desk.principals?.length ? `answers to ${rv.desk.principals.join(', ')}` : null].filter(Boolean).join(', ')) : null,
    wakeHeader(rv.wake, { act }),
    paceHeader(rv.clock),
    h('p', { class: 'hint' }, `Signed in as ${me.account.handle}`),
    h('div', { class: 'row' },
      h('button', { type: 'button', class: 'ghost', 'aria-haspopup': 'dialog', onclick: () => { close(); bug.showModal(); } }, icon('bug', 14), 'Report'),
      h('button', { type: 'button', class: 'ghost', onclick: () => { close(); ctx.signOut?.(); } }, icon('out', 14), 'Sign out')));

  function build() {
    root.classList.toggle('rl-layout-map', mapFirst()); // c-sheets.css trims the header on a phone
    root.classList.toggle('rl-full', mapFirst() && Boolean(ui.full));
    foldEconomy(beginner());
    foldOdds(beginner());
    const { character, setting, happened, intro: opening } = sheets();
    const bug = mapFirst() ? reportDialog() : null;
    const [menuBtn, menu] = gameMenu(game, ctx, work, (next) => {
      setRoomLayout(next);
      rerender();
      root.querySelector('.rl-menu-btn')?.focus();
    }, beginner() ? { sheets: everyPart(), onOpen: (key) => { openSheet(ui, key); rerender(); } } : null,
    mapFirst() ? menuExtra({ character, setting, bug }) : null);
    pending = opening ?? happened;
    status = h('div', { class: 'rl-status', role: 'status', 'aria-live': 'polite' });
    showStatus();
    const dialogs = [menu, character, setting, bug, happened, opening, missedDialog(), playingDialog()];
    if (mapFirst()) return [...mapFirstRoom({ menuBtn, status }), ...dialogs].filter(Boolean);
    const extra = [
      h('span', { class: 'divider', 'aria-hidden': 'true' }),
      h('div', { class: 'stack rl-clock' }, paceHeader(rv.clock)),
      wakeHeader(rv.wake, { act }),
      menuBtn,
    ];
    const top = [
      header({
        ...ctx, game, role: 'Campaign', extra,
        identity: { name: seatName, office: rv.desk.office, principal: rv.desk.principals.join(', ') || null },
        onSetting: setting && work.idle() ? () => setting.showModal() : null,
        onIdentity: character && work.idle() ? () => character.showModal() : null,
      }),
      withHome(statusStrip(rv, ui, { act }), rv,
        { open: Boolean(ui.homeOpen && rv.home), onOpen: toggleHome, sheet: rv.home ? homeSheet(rv.home, homeOpts()) : null }),
    ];
    return [
      ...top,
      stakesStrip(rv.stakes, { aims: ui.view !== 'board', ...ownAimHooks() }),
      status,
      firstWakeCard(rv.wake, { dismissed: ui.firstWakeOff, onDismiss: dismissFirstWake, own: ownAimOf(rv.stakes) }),
      viewSwitch(ui, pick),
      ...(ui.view === 'board' ? [
        newsBlock(whatChanged(rv.documents), (id) => readPress({ id })),
        boardView(rv, ui, { pick, act: (m, a, b, t) => (a === 'lever-ask' || a === 'lever-anyway' ? boardAct(m, a, b, t) : act(m, a, b, t)), write: writeBlock(), open, ...ownAimHooks() }),
      ] : [
        summaryTiles(rv, pick),
        newsBlock(whatChanged(rv.documents), (id) => readPress({ id })),
        sideSwitch(ui, pick),
        h('main', { class: `rl-room${ui.wide ? ' wide' : ''}`, 'data-view': ui.tab, 'data-side': ui.side },
          papers(), deskColumn(), sideColumn()),
      ]),
      withBoard(tabBar(rv, ui, pick), ui, pick),
      dock(),
      pressDesk(),
      ...dialogs,
    ].filter(Boolean);
  }

  // Escape with no sheet open gives the map back from full screen; a sheet or a dialog takes it first
  root.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || e.defaultPrevented || !ui.full || !mapFirst() || openSheetOf(ui)) return;
    if (e.target?.closest?.('dialog')) return;
    e.preventDefault();
    setFull(false);
  });

  root.append(...build());
  lastRoot = root;
  loadMissed();
  if (rv.brief || ui.autoFor === rv.wake_tick) fillBrief();
  else autoBrief();
  // a dialog opens only once it is in the page
  queueMicrotask(() => {
    follow();
    showDesk();
    if (pending?.isConnected && !pending.open) pending.showModal();
    else if (ui.refocusChat) refocus(ui.chat, true); // the reply redrew the room under the player
    showMissed(); // over the wake's own sheet
    // a re-read after a call from a sheet keeps the sheet: the keyboard goes back into it
    const lost = !document.activeElement?.isConnected || document.activeElement === document.body;
    if (lost && mapFirst() && root.isConnected) root.querySelector('.rl-over .rl-over-title, .rl-needs.open h2')?.focus();
  });
  return root;
}
