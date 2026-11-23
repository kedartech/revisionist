// The Capital board (CBD), one test or more per rule, on a seat built here with chambers of one,
// three and seven blocs, a nation with no chamber and a military seat: 1. in the map-first room a
// switch of two, Map and Capital, sits at the top left of the board and the Capital takes the
// map's place, the bar, the list and the season's strip staying; 2. the left column lists the
// live questions, each with its kind, who decides it, its count against its line and its days
// left; 3. a vote is a track (yeas from the left by bloc, nays from the right, the line that
// carries it) over the chamber's blocs sized by seats and the groups outside; a measure of more
// than one vote shows each as a step; 4. a picked piece shows its count, what last moved it and
// the themes that move it, with Speak; 5. a held order shows its chain, opens the map with its
// piece picked, and a lock's line in the piece's sheet opens it again; 6. a conference is a table
// of its members with what each has filed, and opens its form; 7. the right column says what is
// held and owed; 8. the room opens on the board kept for the device, else the Capital for a
// political seat, else the map; 9. with nothing to show the switch is not drawn. Amended:
// 10. both chambers at a glance with the picked vote's line; 11. the people a question passes
// through as portrait tokens opening their cards; 12. the seat's moves light what they would move;
// 13. full screen with the map's control, F and Escape; 14. on a phone the switch is not among the
// map's controls, which keep to two rows, and the Game menu carries it. Also: one person who
// decides and a council.
// Mutants: a count worked out by the client; another nation's bloc drawn; a question row for data
// the view did not send; the switch drawn with nothing to show; the switch back among the phone
// map's controls; the surface smoke's phone line lowered.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { setRoomLayout } = await import('../js/views/realism-sheets.js');
const cap = await import('../js/views/realism-capital.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');

const NORRA = fixture.home.nation;
const ORDER = 'o-neutrality';

/** `n` blocs of a chamber: seats 100, 60, 40, ... with support stepping down. */
const blocs = (n, prefix = 'b') => Array.from({ length: n }, (_, i) => ({
  group: `${prefix}${i}`, name: `Bloc ${prefix.toUpperCase()}${i}`, seats: i === 0 ? 100 : 60 - 5 * i, support: 90 - 10 * i,
}));

/** A roster line. */
const person = (name, office, portrait = null) => ({ person: `P-${name}`, name, office, portrait, regard: { step: null, word: 'Unknown' } });

/**
 * The seat's view: Norra's home block with an assembly of `n` blocs (and a senate of two), one
 * measure (the neutrality bill, filed as `o-neutrality`) with a vote in the assembly whose line
 * is 150 (51 in a chamber of one bloc); a group outside the chambers; two themes; a held order on the levy and an ask; a
 * conference Norra is invited to; one contest and one mandate; the roster with Rayburn and
 * Roosevelt. `change` edits it.
 */
function seat(n = 3, change = () => {}) {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.documents = structuredClone(fixture.listing);
  rv.wake_tick = 1;
  rv.style = 'free';
  rv.battles = [];
  rv.clock = { ...rv.clock, world_date: '1900-04-10' };
  rv.wake = { ...rv.wake, deadline: '2999-01-01T00:00:00+00:00', you_committed: false, humans: 1, committed: 0 };
  const assembly = blocs(n);
  const outside = { key: 'press', name: 'The Press', kind: 'press', support: 45, last_moved: { cause: 'writing', change: 2, on: '1900-04-08' }, feeds: { opinion: 1 } };
  rv.home = {
    ...structuredClone(fixture.home),
    groups: [...assembly.map((b) => ({ key: b.group, name: b.name, kind: 'party', support: b.support, last_moved: null, feeds: { votes: 1 } })),
      { key: 's0', name: 'Senate Right', kind: 'party', support: 40, last_moved: null, feeds: { votes: 1 } },
      { key: 's1', name: 'Senate Left', kind: 'party', support: 60, last_moved: null, feeds: { votes: 1 } }, outside],
    chambers: [
      { key: 'assembly', blocs: assembly, measures: [{ order_id: ORDER, key: 'neutrality', title: 'Revising the Neutrality Act', votes: [{
        vote: 'assembly', yeas: 120, nays: 40, carries: n === 1 ? 51 : 150,
        blocs: assembly.map((b, i) => ({ group: b.group, yeas: i === 0 ? (n > 1 ? 90 : 80) : Math.floor(20 / (n - 1)), nays: i === 0 ? 0 : Math.floor(40 / (n - 1)) })),
      }] }] },
      { key: 'senate', blocs: [{ group: 's0', name: 'Senate Right', seats: 30, support: 40 }, { group: 's1', name: 'Senate Left', seats: 70, support: 60 }], measures: [] },
    ],
    themes: [{ key: 'arms', name: 'Arms for the Allies', moves: { b0: 2, press: -1 } }, { key: 'peace', name: 'Keep the Peace', moves: { s0: 1 } }],
  };
  // the vote's yeas and nays are the blocs' sums
  const v = rv.home.chambers[0].measures[0].votes[0];
  v.yeas = v.blocs.reduce((s, b) => s + b.yeas, 0);
  v.nays = v.blocs.reduce((s, b) => s + b.nays, 0);
  rv.people = { opponents: [], yours: [person('Cordell Hull', 'Secretary of State')], others: [person('Sam Rayburn', 'Speaker of the House', 'rayburn.jpg'), person('Franklin D. Roosevelt', 'President')] };
  rv.orders = structuredClone(fixture.orders);
  rv.locks = structuredClone(fixture.locks);
  const levy = rv.map.marks.find((m) => m.piece?.key);
  rv.locks.held[0].piece = levy.piece.key;
  rv.conferences = { conferences: [{
    key: 'charter', called_by: 'Norra', invited: ['Norra', 'Sudland'], text: 'A charter for the gulf', clauses: [], unanimous: false,
    called: '1900-04-02', voting_day: '1900-04-16', public: false, vote: 'for', can_vote: true, tallied: null, result: null, votes: [], agreement: null,
  }, {
    key: 'old', called_by: 'Sudland', invited: ['Norra', 'Sudland'], text: 'An old one', clauses: [], unanimous: false,
    called: '1900-03-02', voting_day: '1900-03-16', public: false, vote: 'for', can_vote: false, tallied: '1900-03-17', result: 'agreement', votes: [{ nation: 'Norra', vote: 'for' }], agreement: 'X',
  }, {
    key: 'public', called_by: 'Ostmark', invited: ['Ostmark', 'Vesta'], text: 'Someone else\'s', clauses: [], unanimous: false,
    called: '1900-04-02', voting_day: '1900-04-20', public: true, vote: null, can_vote: false, tallied: null, result: null, votes: [], agreement: null,
  }] };
  rv.stakes = { ...structuredClone(fixture.stakes), contests: [structuredClone(fixture.stakes.contests[0])], mandates: [structuredClone(fixture.stakes.mandates[0])] };
  change(rv);
  return rv;
}

/** A view with nothing the board shows: no measure, lock, conference, contest or mandate. */
const bare = () => seat(3, (rv) => {
  rv.home.chambers.forEach((c) => { c.measures = []; });
  rv.locks = null;
  rv.conferences = { conferences: [] };
  rv.stakes = { ...rv.stakes, contests: [], mandates: [] };
});

/** The whole room for view `rv` in `layout`, as the page draws it. */
function room(rv, layout = 'map', id = `h20-${Math.random()}`) {
  const doc = installDom();
  setRoomLayout(layout);
  api.realism = async () => ({});
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const game = { id, name: 'Autumn 1941', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {}, signOut: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  return { root, now: () => doc.body.firstElementChild, doc };
}

/** The board alone, with a record of what its controls asked of the room. */
function board(rv, state = {}) {
  installDom();
  const asked = [];
  const on = Object.fromEntries(['board', 'person', 'map', 'ask', 'openAsk', 'conference', 'speak', 'full'].map((k) => [k, (...a) => asked.push([k, ...a])]));
  const el = cap.capitalBoard(rv, state, on);
  document.body.append(el);
  return { el, asked, state };
}

const switchOf = (root) => root.querySelector('.rl-board-switch');
const rows = (el) => el.querySelectorAll('button.rl-cap-q');
const rowKeys = (el) => rows(el).map((b) => b.getAttribute('data-key'));
const pick = (el, key) => el.querySelector(`button[data-key="${key}"]`).click();
const key = (el, k, target = el) => {
  const ev = { type: 'keydown', key: k, target, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  el.dispatchEvent(ev);
  return ev;
};

// rule 1: the switch at the top left of the board; the Capital takes the map's place

test('the map-first room draws the switch of two at the top left of the map, Map pressed', () => {
  const { root } = room(seat());
  const sw = switchOf(root);
  assert.ok(sw, 'the switch is drawn');
  assert.equal(sw.getAttribute('aria-label'), 'Board');
  assert.deepEqual(sw.querySelectorAll('button').map(words), ['Map', 'Capital']);
  assert.equal(sw.querySelector('button[data-board="map"]').getAttribute('aria-pressed'), 'true');
  const start = sw.parentNode;
  assert.ok(start.classList.contains('rl-tm-tools-start'), 'in the map\'s top left tools');
  assert.equal(start.children[0], sw, 'first of them');
});

test('Capital takes the map\'s place; the bar, What needs you and the season\'s strip stay', () => {
  const r = room(seat());
  switchOf(r.root).querySelector('button[data-board="capital"]').click();
  const root = r.now();
  const section = root.querySelector('.rl-mapfirst-map');
  assert.equal(section.getAttribute('data-board'), 'capital');
  assert.ok(section.querySelector('.rl-cap'), 'the board is in the map\'s section');
  assert.equal(section.querySelector('.rl-tmap'), null, 'the map is not drawn under it');
  assert.ok(section.querySelector('.rl-tl'), 'the season\'s strip stays');
  assert.ok(root.querySelector('.rl-roombar'), 'the bar stays');
  assert.ok(root.querySelector('.rl-needs'), 'What needs you stays');
  const head = section.querySelector('.rl-cap-head');
  assert.equal(head.children[0], switchOf(root), 'the switch at the board\'s top left');
  assert.equal(switchOf(root).querySelector('button[data-board="capital"]').getAttribute('aria-pressed'), 'true');
  switchOf(root).querySelector('button[data-board="map"]').click();
  assert.ok(r.now().querySelector('.rl-mapfirst-map .rl-tmap'), 'one tap back to the map');
});

test('the Classic layout is not changed: no switch and no board', () => {
  const { root } = room(seat(), 'classic');
  assert.equal(switchOf(root), null);
  assert.equal(root.querySelector('.rl-cap'), null);
});

// rule 2: the left column lists the live questions

test('the questions: the measure, the held orders, the ask, the invited conference, the contest and the mandate', () => {
  const rv = seat();
  const { el } = board(rv);
  assert.deepEqual(rowKeys(el), [
    `vote:${ORDER}`, `held:${rv.locks.held[0].id}`, `held:${rv.locks.held[1].id}`, `ask:${rv.locks.asks[0].id}`, 'conf:charter', 'contest:0', 'mandate:0',
  ]);
});

test('a row says its kind, who decides it, its count against its line and its days left', () => {
  const { el } = board(seat());
  const [vote, held, , ask, conf, contest, mandate] = rows(el);
  assert.match(words(vote), /A vote · The assembly/);
  assert.match(vote.getAttribute('aria-label'), /decided by The assembly\. \d+ yea, 150 carry it$/);
  assert.ok(vote.querySelector('svg.rl-cap-rowbar line.rl-cap-carry'), 'the count drawn against its line');
  assert.match(words(held), /A held order · Ilse Varg/);
  assert.equal(held.querySelector('svg'), null, 'no count where none is sent');
  assert.match(words(ask), /Asked of you · You/);
  assert.match(words(conf), /A conference · Norra, Sudland.*6 days left/, 'the days to its voting day');
  assert.match(words(contest), /A contest .*24 days left/);
  assert.match(words(mandate), /Your mandate · You.*6 days left/);
});

test('a row for nothing the view did not send: no tallied or other nations\' conference, no locks without the block', () => {
  const rv = seat(3, (x) => { x.locks = null; x.stakes.contests = []; });
  const { el } = board(rv);
  assert.deepEqual(rowKeys(el), [`vote:${ORDER}`, 'conf:charter', 'mandate:0']);
});

test('a row\'s line is the count the server sent; with none sent the row draws no line', () => {
  const at = (rv) => board(rv).el.querySelector('button.rl-cap-q svg.rl-cap-rowbar line.rl-cap-carry');
  // 150 of the assembly's seats (100 + 55 + 50 = 205), not half of them
  assert.equal(Number(at(seat()).getAttribute('x1')).toFixed(2), (100 * 150 / 205).toFixed(2));
  assert.equal(at(seat(3, (rv) => { delete rv.home.chambers[0].measures[0].votes[0].carries; })), null);
});

// rule 3: the vote as a track over the chamber's blocs, and the groups outside

for (const n of [1, 3, 7]) {
  test(`a vote in a chamber of ${n} bloc${n === 1 ? '' : 's'}: yeas from the left by bloc, nays from the right, the line that carries it`, () => {
    const rv = seat(n);
    const { el } = board(rv);
    const v = rv.home.chambers[0].measures[0].votes[0];
    const total = rv.home.chambers[0].blocs.reduce((s, b) => s + b.seats, 0);
    const track = el.querySelector('svg.rl-cap-track');
    const yeas = track.querySelectorAll('rect.rl-cap-yea');
    const nays = track.querySelectorAll('rect.rl-cap-nay');
    assert.equal(Number(yeas[0].getAttribute('x')), 0, 'the yeas start at the left');
    assert.deepEqual(yeas.map((r) => r.getAttribute('data-group')), v.blocs.filter((b) => b.yeas).map((b) => b.group), 'by bloc in the chamber\'s order');
    const yeaEnd = yeas.reduce((s, r) => s + Number(r.getAttribute('width')), 0);
    assert.ok(Math.abs(yeaEnd - (100 * v.yeas) / total) < 1e-9);
    if (nays.length) {
      const last = nays.at(-1);
      assert.ok(Math.abs(Math.max(...nays.map((r) => Number(r.getAttribute('x')) + Number(r.getAttribute('width')))) - 100) < 1e-9, 'the nays end at the right');
      assert.ok(Number(last.getAttribute('x')) >= yeaEnd);
    }
    const open = track.querySelector('rect.rl-cap-open');
    assert.ok(open, 'those not yet counted between');
    assert.equal(Number(track.querySelector('line.rl-cap-carry').getAttribute('x1')).toFixed(4), ((100 * v.carries) / total).toFixed(4));
    assert.match(track.getAttribute('aria-label'), new RegExp(`${v.carries} carry it`));
    // the blocs as pieces sized by seats, each with its five steps
    const pieces = el.querySelectorAll('.rl-cap-blocs button.rl-cap-piece');
    assert.equal(pieces.length, n);
    rv.home.chambers[0].blocs.forEach((b, i) => {
      assert.ok(pieces[i].classList.contains(`g${cap.grow(b.seats, total)}`), `${b.name} sized by its seats`);
      assert.ok(pieces[i].querySelector('.rl-cap-steps5'), 'its five-step bar');
    });
    // the groups in no chamber as a second row
    assert.deepEqual(el.querySelectorAll('.rl-cap-groups button.rl-cap-piece').map((b) => b.getAttribute('data-group')), ['press']);
  });
}

test('a piece is sized by its seats, not its support', () => {
  const rv = seat(3, (x) => { x.home.chambers[0].blocs[0].support = 5; x.home.chambers[0].blocs[2].support = 99; });
  const { el } = board(rv);
  const [big, , small] = el.querySelectorAll('.rl-cap-blocs button.rl-cap-piece');
  assert.ok(big.classList.contains('g6'), big.getAttribute('class'));
  assert.ok(small.classList.contains('g3'), small.getAttribute('class'));
});

test('the track\'s line is the count the server sent, not a count the client works out', () => {
  const rv = seat(3, (x) => { x.home.chambers[0].measures[0].votes[0].carries = 180; });
  const { el } = board(rv);
  assert.equal(Number(el.querySelector('svg.rl-cap-track line.rl-cap-carry').getAttribute('x1')).toFixed(4), ((100 * 180) / 205).toFixed(4));
  const none = board(seat(3, (x) => { delete x.home.chambers[0].measures[0].votes[0].carries; })).el;
  assert.equal(none.querySelector('svg.rl-cap-track line.rl-cap-carry'), null, 'no line where none is sent');
  assert.equal(words(none.querySelector('.rl-cap-trackbox')).includes('carry'), false);
});

test('a measure of two votes shows each as a step with its own count, and the picked one draws', () => {
  const rv = seat(3, (x) => {
    const m = x.home.chambers[0].measures[0];
    m.votes.push({ vote: 'senate', yeas: 30, nays: 10, carries: 51, blocs: [{ group: 's0', yeas: 0, nays: 10 }, { group: 's1', yeas: 30, nays: 0 }] });
  });
  const { el } = board(rv);
  const stepsOf = () => el.querySelectorAll('button.rl-cap-votestep');
  assert.deepEqual(stepsOf().map(words), [`The assembly${rv.home.chambers[0].measures[0].votes[0].yeas} yea · 150 carry it`, 'The senate30 yea · 51 carry it']);
  stepsOf()[1].click();
  assert.equal(stepsOf()[1].getAttribute('aria-pressed'), 'true');
  assert.equal(Number(el.querySelector('svg.rl-cap-track line.rl-cap-carry').getAttribute('x1')), 51);
  assert.deepEqual(el.querySelectorAll('.rl-cap-blocs button.rl-cap-piece').map((b) => b.getAttribute('data-group')), ['s0', 's1'], 'the senate\'s blocs');
});

test('only the seat\'s own nation\'s blocs: a home block of another nation draws none', () => {
  const rv = seat(3, (x) => { x.home.nation = { ...x.home.nation, relation: 'enemy' }; });
  const { el } = board(rv);
  assert.equal(el.querySelectorAll('.rl-cap-piece').length, 0);
  assert.equal(el.querySelectorAll('.rl-cap-chamber').length, 0);
  assert.equal(rowKeys(el).some((k) => k.startsWith('vote:')), false);
});

// rule 4: a picked piece in the right column

test('picking a bloc shows its count on the vote, what last moved it and why, the themes that move it, and Speak', () => {
  const rv = seat(3, (x) => { x.home.groups[0].last_moved = { cause: 'battle_won', change: 5, on: '1900-04-02' }; });
  const { el, asked } = board(rv);
  pick(el, 'piece:b0');
  assert.equal(el.querySelector('button[data-key="piece:b0"]').getAttribute('aria-pressed'), 'true');
  const card = el.querySelector('.rl-cap-side .rl-cap-card');
  assert.equal(card.getAttribute('data-group'), 'b0');
  const b = rv.home.chambers[0].measures[0].votes[0].blocs[0];
  assert.match(words(card), new RegExp(`On this vote: ${b.yeas} yea, ${b.nays} nay`));
  assert.match(words(card), /Up 5 on .*: a battle won/);
  assert.match(words(card), /Moved by: Arms for the Allies \(up 2\)/);
  card.querySelector('button.rl-cap-speak').click();
  assert.deepEqual(asked.at(-1), ['speak']);
  pick(el, 'piece:b0');
  assert.match(words(el.querySelector('.rl-cap-side')), /Pick a bloc, a group or a person/, 'a second tap puts it down');
});

// rule 5: a held order's chain, to the map and back

test('a held order shows the order, what holds it and the question that would release it', () => {
  const rv = seat();
  const l = rv.locks.held[0];
  const { el, asked } = board(rv, { q: `held:${l.id}` });
  const chain = el.querySelectorAll('.rl-cap-chain li.rl-cap-link-box');
  assert.equal(chain.length, 3);
  assert.match(words(chain[0]), new RegExp(`The order${l.words.replace(/[()]/g, '.')}`));
  assert.match(words(chain[1]), /What holds itIlse VargHeld until Ilse Varg allows it\./);
  assert.match(words(chain[2]), /You have asked Ilse Varg for leave/, 'asked: no second ask');
  const mark = rv.map.marks.find((m) => m.piece?.key === l.piece);
  el.querySelector('button.rl-cap-tomap').click();
  assert.deepEqual(asked.at(-1), ['map', mark]);
  const other = board(rv, { q: `held:${rv.locks.held[1].id}` });
  assert.equal(other.el.querySelector('button.rl-cap-tomap'), null, 'an order on no piece opens no map');
  other.el.querySelector('button.rl-cap-ask').click();
  assert.equal(other.asked.at(-1)[0], 'ask');
});

test('the held order opens the map with its piece picked, and its lock\'s line there opens the question again', () => {
  const rv = seat();
  const l = rv.locks.held[0];
  const mark = rv.map.marks.find((m) => m.piece?.key === l.piece);
  const r = room(rv);
  switchOf(r.root).querySelector('button[data-board="capital"]').click();
  r.now().querySelector(`.rl-cap button[data-key="held:${l.id}"]`).click();
  r.now().querySelector('.rl-cap button.rl-cap-tomap').click();
  let root = r.now();
  assert.ok(root.querySelector('.rl-mapfirst-map .rl-tmap'), 'the map');
  assert.equal(root.querySelector('.rl-over').getAttribute('data-sheet'), 'piece');
  assert.equal(words(root.querySelector('.rl-over-title')), mark.name, 'its piece picked');
  const back = root.querySelector(`.rl-over li[data-held="${l.id}"] button.rl-held-capital`);
  assert.ok(back, 'the lock\'s line opens its question');
  back.click();
  root = r.now();
  assert.equal(root.querySelector('.rl-over'), null, 'the piece\'s sheet closes');
  assert.equal(root.querySelector(`.rl-cap button[data-key="held:${l.id}"]`).getAttribute('aria-pressed'), 'true');
});

// rule 6: a conference as a table

test('a conference draws its members at a table with what each has filed, and opens its form', () => {
  const rv = seat();
  const { el, asked } = board(rv, { q: 'conf:charter' });
  const seats = el.querySelectorAll('.rl-cap-table .rl-cap-seat');
  assert.deepEqual(seats.map((s) => s.getAttribute('data-nation')), ['Norra', 'Sudland']);
  assert.match(words(seats[0]), /Your choice: for/);
  assert.match(words(seats[1]), /Sealed until the count/, 'nothing the view did not send');
  assert.ok(seats[0].querySelector('.flag'), 'each a flag');
  el.querySelector('button.rl-cap-confvote').click();
  assert.equal(asked.at(-1)[0], 'conference');
  const counted = board(seat(3, (x) => { x.conferences.conferences[0].votes = [{ nation: 'Sudland', vote: 'against' }]; }), { q: 'conf:charter' }).el;
  assert.match(words(counted.querySelectorAll('.rl-cap-seat')[1]), /Filed against/);
});

test('the conference\'s form is the Diplomacy sheet the room has today', () => {
  const r = room(seat());
  switchOf(r.root).querySelector('button[data-board="capital"]').click();
  r.now().querySelector('.rl-cap button[data-key="conf:charter"]').click();
  r.now().querySelector('.rl-cap button.rl-cap-confvote').click();
  assert.equal(r.now().querySelector('.rl-over').getAttribute('data-sheet'), 'diplomacy');
});

// rule 7: what the seat holds and owes

// changed rule (PRB rule 3): the promises made are what the seat holds and owes, so nothing is
// owed only when the seat has made none
test('the right column always says what is held and owed: nothing when no promise is made', () => {
  for (const q of [undefined, 'conf:charter', 'mandate:0']) {
    const { el } = board(seat(3, (v) => { v.home.promises = []; }), { q });
    assert.equal(words(el.querySelector('.rl-cap-side .rl-cap-owed')), cap.OWED_NONE);
  }
});

// rule 8: the board the room opens on

test('the room opens on the board kept for the device, else the Capital on the political path, else the map', () => {
  assert.equal(cap.startBoard({ stored: 'capital', path: null }), 'capital');
  assert.equal(cap.startBoard({ stored: 'map', path: 'political' }), 'map');
  assert.equal(cap.startBoard({ stored: null, path: 'political' }), 'capital');
  assert.equal(cap.startBoard({ stored: null, path: 'military' }), 'map');
  assert.equal(cap.startBoard({ stored: 'junk', path: null }), 'map');
  assert.equal(cap.startBoard(), 'map', 'no path sent: the map');
});

test('the switch keeps the choice for the device', () => {
  const kept = new Map();
  globalThis.localStorage = { getItem: (k) => kept.get(k) ?? null, setItem: (k, v) => kept.set(k, v) };
  try {
    const r = room(seat());
    switchOf(r.root).querySelector('button[data-board="capital"]').click();
    assert.equal(kept.get(cap.BOARD_KEY), 'capital');
    const again = room(seat());
    assert.ok(again.root.querySelector('.rl-cap'), 'a new room opens on the Capital');
  } finally {
    delete globalThis.localStorage;
  }
});

// rule 9: with nothing to show the switch is not drawn

test('with no measure, lock, conference, contest or mandate the switch is not drawn', () => {
  assert.equal(cap.hasCapital(bare()), false);
  const { root } = room(bare());
  assert.equal(switchOf(root), null);
  assert.ok(root.querySelector('.rl-tmap'), 'the map');
  const one = cap.hasCapital(seat(3, (rv) => { Object.assign(rv, bare()); rv.stakes.mandates = [{ text: 'Hold', days_left: 3 }]; }));
  assert.equal(one, true, 'a mandate alone is enough');
});

test('a Capital kept for the device opens the map when there is nothing to show', () => {
  globalThis.localStorage = { getItem: () => 'capital', setItem: () => {} };
  try {
    const { root } = room(bare());
    assert.equal(root.querySelector('.rl-cap'), null);
    assert.ok(root.querySelector('.rl-tmap'));
  } finally {
    delete globalThis.localStorage;
  }
});

// rule 10: both chambers at a glance

test('both chambers are in view above the question, split by bloc, the picked vote\'s line in its own chamber', () => {
  const { el } = board(seat());
  const bars = el.querySelectorAll('.rl-cap-head button.rl-cap-chamber');
  assert.deepEqual(bars.map((b) => b.getAttribute('data-key')), ['chamber:assembly', 'chamber:senate']);
  assert.equal(bars[0].querySelectorAll('rect.rl-cap-seg').length, 3);
  assert.equal(bars[1].querySelectorAll('rect.rl-cap-seg').length, 2);
  assert.ok(bars[0].querySelector('line.rl-cap-carry'), 'the assembly carries the picked vote\'s line');
  assert.equal(bars[1].querySelector('line.rl-cap-carry'), null, 'the senate has no vote on it');
  pick(el, `held:${seat().locks.held[0].id}`);
  assert.equal(el.querySelectorAll('.rl-cap-head button.rl-cap-chamber').length, 2, 'still in view on another question');
  assert.equal(el.querySelector('.rl-cap-head line.rl-cap-carry'), null);
});

test('a chamber\'s bar opens its blocs to pick, with no question needed', () => {
  const rv = bare();
  rv.stakes.mandates = [{ text: 'Hold the line', days_left: 3 }];
  const { el } = board(rv);
  pick(el, 'chamber:senate');
  assert.deepEqual(el.querySelectorAll('.rl-cap-blocs button.rl-cap-piece').map((b) => b.getAttribute('data-group')), ['s0', 's1']);
  pick(el, 'piece:s1');
  assert.match(words(el.querySelector('.rl-cap-side .rl-cap-card')), /Senate Left.*70 seats/);
});

test('a nation with no chamber draws no chamber bars, and its board still works', () => {
  const rv = seat(3, (x) => { x.home.chambers = []; });
  const { el } = board(rv);
  assert.equal(el.querySelector('.rl-cap-chambers'), null);
  assert.deepEqual(rowKeys(el).map((k) => k.split(':')[0]), ['held', 'held', 'ask', 'conf', 'contest', 'mandate']);
});

// rule 11: the people a question passes through

test('the people a vote passes through stand as portrait tokens from the roster, and open their cards', () => {
  const rv = seat(3, (x) => { x.home.chambers[0].measures[0].order_id = ORDER; });
  const { el, asked } = board(rv);
  const tokens = el.querySelectorAll('.rl-cap-people button.rl-pp-token');
  // the order's decision steps as the orders log names them: Roosevelt, then Rayburn
  assert.deepEqual(tokens.map((t) => t.getAttribute('data-person')), ['P-Franklin D. Roosevelt', 'P-Sam Rayburn']);
  assert.ok(tokens[1].querySelector('img.rl-pp-portrait'), 'the portrait the roster names');
  assert.equal(tokens[0].querySelector('img'), null, 'initials where it names none');
  tokens[1].click();
  assert.equal(asked.at(-1)[0], 'person');
  assert.equal(asked.at(-1)[1].name, 'Sam Rayburn');
});

test('a token opens the person\'s figure card in the room', () => {
  const r = room(seat());
  switchOf(r.root).querySelector('button[data-board="capital"]').click();
  r.now().querySelector('.rl-cap button.rl-pp-token').click();
  assert.ok(r.doc.body.querySelector('dialog.rl-fc'), 'the figure card');
});

// amendment 37: one person who decides, and a council

test('a held order one person decides draws that person and those with access', () => {
  const rv = seat(3, (x) => { x.locks.held[1].who = 'Franklin D. Roosevelt'; });
  const { el } = board(rv, { q: `held:${rv.locks.held[1].id}` });
  const one = el.querySelector('.rl-cap-one');
  assert.ok(one);
  assert.equal(one.querySelector('button.rl-pp-token').getAttribute('data-person'), 'P-Franklin D. Roosevelt');
  assert.deepEqual(one.querySelectorAll('section.rl-cap-access button.rl-pp-token').map((t) => t.getAttribute('data-person')), ['P-Cordell Hull']);
});

test('a military seat with no home block: its held orders, one person deciding, and no chamber', () => {
  const rv = seat(3, (x) => {
    x.home = null;
    x.stakes.contests = [];
    x.stakes.mandates = [];
    x.conferences = { conferences: [] };
    x.locks.held = [{ ...x.locks.held[0], who: 'Sam Rayburn', reason: 'Held until Sam Rayburn allows it.' }];
    x.locks.asks = [];
  });
  assert.equal(cap.hasCapital(rv), true);
  const { el } = board(rv);
  assert.deepEqual(rowKeys(el), [`held:${rv.locks.held[0].id}`]);
  assert.equal(el.querySelector('.rl-cap-chambers'), null);
  assert.equal(el.querySelector('.rl-cap-one button.rl-pp-token').getAttribute('data-person'), 'P-Sam Rayburn');
  assert.equal(el.querySelector('.rl-cap-moves'), null, 'no themes, no moves row');
});

test('a held order a body with no chamber in view decides is a council at its table', () => {
  const rv = seat(3, (x) => { x.home.chambers = []; x.locks.held[1].who = 'Norra\'s war council'; });
  const { el } = board(rv, { q: `held:${rv.locks.held[1].id}` });
  const council = el.querySelector('.rl-cap-council');
  assert.ok(council);
  assert.match(words(council), /A council decides.*Norra's war council/);
});

// rule 12: the seat's moves light what they would move

test('picking a move lights every bloc and group it would move, with the direction and amount, before anything is filed', () => {
  const { el, asked } = board(seat());
  assert.deepEqual(el.querySelectorAll('.rl-cap-moves button.rl-cap-move').map((b) => b.getAttribute('data-key')), ['theme:arms', 'theme:peace']);
  assert.equal(el.querySelectorAll('.rl-cap-piece.lit').length, 0);
  pick(el, 'theme:arms');
  const lit = el.querySelectorAll('.rl-cap-piece.lit');
  assert.deepEqual(lit.map((b) => b.getAttribute('data-group')), ['b0', 'press']);
  assert.equal(words(lit[0].querySelector('.rl-cap-plit')), '↑ 2');
  assert.ok(lit[0].classList.contains('up'));
  assert.equal(words(lit[1].querySelector('.rl-cap-plit')), '↓ 1');
  assert.match(lit[1].getAttribute('aria-label'), /Arms for the Allies moves it down 1/);
  assert.equal(asked.length, 0, 'nothing filed');
  el.querySelector('.rl-cap-moves button.rl-cap-speak').click();
  assert.deepEqual(asked.at(-1), ['speak']);
});

// rule 13: full screen

test('the board\'s Full screen control and F ask the room for full screen', () => {
  const { el, asked } = board(seat());
  el.querySelector('button.rl-cap-full').click();
  assert.deepEqual(asked.at(-1), ['full', true]);
  const ev = key(el, 'f');
  assert.equal(ev.defaultPrevented, true);
  assert.deepEqual(asked.at(-1), ['full', true]);
  const typing = key(el, 'f', { closest: (s) => (s.includes('textarea') ? {} : null) });
  assert.equal(typing.defaultPrevented, false, 'F typed in a field is a letter');
});

test('in the room the board goes full screen, and Escape gives the room back', () => {
  const r = room(seat());
  switchOf(r.root).querySelector('button[data-board="capital"]').click();
  r.now().querySelector('.rl-cap button.rl-cap-full').click();
  assert.ok(r.now().classList.contains('rl-full'));
  assert.ok(r.now().querySelector('.rl-cap'), 'the Capital stays in full screen');
  assert.ok(r.doc.activeElement?.classList?.contains('rl-cap-full'), 'the keyboard stays on the board, so Escape reaches the room');
  key(r.now(), 'Escape');
  assert.equal(r.now().classList.contains('rl-full'), false);
});

// rule 14: on a phone the switch leaves the map's controls for the Game menu

/** The rules of `css` inside its `@media (max-width: 767px)` blocks, and those outside any block. */
function phoneRules(css) {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const inside = [];
  let outside = text;
  for (const m of text.matchAll(/@media \(max-width: 767px\) \{([\s\S]*?)\n\}/g)) {
    inside.push(m[1]);
    outside = outside.replace(m[0], '');
  }
  return { phone: inside.join('\n'), wide: outside.replace(/@media[^{]*\{[\s\S]*?\n\}/g, '') };
}

const ruleOf = (css, sel) => css.split('\n').map((l) => l.trim()).find((l) => l.startsWith(`${sel} {`)) ?? '';

test('on a phone the map\'s switch is hidden and the Game menu\'s shown; wider, the reverse', () => {
  const { phone, wide } = phoneRules(read('css/c-capital.css'));
  assert.match(ruleOf(phone, '.rl-mapfirst-map[data-board="map"] .rl-board-switch'), /display: none/, 'the map keeps its controls to two rows');
  assert.match(ruleOf(phone, '.rl-menu-board'), /display: block/, 'the Game menu carries the switch');
  assert.match(ruleOf(wide, '.rl-menu-board'), /display: none/, 'on a desk the menu does not');
  assert.equal(ruleOf(wide, '.rl-mapfirst-map[data-board="map"] .rl-board-switch'), '', 'on a desk the map\'s switch stays');
});

test('the Game menu carries the Board switch, two taps from the map to the Capital', () => {
  const r = room(seat());
  const menu = r.root.querySelector('dialog.rl-menu');
  const sw = menu.querySelector('.rl-menu-board .rl-board-switch');
  assert.ok(sw, 'the switch is in the menu');
  assert.equal(sw.getAttribute('aria-label'), 'Board');
  assert.deepEqual(sw.querySelectorAll('button').map(words), ['Map', 'Capital']);
  assert.equal(sw.querySelector('button[data-board="map"]').getAttribute('aria-pressed'), 'true');
  r.root.querySelector('.rl-menu-btn').click();
  assert.equal(menu.open, true, 'one tap opens the menu');
  sw.querySelector('button[data-board="capital"]').click();
  assert.equal(menu.open, false, 'the pick closes the menu');
  const now = r.now();
  assert.equal(now.querySelector('.rl-mapfirst-map').getAttribute('data-board'), 'capital', 'the second tap opens the Capital');
  assert.equal(r.doc.activeElement?.getAttribute('data-board'), 'capital', 'the keyboard lands on the board\'s switch');
  assert.equal(now.querySelector('dialog.rl-menu .rl-board-switch button[data-board="capital"]').getAttribute('aria-pressed'), 'true');
  now.querySelector('dialog.rl-menu .rl-board-switch button[data-board="map"]').click();
  assert.ok(r.now().querySelector('.rl-mapfirst-map .rl-tmap'), 'the menu gives the map back');
  assert.ok(r.doc.activeElement?.classList?.contains('rl-menu-btn'), 'the keyboard goes back to the Game button');
});

test('the Game menu has no switch with nothing to show, nor in the Classic layout', () => {
  assert.equal(room(bare()).root.querySelector('dialog.rl-menu .rl-board-switch'), null);
  assert.equal(room(seat(), 'classic').root.querySelector('dialog.rl-menu .rl-board-switch'), null);
});

test('the surface smoke keeps the phone\'s line: the map clear of its controls for 55% of the viewport', () => {
  assert.match(read('test/e2e/surface_smoke.py'), /^MAP_SHARE = 0\.55 if PHONE else 0\.65$/m);
});

// keeps: colour from the tokens, the stylesheet linked, every control a 44 px target

test('index.html links c-capital.css, which writes no colour but the tokens', () => {
  assert.match(read('index.html'), /<link rel="stylesheet" href="\/css\/c-capital.css">/);
  const css = read('css/c-capital.css').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.equal(/#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(/.test(css), false);
});

test('every control of the board is at least 44 px', () => {
  const css = read('css/c-capital.css');
  for (const sel of ['.rl-board-switch button', '.rl-cap-chamber', '.rl-cap-full', '.rl-cap-q', '.rl-cap-votestep', '.rl-cap-piece', '.rl-pp-token', '.rl-cap-move']) {
    const rule = css.split('\n').find((line) => line.startsWith(`${sel} {`));
    assert.ok(rule && /min-height: 44px/.test(rule), `${sel}: ${rule}`);
  }
});
