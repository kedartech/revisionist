// The theme setting: Paper (the default) or Terminal, kept in the browser under `rv.theme`,
// and the screen effects, off unless `rv.effects` is "on".
// Storage is a parameter, so nothing here touches `window` when the module is imported.

export const THEMES = ['terminal', 'paper'];
export const DEFAULT_THEME = 'paper';
export const THEME_KEY = 'rv.theme';
export const EFFECTS_KEY = 'rv.effects';

/** The stored theme, or `DEFAULT_THEME` when it is missing, unknown or storage is blocked. */
export function themeName(storage) {
  try {
    const stored = storage?.getItem(THEME_KEY);
    return THEMES.includes(stored) ? stored : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

/** True only when `rv.effects` is "on"; false when missing or storage is blocked. */
export function effectsOn(storage) {
  try {
    return storage?.getItem(EFFECTS_KEY) === 'on';
  } catch {
    return false;
  }
}

/**
 * Sets `data-theme` and `data-effects` on the page's root element: the CSP allows a
 * stylesheet keyed on an attribute, not inline style.
 */
export function applyTheme(root, storage) {
  root.dataset.theme = themeName(storage);
  root.dataset.effects = effectsOn(storage) ? 'on' : 'off';
}

/** The page's `localStorage`, or undefined where the browser blocks reading it. */
export function browserStorage(win) {
  try {
    return win?.localStorage;
  } catch {
    return undefined;
  }
}
