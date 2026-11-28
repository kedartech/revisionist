// The offline shell: `sw.js` keeps the shell and each map object by its hash and answers them
// from its stores first; nothing under /api/ is stored; a new version waits for the player's word;
// a session's change empties every store but the shell. `js/shell.js` registers it, removes it on
// `?no-worker`, says in one line when the device is offline and offers a waiting version.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const ORIGIN = 'https://rv.test';
const ANCHOR = 'const SHELL = {"version": "", "files": []};';
const SOURCE = readFileSync(new URL('../sw.js', import.meta.url), 'utf8');
const FILES = ['/index.html', '/js/app.js', '/css/tokens.css', '/fonts/plex.woff2'];
const HASH = 'a'.repeat(64);
const MAP_URL = `${ORIGIN}/maps/${HASH}.json`;

const {
  OFFLINE_LINE, UPDATE_LINE, startWorker, watchNetwork, offerUpdate,
} = await import('../js/shell.js');

/** A cache storage that holds responses by URL, store by store. */
function fakeCaches(net) {
  const stores = new Map();
  const keyOf = (r) => (typeof r === 'string' ? r : r.url);
  const store = (name) => ({
    match: async (r) => stores.get(name)?.get(keyOf(r))?.clone(),
    put: async (r, res) => { stores.get(name).set(keyOf(r), res); },
    addAll: async (reqs) => {
      for (const r of reqs) {
        const res = await net.fetch(r);
        if (!res.ok) throw new TypeError(`addAll: ${r.url} ${res.status}`);
        stores.get(name).set(keyOf(r), res);
      }
    },
  });
  return {
    stores,
    open: async (name) => { if (!stores.has(name)) stores.set(name, new Map()); return store(name); },
    keys: async () => [...stores.keys()],
    delete: async (name) => stores.delete(name),
    urls: () => [...stores.values()].flatMap((m) => [...m.keys()]),
  };
}

/** A network that answers every URL with its path, or fails every call when offline. */
function fakeNet() {
  const net = { offline: false, calls: [] };
  net.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    net.calls.push({ url, method: init.method ?? input.method ?? 'GET', cache: init.cache ?? input.cache });
    if (net.offline) throw new TypeError('Failed to fetch');
    return new Response(`body of ${new URL(url).pathname}`, { status: 200 });
  };
  return net;
}

/** Loads sw.js in its own context, as the server serves it, and hands back what it registered. */
function loadWorker({ version = 'v1', files = FILES } = {}) {
  const net = fakeNet();
  const caches = fakeCaches(net);
  const on = {};
  const self = {
    location: { origin: ORIGIN },
    addEventListener: (type, fn) => { on[type] = fn; },
    skipped: 0,
    skipWaiting() { this.skipped += 1; return Promise.resolve(); },
    clients: { claim: async () => {} },
  };
  const filled = SOURCE.replace(ANCHOR, `const SHELL = ${JSON.stringify({ version, files })};`);
  vm.runInNewContext(filled, { self, caches, fetch: (...a) => net.fetch(...a), URL, Request, Response });
  const lifecycle = async (type) => {
    const waits = [];
    on[type]({ waitUntil: (p) => waits.push(p) });
    await Promise.all(waits);
  };
  /** Fires a fetch event: the worker's answer (undefined when it lets the network have it). */
  const request = async (path, { method = 'GET', mode = 'cors' } = {}) => {
    const url = path.startsWith('http') ? path : ORIGIN + path;
    const ev = {
      request: { url, method, mode },
      answer: undefined,
      waits: [],
      respondWith(p) { this.answer = p; },
      waitUntil(p) { this.waits.push(p); },
    };
    on.fetch(ev);
    await Promise.all(ev.waits);
    return ev.answer === undefined ? undefined : ev.answer;
  };
  return { self, net, caches, on, lifecycle, request };
}

const installed = async (opts) => {
  const w = loadWorker(opts);
  await w.lifecycle('install');
  await w.lifecycle('activate');
  w.net.calls.length = 0;
  return w;
};

test('sw.js carries the line the server fills in, once', () => {
  assert.equal(SOURCE.split(ANCHOR).length, 2);
});

// --- rule 1: the shell and each map object by its hash, from the store first ----------------

test('installing keeps every shell file, fetched past the browser cache', async () => {
  const w = loadWorker();
  await w.lifecycle('install');
  assert.deepEqual(w.caches.urls().sort(), FILES.map((f) => ORIGIN + f).sort());
  assert.ok(w.net.calls.every((c) => c.cache === 'no-cache'));
  assert.deepEqual([...w.caches.stores.keys()], ['revisionist-shell-v1']);
});

test('a shell file is answered from the store with no network', async () => {
  const w = await installed();
  w.net.offline = true;
  const res = await w.request('/js/app.js');
  assert.equal(await res.text(), 'body of /js/app.js');
  assert.equal(w.net.calls.length, 0);
});

test('a navigation to the page or a client route is answered with the kept page', async () => {
  const w = await installed();
  w.net.offline = true;
  for (const path of ['/', '/home']) {
    const res = await w.request(path, { mode: 'navigate' });
    assert.equal(await res.text(), 'body of /index.html', path);
  }
  assert.equal(w.net.calls.length, 0);
});

test('a map object is fetched once by its hash, kept, then answered from the store', async () => {
  const w = await installed();
  const first = await w.request(MAP_URL);
  assert.equal(await first.text(), `body of /maps/${HASH}.json`);
  assert.equal(w.net.calls.length, 1);
  assert.equal(w.net.calls[0].cache, 'no-store');
  w.net.offline = true;
  const again = await w.request(MAP_URL);
  assert.equal(await again.text(), `body of /maps/${HASH}.json`);
  assert.equal(w.net.calls.length, 1);
  assert.ok(w.caches.stores.get('revisionist-maps').has(MAP_URL));
});

test('a refused map object is not kept, nor any path that is not a hash', async () => {
  const w = await installed();
  w.net.fetch = async () => new Response('{}', { status: 404 });
  await w.request(MAP_URL);
  assert.equal(w.caches.stores.get('revisionist-maps')?.size ?? 0, 0);
  assert.equal(await w.request('/maps/latest.json'), undefined);
  assert.equal(await w.request(`/maps/${HASH}.json?x=1`), undefined);
});

test('another origin and a file outside the shell are left to the network', async () => {
  const w = await installed();
  assert.equal(await w.request('https://elsewhere.test/js/app.js'), undefined);
  assert.equal(await w.request('/icons/logo-1024.png'), undefined);
  assert.equal(await w.request('/js/app.js', { method: 'POST' }), undefined);
});

// --- rule 2: /api/ goes to the network only, never stored -----------------------------------

test('nothing under /api/ is answered by the worker or stored, read or write', async () => {
  const w = await installed();
  for (const [path, method] of [['/api/me', 'GET'], ['/api/realism/map', 'POST'], ['/api/realism/commit', 'POST'], ['/api/seat/status', 'POST']]) {
    assert.equal(await w.request(path, { method }), undefined, path);
  }
  assert.ok(w.caches.urls().every((u) => !new URL(u).pathname.startsWith('/api/')));
  assert.equal(w.net.calls.length, 0);
});

// --- rule 3: offline, the shell opens and nothing is committed ------------------------------

test('offline, the page and its files open from the store and a commit is not answered', async () => {
  const w = await installed();
  w.net.offline = true;
  for (const f of FILES) assert.equal((await w.request(f)).status, 200, f);
  assert.equal(await w.request('/api/realism/commit', { method: 'POST' }), undefined);
});

// --- rule 4: a new version waits for the player's word --------------------------------------

test('a new version installs and waits; it takes over only when the page asks', async () => {
  const w = loadWorker({ version: 'v2' });
  await w.lifecycle('install');
  assert.equal(w.self.skipped, 0);
  w.on.message({ data: { type: 'something-else' } });
  assert.equal(w.self.skipped, 0);
  w.on.message({ data: { type: 'take-over' } });
  assert.equal(w.self.skipped, 1);
});

test('taking over drops the old shell and keeps the map objects', async () => {
  const w = loadWorker({ version: 'v2' });
  for (const name of ['revisionist-shell-v1', 'revisionist-maps']) await w.caches.open(name);
  await w.lifecycle('install');
  await w.lifecycle('activate');
  assert.deepEqual([...w.caches.stores.keys()].sort(), ['revisionist-maps', 'revisionist-shell-v2']);
});

// --- rule 5: a session's change empties every store but the shell ---------------------------

test('signing out empties every store but the shell', async () => {
  for (const path of ['/api/signout', '/api/signout-all', '/api/signin', '/api/signup', '/api/recover']) {
    const w = await installed();
    await w.request(MAP_URL);
    await w.caches.open('something-else');
    assert.equal(await w.request(path, { method: 'POST' }), undefined, path);
    assert.deepEqual([...w.caches.stores.keys()], ['revisionist-shell-v1'], path);
    assert.equal(w.caches.stores.get('revisionist-shell-v1').size, FILES.length, path);
  }
});

test('a map object on its way when the session ends is not kept', async () => {
  const w = await installed();
  let land;
  w.net.fetch = () => new Promise((resolve) => { land = () => resolve(new Response('m', { status: 200 })); });
  const pending = w.request(MAP_URL);
  await new Promise((r) => setTimeout(r, 0));
  await w.request('/api/signout', { method: 'POST' });
  land();
  await pending;
  assert.equal(w.caches.stores.get('revisionist-maps')?.size ?? 0, 0);
});

// --- the page's side: js/shell.js -----------------------------------------------------------

/** A window with a body that holds the shell's lines, a service worker container and caches. */
function fakePage({ search = '', online = true, active = {}, waiting = null, sw = true } = {}) {
  const listen = () => {
    const on = {};
    return {
      on,
      addEventListener: (type, fn) => { (on[type] ??= []).push(fn); },
      fire: (type, ev = {}) => { for (const fn of on[type] ?? []) fn(ev); },
    };
  };
  const node = (tag) => {
    const el = {
      tagName: tag.toUpperCase(), attrs: {}, children: [], textContent: '', parent: null, ...listen(),
      setAttribute(k, v) { this.attrs[k] = String(v); },
      getAttribute(k) { return this.attrs[k] ?? null; },
      append(...kids) { for (const k of kids) { if (typeof k === 'object') k.parent = this; this.children.push(k); } },
      remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null; },
      click() { this.fire('click'); },
    };
    return el;
  };
  const body = node('body');
  const reg = { ...listen(), waiting, active, installing: null, updates: 0, unregistered: 0,
    update() { this.updates += 1; return Promise.resolve(); },
    unregister() { this.unregistered += 1; return Promise.resolve(true); } };
  const container = { ...listen(), registered: [],
    register: async (url, opts) => { container.registered.push([url, opts]); return reg; },
    getRegistrations: async () => [reg] };
  const deleted = [];
  const win = {
    ...listen(),
    reloaded: 0,
    timers: [],
    location: { search, reload() { win.reloaded += 1; } },
    navigator: { onLine: online, ...(sw ? { serviceWorker: container } : {}) },
    document: { body, createElement: node },
    caches: { keys: async () => ['revisionist-shell-v1', 'revisionist-maps'], delete: async (n) => { deleted.push(n); return true; } },
    setInterval: (fn, ms) => { win.timers.push([fn, ms]); return 1; },
  };
  const lines = () => body.children.flatMap((c) => c.children).filter((c) => c.attrs?.['data-line']);
  const line = (key) => lines().find((c) => c.attrs['data-line'] === key);
  return { win, reg, container, deleted, body, lines, line };
}

test('the page registers the worker at the root and looks for a new version now and then', async () => {
  const p = fakePage();
  assert.equal(await startWorker(p.win), p.reg);
  assert.deepEqual(p.container.registered, [['/sw.js', { scope: '/' }]]);
  assert.equal(p.win.timers.length, 1);
  p.win.timers[0][0]();
  assert.equal(p.reg.updates, 1);
});

test('a browser with no service worker gets the page as it was', async () => {
  const p = fakePage({ sw: false });
  assert.equal(await startWorker(p.win), null);
  assert.equal(await startWorker(undefined), null);
});

// rule 6
test('?no-worker unregisters the worker and empties its stores, and registers none', async () => {
  const p = fakePage({ search: '?no-worker' });
  assert.equal(await startWorker(p.win), null);
  assert.equal(p.reg.unregistered, 1);
  assert.deepEqual(p.deleted.sort(), ['revisionist-maps', 'revisionist-shell-v1']);
  assert.deepEqual(p.container.registered, []);
});

// rule 3
test('offline, the page says in one line that orders cannot be sent; online, the line goes', () => {
  const p = fakePage({ online: false });
  watchNetwork(p.win);
  assert.equal(p.lines().length, 1);
  assert.equal(p.line('offline').textContent, OFFLINE_LINE);
  assert.equal(p.line('offline').attrs.role, 'status');
  assert.match(OFFLINE_LINE, /orders cannot be sent/i);
  p.win.navigator.onLine = true;
  p.win.fire('online');
  assert.equal(p.lines().length, 0);
  p.win.navigator.onLine = false;
  p.win.fire('offline');
  p.win.fire('offline');
  assert.equal(p.lines().length, 1);
});

test('online, no line is shown', () => {
  const p = fakePage();
  watchNetwork(p.win);
  assert.equal(p.lines().length, 0);
});

// rule 4
/** A worker of the registration's: it records what the page posts and fires its state changes. */
function fakeWorker(state = 'installed') {
  const on = {};
  const w = {
    state, posted: [],
    addEventListener: (type, fn) => { (on[type] ??= []).push(fn); },
    postMessage(m) { w.posted.push(m); },
    become(next) { w.state = next; for (const fn of on.statechange ?? []) fn(); },
  };
  return w;
}

test('a waiting version is offered, and taken over only on the player\'s word, then the page reloads', () => {
  const waiting = fakeWorker();
  const p = fakePage({ waiting });
  offerUpdate(p.win, p.reg);
  const offer = p.line('update');
  assert.ok(offer);
  assert.match(offer.textContent, new RegExp(UPDATE_LINE));
  assert.equal(UPDATE_LINE, 'A new version is ready.');
  assert.deepEqual(waiting.posted, []);
  waiting.become('activated');
  assert.equal(p.win.reloaded, 0, 'nothing reloads the page before the player asks');
  waiting.state = 'installed';
  const button = offer.children.find((c) => c.tagName === 'BUTTON');
  button.click();
  assert.deepEqual(waiting.posted, [{ type: 'take-over' }]);
  assert.equal(p.win.reloaded, 0);
  waiting.become('activating');
  assert.equal(p.win.reloaded, 0);
  waiting.become('activated');
  assert.equal(p.win.reloaded, 1);
});

test('a version found while the page is open is offered once it has installed', () => {
  const p = fakePage();
  offerUpdate(p.win, p.reg);
  assert.equal(p.line('update'), undefined);
  const next = fakeWorker('installing');
  p.reg.installing = next;
  p.reg.fire('updatefound');
  assert.equal(p.line('update'), undefined);
  next.become('installed');
  assert.ok(p.line('update'));
  assert.deepEqual(next.posted, []);
});

test('the first install is not offered as a new version', () => {
  const p = fakePage({ active: null, waiting: fakeWorker() });
  offerUpdate(p.win, p.reg);
  assert.equal(p.line('update'), undefined);
});
