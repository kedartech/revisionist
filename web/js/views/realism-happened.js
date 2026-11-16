// "What happened" (Train 2 unit W): the sheet that opens once when a new wake opens.

import { h } from '../dom.js';
import { aideBriefing, briefingLines, slowOrders } from './realism-briefing.js';
import { movesBlock } from './realism-moves.js';

export const HAPPENED_PREFIX = 'rv.happened.';

/** Verb phrase for each settled order status; a status missing here reads as its bare word. */
export const STATUS_SENTENCE = Object.freeze({
  enacted: 'has been enacted',
  refused: 'has been refused',
  lapsed: 'has lapsed',
  withdrawn: 'has been withdrawn',
  agreed: 'has been agreed to',
  rebuffed: 'has been rebuffed',
  'carried out': 'has been carried out',
  'carried out loosely': 'has been carried out loosely',
  'carried out late': 'has been carried out late',
  'carried out in part': 'has been carried out in part',
});

/**
 * One sentence per order that is moving or settled since the last wake (`record.wake.settled`):
 * moving “<asked>” is under way, with <holder> (no holder: just under way); settled
 * “<asked>” plus its `STATUS_SENTENCE` phrase, or “<asked>”: <status> when the status is not
 * in the table. An answer (`said`) follows after a space in curly quotes.
 */
export function happenedLines(record) {
  const settled = record?.wake?.settled ?? [];
  return (record?.orders ?? [])
    .filter((o) => o.moving || settled.includes(o.id))
    .map(orderSentence);
}

function orderSentence(o) {
  const said = o.said ? ` “${o.said}”` : '';
  if (o.moving) return `“${o.asked}” is under way${o.holder ? `, with ${o.holder}` : ''}.${said}`;
  const phrase = STATUS_SENTENCE[o.status];
  return phrase ? `“${o.asked}” ${phrase}.${said}` : `“${o.asked}”: ${o.status}.${said}`;
}

/**
 * Figures whose latest reading differs from the one before (first source's `history`), as
 * "<label>: <before> to <after> <unit>", numbers in en-US digits, the unit dropped when none.
 */
export function changedFigures(situation) {
  const out = [];
  for (const f of situation?.figures ?? []) {
    const history = f.sources?.[0]?.history ?? [];
    const readings = history.map((r) => r.value).filter((v) => Number.isFinite(v));
    const latest = history.at(-1)?.value;
    if (!Number.isFinite(latest) || readings.length < 2) continue;
    const before = readings.at(-2);
    if (before === latest) continue;
    const unit = f.unit ? ` ${f.unit}` : '';
    out.push(`${f.label}: ${before.toLocaleString('en-US')} to ${latest.toLocaleString('en-US')}${unit}`);
  }
  return out;
}

/** The last wake shown, kept under `rv.happened.<campaignId>`: `{ read(), write(n) }`; `read()` is 0 when missing, broken, with no storage or with storage that throws; `write` never throws. */
export function happenedStore(storage, campaignId) {
  const key = `${HAPPENED_PREFIX}${campaignId}`;
  return {
    read() {
      try {
        const n = Number(storage?.getItem(key));
        return Number.isInteger(n) && n > 0 ? n : 0;
      } catch {
        return 0;
      }
    },
    write(n) {
      try {
        storage?.setItem(key, String(n));
      } catch {
        // A blocked store only means the sheet may open again next time.
      }
    },
  };
}

/** True for a wake page whose number is above 0 and above the one stored. */
export function shouldShow(wake, store) {
  return wake?.number > 0 && wake.number > store.read();
}

/**
 * A `<dialog class="rl-hap">` headed "What happened": the aide's briefing (`briefingLines`, which
 * holds the figures that moved), "It is <date>. <n> days have passed.", the lines the briefing
 * did not tell, "<n> new papers in your tray", where forces moved during the run (`moves` over
 * `places`, realism-moves.js), and "To the desk", which calls `onClose()`; the room then stores
 * the wake number.
 */
export function happenedSheet({ record, situation, agenda, date, moves, places, onClose }) {
  const days = record?.wake?.days_passed;
  const daysLine = days === 1 ? '1 day has passed.' : days > 0 ? `${days} days have passed.` : null;
  const when = [date && `It is ${date}.`, daysLine].filter(Boolean).join(' ');
  const papers = record?.wake?.papers;
  const paperLine = papers === 1 ? '1 new paper in your tray' : papers > 0 ? `${papers} new papers in your tray` : null;
  // an order the aide's briefing tells is not told again in the list under it
  const told = new Set(slowOrders(record).map((o) => o.id));
  const lines = happenedLines({ ...record, orders: (record?.orders ?? []).filter((o) => !told.has(o.id)) });

  return h('dialog', { class: 'rl-hap', 'aria-labelledby': 'rl-hap-title' },
    h('h2', { id: 'rl-hap-title' }, 'What happened'),
    aideBriefing({ lines: briefingLines({ record, situation, agenda }) }),
    when ? h('p', { class: 'rl-hap-when' }, when) : null,
    lines.length ? h('ul', { class: 'rl-hap-lines' }, lines.map((l) => h('li', {}, l))) : null,
    paperLine ? h('p', { class: 'rl-hap-papers' }, paperLine) : null,
    movesBlock({ moves, places }),
    h('div', { class: 'rl-hap-actions' },
      h('button', { type: 'button', onclick: () => onClose() }, 'To the desk')));
}

export const MISSED_TITLE = 'What you missed';

/** The pages of a `catchup` reply, oldest wake first; a reply that is not a list of pages gives none. */
export function missedPages(reply) {
  const pages = Array.isArray(reply?.pages) ? reply.pages : [];
  return pages.filter((p) => Number.isInteger(p?.number)).sort((a, b) => a.number - b.number);
}

/**
 * The owner's note for a wake the aide played, from the page's `aide_filed` (the server sends the
 * key to the owner only): "Your aide played wake N for you: <orders>.", or "... and filed nothing."
 * when it filed none; null on a page with no such key.
 */
export function aideNote(page) {
  const filed = page?.aide_filed;
  if (!Array.isArray(filed)) return null;
  return filed.length
    ? `Your aide played wake ${page.number} for you: ${filed.join('; ')}.`
    : `Your aide played wake ${page.number} for you and filed nothing.`;
}

/** One sentence for each order the page settled that the record holds (an id it does not hold is left out). */
export function missedLines(page, record) {
  const settled = page?.settled ?? [];
  return (record?.orders ?? []).filter((o) => settled.includes(o.id)).map(orderSentence);
}

function missedPage(page, record) {
  const days = page.days_passed;
  const daysLine = days === 1 ? '1 day has passed.' : days > 0 ? `${days} days have passed.` : null;
  const lines = missedLines(page, record);
  const dropped = Array.isArray(page.held_dropped) ? page.held_dropped : [];
  const papers = page.papers;
  const paperLine = papers === 1 ? '1 new paper reached your tray.' : papers > 0 ? `${papers} new papers reached your tray.` : null;
  const note = aideNote(page);
  const told = daysLine || lines.length || dropped.length || paperLine || note;
  return h('section', { class: 'rl-missed-page', 'aria-labelledby': `rl-missed-w${page.number}` },
    h('h3', { id: `rl-missed-w${page.number}` }, page.opened ? `Wake ${page.number}: ${page.opened}` : `Wake ${page.number}`),
    note ? h('p', { class: 'rl-missed-aide' }, note) : null,
    daysLine ? h('p', {}, daysLine) : null,
    lines.length ? h('ul', { class: 'rl-hap-lines' }, lines.map((l) => h('li', {}, l))) : null,
    dropped.length ? h('ul', { class: 'rl-missed-dropped' }, dropped.map((l) => h('li', {}, l))) : null,
    paperLine ? h('p', { class: 'rl-hap-papers' }, paperLine) : null,
    told ? null : h('p', {}, 'Nothing reached you in this wake.'));
}

/**
 * A `<dialog class="rl-hap rl-missed">` headed "What you missed": one section for each page of the
 * `catchup` reply (`missedPages`), oldest first, and "To the desk", which calls `onClose()`. `record`
 * is the room's record, whose orders the settled ids name. No animation, no storage.
 */
export function missedSheet({ pages, record, onClose }) {
  return h('dialog', { class: 'rl-hap rl-missed', 'aria-labelledby': 'rl-missed-title' },
    h('h2', { id: 'rl-missed-title' }, MISSED_TITLE),
    pages.map((p) => missedPage(p, record)),
    h('div', { class: 'rl-hap-actions' },
      h('button', { type: 'button', onclick: () => onClose() }, 'To the desk')));
}
