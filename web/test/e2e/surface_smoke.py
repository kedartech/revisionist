"""Browser smoke of the map as a surface: it follows the finger, zooms smoothly, and a tap is a tap.

Signs up a fresh account and either joins a game with an invite code or, with the code `new`,
starts the ready-made 1941 game as its host and plays Franklin D. Roosevelt. Then, on the map:

- a drag moves the land and the marks before the finger lifts, and the room keeps the new view;
- a pinch of two touches zooms to its spread, not to a step, and the wheel zooms (desktop);
- the arrow keys pan the map and the plus key zooms it, from the keyboard alone;
- one of the seat's own pieces is picked, the map is panned, and a lit place is tapped and chosen;
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
            frame_times(page, cdp, report)
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
