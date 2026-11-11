// Train 3 wiring (contract K3): the select screen and the room reach every unit's entry
// point, every unit has replaced its contract stub, and every unit stylesheet is linked.
// Red until the wave lands.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');

const UNITS = {
  P1: ['js/views/realism-castcard.js', 'css/p5-castcard.css'],
  P2: ['js/views/realism-castlist.js', 'css/p5-castlist.css'],
  P3: ['js/views/realism-castdossier.js', 'css/p5-castdossier.css'],
  P4: ['js/views/realism-intro.js', 'css/p5-intro.css'],
  TH4: [null, 'css/p5-portrait.css'],
  Q5: ['js/views/realism-crawl.js', 'css/p5-crawl.css'],
  Q8: ['js/views/realism-intro.js', 'css/p5-intro.css'],
};

test('the select screen calls each unit with the data the server sends', () => {
  const cast = read('js/views/realism-cast.js');
  for (const call of [
    /castCard\(c, \{ mine, onOpen:/,
    /castDossier\(\{\s*person,\s*dossier: person\.dossier \?\? null,/,
    /castList\(\{\s*cast: castNames,/,
    /api\.newGame\('figures'/,
    /crawlParagraphs\(game\.view\.setting\)/,
    /introCrawl\(\{\s*title: game\.name,\s*paragraphs,\s*ready: false,/,
    /markIntro\(browserStorage\(window\), game\.id, 'crawl'\)/,
    /from '\.\/realism-crawl\.js'/,
    /status\?\.before\(beginStatus\(\)\)/,
    /'Beginning…'\), beginStatus\(\)\)/,
    /if \(crawl\?\.isConnected && crawl\.open\) markReady\(crawl\);/,
    /confirmNote: CONFIRM_NOTE,/,
  ]) assert.match(cast, call);
  assert.ok(!cast.includes('watched'), 'the crawl can no longer be left before Begin answers');
  for (const gone of ['whoHeldPower', 'held-search', "'Reach: '"]) assert.ok(!cast.includes(gone), gone);
});

test('a failed, refused or too-slow Begin closes the crawl before it says why', () => {
  const cast = read('js/views/realism-cast.js');
  const begin = cast.slice(cast.indexOf('async function beginWithCrawl'), cast.indexOf('function hostPanel'));
  assert.match(begin, /if \(r\.refused\) \{\s*closeCrawl\(\);/);
  assert.match(begin, /catch \(ex\) \{\s*closeCrawl\(\);/);
  assert.match(begin, /await beginOrGiveUp\(\)/);
  assert.match(cast, /Promise\.race\(\[api\.newGame\('begin', \{\}\), slow\]\)/);
});

test('the room opens with the intro before the seat files its first order', () => {
  const room = read('js/views/realism-room.js');
  for (const call of [
    /introStage\(storage\(\), game\.id, !rv\.record\?\.orders\?\.length\)/,
    /splashModel\(seatName, rv\.desk, rv\.dossier, startOverview\(rv\)\)/,
    /seatSplash\(\{/,
    /crawlParagraphs\(rv\.setting\)/,
    /introCrawl\(\{\s*title: game\.name,\s*paragraphs,\s*ready: true,/,
    /from '\.\/realism-crawl\.js'/,
    /markIntro\(storage\(\), game\.id, 'splash'\)/,
    /pending = opening \?\? happened/,
  ]) assert.match(room, call);
});

test('the server serves the setting during Session Zero', () => {
  const snap = readFileSync(join(WEB, '..', 'src/revisionist/engine/web/snapshot.py'), 'utf8');
  assert.match(snap, /out\["setting"\] = dossiers\.setting\(state, events\)/);
});

test('every unit has replaced its contract stub', () => {
  for (const [unit, files] of Object.entries(UNITS)) {
    for (const f of files.filter(Boolean)) assert.doesNotMatch(read(f), /contract stub/, `${unit}: ${f}`);
  }
  const server = readFileSync(join(WEB, '..', 'src/revisionist/engine/web/dossiers.py'), 'utf8');
  assert.doesNotMatch(server, /contract stub/, 'S4: dossiers.py');
});

test('every unit stylesheet is linked from the page', () => {
  const page = read('index.html');
  for (const [, css] of Object.values(UNITS)) assert.ok(page.includes(`href="/${css}"`), css);
});
