// The opening on screen: a ready-made game opens on three steps, a nation, then a path, then
// a person, each drawn from the server's `opening` answer. A step with one choice is passed
// over and shown as chosen; a taken person is marked and cannot be taken; the seats left are
// drawn; the client decides nothing. The flat cast stays behind "Show everyone", and is the
// only view for a pitched game.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { api } from '../js/api.js';
import { setFlagIndex } from '../js/flags.js';
import { EVERYONE, NOBODY_LEFT, STEPS_LEAD, openingInto, openingModel, openingView } from '../js/views/realism-opening.js';
import { buttons, installDom, words } from './dom-fake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
const cast = JSON.parse(read('test/fixtures/realism-cast.json'));
const OPENING = cast.opening;
const fresh = () => structuredClone(OPENING);
const byName = (o, name) => o.nations.find((n) => n.name === name);
const KEYS = Object.fromEntries(OPENING.nations.map((n) => [n.key, n.name.toLowerCase().replace(/ /g, '_')]));

function view(opening = fresh(), extra = {}) {
  const doc = installDom();
  const taken = [];
  const read = [];
  const el = openingView({
    opening,
    roster: cast.roster,
    world: 'autumn-1941',
    nationKeys: KEYS,
    onTake: (name) => taken.push(name),
    onRead: (name) => read.push(name),
    ...extra,
  });
  doc.body.append(el);
  return { el, taken, read, doc };
}

const nationButtons = (el) => el.querySelectorAll('button.rl-op-nation');
const pathButtons = (el) => el.querySelectorAll('button.rl-op-path');
const persons = (el) => el.querySelectorAll('.rl-op-person');
const stepNodes = (el) => el.querySelectorAll('.rl-op-step');
const choose = (el, cls, name) => {
  const b = el.querySelectorAll(`button.${cls}`).find((x) => words(x.querySelector('.rl-op-name')) === name);
  assert.ok(b, `${cls} ${name}`);
  b.click();
};

test('a ready-made game opens on the nation step, every nation the server sent, in its order', () => {
  const { el } = view();
  assert.deepEqual(openingModel(fresh()).step, 'nation');
  assert.deepEqual(nationButtons(el).map((b) => words(b.querySelector('.rl-op-name'))), OPENING.nations.map((n) => n.name));
  assert.equal(pathButtons(el).length, 0);
  assert.equal(persons(el).length, 0);
  const usa = nationButtons(el).find((b) => b.getAttribute('aria-label').startsWith('United States'));
  assert.equal(usa.getAttribute('aria-label'), 'United States: 2 to play');
  assert.equal(usa.getAttribute('type'), 'button');
});

test('a nation card draws its people as pips, a taken one hollow, with the count on the mark', () => {
  const { el } = view();
  const japan = nationButtons(el).find((b) => b.getAttribute('aria-label').startsWith('Japan'));
  assert.equal(japan.getAttribute('aria-label'), 'Japan: 1 to play');
  const pips = japan.querySelectorAll('.rl-op-pip');
  assert.equal(pips.length, 2);
  assert.equal(pips.filter((p) => p.classList.contains('on')).length, 1);
  assert.match(words(japan), /1 to play/);
});

test('a nation card carries its flag from the world and nation keys', () => {
  setFlagIndex({ 'autumn-1941': { united_states: 'usa.svg' } });
  try {
    const { el } = view();
    const usa = nationButtons(el).find((b) => b.getAttribute('aria-label').startsWith('United States'));
    const flag = usa.querySelector('.flag');
    assert.ok(flag, 'a flag box');
    assert.equal(flag.getAttribute('data-nation'), 'united_states');
    assert.equal(flag.querySelector('img').getAttribute('src'), '/assets/flags/usa.svg');
    const china = nationButtons(el).find((b) => b.getAttribute('aria-label').startsWith('China'));
    assert.ok(china.querySelector('.flag.flag-plain'), 'no file: the plain block');
  } finally {
    setFlagIndex(null);
  }
});

test('choosing a nation opens its paths, and choosing a path its persons', () => {
  const { el } = view();
  choose(el, 'rl-op-nation', 'United States');
  assert.equal(nationButtons(el).length, 0);
  assert.deepEqual(pathButtons(el).map((b) => words(b.querySelector('.rl-op-name'))), ['Political', 'Military']);
  assert.equal(pathButtons(el)[1].getAttribute('aria-label'), 'Military: 1 to play');
  choose(el, 'rl-op-path', 'Military');
  assert.equal(pathButtons(el).length, 0);
  assert.deepEqual(persons(el).map((p) => words(p.querySelector('.rl-op-who'))), ['Ernest J. King']);
});

test('a person card shows the office and the pitch, and Take this seat runs the claim by name', () => {
  const { el, taken } = view();
  choose(el, 'rl-op-nation', 'United States');
  choose(el, 'rl-op-path', 'Political');
  const [fdr] = persons(el);
  assert.equal(words(fdr.querySelector('.rl-op-office')), 'President of the United States');
  assert.equal(words(fdr.querySelector('.rl-op-pitch')), 'Third-term President steering a neutral nation toward the Allies.');
  assert.equal(words(fdr.querySelector('.rl-op-reach')), 'The Navy, the radio, and what Congress will pass.');
  assert.equal(fdr.querySelector('.rl-op-taken'), null);
  assert.equal(fdr.querySelector('img').getAttribute('src'), '/assets/portraits/roosevelt.jpg');
  const [take] = buttons(fdr, 'Take this seat');
  assert.equal(take.getAttribute('aria-label'), 'Take this seat: Franklin D. Roosevelt');
  take.click();
  assert.deepEqual(taken, ['Franklin D. Roosevelt']);
});

test('a person on the roster can be read first; one with no dossier draws initials', () => {
  const { el, read: opened } = view();
  choose(el, 'rl-op-nation', 'United States');
  choose(el, 'rl-op-path', 'Political');
  buttons(persons(el)[0], 'Read the dossier')[0].click();
  assert.deepEqual(opened, ['Franklin D. Roosevelt']);
  buttons(el, '‹ Path')[0].click();
  buttons(el, '‹ Nations')[0].click();
  choose(el, 'rl-op-nation', 'China');
  const [chiang] = persons(el);
  assert.equal(words(chiang.querySelector('.rl-op-mono')), 'CK');
  assert.equal(buttons(chiang, 'Read the dossier').length, 0, 'off the roster: nothing to read');
});

test('a taken person is marked taken and has no way to take him; the free one beside him has', () => {
  const { el, taken } = view();
  choose(el, 'rl-op-nation', 'Japan');
  const cards = persons(el);
  const konoe = cards.find((p) => words(p.querySelector('.rl-op-who')) === 'Fumimaro Konoe');
  const tojo = cards.find((p) => words(p.querySelector('.rl-op-who')) === 'Hideki Tojo');
  assert.equal(words(konoe.querySelector('.rl-op-taken')), 'Taken');
  assert.ok(konoe.classList.contains('taken'));
  assert.equal(buttons(konoe, 'Take this seat').length, 0);
  assert.equal(konoe.querySelectorAll('button').filter((b) => /take/i.test(words(b))).length, 0);
  buttons(tojo, 'Take this seat')[0].click();
  assert.deepEqual(taken, ['Hideki Tojo']);
});

test('a nation with one path passes over the path step and shows it as already chosen', () => {
  const { el } = view();
  choose(el, 'rl-op-nation', 'China');
  assert.equal(pathButtons(el).length, 0, 'no path to choose');
  assert.deepEqual(persons(el).map((p) => words(p.querySelector('.rl-op-who'))), ['Chiang Kai-shek']);
  const path = stepNodes(el)[1];
  assert.equal(words(path), '2. Path: Political (the only one)');
  assert.notEqual(path.tagName, 'BUTTON', 'a passed step is not a choice');
  assert.ok(path.classList.contains('fixed'));
  assert.deepEqual(el.querySelectorAll('button.rl-op-back').map(words), ['‹ Nations']);
  const m = openingModel(fresh(), { nation: byName(OPENING, 'China').key });
  assert.equal(m.step, 'person');
  assert.equal(m.pathFixed, true);
});

test('a game with one nation passes over the nation step too', () => {
  const one = fresh();
  one.nations = [byName(one, 'United States')];
  const { el } = view(one);
  assert.equal(nationButtons(el).length, 0);
  assert.equal(pathButtons(el).length, 2);
  const nation = stepNodes(el)[0];
  assert.equal(words(nation), '1. Nation: United States (the only one)');
  assert.notEqual(nation.tagName, 'BUTTON');
  assert.equal(el.querySelectorAll('button.rl-op-back').length, 0, 'nothing to go back to');
  choose(el, 'rl-op-path', 'Political');
  assert.deepEqual(el.querySelectorAll('button.rl-op-back').map(words), ['‹ Path']);
});

test('a chosen step is a button that goes back to it; the step being chosen is marked current', () => {
  const { el } = view();
  choose(el, 'rl-op-nation', 'United States');
  choose(el, 'rl-op-path', 'Political');
  const [nation, path, person] = stepNodes(el);
  assert.equal(nation.tagName, 'BUTTON');
  assert.equal(words(nation), '1. Nation: United States');
  assert.equal(words(path), '2. Path: Political');
  assert.equal(person.getAttribute('aria-current'), 'step');
  assert.equal(words(person), '3. Person');
  path.click();
  assert.equal(pathButtons(el).length, 2);
  assert.equal(stepNodes(el)[1].getAttribute('aria-current'), 'step');
  buttons(el, '‹ Nations')[0].click();
  assert.equal(nationButtons(el).length, OPENING.nations.length);
});

test('after a choice the focus moves to the first choice of the next step', () => {
  const { el, doc } = view();
  choose(el, 'rl-op-nation', 'United States');
  assert.equal(doc.activeElement, pathButtons(el)[0]);
  choose(el, 'rl-op-path', 'Political');
  assert.equal(words(doc.activeElement), 'Take this seat');
});

test('the seats left are drawn as a meter of pips with the number on it', () => {
  const { el } = view();
  const meter = el.querySelector('.rl-op-seats');
  assert.equal(meter.getAttribute('role'), 'meter');
  assert.equal(meter.getAttribute('aria-valuenow'), '9');
  assert.equal(meter.getAttribute('aria-valuemax'), '10');
  assert.equal(meter.getAttribute('aria-valuemin'), '0');
  const pips = meter.querySelectorAll('.rl-op-seat');
  assert.equal(pips.length, 10);
  assert.equal(pips.filter((p) => p.classList.contains('on')).length, 9);
  assert.equal(words(meter), '9 of 10 seats left');
  const none = fresh();
  none.seats_left = 0;
  const { el: full } = view(none);
  assert.equal(words(full.querySelector('.rl-op-seats')), 'No seats left');
});

test('the client decides nothing: a nation whose people are all taken is listed as the server sent it', () => {
  const o = fresh();
  for (const p of byName(o, 'Japan').paths[0].persons) p.taken = true;
  const { el } = view(o);
  const japan = nationButtons(el).find((b) => b.getAttribute('aria-label').startsWith('Japan'));
  assert.equal(japan.getAttribute('aria-label'), 'Japan: all taken');
  japan.click();
  assert.equal(el.querySelectorAll('button').filter((b) => words(b) === 'Take this seat').length, 0);
  assert.equal(persons(el).length, 2);
});

test('a path with no post and a nation with no key are named, not dropped', () => {
  const o = fresh();
  o.nations.push({ key: null, name: 'Without a nation', paths: [{ path: null, persons: [{ name: 'A Clerk', office: '', pitch: '', taken: false }] }] });
  const { el } = view(o);
  choose(el, 'rl-op-nation', 'Without a nation');
  assert.equal(words(stepNodes(el)[1]), '2. Path: Without a post (the only one)');
  assert.deepEqual(persons(el).map((p) => words(p.querySelector('.rl-op-who'))), ['A Clerk']);
});

test('an opening with nobody to take says so', () => {
  const { el } = view({ nations: [], seats_left: 3, seats_max: 10 });
  assert.equal(words(el.querySelector('.rl-op-none')), NOBODY_LEFT);
});

test('text from the server goes in as text', () => {
  const o = fresh();
  byName(o, 'China').paths[0].persons[0].pitch = '<img src=x onerror=alert(1)>';
  const { el } = view(o);
  choose(el, 'rl-op-nation', 'China');
  assert.equal(words(el.querySelector('.rl-op-pitch')), '<img src=x onerror=alert(1)>');
  assert.equal(el.querySelector('.rl-op-pitch').querySelectorAll('img').length, 0);
});

async function into(answer) {
  const doc = installDom();
  const was = api.newGame;
  const posted = [];
  const holder = doc.createElement('div');
  const flat = doc.createElement('div');
  const pitched = [];
  flat.setAttribute('hidden', ''); // as the cast screen holds it while the opening is read
  doc.body.append(holder, flat);
  try {
    api.newGame = async (action, body) => {
      posted.push([action, body]);
      if (answer instanceof Error) throw answer;
      return answer;
    };
    await openingInto(holder, flat, { roster: cast.roster, onTake() {}, onRead() {}, onPitched: () => pitched.push(1) });
  } finally {
    api.newGame = was;
  }
  return { holder, flat, posted, pitched };
}

test('a ready-made game shows the three steps and keeps the flat cast behind Show everyone', async () => {
  const { holder, flat, posted, pitched } = await into({ reply: '', refused: false, opening: fresh(), ready_made: true, world: 'autumn-1941', nation_keys: KEYS });
  assert.deepEqual(posted, [['opening', {}]]);
  assert.ok(holder.querySelector('.rl-op'));
  assert.ok(flat.hasAttribute('hidden'));
  assert.deepEqual(pitched, [], 'a ready-made game lists nobody beyond its world');
  const [show] = buttons(holder, EVERYONE);
  assert.equal(show.getAttribute('aria-expanded'), 'false');
  show.click();
  assert.ok(!flat.hasAttribute('hidden'));
  assert.equal(show.getAttribute('aria-expanded'), 'true');
  show.click();
  assert.ok(flat.hasAttribute('hidden'));
});

test('a pitched game, a refusal or a failure keeps the flat cast as the only view', async () => {
  for (const answer of [
    { reply: '', refused: false, opening: fresh(), ready_made: false },
    { reply: 'This game is not choosing its people.', refused: true },
    new Error('The game server didn\'t respond.'),
  ]) {
    const { holder, flat, pitched } = await into(answer);
    assert.equal(holder.querySelector('.rl-op'), null);
    assert.equal(buttons(holder, EVERYONE).length, 0);
    assert.ok(!flat.hasAttribute('hidden'));
    assert.deepEqual(pitched, [1], 'who held power stays where it was');
  }
});

test('the cast screen asks for the opening only while the seat holds nobody', () => {
  const src = uncomment(read('js/views/realism-cast.js'));
  assert.match(src, /import \{ openingInto \} from '\.\/realism-opening\.js';/);
  assert.match(src, /if \(!mine\) \{\s*steps\.append\([^\n]*\);\s*openingInto\(steps, flat, \{/);
  assert.match(src, /hidden: !mine/);
  assert.match(src, /onPitched: \(\) =>/);
});

test('the opening stylesheet is linked and takes its colours from the tokens alone', () => {
  assert.match(read('index.html'), /<link rel="stylesheet" href="\/css\/p5-opening\.css">/);
  const css = uncomment(read('css/p5-opening.css'));
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/);
  assert.match(css, /prefers-reduced-motion/);
  const js = uncomment(read('js/views/realism-opening.js'));
  assert.doesNotMatch(js, /innerHTML|#[0-9a-fA-F]{6}\b/);
});

test('api.newGame names the opening among its actions', () => {
  assert.match(read('js/api.js'), /A new realism game: [^\n]*\bopening\b/);
});

test('no step leaves a stray word where a part is left out', () => {
  const { el } = view();
  const clean = () => assert.doesNotMatch(words(el), /\b(null|undefined)\b/);
  clean();
  choose(el, 'rl-op-nation', 'United States');
  clean();
  choose(el, 'rl-op-path', 'Political');
  clean();
  buttons(el, '‹ Path')[0].click();
  buttons(el, '‹ Nations')[0].click();
  choose(el, 'rl-op-nation', 'China');
  clean();
});

test('the steps set the screen\'s lead line and load the flags before they draw', async () => {
  const doc = installDom();
  const was = api.newGame;
  const wasFetch = globalThis.fetch;
  const fetched = [];
  const lead = doc.createElement('p');
  lead.textContent = 'Open a card to read who they are, then play them.';
  const holder = doc.createElement('div');
  const flat = doc.createElement('div');
  try {
    globalThis.fetch = async (url) => { fetched.push(url); return { ok: true, json: async () => ({ 'autumn-1941': { united_states: 'usa.svg' } }) }; };
    api.newGame = async () => ({ reply: '', refused: false, opening: fresh(), ready_made: true, world: 'autumn-1941', nation_keys: KEYS });
    await openingInto(holder, flat, { roster: cast.roster, lead, onTake() {}, onRead() {}, onPitched() {} });
  } finally {
    api.newGame = was;
    globalThis.fetch = wasFetch;
    setFlagIndex(null);
  }
  assert.equal(words(lead), STEPS_LEAD);
  assert.deepEqual(fetched, ['/assets/flags/index.json']);
  const usa = holder.querySelectorAll('button.rl-op-nation').find((b) => b.getAttribute('aria-label').startsWith('United States'));
  assert.equal(usa.querySelector('img').getAttribute('src'), '/assets/flags/usa.svg');
});
