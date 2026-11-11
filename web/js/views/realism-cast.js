// A realism game choosing its people (Batch 5): each player picks someone from the
// cast, whose papers are drawn up on the spot if no one has yet. The host invites
// the others and begins.

import { api } from '../api.js';
import { h, reply } from '../dom.js';
import { castLine } from '../realism-rules.js';
import { header } from './frame.js';

/** One pick at a time: a redraw gives fresh buttons, so the guard cannot live on a button. */
export function pickLock() {
  const lock = {
    busy: false,
    async run(fn) {
      if (lock.busy) return false;
      lock.busy = true;
      try {
        await fn();
        return true;
      } finally {
        lock.busy = false;
      }
    },
  };
  return lock;
}

const picks = pickLock();

function run(out, button, label, action, body, after) {
  if (action !== 'pick') return doRun(out, button, label, action, body, after);
  return picks.run(() => doRun(out, button, label, action, body, after));
}

async function doRun(out, button, label, action, body, after) {
  const was = button.textContent;
  button.disabled = true;
  button.textContent = label;
  out.replaceChildren();
  try {
    const r = await api.newGame(action, body);
    out.replaceChildren(reply(r.reply), r.code ? h('p', { class: 'code' }, h('strong', {}, r.code)) : null);
    if (!r.refused) await after?.(r);
  } catch (ex) {
    out.replaceChildren(h('p', { class: 'form-error' }, ex.message));
  } finally {
    button.disabled = false;
    button.textContent = was;
  }
}

/** The generated list without anyone already in the cast, by side then kind of power. */
export function figureGroups(groups, castNames) {
  const cast = new Set(castNames.map((n) => n.toLowerCase()));
  return groups
    .map((g) => ({ ...g, figures: g.figures.filter((f) => !cast.has(f.name.toLowerCase())) }))
    .filter((g) => g.figures.length)
    .sort((a, b) => a.side.localeCompare(b.side) || a.power.localeCompare(b.power));
}

export const PLAY_STYLES = [
  { value: 'beginner', label: 'Beginner', line: 'Your aide offers a few ready orders for each matter.' },
  { value: 'guided', label: 'Guided', line: 'Your aide offers a plan for each matter; you write the orders.' },
  { value: 'free', label: 'Free', line: 'You write every order yourself.' },
];

const SEARCH_WAIT = 300;

/** Names on the generated list that are already in the cast. */
export function alreadyPlayed(groups, castNames) {
  const cast = new Set(castNames.map((n) => n.toLowerCase()));
  return groups.flatMap((g) => g.figures).map((f) => f.name).filter((n) => cast.has(n.toLowerCase()));
}

/**
 * What the Find someone box shows: a loading line, the list, or a line saying why it is empty.
 * `taken` names matches hidden because they are already played; the query then names them,
 * not someone new, so no draw is offered.
 */
export function searchState({ loading, shown, query, taken = [] }) {
  if (loading) return { kind: 'loading', text: 'Searching…' };
  if (shown.length) return { kind: 'list' };
  const q = query.trim();
  if (q && taken.length) {
    const who = taken.length === 1 ? `${taken[0]} matches` : `${taken.slice(0, -1).join(', ')} and ${taken.at(-1)} match`;
    return { kind: 'taken', text: `Only ${who} “${q}”, and they are already played.` };
  }
  if (q) return { kind: 'none', text: `No one on the list matches “${q}”.`, offer: `Draw up ${q}` };
  return { kind: 'empty', text: 'No one is listed for this date.' };
}

function whoHeldPower(game, cast, refresh) {
  const out = h('div', { class: 'outcome', role: 'status', 'aria-live': 'polite' });
  const list = h('div', { class: 'held-list' });
  const search = h('input', { id: 'held-search', type: 'search', maxlength: 120, autocomplete: 'off' });
  let timer = null;
  let latest = 0;
  let loading = true;
  let groups = [];
  let asked = '';
  const playButton = (f) => {
    const play = h('button', { type: 'button' }, `Play ${f.name}`);
    play.addEventListener('click', () => run(out, play, 'Drawing up their papers…', 'pick', { name: f.name }, refresh));
    return play;
  };
  const offerButton = (label, name) => {
    const offer = h('button', { type: 'button' }, label);
    offer.addEventListener('click', () => run(out, offer, 'Drawing up their papers…', 'pick', { name }, refresh));
    return offer;
  };
  const render = () => {
    const shown = figureGroups(groups, cast);
    const state = searchState({ loading, shown, query: asked, taken: alreadyPlayed(groups, cast) });
    if (state.kind === 'list') {
      list.replaceChildren(...shown.map((g) => h('div', { class: 'held-group' },
        h('h3', {}, g.side),
        h('h4', {}, g.power),
        h('ul', { class: 'held-figures' }, g.figures.map((f) => h('li', {},
          h('span', { class: 'char-name' }, f.name),
          f.title ? h('span', { class: 'muted' }, f.title) : null,
          playButton(f)))))));
    } else if (state.kind === 'none') {
      list.replaceChildren(
        h('p', { class: 'muted' }, state.text),
        h('p', { class: 'hint' }, 'A person not on the list takes about a minute, and the record may not place them.'),
        offerButton(state.offer, asked));
    } else {
      list.replaceChildren(h('p', { class: 'muted' }, state.text));
    }
  };
  const load = () => {
    const mine = ++latest;
    asked = search.value.trim();
    loading = true;
    render();
    const body = { date: game.date };
    if (asked) body.search = asked;
    api.newGame('figures', body).then((r) => {
      if (mine !== latest) return;
      if (r.refused) list.replaceChildren(reply(r.reply));
      else {
        loading = false;
        groups = r.figures;
        render();
      }
    }).catch((ex) => {
      if (mine === latest) list.replaceChildren(h('p', { class: 'form-error' }, ex.message));
    });
  };
  search.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(load, SEARCH_WAIT);
  });
  load();
  return h('section', { class: 'held', 'aria-labelledby': 'held-title' },
    h('h2', { id: 'held-title' }, 'Who held power'),
    h('p', { class: 'muted' }, 'Anyone on this list can be played. A person not yet drawn up takes about a minute.'),
    h('label', { for: 'held-search' }, 'Find someone'), search,
    list, out);
}

function playStyle() {
  const out = h('div', { class: 'outcome', role: 'status', 'aria-live': 'polite' });
  const choices = PLAY_STYLES.map((s) => {
    const radio = h('input', { type: 'radio', name: 'play-style', id: `style-${s.value}`, value: s.value, checked: s.value === 'free' });
    radio.addEventListener('change', async () => {
      try {
        const r = await api.newGame('style', { style: s.value });
        out.replaceChildren(reply(r.reply));
      } catch (ex) {
        out.replaceChildren(h('p', { class: 'form-error' }, ex.message));
      }
    });
    return h('div', { class: 'style-choice' },
      radio, h('label', { for: `style-${s.value}` }, s.label), h('p', { class: 'hint' }, s.line));
  });
  return h('fieldset', { class: 'play-style' }, h('legend', {}, 'How you play'), choices, out);
}

function hostPanel(game, refresh) {
  const out = h('div', { class: 'outcome', role: 'status', 'aria-live': 'polite' });
  const invite = h('button', { type: 'button' }, 'Invite a player');
  invite.addEventListener('click', () => run(out, invite, 'Issuing…', 'invite', {}));
  const begin = h('button', { type: 'button', class: 'primary', disabled: game.waiting > 0 }, 'Begin the game');
  begin.addEventListener('click', () => run(out, begin, 'Beginning…', 'begin', {}, refresh));
  return h('aside', { class: 'aside-card', 'aria-label': 'Host' },
    h('span', { class: 'eyebrow' }, 'You are the host'),
    h('p', {}, castLine(game.waiting)),
    h('div', { class: 'row' }, invite, begin),
    h('p', { class: 'hint' }, 'Each code seats one player. Anyone in the cast no player takes is drawn up after the game begins and acts on their own.'),
    out);
}

export function realismCast(ctx) {
  const { me, refresh } = ctx;
  const game = me.game;
  const view = game.view;
  const mine = view.seat?.name;
  const out = h('div', { class: 'outcome', role: 'status', 'aria-live': 'polite' });
  const cards = view.roster.map((c) => {
    const play = h('button', { type: 'button', disabled: c.taken || Boolean(mine) },
      c.taken ? 'Taken' : `Play ${c.name}`);
    play.addEventListener('click', () => run(out, play, 'Drawing up their papers…', 'pick', { name: c.name }, refresh));
    return h('article', { class: `char${c.taken ? ' taken' : ''}` },
      h('div', { class: 'char-head' },
        h('span', { class: 'char-name' }, c.name),
        c.taken ? h('span', { class: 'tag' }, c.name === mine ? 'You' : 'Taken') : null),
      h('p', {}, c.pitch),
      h('p', { class: 'muted' }, h('strong', {}, 'Reach: '), c.reach),
      mine ? null : play);
  });
  return h('div', { class: 'screen' },
    header({ ...ctx, game, role: 'Choosing the cast' }),
    h('div', { class: 'sz sz-solo' },
      h('main', { class: 'sz-main' },
        h('div', { class: 'sz-inner' },
          h('div', { class: 'step-head' },
            h('h1', {}, mine ? `You are ${mine}` : 'Choose who you will play'),
            h('p', {}, mine
              ? 'Waiting for the host to begin. You can close this tab; your place is kept.'
              : 'Drawing up a person for the first time takes a minute.')),
          h('div', { class: 'split' },
            h('div', {},
              out,
              h('div', { class: 'roster' }, cards),
              mine ? playStyle() : (game.date ? whoHeldPower(game, view.roster.map((c) => c.name), refresh) : null)),
            game.host ? hostPanel(game, refresh) : null)))));
}
