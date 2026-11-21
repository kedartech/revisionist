// The diplomacy layer (DPL): the map's Diplomatic layer key (each nation's standing to the seat,
// the capitals the payload pins, the public pacts and the seat's envoys), and the Diplomacy sheet:
// the agreements with a chip per clause and Publish, the offers, the offer builder with its reading
// to sign, and the conferences with the call form and the sealed vote. Everything is drawn from the
// seat's own view (`agreements`, `conferences`, the map); no other seat's vote is drawn before a
// tally, whatever reaches the client. Nothing here touches the page on import.

import { h } from '../dom.js';
import { worldDate } from '../rules.js';
import { addDays } from '../realism-rules.js';
import { ANSWER_AT_CLOSE } from './realism-requests.js';

/** The sheet's title and the heading of the layer's key [proposed]. */
export const DIPLOMACY_TITLE = 'Diplomacy';

/** World days from a call to the earliest voting day (CNF `CONF_DAYS`); the server checks the two wake openings. */
export const CONF_DAYS = 4;

/**
 * The clauses the builder offers, as [type, words]: those the seat can name from what its payload
 * holds (nations by id). A clause naming an area, a piece or a form needs an id the payload does not
 * carry, so it is written as wording, which the rules do not check.
 */
export const CLAUSE_TYPES = Object.freeze([
  ['no_war', 'No war declared on a nation'],
  ['no_attack', 'No attack on a nation'],
  ['defend', 'War on whoever newly attacks a nation'],
  ['aid', 'An aid share to a nation'],
]);

/** A clause's state as its chip says it. An unchecked clause is never drawn as checked. */
const STATE_WORDS = Object.freeze({
  pending: 'Pending', kept: 'Kept', broken: 'Broken', called: 'Called', void: 'Void', unchecked: 'Not checked by the rules',
});
const VOTE_WORDS = Object.freeze({ for: 'For', against: 'Against', abstain: 'Abstain' });
const RELATION_WORDS = Object.freeze({
  own: 'your nation', enemy: 'at war with you', ally: 'at war beside you', neutral: 'not at war with you',
});

const day = (d) => (/^\d{4}-\d{2}-\d{2}$/.test(d ?? '') ? worldDate(d) : d ?? '');

/** "A", "A and B", "A, B and C". */
export function andList(names) {
  const xs = [...names];
  return xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs.at(-1)}`;
}

/**
 * Every nation the seat's payload names with its id, the seat's own first: from the economy's
 * figures, the standings at home and the holders on the map, as `{ key, name, relation }`.
 */
export function nationsOf(rv) {
  const out = new Map();
  const add = (n) => { if (n?.key && !out.has(n.key)) out.set(n.key, n); };
  for (const f of rv.economy?.figures ?? []) add(f.nation);
  add(rv.economy?.own?.nation);
  for (const s of rv.home?.standings ?? []) add(s.nation);
  add(rv.home?.nation);
  for (const a of rv.map?.areas ?? []) { add(a.holder); add(a.taken_from); }
  const all = [...out.values()];
  return [...all.filter((n) => n.relation === 'own'), ...all.filter((n) => n.relation !== 'own')];
}

const ownNation = (rv) => nationsOf(rv).find((n) => n.relation === 'own') ?? null;
const otherNations = (rv) => nationsOf(rv).filter((n) => n.relation !== 'own');

/** The seat's own envoys on the map: marks whose piece has the envoy domain. */
export const envoysOf = (map) => (map?.marks ?? []).filter((m) => m.piece?.domain === 'envoy');

/** Agreements made public, by any party: the pacts every seat may read. */
export const publicPacts = (block) => (block?.agreements ?? []).filter((a) => a.published);

/** An envoy's line: where it stands, and where it is bound while under way. */
function envoyWhere(m) {
  const at = m.piece?.area?.name ?? m.area?.name ?? 'somewhere not shown';
  const to = m.piece?.under_way?.to?.name;
  return to ? `in ${at}, on its way to ${to}` : `in ${at}`;
}

/**
 * The Diplomatic layer's key, drawn under the map on that layer: each nation and how it stands to
 * the seat (who is at war with it), each capital the map pins, the public pacts and the envoys.
 * A list with nothing in it is left out.
 */
export function diplomacyKey(rv) {
  const nations = nationsOf(rv);
  const capitals = rv.map?.capitals ?? [];
  const pacts = publicPacts(rv.agreements);
  const envoys = envoysOf(rv.map);
  const list = (cls, title, items) => (items.length
    ? h('div', { class: `rl-dp-keypart ${cls}` }, h('h3', {}, title), h('ul', { role: 'list' }, items))
    : null);
  return h('section', { class: 'rl-dp-key', 'aria-label': 'Diplomatic layer' },
    list('rl-dp-nations', 'Nations', nations.map((n) => h('li', { class: `rl-dp-nation rl-rel-${n.relation}` },
      h('strong', {}, n.name), `: ${RELATION_WORDS[n.relation] ?? RELATION_WORDS.neutral}`))),
    list('rl-dp-capitals', 'Capitals', capitals.map((c) => h('li', {},
      h('strong', {}, c.place.name), `: ${c.name}, ${c.stance?.word ?? 'stance unknown'}${c.at_war ? ', at war with you' : ''}`))),
    list('rl-dp-pacts', 'Public pacts', pacts.map((a) => h('li', {},
      h('strong', {}, andList(a.parties)), `: ${a.wording || `${a.clauses.length} clauses`} Public since ${day(a.published)}`))),
    list('rl-dp-envoys', 'Envoys', envoys.map((m) => h('li', {}, h('strong', {}, m.name), `: ${envoyWhere(m)}`))));
}

// --- the agreements -----------------------------------------------------------------------------

/** A clause's chip: its state in words; a clause the rules do not check reads so, whatever its state. */
export function clauseChip(clause) {
  const state = clause.checked ? clause.state : 'unchecked';
  return h('span', {
    class: `rl-dp-chip rl-dp-${state}`, 'data-state': state, 'data-checked': String(Boolean(clause.checked)),
  }, STATE_WORDS[state] ?? state);
}

/** A term's chip for an offer or a text: whether the rules check it. */
const termChip = (c) => h('span', {
  class: `rl-dp-tag rl-dp-${c.checked ? 'checked' : 'unchecked'}`, 'data-checked': String(Boolean(c.checked)),
}, c.checked ? 'Checked by the rules' : STATE_WORDS.unchecked);

function agreementItem(a, act) {
  return h('li', { class: 'rl-dp-agreement', 'data-agreement': a.id },
    h('p', { class: 'rl-dp-head' }, h('strong', {}, andList(a.parties)), ` · made ${day(a.made)}`),
    a.wording ? h('p', { class: 'rl-dp-wording' }, `Wording, which the rules do not check: ${a.wording}`) : null,
    a.clauses.length
      ? h('ul', { class: 'rl-dp-clauses', role: 'list' }, a.clauses.map((c) => h('li', { class: 'rl-dp-clause-line' },
        h('span', { class: 'rl-dp-text' }, c.text), ' ', clauseChip(c),
        c.on && c.checked ? h('span', { class: 'rl-dp-on muted' }, ` ${c.state === 'pending' ? 'judged on' : 'judged'} ${day(c.on)}`) : null)))
      : null,
    a.published
      ? h('p', { class: 'rl-dp-public' }, `Public since ${day(a.published)}`)
      : a.party
        ? h('div', { class: 'rl-dp-publish' },
          h('p', { class: 'muted' }, 'Known only to its parties.'),
          h('button', {
            type: 'button', class: 'rl-btn rl-dp-btn', 'aria-label': `Publish the agreement of ${andList(a.parties)}`,
            onclick: () => act?.('Sending it…', 'agreement-publish', { agreement: a.id }),
          }, 'Publish'))
        : null);
}

function termsList(terms) {
  return [
    terms.clauses.length
      ? h('ul', { class: 'rl-dp-terms-list', role: 'list' }, terms.clauses.map((c) => h('li', { class: 'rl-dp-term' },
        h('span', { class: 'rl-dp-text' }, c.text), ' ', termChip(c),
        c.interpretation ? h('span', { class: 'rl-dp-read' }, ' Your aide\'s reading of your wording') : null)))
      : null,
    terms.wording ? h('p', { class: 'rl-dp-wording' }, `Wording, which the rules do not check: ${terms.wording}`) : null,
  ];
}

function offerItem(o, act) {
  const own = o.item == null && o.answers.length > 0;
  const others = o.terms.parties.filter((p) => p !== o.by);
  const answerWord = (a) => (a.answer === 'accepted' ? 'accepted' : a.answer === 'declined' ? 'declined' : 'no answer yet');
  const answer = (accept, word) => h('button', {
    type: 'button', class: 'rl-btn rl-dp-btn', onclick: () => act?.('Sending your answer…', 'answer', { item: o.item, accept }),
  }, word);
  return h('li', { class: 'rl-dp-offer', 'data-own': String(own) },
    h('p', { class: 'rl-dp-head' }, h('strong', {}, own ? `Your offer to ${andList(others)}` : `${o.by} offers`),
      ` · filed ${day(o.filed)}`),
    termsList(o.terms),
    own
      ? [h('ul', { class: 'rl-dp-answers', role: 'list' }, o.answers.map((a) => h('li', {}, `${a.nation}: ${answerWord(a)}`))),
        h('p', { class: 'rl-dp-due' }, `Due ${day(o.expires)}`)]
      : o.item
        ? [h('p', { class: 'rl-dp-due' }, `Your answer is due ${day(o.expires)}`),
          h('div', { class: 'rl-dp-pair' }, answer(true, 'Accept'), answer(false, 'Decline')),
          h('p', { class: 'hint' }, ANSWER_AT_CLOSE)]
        : h('p', { class: 'rl-dp-due' }, `Answered; decided on ${day(o.expires)}`));
}

/** The agreements sheet: each agreement with its clauses' chips and Publish, then the open offers. */
export function agreementsSection(block, { act } = {}) {
  const agreements = block?.agreements ?? [];
  const offers = block?.offers ?? [];
  return h('section', { class: 'rl-dp-agreements', 'aria-labelledby': 'rl-dp-agr-h' },
    h('h3', { id: 'rl-dp-agr-h' }, 'Agreements'),
    agreements.length
      ? h('ul', { class: 'rl-dp-list', role: 'list' }, agreements.map((a) => agreementItem(a, act)))
      : h('p', { class: 'muted' }, 'No agreement is in force that you know of.'),
    offers.length
      ? [h('h3', {}, 'Open offers'), h('ul', { class: 'rl-dp-list', role: 'list' }, offers.map((o) => offerItem(o, act)))]
      : null);
}

// --- the offer builder ---------------------------------------------------------------------------

/** An empty offer: the builder's state, kept by the room across redraws. */
export const freshOffer = () => ({ wording: '', parties: [], clauses: [], envoy: '' });

/**
 * The envoys the seat can name as a carrier: its envoys on the map that a form lists, by the
 * value the form files for them (the world key the offer action takes), as [value, name].
 */
export function envoyChoices(rv) {
  const names = new Set(envoysOf(rv.map).map((m) => m.name));
  const out = new Map();
  for (const lever of rv.desk?.levers ?? []) {
    for (const p of lever.params ?? []) {
      for (const c of p.choices ?? []) if (names.has(c.label) && !out.has(c.value)) out.set(c.value, c.label);
    }
  }
  return [...out];
}

/** A select of [value, words] options with `value` chosen (set once its options exist). */
function select(attrs, options, value) {
  const el = h('select', attrs, options.map(([v, label]) => h('option', { value: v, selected: v === value ? true : null }, label)));
  if (value !== undefined && value !== null) el.value = value;
  return el;
}

const nationOptions = (nations) => nations.map((n) => [n.key, n.name]);

/** The fields one clause type takes beyond who it binds and the nation it names. */
const EXTRA = Object.freeze({ defend: ['days', 'Within days', 0, 60], aid: ['share', 'Share, per cent', 1, 100] });

function clauseRow(clause, i, nations, draft, redraw) {
  const words = new Map(CLAUSE_TYPES).get(clause.type) ?? clause.type;
  const set = (name) => (e) => { clause[name] = e.target.value; };
  const extra = EXTRA[clause.type];
  return h('li', { class: 'rl-dp-clause', 'data-type': clause.type },
    h('p', { class: 'rl-dp-head' }, h('strong', {}, `Clause ${i + 1}: ${words}`)),
    h('label', { class: 'rl-dp-field' }, 'Binds ',
      select({ name: 'binds', onchange: set('binds') }, nationOptions(nations), clause.binds)),
    h('label', { class: 'rl-dp-field' }, 'Nation named ',
      select({ name: 'nation', onchange: set('nation') }, nationOptions(nations), clause.nation)),
    extra
      ? h('label', { class: 'rl-dp-field' }, `${extra[1]} `, h('input', {
        type: 'number', name: extra[0], min: extra[2], max: extra[3], value: clause[extra[0]] ?? '', oninput: set(extra[0]),
      }))
      : null,
    h('button', {
      type: 'button', class: 'rl-btn rl-dp-btn', 'aria-label': `Take clause ${i + 1} out`,
      onclick: () => { draft.clauses.splice(i, 1); redraw?.(); },
    }, 'Take it out'));
}

/** What the offer action is sent: the nations, the wording, each clause with its fields as numbers, and an envoy if named. */
export function offerBody(draft) {
  const clauses = draft.clauses.map((c) => {
    const out = { type: c.type, binds: c.binds, nation: c.nation };
    const extra = EXTRA[c.type];
    if (extra) out[extra[0]] = Number(c[extra[0]]);
    return out;
  });
  const body = { parties: [...draft.parties], wording: draft.wording.trim(), clauses };
  if (draft.envoy) body.envoy = draft.envoy;
  return body;
}

/**
 * The offer builder: free wording, the nations it is offered to, typed clauses added from
 * `CLAUSE_TYPES` and taken out again, and the carrier (the usual channel, or an envoy). "Read the
 * terms" sends `agreement-offer`; the reply, the terms to sign, goes to `onReading`. `draft` is
 * the room's `freshOffer()`, changed as the player types; `redraw` redraws after a clause is added or taken out.
 */
export function offerBuilder(rv, draft, { act, redraw, onReading } = {}) {
  const own = ownNation(rv);
  const others = otherNations(rv);
  const nations = [own, ...others].filter(Boolean);
  const envoys = envoyChoices(rv);
  const addType = select({ class: 'rl-dp-addtype', name: 'add', 'aria-label': 'Clause to add' }, CLAUSE_TYPES, CLAUSE_TYPES[0][0]);
  const add = () => {
    draft.clauses.push({ type: addType.value, binds: own?.key ?? '', nation: others[0]?.key ?? own?.key ?? '' });
    redraw?.();
  };
  return h('section', { class: 'rl-dp-builder', 'aria-labelledby': 'rl-dp-build-h' },
    h('h3', { id: 'rl-dp-build-h' }, 'Offer an agreement'),
    h('label', { class: 'rl-dp-field rl-dp-wide' }, 'Your wording (the rules do not check it)',
      h('textarea', { name: 'wording', rows: 3, maxlength: 600, value: draft.wording, oninput: (e) => { draft.wording = e.target.value; } })),
    h('fieldset', { class: 'rl-dp-nationset' }, h('legend', {}, 'Offered to'),
      others.length
        ? others.map((n) => h('label', { class: 'rl-dp-check' }, h('input', {
          type: 'checkbox', name: 'parties', value: n.key, checked: draft.parties.includes(n.key),
          onchange: (e) => {
            draft.parties = e.target.checked ? [...new Set([...draft.parties, n.key])] : draft.parties.filter((k) => k !== n.key);
          },
        }), ` ${n.name}`))
        : h('p', { class: 'muted' }, 'No other nation is named to you yet.')),
    draft.clauses.length
      ? h('ol', { class: 'rl-dp-clauserows', role: 'list' }, draft.clauses.map((c, i) => clauseRow(c, i, nations, draft, redraw)))
      : null,
    h('div', { class: 'rl-dp-add' },
      h('label', { class: 'rl-dp-field' }, 'Add a clause the rules check ', addType),
      h('button', { type: 'button', class: 'rl-btn rl-dp-btn', onclick: add }, 'Add the clause')),
    envoys.length
      ? h('label', { class: 'rl-dp-field' }, 'Carried by ',
        select({ name: 'envoy', onchange: (e) => { draft.envoy = e.target.value; } }, [['', 'the usual channel'], ...envoys], draft.envoy))
      : h('p', { class: 'rl-dp-carrier' }, 'Carried by the usual channel.'),
    h('button', {
      type: 'button', class: 'btn-1 rl-dp-read-btn',
      onclick: () => act?.('Your aide is reading the terms…', 'agreement-offer', offerBody(draft), (r) => onReading?.(r)),
    }, 'Read the terms'));
}

/**
 * The reading of an offer, to sign: each clause with whether the rules check it and whether it is
 * the aide's reading of the seat's wording, the wording the rules do not check, the carrier, and the
 * terms as the server rendered them (`agreement.render_terms`). "Sign and send" files it; a refused
 * reading shows why, with nothing to sign.
 */
export function termsCard(reading, { act, onBack, onSigned } = {}) {
  const back = h('button', { type: 'button', class: 'rl-btn rl-dp-btn', onclick: () => onBack?.() }, 'Change the offer');
  if (reading.refused || !reading.terms) {
    return h('section', { class: 'rl-dp-terms rl-dp-refused', role: 'status' }, h('p', {}, reading.reply), back);
  }
  const { terms } = reading;
  const carried = (reading.proposal?.parts ?? []).find((p) => p.startsWith('Carried by')) ?? 'Carried by the usual channel.';
  return h('section', { class: 'rl-dp-terms', 'aria-labelledby': 'rl-dp-terms-h' },
    h('h3', { id: 'rl-dp-terms-h' }, 'Your offer, to sign'),
    h('p', {}, reading.reply),
    h('p', { class: 'rl-dp-head' }, `Parties: ${andList(terms.parties)}`),
    termsList({ ...terms, wording: '' }),
    terms.wording ? h('p', { class: 'rl-dp-wording' }, `Your wording, which the rules do not check: ${terms.wording}`) : null,
    h('p', { class: 'rl-dp-carrier' }, carried),
    h('div', { class: 'rl-dp-signed' }, h('h4', {}, 'The terms you sign'), h('p', {}, terms.text)),
    h('div', { class: 'rl-dp-pair' },
      h('button', { type: 'button', class: 'btn-1', onclick: () => act?.('Sending it…', 'file', {}, (r) => onSigned?.(r)) }, 'Sign and send'),
      back));
}

// --- the conferences -----------------------------------------------------------------------------

/** An empty call: the call form's state, kept by the room across redraws. */
export const freshCall = () => ({ text: '', invited: [], voting_day: '', public: false, unanimous: false });

/** The earliest voting day the seat can name: `CONF_DAYS` world days from today. */
export const earliestVote = (rv) => (rv.clock?.world_date ? addDays(rv.clock.world_date, CONF_DAYS) : '');

/** The result after the tally, in words. */
function resultWords(c) {
  const yes = (c.votes ?? []).filter((v) => v.vote === 'for').map((v) => v.nation);
  if (c.result === 'agreement') return `Passed: an agreement among ${andList(yes)}.`;
  if (c.result === 'resolution') return 'Passed as a resolution that binds no one.';
  if (c.result === 'cancelled') return 'Cancelled: too few nations voted for a quorum.';
  return 'Not passed.';
}

function voteControls(c, act) {
  return h('div', { class: 'rl-dp-vote', role: 'group', 'aria-label': 'Your vote' },
    Object.entries(VOTE_WORDS).map(([v, word]) => h('button', {
      type: 'button', class: 'rl-btn rl-dp-btn', 'aria-pressed': String(c.vote === v),
      onclick: () => act?.('Sealing your vote…', 'conference-vote', { conference: c.key, vote: v }),
    }, word)));
}

function conferenceItem(c, act) {
  const tallied = Boolean(c.tallied);
  return h('li', { class: 'rl-dp-conference', 'data-conference': c.key },
    h('p', { class: 'rl-dp-head' }, h('strong', {}, c.text)),
    h('p', {}, `Called by ${c.called_by} on ${day(c.called)}. ${c.public ? 'Public.' : 'Private to the nations invited.'}`),
    h('p', {}, `Invited: ${c.invited.join(', ')}`),
    h('p', { class: 'rl-dp-due' }, `Votes on ${day(c.voting_day)}${c.unanimous ? '; it passes only if every nation invited is for' : ''}`),
    c.clauses.length ? termsList({ clauses: c.clauses, wording: '' }) : null,
    tallied
      ? [h('p', { class: 'rl-dp-result' }, resultWords(c)),
        h('p', { class: 'muted' }, `Tallied ${day(c.tallied)}`),
        // each nation's counted vote, only once the tally gives it
        (c.votes ?? []).length
          ? h('ul', { class: 'rl-dp-votes', role: 'list' }, c.votes.map((v) => h('li', {}, `${v.nation}: ${VOTE_WORDS[v.vote] ?? v.vote}`)))
          : null,
        c.vote ? h('p', {}, `Your vote: ${VOTE_WORDS[c.vote]}`) : null]
      : [c.vote
        ? h('p', { class: 'rl-dp-yours' }, `Your vote, sealed until the tally: ${VOTE_WORDS[c.vote]}`)
        : h('p', { class: 'rl-dp-yours' }, 'You have not voted. No one sees your vote before the tally.'),
      c.can_vote
        ? [voteControls(c, act), c.vote ? h('p', { class: 'hint' }, 'To replace your vote, vote again before this wake closes.') : null]
        : c.vote ? h('p', { class: 'hint' }, 'Your vote stands: it was sealed in an earlier wake.') : null]);
}

/** The call form: the text, the nations invited, the voting day, and whether it is public or unanimous. */
function callForm(rv, draft, act) {
  const others = otherNations(rv);
  const earliest = earliestVote(rv);
  const flag = (name, label) => h('label', { class: 'rl-dp-check' }, h('input', {
    type: 'checkbox', name, checked: draft[name], onchange: (e) => { draft[name] = e.target.checked; },
  }), ` ${label}`);
  const send = (e) => {
    e?.preventDefault?.();
    const body = { text: draft.text.trim(), invited: [...draft.invited], voting_day: draft.voting_day || earliest, public: Boolean(draft.public) };
    if (draft.unanimous) body.unanimous = true;
    act?.('Calling the conference…', 'conference-call', body, (r) => { if (!r?.refused) Object.assign(draft, freshCall()); });
  };
  return h('form', { class: 'rl-dp-call', 'aria-labelledby': 'rl-dp-call-h', onsubmit: send },
    h('h4', { id: 'rl-dp-call-h' }, 'Call a conference'),
    h('label', { class: 'rl-dp-field rl-dp-wide' }, 'The text put to the vote',
      h('textarea', { name: 'text', rows: 3, maxlength: 600, value: draft.text, oninput: (e) => { draft.text = e.target.value; } })),
    h('fieldset', { class: 'rl-dp-nationset' }, h('legend', {}, 'Nations invited (yours is always at it)'),
      others.length
        ? others.map((n) => h('label', { class: 'rl-dp-check' }, h('input', {
          type: 'checkbox', name: 'invited', value: n.key, checked: draft.invited.includes(n.key),
          onchange: (e) => {
            draft.invited = e.target.checked ? [...new Set([...draft.invited, n.key])] : draft.invited.filter((k) => k !== n.key);
          },
        }), ` ${n.name}`))
        : h('p', { class: 'muted' }, 'No other nation is named to you yet.')),
    h('label', { class: 'rl-dp-field' }, 'Voting day ', h('input', {
      type: 'date', name: 'voting_day', min: earliest || null, value: draft.voting_day || earliest,
      onchange: (e) => { draft.voting_day = e.target.value; }, oninput: (e) => { draft.voting_day = e.target.value; },
    })),
    h('p', { class: 'hint' }, `At least ${CONF_DAYS} world days and two wake openings after the call.`),
    flag('public', 'Public: the call and the result are news'),
    flag('unanimous', 'Passes only if every nation invited is for'),
    h('button', { type: 'submit', class: 'btn-1' }, 'Call the conference'));
}

/** The conference sheet: each conference the seat's nation is invited to, then the call form. */
export function conferencesSection(rv, draft, { act } = {}) {
  const confs = rv.conferences?.conferences ?? [];
  return h('section', { class: 'rl-dp-conferences', 'aria-labelledby': 'rl-dp-conf-h' },
    h('h3', { id: 'rl-dp-conf-h' }, 'Conferences'),
    confs.length
      ? h('ul', { class: 'rl-dp-list', role: 'list' }, confs.map((c) => conferenceItem(c, act)))
      : h('p', { class: 'muted' }, 'No conference you are invited to.'),
    callForm(rv, draft, act));
}

/** Whether the seat's game has any diplomacy to show: agreements or conferences on. */
export const hasDiplomacy = (rv) => Boolean(rv.agreements || rv.conferences);

/**
 * The Diplomacy sheet: the agreements, the offer builder (or its reading, to sign) and the
 * conferences. `state` is the room's `{ offer, call, reading }`, kept across redraws.
 */
export function diplomacySheet(rv, state, { act, redraw } = {}) {
  const builder = state.reading
    ? termsCard(state.reading, {
      act,
      onBack: () => { state.reading = null; redraw?.(); },
      onSigned: (r) => { if (!r?.refused) { state.reading = null; state.offer = freshOffer(); } },
    })
    : offerBuilder(rv, state.offer, { act, redraw, onReading: (r) => { state.reading = r; } });
  return h('div', { class: 'rl-dp-sheet' },
    rv.agreements ? [agreementsSection(rv.agreements, { act }), builder] : null,
    rv.conferences ? conferencesSection(rv, state.call, { act }) : null);
}

/** A fresh state for the Diplomacy sheet. */
export const freshDiplomacy = () => ({ offer: freshOffer(), call: freshCall(), reading: null });
