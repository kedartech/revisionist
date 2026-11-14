// The opening of a game (Train 3 unit P4): the crawl (realism-crawl.js), then the player's
// own splash, where the aide greets the seat with how it starts, its first papers and its
// open matters. Once per game per browser; never blocks a player whose storage is blocked.

import { h } from '../dom.js';
import { worldDate } from '../rules.js';
import { aideBriefing } from './realism-briefing.js';

export const INTRO_PREFIX = 'rv.intro.';
export const TAKE_DESK = 'Take your desk';
/** At most this many first papers on the splash; the rest wait in the tray. */
export const PAPERS_MAX = 5;
/** How often the open splash looks for the wake's aide brief. */
export const BRIEF_POLL_MS = 1000;

const lines = (xs) => (Array.isArray(xs) ? xs.filter((x) => typeof x === 'string' && x.trim()).map((x) => x.trim()) : []);
const text = (x) => (typeof x === 'string' && x.trim() ? x.trim() : null);
const list = (xs) => (Array.isArray(xs) ? xs : []);

const FORCE_KINDS = ['fleet', 'army', 'air'];
const finite = (x) => typeof x === 'number' && Number.isFinite(x);

/** A mandate's text without its closing full stop, with its deadline when the text does not name it. */
function dueText(item) {
  const words = text(item?.text)?.replace(/\.$/, '');
  if (!words) return null;
  const due = text(item.deadline);
  return `${words}${due && !words.includes(due) ? ` (due ${due})` : ''}`;
}

/** The aide's one-line greeting; `day` is the world date in words, or null. */
export function aideGreeting(day) {
  const when = text(day);
  return when
    ? `Welcome to your desk. It is ${when}, and here is where things stand.`
    : 'Welcome to your desk. Here is where things stand.';
}

/**
 * The tray's papers to name on the splash, as `{ id, label }`: the order the tray lists them,
 * no acknowledgements or answers to the seat's orders, the newest of each feed only, at most
 * `PAPERS_MAX`. `label` is "<author>: <title>", or the title alone without an author.
 */
export function openingPapers(documents) {
  const feeds = new Set();
  const out = [];
  for (const d of list(documents)) {
    if (out.length >= PAPERS_MAX) break;
    const title = text(d?.title);
    if (!title || d.ack || d.answer) continue;
    if (d.group != null) {
      if (feeds.has(d.group)) continue;
      feeds.add(d.group);
    }
    const author = text(d.author);
    out.push({ id: d.id, label: author ? `${author}: ${title}` : title });
  }
  return out;
}

/** Every live mandate as "<kind> from <issuer>: <text> (due <deadline>)"; a part it lacks is left out. */
export function openMatters(agenda) {
  return list(agenda?.items).flatMap((item) => {
    const what = dueText(item);
    if (!what) return [];
    const issuer = text(item.issuer);
    const kind = text(item.kind) ?? 'Matter';
    return [`${kind}${issuer ? ` from ${issuer}` : ''}: ${what}`];
  });
}

/**
 * What the seat starts with, for the splash: own forces, the figures on the desk, the first
 * matter, the first papers (`openingPapers`), the open matters (`openMatters`) and the day.
 */
export function startOverview({ map, situation, agenda, documents, clock } = {}) {
  const orders = list(map?.orders);
  const forces = list(map?.marks)
    .filter((m) => m?.side === 'own' && FORCE_KINDS.includes(m.kind) && text(m.name))
    .slice(0, 3)
    .map((m) => {
      const place = text(m.places?.[0]?.name);
      const base = place ? `${m.name}: ${place}` : m.name;
      const order = orders.find((o) => o?.status === 'under_way' && o.mark === m.name && text(o.to?.name));
      return order ? `${base} to ${order.to.name}` : base;
    });
  const figures = list(situation?.figures)
    .filter((f) => text(f?.label) && finite(f.sources?.[0]?.value))
    .slice(0, 3)
    .map((f) => {
      const unit = text(f.unit);
      return `${f.label}: ${f.sources[0].value.toLocaleString('en-US')}${unit ? ` ${unit}` : ''}`;
    });
  const item = list(agenda?.items).find((i) => text(i?.text));
  return {
    forces,
    figures,
    first: item ? dueText(item) : null,
    papers: openingPapers(documents),
    matters: openMatters(agenda),
    day: text(clock?.world_date) ? worldDate(clock.world_date) : null,
  };
}

/**
 * The splash for the seat named `name`, from the desk and the overview:
 * `{ title, office, answersTo, greeting, overview, papers, matters, action }`. `title` is
 * "You are <name>"; `office` the desk's office or null; `answersTo` "Answers to <principals>"
 * or null; `greeting` the aide's line for the day; `overview` `{ forces, figures }` when
 * either has lines, else null; `papers` and `matters` the overview's (may be []). The select
 * card already showed the dossier, so the splash draws none of it.
 */
export function splashModel(name, desk, _dossier, overview = null) {
  const principals = lines(desk?.principals);
  const forces = overview?.forces ?? [];
  const figures = overview?.figures ?? [];
  return {
    title: `You are ${name}`,
    office: text(desk?.office),
    answersTo: principals.length ? `Answers to ${principals.join(', ')}` : null,
    greeting: aideGreeting(overview?.day ?? null),
    overview: forces.length || figures.length ? { forces, figures } : null,
    papers: overview?.papers ?? [],
    matters: overview?.matters ?? [],
    action: TAKE_DESK,
  };
}

/**
 * What to show now for campaign `campaignId`: 'crawl', 'splash' or null. `fresh` is false
 * once the seat has filed an order (an old game gets no intro): then null. The stored value
 * under `INTRO_PREFIX + campaignId` is 'crawl' once the crawl was seen and 'done' once the
 * splash was taken: nothing stored gives 'crawl', 'crawl' gives 'splash', 'done' gives null.
 * A store that throws gives null.
 */
export function introStage(store, campaignId, fresh) {
  if (!store || !fresh) return null;
  try {
    const seen = store.getItem(INTRO_PREFIX + campaignId);
    if (seen === 'done') return null;
    return seen === 'crawl' ? 'splash' : 'crawl';
  } catch {
    return null;
  }
}

/**
 * Record that `stage` ('crawl' or 'splash') was seen: stores 'crawl' or 'done'. Swallows a
 * throwing store. A later Begin must not pull a finished splash back to the crawl.
 */
export function markIntro(store, campaignId, stage) {
  if (!store) return;
  const key = INTRO_PREFIX + campaignId;
  try {
    if (stage === 'splash') store.setItem(key, 'done');
    else if (store.getItem(key) !== 'done') store.setItem(key, 'crawl');
  } catch {
    // a blocked store never blocks the player
  }
}

/** The "How you start" section; each part shows only when it has lines. */
function overviewSection(o) {
  const parts = [];
  if (o.forces.length) parts.push(h('h4', {}, 'Your forces'), h('ul', {}, o.forces.map((x) => h('li', {}, x))));
  if (o.figures.length) parts.push(h('h4', {}, 'On your desk'), h('ul', {}, o.figures.map((x) => h('li', {}, x))));
  return h('section', { class: 'rl-intro-overview', 'aria-labelledby': 'rl-intro-overview-title' },
    h('h3', { id: 'rl-intro-overview-title' }, 'How you start'),
    ...parts);
}

/** The first papers, each title a button that opens the paper. */
function papersSection(papers, open) {
  return h('section', { class: 'rl-intro-papers', 'aria-labelledby': 'rl-intro-papers-title' },
    h('h3', { id: 'rl-intro-papers-title' }, 'Your first papers'),
    h('ul', {}, papers.map((p) => h('li', {},
      h('button', { type: 'button', class: 'rl-intro-paper', onclick: () => open(p) }, p.label)))));
}

function mattersSection(matters) {
  return h('section', { class: 'rl-intro-matters', 'aria-labelledby': 'rl-intro-matters-title' },
    h('h3', { id: 'rl-intro-matters-title' }, 'Open matters'),
    h('ul', {}, matters.map((x) => h('li', {}, x))));
}

/** The aide's greeting, with the wake's brief under it once there is one. */
function greetingBlock(greeting, brief) {
  const summary = text(brief?.summary);
  return aideBriefing({ lead: greeting, lines: summary ? [summary] : [] });
}

/**
 * `<dialog class="rl-intro rl-intro-splash" aria-labelledby="rl-intro-splash-title">` from a
 * `splashModel`: the h2 title (it takes focus when the dialog opens), the office and answers-to lines, the aide's greeting
 * (`aideBriefing`), "How you start", "Your first papers" (each title opens its paper through
 * `onPaper(paper)` after the splash is done), "Open matters", each section only when it has
 * lines, and a primary "Take your desk" button. The button, a paper and Esc call `onDone()`
 * once. `brief()` returns the wake's aide brief or null: while the splash is open it is read
 * every `BRIEF_POLL_MS` until one arrives, and its summary fills in under the greeting.
 */
export function seatSplash({ model, onDone, onPaper, brief } = {}) {
  const m = model ?? {};
  let done = false;
  let timer = null;
  let aide = greetingBlock(m.greeting, brief?.());
  const stop = () => {
    if (timer !== null) clearInterval(timer);
    timer = null;
  };
  const finish = () => {
    if (done) return false;
    done = true;
    stop();
    onDone?.();
    return true;
  };
  const open = (p) => { if (finish()) onPaper?.(p); };
  const dialog = h('dialog', {
    class: 'rl-intro rl-intro-splash',
    'aria-labelledby': 'rl-intro-splash-title',
    oncancel: (e) => { e.preventDefault(); finish(); },
  },
    h('header', { class: 'rl-intro-splash-head' },
      h('h2', { id: 'rl-intro-splash-title', tabindex: '-1', autofocus: true }, m.title ?? '')),
    m.office ? h('p', { class: 'rl-intro-office' }, m.office) : null,
    m.answersTo ? h('p', { class: 'rl-intro-answers' }, m.answersTo) : null,
    aide,
    m.overview ? overviewSection(m.overview) : null,
    m.papers?.length ? papersSection(m.papers, open) : null,
    m.matters?.length ? mattersSection(m.matters) : null,
    h('button', { type: 'button', class: 'rl-intro-take', onclick: finish }, m.action ?? TAKE_DESK));
  if (brief && !aide.querySelector('.rl-brief-lines')) {
    let seen = false;
    timer = setInterval(() => {
      if (dialog.isConnected) seen = true;
      else if (seen) { stop(); return; }
      const b = brief();
      if (!text(b?.summary)) return;
      stop();
      const next = greetingBlock(m.greeting, b);
      aide.before(next);
      aide.remove();
      aide = next;
    }, BRIEF_POLL_MS);
  }
  return dialog;
}
