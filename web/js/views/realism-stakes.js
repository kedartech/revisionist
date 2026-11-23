// The stakes strip: what is being fought over and how long is left. One tile per contest the
// seat's view holds, then one per open mandate of the seat's own. A tile shows the name and
// the days left, and the lean only when the data carries one (the server sends a lean only
// once a contest's track has moved in this game). Above the tiles: one line per aim of the
// seat's own with its status chip, a tap opening the aim's drill-down, then the degree of the
// win, the drift and the days to the season's end exactly as the data sends them; the client
// counts nothing. While the seat may still write its own aim, its replaceable aim carries a
// "Write your own" control: the ladder of patterns the server sent, each blank a picker of the
// values the server sent for it, the check's answer shown before anything is stored.
// Nothing here touches the page on import.

import { api } from '../api.js';
import { h } from '../dom.js';
import { worldDate } from '../rules.js';

const STEPS = 10;

/** `daysLeft(n)`: "Due now" at zero, "1 day left", "n days left". */
export function daysLeft(n) {
  if (!(n > 0)) return 'Due now';
  return n === 1 ? '1 day left' : `${n} days left`;
}

/** Ten steps, as many on as `lean.step`, counted toward the contest's first side. */
function leanBlock(sides, lean) {
  const cells = [];
  for (let i = 0; i < STEPS; i += 1) cells.push(h('span', { class: i < lean.step ? 'on' : null }));
  return h('span', { class: 'rl-stake-lean' },
    h('span', { class: 'rl-stake-bar', role: 'img', 'aria-label': `${lean.step} of ${STEPS} steps toward ${sides[0] ?? 'the first side'}` }, cells),
    h('span', { class: 'rl-stake-side' }, lean.favours ? `Leaning to ${lean.favours}` : 'No side ahead'));
}

function contestTile(c) {
  return h('li', { class: 'rl-stake', 'data-kind': 'contest', title: c.prize || null },
    h('span', { class: 'rl-stake-name' }, c.name),
    h('span', { class: 'rl-stake-days' }, daysLeft(c.days_left)),
    c.lean ? leanBlock(c.sides ?? [], c.lean) : null);
}

function decidedTile(c) {
  return h('li', { class: 'rl-stake', 'data-kind': 'decided', title: c.prize || null },
    h('span', { class: 'rl-stake-name' }, c.name),
    h('span', { class: 'rl-stake-winner' }, c.winner ? `Won by ${c.winner}` : 'Decided'));
}

function mandateTile(m) {
  return h('li', { class: 'rl-stake', 'data-kind': 'mandate' },
    h('span', { class: 'rl-stake-kind' }, 'Your mandate'),
    h('span', { class: 'rl-stake-name' }, m.text),
    h('span', { class: 'rl-stake-days' }, daysLeft(m.days_left)));
}

const STATUS_WORD = { met: 'Met', at_risk: 'At risk', failed: 'Failed' };
const openAims = new Set();

/** Open aim `aim`'s drill-down, as a press on its line would: a mark on the bar opens its aim this way. */
export function openAim(aim) {
  openAims.add(String(aim.aim ?? aim.text));
}

function periodLine(aim) {
  if (aim.opens && aim.deadline) return `${worldDate(aim.opens)} to ${worldDate(aim.deadline)}`;
  if (aim.deadline) return `By ${worldDate(aim.deadline)}`;
  if (aim.opens) return `From ${worldDate(aim.opens)}`;
  return null;
}

function leafLine(leaf) {
  const unseen = leaf.seen === 'uncertain';
  return h('li', { class: 'rl-aim-leaf', 'data-holds': unseen ? null : String(Boolean(leaf.holds)) },
    h('span', { class: 'rl-aim-reads' }, leaf.reads),
    unseen ? h('span', { class: 'rl-aim-uncertain' }, 'Uncertain: hidden from you') : null,
    ...(unseen ? [] : (leaf.evidence ?? []).map((e) => h('span', { class: 'rl-aim-evidence' }, e))));
}

export const OWN_WORDS = Object.freeze({
  open: 'Write your own', // [proposed] wording for this block
  close: 'Close',
  ladder: 'Patterns, easiest first',
  back: 'Back to the patterns',
  pick: 'Choose\u2026',
  blank: '\u2026',
  government: 'Your government would issue it',
  difficulty: (n) => (Number.isFinite(n) ? `Difficulty ${n}` : 'No fill stands now'),
  set: 'Set as my aim',
  checking: 'Checking\u2026',
  own: 'Your own',
  replaces: (text) => `It replaces: ${text}`,
});

const OWN = { open: false, key: null, picks: {}, check: null, seq: 0 };

export function resetOwn() {
  OWN.open = false;
  OWN.key = null;
  OWN.picks = {};
  OWN.check = null;
  OWN.seq += 1;
}

/** The ladder block's sentence with each blank shown as `fill(name)` (a placeholder with none picked). */
function sentenceOf(pattern, fill) {
  return String(pattern.sentence ?? '').replace(/\{(\w+)\}/g, (_, name) => fill(name) ?? OWN_WORDS.blank);
}

function reasonsList(check) {
  const reasons = check?.aim?.reasons ?? [];
  return reasons.length ? h('ul', { class: 'rl-own-reasons' }, reasons.map((r) => h('li', {}, r))) : null;
}

function ownFill(pattern, box, draw, onSet) {
  const blanks = pattern.blanks ?? [];
  const preview = h('p', { class: 'rl-own-sentence' });
  const status = h('div', { class: 'rl-own-status', role: 'status', 'aria-live': 'polite' });
  const setBtn = h('button', { type: 'button', class: 'rl-own-set', disabled: true }, OWN_WORDS.set);
  const labelOf = (name) => {
    const b = blanks.find((x) => x.name === name);
    const v = b?.values?.[OWN.picks[name]];
    return v ? v.label : null;
  };
  const paint = () => {
    preview.textContent = sentenceOf(pattern, labelOf);
    const c = OWN.check;
    status.replaceChildren(...(c === 'pending' ? [h('p', {}, OWN_WORDS.checking)] : c ? [
      h('p', { class: 'rl-own-reply', 'data-stands': String(Boolean(c.aim?.stands)) }, c.reply),
      reasonsList(c),
    ].filter(Boolean) : []));
    setBtn.disabled = !(c && c !== 'pending' && c.aim?.stands);
  };
  const check = async () => {
    if (!blanks.every((b) => OWN.picks[b.name] !== undefined)) { OWN.check = null; paint(); return; }
    const seq = (OWN.seq += 1);
    OWN.check = 'pending';
    paint();
    const values = Object.fromEntries(blanks.map((b) => [b.name, b.values[OWN.picks[b.name]].value]));
    let r;
    try {
      r = await api.realism('aim-check', { key: pattern.key, values });
    } catch (ex) {
      r = { reply: ex.message, refused: true, aim: { stands: false, text: null, reasons: [] } };
    }
    if (seq !== OWN.seq) return;
    OWN.check = r;
    paint();
  };
  setBtn.addEventListener('click', async () => {
    const values = Object.fromEntries(blanks.map((b) => [b.name, b.values[OWN.picks[b.name]].value]));
    setBtn.disabled = true;
    let r;
    try {
      r = await api.realism('aim-set', { key: pattern.key, values });
    } catch (ex) {
      r = { reply: ex.message, refused: true, aim: { stands: false, text: null, reasons: [] } };
    }
    if (r.aim?.stands && !r.refused) {
      resetOwn();
      onSet?.(r);
      return;
    }
    OWN.check = r;
    paint();
  });
  const pickers = blanks.map((b) => {
    const sel = h('select', { class: 'rl-own-pick', 'aria-label': b.name.replace(/_/g, ' ') },
      h('option', { value: '' }, OWN_WORDS.pick),
      (b.values ?? []).map((v, i) => h('option', { value: String(i) }, v.label)));
    sel.addEventListener('change', () => {
      if (sel.value === '') delete OWN.picks[b.name]; else OWN.picks[b.name] = Number(sel.value);
      check();
    });
    if (OWN.picks[b.name] !== undefined) sel.value = String(OWN.picks[b.name]);
    return h('label', { class: 'rl-own-blank' }, h('span', {}, b.name.replace(/_/g, ' ')), sel);
  });
  const back = h('button', { type: 'button', class: 'ghost rl-own-back', onclick: () => { resetOwn(); OWN.open = true; draw(); } }, OWN_WORDS.back);
  box.replaceChildren(preview, h('div', { class: 'rl-own-blanks' }, pickers), status, h('div', { class: 'rl-own-actions' }, setBtn, back));
  paint();
}

function ownPanel(ownAim, onSet) {
  const box = h('div', { class: 'rl-own', role: 'group', 'aria-label': OWN_WORDS.open });
  const draw = () => {
    const pattern = (ownAim.patterns ?? []).find((p) => p.key === OWN.key);
    if (pattern) { ownFill(pattern, box, draw, onSet); return; }
    box.replaceChildren(
      h('p', { class: 'rl-own-replaces' }, OWN_WORDS.replaces(ownAim.replaces)),
      h('h4', { class: 'rl-own-h' }, OWN_WORDS.ladder),
      h('ol', { class: 'rl-own-ladder' }, (ownAim.patterns ?? []).map((p) => h('li', {},
        h('button', { type: 'button', class: 'rl-own-pattern', onclick: () => { OWN.key = p.key; OWN.picks = {}; OWN.check = null; draw(); } },
          h('span', { class: 'rl-own-text' }, sentenceOf(p, () => null)),
          h('span', { class: 'rl-own-diff' }, OWN_WORDS.difficulty(p.difficulty)),
          p.government ? h('span', { class: 'rl-own-gov' }, OWN_WORDS.government) : null)))));
  };
  draw();
  return box;
}

/** The own aim's mark on a line the seat wrote itself. */
function ownMark(aim) {
  return aim.source === 'player' ? h('span', { class: 'rl-aim-own' }, OWN_WORDS.own) : null;
}

/** The aim the seat wrote itself, or null: the first-wake card names it. */
export function ownAimOf(stakes) {
  return (stakes?.aims ?? []).find((a) => a.source === 'player') ?? null;
}

function ownControl(aim, own) {
  if (!own?.ownAim || own.ownAim.aim !== aim.aim) return null;
  const holder = h('div', { class: 'rl-own-holder' });
  const sync = () => {
    holder.replaceChildren(h('button', {
      type: 'button', class: 'ghost rl-own-open', 'aria-expanded': String(OWN.open),
      onclick: () => { OWN.open = !OWN.open; sync(); },
    }, OWN.open ? OWN_WORDS.close : OWN_WORDS.open), ...(OWN.open ? [ownPanel(own.ownAim, own.onSet)] : []));
  };
  sync();
  return holder;
}

function aimRow(aim, own) {
  const id = String(aim.aim ?? aim.text);
  const period = periodLine(aim);
  const more = h('div', { class: 'rl-aim-more', id: `rl-aim-more-${id}`, hidden: openAims.has(id) ? null : true },
    aim.rule ? h('p', { class: 'rl-aim-rule' }, aim.rule) : null,
    period ? h('p', { class: 'rl-aim-period' }, period) : null,
    (aim.leaves ?? []).length ? h('ul', { class: 'rl-aim-leaves' }, aim.leaves.map(leafLine)) : null,
    aim.reason ? h('p', { class: 'rl-aim-reason' }, aim.reason) : null);
  const toggle = h('button', {
    type: 'button', class: 'rl-aim-toggle', 'aria-expanded': String(openAims.has(id)), 'aria-controls': more.getAttribute('id'),
    onclick: () => {
      const on = !openAims.has(id);
      if (on) openAims.add(id); else openAims.delete(id);
      toggle.setAttribute('aria-expanded', String(on));
      if (on) more.removeAttribute('hidden'); else more.setAttribute('hidden', '');
    },
  },
  h('span', { class: 'rl-aim-chip' }, STATUS_WORD[aim.status] ?? String(aim.status ?? '')),
  h('span', { class: 'rl-aim-text' }, aim.text),
  ownMark(aim));
  return h('li', { class: 'rl-aim', 'data-status': aim.status, 'data-source': aim.source ?? null }, toggle, more, ownControl(aim, own));
}

/** `aimList(aims)`: one line per aim, each with its status chip and a drill-down; null with none. */
export function aimList(aims, extra = '', own = null) {
  const list = Array.isArray(aims) ? aims : [];
  if (!own?.ownAim) resetOwn();
  return list.length ? h('ul', { class: `rl-aims${extra ? ` ${extra}` : ''}` }, list.map((a) => aimRow(a, own))) : null;
}

function scoreLine(stakes) {
  const items = [];
  if (stakes.degree) items.push(h('span', { class: 'rl-score-item rl-score-degree' }, `Degree of the win: ${stakes.degree}`));
  if (Number.isFinite(stakes.drift)) items.push(h('span', { class: 'rl-score-item rl-score-drift' }, `Drift from history: ${stakes.drift}`));
  if (Number.isFinite(stakes.season_days_left)) {
    const n = stakes.season_days_left;
    items.push(h('span', { class: 'rl-score-item rl-score-end' }, n > 0 ? `Season ends in ${n === 1 ? '1 day' : `${n} days`}` : 'Season ends today'));
  }
  return items.length ? h('p', { class: 'rl-score' }, items) : null;
}

/**
 * `stakesStrip(stakes, { aims })`: the strip for `view.realism.stakes`, or null when it holds
 * nothing to show. The aim lines come first (`aims: false` leaves them out where the Board's
 * pin draws them), then the score line, then the contests in the data's order (soonest first),
 * the seat's mandates and the decided contests.
 */
export function stakesStrip(stakes, { aims = true, ownAim = null, onAimSet = null } = {}) {
  const contests = stakes?.contests ?? [];
  const mandates = stakes?.mandates ?? [];
  const decided = stakes?.decided ?? [];
  const lines = aims ? aimList(stakes?.aims, '', { ownAim, onSet: onAimSet }) : null;
  const score = stakes ? scoreLine(stakes) : null;
  const tiles = [...contests.map(contestTile), ...mandates.map(mandateTile), ...decided.map(decidedTile)];
  if (!lines && !score && !tiles.length) return null;
  return h('div', { class: 'rl-stakes', role: 'region', 'aria-label': 'What is at stake' },
    lines, score, tiles.length ? h('ul', { class: 'rl-stakes-list' }, tiles) : null);
}
