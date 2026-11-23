// The black frame header shared by every signed-in screen (design: frame layer).

import { api } from '../api.js';
import { h, icon, reply } from '../dom.js';

/**
 * A header title: a button that opens a dossier when `onClick` is given, else plain text.
 * `extra` adds classes: the game's name alone takes `rl-cursor`, the blinking cursor.
 */
function titleOf(text, onClick, label, extra = '') {
  const cls = extra ? `title ${extra}` : 'title';
  return onClick
    ? h('button', { type: 'button', class: `${cls} head-link`, 'aria-haspopup': 'dialog', 'aria-label': label, onclick: onClick }, text)
    : h('span', { class: cls }, text);
}

/**
 * `identity` is { name, office, principal } of the person the player plays, shown under the
 * game's name. `onSetting` and `onIdentity` make the game's name and the person's name open
 * their dossiers. Only the game's name carries the blinking cursor (css/effects.css).
 */
export function header({ me, game, role, extra = [], refresh, signOut, identity = null, onSetting = null, onIdentity = null }) {
  const bugDialog = reportDialog();
  const name = game?.name ?? 'Revisionist';
  return h('header', { class: 'frame-head' },
    h('span', { class: 'brand-mark', 'aria-hidden': 'true' }, icon('mark', 22)),
    h('div', { class: 'stack' },
      h('span', { class: 'eyebrow' }, role),
      titleOf(name, onSetting, `${name}: open the setting`, 'rl-cursor')),
    identity?.name
      ? h('div', { class: 'stack identity' },
        h('span', { class: 'eyebrow' }, 'Playing as'),
        titleOf(identity.name, onIdentity, `${identity.name}: open the dossier`),
        identity.office ? h('span', { class: 'muted office' }, identity.office) : null,
        identity.principal ? h('span', { class: 'muted answers-to' }, `Answers to ${identity.principal}`) : null)
      : null,
    ...extra,
    h('div', { class: 'head-right' },
      h('span', { class: 'muted' }, 'Signed in as ', me.account.handle),
      game ? h('button', {
        type: 'button', class: 'icon-btn', 'aria-label': 'Report a bug, an idea or something confusing', title: 'Report a bug, an idea or something confusing',
        onclick: () => bugDialog.showModal(),
      }, icon('bug', 16)) : null,
      h('button', { type: 'button', class: 'ghost', onclick: signOut }, icon('out', 14), 'Sign out')),
    bugDialog);
}

const KINDS = [['bug', 'A bug'], ['idea', 'An idea'], ['confusing', 'Something confusing']];
const KIND_NAME = { bug: 'Bug', idea: 'Idea', confusing: 'Confusing' };
const STATUS_NAME = { new: 'New', seen: 'Seen', acted: 'Acted on' };

/** One report as a list row: its kind, its status, its words and the host's reply, all as text. */
function reportRow(r, extra = []) {
  return h('li', { class: 'rl-report' },
    h('div', { class: 'row' },
      h('strong', {}, KIND_NAME[r.kind] ?? r.kind),
      h('span', { class: 'rl-report-status', 'data-status': r.status }, STATUS_NAME[r.status] ?? r.status),
      r.office ? h('span', { class: 'hint' }, r.office) : null),
    h('p', { class: 'rl-report-words' }, r.words),
    r.reply ? h('p', { class: 'rl-report-reply' }, h('span', { class: 'hint' }, 'Host: '), r.reply) : null,
    ...extra);
}

/**
 * The report dialog: the header's control opens it, and so does the map-first room's game menu.
 * A bug, an idea or something confusing, filed through the realism action `report`; \"Your
 * reports\" lists the player's own with their status and the host's reply.
 */
export function reportDialog() {
  const out = h('div', { role: 'status' });
  const notes = h('textarea', { id: 'bug-notes', rows: 5, maxlength: 4000, required: true });
  const radios = KINDS.map(([value]) => h('input', { type: 'radio', name: 'report-kind', value, checked: value === 'bug' }));
  const kinds = KINDS.map(([, label], i) => h('label', { class: 'rl-report-kind' }, radios[i], ` ${label}`));
  const mine = h('ul', { class: 'rl-reports' });
  const dialog = h('dialog', { class: 'sheet', 'aria-labelledby': 'bug-title' });
  const loadMine = async () => {
    mine.replaceChildren('Loading…');
    try {
      const r = await api.realism('reports', {});
      mine.replaceChildren(...(r.reports?.length ? r.reports.map((x) => reportRow(x)) : [h('li', { class: 'hint' }, 'You have filed no reports.')]));
    } catch (ex) {
      mine.replaceChildren(ex.message);
    }
  };
  let listed = false;
  const form = h('form', { method: 'dialog' },
    h('h2', { id: 'bug-title' }, 'Report a bug, an idea or something confusing'),
    h('p', { class: 'hint' }, 'Pinned to this exact moment in the game. Only the host and the makers read it.'),
    h('div', { class: 'row', role: 'radiogroup', 'aria-label': 'What kind of report' }, kinds),
    h('label', { for: 'bug-notes' }, 'What do you want to say'),
    notes,
    out,
    h('div', { class: 'row end' },
      h('button', { type: 'button', class: 'ghost', onclick: () => { listed = true; loadMine(); } }, 'Your reports'),
      h('button', { type: 'button', class: 'ghost', onclick: () => dialog.close() }, 'Close'),
      h('button', { type: 'submit', class: 'primary' }, 'File it')),
    mine);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!notes.value.trim()) return;
    const kind = radios.find((k) => k.checked)?.value ?? 'bug';
    out.replaceChildren('Filing…');
    try {
      const r = await api.realism('report', { kind, text: notes.value });
      out.replaceChildren(reply(r.reply));
      if (!r.refused) {
        notes.value = '';
        if (listed) await loadMine();
      }
    } catch (ex) {
      out.replaceChildren(ex.message);
    }
  });
  dialog.append(form);
  return dialog;
}

/**
 * The host's inbox in the game menu: every report in the game, each marked seen or acted on
 * with a line of reply. `load` asks the server; the server answers a seat that is not the host
 * with nothing, and the menu draws this section for the host only.
 */
export function reportInbox() {
  const list = h('ul', { class: 'rl-reports' });
  const out = h('div', { role: 'status' });
  const load = async () => {
    try {
      const r = await api.realism('reports', { inbox: true });
      list.replaceChildren(...(r.reports?.length ? r.reports.map(inboxRow) : [h('li', { class: 'hint' }, 'No one has filed a report in this game.')]));
    } catch (ex) {
      out.replaceChildren(ex.message);
    }
  };
  const mark = async (id, status, said) => {
    try {
      const r = await api.realism('report-mark', said ? { id, status, reply: said } : { id, status });
      if (r.refused) out.replaceChildren(r.reply);
      else { out.replaceChildren(); await load(); }
    } catch (ex) {
      out.replaceChildren(ex.message);
    }
  };
  function inboxRow(r) {
    const said = h('input', { type: 'text', maxlength: 200, 'aria-label': `Your reply to report ${r.id}`, value: r.reply ?? '' });
    return reportRow(r, [h('div', { class: 'row' }, said,
      h('button', { type: 'button', class: 'ghost', onclick: () => mark(r.id, 'seen', said.value.trim()) }, 'Seen'),
      h('button', { type: 'button', class: 'ghost', onclick: () => mark(r.id, 'acted', said.value.trim()) }, 'Acted on'))]);
  }
  const nodes = h('section', { class: 'rl-inbox', 'aria-labelledby': 'rl-inbox-h' },
    h('h3', { id: 'rl-inbox-h' }, 'Reports from players'), list, out);
  return { nodes, load };
}
