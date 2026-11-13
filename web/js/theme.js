// The screen effects, on unless `rv.effects` is "off", and the one header toggle for them.
// Storage is a parameter, so nothing here touches `window` when the module is imported.

import { h } from './dom.js';

export const EFFECTS_KEY = 'rv.effects';

/** False only when `rv.effects` is "off"; true when missing, unknown or storage is blocked. */
export function effectsOn(storage) {
  try {
    return storage?.getItem(EFFECTS_KEY) !== 'off';
  } catch {
    return true;
  }
}

/** Keeps the setting as "on" or "off"; where storage is blocked it applies for this visit only. */
export function saveEffects(storage, on) {
  try {
    storage?.setItem(EFFECTS_KEY, on ? 'on' : 'off');
  } catch {
    // storage blocked: the change still applies for this visit
  }
}

/**
 * Sets `data-effects` on the page's root element: the CSP allows a stylesheet keyed on an
 * attribute, not inline style.
 */
export function applyEffects(root, storage) {
  root.dataset.effects = effectsOn(storage) ? 'on' : 'off';
}

/** The header's "Screen effects" button, pressed while they are on; a click asks for the other state. */
export function effectsControl({ effects, onChange }) {
  return h('button', {
    type: 'button',
    class: 'rl-effects',
    'aria-pressed': effects ? 'true' : 'false',
    onclick: () => onChange(!effects),
  }, 'Screen effects');
}

/** The page's `localStorage`, or undefined where the browser blocks reading it. */
export function browserStorage(win) {
  try {
    return win?.localStorage;
  } catch {
    return undefined;
  }
}
