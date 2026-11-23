// A nation's flag, found by the world's key and the nation's key from the index in
// assets/flags/index.json. No nation or world is named here. A flag is decoration: it is drawn as an
// image, never inlined, and the nation's name is always in the accessible name. A nation with no
// file gets a plain block in its relation's tone (css/c-flags.css, theme tokens only).

import { h } from './dom.js';

const BASE = '/assets/flags/';
const FILE = /^[a-z0-9_-]+\.svg$/;
/** A flag is never drawn under this many px high; its box is 3 by 2. */
export const MIN_FLAG_HEIGHT = 16;
/** The heights css/c-flags.css has a class for; a request snaps up to the next one. */
const HEIGHTS = [16, 20, 24, 32, 40, 48, 64];

let index = null;

/** Sets the index (world key -> nation key -> file name or null); `null` clears it. */
export function setFlagIndex(next) {
  index = next && typeof next === 'object' ? next : null;
}

/** Fetches the index once; a failed fetch leaves every nation on the plain block. */
export async function loadFlagIndex(fetchFn = fetch) {
  try {
    const resp = await fetchFn(`${BASE}index.json`);
    setFlagIndex(resp.ok ? await resp.json() : null);
  } catch {
    setFlagIndex(null);
  }
}

const own = (o, k) => o != null && typeof k === 'string' && Object.hasOwn(o, k);

/** `/assets/flags/<file>` for the nation's flag in that world, or null when there is none. */
export function flagFor(world, nationKey) {
  if (!own(index, world) || !own(index[world], nationKey)) return null;
  const file = index[world][nationKey];
  return typeof file === 'string' && FILE.test(file) ? BASE + file : null;
}

/**
 * The nation's flag in a 3 by 2 box: `nation` is `{world, key, name, relation}`. The box is sized
 * by the class `flag-h<height>` (16, 20, 24, 32, 40, 48 or 64 px; never under 16), the plain block takes the relation's tone.
 * Beside the name the box is hidden from assistive tech; with `alone` it carries the name.
 */
export function flagBadge({ world, key, name, relation }, { height, alone = false } = {}) {
  const want = Number(height) || MIN_FLAG_HEIGHT;
  const high = HEIGHTS.find((x) => x >= want) ?? HEIGHTS.at(-1);
  const src = flagFor(world, key);
  const tone = relation === 'own' || relation === 'enemy' ? relation : 'neutral';
  return h('span', {
    class: `flag flag-h${high} ${src ? 'flag-file' : `flag-plain flag-${tone}`}`,
    'data-h': high,
    'data-w': high * 1.5,
    'data-nation': key,
    role: alone ? 'img' : null,
    'aria-label': alone ? name : null,
    'aria-hidden': alone ? null : 'true',
  }, src ? h('img', { src, alt: '', width: high * 1.5, height: high, loading: 'lazy', decoding: 'async' }) : null);
}
