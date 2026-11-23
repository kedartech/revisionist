# Map spike: three projections and three ways of drawing, measured

Taken on 22 Nov 2026 from the branch `r3/surface-msp` (base `b294dbc`). Nothing here is loaded by the game.

- `index.html` — the proof page. Open it from the file system; no server. It draws the built 1941 map
  (`worlds/maps/autumn-1941.json`, 360 degrees wide, box `[-126, -11.5, 234, 71.5]`) in Equal Earth,
  Natural Earth and Miller, each centred on the map's middle (54° east), beside what the game draws today
  (one cosine of the middle latitude, 30°, for the whole map), at the whole map and at two region frames
  (Europe, and China, the world's `pacific` region). Each frame is the box around its region's areas, as the
  game works it out.
- `spike.js` — the page's drawing and the timing bench (`index.html?bench=viewbox|transform|canvas`).
- `map-data.js` — the built map and its areas' names, kinds and regions, as a script so the page opens from
  the file system. Written by `map_spike.py data`, which refuses if the map's sha256 is not the world file's.
- `results.json` (the deciding run, four times slower) and `results-1x.json` (a reference run, not slowed):
  every run's summary and every frame's time.
- `shots/` — the proof page at both widths, and the bench's first frame for each method at both sizes.

## The commands

From the worktree root:

```
uv run --frozen python web/test/e2e/map_spike.py data
docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v $PWD:/wt -w /wt \
  -v <dir holding the playwright 1.49.0 Python package>:/pylib:ro -e PYTHONPATH=/pylib \
  mcr.microsoft.com/playwright/python:v1.49.0-noble \
  python web/test/e2e/map_spike.py measure                  # results.json and shots/
# the same with `measure --slowdown 1` for results-1x.json
```

Browser: Chromium 131.0.6778.33, headless, in the Playwright container (no GPU: software raster).

## What the bench does

The whole map in Equal Earth fills the screen at zoom 1 and is panned and zoomed by one fixed path for ten
seconds: the zoom goes from 1 to 8 and back twice while the middle of the view loops across the map. Every
area name and a counter on each land area are drawn over the land and resized each frame so they keep their
pixel size, as the game's `fit` does today. One second of motion is run first and not counted. Each method
runs twice per size, the order of methods reversed on the second run.

- **viewbox**: one SVG; its `viewBox` is set each frame.
- **transform**: one SVG with a fixed `viewBox`; one group inside it is moved by a `transform` each frame.
- **canvas**: land, coasts, borders and the graticule are drawn on a canvas each frame (colours read from
  `web/css/tokens.css`), under an SVG that holds only the names and counters.

Sizes: 1440 by 900 at pixel density 1, and 390 by 844 at pixel density 3 with touch and mobile on (the
phone run). Both are run with Chromium's processor slowdown at four times. A frame's time is the gap
between two animation frames, so it comes in steps of one frame interval (16.7 ms).

## The numbers

Deciding run, processor four times slower (`results.json`; host load 17.4 at the start, 17.8 at the end,
on 24 cores):

| Size | Method | Frames | Median (ms) | 95th percentile (ms) | Run 1 / run 2 p95 | Frames a second |
|---|---|---|---|---|---|---|
| 1440 × 900 | viewbox | 225 | 83.4 | 116.6 | 116.7 / 100.1 | 11.2 |
| 1440 × 900 | transform | 225 | 83.4 | 100.1 | 100.1 / 100.1 | 11.2 |
| 1440 × 900 | canvas | 198 | 83.4 | 183.4 | 199.9 / 183.3 | 9.8 |
| 390 × 844 | viewbox | 356 | 50.1 | 66.8 | 66.7 / 66.8 | 17.6 |
| 390 × 844 | transform | 371 | 50.0 | 66.7 | 66.7 / 83.3 | 18.5 |
| 390 × 844 | canvas | 177 | 100.1 | 166.7 | 183.4 / 166.6 | 8.7 |

Reference run, processor not slowed (`results-1x.json`; host load 17.8 at the start, 13.9 at the end):

| Size | Method | Frames | Median (ms) | 95th percentile (ms) | Run 1 / run 2 p95 | Frames a second |
|---|---|---|---|---|---|---|
| 1440 × 900 | viewbox | 249 | 83.3 | 100.0 | 100 / 83.4 | 12.4 |
| 1440 × 900 | transform | 241 | 83.3 | 100.0 | 100.1 / 100 | 11.9 |
| 1440 × 900 | canvas | 803 | 16.7 | 50.0 | 50 / 50 | 40.0 |
| 390 × 844 | viewbox | 797 | 33.2 | 33.4 | 33.4 / 33.4 | 39.7 |
| 390 × 844 | transform | 825 | 16.7 | 33.4 | 33.4 / 33.4 | 41.1 |
| 390 × 844 | canvas | 905 | 16.7 | 33.4 | 33.4 / 33.4 | 45.2 |

The page's own work each frame (setting the view and resizing the names and counters) was at most 4.5 ms
at the 95th percentile in every run; the rest of each frame is the browser drawing.

## The recommendation

The rule (contract, `[proposed]`): the transform if its 95th percentile is 33 ms or less on the phone run,
else the canvas layer. On the phone run the transform's 95th percentile is **66.7 ms**, so the rule gives
**the canvas layer: land and borders drawn on a canvas, the marks kept in SVG.**

Read with it:

1. **The transform buys nothing over the view box here.** The two SVG methods are within one frame interval
   of each other in every run: moving a group by a transform still has Chromium redraw the whole SVG.
2. **The slowdown falls on the canvas only.** Chromium's processor slowdown slows the page's main thread,
   where a canvas is drawn; SVG is rasterised on other threads that are not slowed. So the deciding run
   charges the canvas for the slowdown and not the SVG. With nothing slowed, the canvas is the fastest of the
   three: at 1440 by 900, 40 frames a second against 12 for either SVG method, and level with them on the
   phone size. The SVG methods do not get faster without the slowdown (83 ms median at 1440 either way):
   drawing 1.2 MB of paths at every frame is their cost, and a slower phone pays it on every thread.
3. **The canvas here is the plain version**: it redraws every path of the whole map every frame, with no
   cut to the part in view and no cached picture. The drag item can make it cheaper.

## Findings for the items that follow

- **For the proper projection:** a straight edge in longitude and latitude is a curve in Equal Earth and
  Natural Earth. The Pacific sea zones store only their corners, so projected point by point their edges are
  drawn as chords across the curved meridians. The page cuts every edge longer than a degree into one-degree
  steps before projecting; the projection item needs the same step, or the sea zones will look wrong.
- **For the proper projection:** Miller stretches the high latitudes (its Europe frame is the tallest of the
  four); in Equal Earth and Natural Earth the far east and far west of the 360-degree map lean in towards
  the poles. Europe,
  near the middle meridian, is least changed by the choice; China and the Pacific, about 50 to 180 degrees from
  the middle, show the difference most.
- **For the drag item:** if the canvas layer is taken, land and borders move to it and the marks stay SVG
  (the contract's Unclear line). The marks' layer must follow the same view each frame; here it is moved
  by its `viewBox`, which cost about 2 ms a frame at the 95th percentile for 111 names and 82 counters.

## What this does not show

- The phone run is a slowed desktop browser in a container with no GPU, not a phone, and the slowdown does
  not reach the raster threads. A real mid-range phone is Josh's or COD3's check, not a lane step.
- The host was running other lanes' test suites (load 14 to 18 on 24 cores); repeated runs moved by one or
  two frame intervals.
- The projection is Josh's pick from the page; with no pick, the projection item takes Equal Earth.

## The screenshots

The proof page: [1440 by 900](shots/proof-desktop.png), [390 by 844](shots/proof-phone.png).

The bench's first frame (the three methods draw the same picture):
viewbox [desktop](shots/bench-viewbox-desktop.png) / [phone](shots/bench-viewbox-phone.png),
transform [desktop](shots/bench-transform-desktop.png) / [phone](shots/bench-transform-phone.png),
canvas [desktop](shots/bench-canvas-desktop.png) / [phone](shots/bench-canvas-phone.png).
