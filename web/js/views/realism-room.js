// The realism room: one surface for a seat in a realism game. The in-tray on the left; in
// the middle what needs an answer, ideas, the order being written or signed, the standard
// forms and the commit; the seat's orders on the right; the messenger floating over it.
// The header's two names open the setting and the character dossiers. Built from
// view.realism (realism_api.py).

import { api } from '../api.js';
import { h, icon } from '../dom.js';
import { STEP_ACTIONS, entityChoices } from '../realism-rules.js';
import { worldDate } from '../rules.js';
import { briefBlock, directiveForm, paceHeader } from './realism.js';
import { header } from './frame.js';
import { ackThread } from './realism-acks.js';
import { needsAnswer } from './realism-answer.js';
import { chatDock, seenStore } from './realism-chat.js';
import { contactsTab } from './realism-contacts.js';
import { characterDossier, settingDossier } from './realism-dossier.js';
import { standardForms } from './realism-forms.js';
import { happenedSheet, happenedStore, shouldShow } from './realism-happened.js';
import { ideasPanel } from './realism-ideas.js';
import { newsBlock, whatChanged } from './realism-news.js';
import { orderCards } from './realism-orders.js';
import { overlayLines, wakeOverlay } from './realism-overlay.js';
import { trayView } from './realism-tray.js';
import { RUNNING, commitPanel, orderCard, stylePicker, wakeHeader } from './realism-wake.js';

const ui = {
  wide: false, page: null, said: null, error: null, busy: null,
  filter: 'all', sort: 'newest', draft: null, proposal: null, autoFor: null,
  chat: { open: false, tab: 'chats', thread: null }, contact: null, orderTo: null,
};

/** Browser storage, or nothing where it is blocked: the units take it as a parameter. */
function storage() {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

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
function gameMenu(game, ctx, work) {
  const out = h('div', { class: 'outcome', role: 'status', 'aria-live': 'polite' });
  const dialog = h('dialog', { class: 'sheet rl-menu', 'aria-labelledby': 'rl-menu-h' });
  const close = () => dialog.close();
  const call = async (action) => {
    out.replaceChildren('Working…');
    try {
      const r = await api.game(action);
      if (r.refused) { out.replaceChildren(r.reply); return; }
      ui.said = r.reply;
      close();
      if (action === 'end') ctx.go('new');
      else if (action === 'leave') ctx.go('home');
      else await ctx.refresh();
    } catch (ex) {
      out.replaceChildren(h('span', { class: 'form-error', role: 'alert' }, ex.message));
    }
  };
  const hours = h('input', { id: 'rl-wake-hours', name: 'hours', type: 'number', min: 1, max: 168, step: 1, required: true });
  const setHours = async () => {
    if (!hours.reportValidity()) return;
    out.replaceChildren('Working…');
    try {
      const r = await api.game('wake-hours', { hours: Number(hours.value) });
      out.replaceChildren(r.reply);
    } catch (ex) {
      out.replaceChildren(h('span', { class: 'form-error', role: 'alert' }, ex.message));
    }
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
    h('h3', {}, 'A new game'),
    h('p', { class: 'hint' }, game.host
      ? 'You play one game at a time. End this one, and you can start another straight away.'
      : 'You play one game at a time. Leave this one, and you can join or start another.'),
    out,
    h('div', { class: 'row end' }, h('button', { type: 'button', class: 'ghost', onclick: close }, 'Close'))));
  const open = h('button', {
    type: 'button', class: 'rl-menu-btn', 'aria-haspopup': 'dialog', onclick: () => { work.idle() && dialog.showModal(); },
  }, 'Game', icon('chevron', 12));
  return [open, dialog];
}

export function realismRoom(ctx) {
  const { me, refresh } = ctx;
  const game = me.game;
  const rv = game.view.realism;
  const seatName = game.view.seat?.name ?? '';
  const root = h('div', { class: 'screen war-screen realism-screen' });
  const rerender = () => root.replaceChildren(...build());
  const seen = seenStore(storage(), game.id);
  const shown = happenedStore(storage(), game.id);

  /**
   * Run one slow call: the status line says what is happening in plain words, every
   * control is held until it is done, and the room is re-read after. A call that runs
   * the wake also lays the overlay over the room; the redraw removes it.
   */
  async function work(message, fn) {
    if (ui.busy) return;
    ui.busy = message;
    ui.error = null;
    const clicked = document.activeElement;
    root.setAttribute('aria-busy', 'true');
    if (clicked?.tagName === 'BUTTON') clicked.classList.add('rl-working');
    for (const el of root.querySelectorAll('button, select, textarea, input')) el.disabled = true;
    showStatus();
    if (message === RUNNING) {
      const layer = wakeOverlay({ message, lines: overlayLines(rv.setting) });
      if (layer) root.append(layer);
    }
    try {
      await fn();
    } catch (ex) {
      ui.error = ex.message;
    } finally {
      ui.busy = null;
    }
    await refresh();
  }
  work.idle = () => !ui.busy;

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

  const act = (message, action, body, then) => work(message, async () => {
    const r = await api.realism(action, body);
    ui.said = r.reply || null;
    // the aide has written: a failed order, or an answer; open its thread
    if (r.help) ui.chat = { open: true, tab: 'chats', thread: 'aide' };
    then?.(r);
  });

  /** The aide reads the order; nothing is filed until the player signs. */
  const ask = (draft) => {
    ui.draft = draft;
    return act('Your aide is reading it…', 'order', draft, (r) => {
      ui.proposal = r.proposal ?? null;
      if (ui.proposal) ui.said = null; // the card says it
    });
  };

  /** File the signed order, which the server holds; a refusal leaves it on the desk to revise. */
  const signed = (p) => act(p.person ? `Sending it to ${p.person}…` : 'Sending it…', 'file', {},
    (r) => { if (!r.refused) { ui.proposal = null; ui.draft = null; ui.orderTo = null; } });

  const open = (d) => work('Fetching the paper…', async () => {
    ui.page = await api.realism('read', { doc_id: d.id });
    ui.said = null;
  });

  const flag = (on) => work(on ? 'Flagging it…' : 'Unflagging it…', async () => {
    await api.realism('flag', { doc_id: ui.page.item.id, flagged: on });
    ui.page.item.flagged = on;
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
    return h('section', { class: 'rl-col rl-papers', 'aria-label': 'Papers' },
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

  /**
   * Who an order can go to: the inner circle, and a contact chosen from the messenger
   * ("Write them an order"), whose channels are the keys the order form posts.
   */
  function orderContacts() {
    const inner = rv.desk.inner_circle;
    const c = ui.orderTo;
    if (!c || inner.some((x) => x.person === c.name)) return inner;
    const keys = c.channel_keys ?? [];
    return [...inner, { person: c.name, title: c.title, channel: keys[0] ?? '', channels: keys }];
  }

  /** The directive form, its words kept as typed: a redraw or a refresh rebuilds it from ui.draft. */
  function orderForm() {
    const form = directiveForm(orderContacts(), ui.draft, ask);
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
      if (r.brief) rv.brief = r.brief;
      fillBrief(r.brief ? {} : { said: r.reply });
    } catch (ex) {
      fillBrief({ said: ex.message });
    }
  }

  function deskColumn() {
    const directive = ui.proposal
      ? orderCard(ui.proposal, { onSign: signed, onRevise: () => { ui.proposal = null; ui.said = null; rerender(); } })
      : orderForm();
    return h('section', { class: 'rl-col rl-desk-col', 'aria-label': 'Desk' },
      h('div', { class: 'rl-col-body' },
        stylePicker(rv.style, { act }),
        needsAnswer(rv.agenda, { act }),
        ideasSlot,
        h('section', { class: 'rl-write', 'aria-label': ui.proposal ? 'Your order, to sign' : 'Write an order' }, directive),
        standardForms(rv.desk, {
          onSubmit: (v) => act('Sending it…', 'lever', v),
          entities: entityChoices(rv.desk),
        }),
        commitPanel(rv.wake, { act })));
  }

  /** Open a standard form on the desk, for a draft the aide suggested. */
  function useDraft(d) {
    const item = root.querySelector(`.rl-instrument[data-lever="${CSS.escape(d.lever)}"]`);
    if (!item) return;
    const fold = item.closest('details');
    if (fold) fold.open = true;
    const toggle = item.querySelector('[aria-expanded]');
    if (toggle?.getAttribute('aria-expanded') === 'false') toggle.click();
    item.scrollIntoView({ block: 'center' });
    item.querySelector('input, select, textarea')?.focus();
  }

  function sideColumn() {
    return h('aside', { class: 'rl-col rl-side', 'aria-label': 'Your orders' },
      h('div', { class: 'rl-col-body' },
        orderCards(rv.record, rv.orders, (o) => stepForm(o, (v) => act('Recording your decision…', 'step', v)))));
  }

  /** Lines in each thread, to mark the ones with something new since last seen. */
  function chatCounts() {
    const counts = { aide: (rv.help ?? []).filter((m) => m.from === 'aide').length };
    for (const c of rv.desk.inner_circle) counts[c.person] = (rv.counsel ?? []).filter((x) => x.person === c.person).length;
    return counts;
  }

  function dock() {
    const counts = chatCounts();
    const marks = seen.read();
    const thread = ui.chat.open ? ui.chat.thread : null;
    if (thread && thread in counts && marks[thread] !== counts[thread]) seen.write({ ...marks, [thread]: counts[thread] });
    const inner = rv.desk.inner_circle.map((c) => c.person);
    return chatDock({
      state: ui.chat,
      onState: (next) => { ui.chat = next; rerender(); },
      counts,
      seen: seen.read(),
      contacts: rv.desk.inner_circle,
      counsel: rv.counsel ?? [],
      help: rv.help ?? [],
      brief: briefSlot,
      ask: (question) => act('Your aide is looking into it…', 'help', { question }),
      consult: (to, question) => act(`Waiting for ${to} to answer…`, 'consult', { to, question }),
      useDraft,
      ackThread: (person) => ackThread(rv.documents, person, open),
      contactsTab: contactsTab(rv.reach, {
        inner,
        selected: ui.contact,
        onSelect: (name) => { ui.contact = name; rerender(); },
        onMessage: (name) => { ui.chat = { open: true, tab: 'chats', thread: name }; rerender(); },
        onOrder: (c) => {
          ui.orderTo = c;
          ui.proposal = null;
          ui.draft = { to: c.name, channel: c.channel_keys?.[0] ?? '', text: ui.draft?.text ?? '' };
          ui.chat = { ...ui.chat, open: false };
          rerender();
          root.querySelector('.rl-write textarea')?.focus();
        },
      }),
    });
  }

  /** The two dossiers behind the header's names, and the sheet a new wake opens with. */
  function sheets() {
    const date = worldDate(rv.clock.world_date);
    const close = (d) => () => d?.close();
    const character = characterDossier({ name: seatName, desk: rv.desk, dossier: rv.dossier, onClose: () => close(character)() });
    const setting = settingDossier({ name: game.name, setting: rv.setting, date, onClose: () => close(setting)() });
    const page = rv.record?.wake;
    const happened = page && shouldShow(page, shown)
      ? happenedSheet({
        record: rv.record, situation: rv.situation, date,
        onClose: () => { shown.write(page.number); happened?.close(); },
      })
      : null;
    return { character, setting, happened };
  }

  let pending = null;
  function build() {
    const [menuBtn, menu] = gameMenu(game, ctx, work);
    const { character, setting, happened } = sheets();
    pending = happened;
    const extra = [
      h('span', { class: 'divider', 'aria-hidden': 'true' }),
      h('div', { class: 'stack rl-clock' }, h('span', { class: 'title' }, worldDate(rv.clock.world_date)), paceHeader(rv.clock)),
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
      status,
      newsBlock(whatChanged(rv.documents), (id) => open({ id })),
      h('main', { class: `rl-room${ui.wide ? ' wide' : ''}` }, papers(), deskColumn(), sideColumn()),
      dock(),
      menu, character, setting, happened,
    ].filter(Boolean);
  }

  root.append(...build());
  if (rv.brief || ui.autoFor === rv.wake_tick) fillBrief();
  else autoBrief();
  // a dialog opens only once it is in the page
  queueMicrotask(() => { if (pending?.isConnected && !pending.open) pending.showModal(); });
  return root;
}
