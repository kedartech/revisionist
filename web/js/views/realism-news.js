// The "What changed" block on the desk (Phase 4 unit H1): the newest unread press pages, so a
// player opening the room sees what the papers report first. Built from view.realism's listing.

import { h } from '../dom.js';

/** The newest unread press pages, newest first (ties by id), as the block lists them. */
export function whatChanged(listing, limit = 5) {
  return listing.documents
    .filter((d) => d.kind === 'press' && d.unread === true)
    .sort((a, b) => b.issued.localeCompare(a.issued) || a.id.localeCompare(b.id))
    .slice(0, limit)
    .map((d) => ({ id: d.id, title: d.title, paper: d.author, issued: d.issued }));
}

/** The block above the room, or null when no press page is unread. */
export function newsBlock(items, onOpen) {
  if (!items.length) return null;
  return h('section', { class: 'rl-news', 'aria-labelledby': 'rl-news-h' },
    h('h2', { id: 'rl-news-h' }, 'What changed'),
    h('ul', { role: 'list' }, items.map((d) => h('li', {},
      h('button', { type: 'button', class: 'rl-btn', onclick: () => onOpen?.(d.id) },
        `${d.paper}: ${d.title}`)))));
}
