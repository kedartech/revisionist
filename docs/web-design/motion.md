# Motion in the room

Every motion the room plays: what change in the game or in the seat's view it shows, how long it
runs, and what reduced motion shows in its place. The same list, with the same times, is
`MOTIONS` in `web/js/motion.js`, the one module that gives the room its durations and its
reduced-motion check; `web/test/h26-motion.test.js` fails a row missing from either, a time that
differs, and a motion in the board lane's files that does not go through the module.

The rules every motion keeps:

- **It shows a change.** Something changed or is changing in the game or in the seat's view: a
  sheet opening where it was called, a count the server moved, a mark that came due. Nothing moves
  to decorate. A motion plays once for the change it shows (a draw that changes nothing moves
  nothing); the few that run in cycles show a state that lasts (a call out, an answer being
  written, a day waiting on the seat).
- **It never holds a control.** A sheet is in the page, its controls live, before it has slid in;
  a closed sheet is gone at once and what slides out is a picture that cannot be pressed or read.
  No motion waits before a redraw, a focus move or a send.
- **Reduced motion shows the end state.** Under `prefers-reduced-motion: reduce` the module plays
  nothing and `c-base.css` stops every stylesheet animation: each motion's end state stands at
  once, with its words. The column below says what stands in its place.
- **It takes its time from the module.** A view never calls `animate`, sets a timer or a frame
  for a motion, or reads the reduced-motion setting itself: it calls `play`, `runCount`,
  `stepLeft`, `slideIn` or `slideOut` with a motion's name from this list. A name not on the list
  is an error.
- **Its colour is the theme's.** Amber for what is due or live, red for what is hostile or lost,
  neutral for the rest; the step a meter left is drawn by outline and place, not by a hue.

Times marked as chosen here are `[proposed]`: 200 ms for a sheet (the item's own default), and the
first set's other times (500 ms for a round's bars, 900 ms for a mark that came due, 400 ms for a
new mark, 600 ms for a nation's bar, 1200 ms for the step a meter left).

## The first set (built with this sheet)

Each of these is new with this sheet.

| Motion | The change it shows | How long | Under reduced motion | Where |
|---|---|---|---|---|
| `sheet-in` | A sheet opening slides in from where it opens: from the right at 1024 px and over, from the foot below. | 200 ms, once | The sheet is there at once. | js/views/realism-sheets.js, from the room's redraw |
| `sheet-out` | A sheet closing slides back the way it came; the map under it is live at once, the sheet leaving is a picture no one can press or read. | 200 ms, once | The sheet is gone at once. | js/views/realism-sheets.js, from the room's redraw |
| `battle-round` | A day's round of a battle the sheet has not drawn before: its two bars, the seat's losses and the enemy's as reported, grow from the foot to their length. | 500 ms, once | The bars stand at their length; the day table under them says the same losses in words. | js/views/realism-battle.js |
| `timeline-due` | A mark on the season's timeline that came due since the strip last drew flashes once. | 900 ms, once | The mark is drawn as due (its outline), with no flash. | js/views/realism-timeline.js |
| `timeline-new` | A dated thing new to the strip since it last drew drops into its place on the line. | 400 ms, once | The mark stands in its place. | js/views/realism-timeline.js |
| `nation-bar` | A nation's bar on the chart runs from its old length to its new one when its figure changes. | 600 ms, once | The bar stands at its new length beside its new figure. | js/views/realism-nations.js |
| `step-left` | A five-step meter that moved a step (a piece's figure, a nation's standing at home, a bloc's support) shows the step it left, outlined, for a moment. | 1200 ms, once | The meter shows its new step; its name says the step in words. | js/views/realism-piece.js, realism-nations.js, realism-capital.js |

## The Capital board's tracks

Built before this sheet; their times now come from the module.

| Motion | The change it shows | How long | Under reduced motion | Where |
|---|---|---|---|---|
| `track-marker` | An order's marker slides along its track to the step that now holds it. | 600 ms, once | The marker stands at its step. | js/views/realism-tracks.js, realism-capital.js |
| `bloc-part` | The blocs' parts of a vote's track slide to their new widths when the count changes; a bloc new to it fades in. | 600 ms, once | The parts stand at their widths. | js/views/realism-capital.js |
| `count-run` | A vote's count runs from the old number to the new one the server sent. | 600 ms, once | The new count is written at once. | js/views/realism-capital.js |
| `offer-in` | An offer filed draws its part of the track in from the bloc that takes it. | 600 ms, once | The part stands on the track. | js/views/realism-capital.js |
| `promise-due` | A promise that came due flashes once on the board and on the timeline. | 900 ms, once | The promise is drawn as due, with no flash. | js/views/realism-capital.js, realism-timeline.js |

## The wake's playback and the opening's crawl

Built before this sheet; their clocks now come from the module.

| Motion | The change it shows | How long | Under reduced motion | Where |
|---|---|---|---|---|
| `wake-day` | One world day of a wake's playback: every own piece that moved runs its step at its own rate, the day and its bar run with it. | 400 ms a world day | Every frame of the wake stands still at once, each with its day. | js/views/realism-playback.js, on the map's clock |
| `wake-cap` | The longest a wake's playback runs; a longer wake runs its clock faster. | 20000 ms at most | As above. | js/views/realism-playback.js |
| `crawl-char` | The setting's crawl types itself, a character at a time (forty a second), as the game is set up. | 25 ms a character | Every paragraph is whole at once. | js/views/realism-crawl.js |
| `crawl-pause` | The pause between two paragraphs of the crawl. | 600 ms, once | No pause. | js/views/realism-crawl.js |

## The stylesheets' animations

Built before this sheet. A stylesheet cannot import the module, so each is listed by its keyframes at the time its stylesheet gives it, and the motion test holds the two to each other. `c-base.css` stops every one of them under reduced motion.

| Motion | The change it shows | How long | Under reduced motion | Where |
|---|---|---|---|---|
| `call-out` | A spinner while a call is out, on the button that made it and on the status line. | 800 ms a cycle, while it lasts | The spinner stands still, a closed ring. | css/c-shell.css (@keyframes rl-spin) |
| `commit-due` | Today's room only: the strip's Done for today pulses its outline while the day waits on the seat. | 2400 ms a cycle, while it lasts | The button stands outlined, with no pulse. | css/c-header.css (@keyframes rl-pulse) |
| `name-cursor` | The cursor after the game's name in the header blinks: the screen effect Josh asked for on 14 Nov. It shows no change in the game; it stays as his choice [proposed]. | 1100 ms a cycle, while it lasts | The cursor stands still. | css/effects.css (@keyframes rl-cursor-blink) |
| `setup-phrases` | While the game is set up, its phrases come and go in turn under the crawl: the work is going on. | 12000 ms a cycle, while it lasts | One phrase stands still. | css/p5-crawl.css (@keyframes rl-intro-phrase) |
| `splash-in` | The splash's parts fade in once as the seat takes the desk. | 600 ms, once | The parts are there at once. | css/p5-intro.css (@keyframes rl-intro-in) |
| `moves-in` | The older moves map: each move the wake made fades in at its place. | 900 ms, once | The marks stand at their places. | css/p5-moves.css (@keyframes rl-moves-in) |
| `overlay-lines` | The first wake's overlay shows what happened, one line after another. | 24000 ms a cycle, while it lasts | Every line stands at once. | css/p5-overlay.css (@keyframes rl-ovl-show) |
| `overlay-march` | The first wake's overlay: the arrow of each of the first orders marches toward where it goes. | 1200 ms a cycle, while it lasts | The arrows stand still. | css/p5-overlay.css (@keyframes rl-ovl-march) |
| `overlay-goal` | The first wake's overlay: each of the first orders' goals pulses. | 2400 ms a cycle, while it lasts | The goals stand still. | css/p5-overlay.css (@keyframes rl-ovl-pulse) |
| `playback-step` | The step of the wake now playing comes in as it is reached. | 400 ms, once | Every step stands at once. | css/p5-overlay.css (@keyframes rl-plb-in) |
| `typing` | Three dots bounce while an answer is being written. | 1200 ms a cycle, while it lasts | The dots stand still. | css/p5-typing.css (@keyframes rl-typing-bounce) |

## The map's own motions (the surface lane's files)

Listed so this sheet is the room's whole list. They are timed and checked in the surface lane's own files, not through this module; the motion test checks only that their times are the ones written here.

| Motion | The change it shows | How long | Under reduced motion | Where |
|---|---|---|---|---|
| `map-slide` | A piece that changed area slides there on the map; an own piece travels linearly so it reads as a rate. | 600 ms, once | The piece stands in its area. | surface lane: js/realism-rules.js SLIDE_MS, js/views/realism-territory.js |
| `map-course` | A course just sent draws itself from the piece to its goal. | 600 ms, once | The course is drawn whole. | surface lane: js/map/motion.js COURSE_DRAW_MS |
| `map-fill` | A territory that changed hands fills with its new holder's tone. | 600 ms, once | The territory stands filled. | surface lane: js/map/motion.js FILL_MS |
| `map-glide` | A pan let go glides on and slows, its speed falling by e every 325 ms; a zoom eases to its step. | 325 ms, once | The map stops where it was let go and zooms in one step. | surface lane: js/map/gestures.js FRICTION_MS |

## Found while listing

- **The cursor after the game's name blinks** (`name-cursor`). It shows no change in the game, so
  under this sheet's first rule it would go. It is kept, and listed, because Josh asked for the
  screen effects on 14 Nov and its test (`web/test/cur-effects.test.js`) pins it; whether it stays
  is his call `[proposed]: keep`.
- **The strip's Done for today pulses** (`commit-due`) in today's room only, for as long as the
  day waits on the seat. It is read here as showing a state that lasts (the day is due), and kept.

## Not built

Each of these would move something on screen, and is not built, for the reason given.

- **Supply and aid moving along their routes.** A route is drawn, but the seat's reply sends no
  progress along it (no day a shipment set out or where it stands on the way), so the room has
  nothing to move a convoy by. It needs the reply to send a route's progress: a server item that
  changes the seat's view.
- **A count moving between wakes.** World time advances only when a wake closes, so between wakes
  nothing in the game changes on its own; the room draws where each thing stands, and the wake's
  playback is where things move at their own rate.
- **Another side's piece moving along its way.** A sighting is never drawn in transit: the seat
  knows where it was reported, not where it is on its way.
- **A contest's time gone running along the season's timeline.** The view sends a contest's days
  left but not its whole span, so the line shows days left only and nothing runs along it.
- **Trend lines for a nation's economy and standing.** The server sends no history; decided on 21
  Nov not to build in this run.
- **The Capital board's blocs moving in the wake's playback.** The playback moves the pieces on the
  map and the groups and counts on the floor; the Capital board shows each count as it stands,
  and runs it only when a new view changes it (`count-run`, `bloc-part`).
- **A sheet sliding in the classic layout.** The classic room has no sheets: its panels stand in
  place, so there is nothing to slide.
