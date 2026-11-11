// The two dossiers behind the header (Train 2 unit D): the character the seat plays, and
// the setting. Text from the desk and from the world's sidecar (realism_api.py Dossier, Setting).

import { h } from '../dom.js';
import { horizonWords, powersSentence } from '../realism-rules.js';

const QUOTE = 'In their words';

/** The initials of the first and last word: "Franklin D. Roosevelt" gives "FR". */
export function monogram(name) {
  const words = String(name ?? '').trim().split(/\s+/).filter(Boolean);
  if (!words.length) return '';
  const first = Array.from(words[0])[0];
  const last = words.length > 1 ? Array.from(words[words.length - 1])[0] : '';
  return `${first}${last}`.toUpperCase();
}

/**
 * The character's sections, in this order and only those with content: Office, Answers to
 * (the principals joined by ", "), As history had it, Biography, Powers (`powersSentence`),
 * Limits, Personal, Aims, How far ahead you see (`horizonWords`), In their words, A fact.
 * Each `{ heading, lines }`; In their words is “<quote>” then "— <source>", and is left out
 * when the quote has no source.
 */
export function dossierSections(desk, dossier) {
  const d = dossier ?? {};
  const text = (xs) => (Array.isArray(xs) ? xs.filter((x) => typeof x === 'string' && x.trim()) : []);
  const days = desk.horizon_days;
  const quote = d.quote && d.source ? [`“${d.quote}”`, `— ${d.source}`] : [];
  const sections = [
    ['Office', desk.office ? [desk.office] : []],
    ['Answers to', text(desk.principals).length ? [text(desk.principals).join(', ')] : []],
    ['As history had it', text(d.history)],
    ['Biography', d.bio ? [d.bio] : []],
    ['Powers', text(desk.powers).length ? [powersSentence(text(desk.powers))] : []],
    ['Limits', text(desk.constraints)],
    ['Personal', text(desk.personal)],
    ['Aims', text(desk.aims)],
    ['How far ahead you see', Number.isInteger(days) && days > 0 ? [horizonWords(days)] : []],
    [QUOTE, quote],
    ['A fact', d.fact ? [d.fact] : []],
  ];
  return sections.filter(([, lines]) => lines.length).map(([heading, lines]) => ({ heading, lines }));
}

/** The setting's sections, only those with content: The date, The situation, The sides, On history's clock ("<on>: <what>"). */
export function settingSections(setting, date) {
  const s = setting ?? {};
  const sides = Array.isArray(s.sides) ? s.sides.filter((x) => typeof x === 'string' && x.trim()) : [];
  const dates = Array.isArray(s.dates)
    ? s.dates.map((d) => (d.on && d.what ? `${d.on}: ${d.what}` : d.what || d.on || '')).filter(Boolean)
    : [];
  const sections = [
    ['The date', date ? [date] : []],
    ['The situation', s.situation ? [s.situation] : []],
    ['The sides', sides],
    ["On history's clock", dates],
  ];
  return sections.filter(([, lines]) => lines.length).map(([heading, lines]) => ({ heading, lines }));
}

function sectionNodes(prefix, sections) {
  return sections.map(({ heading, lines }, i) => h('section', { class: 'rl-dos-sec', 'aria-labelledby': `${prefix}-${i}` },
    h('h3', { id: `${prefix}-${i}`, class: 'rl-dos-h' }, heading),
    heading === QUOTE
      ? lines.map((line, j) => h('p', { class: j ? 'rl-dos-source' : 'rl-dos-quote' }, line))
      : lines.length > 1
        ? h('ul', { class: 'rl-dos-list' }, lines.map((line) => h('li', {}, line)))
        : h('p', {}, lines[0])));
}

function dossierDialog({ id, name, portrait, sections, onClose }) {
  const titleId = `${id}-title`;
  const close = () => onClose?.();
  const dialog = h('dialog', { class: 'rl-dos', 'aria-labelledby': titleId, onclose: close },
    h('header', { class: 'rl-dos-head' },
      portrait,
      h('h2', { id: titleId, class: 'rl-dos-name' }, name)),
    sectionNodes(`${id}-sec`, sections),
    h('div', { class: 'rl-dos-foot' },
      h('button', { type: 'button', class: 'ghost', onclick: close }, 'Close')));
  return dialog;
}

const PORTRAIT_FILE = /^[a-z0-9][a-z0-9-]*\.(jpg|png|webp)$/;

/** `/assets/portraits/<file>` for a bare lowercase image file name (the sidecar's rule); else null. */
export function portraitSrc(file) {
  return typeof file === 'string' && PORTRAIT_FILE.test(file) ? `/assets/portraits/${file}` : null;
}

/**
 * The portrait for `name`, shared by every screen that shows one: a `figure` holding
 * `span.portrait-frame > img.portrait` (alt the name) and the credit as a caption, or, with no
 * usable portrait, `span.portrait-mono` with the monogram (aria-hidden). `prefix` adds the
 * screen's own classes: `<prefix>-figure`, `<prefix>-portrait`, `<prefix>-credit`, `<prefix>-mono`.
 */
export function portraitNode(name, dossier, prefix) {
  const src = portraitSrc(dossier?.portrait);
  if (!src) return h('span', { class: `portrait-mono ${prefix}-mono`, 'aria-hidden': 'true' }, monogram(name));
  return h('figure', { class: `portrait-figure ${prefix}-figure` },
    h('span', { class: 'portrait-frame' }, h('img', { class: `portrait ${prefix}-portrait`, src, alt: name })),
    dossier.credit ? h('figcaption', { class: `portrait-credit ${prefix}-credit` }, dossier.credit) : null);
}

/**
 * A `<dialog class="rl-dos">` headed with `name`: the portrait (`/assets/portraits/<file>`,
 * alt the name) or the monogram, the sections, the credit line under a portrait, and Close.
 */
export function characterDossier({ name, desk, dossier, onClose }) {
  const portrait = portraitNode(name, dossier, 'rl-dos');
  return dossierDialog({
    id: 'rl-dos-character', name, portrait, sections: dossierSections(desk, dossier), onClose,
  });
}

/** A `<dialog class="rl-dos">` headed with the game's `name`: the setting's sections and Close. */
export function settingDossier({ name, setting, date, onClose }) {
  return dossierDialog({
    id: 'rl-dos-setting', name, portrait: null, sections: settingSections(setting, date), onClose,
  });
}
