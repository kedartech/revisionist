// The app shell: knows whether the page runs as an installed app and says so on the root element
// (`data-shell="app"` or `"tab"`), following a change of display mode. It runs on its own when
// the page loads it; with no window (a test, a server) importing it does nothing.

const APP_MODES = ['standalone', 'fullscreen', 'minimal-ui'];

/** True when the page was opened from the home screen or an Android wrapper, not a browser tab. */
export function isInstalled(win) {
  const mode = (m) => win?.matchMedia?.(`(display-mode: ${m})`)?.matches === true;
  if (APP_MODES.some(mode)) return true;
  if (win?.navigator?.standalone === true) return true;
  return String(win?.document?.referrer ?? '').startsWith('android-app://');
}

/** Marks the root element and keeps the mark current. Returns false where there is no window. */
export function startShell(win) {
  const root = win?.document?.documentElement;
  if (!root) return false;
  const mark = () => root.setAttribute('data-shell', isInstalled(win) ? 'app' : 'tab');
  mark();
  for (const m of APP_MODES) win.matchMedia?.(`(display-mode: ${m})`)?.addEventListener?.('change', mark);
  return true;
}

startShell(typeof window === 'undefined' ? undefined : window);
