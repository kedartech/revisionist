// The black frame header shared by every signed-in screen (design: frame layer).

import { api } from '../api.js';
import { h, icon, reply } from '../dom.js';
import { effectsControl } from '../theme.js';

/** A header title: a button that opens a dossier when `onClick` is given, else plain text. */
function titleOf(text, onClick, label) {
  return onClick
    ? h('button', { type: 'button', class: 'title head-link', 'aria-haspopup': 'dialog', 'aria-label': label, onclick: onClick }, text)
    : h('span', { class: 'title' }, text);
}

/**
 * `identity` is { name, office, principal } of the person the player plays, shown under the
 * game's name. `onSetting` and `onIdentity` make the game's name and the person's name open
 * their dossiers. `effects` is { effects, onChange } for the Screen effects toggle.
 */
export function header({ me, game, role, extra = [], refresh, signOut, identity = null, onSetting = null, onIdentity = null, effects = null }) {
  const bugDialog = bugReport(refresh);
  const name = game?.name ?? 'Revisionist';
  return h('header', { class: 'frame-head' },
    h('span', { class: 'brand-mark', 'aria-hidden': 'true' }, icon('mark', 22)),
    h('div', { class: 'stack' },
      h('span', { class: 'eyebrow' }, role),
      titleOf(name, onSetting, `${name}: open the setting`)),
    identity?.name
      ? h('div', { class: 'stack identity' },
        h('span', { class: 'eyebrow' }, 'Playing as'),
        titleOf(identity.name, onIdentity, `${identity.name}: open the dossier`),
        identity.office ? h('span', { class: 'muted office' }, identity.office) : null,
        identity.principal ? h('span', { class: 'muted answers-to' }, `Answers to ${identity.principal}`) : null)
      : null,
    ...extra,
    h('div', { class: 'head-right' },
      effects ? effectsControl(effects) : null,
      h('span', { class: 'muted' }, 'Signed in as ', me.account.handle),
      game ? h('button', {
        type: 'button', class: 'icon-btn', 'aria-label': 'Report a bug', title: 'Report a bug',
        onclick: () => bugDialog.showModal(),
      }, icon('bug', 16)) : null,
      h('button', { type: 'button', class: 'ghost', onclick: signOut }, icon('out', 14), 'Sign out')),
    bugDialog);
}

function bugReport() {
  const out = h('div', { role: 'status' });
  const notes = h('textarea', { id: 'bug-notes', rows: 5, maxlength: 4000, required: true });
  const dialog = h('dialog', { class: 'sheet', 'aria-labelledby': 'bug-title' });
  const form = h('form', { method: 'dialog' },
    h('h2', { id: 'bug-title' }, 'Report a bug'),
    h('p', { class: 'hint' }, 'Pinned to this exact moment in the game. Only the host reads it.'),
    h('label', { for: 'bug-notes' }, 'What went wrong'),
    notes,
    out,
    h('div', { class: 'row end' },
      h('button', { type: 'button', class: 'ghost', onclick: () => dialog.close() }, 'Close'),
      h('button', { type: 'submit', class: 'primary' }, 'File it')));
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!notes.value.trim()) return;
    out.replaceChildren('Filing…');
    try {
      const r = await api.seat('bug', { notes: notes.value });
      out.replaceChildren(reply(r.reply));
      if (!r.refused) notes.value = '';
    } catch (ex) {
      out.replaceChildren(ex.message);
    }
  });
  dialog.append(form);
  return dialog;
}
