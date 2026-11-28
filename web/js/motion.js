// The room's motion: one list of every motion the room plays (MOTIONS), each with what change it
// shows, how long it runs and what reduced motion shows in its place, and the few helpers every
// motion in the board lane's files goes through: the reduced-motion check, `play`, `runCount`,
// `stepLeft`, `slideIn` and `slideOut`. The sheet `docs/web-design/motion.md` is the same list in
// words. Motion shows a change in the game or in the seat's view, once; nothing moves to
// decorate, no motion holds a control, and under reduced motion the end state stands at once.
// The stylesheets' animations are listed here by their keyframes, at the time the stylesheet
// gives them (web/test/h26-motion.test.js holds the two to each other). The map's own motions are
// the surface lane's, listed here so the room's list is whole. Nothing here touches the page on
// import.

const entry = (ms, shows, reduced, more = {}) => Object.freeze({ ms, shows, reduced, lane: 'board', ...more });
const css = (keyframes, file) => ({ css: keyframes, file });
const surface = (where) => ({ lane: 'surface', where });

/** Every motion in the room, by name. `ms` is its time; the clock's two give the wake's pace. */
export const MOTIONS = Object.freeze({
  // the first set
  'sheet-in': entry(200, 'A sheet opening slides in from where it opens: from the right at 1024 px and over, from the foot below.', 'The sheet is there at once.'),
  'sheet-out': entry(200, 'A sheet closing slides back the way it came; the map under it is live at once, the sheet leaving is a picture no one can press or read.', 'The sheet is gone at once.'),
  'battle-round': entry(500, 'A day\'s round of a battle the sheet has not drawn before: its two bars, the seat\'s losses and the enemy\'s as reported, grow from the foot to their length.', 'The bars stand at their length; the day table under them says the same losses in words.'),
  'timeline-due': entry(900, 'A mark on the season\'s timeline that came due since the strip last drew flashes once.', 'The mark is drawn as due (its outline), with no flash.'),
  'timeline-new': entry(400, 'A dated thing new to the strip since it last drew drops into its place on the line.', 'The mark stands in its place.'),
  'nation-bar': entry(600, 'A nation\'s bar on the chart runs from its old length to its new one when its figure changes.', 'The bar stands at its new length beside its new figure.'),
  'step-left': entry(1200, 'A five-step meter that moved a step (a piece\'s figure, a nation\'s standing at home, a bloc\'s support) shows the step it left, outlined, for a moment.', 'The meter shows its new step; its name says the step in words.'),
  // the Capital board's tracks
  'track-marker': entry(600, 'An order\'s marker slides along its track to the step that now holds it.', 'The marker stands at its step.'),
  'bloc-part': entry(600, 'The blocs\' parts of a vote\'s track slide to their new widths when the count changes; a bloc new to it fades in.', 'The parts stand at their widths.'),
  'count-run': entry(600, 'A vote\'s count runs from the old number to the new one the server sent.', 'The new count is written at once.'),
  'offer-in': entry(600, 'An offer filed draws its part of the track in from the bloc that takes it.', 'The part stands on the track.'),
  'promise-due': entry(900, 'A promise that came due flashes once on the board and on the timeline.', 'The promise is drawn as due, with no flash.'),
  // the wake's playback
  'wake-day': entry(400, 'One world day of a wake\'s playback: every own piece that moved runs its step at its own rate, the day and its bar run with it.', 'Every frame of the wake stands still at once, each with its day.', { clock: true }),
  'wake-cap': entry(20000, 'The longest a wake\'s playback runs; a longer wake runs its clock faster.', 'As above.', { clock: true }),
  // the opening's crawl
  'crawl-char': entry(25, 'The setting\'s crawl types itself, a character at a time (forty a second), as the game is set up.', 'Every paragraph is whole at once.', { clock: true }),
  'crawl-pause': entry(600, 'The pause between two paragraphs of the crawl.', 'No pause.', { clock: true }),
  // the stylesheets' animations
  'call-out': entry(800, 'A spinner while a call is out, on the button that made it and on the status line.', 'The spinner stands still, a closed ring.', css('rl-spin', 'c-shell.css')),
  'commit-due': entry(2400, 'Today\'s room only: the strip\'s Done for today pulses its outline while the day waits on the seat.', 'The button stands outlined, with no pulse.', css('rl-pulse', 'c-header.css')),
  'name-cursor': entry(1100, 'The cursor after the game\'s name in the header blinks: the screen effect Josh asked for on 14 Nov. It shows no change in the game; it stays as his choice [proposed].', 'The cursor stands still.', css('rl-cursor-blink', 'effects.css')),
  'setup-phrases': entry(12000, 'While the game is set up, its phrases come and go in turn under the crawl: the work is going on.', 'One phrase stands still.', css('rl-intro-phrase', 'p5-crawl.css')),
  'splash-in': entry(600, 'The splash\'s parts fade in once as the seat takes the desk.', 'The parts are there at once.', css('rl-intro-in', 'p5-intro.css')),
  'moves-in': entry(900, 'The older moves map: each move the wake made fades in at its place.', 'The marks stand at their places.', css('rl-moves-in', 'p5-moves.css')),
  'overlay-lines': entry(24000, 'The first wake\'s overlay shows what happened, one line after another.', 'Every line stands at once.', css('rl-ovl-show', 'p5-overlay.css')),
  'overlay-march': entry(1200, 'The first wake\'s overlay: the arrow of each of the first orders marches toward where it goes.', 'The arrows stand still.', css('rl-ovl-march', 'p5-overlay.css')),
  'overlay-goal': entry(2400, 'The first wake\'s overlay: each of the first orders\' goals pulses.', 'The goals stand still.', css('rl-ovl-pulse', 'p5-overlay.css')),
  'playback-step': entry(400, 'The step of the wake now playing comes in as it is reached.', 'Every step stands at once.', css('rl-plb-in', 'p5-overlay.css')),
  'typing': entry(1200, 'Three dots bounce while an answer is being written.', 'The dots stand still.', css('rl-typing-bounce', 'p5-typing.css')),
  // the map's own (the surface lane's files)
  'map-slide': entry(600, 'A piece that changed area slides there on the map; an own piece travels linearly so it reads as a rate.', 'The piece stands in its area.', surface('js/realism-rules.js SLIDE_MS, js/views/realism-territory.js')),
  'map-course': entry(600, 'A course just sent draws itself from the piece to its goal.', 'The course is drawn whole.', surface('js/map/motion.js COURSE_DRAW_MS')),
  'map-fill': entry(600, 'A territory that changed hands fills with its new holder\'s tone.', 'The territory stands filled.', surface('js/map/motion.js FILL_MS')),
  'map-glide': entry(325, 'A pan let go glides on and slows, its speed falling by e every 325 ms; a zoom eases to its step.', 'The map stops where it was let go and zooms in one step.', surface('js/map/gestures.js FRICTION_MS')),
});

/** The time of motion `name`; a name not on the list is an error, so every motion is listed. */
export function motionMs(name) {
  const m = MOTIONS[name];
  if (!m) throw new Error(`motion "${name}" is not on the motion sheet`);
  return m.ms;
}

/** Whether the seat's device asks for reduced motion. */
export const reducedMotion = () => Boolean(globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches);

/** The page's timers, as `{ set(fn, ms), clear(id) }`; a view takes others in a test. */
export const timers = Object.freeze({
  set: (fn, ms) => setTimeout(fn, ms),
  clear: (id) => clearTimeout(id),
});

/** Run `fn` once the page has laid out what was just drawn (next frame), or soon where there are no frames. */
export function afterLayout(fn) {
  const next = globalThis.requestAnimationFrame ?? ((f) => setTimeout(f, 0));
  return next(fn);
}

/**
 * Plays `frames` on `el` once for motion `name`'s time; nothing under reduced motion or where the
 * page cannot animate. Returns the animation, or null.
 */
export function play(el, frames, name, easing = 'ease-in-out') {
  const ms = motionMs(name);
  if (!el || reducedMotion() || typeof el.animate !== 'function') return null;
  return el.animate(frames, { duration: ms, easing });
}

// What was drawn under each key the last time, for the next draw to compare with.
const drawn = new Map();

/** What was drawn under `key` the last time (undefined the first time); keeps `now` for the next. */
export function lastDrawn(key, now) {
  const was = drawn.get(key);
  drawn.set(key, now);
  return was;
}

/** Forgets every value kept between draws. */
export const forgetDrawn = () => drawn.clear();

/**
 * Whether the thing kept as `key` came due on this draw: its day `due` is reached by `today`
 * and either the last draw saw it not yet due, or this is the first draw and today is its day.
 */
export function cameDue(key, due, today) {
  const now = Boolean(due && today && due <= today);
  const was = lastDrawn(`due:${key}`, now);
  return now && (was === false || (was === undefined && due === today));
}

/**
 * Whether the thing kept as `key`, sent as `left` days to go, came due on this draw: it is at 0
 * days and the last draw saw it ahead, or this is the first draw and it is due today.
 */
export function cameDueIn(key, left) {
  const now = Number.isFinite(left) && left <= 0;
  const was = lastDrawn(`due-in:${key}`, now);
  return now && was !== true;
}

/**
 * Writes `say(to)` into `el`; when `from` differs, it first runs from `say(from)` through the
 * numbers between, ending on `to`, over motion `name`'s time. `from` and `to` are lists of numbers.
 */
export function runCount(el, from, to, say, name = 'count-run') {
  const ms = motionMs(name);
  el.textContent = say(to);
  if (!from || reducedMotion() || from.every((n, i) => n === to[i])) return;
  const frames = Math.max(1, Math.round(ms / 50));
  const at = (k) => to.map((n, i) => Math.round(from[i] + ((n - from[i]) * k) / frames));
  el.textContent = say(from);
  for (let k = 1; k <= frames; k += 1) timers.set(() => { el.textContent = say(at(k)); }, (ms * k) / frames);
}

/**
 * A five-step meter kept as `key` stands at `step`; when the last draw had it at another step,
 * the step it left (`steps`, the meter's step elements, first to fifth) is outlined for a moment
 * (`rl-motion-left`), then let go. Nothing under reduced motion. Answers the step it left, or null.
 */
export function stepLeft(steps, key, step) {
  const was = lastDrawn(`meter:${key}`, step);
  if (!Number.isInteger(was) || was === step || was < 1 || reducedMotion()) return null;
  const el = steps?.[was - 1];
  if (!el) return null;
  el.classList.add('rl-motion-left');
  timers.set(() => el.classList.remove('rl-motion-left'), motionMs('step-left'));
  return was;
}

/** Where a sheet comes from and goes back to: the right at the side (`side`), else the foot. */
const offFrame = (side) => ({ opacity: 0, transform: side ? 'translateX(24px)' : 'translateY(24px)' });

/** A sheet just opened slides in from where it opens. */
export function slideIn(sheet, side) {
  return play(sheet, [offFrame(side), { opacity: 1, transform: 'none' }], 'sheet-in', 'ease-out');
}

/**
 * A sheet just closed (`was`, no longer in the page, laid out at `rect` in the viewport) slides
 * back the way it came as a picture, put in `host` where it stood (`host` clips it, so the page
 * never grows wider for it): no id, inert and hidden from a reader, and gone when it has played. Nothing under reduced motion or where the page cannot animate. Answers the picture.
 */
export function slideOut(was, rect, host, side) {
  if (!was || !host || !rect || reducedMotion() || typeof was.animate !== 'function') return null;
  for (const el of [was, ...was.querySelectorAll('[id]')]) el.removeAttribute('id');
  was.className = 'rl-over-ghost';
  was.setAttribute('aria-hidden', 'true');
  was.setAttribute('inert', '');
  const at = host.getBoundingClientRect?.() ?? { left: 0, top: 0 };
  for (const [k, v] of Object.entries({ left: rect.left - at.left, top: rect.top - at.top, width: rect.width, height: rect.height })) {
    was.style?.setProperty(k, `${Math.round(v)}px`);
  }
  host.append(was);
  const gone = () => was.remove();
  const a = play(was, [{ opacity: 1, transform: 'none' }, offFrame(side)], 'sheet-out', 'ease-in');
  if (a) a.onfinish = gone;
  timers.set(gone, motionMs('sheet-out') + 100);
  return was;
}
