// The service worker. It keeps the shell (the page, its scripts, styles, fonts, icons and
// assets) and each map object by its hash, and answers them from its stores before the network.
// Nothing under /api/ is answered or stored here. A new version installs and waits until the
// page, on the player's word, asks it to take over. A sign-in, sign-up, recovery or sign-out
// empties every store but the shell, so the device keeps nothing of a player's game.
// The server fills in the SHELL line (src/revisionist/engine/web/worker.py).

const SHELL = {"version": "", "files": []};

const SHELL_STORE = `revisionist-shell-${SHELL.version}`;
const MAP_STORE = 'revisionist-maps';
const PAGE = '/index.html';
const MAP_OBJECT = /^\/maps\/[0-9a-f]{64}\.json$/;
const SESSION_CHANGES = new Set(['/api/signin', '/api/signup', '/api/recover', '/api/signout', '/api/signout-all']);
const kept = new Set(SHELL.files);

const at = (path) => new URL(path, self.location.origin).href;

// Raised by each emptying, so a map object that was on its way when the session changed is not stored.
let era = 0;

async function keepShell() {
  const store = await caches.open(SHELL_STORE);
  await store.addAll(SHELL.files.map((path) => new Request(at(path), { cache: 'no-cache' })));
}

async function dropOld() {
  for (const name of await caches.keys()) {
    if (name.startsWith('revisionist-') && name !== SHELL_STORE && name !== MAP_STORE) await caches.delete(name);
  }
  await self.clients.claim();
}

async function forget() {
  era += 1;
  for (const name of await caches.keys()) if (name !== SHELL_STORE) await caches.delete(name);
}

async function fromShell(path, request) {
  const store = await caches.open(SHELL_STORE);
  const hit = await store.match(at(path));
  if (hit) return hit;
  const res = await fetch(request);
  if (res.status === 200 && kept.has(path)) await store.put(at(path), res.clone());
  return res;
}

async function mapObject(url) {
  const store = await caches.open(MAP_STORE);
  const hit = await store.match(url);
  if (hit) return hit;
  const then = era;
  const res = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
  if (res.status === 200 && then === era) await store.put(url, res.clone());
  return res;
}

function onFetch(event) {
  const req = event.request;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) {
    if (req.method === 'POST' && SESSION_CHANGES.has(url.pathname)) event.waitUntil(forget());
    return;
  }
  if (req.method !== 'GET') return;
  if (MAP_OBJECT.test(url.pathname) && !url.search) {
    event.respondWith(mapObject(url.href));
    return;
  }
  if (req.mode === 'navigate') {
    if (url.searchParams.has('no-worker')) return;
    if (!url.pathname.split('/').pop().includes('.')) {
      event.respondWith(fromShell(PAGE, req));
      return;
    }
  }
  if (kept.has(url.pathname) && !url.search) event.respondWith(fromShell(url.pathname, req));
}

self.addEventListener('install', (event) => event.waitUntil(keepShell()));
self.addEventListener('activate', (event) => event.waitUntil(dropOld()));
self.addEventListener('fetch', onFetch);
self.addEventListener('message', (event) => {
  if (event.data?.type === 'take-over') self.skipWaiting();
});
