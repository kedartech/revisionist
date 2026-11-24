/**
 * The office question on screen: the holder's footing, an open question as a panel drawn by
 * who decides it, the member's own sealed choice, the elections ahead and the public result.
 * Everything here reads the seat's home block as the server sends it (`office`, `footing`,
 * `results`, `elections`); the client works out no rule. A member's choice goes out through
 * the room's `officeVote({ question, remove })`, and what reads back is the server's `choice`.
 */
import { h } from '../dom.js';
import { worldDate } from '../rules.js';

/** Why a question opened, in words [proposed]. */
export const CAUSE_WORDS = Object.freeze({
  base: 'the groups the post rests on turned on its holder',
  incident: 'an incident put it in doubt',
  order: 'an order would take the holder\'s last authority',
  term: 'the holder\'s term ended',
  election: 'an election names the post',
});

/** Who decides, in words, by the way the server sends [proposed]. */
export const WAY_WORDS = Object.freeze({
  vote: 'A vote of the chamber',
  council: 'A council',
  person: 'One person',
  term: 'The end of the term',
  election: 'The election',
});

export const KEEP = 'Keep';
export const REMOVE = 'Remove';
export const NOT_FILED = 'Your choice: not filed';
export const SEALED = 'Sealed until the sitting';

const capital = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const chamberWords = (key) => (key ? `the ${String(key).replace(/[-_]/g, ' ')}` : 'the chamber');

/** The seat's own home block, or null for another nation's. */
const own = (home) => (home?.nation?.relation === 'own' ? home : null);

/** The holder's footing lines, as the server sends them; [] for every other seat. */
export const footingOf = (home) => own(home)?.footing ?? [];

/** The office questions open on the seat's nation, each with its public result once there is one. */
export function officeQuestions(home) {
  const h0 = own(home);
  if (!h0) return [];
  const results = new Map((h0.results ?? []).map((r) => [r.question_id, r]));
  const open = (h0.office ?? []).map((q) => ({ q, result: results.get(q.question_id) ?? null }));
  const seen = new Set(open.map((x) => x.q.question_id));
  // a decided question the server no longer lists as open still shows its result where it stood
  for (const r of h0.results ?? []) if (!seen.has(r.question_id)) open.push({ q: null, result: r });
  return open;
}

/** The elections ahead of the seat's nation, by day as the server sends them. */
export const electionsOf = (home) => own(home)?.elections ?? [];

/** "Support 20, 10 under its line of 30, 15 days under" or "Support 40, 10 over its line of 30". */
export function footingWords(f) {
  const gap = Math.round(Math.abs(f.support - f.line) * 10) / 10;
  if (f.days > 0) return `Support ${f.support}, ${gap} under its line of ${f.line}, ${plural(f.days, 'day')} under`;
  return gap === 0 ? `Support ${f.support}, at its line of ${f.line}` : `Support ${f.support}, ${gap} over its line of ${f.line}`;
}

/** The holder's footing, one line per post he holds; null when he holds none that a question may reach. */
export function footingStrip(home, { onQuestion } = {}) {
  const lines = footingOf(home);
  if (!lines.length) return null;
  return h('section', { class: 'rl-office-footing', 'aria-label': 'Your footing' },
    lines.map((f) => h('p', { class: `rl-office-foot${f.days > 0 ? ' under' : ''}`, 'data-office': f.office },
      h('span', {}, h('strong', {}, f.office), ': ', footingWords(f)), // one flex item: the colon stays by its office
      f.groups?.length ? h('span', { class: 'rl-office-groups' }, ` · rests on ${f.groups.join(', ')}`) : null,
      f.question ? h('button', {
        type: 'button', class: 'rl-btn rl-office-foot-q', 'data-key': `office:${f.question}`,
        onclick: () => onQuestion?.(`office:${f.question}`),
      }, 'A question is open on it') : null)));
}

/** "Kara Lind is kept as General of the Norra Levy on 17 April 1900; she rests until …". */
export function resultWords(r) {
  if (r.removed) return `${r.holder} is removed as ${r.office}, decided ${worldDate(r.on)}.`;
  return `${r.holder} is kept as ${r.office}, decided ${worldDate(r.on)}${r.rests_until ? `; no question may sit on the post before ${worldDate(r.rests_until)}` : ''}.`;
}

/** The public result, in the place the question's panel stood. */
export function resultPanel(r) {
  return h('section', { class: 'rl-office-result', 'aria-label': 'The result', 'data-question': r.question_id },
    h('h4', { class: 'rl-cap-h' }, 'Decided'),
    h('p', {}, resultWords(r)));
}

/** The member's own sealed choice: Keep or Remove, pressed as the server reads it back. */
function choiceControl(q, on) {
  const filed = q.choice === true ? 'remove' : q.choice === false ? 'keep' : null;
  const pick = (remove) => on.officeVote?.({ question: q.question_id, remove });
  return h('div', { class: 'rl-office-choice', role: 'group', 'aria-label': 'Your sealed choice' },
    h('button', { type: 'button', class: 'rl-btn', 'data-key': 'office-keep', 'aria-pressed': String(filed === 'keep'), onclick: () => pick(false) }, KEEP),
    h('button', { type: 'button', class: 'rl-btn', 'data-key': 'office-remove', 'aria-pressed': String(filed === 'remove'), onclick: () => pick(true) }, REMOVE),
    h('p', { class: 'rl-office-mine', 'aria-live': 'polite' },
      filed ? `Your choice: ${filed === 'remove' ? 'remove' : 'keep'}. Sealed; you may change it until the sitting.` : NOT_FILED));
}

/**
 * Who decides: the count of the chamber for a vote, the table of members for a council or one
 * person. Every member's choice reads sealed: the server sends the seat only its own, drawn below.
 */
function deciders(q) {
  if (q.way === 'vote') {
    const c = q.count;
    return h('section', { class: 'rl-office-count', 'aria-label': `The count of ${chamberWords(q.chamber)}` },
      h('h4', { class: 'rl-cap-h' }, `${capital(chamberWords(q.chamber))} votes`),
      c ? h('p', {}, `As it would fall today: ${c.yeas} to remove, ${c.nays} to keep.`) : h('p', { class: 'muted' }, 'No count sent.'));
  }
  if (q.way === 'council' || q.way === 'person') {
    return h('section', { class: 'rl-office-table', 'aria-label': q.way === 'person' ? 'One person decides' : 'The council' },
      h('h4', { class: 'rl-cap-h' }, q.way === 'person' ? 'One person decides' : 'Around the table'),
      h('ul', { role: 'list', class: 'rl-office-members' }, (q.deciders ?? []).map((name) => h('li', { 'data-member': name },
        h('strong', {}, name), ' ',
        h('span', { class: 'muted' }, SEALED)))));
  }
  return h('p', { class: 'rl-office-way' }, q.way === 'term' ? 'It is decided by the end of the term.' : 'It is decided by the post\'s base on the day of the election.');
}

/** An open office question as a panel, or its public result once there is one. */
export function officePanel(entry, on = {}) {
  if (entry.result) return resultPanel(entry.result);
  const q = entry.q;
  return h('section', { class: `rl-office-panel w-${q.way}`, 'aria-label': `The office question on ${q.office}`, 'data-question': q.question_id },
    h('p', { class: 'rl-office-what' }, `Whether ${q.holder} stays as ${q.office}.`),
    h('p', { class: 'rl-office-why' }, `Opened because ${CAUSE_WORDS[q.cause] ?? q.cause}. It sits ${worldDate(q.sits)}.`),
    h('p', { class: 'rl-office-who' }, `Decided by: ${WAY_WORDS[q.way] ?? q.way}.`),
    deciders(q),
    q.mine ? choiceControl(q, on) : null);
}

/** "On 1 May 1900, the assembly: The Greens 60 → 64, The Greys 40 → 36". */
export function electionWords(e) {
  const seats = (e.chambers ?? []).map((c) => `${chamberWords(c.key)}: ${(c.blocs ?? []).map((b) => `${b.name} ${b.seats} → ${b.would}`).join(', ')}`);
  return `${worldDate(e.day)}${e.office ? `, the term of ${e.office} ends` : ''}; seats as they would fall today, ${seats.join('; ')}`;
}

/** Each election ahead, one line each; null with none. */
export function electionsSection(home) {
  const list = electionsOf(home);
  if (!list.length) return null;
  return h('section', { class: 'rl-office-elections', 'aria-label': 'Elections ahead' },
    h('h4', {}, 'Elections ahead'),
    h('ul', { role: 'list' }, list.map((e) => h('li', { 'data-day': e.day }, electionWords(e)))));
}

/** The office block of the home sheet: footing, each question in brief or its result, the elections. */
export function homeOffice(home) {
  const qs = officeQuestions(home);
  const foot = footingStrip(home);
  const els = electionsSection(home);
  if (!qs.length && !foot && !els) return null;
  return h('section', { class: 'rl-home-office', 'aria-label': 'The office question' },
    foot,
    qs.length ? h('ul', { role: 'list', class: 'rl-office-brief' }, qs.map((x) => h('li', { 'data-question': (x.q ?? x.result).question_id },
      x.result ? resultWords(x.result)
        : `The office question on ${x.q.office} sits ${worldDate(x.q.sits)}; ${WAY_WORDS[x.q.way] ?? x.q.way} decides.${x.q.mine ? ` ${x.q.choice === null ? NOT_FILED : 'Your choice is filed.'}` : ''}`))) : null,
    els);
}
