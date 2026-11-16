// The realism room: one surface for a seat in a realism game, in two views with one switch.
// Desk: the in-tray on the left; in the middle what needs an answer, ideas, the order being
// written or signed, the standard forms and the commit; the seat's orders on the right.
// Board, the view it opens on: the Theatre or the Court beside the selected piece and the
// order form. The messenger floats over either. The header's two names open the setting and
// the character dossiers. Built from view.realism (realism_api.py).

import { api } from '../api.js';
import { h, icon } from '../dom.js';
import { STEP_ACTIONS, entityChoices } from '../realism-rules.js';
import { worldDate } from '../rules.js';
import { browserStorage } from '../theme.js';
import { briefBlock, directiveForm, paceHeader } from './realism.js';
import { boardView, viewSwitch, withBoard } from './realism-board.js';
import { header } from './frame.js';
import { needsAnswer } from './realism-answer.js';
import { chatDock, seenStore, settleMarks, threadCounts } from './realism-chat.js';
import { contactsTab } from './realism-contacts.js';
import { characterDossier, settingDossier } from './realism-dossier.js';
import { withCostStrips } from './realism-estimate.js';
import { standardForms } from './realism-forms.js';
import { firstWakeCard } from './realism-firstwake.js';
import { happenedSheet, happenedStore, shouldShow } from './realism-happened.js';
import { ideasPanel } from './realism-ideas.js';
import { crawlParagraphs, introCrawl } from './realism-crawl.js';
import { runMoves } from './realism-moves.js';
import { introStage, markIntro, seatSplash, splashModel, startOverview } from './realism-intro.js';
import { newsBlock, whatChanged } from './realism-news.js';
import { orderCards } from './realism-orders.js';
import { pressCounts, pressDock, pressFocus, pressMarks, pressPapers, pressSeen, pressTab } from './realism-press.js';
import { overlayLines, wakeOverlay, withPlayback } from './realism-overlay.js';
import { peopleRoster, personDossier } from './realism-people.js';
import { stakesStrip } from './realism-stakes.js';
import { statusStrip, summaryTiles } from './realism-status.js';
import { sideSwitch, tabBar } from './realism-tabs.js';
import { noticesSection } from './realism-notices.js';
import { followThread, threadItems } from './realism-thread.js';
import { threatsPanel } from './realism-threats.js';
import { trayView } from './realism-tray.js';
import { RUNNING, commitPanel, orderCard, stylePicker, wakeHeader } from './realism-wake.js';

const freshUi = (game) => ({
  game, wide: false, page: null, said: null, error: null, busy: null,
  filter: 'all', sort: 'newest', draft: null, proposal: null, autoFor: null,
  chat: { open: false, tab: 'chats', thread: null }, contact: null, orderTo: null,
  happenedSeen: null, refocusChat: false, brief: null, pending: null, drafts: {}, letters: [], runFrom: null, offer: null, menuCall: false,
  tab: 'desk', side: 'papers', press: { open: false, tab: null }, pressPage: null, peopleTab: 'opponents',
  view: 'board', board: 'theatre', piece: null, theatre: { mode: 'map', scope: 'reports' },
  firstWakeOff: null,
});
let ui = freshUi(null);

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

/** Where focus goes when the messenger closes: its launcher, or on a phone (launcher hidden) the Messages tab. */
export function closedChatTarget(root, phone) {
  if (!phone) return root.querySelector('.rl-msgr-btn');
  return [...root.querySelectorAll('.rl-tabbar button')].find((b) => b.textContent.startsWith('Messages')) ?? null;
}

const SWITCHES = ['.rl-tabbar', '.rl-sideswitch', '.rl-tiles', '.rl-viewswitch', '.rl-board-main'];

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

/** The game menu: pause, resume and end for the host; how to start another game. */
export function gameMenu(game, ctx, work) {
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
    host,
    notices.nodes,
    h('h3', {}, 'A new game'),
    h('p', { class: 'hint' }, game.host
      ? 'You play one game at a time. End this one, and you can start another straight away.'
      : 'You play one game at a time. Leave this one, and you can join or start another.'),
    out,
    h('div', { class: 'row end' }, closeBtn)));
  const open = h('button', {
    type: 'button', class: 'rl-menu-btn', 'aria-haspopup': 'dialog', onclick: () => { if (work.idle()) { dialog.showModal(); notices.load(); } },
  }, 'Game', icon('chevron', 12));
  return [open, dialog];
}

export function realismRoom(ctx) {
  const { me, refresh } = ctx;
  const game = me.game;
  uiFor(game.id);
  const rv = game.view.realism;
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
  const rerender = () => {
    root.replaceChildren(...build());
    follow();
    showDesk();
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
      ui.runFrom = { wake: rv.record?.wake?.number ?? 0, map: rv.map ?? null }; // What happened replays the moves
      const layer = withPlayback(wakeOverlay({ message, lines: overlayLines(rv.setting, rv.wake.wake), map: rv.map, orders: rv.record?.orders }), { court: rv.court, stakes: rv.stakes });
      if (layer) root.append(layer);
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
    return ask(letterDraft(to, words));
  };

  /** File the signed order, which the server holds; a refusal leaves it on the desk to revise. */
  const signed = (p) => act(p.person ? `Sending it to ${p.person}…` : 'Sending it…', 'file', {},
    (r) => { if (!r.refused) { ui.proposal = null; ui.draft = null; ui.orderTo = null; } });

  const open = (d) => work('Fetching the paper…', async () => {
    ui.page = await api.realism('read', { doc_id: d.id });
    ui.said = null;
    // the paper opens in the in-tray, which is on the Desk view
    if (ui.view === 'board') pickPanel(ui, { tab: 'papers', side: 'papers' }, phoneWidth());
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
    return h('section', { class: 'rl-write', 'aria-label': ui.proposal ? 'Your order, to sign' : 'Write an order' }, directive,
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
        }), rv.desk?.levers, rv.court),
        commitPanel(rv.wake, { act })));
  }

  /** Open a standard form on the desk, for a draft the aide suggested. */
  function useDraft(d) {
    if (ui.view === 'board') { // the standard forms are on the Desk view
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
    root.append(dossier);
    dossier.showModal();
  }

  /** A roster tab is picked: the redraw keeps focus on that tab's button. */
  function pickPeople(key) {
    ui.peopleTab = key;
    rerender();
    root.querySelector('.rl-people .seg button[aria-pressed="true"]')?.focus();
  }

  function sideColumn() {
    // the People roster replaces the Opponents panel; a view without it keeps the old panel
    const people = rv.people
      ? peopleRoster(rv.people, { tab: ui.peopleTab, onTab: pickPeople, onOpen: openPerson })
      : threatsPanel(rv.threats);
    return h('aside', { class: 'rl-col rl-side', 'data-tab': 'orders', 'aria-label': 'Your orders' },
      h('div', { class: 'rl-col-body' },
        people,
        orderCards(rv.record, rv.orders, (o) => stepForm(o, (v) => act('Recording your decision…', 'step', v)), open)));
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
      onState: (next) => { if (!next.open && ui.tab === 'messages') ui.tab = 'desk'; ui.chat = next; rerender(); refocus(next); },
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
    rerender();
    root.querySelector(written ? '.rl-write textarea' : '.rl-offer button.ghost')?.focus();
  }

  /** Replace or Keep mine on the offer line; focus goes back to the order's words. */
  function answerOffer(replace) {
    settleOffer(ui, replace);
    rerender();
    root.querySelector('.rl-write textarea')?.focus();
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
        moves: runMoves(ui.runFrom, page, rv.map), places: rv.map?.places,
        onClose: () => happened?.close(),
      })
      : null;
    // Esc closes a dialog without its button: the close event counts either way
    happened?.addEventListener('close', () => { ui.happenedSeen = page.number; shown.write(page.number); });
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

  let pending = null;
  const pick = (p) => {
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
    (root.querySelector('.rl-pin') ?? root.querySelector('.rl-viewswitch button'))?.focus();
  }
  function build() {
    const [menuBtn, menu] = gameMenu(game, ctx, work);
    const { character, setting, happened, intro: opening } = sheets();
    pending = opening ?? happened;
    const extra = [
      h('span', { class: 'divider', 'aria-hidden': 'true' }),
      h('div', { class: 'stack rl-clock' }, paceHeader(rv.clock)),
      wakeHeader(rv.wake, { act }),
      menuBtn,
    ];
    status = h('div', { class: 'rl-status', role: 'status', 'aria-live': 'polite' });
    showStatus();
    return [
      header({
        ...ctx, game, role: 'Campaign', extra,
        identity: { name: seatName, office: rv.desk.office, principal: rv.desk.principals.join(', ') || null },
        onSetting: setting && work.idle() ? () => setting.showModal() : null,
        onIdentity: character && work.idle() ? () => character.showModal() : null,
      }),
      statusStrip(rv, ui, { act }),
      stakesStrip(rv.stakes),
      status,
      firstWakeCard(rv.wake, { dismissed: ui.firstWakeOff, onDismiss: dismissFirstWake }),
      viewSwitch(ui, pick),
      ...(ui.view === 'board' ? [
        newsBlock(whatChanged(rv.documents), (id) => readPress({ id })),
        boardView(rv, ui, { pick, act, write: writeBlock(), open }),
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
      menu, character, setting, happened, opening,
    ].filter(Boolean);
  }

  root.append(...build());
  if (rv.brief || ui.autoFor === rv.wake_tick) fillBrief();
  else autoBrief();
  // a dialog opens only once it is in the page
  queueMicrotask(() => {
    follow();
    showDesk();
    if (pending?.isConnected && !pending.open) pending.showModal();
    else if (ui.refocusChat) refocus(ui.chat, true); // the reply redrew the room under the player
  });
  return root;
}
