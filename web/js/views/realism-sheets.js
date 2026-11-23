// The map-first room: the default layout of a territory game, with the classic room beside it, chosen from the game menu. The map fills
// the screen; each part of the four groups (realism-groups.js) and the messenger open as a sheet
// over it (at the side from 1024 px, a half sheet from the bottom below that: c-sheets.css), and
// a picked force opens its own. One sheet at a time; Escape or Close shuts it and focus goes back
// to what opened it. The room (realism-room.js) builds each sheet's body; this file holds the
// layout choice, the sheet state, the frame and the form values a redraw must keep.
// Nothing here touches the page on import.

import { h } from '../dom.js';
import { groupOf } from './realism-groups.js';

/** The messenger's sheet's title; a group's part takes its group's name. */
const MESSAGES_TITLE = 'Messages';

const LAYOUTS = [['map', 'Map first'], ['room', 'Classic layout']]; // [proposed]

// Held for the page's life: no account setting stores it yet, so a reload opens the default.
let layout = null;
let territorial = false;

/** Whether the game drawn is a territory game; only such a game has the map-first room. */
export function setTerritorial(on) { territorial = Boolean(on); }

/** The room layout this page shows: 'map' for a territory game unless the player chose the classic one; else 'room'. */
export function roomLayout() { return territorial && layout !== 'room' ? 'map' : 'room'; }

/** Choose the layout; anything but 'map' is the classic room. */
export function setRoomLayout(next) { layout = next === 'map' ? 'map' : 'room'; }

/** The game menu's layout choice: two buttons, the current one pressed; a click calls `onPick(key)`. */
export function layoutChoice(onPick) {
  if (!territorial) return null;
  return h('div', { class: 'rl-layout', role: 'group', 'aria-labelledby': 'rl-layout-h' },
    h('h3', { id: 'rl-layout-h' }, 'Room layout'),
    h('div', { class: 'row' }, LAYOUTS.map(([key, word]) => h('button', {
      type: 'button', class: 'ghost', 'aria-pressed': String(roomLayout() === key), onclick: () => onPick(key),
    }, word))));
}

/**
 * The open sheet: Messages while the messenger is open, Press while the newspaper desk is, else
 * `ui.sheet` (a force's sheet only while a force is picked); null for the bare map.
 */
export function openSheetOf(ui) {
  if (ui.chat?.open) return 'messages';
  if (ui.press?.open) return 'press';
  if (ui.sheet === 'piece') return ui.piece?.kind === 'force' ? 'piece' : null;
  return ui.sheet ?? null;
}

/**
 * Open sheet `name`, closing any other: the messenger and the newspaper desk keep their own open
 * flags, so a thread the aide opens or a paper read from the news opens its sheet the same way.
 * Opening the Court clears the pick; any sheet but a force's drops a picked force. `from` is what
 * opened it (`{ tab }` or `{ mark }`), where focus goes back when it closes. A part of a group
 * becomes the part that group opens on next (`ui.parts`).
 */
export function openSheet(ui, name, from = { tab: name }) {
  const group = groupOf(name);
  if (group) ui.parts = { ...ui.parts, [group.key]: name };
  ui.chat = { ...ui.chat, open: name === 'messages' };
  ui.press = { ...ui.press, open: name === 'press' };
  ui.sheet = name === 'messages' || name === 'press' ? null : name;
  if (name === 'court' || (name !== 'piece' && ui.piece?.kind === 'force')) ui.piece = null;
  ui.sheetFrom = from;
}

/** Close the open sheet: a force's sheet drops the pick. Answers what opened it, or null. */
export function closeSheet(ui) {
  const from = openSheetOf(ui) ? ui.sheetFrom ?? null : null;
  if (ui.sheet === 'piece') ui.piece = null;
  ui.chat = { ...ui.chat, open: false };
  ui.press = { ...ui.press, open: false };
  ui.sheet = null;
  ui.sheetFrom = null;
  return from;
}

/**
 * One sheet over the map: `<section class="rl-over" role="dialog">` with its title (a part's is
 * its group's), a Close, a group's part tabs (`parts`) and the body. Escape inside it or Close
 * calls `onClose`. Not modal: the map under it stays live, so a lit area can be picked while a
 * form is open.
 */
export function overSheet({ name, title, body, onClose, piece = null, parts = null }) {
  return h('section', {
    class: 'rl-over', id: 'rl-over', role: 'dialog', 'aria-modal': 'false', 'aria-labelledby': 'rl-over-h',
    'data-sheet': name, 'data-piece': piece,
    onkeydown: (e) => { if (e.key === 'Escape') { e.preventDefault(); onClose(); } },
  },
  h('div', { class: 'rl-over-head' },
    h('h2', { class: 'rl-over-title', id: 'rl-over-h', tabindex: '-1' }, title ?? groupOf(name)?.label ?? (name === 'messages' ? MESSAGES_TITLE : name)),
    h('button', { type: 'button', class: 'rl-btn rl-over-close', onclick: onClose }, 'Close')),
  parts,
  h('div', { class: 'rl-over-body' }, body));
}

/** Where a sheet's form values are kept: its sheet, and for a force's sheet the force. */
const sheetKey = (sheet) => {
  const name = sheet.getAttribute('data-sheet');
  return name === 'piece' ? `piece:${sheet.getAttribute('data-piece')}` : name;
};

/** A form's fields that carry a value: every named field but the place picker's radios. */
const fieldsOf = (item) => [...item.querySelectorAll('select[name], input[name], textarea[name]')]
  .filter((el) => el.getAttribute('type') !== 'radio');

/**
 * `readForms(root, kept)`: each standard form in the open sheet, by sheet and form, as
 * `{ open, values }`, laid over `kept` so a form a redraw left out (a force's form on the
 * Diplomatic layer) keeps what it had. A form being filed (`data-filed`) is dropped.
 */
export function readForms(root, kept = {}) {
  const out = { ...kept };
  for (const sheet of root?.querySelectorAll('.rl-over') ?? []) {
    const key = sheetKey(sheet);
    const forms = { ...(out[key] ?? {}) };
    for (const item of sheet.querySelectorAll('.rl-instrument')) {
      const lever = item.getAttribute('data-lever');
      if (item.hasAttribute('data-filed')) { delete forms[lever]; continue; }
      const values = {};
      for (const el of fieldsOf(item)) if (el.value !== '') values[el.getAttribute('name')] = el.value;
      forms[lever] = { open: item.querySelector('.rl-instrument-head [aria-expanded]')?.getAttribute('aria-expanded') === 'true', values };
    }
    out[key] = forms;
  }
  return out;
}

/** Drop what is kept for form `lever` in every sheet: it has been filed. */
export function forgetForm(kept, lever) {
  const out = {};
  for (const [key, forms] of Object.entries(kept ?? {})) {
    const { [lever]: _filed, ...rest } = forms;
    out[key] = rest;
  }
  return out;
}

/** Tell a field's own listeners it changed, as the player's change would. */
const change = (el) => el.dispatchEvent(globalThis.Element && el instanceof globalThis.Element
  ? new Event('change')
  : { type: 'change', target: null, defaultPrevented: false, preventDefault() {}, stopPropagation() {} });

/**
 * `restoreForms(sheet, kept)`: put back what `readForms` kept for this sheet: each value, the
 * force first so the place picker redraws for it, the form opened if it was, and a picked place
 * chosen through its radio so the map lights it as chosen.
 */
export function restoreForms(sheet, kept) {
  const forms = kept?.[sheetKey(sheet)];
  if (!forms) return;
  for (const item of sheet.querySelectorAll('.rl-instrument')) {
    const saved = forms[item.getAttribute('data-lever')];
    if (!saved) continue;
    const fields = fieldsOf(item);
    const places = [];
    for (const el of fields) {
      const v = saved.values[el.getAttribute('name')];
      if (v === undefined) continue;
      if (el.getAttribute('type') === 'hidden') places.push([el, v]);
      else if (el.value !== v) { el.value = v; change(el); }
    }
    const toggle = item.querySelector('.rl-instrument-head [aria-expanded]');
    if (saved.open && toggle?.getAttribute('aria-expanded') === 'false') toggle.click();
    for (const [field, v] of places) {
      const radio = [...item.querySelectorAll('input[type="radio"]')].find((r) => r.value === v && !r.disabled);
      if (radio) { radio.checked = true; change(radio); } else field.value = v;
    }
  }
}

/** Mark the form a submit came from as filed, so the redraw after it does not fill it again. */
export function markFiled(root, lever) {
  for (const item of root?.querySelectorAll('.rl-over .rl-instrument') ?? []) {
    if (item.getAttribute('data-lever') === lever) item.setAttribute('data-filed', '');
  }
}

/**
 * The element focus goes back to when a sheet opened by `from` closes: the force's mark, the
 * chat button for the messenger, or the tab of the group (`from.group`, or the group of `from.tab`).
 */
export function returnTarget(root, from) {
  if (from?.mark) {
    const named = (el) => (el.getAttribute('aria-label') ?? '').startsWith(`${from.mark}:`);
    return [...root.querySelectorAll('.rl-mapfirst .rl-mk')].find(named)
      ?? [...root.querySelectorAll('.rl-mapfirst [data-stack]')].find((g) => (g.getAttribute('aria-label') ?? '').includes(from.mark))
      ?? null;
  }
  const group = from?.group ?? groupOf(from?.tab)?.key ?? null;
  if (!group) return (from?.tab ?? 'messages') === 'messages' ? root.querySelector('.rl-roombar .rl-chat-btn') : null;
  return [...root.querySelectorAll('.rl-sheettabs button')].find((b) => b.getAttribute('data-group') === group) ?? null;
}
