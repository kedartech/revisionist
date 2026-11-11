// The theme control in the header (Train 2 unit TH1): Terminal or Paper, and the screen
// effects on or off. Storage is a parameter; nothing here touches `window` when the module is imported.

import { EFFECTS_KEY, THEME_KEY, THEMES, effectsOn, themeName } from './theme.js';
import { h } from './dom.js';

const LABEL = { terminal: 'Terminal', paper: 'Paper' };

/** `{ theme(), effects(), save(theme, effects) }` over `rv.theme` and `rv.effects`; safe with no storage or a blocked one. */
export function themeStore(storage) {
  return {
    theme: () => themeName(storage),
    effects: () => effectsOn(storage),
    save(theme, effects) {
      try {
        if (THEMES.includes(theme)) storage?.setItem(THEME_KEY, theme);
      } catch {
        // storage blocked: the change still applies for this visit
      }
      try {
        storage?.setItem(EFFECTS_KEY, effects ? 'on' : 'off');
      } catch {
        // storage blocked: the change still applies for this visit
      }
    },
  };
}

/** The other theme: terminal gives paper, anything else gives terminal. */
export function nextTheme(current) {
  return current === 'terminal' ? 'paper' : 'terminal';
}

/**
 * A labelled group: a button that switches between "Terminal" and "Paper" (its label names
 * the current one, `aria-pressed` false) and an "Effects" toggle (`aria-pressed`), each
 * calling `onChange(theme, effects)`.
 */
export function themeControl({ theme, effects, onChange }) {
  const now = theme === 'paper' ? 'paper' : 'terminal';
  const other = nextTheme(now);
  return h('div', { class: 'rl-theme', role: 'group', 'aria-label': 'Display' },
    h('button', {
      type: 'button',
      title: `Switch to ${LABEL[other]}`,
      onclick: () => onChange(other, effects),
    }, LABEL[now]),
    h('button', {
      type: 'button',
      'aria-pressed': effects ? 'true' : 'false',
      onclick: () => onChange(now, !effects),
    }, 'Effects'));
}
