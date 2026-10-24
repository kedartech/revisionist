# The realism room as one surface (proposal, built as option A)

Josh's notes 6 to 9 after playing `feat/realism`: the five tabs (In-tray,
Situation, Desk, Orders, Map) split material that one action needs. A directive
is written on the Desk from what an in-tray paper says; a decision due on an
order is taken on the Orders tab; the aide and consult were not in the web room
at all; the map tab was hidden for games begun before positions were kept.

Goal: one view, with the Desk as the working surface. Nothing in it shows more
than the seat's own papers support: every panel is built from the same
`view.realism` block and the same per-seat routes as before.

## Option A: three columns (built)

```
+----------------------------------------------------------------------------------+
| [mark] Game name              | 12 October 1941 · next wake ... | [Advance] [Game]|
|        Playing as Franklin D. Roosevelt, President of the United States   [you] |
+----------------------------------------------------------------------------------+
| (status line: "The wake is running…" while busy)                                  |
+--------------------------+------------------------------------+------------------+
| PAPERS                   | DESK                               | YOUR AIDE        |
| [In-tray 7][Situation]   |  Office, answerable to ...         |  [Brief me]      |
| [Map]          [Widen]   |  Write a directive                 |  summary ...     |
|                          |   To: (o) Cordell Hull             |  Consult         |
|  folder  folder          |           Secretary of State       |   To [..] [Ask]  |
|  folder  folder          |       ( ) Harold Stark             |   past answers   |
|                          |           Chief of Naval Operations|------------------|
|  (an opened paper reads  |   By [..]  Instruction [.....]     | PENDING ORDERS   |
|   here, in its folder,   |   [Prepare the order]              |  ! Lend-Lease .. |
|   with Close folder)     |  Standard forms ...                |    [decide]      |
|                          |  Powers, limits, contacts          |  Escort order .. |
+--------------------------+------------------------------------+------------------+
```

- Left, **Papers**: In-tray, Situation and Map share one reference panel with a
  segmented switch. Opening a paper (from a folder, a situation card or a map
  mark) shows it in this panel, so the desk stays in view while the player
  writes. "Widen" gives the panel the centre's width for the map or a long
  paper; the desk stays one click away.
- Centre, **Desk**: unchanged content, recipient picker shows name and title.
- Right: **Your aide** (brief on demand, consult a contact, earlier answers) on
  top, **Pending orders** below with decisions due first and the step form
  inline.
- Under 1100px the columns stack: Papers, Desk, Aide, Orders.

## Option B: desk with drawers

```
+-------------------------------------------------------------+
| header ...                                                   |
+-----------------------------------------------+-------------+
| [In-tray] [Situation] [Map]  <- open drawers  | PENDING     |
|                                               | ORDERS      |
|  DESK (full width)                            |             |
|                                               | YOUR AIDE   |
|                         +---------------------+             |
|                         | drawer: in-tray     |             |
|                         | slides over the desk|             |
+-------------------------+---------------------+-------------+
```

Wider desk, but a drawer covers part of it, which is the "material in another
tab" problem again in a smaller form.

## Option C: map as the ground

```
+-------------------------------------------------------------+
| header ...                                                   |
+-------------------------------------------------------------+
|  MAP (full bleed)                     +-------------------+ |
|                                       | floating desk     | |
|      marks ...                        | papers / aide     | |
|                                       +-------------------+ |
+-------------------------------------------------------------+
```

Strong look, but many realism worlds have no positions (generated casts, games
begun before the map), so the map cannot be the ground for every game.

## Why A

It is the conservative one: each existing component (folder grid, paper,
desk, tracker, map) moves into a column unchanged; no overlay hides the desk;
it works for a game with no map. B and C stay open if play shows the desk
needs more width.

## Decided (Josh, 24 October 2026)

- The aide briefs itself once per wake. The server keeps each seat's brief for
  the current wake (in memory; a restart costs one more call), and the room asks
  for it when the wake has none, without holding the desk. "Brief me again"
  asks afresh.
- Contact titles come from the public card face's office.
- A player who is not the host can leave a game (below).

## The game menu (note 5)

A "Game" button in the header opens a sheet. The host can Pause, Resume and End
the game; ending asks first and then retires the game exactly as `/retire` does
on Discord (the schedule row is retired, every seat is unlinked, the event log is
kept, no new event). The player then lands on "Start a game". Other players see
that only the host can pause or end it, and can leave: "Leave game…" asks first,
then unlinks only their own seat. Their person stays in the game, played by no
one; the host cannot leave, only end.

Not built, because no backend exists to change it after a game starts:

- the wake cadence (`Settings.tick_hours`) and the end date
  (`Settings.end_date` / `real_days`): set at world load, no event or route
  changes them;
- re-seating a person someone left: the web invites only while the cast is
  being chosen (Discord's `/invite <seat>` works in play);
- live or template prose per game: a server flag (`--offline-prose`), not a
  per-game setting.

The planned Settings screens (`O1`, `O2`: account and agent) are account-level,
not per-game, and are not built here.

## Smoke run

`web/test/e2e/serve_canned.py` serves with template prose and canned model
replies, so `realism_smoke.py BASE new OUT` runs with no model calls. Screens
from the run on this branch: `docs/web-design/shots/realism-room-unify/`.
