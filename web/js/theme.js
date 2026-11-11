// The theme setting: Terminal (the default) or Paper, kept in the browser under `rv.theme`.
// Storage is a parameter, so nothing here touches `window` when the module is imported.

export const THEMES = ['terminal', 'paper'];
export const THEME_KEY = 'rv.theme';

/** The stored theme, or `terminal` when it is missing, unknown or storage is blocked. */
export function themeName(storage) {
  try {
    const stored = storage?.getItem(THEME_KEY);
    return THEMES.includes(stored) ? stored : 'terminal';
  } catch {
    return 'terminal';
  }
}

/** Sets `data-theme` on the page's root element: the CSP allows a stylesheet keyed on an attribute, not inline style. */
export function applyTheme(root, storage) {
  root.dataset.theme = themeName(storage);
}
