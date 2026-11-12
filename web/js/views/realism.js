// Realism views: the in-tray, a document page, the directive form, the situation board, the
// aide's brief, the pace header and the standard forms. Each takes the
// realism_api JSON and returns a node.

import { h, icon } from '../dom.js';
import {
  TRAY_FILTERS, addressLine, channelWord, directiveChannel, classificationWord, figureValue, filterInTray, linesHeading, paceLine,
  reportLine, runLine, sheetLines, sortInTray, trayCounts, trendLine,
} from '../realism-rules.js';
import { worldDate } from '../rules.js';

/** The classification stamp: the word, always. */
function stamp(c) {
  return h('span', { class: `stamp stamp-${c}` }, classificationWord(c).toUpperCase());
}

function list(items, cls) {
  return h('ul', { class: cls }, items.map((t) => h('li', {}, t)));
}

/** One folder in the tray: a tab with the author, a cover with the title, and a routing slip. */
function folder(d, onOpen) {
  const state = d.unread ? 'unread' : 'read';
  return h('li', { class: `rl-folder ${state}${d.flagged ? ' flagged' : ''}` },
    h('span', { class: 'rl-folder-tab' }, d.author),
    h('button', { type: 'button', class: 'rl-cover', onclick: () => onOpen?.(d) },
      d.unread ? h('span', { class: 'rl-ribbon' }, 'Unread') : null,
      d.flagged ? h('span', { class: 'rl-flagmark' }, h('span', { class: 'rl-clip', 'aria-hidden': 'true' }), 'Flagged') : null,
      h('span', { class: 'rl-doc-title' }, d.title),
      stamp(d.classification),
      h('dl', { class: 'rl-slip' },
        h('dt', {}, 'From'), h('dd', {}, d.author),
        h('dt', {}, 'Via'), h('dd', {}, channelWord(d.channel)),
        h('dt', {}, 'Arrived'), h('dd', {}, worldDate(d.arrives)))));
}

/** The folder grid under a filter bar. `opts` is { filter, sort, onFilter, onSort }. */
export function inTray(listing, onOpen, opts = {}) {
  const { filter = 'all', sort = 'newest', onFilter, onSort } = opts;
  const counts = trayCounts(listing.documents);
  const items = sortInTray(filterInTray(listing.documents, filter), sort);
  const tabs = TRAY_FILTERS.map(([key, word]) => h('button', {
    type: 'button', role: 'tab', id: `rl-filter-${key}`, 'aria-selected': String(filter === key),
    'aria-controls': 'rl-folders', tabindex: filter === key ? 0 : -1, class: 'rl-filter',
    onclick: () => onFilter?.(key),
    onkeydown: (e) => {
      const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (!step) return;
      e.preventDefault();
      const last = TRAY_FILTERS.length - 1;
      let to = TRAY_FILTERS.findIndex(([k]) => k === key) + step;
      if (to < 0) to = last;
      if (to > last) to = 0;
      onFilter?.(TRAY_FILTERS[to][0], true);
    },
  }, word, h('span', { class: 'rl-count' }, ` ${counts[key]}`)));
  return h('section', { class: 'rl-tray', 'aria-labelledby': 'rl-tray-h' },
    h('h2', { id: 'rl-tray-h' }, 'In-tray'),
    h('div', { class: 'rl-bar' },
      h('div', { role: 'tablist', 'aria-label': 'Show papers', class: 'rl-filters' }, tabs),
      h('label', { class: 'rl-sort' }, 'Sort ',
        h('select', { name: 'sort', onchange: (e) => onSort?.(e.target.value) },
          h('option', { value: 'newest', selected: sort === 'newest' }, 'Newest first'),
          h('option', { value: 'oldest', selected: sort === 'oldest' }, 'Oldest first')))),
    h('div', { role: 'tabpanel', id: 'rl-folders', 'aria-labelledby': `rl-filter-${filter}` },
      items.length
        ? h('ul', { class: 'rl-folders', role: 'list' }, items.map((d) => folder(d, onOpen)))
        : h('p', { class: 'rl-none' }, 'Nothing in this tray.')));
}

/**
 * The page's figures; a line with no figure is left off rather than marked as missing.
 * Without a letter the lines are the whole paper, shown as a plain summary sheet.
 */
function figures(lines, written) {
  const shown = sheetLines(lines);
  if (!shown.length) return null;
  return h('section', { class: written ? 'rl-figures' : 'rl-figures rl-sheet' },
    h('h3', {}, written ? linesHeading(shown) : 'Summary sheet'),
    written ? null : h('p', { class: 'rl-sheet-note' }, 'No covering letter came with this paper.'),
    h('dl', { class: 'rl-body' }, shown.map((b) => [
      h('dt', {}, b.label),
      h('dd', {}, `${b.value}${b.unit ? ` ${b.unit}` : ''}`),
    ])));
}

export function documentPage(page) {
  const { item } = page;
  const paragraphs = page.prose ? page.prose.split(/\n{2,}/).filter((p) => p.trim()) : [];
  return h('article', { class: item.kind === 'press' ? 'rl-page rl-page-press' : 'rl-page', 'aria-labelledby': 'rl-page-h' },
    h('div', { class: 'rl-page-top' }, stamp(item.classification),
      h('span', { class: 'rl-page-via' }, `via ${channelWord(item.channel)}`)),
    h('h2', { id: 'rl-page-h' }, item.title),
    h('p', { class: 'rl-page-from' }, `From ${item.author}, issued ${worldDate(item.issued)}, arrived ${worldDate(item.arrives)}`),
    paragraphs.length ? h('div', { class: 'rl-prose' }, paragraphs.map((p) => h('p', {}, p))) : null,
    figures(page.body, paragraphs.length > 0));
}

/** An opened folder: the paper on the folder's inside, with Close folder and Flag/Unflag. */
export function dossier(page, { onClose, onFlag }) {
  const flagged = page.item.flagged;
  return h('section', { class: 'rl-dossier', 'aria-label': 'Open folder' },
    h('div', { class: 'rl-dossier-bar' },
      h('button', { type: 'button', class: 'rl-btn', onclick: () => onClose?.() }, 'Close folder'),
      h('button', {
        type: 'button', class: 'rl-btn', 'aria-pressed': String(flagged), onclick: () => onFlag?.(!flagged),
      }, flagged ? 'Unflag' : 'Flag')),
    documentPage(page));
}

/** A person's name with their title beneath, in a lighter hand. */
export function personName(c) {
  return h('span', { class: 'rl-person' },
    h('span', { class: 'rl-person-name' }, c.person),
    c.title ? h('span', { class: 'rl-person-title' }, c.title) : null);
}

/** The recipients as a list of radio cards: name, and title beneath. */
function recipients(contacts, start, name, onPick) {
  return h('fieldset', { class: 'rl-recipients' },
    h('legend', {}, 'To'),
    contacts.map((c, i) => {
      const rid = `${name}-${i}`;
      return h('label', { class: 'rl-recipient', for: rid },
        h('input', {
          type: 'radio', id: rid, name, value: c.person, required: true, checked: c === start,
          onchange: () => onPick(c),
        }),
        personName(c));
    }));
}

let directiveSeq = 0;

/**
 * Write a directive: to whom, how, and the words. `draft` is { to, channel, text } to
 * start from (kept across Revise); `onAsk` gets the same shape.
 */
export function directiveForm(contacts, draft, onAsk) {
  const id = `rl-dir-${directiveSeq++}`;
  const start = contacts.find((c) => c.person === draft?.to) ?? contacts[0];
  const how = h('select', { id: `${id}-how`, name: 'channel', required: true });
  const fill = (contact, chosen) => how.replaceChildren(...contact.channels.map((ch) => h('option', {
    value: ch, selected: ch === chosen,
  }, directiveChannel(ch))));
  const picker = recipients(contacts, start, `${id}-to`, (c) => fill(c, null));
  const to = { get value() { return picker.querySelector('input:checked')?.value ?? ''; } };
  const words = h('textarea', { id: `${id}-text`, name: 'text', rows: 4, maxlength: 1000, required: true }, draft?.text ?? '');
  if (start) fill(start, draft?.channel);
  const form = h('form', {
    class: 'rl-form rl-directive', 'aria-label': 'Write a directive',
    onsubmit: (e) => { e.preventDefault(); onAsk?.({ to: to.value, channel: how.value, text: words.value }); },
  },
  picker,
  h('div', { class: 'rl-field' }, h('label', { for: `${id}-how` }, 'By'), how),
  h('div', { class: 'rl-field' }, h('label', { for: `${id}-text` }, 'Your instruction'), words),
  h('button', { type: 'submit', class: 'rl-submit' }, 'Prepare the order'));
  return h('section', { class: 'rl-desk-block', 'aria-labelledby': `${id}-h` },
    h('h3', { id: `${id}-h` }, 'Write a directive'),
    contacts.length ? form : h('p', { class: 'rl-none' }, 'No one is within reach.'));
}

/** The order the aide read a directive as, to sign or revise; or why there is none. */
export function proposalCard(p, { onSign, onRevise } = {}) {
  const revise = h('button', { type: 'button', class: 'rl-btn', onclick: () => onRevise?.(p) }, 'Revise');
  return h('section', { class: 'rl-desk-block rl-proposal', 'aria-labelledby': 'rl-proposal-h' },
    h('h3', { id: 'rl-proposal-h' }, p.lever ? 'Ready to sign' : 'This cannot be sent'),
    h('p', { class: 'rl-address' }, addressLine(p)),
    h('blockquote', { class: 'rl-words' }, p.text),
    p.lever
      ? [h('p', {}, 'Your aide reads this as: ', h('strong', {}, p.label)),
        p.terms.length ? list(p.terms, 'rl-terms') : null]
      : h('p', { class: 'rl-reason' }, p.reason),
    h('div', { class: 'rl-actions' },
      p.lever ? h('button', { type: 'button', class: 'rl-submit', onclick: () => onSign?.(p) }, 'Sign and send') : null,
      revise));
}

let draftSeq = 0;

/** One standard form: its label, a Draft toggle, and the lever form under it. */
export function instrument(lever, { onSubmit, entities = [] } = {}) {
  const id = `rl-draft-${draftSeq++}`;
  const panel = h('div', { id, hidden: true }, leverForm(lever, onSubmit, entities));
  const toggle = h('button', {
    type: 'button', class: 'rl-btn', 'aria-expanded': 'false', 'aria-controls': id,
    onclick: () => {
      const open = panel.hidden;
      panel.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
    },
  }, 'Draft');
  return h('li', { class: 'rl-instrument', 'data-lever': lever.name },
    h('div', { class: 'rl-instrument-head' }, h('strong', {}, lever.label), toggle),
    lever.summary ? h('p', { class: 'rl-summary' }, lever.summary) : null,
    panel);
}

/** One source's line on a figure's card: the figure, the trend, who and when. */
function reading(unit, src, onOpen) {
  const given = src.history.filter((r) => r.value !== null);
  return h('li', { class: 'rl-reading' },
    h('p', { class: 'rl-reading-head' },
      h('span', { class: 'rl-figure' }, figureValue(src.value, '')), unit ? h('span', { class: 'rl-unit' }, unit) : null,
      h('span', { class: 'rl-trend' }, trendLine(src))),
    h('p', { class: 'rl-reported' }, reportLine(src)),
    given.length > 1 ? h('p', { class: 'rl-run' }, `Recent reports: ${runLine(given)}`) : null,
    h('button', { type: 'button', class: 'rl-btn', onclick: () => onOpen?.({ id: src.doc_id }) }, 'Open the report'));
}

/** The situation board: an index card per figure, each source on it as it gave the figure. */
export function board(s, { onOpen } = {}) {
  // A source whose latest page gives no figure is left off; a card with none is not drawn.
  const shown = s.figures
    .map((f) => ({ ...f, sources: f.sources.filter((src) => figureValue(src.value, '') !== null) }))
    .filter((f) => f.sources.length);
  return h('section', { class: 'rl-board', 'aria-labelledby': 'rl-board-h' },
    h('h2', { id: 'rl-board-h' }, 'Situation'),
    h('p', { class: 'rl-board-note' }, 'The figures in the papers on your desk, each as its author gave it.'),
    shown.length
      ? h('ul', { class: 'rl-cards', role: 'list' }, shown.map((f) => h('li', { class: `rl-card${f.disagree && f.sources.length > 1 ? ' differ' : ''}` },
        h('h3', {}, f.label),
        f.disagree && f.sources.length > 1 ? h('p', { class: 'rl-differ' }, 'Sources differ') : null,
        h('ul', { class: 'rl-readings', role: 'list' }, f.sources.map((src) => reading(f.unit, src, onOpen))))))
      : h('p', { class: 'rl-none' }, 'No figures have reached your desk.'));
}

/**
 * The aide's brief, or a line while the aide reads (`reading`) or since it could not
 * (`said`). `on` is { brief, useDraft(d) }; brief asks again.
 */
export function briefBlock(brief, on, { reading = false, said = null } = {}) {
  if (reading) {
    return h('p', { class: 'rl-brief-reading', role: 'status' },
      h('span', { class: 'rl-spinner', 'aria-hidden': 'true' }), 'Your aide is reading the new papers…');
  }
  return [
    brief
      ? h('div', { class: 'rl-brief' },
        h('p', {}, brief.summary),
        brief.decisions ? h('p', { class: 'rl-brief-due' }, icon('alert'), ` ${brief.decisions === 1 ? 'One order waits' : `${brief.decisions} orders wait`} on your decision, under Your orders.`) : null,
        brief.drafts.length
          ? [h('h3', {}, 'Your aide suggests'), h('ul', { class: 'rl-drafts', role: 'list' }, brief.drafts.map((d) => h('li', {},
            h('strong', {}, d.label), d.terms.length ? list(d.terms, 'rl-terms') : null,
            h('button', { type: 'button', class: 'rl-btn', onclick: () => on.useDraft?.(d) }, 'Open the form'))))]
          : null)
      : h('p', { class: 'rl-none' }, said ?? 'Your aide reads the papers on your desk after each wake and tells you what matters.'),
    h('button', { type: 'button', class: 'rl-btn', onclick: () => on.brief?.() }, brief ? 'Brief me again' : 'Brief me'),
  ];
}

export function paceHeader(clock) {
  const line = paceLine(clock);
  return h('p', { class: 'rl-pace', title: line }, icon('clock'), ' ', line);
}

let formSeq = 0;

/** A form built from lever params; `entities` are the names offered for entity params. */
export function leverForm(lever, onSubmit, entities = []) {
  const id = `rl-form-${formSeq++}`;
  const fields = lever.params.map((p, i) => {
    const fid = `${id}-${i}`;
    let input;
    if (p.kind === 'int') {
      input = h('input', { id: fid, name: p.name, type: 'number', step: 1, min: p.lo, max: p.hi, required: true });
    } else if (p.kind === 'enum' || p.kind === 'entity') {
      const names = (p.kind === 'enum' ? p.choices : entities.map((n) => ({ value: n, label: n })));
      input = h('select', { id: fid, name: p.name, required: true },
        h('option', { value: '' }, 'Choose…'), names.map((n) => h('option', { value: n.value }, n.label)));
    } else {
      input = h('textarea', { id: fid, name: p.name, rows: 3, required: true });
    }
    const hint = p.kind === 'int' && p.lo !== null && p.hi !== null ? ` (${p.lo} to ${p.hi})` : '';
    return h('div', { class: 'rl-field' }, h('label', { for: fid }, p.label, hint), input);
  });
  const form = h('form', {
    class: 'rl-form',
    'aria-label': lever.label,
    onsubmit: (e) => {
      e.preventDefault();
      const params = {};
      lever.params.forEach((p, i) => {
        const el = form.querySelector(`#${id}-${i}`);
        params[p.name] = p.kind === 'int' ? Number(el.value) : el.value;
      });
      onSubmit?.({ lever: lever.name, params });
    },
  }, fields, h('button', { type: 'submit', class: 'rl-submit' }, 'Sign and send'));
  return form;
}
