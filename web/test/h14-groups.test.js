// The sheets in four groups, and forms from what they act on (SHG), one test or more per rule:
// 1. in the map-first room the bar's sheet tabs are four, Inbox (Papers, Press), Orders (Write,
// Sent), People (Roster, Court) and World (Nations, Standing, Home, Diplomacy), each opening one
// sheet with its parts as inner tabs, on the part last open; 2. Messages is a chat button on the
// bar with its unread count; 3. a group's count is the sum of its parts' counts; 4. the Write part
// holds the free-writing form and a search over the standing forms by name; 5. a form opens from
// what it acts on: a piece's sheet, a person's card, a nation's card; 6. a line of "What needs
// you" or a paper that names one of the old sheets opens its group at that part. Keeps: the
// Classic layout keeps its own tabs. Mutants: a part unreachable; a group's count missing a part;
// a form from a piece opening empty.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, fire, installDom, words } from './dom-fake.js';

Object.defineProperty(Object.getPrototypeOf(installDom().createElement('div')), 'hidden', {
  configurable: true,
  get() { return this.hasAttribute('hidden'); },
  set(on) { this.toggleAttribute('hidden', Boolean(on)); },
});
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { realismRoom, uiFor } = await import('../js/views/realism-room.js');
const { forgetShapes } = await import('../js/views/realism-theatre.js');
const { openSheet, setRoomLayout } = await import('../js/views/realism-sheets.js');
const { addNeedKind } = await import('../js/views/realism-needs.js');
const groups = await import('../js/views/realism-groups.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const settle = () => new Promise((r) => setTimeout(r, 0));

/** The seat's view on the toy board, with the home front, agreements and economy; `change` edits it. */
function seat(change = () => {}) {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.documents = structuredClone(fixture.listing);
  rv.wake_tick = 1;
  rv.style = 'free';
  rv.locks = null;
  rv.battles = [];
  change(rv);
  return rv;
}

/** The whole room for view `rv` in `layout`, as the page draws it; `now()` is the room after a re-read. */
async function room(rv = seat(), layout = 'map', id = `h14-${Math.random()}`) {
  const doc = installDom();
  setRoomLayout(layout);
  forgetShapes();
  const calls = [];
  api.realism = async (action, body) => {
    calls.push([action, body]);
    return action === 'map' ? { reply: '', refused: false, file: fixture.territory_map.file, map: SHAPES } : {};
  };
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const game = { id, name: 'Autumn 1941', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {}, signOut: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  await settle();
  await settle();
  return { root, id, calls, now: () => doc.body.firstElementChild };
}

const key = (el, k) => el.dispatchEvent({
  type: 'keydown', key: k, target: null, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {},
});
const bar = (root) => root.querySelector('.rl-roombar');
const groupTabs = (root) => root.querySelectorAll('.rl-sheettabs button');
const groupTab = (root, g) => groupTabs(root).find((b) => b.getAttribute('data-group') === g);
const over = (root) => root.querySelector('.rl-over');
const openPart = (root) => over(root)?.getAttribute('data-sheet') ?? null;
const partTabs = (root) => over(root)?.querySelectorAll('.rl-parts button') ?? [];
const partTab = (root, part) => partTabs(root).find((b) => b.getAttribute('data-sheet') === part);
const pressed = (root) => partTabs(root).filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.getAttribute('data-sheet'));
const countOf = (el) => (el.querySelector('.rl-tab-count') ? Number(words(el.querySelector('.rl-tab-count'))) : 0);

// rule 1: four groups, each one sheet with its parts as inner tabs, on the part last open

test('the bar\'s sheet tabs are the four groups, in order, and no Nations control', async () => {
  const { root } = await room();
  assert.deepEqual(groupTabs(root).map((b) => b.getAttribute('data-group')), ['inbox', 'orders', 'people', 'world']);
  assert.deepEqual(groupTabs(root).map((b) => words(b).replace(/ \d+$/, '')), ['Inbox', 'Orders', 'People', 'World']);
  assert.equal(bar(root).querySelector('.rl-nations-btn'), null, 'the Nations part of World replaces the control');
  assert.equal(groupTabs(root).filter((b) => /Messages/.test(words(b))).length, 0, 'Messages is not a group');
});

test('each group opens one sheet named for it, with its parts as inner tabs; every part is reachable', async () => {
  const { root } = await room();
  const inside = {
    papers: '.rl-tray', press: '.rl-pd-body', forms: '.rl-write', orders: '.rl-oc',
    people: '.rl-people', court: '.rl-court', nations: '.rl-nations-body', standing: '.rl-sg', home: '.rl-home-sheet', diplomacy: '.rl-dp-builder',
  };
  const seen = [];
  for (const [g, label, parts] of [['inbox', 'Inbox', ['papers', 'press']], ['orders', 'Orders', ['forms', 'orders']],
    ['people', 'People', ['people', 'court']], ['world', 'World', ['nations', 'standing', 'home', 'diplomacy']]]) {
    groupTab(root, g).click();
    assert.equal(root.querySelectorAll('.rl-over').length, 1, `one sheet for ${g}`);
    assert.equal(words(over(root).querySelector('.rl-over-title')), label);
    assert.deepEqual(partTabs(root).map((b) => b.getAttribute('data-sheet')), parts, `${g}'s parts`);
    assert.equal(groupTab(root, g).getAttribute('aria-expanded'), 'true');
    for (const part of parts) {
      partTab(root, part).click();
      assert.equal(openPart(root), part);
      assert.deepEqual(pressed(root), [part]);
      assert.ok(over(root).querySelector('.rl-over-body').querySelector(inside[part]), `${part} holds ${inside[part]}`);
      assert.equal(words(over(root).querySelector('.rl-over-title')), label, 'the sheet keeps the group\'s name');
      seen.push(part);
    }
  }
  assert.equal(seen.length, 10);
});

test('the parts\' words are the group\'s own: Write and Sent, Roster and Court', async () => {
  const { root } = await room();
  groupTab(root, 'orders').click();
  assert.deepEqual(partTabs(root).map((b) => words(b).replace(/ \d+$/, '')), ['Write', 'Sent']);
  groupTab(root, 'people').click();
  assert.deepEqual(partTabs(root).map((b) => words(b).replace(/ \d+$/, '')), ['Roster', 'Court']);
});

test('a group opens on the part last open in it', async () => {
  const { root } = await room();
  groupTab(root, 'inbox').click();
  assert.equal(openPart(root), 'papers', 'first time: the first part');
  partTab(root, 'press').click();
  groupTab(root, 'inbox').click();
  assert.equal(over(root), null, 'its own tab closes it');
  groupTab(root, 'orders').click();
  partTab(root, 'orders').click();
  groupTab(root, 'inbox').click();
  assert.equal(openPart(root), 'press');
  groupTab(root, 'orders').click();
  assert.equal(openPart(root), 'orders');
});

test('a part with nothing to hold is left off: no Diplomacy in a game with no agreements', async () => {
  const { root } = await room(seat((r) => { delete r.agreements; delete r.conferences; }));
  groupTab(root, 'world').click();
  assert.deepEqual(partTabs(root).map((b) => b.getAttribute('data-sheet')), ['nations', 'standing', 'home']);
});

test('Escape closes a group\'s sheet and focus goes back to the group\'s tab, after a part was picked', async () => {
  const { root } = await room();
  groupTab(root, 'people').focus();
  groupTab(root, 'people').click();
  partTab(root, 'court').click();
  assert.equal(document.activeElement, partTab(root, 'court'), 'focus stays on the part picked');
  key(over(root), 'Escape');
  assert.equal(over(root), null);
  assert.equal(document.activeElement, groupTab(root, 'people'));
});

test('a part opened from inside another sheet gives focus back to its own group\'s tab', async () => {
  const { root } = await room();
  groupTab(root, 'world').click();
  partTab(root, 'home').click();
  buttons(over(root), 'Speak to the nation')[0].click();
  assert.equal(openPart(root), 'forms');
  key(over(root), 'Escape');
  assert.equal(over(root), null);
  assert.equal(document.activeElement, groupTab(root, 'orders'));
});

test('the Classic layout keeps its own tabs', async () => {
  const { root } = await room(seat(), 'room');
  assert.equal(root.querySelector('.rl-sheettabs'), null);
  assert.equal(root.querySelector('.rl-chat-btn'), null);
  assert.ok(root.querySelector('.rl-tabbar'), 'today\'s tab bar');
  setRoomLayout('map');
});

// rule 2: Messages is a chat button on the bar, with its unread count

test('the chat button on the bar opens the messenger, and Escape gives focus back to it', async () => {
  const { root } = await room();
  const chat = bar(root).querySelector('.rl-chat-btn');
  assert.ok(chat, 'a chat button on the bar');
  assert.match(chat.getAttribute('aria-label'), /^Messages/);
  assert.equal(chat.getAttribute('aria-expanded'), 'false');
  chat.focus();
  chat.click();
  assert.equal(openPart(root), 'messages');
  assert.ok(over(root).querySelector('.rl-msgr-panel'), 'the messenger');
  assert.equal(partTabs(root).length, 0, 'the messenger has no inner tabs');
  assert.equal(bar(root).querySelector('.rl-chat-btn').getAttribute('aria-expanded'), 'true');
  key(over(root), 'Escape');
  assert.equal(over(root), null);
  assert.equal(document.activeElement, bar(root).querySelector('.rl-chat-btn'));
});

test('the chat button carries the unread count, in its accessible name and on its badge', async () => {
  const { root } = await room();
  const chat = bar(root).querySelector('.rl-chat-btn');
  const n = countOf(chat);
  assert.ok(n > 0, 'the fixture has an unread message');
  assert.equal(chat.getAttribute('aria-label'), `Messages, ${n} unread`);
});

// rule 3: a group's count is the sum of its parts' counts

test('Inbox counts the unread papers and the unread press together, and each part shows its own', async () => {
  const { root } = await room();
  groupTab(root, 'inbox').click();
  const papers = countOf(partTab(root, 'papers'));
  const press = countOf(partTab(root, 'press'));
  assert.ok(papers > 0 && press > 0, 'both parts have something unread');
  assert.equal(countOf(groupTab(root, 'inbox')), papers + press);
});

test('groups.groupCount sums every drawn part and nothing else', () => {
  const g = groups.GROUPS.find((x) => x.key === 'world');
  assert.equal(groups.groupCount(g, { nations: 1, home: 2, diplomacy: 4, papers: 8 }, ['nations', 'home', 'diplomacy']), 7);
  assert.equal(groups.groupCount(g, { home: 2, diplomacy: 4 }, ['home']), 2, 'a part left off is not counted');
});

test('on Beginner a line in Diplomacy marks the part and the World group', async () => {
  const rv = seat((r) => {
    r.style = 'beginner';
    r.home = { ...r.home, chambers: [] };
    r.agenda = { ...r.agenda, items: [{ id: 'V1', kind: 'Vote', text: 'Vote on the text.', issuer: 'The chair', issued: '1941-10-01', deadline: '1941-10-20', options: [] }] };
    r.orders = { orders: r.orders.orders.map((o) => ({ ...o, decision_needed: false })) };
  });
  const { root } = await room(rv);
  assert.equal(countOf(groupTab(root, 'world')), 1);
  groupTab(root, 'world').click();
  assert.equal(countOf(partTab(root, 'diplomacy')), 1);
});

// rule 4: the Write part holds the free-writing form and a search over the standing forms

test('the Write part holds the free-writing form, then a search over the standing forms', async () => {
  const { root } = await room();
  groupTab(root, 'orders').click();
  const body = over(root).querySelector('.rl-over-body');
  assert.ok(body.querySelector('.rl-write textarea'), 'the free-writing form');
  const search = body.querySelector('input[type="search"]');
  assert.ok(search, 'a search field');
  assert.ok(search.getAttribute('aria-label') || search.closest('label'), 'the search is named');
  assert.equal(body.querySelectorAll('.rl-instrument').length, fixture.desk.levers.length, 'every form, before a search');
});

test('typing in the search keeps the forms whose names match, and a form picked there opens as today', async () => {
  const { root } = await room();
  groupTab(root, 'orders').click();
  const search = () => over(root).querySelector('input[type="search"]');
  search().value = 'lend';
  fire(search(), 'input');
  const shown = () => over(root).querySelectorAll('.rl-instrument').filter((i) => !i.hidden).map((i) => i.getAttribute('data-lever'));
  assert.deepEqual(shown(), ['lend_lease_finding']);
  search().value = 'PATROL';
  fire(search(), 'input');
  assert.deepEqual(shown(), ['patrol'], 'case does not matter');
  const item = over(root).querySelector('.rl-instrument[data-lever="patrol"]');
  item.querySelector('[aria-expanded]').click();
  assert.equal(item.querySelector('[aria-expanded]').getAttribute('aria-expanded'), 'true');
  assert.ok(item.querySelector('select[name="intel"]'), 'its fields');
  search().value = 'nothing like it';
  fire(search(), 'input');
  assert.deepEqual(shown(), []);
  assert.ok(words(over(root)).includes('No form is called that'), 'a line says so');
});

test('the search is kept over a redraw', async () => {
  const { root } = await room();
  groupTab(root, 'orders').click();
  const search = () => over(root).querySelector('input[type="search"]');
  search().value = 'fleet';
  fire(search(), 'input');
  groupTab(root, 'inbox').click();
  groupTab(root, 'orders').click();
  assert.equal(search().value, 'fleet');
  assert.deepEqual(over(root).querySelectorAll('.rl-instrument').filter((i) => !i.hidden).map((i) => i.getAttribute('data-lever')), ['move_fleet']);
});

test('groups.matchForms matches a form\'s name or label, and an empty search matches every form', () => {
  const levers = [{ name: 'patrol', label: 'Send a patrol' }, { name: 'conceal', label: 'Conceal a force' }];
  assert.deepEqual([...groups.matchForms(levers, '')], ['patrol', 'conceal']);
  assert.deepEqual([...groups.matchForms(levers, ' force ')], ['conceal']);
  assert.deepEqual([...groups.matchForms(levers, 'patrol')], ['patrol']);
});

// rule 5: a form opens from what it acts on

/** The seat with a form that takes a piece by the Norra Levy's name, beside the fixture's forms. */
const withPieceForm = () => seat((r) => {
  r.desk = { ...r.desk, levers: [...r.desk.levers, {
    name: 'stand_down', label: 'Stand a force down', pipeline: null,
    params: [{ name: 'piece', kind: 'enum', label: 'Force', choices: [{ value: 'other', label: 'Norra Kites' }, { value: 'levy', label: 'Norra Levy' }] }],
  }] };
});

test('a piece\'s sheet lists the forms that take it, each open with the piece filled in', async () => {
  const { root } = await room(withPieceForm());
  const markOf = () => root.querySelectorAll('.rl-mapfirst g[data-stack]').find((m) => (m.getAttribute('aria-label') ?? '').startsWith('The Norra Levy'));
  if (!markOf()) root.querySelectorAll('.rl-mapfirst g[data-count]').find((g) => (g.getAttribute('aria-label') ?? '').includes('The Norra Levy'))?.click();
  markOf().click();
  assert.equal(openPart(root), 'piece');
  const item = over(root).querySelector('.rl-piece-forms .rl-instrument[data-lever="stand_down"]');
  assert.ok(item, 'the form that takes the piece');
  assert.equal(item.querySelector('[aria-expanded]').getAttribute('aria-expanded'), 'true', 'open');
  assert.equal(item.querySelector('select[name="piece"]').value, 'levy', 'with the piece filled in');
  assert.equal(over(root).querySelector('.rl-piece-forms .rl-instrument[data-lever="patrol"]'), null, 'a form that cannot take it is not listed');
});

test('groups.formsTaking matches a piece by its name, with or without "The"', () => {
  const levers = withPieceForm().desk.levers;
  assert.deepEqual(groups.formsTaking(levers, { name: 'The Norra Levy', side: 'own' }).map((f) => [f.lever.name, f.param, f.value]), [['stand_down', 'piece', 'levy']]);
  assert.deepEqual(groups.formsTaking(levers, { name: 'The Norra Levy', side: 'enemy' }), [], 'not another side\'s piece');
  assert.deepEqual(groups.formsTaking(levers, { name: 'The Norra Levy', side: 'own' }, new Set(['stand_down'])), [], 'a form already shown is skipped');
});

/** The seat with Anthony Eden, of the seat's own people, in reach by letter. */
const withEden = (channels = ['Letter'], keys = ['letter']) => seat((r) => {
  r.reach = { ...r.reach, inner_circle: [...r.reach.inner_circle, { name: 'Anthony Eden', title: 'Foreign Secretary', channels, powers: [], channel_keys: keys }] };
});

/** People, Roster, the seat's own people, then Anthony Eden's card. */
function edenCard(root) {
  groupTab(root, 'people').click();
  over(root).querySelectorAll('.rl-people .seg button').find((b) => words(b).startsWith('Your people')).click();
  over(root).querySelectorAll('.rl-pp-row').find((b) => words(b.querySelector('.rl-pp-name')) === 'Anthony Eden').click();
  return root.querySelector('dialog.rl-fc');
}

test('a person\'s card has Ask a question and Write an order', async () => {
  const { root } = await room(withEden());
  const card = edenCard(root);
  assert.ok(card, 'the card');
  assert.deepEqual(card.querySelectorAll('.rl-person-moves button').map(words), ['Ask a question', 'Write an order']);
});

test('Write an order on a person\'s card opens Orders at Write, addressed to them', async () => {
  const { root, id } = await room(withEden());
  buttons(edenCard(root), 'Write an order')[0].click();
  assert.equal(root.querySelector('dialog.rl-fc'), null, 'the card closes');
  assert.equal(openPart(root), 'forms');
  assert.equal(words(over(root).querySelector('.rl-over-title')), 'Orders');
  assert.equal(uiFor(id).orderTo?.name, 'Anthony Eden');
  const to = over(root).querySelectorAll('.rl-write input[type="radio"]').find((r) => r.checked);
  assert.equal(to?.value, 'Anthony Eden', 'the order is addressed to them');
  assert.equal(document.activeElement, over(root).querySelector('.rl-write textarea'));
});

test('Ask a question on a person\'s card opens the messenger on their thread', async () => {
  const { root, id } = await room(withEden());
  buttons(edenCard(root), 'Ask a question')[0].click();
  assert.equal(openPart(root), 'messages');
  assert.equal(uiFor(id).chat.thread, 'Anthony Eden');
});

test('a person the seat cannot reach has neither, and says so', async () => {
  const { root } = await room();
  groupTab(root, 'people').click();
  over(root).querySelectorAll('.rl-pp-row')[0].click();
  const card = root.querySelector('dialog.rl-fc');
  assert.deepEqual(card.querySelectorAll('.rl-person-moves button').map(words), []);
  assert.ok(words(card.querySelector('.rl-person-moves')).includes('You cannot reach them from here.'));
});

/** World, Nations, then another nation's card from its row in the chart. */
function sudlandCard(root) {
  groupTab(root, 'world').click();
  partTab(root, 'nations').click();
  over(root).querySelectorAll('button.rl-nb-row').find((b) => b.getAttribute('aria-label').startsWith('Sudland')).click();
  return over(root).querySelector('.rl-nb-card');
}

test('a nation\'s card has Make an offer, which opens World at Diplomacy with that nation filled in', async () => {
  const { root } = await room();
  const card = sudlandCard(root);
  assert.ok(card, 'Sudland\'s card');
  buttons(card, 'Make an offer')[0].click();
  assert.equal(openPart(root), 'diplomacy');
  assert.deepEqual(pressed(root), ['diplomacy']);
  const sudland = fixture.economy.figures.find((f) => f.nation.name === 'Sudland').nation.key;
  const checked = over(root).querySelectorAll('.rl-dp-builder input[type="checkbox"]').filter((i) => i.checked).map((i) => i.value);
  assert.deepEqual(checked, [sudland]);
  assert.equal(document.activeElement, over(root).querySelector('.rl-dp-builder textarea'));
});

test('a game with no agreements has no Make an offer on a nation\'s card', async () => {
  const { root } = await room(seat((r) => { delete r.agreements; }));
  assert.equal(buttons(sudlandCard(root), 'Make an offer').length, 0);
});

// rule 6: a line or a paper that names an old sheet opens its group at that part

test('the seat\'s order waiting on it opens Orders at Sent', async () => {
  const { root } = await room();
  root.querySelectorAll('.rl-needs .rl-need').find((l) => l.getAttribute('data-kind') === 'order').querySelector('.rl-need-act').click();
  assert.equal(openPart(root), 'orders');
  assert.equal(words(over(root).querySelector('.rl-over-title')), 'Orders');
  assert.deepEqual(pressed(root), ['orders']);
  assert.equal(groupTab(root, 'orders').getAttribute('aria-expanded'), 'true');
});

test('a conference vote opens World at Diplomacy', async () => {
  const { root } = await room(seat((r) => {
    r.agenda = { ...r.agenda, items: [{ id: 'V1', kind: 'Vote', text: 'Vote on the text.', issuer: 'The chair', issued: '1941-10-01', deadline: '1941-10-20', options: [] }] };
  }));
  root.querySelectorAll('.rl-needs .rl-need-act').find((b) => b.getAttribute('data-need') === 'V1').click();
  assert.equal(openPart(root), 'diplomacy');
  assert.equal(words(over(root).querySelector('.rl-over-title')), 'World');
  assert.deepEqual(pressed(root), ['diplomacy']);
});

test('a line that names any of the old sheets opens its group at that part', async () => {
  const parts = { papers: 'Inbox', press: 'Inbox', forms: 'Orders', orders: 'Orders', people: 'People', court: 'People', nations: 'World', home: 'World', diplomacy: 'World' };
  const off = addNeedKind('test-parts', () => Object.keys(parts).map((sheet) => ({
    key: `to-${sheet}`, label: 'Test', what: `Open ${sheet}.`, from: 'a test', due: null, arrived: null, action: { word: 'Open', to: 'sheet', sheet },
  })));
  try {
    const { root } = await room();
    for (const [sheet, label] of Object.entries(parts)) {
      root.querySelectorAll('.rl-needs .rl-need-act').find((b) => b.getAttribute('data-need') === `to-${sheet}`).click();
      assert.equal(openPart(root), sheet);
      assert.equal(words(over(root).querySelector('.rl-over-title')), label, `${sheet} opens ${label}`);
      assert.deepEqual(pressed(root), [sheet]);
      over(root).querySelector('.rl-over-close').click();
    }
  } finally { off(); }
});

test('opening a part from anywhere makes it the part its group opens on next', async () => {
  const ui = { chat: {}, press: {} };
  openSheet(ui, 'press');
  openSheet(ui, 'home');
  openSheet(ui, 'messages');
  assert.deepEqual(ui.parts, { inbox: 'press', world: 'home' });
});

test('groups.groupOf names the group of every old sheet, and of nothing else', () => {
  const of = (k) => groups.groupOf(k)?.key ?? null;
  assert.deepEqual(['papers', 'press', 'forms', 'orders', 'people', 'court', 'nations', 'standing', 'home', 'diplomacy'].map(of),
    ['inbox', 'inbox', 'orders', 'orders', 'people', 'people', 'world', 'world', 'world', 'world']);
  for (const k of ['messages', 'piece', 'needs', 'matter', 'ask', 'battle', 'aims', null]) assert.equal(of(k), null, String(k));
});
