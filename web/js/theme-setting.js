// The theme control in the header (Train 2 unit TH1): Terminal or Paper, and the screen
// effects on or off. Storage is a parameter; nothing touches `window` on import.

/** `{ theme(), effects(), save(theme, effects) }` over `rv.theme` and `rv.effects`; safe with no storage or a blocked one. */
export function themeStore(storage) { // contract stub
  return { theme: () => 'terminal', effects: () => false, save: () => {} };
}

/** The other theme: terminal gives paper, anything else gives terminal. */
export function nextTheme(current) { // contract stub
  return 'terminal';
}

/**
 * A labelled group: a button that switches between "Terminal" and "Paper" (its label names
 * the current one, `aria-pressed` false) and an "Effects" toggle (`aria-pressed`), each
 * calling `onChange(theme, effects)`.
 */
export function themeControl({ theme, effects, onChange }) { // contract stub
  return null;
}
