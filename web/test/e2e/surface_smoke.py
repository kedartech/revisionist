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
  two frame intervals (a frame's time comes in steps of 16.7 ms).

Screenshots, a ten-second recording of the same pan and pinch (not slowed) and `report.json` go to
OUT_DIR. With a fourth argument `phone` it runs at 390x844 with touch, else at 1440x900. Fails on
any console error, page error, failed request or request to another origin, or any named check
that does not hold.

    python web/test/e2e/surface_smoke.py BASE_URL INVITE_CODE|new OUT_DIR [phone]

For a run with no model calls, serve with web/test/e2e/serve_canned.py.
"""

import json
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
        record(browser, state, url)  # type: ignore[arg-type]
        browser.close()
    report["checks"] = rs.checks
    report["problems"] = rs.problems
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "frames"}, indent=2))
    return 1 if rs.problems else 0


if __name__ == "__main__":
    sys.exit(main())
