// The opening of a game (Train 3 unit P4): the crawl that sets the scene, shown while the
// host's Begin runs and to every other player on first entry, then the player's own
// splash. Once per game per browser; never blocks a player whose storage is blocked.

import { h } from '../dom.js';

export const INTRO_PREFIX = 'rv.intro.';
export const TAKE_DESK = 'Take your desk';
export const NOT_BINDING = 'As history had it. You are not bound by it.';

/** The setting's crawl paragraphs: trimmed, empty ones dropped, at most three. contract stub */
export function crawlParagraphs(setting) {
  return [];
}

/**
 * The splash for the seat named `name`, from the desk and the dossier:
 * `{ title, office, answersTo, arena, history, note, action }`. `title` is "You are <name>";
 * `office` the desk's office or null; `answersTo` "Answers to <principals joined by ', '>" or
 * null with none; `arena` the dossier's arena or null; `history` its lines (may be []);
 * `note` NOT_BINDING when there are history lines, else null; `action` TAKE_DESK.
 * contract stub
 */
export function splashModel(name, desk, dossier) {
  return { title: '', office: null, answersTo: null, arena: null, history: [], note: null, action: TAKE_DESK };
}

/**
 * What to show now for campaign `campaignId`: 'crawl', 'splash' or null. `fresh` is false
 * once the seat has filed an order (an old game gets no intro): then null. The stored value
 * under `INTRO_PREFIX + campaignId` is 'crawl' once the crawl was seen and 'done' once the
 * splash was taken: nothing stored gives 'crawl', 'crawl' gives 'splash', 'done' gives null.
 * A store that throws gives null.
 * contract stub
 */
export function introStage(store, campaignId, fresh) {
  return null;
}

/** Record that `stage` ('crawl' or 'splash') was seen: stores 'crawl' or 'done'. Swallows a throwing store. contract stub */
export function markIntro(store, campaignId, stage) {}

/**
 * `<dialog class="rl-intro" aria-labelledby="rl-intro-title">`: an h2 `title` (the game's
 * name), the paragraphs rising by CSS animation inside `.rl-intro-crawl`, a
 * `p.rl-intro-status[role=status]` the caller writes progress into, and a "Continue" button.
 * Continue, and the dialog's `cancel` (Esc), call `onDone()` once. Under reduced motion the
 * text is static (CSS).
 * contract stub
 */
export function introCrawl({ title, paragraphs = [], onDone } = {}) {
  return h('dialog', { class: 'rl-intro', 'aria-labelledby': 'rl-intro-title' },
    h('h2', { id: 'rl-intro-title' }, title ?? ''));
}

/**
 * `<dialog class="rl-intro rl-intro-splash" aria-labelledby="rl-intro-splash-title">` from a
 * `splashModel`: `portraitNode(name, dossier, 'rl-intro')`, the h2 title, the office and
 * answers-to lines, the arena paragraph, the history list under an h3 "As history had it" with
 * the note, and a primary "Take your desk" button. The button and Esc call `onDone()` once.
 * contract stub
 */
export function seatSplash({ name, model, dossier = null, onDone } = {}) {
  return h('dialog', { class: 'rl-intro rl-intro-splash', 'aria-labelledby': 'rl-intro-splash-title' },
    h('h2', { id: 'rl-intro-splash-title' }, model?.title ?? ''));
}
