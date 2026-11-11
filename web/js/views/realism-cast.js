// A realism game choosing its people: the cast as cards that open a dossier, everyone else
// who held power as a searchable table, and the host's invite and Begin. Begin plays the
// opening crawl while the server sets the game up. Units: realism-castcard.js,
// realism-castlist.js, realism-castdossier.js, realism-intro.js.

import { api } from '../api.js';
import { h, reply } from '../dom.js';
import { castLine } from '../realism-rules.js';
import { browserStorage } from '../theme.js';
import { header } from './frame.js';
import { castCard } from './realism-castcard.js';
import { castDossier } from './realism-castdossier.js';
import { alreadyPlayed, castList, figureGroups, searchState } from './realism-castlist.js';
import { crawlParagraphs, introCrawl, markIntro } from './realism-intro.js';

export { alreadyPlayed, figureGroups, searchState };

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

/** Pick `name`; the reply goes in `out`. One pick at a time across redraws. */
function pick(out, name, refresh) {
  return picks.run(async () => {
    out.replaceChildren(h('p', { class: 'muted' }, `Drawing up the papers for ${name}…`));
    try {
      const r = await api.newGame('pick', { name });
      out.replaceChildren(reply(r.reply));
      if (!r.refused) await refresh?.();
    } catch (ex) {
      out.replaceChildren(h('p', { class: 'form-error' }, ex.message));
    }
  });
}

async function issue(out, button) {
  const was = button.textContent;
  button.disabled = true;
  button.textContent = 'Issuing…';
  out.replaceChildren();
  try {
    const r = await api.newGame('invite', {});
    out.replaceChildren(reply(r.reply), r.code ? h('p', { class: 'code' }, h('strong', {}, r.code)) : null);
  } catch (ex) {
    out.replaceChildren(h('p', { class: 'form-error' }, ex.message));
  } finally {
    button.disabled = false;
    button.textContent = was;
  }
}

/** A dossier dialog over `root` for a cast member or a listed figure, removed once closed. */
function openDossier(root, person, { canPlay, out, refresh }) {
  const dialog = castDossier({
    person,
    dossier: person.dossier ?? null,
    canPlay,
    onPlay: () => {
      if (dialog.open) dialog.close();
      pick(out, person.name, refresh);
    },
    onClose: () => {
      if (dialog.open) dialog.close();
      dialog.remove();
    },
  });
  root.append(dialog);
  dialog.showModal();
}

export const PLAY_STYLES = [
  { value: 'beginner', label: 'Beginner', line: 'Your aide offers a few ready orders for each matter.' },
  { value: 'guided', label: 'Guided', line: 'Your aide offers a plan for each matter; you write the orders.' },
  { value: 'free', label: 'Free', line: 'You write every order yourself.' },
];

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

/**
 * Begin, with the opening crawl over the page while the server works. A refused or failed
 * Begin closes the crawl at once and says why; the crawl never holds a player on a failure.
 * Once Begin succeeds the crawl counts as seen, so the room opens on the player's splash.
 */
async function beginWithCrawl(game, out, button, refresh) {
  const paragraphs = crawlParagraphs(game.view.setting);
  button.disabled = true;
  out.replaceChildren(h('p', { class: 'muted' }, 'Beginning…'));
  let crawl = null;
  let ready = false;
  let watched = false;
  const closeCrawl = () => {
    if (crawl?.open) crawl.close();
    crawl?.remove();
  };
  if (paragraphs.length) {
    crawl = introCrawl({
      title: game.name,
      paragraphs,
      onDone: () => {
        watched = true;
        closeCrawl();
        if (ready) refresh?.();
      },
    });
    document.body.append(crawl);
    crawl.showModal();
    crawl.querySelector('.rl-intro-status')?.replaceChildren('Setting up the game…');
  }
  try {
    const r = await api.newGame('begin', {});
    if (r.refused) {
      closeCrawl();
      out.replaceChildren(reply(r.reply));
      return;
    }
    ready = true;
    markIntro(browserStorage(window), game.id, 'crawl');
    if (!crawl || watched) await refresh?.();
    else crawl.querySelector('.rl-intro-status')?.replaceChildren('Ready. Continue when you are.');
  } catch (ex) {
    closeCrawl();
    out.replaceChildren(h('p', { class: 'form-error' }, ex.message));
  } finally {
    button.disabled = false;
  }
}

function hostPanel(game, refresh) {
  const out = h('div', { class: 'outcome', role: 'status', 'aria-live': 'polite' });
  const invite = h('button', { type: 'button' }, 'Invite a player');
  invite.addEventListener('click', () => issue(out, invite));
  const begin = h('button', { type: 'button', class: 'primary', disabled: game.waiting > 0 }, 'Begin the game');
  begin.addEventListener('click', () => {
    if (!begin.disabled) beginWithCrawl(game, out, begin, refresh);
  });
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
  const mine = view.seat?.name ?? null;
  const out = h('div', { class: 'outcome', role: 'status', 'aria-live': 'polite' });
  const castNames = view.roster.map((c) => c.name);
  const screen = h('div', { class: 'screen' });
  const open = (person, canPlay) => openDossier(screen, person, { canPlay, out, refresh });
  const cards = view.roster.map((c) => castCard(c, { mine, onOpen: () => open(c, !c.taken && !mine) }));
  const others = !mine && game.date
    ? castList({
      cast: castNames,
      load: (query) => api.newGame('figures', query ? { date: game.date, search: query } : { date: game.date }),
      onOpen: (row) => open(row, true),
      onDraw: (name) => pick(out, name, refresh),
    })
    : null;
  screen.append(
    header({ ...ctx, game, role: 'Choosing the cast' }),
    h('div', { class: 'sz sz-solo' },
      h('main', { class: 'sz-main' },
        h('div', { class: 'sz-inner' },
          h('div', { class: 'step-head' },
            h('h1', {}, mine ? `You are ${mine}` : 'Choose who you will play'),
            h('p', {}, mine
              ? 'Waiting for the host to begin. You can close this tab; your place is kept.'
              : 'Open a card to read who they are, then play them.')),
          h('div', { class: 'split' },
            h('div', {},
              out,
              h('section', { class: 'rl-cast', 'aria-labelledby': 'rl-cast-title' },
                h('h2', { id: 'rl-cast-title' }, 'The cast'),
                h('div', { class: 'rl-cast-cards' }, cards)),
              mine ? playStyle() : others),
            game.host ? hostPanel(game, refresh) : null)))));
  return screen;
}
