// "What happened" (Train 2 unit W): the sheet that opens once when a new wake opens.

import { h } from '../dom.js';

export const HAPPENED_PREFIX = 'rv.happened.';

/**
 * One line per order that is moving or settled since the last wake (`record.wake.settled`):
 * moving "<asked>: under way, with <holder>" (", with" dropped with no holder); settled
 * "<asked>: <status>", then " — “<said>”" when the order has an answer.
 */
export function happenedLines(record) {
  const settled = record?.wake?.settled ?? [];
  return (record?.orders ?? [])
    .filter((o) => o.moving || settled.includes(o.id))
    .map((o) => {
      if (o.moving) return `${o.asked}: under way${o.holder ? `, with ${o.holder}` : ''}`;
      return `${o.asked}: ${o.status}${o.said ? ` — “${o.said}”` : ''}`;
    });
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
 * A `<dialog class="rl-hap">` headed "What happened": "It is <date>. <n> days have passed.",
 * the lines, "<n> new papers in your tray", the changed figures, and "To the desk", which
 * calls `onClose()`; the room then stores the wake number.
 */
export function happenedSheet({ record, situation, date, onClose }) {
  const days = record?.wake?.days_passed;
  const daysLine = days === 1 ? '1 day has passed.' : days > 0 ? `${days} days have passed.` : null;
  const when = [date && `It is ${date}.`, daysLine].filter(Boolean).join(' ');
  const papers = record?.wake?.papers;
  const paperLine = papers === 1 ? '1 new paper in your tray' : papers > 0 ? `${papers} new papers in your tray` : null;
  const lines = happenedLines(record);
  const figures = changedFigures(situation);

  return h('dialog', { class: 'rl-hap', 'aria-labelledby': 'rl-hap-title' },
    h('h2', { id: 'rl-hap-title' }, 'What happened'),
    when ? h('p', { class: 'rl-hap-when' }, when) : null,
    lines.length ? h('ul', { class: 'rl-hap-lines' }, lines.map((l) => h('li', {}, l))) : null,
    paperLine ? h('p', { class: 'rl-hap-papers' }, paperLine) : null,
    figures.length ? h('h3', {}, 'Figures that moved') : null,
    figures.length ? h('ul', { class: 'rl-hap-figures' }, figures.map((l) => h('li', {}, l))) : null,
    h('div', { class: 'rl-hap-actions' },
      h('button', { type: 'button', onclick: () => onClose() }, 'To the desk')));
}
