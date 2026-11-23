"""Browser smoke run of the realism room against a live `revisionist web serve`.

Signs up a fresh account and either joins a realism game with an invite code or, with
the code `new`, starts the ready-made game as its host and plays Franklin D. Roosevelt, chosen by
nation, path and person (by keyboard alone at desktop width, by taps at 390).
With the code `v2` it starts the engine-v2 slice from the timeline instead and checks
the timeline, who held power and the play style first.
Checks the room: the header names the player and its two names open the setting and the
character dossiers; the game menu; the wake header with the host's "Run the day now" and
the status strip with the date and "Done for today"; the in-tray's grouped rows, an
opened paper, flagging and the filters;
needs-your-answer, ideas, the standard forms, a directive read by the aide (signed when it
reads as an order, revised when it cannot be sent) and the orders column; the messenger
with the aide's thread, a question to the aide, a consult and the contacts tab; a day run
with the busy line and the overlay, then the "What happened" sheet; a narrow room; that no
empty-state filler shows; and (as host) ending the game and the reveal. Screenshots at
1440x900. The Board comes first: one move by keyboard alone (pick the fleet, light a place,
send it). With a fourth argument `phone` it runs at 390x844 instead, reaches the Board, and
checks that the map shows, that one lit place can be tapped and that the page is as wide as
the viewport. Fails on any console error, page error, failed request or a request to
another origin, or any named check that does not hold; runs axe-core when it is
mounted at /axe/axe.min.js.

    python web/test/e2e/realism_smoke.py BASE_URL INVITE_CODE|new|v2 OUT_DIR [phone]

For a run with no model calls, serve with web/test/e2e/serve_canned.py.
"""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Locator, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

BASE, CODE, OUT = sys.argv[1].rstrip("/"), sys.argv[2], Path(sys.argv[3])
PHONE = sys.argv[4:5] == ["phone"]
SIZE = (390, 844) if PHONE else (1440, 900)
AXE = Path("/axe/axe.min.js")
WAKE_MS = 240_000  # a wake makes one live prose call per author
RUN_NOW = "Run the day now"
problems: list[str] = []
checks: dict[str, bool] = {}
origin = urlparse(BASE).netloc


def watch(page: Page) -> None:
    page.on("console", lambda m: m.type == "error" and problems.append(f"console: {m.text}"))
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("requestfailed", lambda r: problems.append(f"failed: {r.url} {r.failure}"))

    def request(r: object) -> None:
        url = r.url  # type: ignore[attr-defined]
        if not url.startswith("data:") and urlparse(url).netloc != origin:
            problems.append(f"outside request: {url}")

    page.on("request", request)


def axe(page: Page, name: str) -> list[dict]:
    if not AXE.is_file():
        return []
    page.evaluate(AXE.read_text())  # CDP evaluate, so the page's own CSP still holds
    found = page.evaluate(
        "async () => (await axe.run(document, {runOnly: ['wcag2a','wcag2aa']})).violations"
        ".map(v => ({id: v.id, impact: v.impact, n: v.nodes.length,"
        " first: v.nodes[0] && v.nodes[0].target.join(' ')}))"
    )
    for v in found:
        problems.append(f"axe {name}: {v['id']} ({v['impact']}) x{v['n']} at {v['first']}")
    return found


def shoot(page: Page, name: str) -> None:
    page.wait_for_timeout(150)
    page.screenshot(path=str(OUT / f"{name}-{SIZE[0]}x{SIZE[1]}.png"))


def check(name: str, ok: bool, detail: str = "") -> None:
    checks[name] = ok
    if not ok:
        problems.append(f"check failed: {name} {detail}".strip())


FILLER = (
    "No figure given",
    "has not reached your desk",
    "nothing firm",
    "no figure to give",
    "Not stated",
)
"""Empty-state filler that must not reach the screen."""

SLOW_ADVANCE = (
    "() => { const f = window.fetch; window.fetch = (u, i) => /[/](commit|close)$/.test(String(u))"
    " ? new Promise((r) => setTimeout(r, 2000)).then(() => f(u, i)) : f(u, i); }"
)
"""Holds the commit or close call for two seconds so the busy state can be seen and shot."""


def no_filler(page: Page, where: str) -> None:
    text = page.locator("main").inner_text()
    found = [f for f in FILLER if f.lower() in text.lower()]
    check(f"no empty-state filler on {where}", not found, ", ".join(found))


def advance(page: Page, name: str, button: str = "Done for today") -> None:
    """Run the day (the only player, so it runs) with the call held, and check the busy
    state and the overlay while it runs, then the What happened sheet after."""
    page.evaluate(SLOW_ADVANCE)
    before = world_day(page)
    go = page.get_by_role("button", name=button).first
    go.click()
    if button == RUN_NOW:
        dialog = page.locator("dialog.rl-close-wake[open]")
        dialog.wait_for()
        check(
            f"{name}: running the day asks first", "every order as it stands" in dialog.inner_text()
        )
        shoot(page, f"{name}-confirm")
        dialog.get_by_role("button", name="Run it", exact=True).click()
    busy = page.locator(".rl-status.busy")
    busy.wait_for(timeout=5_000)
    check(f"{name}: busy line says the wake is running", "wake is running" in busy.inner_text())
    check(
        f"{name}: busy line is announced",
        busy.get_attribute("role") == "status" and busy.get_attribute("aria-live") == "polite",
    )
    check(
        f"{name}: controls are held while busy",
        page.locator(".rl-room button:not([disabled])").count() == 0,
    )
    overlay = page.locator(".rl-ovl")
    check(f"{name}: the overlay covers the room", overlay.count() == 1 and overlay.is_visible())
    shoot(page, f"{name}-busy")
    page.locator(".rl-status.said").filter(has_text="calendar moves").wait_for(timeout=WAKE_MS)
    page.wait_for_timeout(300)
    after = world_day(page)
    check(f"{name}: the day moves on", after != before, f"{before} -> {after}")
    check(f"{name}: the overlay is gone", page.locator(".rl-ovl").count() == 0)
    sheet = page.locator("dialog.rl-hap[open]")
    sheet.wait_for(timeout=5_000)
    check(f"{name}: What happened opens", "what happened" in sheet.inner_text().lower())
    shoot(page, f"{name}-happened")
    axe(page, f"{name} what happened")
    sheet.get_by_role("button", name="To the desk").click()
    page.wait_for_timeout(300)
    check(f"{name}: What happened closes", page.locator("dialog.rl-hap[open]").count() == 0)


def world_day(page: Page) -> str:
    """The world date the status strip (or the map-first room's bar) shows; no wake number."""
    return page.locator(".rl-strip .rl-date, .rl-roombar .rl-date").first.inner_text()


def fill(form: Locator) -> None:
    """Answer every field of a lever form with a value its input accepts."""
    for field in form.locator(".rl-field").all():
        number, select = field.locator("input[type=number]"), field.locator("select")
        if number.count():
            number.fill(number.get_attribute("min") or "1")
        elif select.count():
            select.select_option(index=1)
        else:
            field.locator("textarea").fill("Smoke test order")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        if CODE == "salt":  # the Salt Strait walk alone (a developer's run)
            try:
                salt_strait(p, browser, report)
            finally:
                print(json.dumps({**report, "checks": checks, "problems": problems}, indent=2))
            return 1 if problems else 0
        page = browser.new_page(
            viewport={"width": SIZE[0], "height": SIZE[1]},
            bypass_csp=False,
            has_touch=PHONE,
            is_mobile=PHONE,
        )
        watch(page)
        page.goto(BASE + "/")
        page.get_by_role("link", name="Create an account").click()
        page.get_by_role("heading", name="Create an account").wait_for()
        page.get_by_label("Handle").fill(f"rsmoke{int(time.time()) % 100000}")
        page.get_by_label("Password").fill("a long enough passphrase")
        page.get_by_role("button", name="Create account").click()
        page.get_by_role("heading", name="Your recovery codes").wait_for()
        page.get_by_label("I've kept these somewhere safe").check()
        page.get_by_role("button", name="Continue").click()
        page.get_by_role("heading", name="Join a game").wait_for()
        host = CODE in ("new", "v2")
        v2 = CODE == "v2"
        if v2:
            page.get_by_role("link", name="Start a new game").click()
            page.get_by_role("heading", name="When to begin").wait_for()
            begin = page.get_by_role("button", name="Begin on Autumn 1941 (engine v2 slice)")
            begin.wait_for(timeout=30_000)
            later = page.locator(".tag", has_text="Coming later").count()
            check("the timeline marks dates with no game as coming later", later > 0, str(later))
            no_filler(page, "the new-game screen")
            shoot(page, "00a-timeline")
            axe(page, "timeline")
            begin.click()
            page.get_by_role("heading", name="Choose who you will play").wait_for(timeout=30_000)
            page.get_by_role("heading", name="Who held power").wait_for()
            page.get_by_role("button", name="Henry L. Stimson", exact=True).wait_for(timeout=30_000)
            check(
                "a cast member shows once, not again under who held power",
                page.get_by_role("button", name="Franklin D. Roosevelt: open the dossier").count()
                == 1
                and page.get_by_role("button", name="Franklin D. Roosevelt", exact=True).count()
                == 0,
            )
            shoot(page, "00b-who-held-power")
            axe(page, "who held power")
            play_from_dossier(page, report, "Franklin D. Roosevelt")
            page.get_by_role("heading", name="You are Franklin D. Roosevelt").wait_for(
                timeout=60_000
            )
            check(
                "who held power hides once the seat holds a person",
                page.get_by_role("heading", name="Who held power").count() == 0,
            )
            page.get_by_label("Beginner").check()
            page.locator(".play-style .outcome > *").first.wait_for(timeout=10_000)
            shoot(page, "00c-play-style")
            axe(page, "play style")
            begin_with_crawl(page, report)
        elif host:
            page.get_by_role("link", name="Start a new game").click()
            page.get_by_role("button", name="Start Autumn 1941").click()
            page.get_by_role("heading", name="Choose who you will play").wait_for(timeout=30_000)
            opening_steps(page, report, "Franklin D. Roosevelt")
            release_and_repick(page, report, "Franklin D. Roosevelt")
            page.get_by_role("button", name="Begin the game").wait_for(timeout=60_000)
            begin_with_crawl(page, report)
        else:
            page.get_by_label("Invite code").fill(CODE)
            page.get_by_role("button", name="Join").click()

        page.locator("main.rl-board, main.rl-mapfirst").first.wait_for(timeout=60_000)
        page.wait_for_timeout(300)
        through_intro(page, report)
        shoot(page, "00-opening")
        opening(page, report)
        try:
            if PHONE:
                phone_board(page, report)
                locked_order(page, report)
                capital_board(page, report)
            else:
                keyboard_move(page, report)
                withdraw_move(page, report)
                locked_order(page, report)
                capital_board(page, report)
                page.get_by_role("group", name="View").get_by_role("button", name="Desk").click()
                page.locator("main.rl-room").wait_for(timeout=10_000)
                header_and_menu(page, report, host)
                wake_header(page, report, host)
                desk(page, report, v2)
                tray(page, report)
                orders(page, report, v2)
                messenger(page, report)
                after_wake(page, report, host)
                narrow(page)
        except Exception:
            page.screenshot(path=str(OUT / "zz-failed.png"), full_page=True)
            (OUT / "zz-failed.aria.txt").write_text(page.locator("body").aria_snapshot())
            raise
        body = page.locator("body").inner_text()
        for word in ("controller", "human", "truth", " AI ", "%", "Commit my orders"):
            if word in body:
                problems.append(f"rule: page text contains {word!r}")
        if host and not PHONE:
            end_game(page, report, v2)
        if host and not v2:
            # the first game's checks are kept even when the Salt Strait walk stops short
            (OUT / "report.json").write_text(
                json.dumps({**report, "checks": checks, "problems": problems}, indent=2)
            )
            salt_strait(p, browser, report)
        browser.close()
    report["checks"] = checks
    report["problems"] = problems
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 1 if problems else 0


def tab_to(page: Page, wanted: str, limit: int = 250) -> bool:
    """Press Tab until the focused element satisfies the JS predicate `wanted`."""
    for _ in range(limit):
        page.keyboard.press("Tab")
        if page.evaluate(
            f"() => {{ const a = document.activeElement; return !!a && ({wanted}); }}"
        ):
            return True
    return False


def picked(page: Page) -> bool:
    """After a pick of the seat's own force: wait for its forms (a point map) or its lit areas
    (a territory map); True on a territory map."""
    page.locator(".rl-theatre-forms, .rl-map-target[data-area]").first.wait_for(timeout=10_000)
    return page.locator("svg.rl-tm-svg").count() > 0


def keyboard_move_areas(page: Page, report: dict[str, object], errors: int) -> None:
    """The keyboard move on a territory map: a lit area, its chip, Send it."""
    check(
        "a picked piece shows its panel and lights the areas it can reach",
        page.locator("aside.rl-board-side h2").count() > 0
        and page.locator(".rl-map-target[data-area]").count() > 0,
    )
    found = tab_to(page, "a.matches('.rl-map-target[data-area]')")
    check("Tab reaches a lit area on the map", found)
    if not found:
        return
    label = str(page.evaluate("() => document.activeElement.getAttribute('aria-label')"))
    report["keyboard_move_to"] = label
    page.keyboard.press("Enter")
    chip = page.locator(".rl-pup-chip")
    chip.wait_for(timeout=10_000)
    report["keyboard_move_chip"] = chip.inner_text()
    check(
        "Enter on a lit area chooses it and opens its chip",
        page.locator(".rl-map-target[aria-pressed=true]").count() == 1,
        label,
    )
    check(
        "focus moves to the chip's Send it",
        bool(page.evaluate("() => document.activeElement?.textContent?.trim() === 'Send it'")),
    )
    shoot(page, "00a-keyboard-pick")
    page.keyboard.press("Enter")
    page.locator(".rl-status.said").filter(has_text="Sent to").wait_for(timeout=30_000)
    report["keyboard_move_status"] = page.locator(".rl-status").inner_text()
    check("the keyboard move is sent", True)
    check(
        "the keyboard move raises no page error",
        len([p for p in problems if p.startswith("pageerror")]) == errors,
    )
    shoot(page, "00b-keyboard-sent")


def keyboard_move(page: Page, report: dict[str, object]) -> None:
    """On the Board, from the keyboard alone: pick the seat's fleet, light a place (a point
    map) or an area (a territory map), send it."""
    errors = len([p for p in problems if p.startswith("pageerror")])
    page.get_by_role("group", name="Board").get_by_role("button", name="Theatre").focus()
    found = tab_to(page, "a.matches('.rl-mk.rl-side-own')")
    check("Tab reaches one of the seat's own forces on the map", found)
    if not found:
        return
    page.keyboard.press("Enter")
    if picked(page):
        keyboard_move_areas(page, report, errors)
        return
    forms = page.locator(".rl-theatre-forms")
    check(
        "a picked force shows its panel and the forms that move it",
        page.locator("aside.rl-board-side .rl-board-piece, aside.rl-board-side h2").count() > 0
        and forms.locator("form").count() > 0,
    )
    found = tab_to(page, "a.matches('.rl-map-target')")
    check("Tab reaches a lit place on the map", found)
    if not found:
        return
    label = str(page.evaluate("() => document.activeElement.getAttribute('aria-label')"))
    report["keyboard_move_to"] = label
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    check(
        "Enter on a lit place chooses it",
        page.locator(".rl-map-target[aria-pressed=true]").count() == 1
        and forms.locator("input[type=radio]:checked").count() >= 1,
        label,
    )
    check(
        "focus stays on the map's lit place after it is chosen",
        bool(page.evaluate("() => !!document.activeElement?.closest?.('.rl-map-target')")),
    )
    shoot(page, "00a-keyboard-pick")
    found = tab_to(
        page,
        "a.textContent.trim() === 'Sign and send'"
        " && !!a.closest('.rl-theatre-forms form')?.querySelector('input[type=radio]:checked')",
    )
    check("Tab reaches Sign and send on the form the lit place filled", found)
    if not found:
        return
    page.keyboard.press("Enter")
    page.locator(".rl-status.said").filter(has_text="Sent to").wait_for(timeout=30_000)
    report["keyboard_move_status"] = page.locator(".rl-status").inner_text()
    check("the keyboard move is sent", True)
    check(
        "the keyboard move raises no page error",
        len([p for p in problems if p.startswith("pageerror")]) == errors,
    )
    shoot(page, "00b-keyboard-sent")


def withdraw_move(page: Page, report: dict[str, object]) -> None:
    """The move just sent shows a Withdraw button while it may be withdrawn; Withdraw asks the
    server, and the button goes only once the room is drawn from the reply."""
    errors = len([p for p in problems if p.startswith("pageerror")])
    button = page.locator(".rl-pup-ghosts button.rl-pup-withdraw")
    try:
        button.first.wait_for(timeout=10_000)
    except PlaywrightTimeout:
        check("the move just sent offers Withdraw while it may be withdrawn", False)
        return
    report["withdraw_line"] = page.locator(".rl-pup-ghosts li").first.inner_text()
    check("the move just sent offers Withdraw while it may be withdrawn", button.count() >= 1)
    shoot(page, "00b1-withdraw-offered")
    before = button.count()
    button.first.click()
    page.locator(".rl-status.said").filter(has_text="withdrawn").wait_for(timeout=30_000)
    report["withdraw_status"] = page.locator(".rl-status").inner_text()
    check(
        "Withdraw takes the order back and its button goes with the reply",
        page.locator(".rl-pup-ghosts button.rl-pup-withdraw").count() == before - 1,
        f"{before} -> {page.locator('.rl-pup-ghosts button.rl-pup-withdraw').count()}",
    )
    check(
        "the withdrawal raises no page error",
        len([p for p in problems if p.startswith("pageerror")]) == errors,
    )
    shoot(page, "00b2-withdrawn")


LOCK_WHO = "Frank Knox"
"""Who can allow the canned server's one lock: a detachment sent to Reykjavik (serve_canned.py)."""


def view_button(page: Page, word: str) -> Locator:
    """The room's Board or Desk switch: the View group, or on a phone the room's panel tabs."""
    if PHONE:
        return page.get_by_role("navigation", name="Room panels").get_by_role("button", name=word)
    return page.get_by_role("group", name="View").get_by_role("button", name=word)


def set_layout(page: Page, word: str) -> bool:
    """Choose the room layout from the game menu ("Map first" or "Classic layout"); a game
    without territories has no choice, and nothing is clicked."""
    page.get_by_role("button", name="Game").click()
    menu = page.locator("dialog.rl-menu")
    menu.wait_for(timeout=10_000)
    group = menu.get_by_role("group", name="Room layout")
    chosen = group.count() > 0
    if chosen:
        group.get_by_role("button", name=word).click()
        page.wait_for_timeout(300)
    if menu.count() and menu.first.is_visible():
        page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    return chosen


def opening(page: Page, report: dict[str, object]) -> None:
    """A territory game opens in the map-first room; the walk below is the classic
    room's, so the smoke takes Classic layout from the game menu. A game without
    territories opens the classic room and offers no layout choice."""
    map_first = page.locator("main.rl-mapfirst").count() > 0
    report["opening_layout"] = "map" if map_first else "room"
    if not map_first:
        return
    check(
        "a territory game opens in the map-first room", page.locator("main.rl-board").count() == 0
    )
    room_top(page, report)
    season_timeline(page, report)
    groups_walk(page, report)
    nations_chart(page, report, "1941")
    quiet_parts(page, report)
    forms_from(page, report)
    check("the map-first room offers Classic layout", set_layout(page, "Classic layout"))
    page.locator("main.rl-board").wait_for(timeout=10_000)
    shoot(page, "01d-rmt-classic")


# The map-first room gives the map the screen (RMT): one bar of at most 56 px at 1440 wide and
# 96 px at 390 [proposed], and the map clear of what lies over it at least 70 and 60 percent of
# the viewport's height [proposed], on the ready-made 1941 game with no sheet open.
BAR_MAX = 96 if PHONE else 56
MAP_SHARE = 0.60 if PHONE else 0.70
MAP_FLOOR = 320
MEASURE = """() => {
  const vh = innerHeight;
  const svg = document.querySelector('main.rl-mapfirst svg.rl-map-svg');
  const bar = document.querySelector('.rl-roombar');
  if (!svg || !bar) return { share: 0, bar: 1e9, vh };
  const r = svg.getBoundingClientRect();
  let top = Math.max(r.top, 0);
  let bottom = Math.min(r.bottom, vh);
  // what lies over the map's foot: the phone's bottom bar, the status line
  for (const el of document.querySelectorAll('.rl-needsbar, .rl-mapfirst-map > .rl-status')) {
    const b = el.getBoundingClientRect();
    if (!b.height || getComputedStyle(el).display === 'none') continue;
    if (b.top < bottom && b.bottom > top) bottom = Math.min(bottom, b.top);
  }
  const above = [...document.querySelector('.realism-screen').children]
    .filter((c) => c.tagName !== 'DIALOG' && getComputedStyle(c).display !== 'none')
    .filter((c) => c.getBoundingClientRect().bottom <= r.top + 1)
    .filter((c) => !c.matches('main.rl-mapfirst, .rl-needsbar'))
    .map((c) => c.className);
  return { share: Math.max(0, bottom - top) / vh, top, bottom, vh,
    bar: bar.getBoundingClientRect().height, svg: r.height,
    map: document.querySelector('main.rl-mapfirst').getBoundingClientRect().height,
    above, width: document.documentElement.scrollWidth };
}"""


def room_top(page: Page, report: dict[str, object]) -> None:
    """Measure the bar and the map on the 1941 game, open a sheet over it, and check that a
    viewport too short for the map's floor scrolls the room instead of squeezing the map."""
    page.locator("main.rl-mapfirst svg.rl-map-svg").first.wait_for(timeout=30_000)
    page.wait_for_timeout(500)
    got = page.evaluate(MEASURE)
    report["rmt_room_top"] = got
    check(f"the room's one bar is at most {BAR_MAX} px tall", got["bar"] <= BAR_MAX, str(got))
    check("nothing but the bar is above the map", got["above"] == ["rl-roombar"], str(got))
    check(
        f"the map is clear for at least {MAP_SHARE:.0%} of the viewport's height",
        got["share"] >= MAP_SHARE,
        str(got),
    )
    check("the room is as wide as the viewport", got["width"] == SIZE[0], str(got))
    shoot(page, "01a-rmt-first-wake")
    page.locator(".rl-roombar .rl-sheettab", has_text="Inbox").first.click()
    over(page).wait_for(timeout=10_000)
    shoot(page, "01b-rmt-sheet-open")
    page.locator(".rl-over .rl-over-close").first.click()
    page.wait_for_timeout(300)
    marks = page.locator(".rl-roombar .rl-aimmark")
    report["rmt_aim_marks"] = marks.count()
    if marks.count():
        marks.first.click()
        over(page).wait_for(timeout=10_000)
        shoot(page, "01e-rmt-aims")
        page.locator(".rl-over .rl-over-close").first.click()
        page.wait_for_timeout(300)
    page.set_viewport_size({"width": SIZE[0], "height": 360})  # shorter than the bar and the floor
    page.wait_for_timeout(400)
    short = page.evaluate(MEASURE)
    scrolls = page.evaluate("() => document.documentElement.scrollHeight > innerHeight")
    report["rmt_short_viewport"] = {**short, "scrolls": scrolls}
    check(
        f"in a short viewport the map keeps {MAP_FLOOR} px and the room scrolls",
        short["map"] >= MAP_FLOOR and scrolls,
        str(report["rmt_short_viewport"]),
    )
    page.set_viewport_size({"width": SIZE[0], "height": SIZE[1]})
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(300)


# The season on one timeline (STL): a strip at the map's foot, 44 px closed; open, a list over
# at most 40 percent of the map with the map's controls above it; a row opens its item.
TL_SHARE = 0.40  # [proposed]
TL_MEASURE = """() => {
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, height: r.height };
  };
  const tl = document.querySelector('.rl-mapfirst-map .rl-tl');
  const svg = document.querySelector('main.rl-mapfirst svg.rl-map-svg');
  if (!tl || !svg) return null;
  const body = tl.querySelector('.rl-tl-body');
  const cover = body ? box(body) : null;
  const shown = (el) => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
  // the map's controls: every control in the map's section that is not the strip's own
  const sel = '.rl-mapfirst-map button, .rl-mapfirst-map select, .rl-mapfirst-map input';
  const controls = [...document.querySelectorAll(sel)]
    .filter((c) => !c.closest('.rl-tl') && !c.closest('svg') && shown(c));
  const hit = (r) => r.bottom > cover.top + 1 && r.top < cover.bottom - 1
    && r.right > cover.left && r.left < cover.right;
  const under = cover ? controls.filter((c) => hit(c.getBoundingClientRect()))
    .map((c) => (c.getAttribute('aria-label') || c.textContent).trim().slice(0, 40)) : [];
  const marks = tl.querySelectorAll('.rl-tl-axis .rl-tl-mark').length;
  return { head: box(tl.querySelector('.rl-tl-head')), map: box(svg), cover, under, marks,
    rows: tl.querySelectorAll('.rl-tl-row').length, width: document.documentElement.scrollWidth };
}"""


def tl_marks(page: Page) -> int:
    return page.locator(".rl-mapfirst-map .rl-tl .rl-tl-axis .rl-tl-mark").count()


def season_timeline(page: Page, report: dict[str, object]) -> None:
    """The strip on the 1941 game: closed, open by Enter or a tap, and one row's item opened."""
    try:
        page.locator(".rl-mapfirst-map .rl-tl").wait_for(timeout=10_000)
    except PlaywrightTimeout:
        check("the season's strip is drawn at the map's foot", False)
        return
    closed = page.evaluate(TL_MEASURE)
    report["stl_closed"] = closed
    check(
        "the season's strip is drawn at the map's foot",
        bool(closed) and closed["marks"] > 0,
        str(closed),
    )
    check(
        "closed, the strip is 44 px tall",
        abs(closed["head"]["height"] - 44) < 1,
        str(closed["head"]),
    )
    check(
        "closed, the strip is under the map, not over it",
        closed["head"]["top"] >= closed["map"]["bottom"] - 1,
        str(closed),
    )
    shoot(page, "60-stl-closed")
    check("Enter or a tap opens the strip", press(page, ".rl-tl-head", "The season"))
    try:
        page.locator(".rl-tl.open .rl-tl-list").wait_for(timeout=10_000)
    except PlaywrightTimeout:
        check("the open strip lists the season", False)
        return
    page.wait_for_timeout(200)
    got = page.evaluate(TL_MEASURE)
    report["stl_open"] = got
    check("open, a row for every mark", got["rows"] == got["marks"] > 0, str(got))
    cover = got["cover"]
    covered = max(
        0.0, min(cover["bottom"], got["map"]["bottom"]) - max(cover["top"], got["map"]["top"])
    )
    check(
        f"open, the strip covers at most {TL_SHARE:.0%} of the map",
        covered <= TL_SHARE * got["map"]["height"] + 1,
        f"{covered:.0f} of {got['map']['height']:.0f}",
    )
    check("open, the map's controls sit above the strip", got["under"] == [], str(got["under"]))
    check(
        "the open strip keeps the page as wide as the viewport", got["width"] == SIZE[0], str(got)
    )
    report["stl_rows"] = page.locator(".rl-tl-row").evaluate_all(
        "(rs) => rs.map((r) => r.getAttribute('aria-label'))"
    )
    shoot(page, "61-stl-open")
    row = "Season:" if page.locator(".rl-tl-row[data-kind=end]").count() else ""
    check("a row of the strip can be pressed", press(page, ".rl-tl-row", row))
    try:
        over(page).wait_for(timeout=10_000)
        check("a row opens its item where it lives", True)
        shoot(page, "62-stl-row-opened")
        page.locator(".rl-over .rl-over-close").first.click()
        page.wait_for_timeout(300)
    except PlaywrightTimeout:
        check("a row opens its item where it lives", False)


# The sheets in four groups (SHG): the bar's four group tabs and the chat button; each group a
# sheet with its parts as inner tabs, every part reached by keyboard at 1440 and by tap at 390;
# and a form opened from the search, from a person's card and from a piece.
GROUP_WORDS = ("Inbox", "Orders", "People", "World")


def part_keys(page: Page) -> list[str]:
    """The open group's parts, by their sheet keys, in order."""
    keys: list[str] = page.locator(".rl-over .rl-parts button").evaluate_all(
        "(bs) => bs.map((b) => b.getAttribute('data-sheet'))"
    )
    return keys


def groups_walk(page: Page, report: dict[str, object]) -> None:
    """Open each group from the bar and each of its parts from the sheet's inner tabs."""
    bar = page.locator(".rl-roombar")
    words = bar.locator(".rl-sheettab").evaluate_all(
        "(bs) => bs.map((b) => b.getAttribute('data-group'))"
    )
    report["shg_groups"] = words
    check(
        "the bar's sheet tabs are the four groups",
        words == ["inbox", "orders", "people", "world"],
        str(words),
    )
    check("the bar has the chat button", bar.locator(".rl-chat-btn").count() == 1)
    check("the bar has no Nations control", bar.locator(".rl-nations-btn").count() == 0)
    shoot(page, "40-shg-bar")
    seen: dict[str, list[str]] = {}
    drawn: dict[str, list[str]] = {}
    for word in GROUP_WORDS:
        page.wait_for_timeout(200)
        if not check_open(page, press(page, ".rl-roombar .rl-sheettab", word), f"the {word} group"):
            continue
        parts = part_keys(page)
        seen[word] = []
        for key in parts:
            label = (
                over(page)
                .locator(f".rl-parts button[data-sheet='{key}']")
                .inner_text()
                .split("\n")[0]
                .strip()
            )
            got = press(page, ".rl-over .rl-parts button", label)
            page.wait_for_timeout(300)
            on = over(page).get_attribute("data-sheet") == key
            check(f"{word}: the {label} part is reached and opens", got and on, f"{got} {on}")
            if on:
                seen[word].append(key)
                shoot(page, f"41-shg-{word.lower()}-{key}")
        drawn[word] = parts
        sheet_close(page, word)
    report["shg_parts"] = seen
    report["shg_drawn"] = drawn
    # on Beginner a quiet part (the Court, Home, Diplomacy) is left out of its group while
    # nothing in it waits; the game menu's All sheets reaches it
    check(
        "every part drawn in the four groups was reached",
        len(seen) == 4 and seen == drawn,
        f"{seen} of {drawn}",
    )
    if check_open(
        page, press(page, ".rl-roombar .rl-chat-btn", "Messages"), "the chat button's messenger"
    ):
        check(
            "the chat button opens the messenger",
            over(page).get_attribute("data-sheet") == "messages",
        )
        shoot(page, "42-shg-chat")
        sheet_close(page, "Messages")


def quiet_parts(page: Page, report: dict[str, object]) -> None:
    """A part left out of its group on Beginner (the Court, Home, Diplomacy) opens from the game
    menu's All sheets, which names it by its group."""
    opened = []
    for name in ("People: Court", "World: Home", "World: Diplomacy"):
        page.wait_for_timeout(300)
        press(page, "button", "Game")
        menu = page.locator("dialog.rl-menu[open]")
        menu.wait_for(timeout=10_000)
        if menu.get_by_role("button", name=name).count() == 0:
            page.keyboard.press("Escape")
            continue
        check(f"All sheets opens {name}", press(page, "dialog.rl-menu button", name))
        over(page).wait_for(timeout=10_000)
        page.wait_for_timeout(300)
        key = over(page).get_attribute("data-sheet") or ""
        opened.append(key)
        shoot(page, f"41-shg-{name.split(':')[0].lower()}-{key}")
        sheet_close(page, name)
    report["shg_quiet_parts"] = opened


# The nations as a bar chart, with a card each (NBR): World's Nations part on the 1941 game and on
# Salt Strait, by keyboard at 1440 and by tap at 390: the bars against the largest, ten before
# "All nations" with the seat's own among them, the names beside the flags at 1440 only, a card
# for the seat's own nation and for another, Escape closing a card with the focus back on its row,
# and the page as wide as the viewport.
ROW = ".rl-over button.rl-nb-row"
SHOWN_NAMES = """() => [...document.querySelectorAll('.rl-over .rl-nb-name')]
  .filter((e) => e.getClientRects().length).length"""


def nation_card(page: Page, label: str, game: str, name: str) -> str:
    """Open the card of the row named `label`, shoot it, close it by Escape: its words."""
    if not press(page, ROW, label):
        check(f"{game}: the row {label[:30]!r} is reached", False)
        return ""
    card = over(page).locator(".rl-nb-card")
    try:
        card.wait_for(timeout=10_000)
    except PlaywrightTimeout:
        check(f"{game}: a row opens its card", False, label)
        return ""
    words = said(card)
    shoot(page, name)
    key = card.get_attribute("data-nation")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    back = page.evaluate("() => document.activeElement?.getAttribute('data-nation')")
    check(
        f"{game}: Escape closes the card, the chart stays and the focus is back on its row",
        card.count() == 0 and over(page).get_attribute("data-sheet") == "nations" and back == key,
        f"{back} {key}",
    )
    return words


def nations_chart(page: Page, report: dict[str, object], game: str) -> None:
    """Open World at Nations, read the chart and open two cards."""
    page.wait_for_timeout(300)
    if not check_open(page, press(page, ".rl-roombar .rl-sheettab", "World"), "World"):
        return
    if over(page).get_attribute("data-sheet") != "nations":
        press(page, ".rl-over .rl-parts button", "Nations")
        page.wait_for_timeout(300)
    sheet = over(page)
    rows = sheet.locator("button.rl-nb-row")
    n = rows.count()
    more = sheet.locator("button.rl-nb-all").count() > 0
    widths = sheet.locator("rect.rl-nb-fill").evaluate_all(
        "(rs) => rs.map((r) => Number(r.getAttribute('width')))"
    )
    flags = sheet.locator("button.rl-nb-row .flag").count()
    names = page.evaluate(SHOWN_NAMES)
    width = page.evaluate("document.documentElement.scrollWidth")
    report[f"nbr_{game}"] = {
        "rows": n,
        "more": more,
        "bars": widths,
        "names": names,
        "width": width,
    }
    check(
        f"{game}: World's Nations part is the chart", sheet.locator(".rl-nb").count() == 1 and n > 0
    )
    check(f"{game}: ten rows before All nations", n == 10 if more else n <= 10, str(n))
    check(f"{game}: the seat's own row is among them", rows.locator(".rl-nb-yours").count() == 1)
    check(
        f"{game}: the largest bar fills its track and none runs past it",
        bool(widths) and max(widths) == 100 and all(0 <= w <= 100 for w in widths),
        str(widths),
    )
    check(f"{game}: a flag on every row", flags == n, f"{flags} of {n}")
    check(
        f"{game}: the names beside the flags at 1440 only",
        names == (0 if PHONE else n),
        f"{names} of {n}",
    )
    check(f"{game}: the page is as wide as the viewport", width == SIZE[0], str(width))
    shoot(page, f"50-nbr-{game}-chart")
    if more:
        check(
            f"{game}: All nations opens the rest", press(page, ".rl-over button.rl-nb-all", "All")
        )
        page.wait_for_timeout(300)
        check(f"{game}: every nation in place", rows.count() > n, str(rows.count()))
        shoot(page, f"50-nbr-{game}-all")
        press(page, ".rl-over button.rl-nb-all", "The first")
        page.wait_for_timeout(300)
    own = rows.filter(has=page.locator(".rl-nb-yours")).first.get_attribute("aria-label") or ""
    other = (
        rows.evaluate_all(
            "(bs) => bs.map((b) => b.getAttribute('aria-label'))"
            ".find((l) => !l.includes('(yours)'))"
        )
        or ""
    )
    mine = nation_card(page, own, game, f"51-nbr-{game}-own-card")
    check(
        f"{game}: the seat's own card has its ways on",
        ("your war economy" in mine) == bool(widths) and "at home" in mine,
        mine[:200],
    )
    theirs = nation_card(page, other, game, f"52-nbr-{game}-other-card")
    check(
        f"{game}: another nation's card says what its figure is, where it has one",
        ("read from the map" in theirs) == bool(widths),
        theirs[:200],
    )
    sheet_close(page, "World")


def check_open(page: Page, found: bool, what: str) -> bool:
    """`found` says the control for `what` was pressed: check a sheet is over the map."""
    if found:
        try:
            over(page).wait_for(timeout=10_000)
        except PlaywrightTimeout:
            found = False
    check(f"{what} opens as a sheet", found)
    return found


def forms_from(page: Page, report: dict[str, object]) -> None:
    """A form from the Write part's search, from a person's card and from a piece."""
    press(page, ".rl-roombar .rl-sheettab", "Orders")
    over(page).wait_for(timeout=10_000)
    press(page, ".rl-over .rl-parts button", "Write")
    page.wait_for_timeout(300)
    check("the Write part has the search", write(page, "input[type=search]", "Find a form", "lend"))
    page.wait_for_timeout(300)
    shown = (
        over(page)
        .locator(".rl-instrument:not([hidden]) .rl-instrument-head")
        .evaluate_all("(hs) => hs.map((h) => h.textContent.trim())")
    )
    report["shg_search_lend"] = shown
    check(
        "the search keeps the forms named for it",
        bool(shown) and all("lend" in t.lower() for t in shown),
        str(shown),
    )
    opened = press(
        page, ".rl-over .rl-instrument:not([hidden]) .rl-instrument-head [aria-expanded]"
    )
    page.wait_for_timeout(300)
    check(
        "a form picked from the search opens as it does today",
        opened
        and over(page).locator(".rl-instrument:not([hidden]) [aria-expanded='true']").count() > 0,
    )
    shoot(page, "43-shg-search")
    over(page).locator("input[type=search]").fill("")
    sheet_close(page, "Orders")
    person_form(page, report)
    piece_form(page, report)


def person_form(page: Page, report: dict[str, object]) -> None:
    """People, Roster: the first of the seat's people with Write an order on their card."""
    press(page, ".rl-roombar .rl-sheettab", "People")
    over(page).wait_for(timeout=10_000)
    press(page, ".rl-over .rl-parts button", "Roster")
    page.wait_for_timeout(300)
    yours = over(page).locator(".rl-people .seg button", has_text="Your people")
    if yours.count():
        yours.first.click()
        page.wait_for_timeout(300)
    rows = over(page).locator(".rl-pp-row")
    card = page.locator("dialog.rl-fc[open]")
    who = None
    for i in range(min(rows.count(), 10)):
        rows.nth(i).click()
        card.wait_for(timeout=10_000)
        if card.get_by_role("button", name="Write an order").count():
            who = (card.locator("h2").first.text_content() or "").strip()
            break
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
    report["shg_person"] = who
    check("a person's card has Write an order", who is not None)
    if who is None:
        sheet_close(page, "People")
        return
    shoot(page, "44-shg-person-card")
    check(
        "Write an order on the card is pressed",
        press(page, "dialog.rl-fc button", "Write an order"),
    )
    page.wait_for_timeout(500)
    to = over(page).locator(".rl-write input[type=radio]:checked")
    check(
        "it opens Orders at Write, addressed to them",
        over(page).get_attribute("data-sheet") == "forms"
        and to.count() == 1
        and to.first.get_attribute("value") == who,
        f"{who} {over(page).get_attribute('data-sheet')}",
    )
    shoot(page, "45-shg-person-write")
    sheet_close(page, "Orders")
    # the roster opens on Opponents again, as the classic room's walk expects
    press(page, ".rl-roombar .rl-sheettab", "People")
    over(page).wait_for(timeout=10_000)
    over(page).locator(".rl-people .seg button", has_text="Opponents").first.click()
    page.wait_for_timeout(300)
    sheet_close(page, "People")


OWN_ON_TOP = """() => {
  for (const m of document.querySelectorAll('.rl-mapfirst .rl-mk.rl-side-own')) {
    m.scrollIntoView({ block: 'center' });
    const r = m.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;
    const on = document.elementFromPoint(x, y);
    if (on && m.contains(on)) return { x, y, label: m.getAttribute('aria-label') };
  }
  return null;
}"""


def piece_form(page: Page, report: dict[str, object]) -> None:
    """One of the seat's own pieces: its sheet lists the forms that take it, filled in."""
    if (
        PHONE
    ):  # a tap lands on whatever is on top at the mark's centre: take the first own mark on top
        hit = page.evaluate(OWN_ON_TOP)
        report["shg_piece_tap"] = hit
        found = hit is not None
        if found:
            page.touchscreen.tap(hit["x"], hit["y"])
    else:
        found = press(page, ".rl-mapfirst .rl-mk.rl-side-own")
    try:
        page.locator(".rl-over[data-sheet='piece']").wait_for(timeout=10_000)
    except PlaywrightTimeout:
        found = False
    check("one of the seat's own pieces opens its sheet", found)
    if not found:
        return
    filled = (
        over(page)
        .locator(".rl-instrument")
        .evaluate_all(
            "(items) => items.map((i) => [i.getAttribute('data-lever'),"
            " i.querySelector('select[name=force], select[name=piece]')?.value ?? null])"
        )
    )
    report["shg_piece_forms"] = filled
    check(
        "the piece's forms open with the piece filled in",
        bool(filled) and all(v for _, v in filled),
        str(filled),
    )
    shoot(page, "46-shg-piece-forms")
    sheet_close(page, "piece")


def locked_order(page: Page, report: dict[str, object]) -> None:
    """One locked order (LKM), on a game with the canned server's lock: on the Desk, the
    fleet's detach form sent to Reykjavik is checked and shows the lock with who can allow it
    and two choices; Ask files it to be held and asks; the held order is then in what needs
    you, marked asked. Back on the Board after."""
    errors = len([p for p in problems if p.startswith("pageerror")])
    view_button(page, "Desk").click()
    page.locator("details.rl-forms").first.wait_for(timeout=10_000)
    forms = page.locator("details.rl-forms").first
    if forms.get_attribute("open") is None:
        forms.locator("summary").click()
    item = forms.locator(".rl-instrument[data-lever=detach_fleet]")
    if item.count() == 0:
        check("the desk offers the detach form", False)
        return
    item = item.first
    item.scroll_into_view_if_needed()
    item.get_by_role("button", name="Draft").click()
    form = item.locator("form.rl-form")
    form.wait_for(timeout=10_000)
    form.locator("select[name=force]").select_option("us_atlantic_fleet")
    place = form.locator("input[type=radio][value=reykjavik]")
    if place.count():
        place.first.evaluate("(e) => e.click()")  # the picker's radio may sit under its label
    else:
        form.locator("select[name=to]").select_option("reykjavik")
    strength = form.locator("input[name=strength]")
    if strength.count():
        strength.fill("1")
    form.get_by_role("button", name="Sign and send").click()
    choice = item.locator(".rl-lock-choice")
    try:
        choice.wait_for(timeout=15_000)
    except PlaywrightTimeout:
        report["lock_status"] = page.locator(".rl-status").inner_text()
        check("a locked order shows the lock before it is sent", False, str(report["lock_status"]))
        return
    report["lock_choice"] = choice.inner_text()
    check(
        "a locked order shows the padlock and who can allow it",
        choice.locator(".rl-lock .rl-lock-icon").count() == 1
        and choice.locator(".rl-lock-who").inner_text().strip() == LOCK_WHO,
        str(report["lock_choice"]),
    )
    acts = [b.strip() for b in choice.locator(".rl-lock-acts button").all_inner_texts()]
    check(
        "a locked order offers file it to be held, and ask",
        acts == ["File it to be held", f"Ask {LOCK_WHO}"],
        str(acts),
    )
    item.screenshot(path=str(OUT / f"00d-lock-choice-{SIZE[0]}x{SIZE[1]}.png"))
    choice.get_by_role("button", name=f"Ask {LOCK_WHO}").click()
    page.locator(".rl-status.said").filter(has_text=f"Asked {LOCK_WHO}").wait_for(timeout=30_000)
    report["lock_status"] = page.locator(".rl-status").inner_text()
    check("the locked order is filed to be held and asked for", True)
    if set_layout(page, "Map first"):  # only a territory game has the map-first room
        if PHONE:
            page.locator(".rl-needs-btn").click()
        needs = page.locator("#rl-needs")
        needs.wait_for(timeout=10_000)
        more = needs.locator("details.rl-needs-more > summary")
        if more.count():  # Beginner shows one next step; the rest is behind More (BGN)
            more.first.click()
        line = needs.locator("li.rl-need[data-kind=held]")
        if line.count():  # a line opens in place to who can allow it and its action
            line.first.locator(".rl-need-row").click()
        report["lock_needs_line"] = line.first.inner_text() if line.count() else ""
        check(
            "the held order is in what needs you, marked asked, with who can allow it",
            line.count() == 1
            and line.first.locator(".rl-need-status").inner_text().strip() == "Asked"
            and line.first.locator(".rl-lock-who").inner_text().strip() == LOCK_WHO
            and line.first.locator(".rl-need-act").count() == 0,
            str(report["lock_needs_line"]),
        )
        if line.count():
            line.first.scroll_into_view_if_needed()
        width = page.evaluate("document.documentElement.scrollWidth")
        check("the needs list with a held order fits the viewport", width <= SIZE[0], str(width))
        page.screenshot(path=str(OUT / f"00e-lock-needs-{SIZE[0]}x{SIZE[1]}.png"))
        if PHONE:
            page.keyboard.press("Escape")
        set_layout(page, "Classic layout")
    view_button(page, "Board").click()
    page.locator("main.rl-board").wait_for(timeout=10_000)
    held_on_piece(page, report)
    check(
        "the locked order raises no page error",
        len([p for p in problems if p.startswith("pageerror")]) == errors,
    )


LOCK_PIECE = "Atlantic Fleet"
"""The piece the canned lock's held order moves: the fleet the detach form names."""


def held_on_piece(page: Page, report: dict[str, object]) -> None:
    """The held order on its piece (LKM): on a territory map the fleet's marker (or the
    closed stack it is in) carries the padlock and says it in its label; on any map the
    fleet's sheet lists the held order with who can allow it, marked asked."""
    page.locator("figure.rl-map-figure").first.wait_for(timeout=10_000)
    seen = page.evaluate(
        """(name) => {
      const label = (el) => el.getAttribute('aria-label') || '';
      const on = [...document.querySelectorAll('.rl-tm-mark, .rl-tm-stack')]
        .map(label).filter((l) => l.includes(name) && /held order/i.test(l));
      return { territory: !!document.querySelector('svg.rl-tm-svg'), on,
        glyphs: document.querySelectorAll('.rl-tm-held .rl-lock-glyph').length };
    }""",
        LOCK_PIECE,
    )
    report["lock_on_map"] = seen
    if seen["territory"]:
        check(
            "the held order shows on its piece on the map, with the padlock",
            seen["glyphs"] >= 1 and len(seen["on"]) >= 1,
            str(seen),
        )
    pick = """(name) => {
      const label = (el) => el.getAttribute('aria-label') || '';
      const stack = [...document.querySelectorAll('.rl-tm-stack')]
        .find((s) => label(s).includes(name));
      const mark = [...document.querySelectorAll('.rl-mk')].find((m) => label(m).includes(name)
        && m.getAttribute('aria-pressed') !== null);
      const hit = mark ?? stack;
      hit?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      return hit ? (mark ? 'mark' : 'stack') : null;
    }"""
    first = page.evaluate(pick, LOCK_PIECE)
    if first == "stack":
        page.wait_for_timeout(300)
        first = page.evaluate(pick, LOCK_PIECE)
    sheet = page.locator(".rl-piece-held")
    try:
        sheet.first.wait_for(timeout=10_000)
    except PlaywrightTimeout:
        check("the held order shows in its piece's sheet", False, str(first))
        return
    report["lock_piece_sheet"] = sheet.first.inner_text()
    row = sheet.first.locator("li")
    check(
        "the held order shows in its piece's sheet, with who can allow it, marked asked",
        row.count() == 1
        and row.first.locator(".rl-lock-who").inner_text().strip() == LOCK_WHO
        and row.first.locator(".rl-held-status").inner_text().strip() == "Asked",
        str(report["lock_piece_sheet"]),
    )
    sheet.first.scroll_into_view_if_needed()
    page.screenshot(path=str(OUT / f"00f-lock-piece-{SIZE[0]}x{SIZE[1]}.png"))
    close = page.locator(".rl-sheet-close")
    if close.count() and close.first.is_visible():
        close.first.click()
        page.wait_for_timeout(200)


def capital_board(page: Page, report: dict[str, object]) -> None:
    """The Capital board (CBD), in the map-first room after the held order is filed: the switch
    at the map's top left opens the Capital in the map's place, with the bar and the season's
    strip kept; a chamber's bar opens its blocs and one is picked; the held order's chain opens the
    map with its piece's sheet, whose lock line opens the question again; F and Escape go into
    full screen and out; the page is as wide as the viewport. Back to the Classic layout after."""
    errors = len([p for p in problems if p.startswith("pageerror")])
    if not set_layout(page, "Map first"):
        return
    switch = page.locator(".rl-board-switch")
    try:
        switch.first.wait_for(timeout=10_000)
    except PlaywrightTimeout:
        check("the Capital switch is drawn with a held order to show", False)
        set_layout(page, "Classic layout")
        return
    corner = page.evaluate(
        "() => !!document.querySelector('.rl-tm-tools-start > .rl-board-switch:first-child')"
    )
    check("the Map and Capital switch sits at the map's top left", corner)
    switch.get_by_role("button", name="Capital").click()
    board = page.locator(".rl-cap")
    board.wait_for(timeout=10_000)
    kept = page.evaluate(
        """() => ({ bar: !!document.querySelector('.rl-roombar'),
          strip: !!document.querySelector('.rl-mapfirst-map .rl-tl'),
          map: !!document.querySelector('.rl-mapfirst-map .rl-tmap') })"""
    )
    report["capital_kept"] = kept
    check(
        "the Capital takes the map's place, the bar and the season's strip kept",
        kept["bar"] and kept["strip"] and not kept["map"],
        str(kept),
    )
    rows = [t.strip() for t in board.locator("button.rl-cap-q").all_inner_texts()]
    report["capital_rows"] = rows
    check(  # the kind line is drawn in capitals
        "the Capital lists the held order as a question",
        any(LOCK_WHO.upper() in r.upper() for r in rows),
        str(rows),
    )
    width = page.evaluate("document.documentElement.scrollWidth")
    check("the Capital fits the viewport", width <= SIZE[0], str(width))
    chamber = board.locator("button.rl-cap-chamber")
    if chamber.count():
        chamber.first.click()
        piece = board.locator(".rl-cap-blocs button.rl-cap-piece")
        piece.first.wait_for(timeout=10_000)
        piece.first.click()
        card = board.locator(".rl-cap-side .rl-cap-card")
        card.wait_for(timeout=10_000)
        report["capital_bloc"] = card.inner_text()
        check("picking a bloc shows its card in the right column", card.count() == 1)
        shoot(page, "40-capital-bloc")
    else:
        report["capital_bloc"] = "no chamber in this seat's view"
    held = board.locator("button.rl-cap-q.k-held")
    held.first.click()
    chain = board.locator(".rl-cap-chain")
    chain.wait_for(timeout=10_000)
    report["capital_chain"] = chain.inner_text()
    check("the held order's chain names who holds it", LOCK_WHO in chain.inner_text())
    shoot(page, "41-capital-held-chain")
    to_map = board.locator("button.rl-cap-tomap")
    if to_map.count():
        to_map.click()
        sheet = page.locator(".rl-over[data-sheet=piece]")
        sheet.wait_for(timeout=10_000)
        check(
            "the held order opens the map with its piece's sheet", LOCK_PIECE in sheet.inner_text()
        )
        back = sheet.locator("button.rl-held-capital")
        back.first.click()
        page.locator(".rl-cap button.rl-cap-q.k-held[aria-pressed=true]").wait_for(timeout=10_000)
        check("the lock's line in the piece's sheet opens the question again", True)
    else:
        check("the held order's piece is on the map", False, str(report["capital_chain"]))
    board.locator("button.rl-cap-q.k-held").first.focus()
    page.keyboard.press("f")
    page.locator(".rl-full .rl-cap").wait_for(timeout=10_000)
    check("F takes the Capital into full screen", True)
    shoot(page, "42-capital-full")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    check(
        "Escape gives the room back",
        page.locator(".rl-full").count() == 0 and page.locator(".rl-cap").count() == 1,
    )
    page.locator(".rl-board-switch").get_by_role("button", name="Map").click()
    page.locator(".rl-mapfirst-map .rl-tmap").wait_for(timeout=10_000)
    check("one tap gives the map back", True)
    check(
        "the Capital raises no page error",
        len([p for p in problems if p.startswith("pageerror")]) == errors,
    )
    set_layout(page, "Classic layout")


def phone_board(page: Page, report: dict[str, object]) -> None:
    """At 390 wide: the map shows, one lit place is tapped, the page is as wide as the viewport."""
    figure = page.locator("figure.rl-map-figure")
    figure.scroll_into_view_if_needed()
    box = figure.bounding_box() or {"width": 0, "height": 0}
    check(
        "the phone shows the map",
        figure.is_visible() and 0 < box["width"] <= SIZE[0] and box["height"] > 0,
        str(box),
    )
    # A tap lands on whatever is on top at the mark's centre; take the first own force it reaches
    # (on the whole territory map at this width a mark at the frame's edge is cut by it).
    own = page.evaluate(
        """() => {
      const out = { cut: 0, hit: null };
      for (const m of document.querySelectorAll('.rl-mk.rl-side-own')) {
        m.scrollIntoView({ block: 'center' });
        const r = m.getBoundingClientRect();
        const x = r.left + r.width / 2;
        const y = r.top + r.height / 2;
        const on = document.elementFromPoint(x, y);
        if (on && m.contains(on)) {
          out.hit = { x, y, label: m.getAttribute('aria-label') };
          break;
        }
        out.cut += 1;
      }
      return out;
    }"""
    )
    report["phone_cut_forces"] = own["cut"]
    check(
        "one of the seat's own forces can be tapped on the phone", own["hit"] is not None, str(own)
    )
    if own["hit"] is None:
        return
    report["phone_picked"] = own["hit"]["label"]
    page.touchscreen.tap(own["hit"]["x"], own["hit"]["y"])
    report["phone_territory"] = picked(page)
    page.wait_for_timeout(300)
    # A tap lands on whatever is on top at the place's centre; take the first lit place it reaches.
    spot = page.evaluate(
        """() => {
      const out = { open: 0, hit: null };
      for (const t of document.querySelectorAll('.rl-map-target:not([aria-disabled=true])')) {
        t.scrollIntoView({ block: 'center' });
        const r = t.querySelector('circle').getBoundingClientRect();
        const x = r.left + r.width / 2;
        const y = r.top + r.height / 2;
        const on = document.elementFromPoint(x, y);
        if (on && t.contains(on)) {
          out.hit = { x, y, label: t.getAttribute('aria-label') };
          break;
        }
        out.open += 1;
      }
      return out;
    }"""
    )
    report["phone_covered_places"] = spot["open"]
    check("a lit place can be tapped on the phone", spot["hit"] is not None, str(spot))
    if spot["hit"] is None:
        return
    report["phone_tap_to"] = spot["hit"]["label"]
    page.touchscreen.tap(spot["hit"]["x"], spot["hit"]["y"])
    page.wait_for_timeout(300)
    check(
        "a tap on a lit place chooses it",
        page.locator(".rl-map-target[aria-pressed=true]").count() == 1,
        spot["hit"]["label"],
    )
    width = page.evaluate("document.documentElement.scrollWidth")
    check("the phone's page is as wide as the viewport", width == SIZE[0], str(width))
    page.screenshot(path=str(OUT / f"00c-phone-board-{SIZE[0]}x{SIZE[1]}.png"), full_page=True)


STEPS_SHOWN = ".rl-op-everyone, .rl-cast-flat:not([hidden])"


def show_everyone(page: Page) -> None:
    """Open the flat cast under the opening's steps, once the screen has read the opening."""
    page.locator(STEPS_SHOWN).first.wait_for(timeout=30_000)
    toggle = page.locator("button.rl-op-everyone")
    if toggle.count() and toggle.get_attribute("aria-expanded") == "false":
        toggle.click()


def step_texts(page: Page) -> list[str]:
    return [t.strip() for t in page.locator(".rl-op-step").all_inner_texts()]


def opening_steps(page: Page, report: dict, name: str) -> None:
    """A ready-made game opens on a nation, a path and a person: walked by keyboard alone at
    desktop width and by taps at 390, with a nation of one path on the way."""
    page.locator(".rl-op").wait_for(timeout=30_000)
    nations = page.locator("button.rl-op-nation").count()
    report["opening_nations"] = nations
    check("the opening opens on the nation step", nations >= 2, str(nations))
    check(
        "the opening draws the seats left as a meter",
        page.locator(".rl-op-seats[role=meter] .rl-op-seat").count() > 0,
    )
    check(
        "the flat cast waits behind Show everyone",
        page.locator(".rl-cast-flat[hidden]").count() == 1,
    )
    shoot(page, "00o-opening-nation")
    one = page.evaluate(
        """async () => {
          const r = await fetch('/api/new/opening', { method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' }, body: '{}' });
          const o = (await r.json()).opening;
          return o.nations.find((n) => n.paths.length === 1 && n.key !== null)?.name ?? null;
        }"""
    )
    check("a nation is reached and chosen", press(page, "button.rl-op-nation", one), str(one))
    page.locator(".rl-op-person").first.wait_for(timeout=10_000)
    steps = step_texts(page)
    report["opening_one_path_steps"] = steps
    check(
        "a nation with one path passes the path step and shows it chosen",
        page.locator("button.rl-op-path").count() == 0
        and steps[1].endswith("(the only one)")
        and page.locator("span.rl-op-step.fixed").count() == 1,
        str(steps),
    )
    shoot(page, "00p-opening-one-path")
    check("Back to the nations is reached", press(page, "button.rl-op-back", "\u2039 Nations"))
    check(
        "the United States is reached and chosen",
        press(page, "button.rl-op-nation", "United States"),
    )
    page.locator("button.rl-op-path").first.wait_for(timeout=10_000)
    check("the paths are the nation's two", page.locator("button.rl-op-path").count() == 2)
    shoot(page, "00q-opening-path")
    check("the political path is reached and chosen", press(page, "button.rl-op-path", "Political"))
    card = page.locator(".rl-op-person", has_text=name)
    card.wait_for(timeout=10_000)
    check("the person card shows the office", card.locator(".rl-op-office").count() == 1)
    shoot(page, "00r-opening-person")
    axe(page, "the opening")
    width = page.evaluate("document.documentElement.scrollWidth")
    check("the opening is as wide as the viewport", width <= SIZE[0], str(width))
    check("Take this seat is reached", press(page, "button.rl-op-take", f"Take this seat: {name}"))
    page.get_by_role("heading", name=f"You are {name}").wait_for(timeout=60_000)


def play_from_dossier(page: Page, report: dict, name: str) -> None:
    """Open a cast card's dossier, check it reads as a dossier, and play that person."""
    page.get_by_role("button", name=f"{name}: open the dossier").click()
    dialog = page.locator("dialog.rl-cd[open]")
    dialog.wait_for(timeout=10_000)
    heads = [t.strip().lower() for t in dialog.locator("h3").all_inner_texts()]
    report["cast_dossier_headings"] = heads
    check("the cast dossier carries a biography", "biography" in heads, str(heads))
    check("the cast dossier carries the arena", "your arena" in heads, str(heads))
    shoot(page, "00x-cast-dossier")
    page.get_by_role("button", name=f"Play {name}").click()
    yes = dialog.get_by_role("button", name=f"Yes, play {name}")
    yes.wait_for(timeout=10_000)
    check(
        "a pick asks first, with focus on Yes",
        bool(page.evaluate("() => document.activeElement?.textContent?.startsWith('Yes, play')")),
    )
    yes.click()
    page.get_by_role("heading", name=f"You are {name}").wait_for(timeout=60_000)


def release_and_repick(page: Page, report: dict, name: str) -> None:
    """Give the person up behind its confirm, see the cast again, then play them again."""
    page.get_by_role("button", name="Choose someone else").click()
    keep = page.get_by_role("button", name=f"Keep {name}")
    keep.wait_for(timeout=10_000)
    check(
        "a release asks first, with focus on Keep",
        bool(page.evaluate("() => document.activeElement?.textContent?.startsWith('Keep ')")),
    )
    shoot(page, "00c-release-confirm")
    page.get_by_role("button", name="Yes, choose again").click()
    page.get_by_role("heading", name="Choose who you will play").wait_for(timeout=30_000)
    show_everyone(page)
    check(
        "a released person is free on the cast again",
        page.get_by_role("button", name=f"{name}: open the dossier").count() == 1,
    )
    play_from_dossier(page, report, name)


def begin_with_crawl(page: Page, report: dict) -> None:
    """Begin plays the crawl while the server works; Continue once it says it is ready."""
    page.get_by_role("button", name="Begin the game").click()
    crawl = page.locator("dialog.rl-intro[open]")
    crawl.wait_for(timeout=10_000)
    paragraphs = crawl.locator(".rl-intro-crawl p").count()
    report["crawl_paragraphs"] = paragraphs
    check("Begin plays the opening crawl", paragraphs > 0, str(paragraphs))
    go = crawl.get_by_role("button", name="Continue")
    held = go.is_disabled() or crawl.locator(".rl-intro-status", has_text="Ready").count() == 1
    check("Continue waits while Begin runs", held)
    crawl.locator(".rl-intro-status", has_text="Ready").wait_for(timeout=120_000)
    check("Continue opens once the game is ready", go.is_enabled())
    shoot(page, "00y-crawl")
    crawl.get_by_role("button", name="Continue").click()


def through_intro(page: Page, report: dict) -> None:
    """The room opens on the intro once per game: the crawl if not yet seen, then the splash."""
    intro = page.locator("dialog.rl-intro[open]")
    try:
        intro.wait_for(timeout=5_000)
    except Exception:
        check("the room opens on the intro before the first order", False, "no intro dialog")
        return
    if page.locator("dialog.rl-intro-splash[open]").count() == 0:
        intro.get_by_role("button", name="Continue").click()
    splash = page.locator("dialog.rl-intro-splash[open]")
    splash.wait_for(timeout=10_000)
    title = splash.locator("h2").inner_text()
    report["splash_title"] = title
    check("the splash names the seat", title.lower().startswith("you are "), title)
    check(
        "focus lands on the splash heading",
        bool(page.evaluate("() => document.activeElement?.id === 'rl-intro-splash-title'")),
    )
    check("the aide greets the seat on the splash", splash.locator("section.rl-brief").count() == 1)
    check(
        "the splash leaves the portrait and biography to the select card",
        splash.locator("img").count() == 0 and "As history had it" not in splash.inner_text(),
    )
    report["splash_papers"] = splash.locator(".rl-intro-paper").count()
    report["splash_matters"] = splash.locator(".rl-intro-matters li").count()
    no_filler(page, "the splash")
    shoot(page, "00z-splash")
    splash.get_by_role("button", name="Take your desk").click()
    page.wait_for_timeout(300)
    check(
        "Take your desk closes the intro",
        page.locator("dialog.rl-intro[open]").count() == 0,
    )


def header_and_menu(page: Page, report: dict[str, object], host: bool) -> None:
    who = page.locator(".frame-head .identity")
    report["header_identity"] = who.inner_text() if who.count() else ""
    check(
        "the header names who the player plays",
        who.count() == 1
        and "playing as" in who.inner_text().lower()
        and len(who.inner_text()) > 20,
        str(report["header_identity"]),
    )
    for label, name in (("open the setting", "setting"), ("open the dossier", "character")):
        page.locator(f"button.head-link[aria-label$='{label}']").click()
        dossier = page.locator("dialog.rl-dos[open]")
        dossier.wait_for()
        report[f"{name}_dossier"] = dossier.inner_text()[:800]
        check(f"the {name} dossier opens from the header", dossier.locator("h3").count() > 0)
        no_filler(page, f"the {name} dossier")
        shoot(page, f"01-{name}-dossier")
        axe(page, f"{name} dossier")
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        check(f"Esc closes the {name} dossier", page.locator("dialog.rl-dos[open]").count() == 0)
    page.get_by_role("button", name="Game").click()
    menu = page.locator("dialog.rl-menu")
    menu.wait_for()
    report["game_menu"] = menu.inner_text()
    check("the game menu opens from the header", menu.is_visible())
    if host:
        check(
            "the host's menu offers End game",
            menu.get_by_role("button", name="End game…").count() == 1,
        )
        check("the host's menu offers Pause", menu.get_by_role("button", name="Pause").count() == 1)
        check(
            "the host's menu does not offer Leave",
            menu.get_by_role("button", name="Leave game…").count() == 0,
        )
    else:
        check(
            "a player's menu offers Leave",
            menu.get_by_role("button", name="Leave game…").count() == 1,
        )
    shoot(page, "01-game-menu")
    menu.get_by_role("button", name="Close").click()


def wake_header(page: Page, report: dict[str, object], host: bool) -> None:
    wake = page.locator(".frame-head .rl-wake")
    report["wake_header"] = wake.inner_text()
    check("the header names no wake number", "Wake " not in wake.inner_text(), wake.inner_text())
    strip = page.get_by_role("region", name="Where the day stands")
    check("the status strip shows the world date", strip.locator(".rl-date").count() == 1)
    check(
        "the header leaves the date to the strip",
        page.locator(".frame-head .rl-clock .title").count() == 0,
    )
    check("the header says when the wake closes", "Closes " in wake.inner_text())
    check("the header counts players done", "done" in wake.inner_text())
    check(
        "the strip offers Done for today and the header does not",
        strip.get_by_role("button", name="Done for today").count() == 1
        and page.locator(".frame-head").get_by_role("button", name="Done for today").count() == 0,
    )
    check(
        "Run the day now is hidden (a one-player game, or a seat that is not the host)",
        page.get_by_role("button", name=RUN_NOW).count() == 0,
    )


def desk(page: Page, report: dict[str, object], v2: bool) -> None:
    room = page.locator("main.rl-room")
    for region in ("Papers", "Desk", "Your orders"):
        check(
            f"the room shows {region}",
            room.get_by_role("region", name=region).count()
            + room.get_by_role("complementary", name=region).count()
            >= 1,
        )
    check(
        "the room shows the play style", room.get_by_role("group", name="How you play").count() == 1
    )
    if v2:
        check("the play style shows as chosen", page.get_by_label("Beginner").is_checked())
    needs = room.get_by_role("region", name="Needs your answer")
    report["needs_your_answer"] = needs.inner_text() if needs.count() else ""
    ideas = room.get_by_role("region", name="Ideas")
    report["ideas"] = ideas.inner_text() if ideas.count() else ""
    check("the desk shows needs-your-answer or ideas", needs.count() + ideas.count() >= 1)
    no_filler(page, "the desk")
    shoot(page, "02-room")
    axe(page, "room")


def tray(page: Page, report: dict[str, object]) -> None:
    rows = page.locator(".rl-tray .rl-row")
    if rows.count() == 0:
        advance(page, "03-first-wake")  # a new game's first papers arrive on the first wake
    check("the in-tray lists papers", rows.count() > 0, str(rows.count()))
    unread = tab_count(page, "Unread")
    group = page.locator(".rl-tray .rl-row-group.rl-row-unread, .rl-tray .rl-row-unread").first
    group.click()
    paper = page.locator(".rl-tray .rl-row-paper").first
    if paper.count():
        paper.click()
    page.locator(".rl-page").wait_for(timeout=30_000)
    page.wait_for_timeout(300)
    prose = page.locator(".rl-page .rl-prose")
    report["sample_prose"] = prose.first.inner_text()[:600] if prose.count() else ""
    check(
        "an opened paper reads beside the desk",
        page.get_by_role("region", name="Desk").is_visible(),
    )
    no_filler(page, "an opened paper")
    shoot(page, "04-paper")
    axe(page, "paper")
    page.get_by_role("button", name="Flag", exact=True).click()
    page.get_by_role("button", name="Unflag").wait_for()
    check(
        "opening a paper marks it read",
        tab_count(page, "Unread") == unread - 1,
        f"unread {unread} -> {tab_count(page, 'Unread')}",
    )
    check("flagging counts under Flagged", tab_count(page, "Flagged") == 1)
    page.get_by_role("tab", name="Flagged 1").click()
    page.wait_for_timeout(200)
    check("the Flagged filter shows one row", page.locator(".rl-tray .rl-row").count() >= 1)
    page.get_by_role("tab").filter(has_text="All").first.click()
    page.wait_for_timeout(200)


def tab_count(page: Page, word: str) -> int:
    tab = page.get_by_role("tab").filter(has_text=word).first
    return int(tab.inner_text().split()[-1])


def orders(page: Page, report: dict[str, object], v2: bool) -> None:
    cards = page.locator(".rl-oc-card")
    before = cards.count()
    choose = page.locator("main.rl-room").get_by_role("button", name="Choose")
    if v2 and choose.count():
        choose.first.click()
        page.locator(".rl-status.said").wait_for(timeout=30_000)
        page.wait_for_timeout(300)
        report["chosen_reply"] = page.locator(".rl-status").inner_text()
        check(
            "a chosen idea joins your orders",
            cards.count() == before + 1,
            f"{before} -> {cards.count()}",
        )
        check(
            "a chosen idea shows as filed",
            page.locator("main.rl-room").get_by_text("Filed").count() >= 1,
        )
        before = cards.count()
        shoot(page, "05-chosen")
    forms = page.locator("details.rl-forms")
    check("the desk folds the standard forms", forms.count() == 1)
    forms.locator("summary").click()
    instruments = page.locator(".rl-instrument")
    check("the standard forms list instruments", instruments.count() > 0)
    snake = [t for t in instruments.locator("strong").all_inner_texts() if "_" in t]
    check("instrument names are in words", not snake, ", ".join(snake))
    fleet = page.locator("form.rl-form[aria-label='Move a fleet'] select[name='to'] option")
    if fleet.count():
        places = [t.strip() for t in fleet.all_text_contents()[1:]]
        report["fleet_places"] = places
        check(
            "the fleet form offers every place on the map, in words",
            len(places) > 4 and not [t for t in places if "_" in t],
            str(len(places)),
        )
    people = page.locator("form.rl-directive .rl-recipient")
    titles = people.locator(".rl-person-title").all_inner_texts()
    report["recipients"] = people.all_inner_texts()
    check(
        "each recipient shows a title",
        people.count() > 0 and len(titles) == people.count() and all(titles),
        str(report["recipients"]),
    )
    words = "Send word that our escorts will see the convoys as far as Iceland."
    directive = page.locator("form.rl-directive")
    check("the desk offers a directive", directive.count() == 1)
    directive.get_by_label("Your instruction").fill(words)
    directive.get_by_role("button", name="Prepare the order").click()
    card = page.locator(".rl-proposal")
    card.wait_for(timeout=WAKE_MS)
    page.wait_for_timeout(300)
    report["directive_reading"] = card.inner_text()
    shoot(page, "06-directive-reading")
    axe(page, "directive")
    check("the reading quotes the instruction", words in card.inner_text())
    check("the reading is in words", "_" not in card.inner_text(), card.inner_text())
    sign = card.get_by_role("button", name="Sign and send")
    if sign.count():
        sign.click()
        page.locator(".rl-status.said").filter(has_text="Sent to").wait_for()
        report["directive_reply"] = page.locator(".rl-status").inner_text()
        before += 1
    else:
        card.get_by_role("button", name="Revise").click()
        kept = page.locator("form.rl-directive textarea").input_value()
        check("Revise keeps the instruction", kept == words, kept)
    page.wait_for_timeout(300)
    check(
        "a signed directive joins your orders",
        cards.count() == before,
        f"{before} -> {cards.count()}",
    )
    if forms.get_attribute("open") is None:  # a redraw folds the forms again
        forms.locator("summary").click()
    first = instruments.first
    first.get_by_role("button", name="Draft").click()
    form = first.locator("form.rl-form")
    form.wait_for()
    fill(form)
    form.get_by_role("button", name="Sign and send").click()
    page.locator(".rl-status.said").filter(has_text="Sent to").wait_for()
    report["sent_reply"] = page.locator(".rl-status").inner_text()
    page.wait_for_timeout(300)
    check(
        "a signed form joins your orders",
        cards.count() == before + 1,
        f"{before} -> {cards.count()}",
    )
    report["orders"] = page.locator(".rl-oc").inner_text()[:1200]
    check("your orders are in words", "_" not in str(report["orders"]))
    if not v2:  # the slice declares no allies or conflicts, so it has no opponents list
        listed = page.locator(".rl-people")
        report["opponents"] = listed.inner_text()[:600] if listed.count() else ""
        said = str(report["opponents"]).lower()
        check(
            "the people roster opens on who is set against you",
            all(w in said for w in ("opponents", "hideki tojo"))
            and bool(page.locator(".rl-pp-meter").count()),
            said[:200],
        )
    shoot(page, "07-orders")
    axe(page, "orders")


def messenger(page: Page, report: dict[str, object]) -> None:
    page.get_by_role("button", name=re.compile(r"^Messages")).click()
    dock = page.locator(".rl-msgr")
    dock.get_by_role("tab", name="Chats").wait_for()
    rows = dock.locator(".rl-cl-row")
    check("the chats list opens with the aide first", "Your aide" in rows.first.inner_text())
    rows.first.click()
    page.locator(".rl-msgr .rl-brief").wait_for(timeout=WAKE_MS)
    report["aide_brief"] = page.locator(".rl-msgr .rl-brief").inner_text()[:600]
    check("the aide's thread holds its brief", len(str(report["aide_brief"])) > 20)
    check("with the brief open the composer stays in the dock", composer_in_dock(page))
    theirs = dock.locator(".rl-th-bubble.theirs:not(.rl-typing)")
    before = theirs.count()
    send(page, "How do I move a fleet?")
    check(
        "while a message is out the composer waits and the room does not",
        not dock.locator(".rl-th-input").is_editable() and room_free(page),
    )
    check("focus stays in the dock while a message is out", in_messenger(page))
    theirs.nth(before).wait_for(timeout=WAKE_MS)
    page.wait_for_timeout(300)
    check(
        "the aide answers in its thread", theirs.count() > before, f"{before} -> {theirs.count()}"
    )
    check("the typing bubble goes when the answer comes", dock.locator(".rl-typing").count() == 0)
    check("focus stays in the messenger after the aide answers", in_messenger(page))
    shoot(page, "08-aide-thread")
    axe(page, "aide thread")
    dock.get_by_label("Message", exact=True).fill("A draft I have not sent")
    dock.get_by_role("button", name="Back").click()
    rows.first.click()
    check(
        "a draft survives leaving the thread",
        dock.get_by_label("Message", exact=True).input_value() == "A draft I have not sent",
    )
    dock.get_by_label("Message", exact=True).fill("")
    dock.get_by_role("button", name="Back").click()
    report["chat_rows"] = rows.count()
    # Ask the first of the inner circle: they always answer, where anyone outside it may
    # decline on that tick's roll, and a smoke that fails on a roll is no gate.
    dock.get_by_role("tab", name="Contacts").click()
    cards = dock.locator(".rl-ct-row")
    for i in range(cards.count()):
        cards.nth(i).click()
        if dock.get_by_role("button", name="Message", exact=True).count():
            break
        dock.locator(".rl-ct-back").click()
    who = dock.locator(".rl-ct-name").first.inner_text()
    dock.get_by_role("button", name="Message", exact=True).click()

    before = theirs.count()
    send(page, "Should we wait for the Senate before we move?")
    theirs.nth(before).wait_for(timeout=WAKE_MS)
    report["consult"] = theirs.last.inner_text()
    check(f"a consult with {who} shows the answer", theirs.count() > before)
    check("focus stays in the messenger after a consult", in_messenger(page))
    papers = dock.locator(".rl-th .rl-th-open").all_inner_texts()
    report["consult_papers"] = papers
    check(
        f"{who}'s thread holds a line for each letter and no other paper",
        all(t.startswith("Letter received: ") for t in papers),
        str(papers),
    )
    shoot(page, "09-consult")
    dock.get_by_role("button", name="Back").click()
    dock.get_by_role("tab", name="Contacts").click()
    if dock.locator(".rl-ct-back").count():  # the contact asked above is still open
        dock.locator(".rl-ct-back").click()
    report["contacts"] = dock.inner_text()[:1200]
    check(
        "contacts are grouped",
        any(
            g in str(report["contacts"]).lower() for g in ("inner circle", "government", "foreign")
        ),
    )
    shoot(page, "10-contacts")
    axe(page, "contacts")
    outsider(page, report)
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    check("Esc closes the messenger", page.locator(".rl-msgr-panel").count() == 0)


def composer_in_dock(page: Page) -> bool:
    """The Send button sits inside the dock and on screen, not under the launcher or the
    phone's tab bar."""
    return bool(
        page.evaluate(
            """() => {
      const p = document.querySelector('.rl-msgr-panel')?.getBoundingClientRect();
      const s = document.querySelector('.rl-msgr .rl-th-send')?.getBoundingClientRect();
      const bar = document.querySelector('.rl-tabbar');
      const floor = bar && getComputedStyle(bar).display !== 'none'
        ? bar.getBoundingClientRect().top : innerHeight;
      return !!p && !!s && s.bottom <= p.bottom + 1
        && s.bottom <= floor + 1 && s.right <= innerWidth;
    }"""
        )
    )


def send(page: Page, text: str) -> None:
    dock = page.locator(".rl-msgr")
    dock.get_by_label("Message", exact=True).fill(text)
    dock.get_by_role("button", name="Send").click()


def room_free(page: Page) -> bool:
    """The desk is not behind a busy overlay while a message is out."""
    return page.locator(".rl-busy, [aria-busy='true']").count() == 0


def outsider(page: Page, report: dict[str, object]) -> None:
    """Message the first contact outside the inner circle, if the seat can reach one."""
    dock = page.locator(".rl-msgr")
    rows = dock.locator(".rl-ct-row")
    for i in range(rows.count()):
        rows.nth(i).click()
        if (
            dock.locator(".rl-ct-note").count()
            and dock.get_by_role("button", name="Message", exact=True).count()
        ):
            break
        dock.locator(".rl-ct-back").click()
    else:
        report["outsider"] = "no reachable outsider"
        return
    who = dock.locator(".rl-ct-name").inner_text()
    dock.get_by_role("button", name="Message", exact=True).click()
    check(
        f"a thread with {who} says a message changes nothing",
        dock.locator(".rl-th-tie").count() == 1,
    )
    theirs = dock.locator(".rl-th-bubble.theirs:not(.rl-typing)")
    send(page, "Where do you stand on the convoy question?")
    dock.locator(".rl-typing").wait_for(state="detached", timeout=WAKE_MS)
    page.wait_for_timeout(300)
    said = theirs.last.inner_text() if theirs.count() else ""
    error = page.locator("[role=alert]").all_inner_texts()
    report["outsider"] = {"who": who, "answer": said[:400], "refused": error}
    check(
        f"{who} answers or declines in words",
        bool(said) or any("did not answer" in e for e in error),
    )
    shoot(page, "11-outsider")
    dock.get_by_role("button", name="Back").click()


def in_messenger(page: Page) -> bool:
    return bool(page.evaluate("() => !!document.activeElement?.closest('.rl-msgr-panel')"))


def after_wake(page: Page, report: dict[str, object], host: bool) -> None:
    pace = page.locator(".rl-pace").first.inner_text()
    t0 = time.time()
    advance(page, "11-day")
    report["advance_seconds"] = round(time.time() - t0, 1)
    moved = page.locator(".rl-pace").first.inner_text()
    check("a day moves the world date", moved != pace, f"{pace!r} -> {moved!r}")
    check("pace line has no engine words", "horizon" not in moved, moved)
    report["pace_after_advance"] = moved
    titles = page.locator(".rl-tray .rl-row-title").all_inner_texts()
    report["titles_after_advance"] = titles
    check(
        "no title shows an ISO date",
        not any(c.isdigit() and "-" in t for t in titles for c in t[-3:]),
    )
    shoot(page, "12-room-after-day")


def narrow(page: Page) -> None:
    page.wait_for_timeout(1_000)  # the wake player opens when its pages arrive, over the room
    playback_closed(page)
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(300)
    width = page.evaluate("document.documentElement.scrollWidth")
    check("a narrow room has no sideways scroll", width <= 390, str(width))
    check(
        "a narrow room repeats Done for today at the desk's foot",
        page.locator(".rl-commit-foot").first.is_visible(),
    )
    page.screenshot(path=str(OUT / "14n-room-390x844.png"), full_page=True)
    axe(page, "narrow room")
    page.get_by_role("button", name=re.compile(r"^Messages")).click()
    page.locator(".rl-msgr").get_by_role("tab", name="Chats").click()
    page.locator(".rl-msgr .rl-cl-row").first.click()
    page.locator(".rl-msgr .rl-th-send").wait_for()
    check("a narrow dock keeps the composer on screen", composer_in_dock(page))
    check(
        "a narrow dock's launcher covers no message or control",
        bool(
            page.evaluate(
                """() => {
      const b = document.querySelector('.rl-msgr-btn').getBoundingClientRect();
      const hit = (r) => !(r.right <= b.left || r.left >= b.right
        || r.bottom <= b.top || r.top >= b.bottom);
      const parts = '.rl-th, .rl-th-compose, .rl-msgr-tabs, .rl-th-head';
      return ![...document.querySelectorAll(parts)].some((e) => hit(e.getBoundingClientRect()));
    }"""
            )
        ),
    )
    width = page.evaluate("document.documentElement.scrollWidth")
    check("a narrow dock has no sideways scroll", width <= 390, str(width))
    page.screenshot(path=str(OUT / "14n-aide-390x844.png"))
    page.get_by_role("navigation", name="Room panels").get_by_role("button", name="Papers").click()
    page.wait_for_timeout(200)
    panel = page.locator(".rl-msgr-panel")
    check(
        "a narrow room's Papers tab closes the messenger over it",
        panel.count() == 0 or not panel.first.is_visible(),
    )
    if panel.count() and panel.first.is_visible():
        page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    page.set_viewport_size({"width": SIZE[0], "height": SIZE[1]})
    page.wait_for_timeout(300)


def end_game(page: Page, report: dict[str, object], v2: bool) -> None:
    page.get_by_role("button", name="Game").click()
    menu = page.locator("dialog.rl-menu")
    menu.get_by_role("button", name="End game…").click()
    confirm = menu.locator(".rl-confirm")
    check("ending asks first", confirm.is_visible() and "for everyone" in confirm.inner_text())
    shoot(page, "15-end-confirm")
    menu.get_by_role("button", name="End the game").click()
    page.get_by_role("heading", name="Start a game").wait_for(timeout=30_000)
    check("after ending, the player can start a new game", True)
    shoot(page, "16-after-end")
    if v2:
        page.wait_for_load_state("networkidle")  # let the new-game screen finish loading
        page.goto(BASE + "/#home")
        page.reload()  # the client reads its route once per load
        page.get_by_role("heading", name="Ended games").wait_for(timeout=30_000)
        shoot(page, "17-ended-games")
        axe(page, "ended games")
        page.get_by_role("link", name="See the reveal of Autumn 1941 (engine v2 slice)").click()
        page.get_by_role(
            "heading", name="Autumn 1941 (engine v2 slice): what was hidden"
        ).wait_for()
        page.get_by_role("heading", name="Franklin D. Roosevelt").first.wait_for(timeout=30_000)
        page.wait_for_timeout(300)
        report["reveal"] = page.locator("main").inner_text()[:1500]
        check(
            "the reveal shows how the seat played",
            "how they played" in str(report["reveal"]).lower(),
        )
        check("the reveal is in words", "_" not in str(report["reveal"]))
        no_filler(page, "the reveal")
        shoot(page, "18-reveal")
        axe(page, "reveal")


# --- the new room, walked on a canned Salt Strait game (SMK) ---------------------------------
#
# A second game on a second account, after the autumn 1941 walk: the Marshal of Ostrel on
# Beginner, with the Varda leader a second player who is only ever Done (the engine answers
# for a nation only through a seat a human holds, so an offer or a conference needs one).
# The same steps run twice, by keyboard alone at desktop width and by taps at 390 by 844.

SALT = "Salt Strait"
SALT_LEVY = "The Ostrel Levy"
SALT_FRONT = "The Saltworks Coast"
SALT_WORDING = "Our levy keeps off that shore this season."
SALT_SPEECH = "We speak on the march south, and hold the line."
SALT_CALL = "The strait stays open to every flag."
LABEL = "(a.getAttribute('aria-label') || a.labels?.[0]?.textContent || a.textContent || '').trim()"


def named(sel: str, text: str) -> str:
    """A JS predicate on `a`: it matches `sel` and its name starts with `text`."""
    return f"a.matches({json.dumps(sel)}) && {LABEL}.startsWith({json.dumps(text)})"


def reach(page: Page, sel: str, text: str = "") -> bool:
    """Put the focus on the control `sel` named `text`: by Tab on a desktop, and on a phone by
    tapping it (which presses a button, puts the cursor in a field and ticks a box)."""
    if not PHONE:
        return tab_to(page, named(sel, text), 400)
    found = (
        f"[...document.querySelectorAll({json.dumps(sel)})]"
        f".find((a) => a.getClientRects().length && {named(sel, text)})"
    )
    # Playwright's tap scrolls the control into view, waits for it to be still and taps a
    # point where the control itself is on top (a mark under the sticky bar, or cut by the
    # map's frame, is not tapped); a hand-made tap at a mark's centre landed on the map
    if not page.evaluate(
        f"() => {{ document.querySelector('[data-smk-reach]')?.removeAttribute('data-smk-reach'); "
        f"const a = {found}; a?.setAttribute('data-smk-reach', ''); return !!a; }}"
    ):
        return False
    target = page.locator("[data-smk-reach]")
    try:
        target.scroll_into_view_if_needed(timeout=10_000)
        # a mark at the edge of the map's window is drawn in part: tap a point of it that shows
        target.tap(timeout=10_000, position=page.evaluate(SHOWN_POINT))
    except PlaywrightTimeout:
        return False
    return True


SHOWN_POINT = """() => {
  const a = document.querySelector('[data-smk-reach]');
  const r = a.getBoundingClientRect();
  for (const fy of [0.5, 0.65, 0.8, 0.35, 0.2, 0.9]) {
    for (const fx of [0.5, 0.3, 0.7]) {
      const x = r.left + r.width * fx;
      const y = r.top + r.height * fy;
      // on top here and 3 px around, so a tap rounded to a whole pixel still lands on it
      const near = [[0, 0], [0, -3], [0, 3], [-3, 0], [3, 0]].every(([dx, dy]) => {
        const e = document.elementFromPoint(x + dx, y + dy);
        return e && (e === a || a.contains(e));
      });
      if (near) return { x: r.width * fx, y: r.height * fy };
    }
  }
  return null;
}"""


def press(page: Page, sel: str, text: str = "", key: str = "Enter") -> bool:
    """Press a control the way the width is walked: Tab to it and a key, or a tap."""
    found = reach(page, sel, text)
    if found and not PHONE:
        page.keyboard.press(key)
    return found


def write(page: Page, sel: str, text: str, value: str) -> bool:
    found = reach(page, sel, text)
    if found:
        page.keyboard.type(value)
    return found


def said(loc: Locator) -> str:
    """A sheet's words as the page prints them in a lower case, so a heading's capitals do
    not matter."""
    return loc.inner_text().lower()


def over(page: Page) -> Locator:
    """The sheet over the map: the last of the room's sheets."""
    return page.locator(".rl-over").last


def sheet_open(page: Page, word: str) -> None:
    """Open a sheet of the room from the Game menu's list of every sheet, which is the quiet
    route to each on Beginner."""
    page.wait_for_timeout(300)
    press(page, "button", "Game")
    menu = page.locator("dialog.rl-menu[open]")
    menu.wait_for(timeout=10_000)
    check(f"the Game menu lists the {word} sheet", press(page, "dialog.rl-menu button", word))
    over(page).wait_for(timeout=10_000)
    page.wait_for_timeout(500)


def sheet_close(page: Page, word: str) -> None:
    """Close the open sheet by its Close button, and see the map again."""
    check(f"the {word} sheet has a Close button", press(page, ".rl-over button", "Close"))
    page.wait_for_timeout(400)
    check(f"the {word} sheet closes", page.locator(".rl-over").count() == 0)


def settle(page: Page, said: str, name: str) -> None:
    """Wait for the room's one status line to say `said`."""
    try:
        page.locator(".rl-status").filter(has_text=said).first.wait_for(timeout=30_000)
        check(name, True)
    except PlaywrightTimeout:
        check(name, False, page.locator(".rl-status").first.inner_text())


def salt_start(page: Page, report: dict[str, object], play: object) -> None:
    """A new account hosts Salt Strait as the Marshal of Ostrel, with a second account holding
    the Varda leader; the second only commits (`play.commit()`), through the API."""
    page.goto(BASE + "/")
    page.get_by_role("link", name="Create an account").click()
    page.get_by_role("heading", name="Create an account").wait_for()
    page.get_by_label("Handle").fill(f"rsalt{int(time.time()) % 100000}")
    page.get_by_label("Password").fill("a long enough passphrase")
    page.get_by_role("button", name="Create account").click()
    page.get_by_role("heading", name="Your recovery codes").wait_for()
    page.get_by_label("I've kept these somewhere safe").check()
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("heading", name="Join a game").wait_for()
    page.get_by_role("link", name="Start a new game").click()
    page.get_by_role("button", name=f"Start {SALT}").click()
    page.get_by_role("heading", name="Choose who you will play").wait_for(timeout=30_000)
    show_everyone(page)
    page.get_by_role("button", name="General Aske: open the dossier").click()
    dossier = page.locator("dialog.rl-cd[open]")
    dossier.wait_for(timeout=10_000)
    page.get_by_role("button", name="Play General Aske").click()
    dossier.get_by_role("button", name="Yes, play General Aske").click()
    page.get_by_role("heading", name="You are General Aske").wait_for(timeout=60_000)
    if not page.get_by_label("Beginner").is_checked():
        page.get_by_label("Beginner").check()
        page.locator(".play-style .outcome > *").first.wait_for(timeout=10_000)
    check("the Salt Strait seat plays on Beginner", page.get_by_label("Beginner").is_checked())
    page.get_by_role("button", name="Invite a player").click()
    page.locator(".outcome", has_text="Send this code").wait_for(timeout=10_000)
    code = re.search(
        r"Send this code[^\n]*\n+\s*([A-Z0-9-]{8,})", page.locator("body").inner_text()
    )
    check("the host is given a code for the second player", code is not None)
    play.join(code.group(1) if code else "")  # type: ignore[attr-defined]
    page.get_by_role("button", name="Begin the game").click()  # Salt Strait has no crawl
    page.locator("main.rl-board, main.rl-mapfirst").first.wait_for(timeout=60_000)
    page.wait_for_timeout(300)
    through_intro(page, report)
    check(
        "a Salt Strait game opens in the map-first room",
        page.locator("main.rl-mapfirst").count() == 1,
    )
    shoot(page, "20-salt-opening")


class Second:
    """The Varda leader's account, driven through the API: it joins, picks its leader and
    presses Done each wake, which is all the walk needs of it."""

    def __init__(self, playwright: object) -> None:
        self.api = playwright.request.new_context()  # type: ignore[attr-defined]

    def call(self, path: str, body: dict[str, object]) -> dict[str, object]:
        got = self.api.post(BASE + path, data=body)
        check(f"the second player's {path} answers", got.ok, str(got.status))
        return got.json() if got.ok else {}

    def join(self, code: str) -> None:
        handle = f"rsecond{int(time.time()) % 100000}"
        self.call("/api/signup", {"handle": handle, "password": "a long enough passphrase"})
        self.call("/api/seat/join", {"code": code})
        done = self.call("/api/new/pick", {"name": "Oren Vale"})
        check("the second player takes the Varda leader", "Oren Vale" in str(done.get("reply")))

    def commit(self) -> None:
        self.call("/api/realism/commit", {})


def playback_closed(page: Page) -> None:
    """Close the wake player if it opened over the room (Skip while it plays, To the map
    once it has played), so the room's own controls take a press again."""
    player = page.locator("dialog.rl-plb-dialog[open]")
    if not player.count():
        return
    shoot(page, "salt-playback")
    word = "To the map" if player.get_by_role("button", name="To the map").count() else "Skip"
    check(
        f"the wake player's {word} can be reached", press(page, "dialog.rl-plb-dialog button", word)
    )
    page.wait_for_timeout(400)
    check("the wake player closes", player.count() == 0)


def salt_day(page: Page, play: Second, name: str) -> None:
    """The second player presses Done, then the host does, which runs the day; the sheet of
    what happened is read and closed, and the wake player after it."""
    playback_closed(page)
    play.commit()
    before = world_day(page)
    check(f"{name}: Done for today can be reached", press(page, "button", "Done for today"))
    page.locator(".rl-status.said").filter(has_text="calendar moves").wait_for(timeout=WAKE_MS)
    sheet = page.locator("dialog.rl-hap[open]")
    sheet.wait_for(timeout=10_000)
    check(f"{name}: the day moves on", world_day(page) != before, before)
    shoot(page, f"{name}-happened")
    check(f"{name}: To the desk can be reached", press(page, "dialog.rl-hap button", "To the desk"))
    page.wait_for_timeout(500)
    check(f"{name}: What happened closes", page.locator("dialog.rl-hap[open]").count() == 0)
    page.wait_for_timeout(600)
    playback_closed(page)


def needs_list_opened(page: Page) -> None:
    """On a phone, What needs you is folded behind the Needs button: a tap unfolds it."""
    check("the Needs button opens What needs you", press(page, ".rl-needsbar button", "Needs"))
    page.locator(".rl-needs.open").first.wait_for(timeout=10_000)


def needs_list_closed(page: Page) -> None:
    """On a phone, fold What needs you away again by its Close button, if it is still open."""
    if page.locator(".rl-needs.open").count():
        check("What needs you has a Close button", press(page, ".rl-needs.open button", "Close"))
        page.wait_for_timeout(400)
    check("What needs you folds away", page.locator(".rl-needs.open").count() == 0)


def open_row(page: Page, text: str) -> bool:
    """Open in place the line of What needs you whose words hold `text`, by the width's way."""
    found = page.evaluate(
        "(t) => { document.querySelector('[data-smk-row]')?.removeAttribute('data-smk-row');"
        " const b = [...document.querySelectorAll('.rl-needs .rl-need-row')]"
        ".find((x) => x.getClientRects().length && x.textContent.toLowerCase().includes(t));"
        " if (!b) return false; b.setAttribute('data-smk-row', '');"
        " return b.getAttribute('aria-expanded') !== 'true'; }",
        text.lower(),
    )
    if not found:
        return page.locator("[data-smk-row]").count() > 0
    return press(page, "[data-smk-row]")


def needs_opened(page: Page, report: dict[str, object]) -> None:
    """\"What needs you\" opens from the keyboard (a tap on a phone), and its one matter opens."""
    if PHONE:
        needs_list_opened(page)
    listed = page.locator(".rl-needs").first
    check("What needs you lists the matter waiting", "make your position public" in said(listed))
    check("the matter's line opens in place", open_row(page, "position public"))
    check("Tab reaches a matter's Answer button", press(page, ".rl-needs button", "Answer"))
    over(page).wait_for(timeout=10_000)
    page.wait_for_timeout(500)
    shoot(page, "21-salt-needs")
    check("the matter opens its own sheet", "position public" in said(over(page)))
    sheet_close(page, "matter")
    if PHONE:
        needs_list_closed(page)


def salt_move(page: Page, report: dict[str, object]) -> None:
    """Pick the Ostrel levy in Harrow Pass and send it to the Saltworks Coast, next door."""
    errors = len([p for p in problems if p.startswith("pageerror")])
    check("the levy can be picked on the map", press(page, "[aria-label]", f"{SALT_LEVY}:"))
    page.wait_for_timeout(800)
    lit = page.locator(".rl-map-target")
    check("a picked piece lights the areas next to it", lit.count() > 0, str(lit.count()))
    check(
        "the Saltworks Coast is lit, a step from Harrow Pass",
        press(page, ".rl-map-target", f"Send to {SALT_FRONT}"),
    )
    page.locator(".rl-pup-chip").wait_for(timeout=10_000)
    shoot(page, "22-salt-move")
    marks = tl_marks(page)
    check("Send it files the move", press(page, ".rl-pup-chip button", "Send it"))
    settle(page, "Sent to", "the move is sent")
    page.wait_for_timeout(500)
    report["stl_move_marks"] = [marks, tl_marks(page)]
    check(
        "the move filed adds its mark to the season's strip",
        tl_marks(page) == marks + 1,
        str(report["stl_move_marks"]),
    )
    if page.locator(".rl-tl:not(.open) .rl-tl-head").count() and press(
        page, ".rl-tl-head", "The season"
    ):
        page.wait_for_timeout(300)
        shoot(page, "63-stl-after-move")
        press(page, ".rl-tl-head", "The season")
        page.wait_for_timeout(300)
    check(
        "the move raises no page error",
        len([p for p in problems if p.startswith("pageerror")]) == errors,
    )


def quiet_wake(page: Page) -> None:
    """Rule 2 starts in a quiet wake: the list says nothing waits but Done."""
    if PHONE:
        needs_list_opened(page)
    try:
        page.locator(".rl-needs", has_text="Nothing waits on you").first.wait_for(timeout=10_000)
    except PlaywrightTimeout:
        pass
    text = page.locator(".rl-needs").first.inner_text()
    check("the wake is quiet: only Done waits", "Nothing waits on you" in text, text[:200])
    if PHONE:
        needs_list_closed(page)


def statement(page: Page, first: bool = False) -> None:
    """From the Home sheet's composer: a statement on a theme of the nation's. The first, on
    the first day, answers the opening matter (make your position public), so the next wake
    is quiet; the second is rule 2's, in that quiet wake."""
    tag = "the opening statement" if first else "the statement"
    sheet_open(page, "World: Home")
    check(
        f"{tag}: the Home sheet offers Speak to the nation",
        press(page, "button", "Speak to the nation"),
    )
    page.wait_for_timeout(600)
    check(
        f"{tag}: the composer names the nation's themes and the cap",
        "the march south" in said(over(page)) and "at most" in said(over(page)),
    )
    check(
        f"{tag}: Tab reaches the composer's words",
        write(page, "textarea", "Your instruction", SALT_SPEECH),
    )
    check(f"{tag}: the aide reads it", press(page, "button", "Prepare the order"))
    over(page).get_by_role("button", name="Sign and send").wait_for(timeout=30_000)
    check(
        f"{tag}: the staff's read names the groups it moves",
        "your staff's read" in said(over(page)),
    )
    shoot(page, "21b-salt-opening-statement" if first else "23-salt-statement")
    check(f"{tag} is signed", press(page, ".rl-over button", "Sign and send"))
    settle(page, "Sent to", f"{tag} is sent")
    sheet_close(page, "Forms")


def diplomacy_open(page: Page) -> None:
    sheet_open(page, "World: Diplomacy")
    check(
        "the Diplomacy sheet carries agreements and conferences",
        all(w in said(over(page)) for w in ("agreements", "conferences")),
    )


def offer(page: Page) -> None:
    """From the offer builder: wording to Varda, read, signed."""
    check("Tab reaches the offer's wording", write(page, "textarea", "Your wording", SALT_WORDING))
    check(
        "the offer can be made to Varda",
        press(page, ".rl-dp-builder input[type=checkbox]", "Varda", key="Space"),
    )
    check("the offer's terms are read", press(page, ".rl-dp-builder button", "Read the terms"))
    over(page).get_by_role("button", name="Sign and send").wait_for(timeout=30_000)
    check("the terms the seat signs are shown", "the terms you sign" in said(over(page)))
    shoot(page, "24-salt-offer")
    check("the offer is signed", press(page, ".rl-over button", "Sign and send"))
    settle(page, "filed", "the offer is filed")


def vote_state(page: Page) -> tuple[str, str]:
    """The conference's vote line and the pressed vote button, as the sheet shows them."""
    return (
        page.locator(".rl-dp-vote").first.locator("xpath=preceding-sibling::p[1]").inner_text(),
        page.locator(".rl-dp-vote button[aria-pressed=true]").first.inner_text()
        if page.locator(".rl-dp-vote button[aria-pressed=true]").count()
        else "",
    )


def conference(page: Page) -> None:
    """Call a conference of the nation and Varda, then vote For, Against, Abstain, each
    replacing the last, and read the vote back from the sheet."""
    check(
        "Tab reaches the call's words",
        write(page, ".rl-dp-call textarea", "The text put to the vote", SALT_CALL),
    )
    check(
        "Varda can be invited",
        press(page, ".rl-dp-call input[type=checkbox]", "Varda", key="Space"),
    )
    check("the conference is called", press(page, ".rl-dp-call button", "Call the conference"))
    settle(page, "conference is called", "the call is sent")
    try:
        page.locator(".rl-dp-vote").first.wait_for(timeout=10_000)
    except PlaywrightTimeout:
        check("the called conference shows the seat's vote control", False)
        return
    shoot(page, "25-salt-conference")
    for word in ("For", "Against", "Abstain"):
        check(f"Tab reaches the {word} vote", press(page, ".rl-dp-vote button", word))
        try:  # the status line says "Sealing your vote…" while it goes: wait for the sheet itself
            page.locator(".rl-dp-vote button[aria-pressed=true]", has_text=word).first.wait_for(
                timeout=30_000
            )
            check(f"the {word} vote is filed", True)
        except PlaywrightTimeout:
            check(f"the {word} vote is filed", False, page.locator(".rl-status").first.inner_text())
        page.wait_for_timeout(600)
        line, pressed = vote_state(page)
        check(f"the sheet reads the {word} vote back", pressed == word, f"{line!r} / {pressed!r}")
    shoot(page, "26-salt-votes")


def publish(page: Page) -> None:
    """Publish the agreement the seat is party to and that only its parties know."""
    found = press(page, ".rl-dp-agreements button", "Publish the agreement of Ostrel and Kesh")
    check("Tab reaches Publish on an agreement the seat is party to", found)
    settle(page, "Publish the agreement", "the publication is sent")
    page.wait_for_timeout(800)
    shoot(page, "27-salt-publish")


def battle_day(page: Page, play: Second) -> None:
    """Run days until the levy's battle opens (a few wakes: each lasts a day)."""
    for n in range(8):
        if page.locator("[aria-label^='Battle at']").count():
            return
        salt_day(page, play, f"salt-day-{n}")
    check("the levy's battle opens within a few days", False)


def battle_sheet(page: Page, report: dict[str, object]) -> None:
    """The battle's sheet: its odds panel, then a decision filed. On a desktop it opens from
    the battle's mark on the map; on a phone from What needs you, the list a thumb works from,
    since at 390 px the mark sits under the pieces fighting there (the report says whether a
    tap on the mark could reach it)."""
    if PHONE:
        mark = page.locator("[aria-label^='Battle at']").first
        try:
            mark.tap(timeout=5_000, trial=True)
            report["salt_phone_battle_mark_tappable"] = True
        except PlaywrightTimeout:
            report["salt_phone_battle_mark_tappable"] = False
        needs_list_opened(page)
        check(
            "What needs you lists the battle",
            "the battle at" in said(page.locator(".rl-needs").first),
        )
        check("the battle's line opens in place", open_row(page, "the battle at"))
        check("the battle's Decide button can be tapped", press(page, ".rl-needs button", "Decide"))
    else:
        check("Tab reaches the battle's mark", press(page, "[aria-label]", "Battle at"))
    over(page).wait_for(timeout=10_000)
    page.wait_for_timeout(600)
    check("the battle sheet offers the seat's decisions", "your decision" in said(over(page)))
    check("Tab reaches the Odds button", press(page, ".rl-bt-odds button", "Odds"))
    box = over(page).locator(".rl-odds").first
    box.wait_for(timeout=15_000)
    check("the odds panel opens on the battle's area", "odds · the saltworks coast" in said(box))
    answered = box.locator(".rl-odds-outcome, .rl-odds-refused, .rl-odds-unknown").first
    try:
        answered.wait_for(timeout=30_000)
        check("the odds desk answers in the panel", True)
        report["salt_odds"] = answered.get_attribute("class")
    except PlaywrightTimeout:
        check("the odds desk answers in the panel", False, said(box)[:200])
    shoot(page, "28-salt-odds")
    check("the odds panel has a Close button", press(page, ".rl-odds button", "Close"))
    page.wait_for_timeout(400)
    check("the odds panel closes", over(page).locator(".rl-odds").count() == 0)
    check("Tab reaches the Hold decision", press(page, ".rl-bt-decisions button", "Hold"))
    try:  # the decision is filed through the server: wait for the sheet to say so
        over(page).filter(has_text=re.compile("its decision for this wake", re.I)).wait_for(
            timeout=30_000
        )
        check("the sheet says the decision is filed for this wake", True)
    except PlaywrightTimeout:
        check("the sheet says the decision is filed for this wake", False, said(over(page))[:300])
    shoot(page, "29-salt-decision")
    sheet_close(page, "battle")
    if PHONE:
        needs_list_closed(page)


def sheets_opened(page: Page) -> None:
    """The Home and Diplomacy sheets open, hold what they should and close."""
    sheet_open(page, "World: Home")
    check("the Home sheet shows the nation's groups", "groups" in said(over(page)))
    shoot(page, "30-salt-home")
    sheet_close(page, "At home")
    diplomacy_open(page)
    shoot(page, "31-salt-diplomacy")
    sheet_close(page, "Diplomacy")


def phone_room(page: Page, report: dict[str, object]) -> None:
    """At 390 by 844: the map with the season's strip at its foot is at least half the
    viewport's height, a sheet no more than half of it, and the page as wide as the viewport."""
    figure = page.locator("figure.rl-map-figure").first
    figure.scroll_into_view_if_needed()
    box = figure.bounding_box() or {"height": 0}
    strip = page.locator(".rl-mapfirst-map .rl-tl-head")
    foot = (strip.bounding_box() or {"height": 0})["height"] if strip.count() else 0
    report["salt_phone_map_height"] = [box["height"], foot]
    check(
        "the map and the season's strip at its foot are at least half the viewport's height",
        box["height"] + foot >= SIZE[1] / 2,
        f"{box} + strip {foot}",
    )
    sheet_open(page, "World: Diplomacy")
    sheet = over(page).bounding_box() or {"height": 1e9}
    report["salt_phone_sheet_height"] = sheet["height"]
    check("a sheet is a half sheet", sheet["height"] <= SIZE[1] / 2 + 1, str(sheet))
    sheet_close(page, "Diplomacy")
    width = page.evaluate("document.documentElement.scrollWidth")
    check("the page is as wide as the viewport", width == SIZE[0], str(width))


def salt_strait(playwright: object, browser: object, report: dict[str, object]) -> None:
    """The whole walk: rule 1 (needs, a move, the odds, a decision, Home and Diplomacy) and
    rule 2 (a statement, an offer, a conference and its votes, a publication), at this width."""
    ctx = browser.new_context(  # type: ignore[attr-defined]
        viewport={"width": SIZE[0], "height": SIZE[1]}, has_touch=PHONE, is_mobile=PHONE
    )
    page = ctx.new_page()
    watch(page)
    play = Second(playwright)
    try:
        salt_start(page, report, play)
        needs_opened(page, report)
        salt_move(page, report)
        statement(page, first=True)
        salt_day(page, play, "salt-first-day")
        quiet_wake(page)
        statement(page)
        diplomacy_open(page)
        offer(page)
        conference(page)
        publish(page)
        sheet_close(page, "Diplomacy")
        battle_day(page, play)
        battle_sheet(page, report)
        sheets_opened(page)
        nations_chart(page, report, "salt")
        if PHONE:
            phone_room(page, report)
    except Exception:
        page.screenshot(path=str(OUT / "zz-salt-failed.png"), full_page=True)
        (OUT / "zz-salt-failed.aria.txt").write_text(page.locator("body").aria_snapshot())
        raise
    finally:
        ctx.close()


if __name__ == "__main__":
    sys.exit(main())
