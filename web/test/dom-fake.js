// A small stand-in DOM for the node specs: enough for `h()`, dialogs, buttons, events and
// `querySelector` with simple selectors. No layout and no CSS. A view that needs more than
// this from the DOM is doing more than the room's views do.
//
// Supported: createElement, createElementNS, createTextNode; setAttribute, getAttribute,
// hasAttribute, removeAttribute, toggleAttribute; className, classList (add, remove,
// contains, toggle), id; append, prepend, before, after, remove, replaceChildren,
// textContent, children, isConnected; addEventListener, removeEventListener,
// dispatchEvent, click (nothing on a disabled element), focus, blur; showModal, show,
// close (fires `close`), open; querySelector, querySelectorAll, matches, closest with
// selectors made of a tag, classes and `[attr]` or `[attr="v"]`, joined by spaces.

const event = (type) => ({
  type,
  target: null,
  defaultPrevented: false,
  preventDefault() { this.defaultPrevented = true; },
  stopPropagation() {},
});

function simple(el, part) {
  const m = part.match(/^([a-zA-Z0-9-]*)((?:\.[\w-]+)*)((?:\[[^\]]+\])*)$/);
  if (!m) throw new Error(`dom-fake: unsupported selector part ${part}`);
  const [, tag, classes, attrs] = m;
  if (tag && el.tagName !== tag.toUpperCase()) return false;
  for (const c of classes.split('.').filter(Boolean)) if (!el.classList.contains(c)) return false;
  for (const a of attrs.match(/\[[^\]]+\]/g) ?? []) {
    const [, name, value] = a.match(/^\[([\w-]+)(?:="([^"]*)")?\]$/) ?? [];
    if (!name) throw new Error(`dom-fake: unsupported attribute selector ${a}`);
    if (!el.hasAttribute(name)) return false;
    if (value !== undefined && el.getAttribute(name) !== value) return false;
  }
  return true;
}

function matches(el, selector) {
  return selector.split(',').some((one) => {
    const parts = one.trim().split(/\s+/);
    if (!simple(el, parts.at(-1))) return false;
    let at = el.parentNode;
    for (let i = parts.length - 2; i >= 0; i -= 1) {
      while (at && !(at instanceof Element && simple(at, parts[i]))) at = at.parentNode;
      if (!at) return false;
      at = at.parentNode;
    }
    return true;
  });
}

let doc = null;

class Node {
  constructor() {
    this.parentNode = null;
    this.childNodes = [];
  }

  get isConnected() {
    let n = this;
    while (n.parentNode) n = n.parentNode;
    return n === doc?.body;
  }

  remove() {
    const p = this.parentNode;
    if (!p) return;
    p.childNodes.splice(p.childNodes.indexOf(this), 1);
    this.parentNode = null;
  }

  before(...nodes) {
    const p = this.parentNode;
    if (p) p.insertAt(p.childNodes.indexOf(this), nodes);
  }

  after(...nodes) {
    const p = this.parentNode;
    if (p) p.insertAt(p.childNodes.indexOf(this) + 1, nodes);
  }
}

class Text extends Node {
  constructor(data) {
    super();
    this.data = String(data);
  }

  get textContent() { return this.data; }
}

class Element extends Node {
  constructor(tag) {
    super();
    this.tagName = String(tag).toUpperCase();
    this.attrs = new Map();
    this.listeners = new Map();
    this.disabled = false;
    this.open = false;
    this.value = '';
    this.checked = false;
  }

  get className() { return this.getAttribute('class') ?? ''; }
  set className(v) { this.setAttribute('class', v); }
  get id() { return this.getAttribute('id') ?? ''; }
  set id(v) { this.setAttribute('id', v); }

  get classList() {
    const names = () => this.className.split(/\s+/).filter(Boolean);
    const set = (xs) => this.setAttribute('class', xs.join(' '));
    return {
      contains: (c) => names().includes(c),
      add: (...cs) => set([...new Set([...names(), ...cs])]),
      remove: (...cs) => set(names().filter((n) => !cs.includes(n))),
      toggle: (c, force) => {
        const on = force ?? !names().includes(c);
        if (on) set([...new Set([...names(), c])]);
        else set(names().filter((n) => n !== c));
        return on;
      },
    };
  }

  setAttribute(k, v) { this.attrs.set(k, String(v)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  hasAttribute(k) { return this.attrs.has(k); }
  removeAttribute(k) { this.attrs.delete(k); }
  toggleAttribute(k, force) {
    const on = force ?? !this.attrs.has(k);
    if (on) this.attrs.set(k, '');
    else this.attrs.delete(k);
    return on;
  }

  insertAt(i, nodes) {
    const items = nodes.map((n) => (n instanceof Node ? n : new Text(n)));
    for (const n of items) n.remove();
    this.childNodes.splice(i, 0, ...items);
    for (const n of items) n.parentNode = this;
  }

  append(...nodes) { this.insertAt(this.childNodes.length, nodes); }
  prepend(...nodes) { this.insertAt(0, nodes); }

  replaceChildren(...nodes) {
    for (const c of [...this.childNodes]) c.remove();
    this.append(...nodes);
  }

  get textContent() { return this.childNodes.map((c) => c.textContent).join(''); }
  set textContent(v) { this.replaceChildren(String(v ?? '')); }
  get children() { return this.childNodes.filter((c) => c instanceof Element); }
  get firstChild() { return this.childNodes[0] ?? null; }
  get firstElementChild() { return this.children[0] ?? null; }

  addEventListener(type, fn) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(fn);
  }

  removeEventListener(type, fn) {
    const fns = this.listeners.get(type) ?? [];
    if (fns.includes(fn)) fns.splice(fns.indexOf(fn), 1);
  }

  dispatchEvent(ev) {
    ev.target ??= this;
    for (const fn of [...(this.listeners.get(ev.type) ?? [])]) fn.call(this, ev);
    return !ev.defaultPrevented;
  }

  click() {
    if (!this.disabled) this.dispatchEvent(event('click'));
  }

  focus() { doc.activeElement = this; }
  blur() { if (doc.activeElement === this) doc.activeElement = doc.body; }
  showModal() { this.open = true; }
  show() { this.open = true; }

  close() {
    if (!this.open) return;
    this.open = false;
    this.dispatchEvent(event('close'));
  }

  querySelectorAll(selector) {
    const out = [];
    const walk = (n) => {
      for (const c of n.childNodes) {
        if (!(c instanceof Element)) continue;
        if (matches(c, selector)) out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }

  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
  matches(selector) { return matches(this, selector); }

  closest(selector) {
    for (let n = this; n instanceof Element; n = n.parentNode) if (matches(n, selector)) return n;
    return null;
  }
}

/** Install the fake as `globalThis.document` and `globalThis.Node`; returns the document. */
export function installDom() {
  doc = {
    createElement: (tag) => new Element(tag),
    createElementNS: (_ns, tag) => new Element(tag),
    createTextNode: (data) => new Text(data),
    body: new Element('body'),
    activeElement: null,
  };
  doc.activeElement = doc.body;
  globalThis.document = doc;
  globalThis.Node = Node;
  return doc;
}

/** Dispatch a plain event of `type` on `el`; returns the event (read `defaultPrevented`). */
export function fire(el, type) {
  const ev = event(type);
  el.dispatchEvent(ev);
  return ev;
}

/** The visible words of `el`, whitespace collapsed. */
export const words = (el) => el.textContent.replace(/\s+/g, ' ').trim();

/** The buttons under `el` whose words are exactly `label`. */
export const buttons = (el, label) => el.querySelectorAll('button').filter((b) => words(b) === label);
