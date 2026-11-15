// Browser storage, read safely. The screen effects are plain CSS (css/effects.css) with no
// setting, so a value a browser kept from the old toggle is never read.
// Nothing here touches `window` when the module is imported.

/** The page's `localStorage`, or undefined where the browser blocks reading it. */
export function browserStorage(win) {
  try {
    return win?.localStorage;
  } catch {
    return undefined;
  }
}
