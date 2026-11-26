"""Browser smoke of the map as a surface: it follows the finger, zooms, and a piece is carried.

Signs up a fresh account and either joins a game with an invite code or, with the code `new`,
starts the ready-made 1941 game as its host and plays Franklin D. Roosevelt. Then, on the map:

- a drag moves the land and the marks before the finger lifts, and the room keeps the new view;
- a pinch of two touches zooms to its spread, not to a step, and the wheel zooms (desktop);
- the arrow keys pan the map and the plus key zooms it, from the keyboard alone;
- one of the seat's own pieces is picked, the map is panned, and a lit place is tapped and chosen;
- one of the seat's own pieces is carried by the finger (the mouse at desktop width) to a lit area:
  it is picked up, its moves light, the map holds still, the lit area under it is marked, the drop
  opens the confirm chip and nothing is filed until Send it; carried to an area that is not lit it
  goes back and nothing is drafted; and the same move is made from the keyboard alone;
- the map's controls sit over it, a press on one does not pan the map, and the map is clear of
  them for at least 65 percent of the viewport's height at 1440 by 900 and 55 at 390 by 844;
  Full screen (pointer) and F (keyboard) give the map the whole viewport and keep its view, a
  piece is carried to a lit area there, a piece's sheet opens over it and Escape closes the sheet
  before it leaves full screen, and the view is the same when it has left;
- the app shell is installable: the page's manifest names the app, starts at `/`, opens standalone
  and lists three icons, each of which answers as a PNG of its stated size, and the page marks
  itself as a tab or as the app;
- the map is panned and pinched for ten seconds with the processor slowed four times, and the
  time between frames is read: on the phone run the 95th percentile must be at or under 33.4 ms,
  two frame intervals (a frame's time comes in steps of 16.7 ms);
- the offline shell, in a context of its own with the same session: the room loads once and its
  service worker takes control; the worker's stores hold the page and the map object by its hash
  and nothing under `/api/`; with the network cut a reload opens the shell with its one offline
  line and a write does not get through; a new worker is offered as a new version, nothing
  changes until Reload is pressed, and then the new worker controls the reloaded page;
- pieces under way, in a context of its own whose replies put six of the seat's pieces on steps
  at six shares of their days: each is drawn at its share between its two areas with its tag
  and the part travelled; the playback's clock carries all six to the areas they enter, and on
  the phone run the 95th percentile frame time while they move is at or under the same line; a
  move sent from the keyboard draws its line from the piece to its goal, whole within 600 ms; and
  under reduced motion the same pieces stand at their shares with their tags and nothing moves;
- what the Android wrapper needs of the web side (`deploy/android/README.md`): the manifest the
  page links, the worker in control, the 512 px icon, and the asset-links address, which answers
  with a list naming an Android app when `REVISIONIST_ASSETLINKS_FILE` is set in the smoke's
  environment (the same value the server was started with) and is a 404 when it is not.

Screenshots, a ten-second recording of the same pan and pinch (not slowed) and `report.json` go to
OUT_DIR. With a fourth argument `phone` it runs at 390x844 with touch, else at 1440x900. Fails on
any console error, page error, failed request or request to another origin, or any named check
that does not hold.

    python web/test/e2e/surface_smoke.py BASE_URL INVITE_CODE|new OUT_DIR [phone]

For a run with no model calls, serve with web/test/e2e/serve_canned.py.
"""

import json
import os
import sys
import time

import realism_smoke as rs
from playwright.sync_api import CDPSession, Page, sync_playwright

BASE, CODE, OUT = rs.BASE, rs.CODE, rs.OUT
PHONE, SIZE = rs.PHONE, rs.SIZE
SLOWDOWN = 4
FRAME_LINE_MS = 33.4
"""The phone run's 95th percentile frame time while the map moves, slowed four times. [proposed]"""
RUN_MS = 10_000
MAP = "main.rl-mapfirst svg.rl-tm-svg, svg.rl-tm-svg"

VIEW_JS = """(sel) => {
  const svg = document.querySelector(sel);
  if (!svg) return null;
  const [x, y, w, h] = svg.getAttribute('viewBox').split(' ').map(Number);
  const r = svg.getBoundingClientRect();
  return { x, y, w, h, left: r.left, top: r.top, width: r.width, height: r.height,
    frame: svg.getAttribute('data-frame') };
}"""

LIVE_JS = """(sel) => {
  const svg = document.querySelector(sel);
  const live = document.querySelector('svg.rl-tm-live');
  return { transform: svg?.style.transform ?? '', layer: !!live,
    marks: live ? live.querySelectorAll('.rl-tm-px').length : 0 };
}"""

DRIVE_JS = """async ([sel, ms]) => {
  // One long gesture driven a frame at a time: a pan on a loop, a pinch that opens and closes
  // while its middle drifts, then the pan again. Each frame's time is the gap between two frames.
  const svg = document.querySelector(sel);
  const r = svg.getBoundingClientRect();
  const cx = r.left + r.width / 2; const cy = r.top + r.height / 2;
  const reach = Math.min(r.width, r.height) * 0.25;
  const send = (type, id, x, y) => svg.dispatchEvent(new PointerEvent(type, {
    pointerId: id, clientX: x, clientY: y, bubbles: true, cancelable: true, isPrimary: id === 1,
    pointerType: 'touch', button: 0,
  }));
  return await new Promise((resolve) => {
    const frames = [];
    let t0 = null; let last = null; let two = false;
    send('pointerdown', 1, cx, cy);
    const step = (now) => {
      if (t0 === null) t0 = now;
      const t = (now - t0) / ms;
      if (last !== null) frames.push(now - last);
      last = now;
      if (t >= 1) {
        if (two) send('pointerup', 2, cx, cy);
        send('pointerup', 1, cx, cy);
        resolve(frames);
        return;
      }
      const a = 2 * Math.PI * t * 3;
      const px = cx + reach * Math.sin(a); const py = cy + reach * 0.6 * Math.sin(2 * a);
      const pinching = t > 0.3 && t < 0.7;
      if (pinching && !two) { send('pointerdown', 2, px + 30, py); two = true; }
      if (!pinching && two) { send('pointerup', 2, px + 30, py); two = false; }
      if (two) {
        const spread = 30 + reach * (0.5 - 0.5 * Math.cos(2 * Math.PI * (t - 0.3) / 0.2));
        send('pointermove', 1, px - spread, py);
        send('pointermove', 2, px + spread, py);
      } else send('pointermove', 1, px, py);
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}"""


def view(page: Page) -> dict:
    return page.evaluate(VIEW_JS, MAP)


def settle(page: Page, ms: int = 1500) -> dict:
    """Wait for the slide to stop and the room to draw the view it was told."""
    page.wait_for_timeout(ms)
    page.locator(MAP).first.wait_for(timeout=10_000)
    return view(page)


def touch(cdp: CDPSession, kind: str, points: list[tuple[float, float]]) -> None:
    cdp.send(
        "Input.dispatchTouchEvent",
        {
            "type": kind,
            "touchPoints": [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(points)],
        },
    )


def drag(page: Page, cdp: CDPSession, x: float, y: float, dx: float, dy: float) -> dict:
    """Drag from (x, y) by (dx, dy) in ten steps; what the map showed before the lift."""
    steps = 10
    if PHONE:
        touch(cdp, "touchStart", [(x, y)])
    else:
        page.mouse.move(x, y)
        page.mouse.down()
    for i in range(1, steps + 1):
        at = (x + dx * i / steps, y + dy * i / steps)
        if PHONE:
            touch(cdp, "touchMove", [at])
        else:
            page.mouse.move(*at)
        page.wait_for_timeout(16)
    page.wait_for_timeout(50)
    during = page.evaluate(LIVE_JS, MAP)
    if PHONE:
        touch(cdp, "touchEnd", [])
    else:
        page.mouse.up()
    return during


def pinch(page: Page, cdp: CDPSession, x: float, y: float, d0: float, d1: float) -> None:
    steps = 10
    touch(cdp, "touchStart", [(x - d0 / 2, y), (x + d0 / 2, y)])
    for i in range(1, steps + 1):
        d = d0 + (d1 - d0) * i / steps
        touch(cdp, "touchMove", [(x - d / 2, y), (x + d / 2, y)])
        page.wait_for_timeout(16)
    touch(cdp, "touchEnd", [])


def p95(xs: list[float]) -> float:
    s = sorted(xs)
    return round(s[int(0.95 * (len(s) - 1))], 1) if s else 0.0


def start(page: Page) -> None:
    page.goto(BASE + "/")
    page.get_by_role("link", name="Create an account").click()
    page.get_by_role("heading", name="Create an account").wait_for()
    page.get_by_label("Handle").fill(f"msmoke{int(time.time()) % 100000}")
    page.get_by_label("Password").fill("a long enough passphrase")
    page.get_by_role("button", name="Create account").click()
    page.get_by_role("heading", name="Your recovery codes").wait_for()
    page.get_by_label("I've kept these somewhere safe").check()
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("heading", name="Join a game").wait_for()
    if CODE == "new":
        page.get_by_role("link", name="Start a new game").click()
        page.get_by_role("button", name="Start Autumn 1941").click()
        page.get_by_role("heading", name="Choose who you will play").wait_for(timeout=30_000)
        rs.show_everyone(page)
        rs.play_from_dossier(page, {}, "Franklin D. Roosevelt")
        page.get_by_role("button", name="Begin the game").wait_for(timeout=60_000)
        rs.begin_with_crawl(page, {})
    else:
        page.get_by_label("Invite code").fill(CODE)
        page.get_by_role("button", name="Join").click()
    page.locator("main.rl-board, main.rl-mapfirst").first.wait_for(timeout=60_000)
    page.wait_for_timeout(300)
    rs.through_intro(page, {})
    page.locator(MAP).first.wait_for(timeout=30_000)


def follows(page: Page, cdp: CDPSession, report: dict) -> None:
    """The drag, the pinch, the wheel and the keys."""
    v0 = view(page)
    report["view_start"] = v0
    cx, cy = v0["left"] + v0["width"] / 2, v0["top"] + v0["height"] / 2
    pinch(page, cdp, cx, cy, 80, 200)
    v1 = settle(page)
    zoom = v0["w"] / v1["w"]
    report["pinch_zoom"] = round(zoom, 3)
    rs.check(
        "a pinch zooms to its spread, not to a step",
        2.0 < zoom < 3.0 and abs(zoom - 2.5) < 0.4,
        f"{zoom:.3f}",
    )
    during = drag(page, cdp, cx, cy, -120, -40)
    report["drag_during"] = during
    rs.check(
        "the land moves under the finger before it lifts",
        during["transform"].startswith("translate(") and during["layer"],
        json.dumps(during),
    )
    rs.check("the marks ride over the land while it moves", during["marks"] > 0, str(during))
    rs.shoot(page, "mpn-01-dragging")
    v2 = settle(page)
    report["view_after_drag"] = v2
    rs.check(
        "the room keeps the view the drag left",
        v2["x"] > v1["x"] and abs(v2["w"] - v1["w"]) < 1e-6 * max(v1["w"], 1),
        f"{v1['x']} -> {v2['x']}",
    )
    if not PHONE:
        page.mouse.move(cx, cy)
        page.mouse.wheel(0, -300)
        v3 = settle(page)
        report["wheel_zoom"] = round(v0["w"] / v3["w"], 3)
        rs.check("the wheel zooms in", v3["w"] < v2["w"], f"{v2['w']} -> {v3['w']}")
    page.locator(MAP).first.focus()
    before = view(page)
    page.keyboard.press("ArrowLeft")
    after = settle(page, 800)
    rs.check("the left arrow key pans the map", after["x"] < before["x"], f"{before} {after}")
    page.locator(MAP).first.focus()
    page.keyboard.press("+")
    zoomed = settle(page, 800)
    rs.check("the plus key zooms in", zoomed["w"] < after["w"], f"{after['w']} -> {zoomed['w']}")
    rs.shoot(page, "mpn-02-panned-zoomed")


def tap_after_pan(page: Page, cdp: CDPSession, report: dict) -> None:
    """Pick one of the seat's own pieces, pan the map, then tap a lit place."""
    page.get_by_role("button", name="Zoom 1 times").first.click()
    settle(page, 500)
    own = page.evaluate(
        """() => {
      for (const m of document.querySelectorAll('.rl-tm-svg .rl-mk.rl-side-own')) {
        const r = m.getBoundingClientRect();
        const x = r.left + r.width / 2; const y = r.top + r.height / 2;
        const on = document.elementFromPoint(x, y);
        if (on && m.contains(on)) return { x, y, label: m.getAttribute('aria-label') };
      }
      return null;
    }"""
    )
    rs.check("one of the seat's own pieces can be reached", own is not None)
    if own is None:
        return
    report["picked"] = own["label"]
    if PHONE:
        page.touchscreen.tap(own["x"], own["y"])
    else:
        page.mouse.click(own["x"], own["y"])
    page.locator(".rl-map-target").first.wait_for(timeout=10_000)
    v = view(page)
    drag(page, cdp, v["left"] + v["width"] * 0.5, v["top"] + v["height"] * 0.7, 30, 0)
    settle(page)
    rs.check(
        "the piece stays picked after a pan",
        page.locator(".rl-map-target").count() > 0,
    )
    spot = page.evaluate(
        """() => {
      for (const t of document.querySelectorAll('.rl-map-target:not([aria-disabled=true])')) {
        const r = t.querySelector('circle').getBoundingClientRect();
        const x = r.left + r.width / 2; const y = r.top + r.height / 2;
        if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) continue;
        const on = document.elementFromPoint(x, y);
        if (on && t.contains(on)) return { x, y, label: t.getAttribute('aria-label') };
      }
      return null;
    }"""
    )
    rs.check("a lit place can be reached after a pan", spot is not None)
    if spot is None:
        return
    report["tapped"] = spot["label"]
    if PHONE:
        page.touchscreen.tap(spot["x"], spot["y"])
    else:
        page.mouse.click(spot["x"], spot["y"])
    page.wait_for_timeout(400)
    rs.check(
        "a tap on a lit place after a pan chooses it",
        page.locator(".rl-map-target[aria-pressed=true]").count() == 1,
        spot["label"],
    )
    rs.shoot(page, "mpn-03-tap-after-pan")
    page.keyboard.press("Escape")


OWN_JS = """() => {
  // one of the seat's own pieces that can be carried, reachable under the pointer
  for (const m of document.querySelectorAll('.rl-tm-svg .rl-tm-mark[data-grab]')) {
    const r = m.querySelector('.rl-tm-hit').getBoundingClientRect();
    const x = r.left + r.width / 2; const y = r.top + r.height / 2;
    if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) continue;
    const on = document.elementFromPoint(x, y);
    if (on && m.contains(on)) return { x, y, name: m.getAttribute('data-grab') };
  }
  return null;
}"""

LIT_JS = """() => {
  // a lit area's ring the pointer can reach, the piece held over the map
  for (const t of document.querySelectorAll('.rl-map-target:not([aria-disabled=true])')) {
    const r = t.querySelector('circle').getBoundingClientRect();
    const x = r.left + r.width / 2; const y = r.top + r.height / 2;
    if (x < 8 || y < 8 || x > innerWidth - 8 || y > innerHeight - 8) continue;
    const on = document.elementFromPoint(x, y);
    if (on && t.contains(on)) {
      return { x, y, area: t.getAttribute('data-area'), label: t.getAttribute('aria-label') };
    }
  }
  return null;
}"""

UNLIT_JS = """(sel) => {
  // a point of the map over an area that is not lit, well away from every lit ring
  const svg = document.querySelector(sel);
  const b = svg.getBoundingClientRect();
  const targets = [...document.querySelectorAll('.rl-map-target')];
  const lit = new Set(targets.map((t) => t.getAttribute('data-area')));
  const rings = targets.map((t) => t.querySelector('circle').getBoundingClientRect());
  const left = Math.max(b.left, 0) + 60; const right = Math.min(b.right, innerWidth) - 60;
  const top = Math.max(b.top, 0) + 60; const bottom = Math.min(b.bottom, innerHeight) - 60;
  for (let y = top; y < bottom; y += 23) {
    for (let x = left; x < right; x += 23) {
      const on = document.elementFromPoint(x, y);
      if (!on || !on.matches('.rl-tm-svg path.rl-area')) continue;
      if (lit.has(on.getAttribute('data-area'))) continue;
      const far = (r) => Math.hypot(x - (r.left + r.width / 2), y - (r.top + r.height / 2)) >= 80;
      if (!rings.every(far)) continue;
      return { x, y, area: on.getAttribute('data-area') };
    }
  }
  return null;
}"""

HELD_JS = """() => {
  const areas = (sel) => [...document.querySelectorAll(sel)].map((t) => t.dataset.area);
  const lifted = [...document.querySelectorAll('.rl-tm-lifted')];
  return { under: areas('.rl-map-target.under'), lifted: lifted.length,
    shift: lifted[0]?.parentNode.style.transform ?? '',
    chosen: areas('.rl-map-target[aria-pressed=true]'),
    chip: !!document.querySelector('.rl-pup-chip'), lit: areas('.rl-map-target').length };
}"""


FOCUS_JS = """(name) => {
  // focus piece `name`, or the first own piece that can be carried; its name
  const all = [...document.querySelectorAll('.rl-tm-svg .rl-tm-mark[data-grab]')];
  const m = name === null ? all[0] : all.find((x) => x.getAttribute('data-grab') === name);
  m?.focus();
  return m?.getAttribute('data-grab') ?? null;
}"""


def press(page: Page, cdp: CDPSession, x: float, y: float) -> None:
    if PHONE:
        touch(cdp, "touchStart", [(x, y)])
    else:
        page.mouse.move(x, y)
        page.mouse.down()


def move(
    page: Page, cdp: CDPSession, a: tuple[float, float], b: tuple[float, float], steps: int
) -> None:
    for i in range(1, steps + 1):
        at = (a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps)
        if PHONE:
            touch(cdp, "touchMove", [at])
        else:
            page.mouse.move(*at)
        page.wait_for_timeout(16)


def release(page: Page, cdp: CDPSession) -> None:
    if PHONE:
        touch(cdp, "touchEnd", [])
    else:
        page.mouse.up()


def detail(page: Page, name: str, x: float, y: float) -> None:
    """A close shot around (x, y): at 1440 wide the whole map is small."""
    w, h = min(480, SIZE[0]), min(320, SIZE[1])
    left = min(max(x - w / 2, 0), SIZE[0] - w)
    top = min(max(y - h / 2, 0), SIZE[1] - h)
    clip = {"x": left, "y": top, "width": w, "height": h}
    page.screenshot(path=str(rs.OUT / f"{name}-{SIZE[0]}x{SIZE[1]}.png"), clip=clip)


def clear(page: Page) -> None:
    """Back out of a chosen move and close the sheet over the map, so the map has its room."""
    back = page.locator(".rl-pup-chip").get_by_role("button", name="Back")
    if back.count():
        back.first.click()
    close = page.locator(".rl-over .rl-over-head").get_by_role("button", name="Close")
    if close.count():
        close.first.click()
    page.wait_for_timeout(300)


def pick_up(page: Page, cdp: CDPSession, what: str) -> dict | None:
    """Press on one of the seat's own pieces and move it 12 px; where the finger now is."""
    clear(page)
    page.get_by_role("button", name="Zoom 1 times").first.click()
    settle(page, 500)
    own = page.evaluate(OWN_JS)
    rs.check(f"{what}: one of the seat's own pieces can be reached", own is not None)
    if own is None:
        return None
    before = view(page)
    press(page, cdp, own["x"], own["y"])
    move(page, cdp, (own["x"], own["y"]), (own["x"] + 12, own["y"]), 3)
    page.locator(".rl-map-target").first.wait_for(timeout=10_000)
    page.wait_for_timeout(100)
    # the finger keeps moving: a drawing the room made meanwhile shows the lift on the next move
    move(page, cdp, (own["x"] + 12, own["y"]), (own["x"] + 14, own["y"]), 1)
    page.wait_for_timeout(50)
    held = page.evaluate(HELD_JS)
    after = view(page)
    rs.check(
        f"{what}: pressed and moved, the piece is picked up and its moves light",
        held["lit"] > 0 and held["lifted"] == 1,
        json.dumps(held),
    )
    rs.check(
        f"{what}: the map does not pan while a piece is carried",
        (before["x"], before["y"], before["w"]) == (after["x"], after["y"], after["w"]),
        f"{before} {after}",
    )
    return {**own, "at": (own["x"] + 14, own["y"])}


def drag_to_lit(
    page: Page, cdp: CDPSession, report: dict, filed: list[str], tag: str = "drg"
) -> None:
    """Carry a piece to a lit area, drop it, and confirm the chip."""
    own = pick_up(page, cdp, "drop on a lit area" if tag == "drg" else f"{tag}: drop on a lit area")
    if own is None:
        return
    spot = page.evaluate(LIT_JS)
    rs.check("a lit area can be reached with the piece held", spot is not None)
    if spot is None:
        release(page, cdp)
        return
    key = "dragged" if tag == "drg" else f"{tag}_dragged"
    report[key] = {"piece": own["name"], "to": spot["label"]}
    move(page, cdp, own["at"], (spot["x"], spot["y"]), 12)
    page.wait_for_timeout(150)
    held = page.evaluate(HELD_JS)
    rs.check(
        "the lit area under the held piece is marked",
        held["under"] == [spot["area"]],
        json.dumps(held),
    )
    rs.check(
        "the held piece rides under the finger",
        held["shift"].startswith("translate("),
        json.dumps(held),
    )
    rs.shoot(page, f"{tag}-01-held-over-lit")
    detail(page, f"{tag}-01-held-over-lit-detail", spot["x"], spot["y"])
    before = len(filed)
    release(page, cdp)
    page.locator(".rl-pup-chip").first.wait_for(timeout=10_000)
    page.wait_for_timeout(300)
    held = page.evaluate(HELD_JS)
    rs.check(
        "the drop opens the confirm chip for that area",
        held["chip"] and held["chosen"] == [spot["area"]],
        json.dumps(held),
    )
    rs.check("the piece is back in its place on the board", held["lifted"] == 0, json.dumps(held))
    rs.shoot(page, f"{tag}-02-chip-after-drop")
    detail(page, f"{tag}-02-chip-after-drop-detail", spot["x"], spot["y"])
    rs.check("nothing is filed by the drop", len(filed) == before, str(filed))
    send = page.locator(".rl-pup-chip").get_by_role("button", name="Send it")
    if send.count():
        send.first.click()
        page.wait_for_timeout(1500)
        rs.check("Send it files the move", len(filed) == before + 1, str(filed))
    else:
        report[key]["locked"] = True
        rs.check(
            "a locked move offers its choices in the chip",
            page.locator(".rl-pup-chip .rl-lock-file").count() > 0,
        )


def drag_to_unlit(page: Page, cdp: CDPSession, report: dict, filed: list[str]) -> None:
    """Carry a piece to an area that is not lit: it goes back, and nothing is drafted."""
    own = pick_up(page, cdp, "drop on an area not lit")
    if own is None:
        return
    spot = page.evaluate(UNLIT_JS, MAP)
    rs.check("an area that is not lit can be reached with the piece held", spot is not None)
    if spot is None:
        release(page, cdp)
        return
    report["dragged_unlit"] = {"piece": own["name"], "to": spot["area"]}
    move(page, cdp, own["at"], (spot["x"], spot["y"]), 12)
    page.wait_for_timeout(150)
    held = page.evaluate(HELD_JS)
    rs.check("an area that is not lit is not marked", held["under"] == [], json.dumps(held))
    rs.shoot(page, "drg-03-held-over-unlit")
    before = len(filed)
    release(page, cdp)
    page.wait_for_timeout(600)
    held = page.evaluate(HELD_JS)
    rs.check(
        "dropped where nothing is lit, the piece goes back and nothing is drafted",
        held["lifted"] == 0
        and not held["shift"]
        and not held["chip"]
        and held["chosen"] == []
        and len(filed) == before,
        json.dumps(held),
    )


def by_keyboard(page: Page, report: dict) -> None:
    """The same move from the keyboard alone: Enter on the piece, an arrow to a lit area, Enter."""
    clear(page)
    page.get_by_role("button", name="Zoom 1 times").first.click()
    settle(page, 500)
    name = page.evaluate(FOCUS_JS, None)
    rs.check("a piece can take the focus", name is not None)
    if name is None:
        return
    page.keyboard.press("Enter")
    page.locator(".rl-map-target").first.wait_for(timeout=10_000)
    page.evaluate(FOCUS_JS, name)
    page.keyboard.press("ArrowRight")
    focused = page.evaluate("() => document.activeElement?.getAttribute('data-area')")
    page.keyboard.press("Enter")
    page.wait_for_timeout(400)
    held = page.evaluate(HELD_JS)
    report["keyboard"] = {"piece": name, "to": focused}
    rs.check(
        "by keyboard: a piece, an arrow and Enter open the chip",
        bool(focused) and held["chip"] and held["chosen"] == [focused],
        json.dumps(held),
    )
    page.keyboard.press("Escape")


MAP_SHARE = 0.55 if PHONE else 0.65
"""The viewport's height the map is clear of its controls for, the room's line. [proposed] The
season strip's 44 px row (5 percent of the viewport) lies under every map since the season
timeline landed, so it is taken off the 70 and 60 the line first named."""

ROOM_JS = """() => {
  const box = (el) => {
    const b = el.getBoundingClientRect();
    return { x: b.left, y: b.top, w: b.width, h: b.height, r: b.right, b: b.bottom };
  };
  const shown = (el) => el && getComputedStyle(el).display !== 'none'
    && el.getBoundingClientRect().height > 0;
  const svg = document.querySelector('main.rl-mapfirst svg.rl-tm-svg');
  const map = box(svg);
  const top = [...document.querySelectorAll('.rl-tm-top .rl-tm-tools > *')].filter(shown).map(box);
  const zoom = [...document.querySelectorAll('.rl-tm-zoomcorner .rl-filter')]
    .filter(shown).map(box);
  // the map's height clear of what lies over it: its controls along the top, the phone's bottom bar
  let lo = Math.max(map.y, 0, ...top.map((t) => t.b));
  let hi = Math.min(map.b, innerHeight);
  for (const el of document.querySelectorAll('.rl-needsbar, .rl-mapfirst-map > .rl-status')) {
    if (!shown(el)) continue;
    const b = box(el);
    if (b.y < hi && b.b > lo) hi = Math.min(hi, b.y);
  }
  const h2 = document.querySelector('#rl-map-h');
  return { vw: innerWidth, vh: innerHeight, map, controls: [...top, ...zoom],
    clear: Math.max(0, hi - lo) / innerHeight, full: !!document.querySelector('.rl-full'),
    browser: !!document.fullscreenElement, title: h2 ? box(h2) : null,
    line: !!document.querySelector('.rl-tmap > p.muted'), view: svg.getAttribute('viewBox'),
    sheet: !!document.querySelector('.rl-over'), focus: document.activeElement?.tagName ?? '' };
}"""


def room_map(page: Page) -> dict:
    page.wait_for_timeout(300)
    page.locator(MAP).first.wait_for(timeout=10_000)
    return page.evaluate(ROOM_JS)


def fills(got: dict) -> bool:
    m = got["map"]
    near = [abs(m["x"]), abs(m["y"]), abs(m["w"] - got["vw"]), abs(m["h"] - got["vh"])]
    return max(near) <= 1


def controls_over(page: Page, cdp: CDPSession, report: dict) -> dict:
    """The map's controls over its corners, and a press on one that does not pan the map."""
    clear(page)
    page.get_by_role("button", name="Zoom 1 times").first.click()
    settle(page, 500)
    got = room_map(page)
    report["mfs_room"] = got
    rs.check(
        "the map's title is for a screen reader only",
        (got["title"] or {}).get("w", 9) <= 1,
        str(got["title"]),
    )
    rs.check("the map's line of explanation is not drawn", not got["line"])
    m = got["map"]
    inside = all(
        c["x"] >= m["x"] - 1
        and c["r"] <= m["r"] + 1
        and c["y"] >= m["y"] - 1
        and c["b"] <= m["b"] + 1
        for c in got["controls"]
    )
    rs.check(
        "the map's controls sit over the map",
        bool(got["controls"]) and inside,
        json.dumps(got["controls"]),
    )
    rs.check(
        f"the map is clear of its controls for at least {MAP_SHARE:.0%} of the viewport's height",
        got["clear"] >= MAP_SHARE,
        str(got["clear"]),
    )
    rs.shoot(page, "mfs-01-controls-over-map")
    zoom = page.get_by_role("button", name="Zoom 1 times").first.bounding_box()
    before = view(page)
    if zoom:
        x, y = zoom["x"] + zoom["width"] / 2, zoom["y"] + zoom["height"] / 2
        press(page, cdp, x, y)
        move(page, cdp, (x, y), (x - 90, y - 60), 8)
        release(page, cdp)
    after = settle(page, 800)
    rs.check(
        "a press on the zoom control and a drag from it do not pan the map",
        zoom is not None
        and (before["x"], before["y"], before["w"]) == (after["x"], after["y"], after["w"]),
        f"{before} {after}",
    )
    return got


def full_screen(page: Page, cdp: CDPSession, report: dict, filed: list[str]) -> None:
    """Full screen by pointer, a piece carried there, a piece's sheet over it, out by Escape;
    then in by F and out by Escape from the keyboard alone."""
    out = controls_over(page, cdp, report)
    page.get_by_role("button", name="Full screen", exact=True).first.click()
    got = room_map(page)
    report["mfs_full"] = got
    rs.check(
        "by pointer: the map's box is the viewport",
        got["full"] and fills(got),
        json.dumps(got["map"]),
    )
    rs.check(
        "going into full screen keeps the view",
        got["view"] == out["view"],
        f"{out['view']} {got['view']}",
    )
    report["mfs_browser_full"] = got["browser"]
    rs.shoot(page, "mfs-02-full-screen")
    drag_to_lit(page, cdp, report, filed, tag="mfs")
    got = room_map(page)
    rs.check(
        "full screen stays on through a move", got["full"] and fills(got), json.dumps(got["map"])
    )
    clear(page)
    name = page.evaluate(FOCUS_JS, None)
    page.keyboard.press("Enter")
    page.locator(".rl-over").first.wait_for(timeout=10_000)
    got = room_map(page)
    rs.check(
        "a piece's sheet opens over the map in full screen",
        bool(name) and got["sheet"] and got["full"] and fills(got),
        json.dumps(got),
    )
    rs.shoot(page, "mfs-03-full-screen-piece-sheet")
    page.locator(".rl-over .rl-over-close").first.focus()
    page.keyboard.press("Escape")
    got = room_map(page)
    rs.check(
        "Escape closes the sheet first, and full screen stays",
        not got["sheet"] and got["full"],
        json.dumps(got),
    )
    page.locator(MAP).first.focus()
    page.keyboard.press("Escape")
    got = room_map(page)
    rs.check(
        "a second Escape leaves full screen",
        not got["full"] and not got["browser"],
        json.dumps(got),
    )
    rs.check("the map is back in its place", got["map"] == out["map"], f"{out['map']} {got['map']}")
    rs.check(
        "leaving full screen keeps the view",
        got["view"] == out["view"],
        f"{out['view']} {got['view']}",
    )
    page.locator(MAP).first.focus()
    page.keyboard.press("f")
    got = room_map(page)
    rs.check(
        "by keyboard: F on the map gives it the viewport, and the map keeps the focus",
        got["full"] and fills(got) and got["focus"].lower() == "svg",
        json.dumps(got),
    )
    page.keyboard.press("Escape")
    got = room_map(page)
    rs.check(
        "by keyboard: Escape leaves full screen",
        not got["full"] and got["map"] == out["map"],
        json.dumps(got),
    )


def frame_times(page: Page, cdp: CDPSession, report: dict) -> None:
    page.get_by_role("button", name="Zoom 1 times").first.click()
    settle(page, 500)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": SLOWDOWN})
    try:
        frames = page.evaluate(DRIVE_JS, [MAP, RUN_MS])
    finally:
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
    settle(page)
    s = sorted(frames)
    report["frames"] = {
        "slowdown": SLOWDOWN,
        "count": len(frames),
        "median_ms": round(s[len(s) // 2], 1) if s else 0.0,
        "p95_ms": p95(frames),
        "line_ms": FRAME_LINE_MS,
        "raw": [round(f, 2) for f in frames],
    }
    print("frames", {k: v for k, v in report["frames"].items() if k != "raw"}, flush=True)
    if PHONE:
        rs.check(
            f"the phone's 95th percentile frame time is at or under {FRAME_LINE_MS} ms",
            0 < p95(frames) <= FRAME_LINE_MS,
            str(p95(frames)),
        )
    else:
        rs.check("frames were drawn while the map moved", len(frames) > RUN_MS / 200)


def install_files(page: Page, report: dict) -> None:
    """The manifest the page links and each icon it lists answer, and the shell marks the page."""
    href = page.evaluate("document.querySelector('link[rel=manifest]')?.getAttribute('href') ?? ''")
    rs.check("the page links a manifest", bool(href), href)
    got = page.request.get(BASE + "/" + href.lstrip("/"))
    rs.check("the manifest answers", got.ok, str(got.status))
    manifest = got.json()
    rs.check("the manifest opens standalone at /", manifest.get("display") == "standalone")
    rs.check(
        "the manifest starts at /", manifest.get("start_url") == "/", str(manifest.get("start_url"))
    )
    icons = manifest.get("icons", [])
    rs.check("the manifest lists three icons", len(icons) == 3, str(len(icons)))
    for icon in icons:
        res = page.request.get(BASE + icon["src"])
        body = res.body() if res.ok else b""
        size = f"{int.from_bytes(body[16:20], 'big')}x{int.from_bytes(body[20:24], 'big')}"
        ok = res.ok and body[:8] == b"\x89PNG\r\n\x1a\n" and size == icon["sizes"]
        rs.check(f"icon {icon['src']} answers as a {icon['sizes']} PNG", ok, f"{res.status} {size}")
    mark = page.evaluate("document.documentElement.getAttribute('data-shell')")
    report["shell"] = {"manifest": href, "icons": [i["src"] for i in icons], "mark": mark}


STORES_JS = """async () => {
  const out = [];
  for (const name of await caches.keys()) {
    const store = await caches.open(name);
    for (const req of await store.keys()) out.push([name, new URL(req.url).pathname]);
  }
  return out;
}"""

WRITE_JS = """async () => {
  try {
    const r = await fetch('/api/realism/commit', { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: '{}' });
    return `answered ${r.status}`;
  } catch (e) { return 'refused'; }
}"""

SCRIPT_JS = "() => navigator.serviceWorker.controller?.scriptURL ?? ''"

READY_JS = """() => Promise.race([
  navigator.serviceWorker.ready.then(() => true),
  new Promise((done) => setTimeout(() => done(false), 30000)),
])"""


def offline_shell(browser: object, state: dict, url: str, report: dict) -> None:
    """Loads once, takes the worker, cuts the network and reloads, then offers a new version."""
    ctx = browser.new_context(  # type: ignore[attr-defined]
        viewport={"width": SIZE[0], "height": SIZE[1]},
        has_touch=PHONE,
        is_mobile=PHONE,
        storage_state=state,
        service_workers="allow",
    )
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.goto(url)
    page.locator(MAP).first.wait_for(timeout=60_000)
    ready = page.evaluate(READY_JS)
    rs.check("the worker is ready after one load", ready)
    if not ready:
        ctx.close()
        return
    page.reload()
    page.locator(MAP).first.wait_for(timeout=60_000)
    script = page.evaluate(SCRIPT_JS)
    rs.check("the worker controls the page after one load", script.endswith("/sw.js"), script)
    wrapper_needs(page, report)
    stores: list[list[str]] = []
    for _ in range(40):
        stores = page.evaluate(STORES_JS)
        if any(path.startswith("/maps/") for _, path in stores):
            break
        page.wait_for_timeout(250)
    paths = [path for _, path in stores]
    api = [path for path in paths if path.startswith("/api/")]
    rs.check("no key in the worker's stores is under /api/", not api, str(api))
    rs.check("the worker keeps the page", "/index.html" in paths)
    rs.check(
        "the worker keeps the scripts and styles",
        "/js/app.js" in paths and "/css/tokens.css" in paths,
    )
    maps = [path for path in paths if path.startswith("/maps/")]
    rs.check("the worker keeps the map object by its hash", len(maps) == 1, str(maps))
    worker: dict[str, object] = {
        "keys": len(paths),
        "stores": sorted({n for n, _ in stores}),
        "maps": maps,
    }

    ctx.set_offline(True)
    page.reload()
    line = page.locator(".shell-line.shell-offline")
    line.wait_for(timeout=15_000)
    said = line.inner_text()
    rs.check("offline, the shell opens with its one line", "orders cannot be sent" in said, said)
    rs.check(
        "offline, the page is the app's",
        page.title() == "Revisionist" and page.locator("#app").count() == 1,
    )
    wrote = page.evaluate(WRITE_JS)
    rs.check("offline, a write does not get through", wrote == "refused", wrote)
    rs.shoot(page, "swk-offline")
    ctx.set_offline(False)
    page.reload()
    page.locator(MAP).first.wait_for(timeout=60_000)
    rs.check("online again, the offline line is gone", page.locator(".shell-offline").count() == 0)

    # A worker at another address in the same scope is a new version to the browser, bytes alike:
    # it installs beside the one in control and waits, as a deploy's changed worker does.
    first = page.evaluate(SCRIPT_JS)
    page.evaluate(
        "async () => { await navigator.serviceWorker.register('/sw.js?next=1', { scope: '/' }); }"
    )
    offer = page.locator(".shell-line.shell-update")
    offered = True
    try:
        offer.wait_for(timeout=20_000)
    except Exception:
        offered = False
    rs.check("a new version is offered", offered)
    if offered:
        said = offer.inner_text()
        rs.check("the offer says a new version is ready", "A new version is ready." in said, said)
        rs.shoot(page, "swk-update")
        page.evaluate("() => { window.swkMark = 1; }")
        page.wait_for_timeout(1500)
        held = page.evaluate("() => window.swkMark === 1") and page.evaluate(SCRIPT_JS) == first
        rs.check("nothing changes before the player's word", held)
        with page.expect_navigation(timeout=20_000):
            offer.get_by_role("button", name="Reload").click()
        page.locator(MAP).first.wait_for(timeout=60_000)
        now = page.evaluate(SCRIPT_JS)
        rs.check(
            "Reload reloads the page under the new version",
            page.evaluate("() => window.swkMark === undefined") and now.endswith("/sw.js?next=1"),
            now,
        )
        worker["script"] = [first, now]
    rs.check("the offline shell raised no page error", not errors, "; ".join(errors))
    report["worker"] = worker
    ctx.close()


ASSETLINKS = "/.well-known/assetlinks.json"


def wrapper_needs(page: Page, report: dict) -> None:
    """What the Android wrapper reads: the linked manifest, the worker in control, the 512 icon,
    and the asset-links address."""
    href = page.evaluate("document.querySelector('link[rel=manifest]')?.getAttribute('href') ?? ''")
    rs.check("wrapper: the page links a manifest", bool(href), href)
    manifest = {}
    if href:
        got = page.request.get(BASE + "/" + href.lstrip("/"))
        manifest = got.json() if got.ok else {}
    rs.check("wrapper: the manifest opens standalone at /", manifest.get("display") == "standalone")
    rs.check("wrapper: the manifest starts at /", manifest.get("start_url") == "/")
    script = page.evaluate(SCRIPT_JS)
    rs.check("wrapper: the worker is in control", script.endswith("/sw.js"), script)
    big = [i for i in manifest.get("icons", []) if i.get("sizes") == "512x512"]
    rs.check("wrapper: the manifest lists a 512 px icon", bool(big))
    body = b""
    for icon in big:
        res = page.request.get(BASE + icon["src"])
        body = res.body() if res.ok else b""
        if body[:8] == b"\x89PNG\r\n\x1a\n" and body[16:24] == (512).to_bytes(4, "big") * 2:
            break
        body = b""
    rs.check("wrapper: a 512 px icon answers as a 512 by 512 PNG", bool(body))
    res = page.request.get(BASE + ASSETLINKS)
    if os.environ.get("REVISIONIST_ASSETLINKS_FILE"):
        try:
            links = res.json() if res.ok else []
        except ValueError:
            links = []
        named = [
            x
            for x in links
            if isinstance(x, dict) and x.get("target", {}).get("namespace") == "android_app"
        ]
        rs.check(
            "wrapper: the asset-links address names an Android app", bool(named), str(res.status)
        )
    else:
        rs.check("wrapper: with no asset-links file set, its address is a 404", res.status == 404)
    report["wrapper"] = {"manifest": href, "assetlinks": res.status}


UNDER_WAY_JS = """(() => {
  // Pieces under way, for the smoke's own context: in every reply that carries the seat's map,
  // its first own piece and five more like it are put on steps the game offers, at six shares of
  // their days. A fresh game has nothing under way, and the drawing reads only the reply. The
  // seat's other pieces are left alone, so one can still be sent.
  const SHARES = [[1, 4], [2, 4], [3, 4], [1, 3], [2, 5], [4, 6]];
  const plus = (day, n) => {
    const d = new Date(`${day}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  };
  const patch = (rv) => {
    const today = rv.clock.world_date;
    const own = rv.map.marks.filter((m) => m.side === 'own' && m.piece?.area
      && !m.piece.under_way && m.piece.domain !== 'envoy');
    if (own.length < 2) return;
    const first = own[0];
    const legs = own.flatMap((m) => m.piece.moves ?? []).map((mv) => mv.path)
      .filter((p) => p.length >= 2).map((p) => [p[0], p.slice(1)]);
    const steps = [[first.piece.area, first.piece.moves?.[0]?.path ?? []], ...legs]
      .filter(([, path]) => path.length).slice(0, SHARES.length);
    const at = [];
    steps.forEach(([area, path], i) => {
      const [gone, days] = SHARES[i];
      const began = plus(today, -gone);
      const key = i === 0 ? first.piece.key : `smoke-${i}`;
      const mark = i === 0 ? first
        : structuredClone({ ...first, name: `Smoke group ${i}`, key,
          piece: { ...first.piece, key, moves: [] } });
      const due = plus(began, days);
      Object.assign(mark.piece, { area, under_way: {
        path, step_began: began, step_due: due, step_days: days,
        arrives: plus(due, path.length - 1),
      } });
      if (i > 0) rv.map.marks.push(mark);
      at.push({ key, name: mark.name, from: area.key, to: path[0].key, into: path[0].name,
        gone, days });
    });
    window.__underWayAt = at;
  };
  const walk = (o) => {
    if (!o || typeof o !== 'object') return;
    if (o.clock?.world_date && Array.isArray(o.map?.marks)) { patch(o); return; }
    for (const v of Object.values(o)) walk(v);
  };
  const real = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const resp = await real(...args);
    const url = String(args[0]?.url ?? args[0]);
    const json = (resp.headers.get('content-type') ?? '').includes('json');
    if (!url.includes('/api/') || !json) return resp;
    const body = await resp.clone().json();
    walk(body);
    const { status, statusText, headers } = resp;
    return new Response(JSON.stringify(body), { status, statusText, headers });
  };
})();"""

PLACES_JS = """() => {
  // where each piece put under way is drawn, as a share of the way between its areas' labels
  const svg = document.querySelector('svg.rl-tm-svg');
  const pt = (g) => (g ? [Number(g.dataset.x), Number(g.dataset.y)] : null);
  const labels = [...svg.querySelectorAll('.rl-tm-label')];
  const label = (k) => pt(labels.find((g) => g.dataset.area === k));
  return (window.__underWayAt ?? []).map((w) => {
    const g = [...svg.querySelectorAll('.rl-tm-mark')].find((m) => m.dataset.key === w.key);
    const [a, b, at] = [label(w.from), label(w.to), pt(g)];
    if (!a || !b || !at) return { ...w, drawn: false };
    const [dx, dy] = [b[0] - a[0], b[1] - a[1]];
    const len2 = dx * dx + dy * dy || 1;
    const share = ((at[0] - a[0]) * dx + (at[1] - a[1]) * dy) / len2;
    const off = Math.abs((at[0] - a[0]) * dy - (at[1] - a[1]) * dx) / Math.sqrt(len2);
    return { ...w, drawn: true,
      share: Math.round(share * 1000) / 1000, off: Math.round(off * 100) / 100,
      tag: g.querySelector('text.rl-tm-tag')?.textContent ?? null,
      gone_line: !!svg.querySelector(`.rl-tm-course[data-key="${w.key}"] polyline.rl-tm-gone`) };
  });
}"""

MOVE_JS = """async (ms) => {
  // the six pieces carried to the ends of their steps on a clock of world days, by the drawing's
  // own hooks (the playback's); each frame's time is the gap between two frames
  const { placeMark, worldClock } = await import('/js/map/motion.js');
  const svg = document.querySelector('svg.rl-tm-svg');
  const ways = window.__underWayAt ?? [];
  return await new Promise((resolve) => {
    const frames = [];
    let last = null;
    worldClock({ days: 6, msPerDay: ms / 6, onDay: (day) => {
      const now = performance.now();
      if (last !== null) frames.push(now - last);
      last = now;
      for (const w of ways) {
        placeMark(svg, w.key, w.from, w.to, Math.min(1, (w.gone + day) / w.days));
      }
    }, onEnd: () => resolve(frames) });
  });
}"""

WATCH_JS = """() => {
  // the length of each order line drawn after now, in every frame for 2.5 s
  // an order is new when its piece and goal are: a piece sent again keeps its order id and
  // takes a new goal, and an order's holder may change in the same reply
  const said = (g) => g.getAttribute('aria-label').split(':')[0];
  const seen = new Set([...document.querySelectorAll('.rl-mk-order')].map(said));
  const t0 = performance.now();
  window.__drawn = [];
  const step = () => {
    const t = performance.now() - t0;
    for (const g of document.querySelectorAll('svg.rl-tm-svg .rl-mk-order')) {
      const l = g.querySelector('line');
      if (seen.has(said(g)) || !l) continue;
      const v = (a) => Number(l.getAttribute(a));
      const length = Math.hypot(v('x2') - v('x1'), v('y2') - v('y1'));
      window.__drawn.push([Math.round(t), Math.round(length * 100) / 100]);
    }
    if (t < 2500) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}"""

ORDERS_JS = "() => [...document.querySelectorAll('.rl-mk-order')].map((g) => g.ariaLabel)"

SHARE_SLACK = 0.02
"""How far a piece's drawn share may sit from its days gone over its days (rounded points)."""
DRAW_SLACK_MS = 150
"""A course drawing itself may take this much past its 600 ms: the first and last frames' gaps."""


def under_way_context(browser: object, state: dict, reduced: bool) -> tuple[object, Page]:
    ctx = browser.new_context(  # type: ignore[attr-defined]
        viewport={"width": SIZE[0], "height": SIZE[1]},
        has_touch=PHONE,
        is_mobile=PHONE,
        storage_state=state,
        reduced_motion="reduce" if reduced else "no-preference",
        service_workers="block",
    )
    ctx.add_init_script(UNDER_WAY_JS)
    return ctx, ctx.new_page()


def placed(page: Page, report: dict, tag: str) -> list[dict]:
    """Each piece put under way is drawn at its share of its step, with its tag."""
    got = page.evaluate(PLACES_JS)
    report[tag] = got
    rs.check(f"{tag}: six pieces are put under way", len(got) == 6, json.dumps(got))
    for w in got:
        want = w["gone"] / w["days"]
        rs.check(
            f"{tag}: {w['name']} is drawn {w['gone']} of {w['days']} days along its step",
            w["drawn"] and abs(w["share"] - want) <= SHARE_SLACK and w["off"] <= 1,
            json.dumps(w),
        )
        words = f"day {max(1, w['gone'])} of {w['days']} into {w['into']}"
        rs.check(f"{tag}: {w['name']} carries its tag", w.get("tag") == words, json.dumps(w))
        rs.check(f"{tag}: {w['name']} shows the part travelled", w.get("gone_line"), json.dumps(w))
    shares = {round(w["gone"] / w["days"], 3) for w in got if w["drawn"]}
    rs.check(
        f"{tag}: pieces stand at three or more shares of a step", len(shares) >= 3, str(shares)
    )
    return got


def under_way(browser: object, state: dict, url: str, report: dict) -> None:
    """Pieces under way drawn on their way, six moved by the playback's hooks, a course drawing
    itself when a move is sent, and the same pieces standing still under reduced motion."""
    ctx, page = under_way_context(browser, state, reduced=False)
    rs.watch(page)
    cdp = ctx.new_cdp_session(page)  # type: ignore[attr-defined]
    page.goto(url)
    page.locator(MAP).first.wait_for(timeout=60_000)
    page.wait_for_timeout(800)
    got = placed(page, report, "mvs_placed")
    rs.shoot(page, "mvs-01-under-way")
    first = next((w for w in got if w["drawn"]), None)
    if first:
        spot = page.evaluate(
            """(key) => { const g = [...document.querySelectorAll('svg.rl-tm-svg .rl-tm-mark')]
              .find((m) => m.dataset.key === key)?.querySelector('.rl-tm-hit')
              ?.getBoundingClientRect();
              return g ? [g.left + g.width / 2, g.top + g.height / 2] : null; }""",
            first["key"],
        )
        if spot:
            detail(page, "mvs-01-under-way-detail", spot[0], spot[1])
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": SLOWDOWN})
    try:
        frames = page.evaluate(MOVE_JS, 5000)
    finally:
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
    ends = page.evaluate(PLACES_JS)
    report["mvs_frames"] = {"slowdown": SLOWDOWN, "count": len(frames), "p95_ms": p95(frames)}
    rs.check(
        "the playback's clock carries all six pieces to the areas they enter",
        len(ends) == 6 and all(w["drawn"] and abs(w["share"] - 1) <= SHARE_SLACK for w in ends),
        json.dumps(ends),
    )
    if PHONE:
        rs.check(
            "while six pieces move the phone's 95th percentile frame time is at or under "
            f"{FRAME_LINE_MS} ms",
            0 < p95(frames) <= FRAME_LINE_MS,
            str(p95(frames)),
        )
    else:
        rs.check(
            "frames were drawn while six pieces moved", len(frames) > 5000 / 200, str(len(frames))
        )
    # a move sent from the keyboard: its line draws itself from the piece to its goal, once
    page.reload()
    page.locator(MAP).first.wait_for(timeout=60_000)
    page.wait_for_timeout(800)
    name = page.evaluate(FOCUS_JS, None)
    rs.check("mvs: a piece not under way can take the focus", name is not None)
    if name is not None:
        page.keyboard.press("Enter")
        page.locator(".rl-map-target").first.wait_for(timeout=10_000)
        before = page.evaluate(ORDERS_JS)
        report["mvs_orders_before"] = before
        # a goal the piece is not already sent to, so that the move makes a line of its own
        goals = [said.split(" to ", 1)[1].split(":")[0] for said in before if " to " in said]
        chip = page.locator(".rl-pup-chip")
        send = chip.get_by_role("button", name="Send it")
        for steps in range(1, 7):
            page.evaluate(FOCUS_JS, name)
            for _ in range(steps):
                page.keyboard.press("ArrowRight")
            page.keyboard.press("Enter")
            send.first.wait_for(timeout=10_000)
            if not any(goal in chip.first.inner_text() for goal in goals):
                break
            chip.get_by_role("button", name="Back").first.click()
            page.wait_for_timeout(300)
        page.evaluate(WATCH_JS)
        send.first.press("Enter")
        for _ in range(100):  # the page's policy forbids eval, so wait_for_function cannot run
            if page.evaluate("() => (window.__drawn ?? []).length > 0"):
                break
            page.wait_for_timeout(100)
        page.wait_for_timeout(150)
        page.screenshot(path=str(rs.OUT / f"mvs-02-course-drawing-{SIZE[0]}x{SIZE[1]}.png"))
        page.wait_for_timeout(2600)
        drawn = page.evaluate("() => window.__drawn")
        report["mvs_course"] = drawn
        report["mvs_orders"] = page.evaluate(ORDERS_JS)
        full = max((d[1] for d in drawn), default=0)
        whole = next((d[0] for d in drawn if d[1] >= full - 0.5), None)
        rs.check(
            "a move sent draws its line from the piece to its goal",
            bool(drawn) and drawn[0][1] < full * 0.5 and full > 0,
            json.dumps(drawn[:8]),
        )
        rs.check(
            "the line is whole within 600 ms of its first frame",
            whole is not None and whole - drawn[0][0] <= 600 + DRAW_SLACK_MS,
            json.dumps(drawn[:40]),
        )
        rs.shoot(page, "mvs-02-course-drawn")
    ctx.close()
    ctx, page = under_way_context(browser, state, reduced=True)
    rs.watch(page)
    page.goto(url)
    page.locator(MAP).first.wait_for(timeout=60_000)
    page.wait_for_timeout(800)
    placed(page, report, "mvs_reduced")
    moving = page.evaluate("() => document.getAnimations().length")
    rs.check("under reduced motion nothing on the map moves", moving == 0, str(moving))
    rs.shoot(page, "mvs-03-reduced-motion")
    ctx.close()


def record(browser: object, state: dict, url: str) -> None:
    """The same ten seconds of pan and pinch, not slowed, as a recording."""
    ctx = browser.new_context(  # type: ignore[attr-defined]
        viewport={"width": SIZE[0], "height": SIZE[1]},
        has_touch=PHONE,
        is_mobile=PHONE,
        storage_state=state,
        record_video_dir=str(OUT / "video"),
        record_video_size={"width": SIZE[0], "height": SIZE[1]},
    )
    page = ctx.new_page()
    page.goto(url)
    page.locator(MAP).first.wait_for(timeout=60_000)
    page.wait_for_timeout(500)
    page.evaluate(DRIVE_JS, [MAP, RUN_MS])
    page.wait_for_timeout(1500)
    video = page.video
    ctx.close()
    if video:
        video.save_as(str(OUT / f"mpn-pan-zoom-{SIZE[0]}x{SIZE[1]}.webm"))
        video.delete()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {"size": list(SIZE)}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": SIZE[0], "height": SIZE[1]}, has_touch=PHONE, is_mobile=PHONE
        )
        page = ctx.new_page()
        rs.watch(page)
        cdp = ctx.new_cdp_session(page)
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
        try:
            start(page)
            follows(page, cdp, report)
            tap_after_pan(page, cdp, report)
            filed: list[str] = []
            page.on(
                "request",
                lambda r: (
                    r.method == "POST"
                    and r.url.endswith("/api/realism/lever")
                    and filed.append(r.url)
                ),
            )
            drag_to_lit(page, cdp, report, filed)
            drag_to_unlit(page, cdp, report, filed)
            by_keyboard(page, report)
            full_screen(page, cdp, report, filed)
            frame_times(page, cdp, report)
            install_files(page, report)
            width = page.evaluate("document.documentElement.scrollWidth")
            rs.check("the page is as wide as the viewport", width == SIZE[0], str(width))
        except Exception:
            page.screenshot(path=str(OUT / "zz-failed.png"), full_page=True)
            raise
        url = page.url
        state = ctx.storage_state()
        ctx.close()
        try:
            offline_shell(browser, state, url, report)  # type: ignore[arg-type]
        except Exception as exc:
            rs.problems.append(f"the offline shell: {exc}")
        try:
            under_way(browser, state, url, report)  # type: ignore[arg-type]
        except Exception as exc:
            rs.problems.append(f"pieces under way: {exc}")
        record(browser, state, url)  # type: ignore[arg-type]
        browser.close()
    report["checks"] = rs.checks
    report["problems"] = rs.problems
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "frames"}, indent=2))
    return 1 if rs.problems else 0


if __name__ == "__main__":
    sys.exit(main())
