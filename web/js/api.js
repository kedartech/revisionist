// The JSON API (src/revisionist/engine/web/server.py). Same origin, cookie session.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function call(method, path, body) {
  const init = { method, credentials: 'same-origin', headers: {} };
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let resp;
  try {
    resp = await fetch(path, init);
  } catch {
    throw new ApiError(0, "The game server didn't respond. Your text is still here.");
  }
  let data = {};
  try {
    data = await resp.json();
  } catch {
    throw new ApiError(resp.status, 'The game server sent something unreadable.');
  }
  if (!resp.ok) throw new ApiError(resp.status, data.error ?? 'Something went wrong.');
  return data;
}

export const api = {
  me: () => call('GET', '/api/me'),
  signup: (handle, password) => call('POST', '/api/signup', { handle, password }),
  signin: (handle, password) => call('POST', '/api/signin', { handle, password }),
  recover: (handle, code, password) => call('POST', '/api/recover', { handle, code, password }),
  signout: () => call('POST', '/api/signout', {}),
  /** A seat command; resolves to { reply, refused }. */
  seat: (action, body = {}) => call('POST', `/api/seat/${action}`, body),
  /** A realism call: read (resolves to a document page), flag (to { flagged }), directive (to { reply, refused, proposal }), aide (to { reply, refused, brief }), help (to { reply, refused, help }), order (to { reply, refused, proposal }), consult, sign, lever, aim-check and aim-set with { key, values } (to { reply, refused, aim: { stands, text, reasons } }), step, advance, commit, close, style, option, file, office-vote with { question, remove } (to { reply, refused }). */
  realism: (action, body = {}) => call('POST', `/api/realism/${action}`, body),
  /** The shapes of a territory game's map: resolves to { reply, refused, file, map }, the map file its stored hash names. */
  map: () => api.realism('map'),
  /** The pages for the wakes this seat missed: resolves to { first, last, pages }; a range { first, last } is optional, and with none the server names it. */
  catchup: (body = {}) => api.realism('catchup', body),
  /** The server's check of a move of post `{ move, person, post }`, filing nothing: resolves to { reply, refused, check, who, reason }. */
  moveCheck: (body) => api.realism('check', { move: body.move, person: body.person, post: body.post }),
  /** The game menu: pause, resume, end, wake-hours with { hours } (host), leave (anyone else); resolves to { reply, refused }. */
  game: (action, body = {}) => call('POST', `/api/game/${action}`, body),
  /** An ended game this account held a seat in; resolves to its reveal, or { reply, refused }. */
  reveal: (game) => call('POST', '/api/game/reveal', { game }),
  /** A new realism game: worlds, timeline, figures with { date, search }, ready, pitch, cast, start with { date }, opening (to { opening, ready_made, world, nation_keys }), pick, style with { style }, invite, begin; resolves to { reply, refused } and more. */
  newGame: (action, body = {}) => call('POST', `/api/new/${action}`, body),
};
