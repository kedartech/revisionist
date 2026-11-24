# What the room counts, and how it is drawn

Every number, share, count, band and time left the map-first room and its sheets show, each marked
drawn (and by which mark) or left as words (and why). The four marks are in
`web/js/views/realism-marks.js`: a **bar** (a value against a limit), a **meter** (a band of five
steps), a **track** (time left against a span) and **pips** (a small count). Every mark has the role
of an image and an accessible name that says its number, and shows the number on the mark. A mark
draws only a value the seat's view sends; nothing rests on colour alone. What the game writes
(papers, briefings, messages, the press, a ruling's words) stays writing.

"Built here" marks an entry this list's item draws. "Drawn by" names the screen or item that already
draws it. "Not built" names the value the server would have to send first.

## The bar above the map

| # | What is shown | Drawn or words | Why |
|---|---|---|---|
| 1 | The world date | Words | A date, not a quantity |
| 2 | Time until the wake closes | Words, with the clock icon | Not built: the reply sends the close (`wake.deadline`) but not when the wake opened, so a track has no full length |
| 3 | Players done, of the players in the game | Drawn by the room's bar, the players-done pips, named "1 of 3 players done" | A small count against a limit |
| 4 | The three aims: met, at risk, failed | Drawn by the room's aim marks, by shape | A status, not a number |
| 5 | The count on a sheet tab and on the chat button | A badge with its number | A count to act on, with no limit sent; the badge is its mark |

## What needs you, and the season strip

| # | What is shown | Drawn or words | Why |
|---|---|---|---|
| 6 | The due day of each line | Words | A date; the season's timeline places it |
| 7 | Days to the season's end, and each dated day in it | Drawn by the season's timeline, as a track | |

## The map

| # | What is shown | Drawn or words | Why |
|---|---|---|---|
| 8 | A piece's strength | Pips, on the piece's mark | |
| 9 | A report's strength range | Pips, filled and open | |
| 10 | The days a move's step takes, on a lit area | Words | A time a move would take, with no limit sent; the map is the surface lane's file |
| 11 | A territory's printed yields (economy layer) | Pips, one to three, the numbers on a tap | |
| 12 | A battle's day | Words, in the battle mark's name | A day count with no span |

## The aims sheet (the stakes strip)

| # | What is shown | Drawn or words | Why |
|---|---|---|---|
| 13 | A contest's lean, in steps of ten toward its first side | Drawn by the stakes strip, ten steps named "7 of 10 steps toward ..." | A value against a limit |
| 14 | A contest's and a mandate's days left | Words here; the season's timeline draws them | Plan amendment: the timeline's, not this sheet's |
| 15 | The degree of the win | Words | A grade, not a quantity |
| 16 | The drift from history | Words | Not built: the server sends the drift with no scale |
| 17 | Days to the season's end | Words here; the timeline's track draws it | A contest's time gone needs its whole span, which is not sent |

## The seat's own war economy (on its nation's card)

| # | What is shown | Drawn or words | Why |
|---|---|---|---|
| 18 | Income of each resource | Words | An amount with no limit sent |
| 19 | The output and manpower pools | Words | An amount with no limit sent |
| 20 | The fuel stock | Words | An amount with no limit sent |
| 21 | Months the fuel lasts | **Bar** against twelve months, built here (`fuel_months`) | A time left; twelve is the bar's full length `[proposed]` |
| 22 | What a territory pays against what it prints | **Bar**, built here (paid of printed, per resource) | A value against a limit; the reason stays in words |

## The nations chart and a nation's card

| # | What is shown | Drawn or words | Why |
|---|---|---|---|
| 23 | Each nation's war-economy figure | Drawn by the nations chart, a bar against the largest | |
| 24 | A nation's band at home | Drawn by the nation's card, a meter of five | |

## The home sheet, the court and the orders

| # | What is shown | Drawn or words | Why |
|---|---|---|---|
| 25 | A group's support, step of five | Drawn by the home sheet, a meter, the number on a tap | |
| 26 | Seats in each chamber, and a measure's count | Drawn by the home sheet's seat bars | |
| 27 | How far a group may be moved in a day and a week | Words | A rule, not a reading |
| 28 | A path's steps and the days on each | Drawn by the court's tracks | |
| 29 | A sent order's progress | Drawn by the orders' tracks | |
| 30 | Days left on a suggested action | Words, in its chip | Not built: no span is sent, only the deadline |
| 31 | Days to reach each place in a form | Words | A time a move would take, with no limit |

## An answer to give (the staff's read)

| # | What is shown | Drawn or words | Why |
|---|---|---|---|
| 32 | What the staff expect a choice to move | Drawn by the staff read, step cells | |
| 33 | Escalation, refusal and exposure, level of three | Drawn by the staff read, pips | |
| 34 | The staff's record: right so many of so many | **Bar**, built here (`held` of `checked`) | A value against a limit |

## The odds panel

| # | What is shown | Drawn or words | Why |
|---|---|---|---|
| 35 | The outcome shares: win, neither, loss | Drawn, one bar of three, with its text twin | |
| 36 | Each side's losses, a range in steps | Drawn, a band on a scale | |
| 37 | The chance to take the territory | **Bar** of 100, built here (`taken`), its words kept | Never without its outcome: the bar is named "Taken" |
| 38 | The day it is taken, in half the runs that took it | Words | A day of the fighting, with no limit beyond the runs' days |
| 39 | The risk of being forced back | **Bar** of 100, built here (`forced_back`), its words kept | |
| 40 | The win share at each strength in the reported range | **Columns** of bars, built here (`by_strength`), the reported range marked by a bracket under them `[proposed]`; the table stays as its twin | The reply sends a range, not one reported strength |
| 41 | How many runs the odds come from | Words | A footnote on how they were made |

## The battle sheet

| # | What is shown | Drawn or words | Why |
|---|---|---|---|
| 42 | The seat's strength, and the enemy's as reported | Pips | |
| 43 | Each day's losses, the seat's and the enemy's as reported | **A pair of bars** per day, built here; the table stays as its twin | Each against the largest loss in the rounds shown |
| 44 | The battle's day | Words, in its title | A day count with no span |

## What is built in this item, in list order

21, 22, 34, 37, 39, 40, 43: seven entries, so none is left for a follow-on item. Entries 3 and 13 were drawn already, as marks with their numbers in their names.

## Not built, and what the server would have to send

- 2: when the wake opened, so its time left has a full length.
- 16: a scale for the drift from history.
- 17 and 14: a contest's whole span, so its time gone can be drawn.
- 30: the day a suggested action opened.
