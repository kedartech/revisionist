// The app shell: knows whether the page runs as an installed app and says so on the root element
// (`data-shell="app"` or `"tab"`), following a change of display mode. It registers the service
// worker (`/sw.js`), or removes it and its stores when the address has `?no-worker`; says in one
// line when the device is offline; and offers a waiting new version, which takes over only on the
// player's word. It runs on its own when the page loads it; with no window (a test, a server)
// importing it does nothing.

const APP_MODES = ['standalone', 'fullscreen', 'minimal-ui'];
const WORKER = '/sw.js';
const LOOK_FOR_UPDATE_MS = 30 * 60 * 1000;
export const OFFLINE_LINE = 'Offline: orders cannot be sent until the connection is back.';
export const UPDATE_LINE = 'A new version is ready.';

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

// the lines each window shows, by key, in one box of its own
const shown = new WeakMap();

/** Shows the shell's line `key` with `text`, and a button when `act` is given; one line per key. */
function showLine(win, key, text, act) {
  const doc = win.document;
  let lines = shown.get(win);
  if (!lines) {
    const box = doc.createElement('div');
    box.setAttribute('class', 'shell-lines');
    doc.body.append(box);
    lines = { box, by: new Map() };
    shown.set(win, lines);
  }
  if (lines.by.has(key)) return;
  const line = doc.createElement('p');
  line.setAttribute('class', `shell-line shell-${key}`);
  line.setAttribute('data-line', key);
  line.setAttribute('role', 'status');
  line.textContent = text;
  if (act) {
    const button = doc.createElement('button');
    button.setAttribute('type', 'button');
    button.setAttribute('class', 'rl-btn');
    button.textContent = act.label;
    button.addEventListener('click', act.run);
    line.append(' ', button);
  }
  lines.box.append(line);
  lines.by.set(key, line);
}

function hideLine(win, key) {
  const lines = shown.get(win);
  lines?.by.get(key)?.remove();
  lines?.by.delete(key);
}

/** Keeps the offline line shown while the browser says it has no network. */
export function watchNetwork(win) {
  if (!win?.document?.body) return false;
  const mark = () => (win.navigator?.onLine === false ? showLine(win, 'offline', OFFLINE_LINE) : hideLine(win, 'offline'));
  mark();
  win.addEventListener?.('online', mark);
  win.addEventListener?.('offline', mark);
  return true;
}

/** Offers a waiting version of the worker; on the player's word it takes over and the page reloads. */
export function offerUpdate(win, reg) {
  const offer = (waiting) => {
    // a first install replaces no active worker, so there is nothing to offer
    if (!waiting || !reg.active) return;
    showLine(win, 'update', UPDATE_LINE, {
      label: 'Reload',
      run: () => {
        waiting.addEventListener('statechange', () => { if (waiting.state === 'activated') win.location.reload(); });
        waiting.postMessage({ type: 'take-over' });
      },
    });
  };
  if (reg.waiting) offer(reg.waiting);
  reg.addEventListener('updatefound', () => {
    const next = reg.installing;
    next?.addEventListener('statechange', () => { if (next.state === 'installed') offer(next); });
  });
}

/** Registers the worker, or with `?no-worker` in the address removes it and empties its stores. */
export async function startWorker(win) {
  const sw = win?.navigator?.serviceWorker;
  if (!sw) return null;
  if (new URLSearchParams(win.location?.search ?? '').has('no-worker')) {
    for (const reg of await sw.getRegistrations()) await reg.unregister();
    for (const name of (await win.caches?.keys()) ?? []) await win.caches.delete(name);
    return null;
  }
  const reg = await sw.register(WORKER, { scope: '/' });
  offerUpdate(win, reg);
  win.setInterval(() => { reg.update().catch(() => {}); }, LOOK_FOR_UPDATE_MS);
  return reg;
}

const page = typeof window === 'undefined' ? undefined : window;
startShell(page);
watchNetwork(page);
startWorker(page).catch(() => {});
