"""Browser smoke run of the realism room against a live `revisionist web serve`.

Signs up a fresh account and either joins a realism game with an invite code or, with
the code `new`, starts the ready-made game as its host and plays Franklin D. Roosevelt.
With the code `v2` it starts the engine-v2 slice from the timeline instead and checks
the timeline, who held power and the play style first.
Checks the room: the header names the player and its two names open the setting and the
character dossiers; the game menu; the wake header with "Done for today" and the host's
"Run the day now"; the in-tray's grouped rows, an opened paper, flagging and the filters;
needs-your-answer, ideas, the standard forms, a directive read by the aide (signed when it
reads as an order, revised when it cannot be sent) and the orders column; the messenger
with the aide's thread, a question to the aide, a consult and the contacts tab; a day run
with the busy line and the overlay, then the "What happened" sheet; a narrow room; that no
empty-state filler shows; and (as host) ending the game and the reveal. Screenshots at
1440x900. Fails on any console error, page error, failed request or a request to
another origin, or any named check that does not hold; runs axe-core when it is
mounted at /axe/axe.min.js.

    python web/test/e2e/realism_smoke.py BASE_URL INVITE_CODE|new|v2 OUT_DIR

For a run with no model calls, serve with web/test/e2e/serve_canned.py.
"""

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Locator, Page, sync_playwright

BASE, CODE, OUT = sys.argv[1].rstrip("/"), sys.argv[2], Path(sys.argv[3])
SIZE = (1440, 900)
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
    number = wake_number(page)
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
    after = wake_number(page)
    check(f"{name}: the wake moves on", after == number + 1, f"{number} -> {after}")
    check(f"{name}: the overlay is gone", page.locator(".rl-ovl").count() == 0)
    sheet = page.locator("dialog.rl-hap[open]")
    sheet.wait_for(timeout=5_000)
    check(f"{name}: What happened opens", "what happened" in sheet.inner_text().lower())
    shoot(page, f"{name}-happened")
    axe(page, f"{name} what happened")
    sheet.get_by_role("button", name="To the desk").click()
    page.wait_for_timeout(300)
    check(f"{name}: What happened closes", page.locator("dialog.rl-hap[open]").count() == 0)


def wake_number(page: Page) -> int:
    text = page.locator(".rl-wake").first.inner_text()
    return int(text.split("Wake ", 1)[1].split()[0])


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
        page = browser.new_page(viewport={"width": SIZE[0], "height": SIZE[1]}, bypass_csp=False)
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
            play_from_dossier(page, report, "Franklin D. Roosevelt")
            page.get_by_role("button", name="Begin the game").wait_for(timeout=60_000)
            begin_with_crawl(page, report)
        else:
            page.get_by_label("Invite code").fill(CODE)
            page.get_by_role("button", name="Join").click()

        page.locator("main.rl-room").wait_for(timeout=60_000)
        page.wait_for_timeout(300)
        through_intro(page, report)
        shoot(page, "00-opening")
        try:
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
        if host:
            end_game(page, report, v2)
        browser.close()
    report["checks"] = checks
    report["problems"] = problems
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 1 if problems else 0


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
    page.get_by_role("heading", name=f"You are {name}").wait_for(timeout=60_000)


def begin_with_crawl(page: Page, report: dict) -> None:
    """Begin plays the crawl while the server works; Continue once it says it is ready."""
    page.get_by_role("button", name="Begin the game").click()
    crawl = page.locator("dialog.rl-intro[open]")
    crawl.wait_for(timeout=10_000)
    paragraphs = crawl.locator(".rl-intro-crawl p").count()
    report["crawl_paragraphs"] = paragraphs
    check("Begin plays the opening crawl", paragraphs > 0, str(paragraphs))
    crawl.locator(".rl-intro-status", has_text="Ready").wait_for(timeout=120_000)
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
    check("the header shows the wake", "Wake " in wake.inner_text(), wake.inner_text())
    check("the header says when the wake closes", "Closes " in wake.inner_text())
    check("the header counts players done", "done" in wake.inner_text())
    check(
        "the header offers Done for today",
        page.get_by_role("button", name="Done for today").count() >= 1,
    )
    check(
        "only the host can run the day now",
        page.get_by_role("button", name=RUN_NOW).count() == (1 if host else 0),
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
    shoot(page, "07-orders")
    axe(page, "orders")


def messenger(page: Page, report: dict[str, object]) -> None:
    page.get_by_role("button", name="Messages").click()
    dock = page.locator(".rl-msgr")
    dock.get_by_role("tab", name="Chats").wait_for()
    dock.get_by_role("button", name="Your aide").click()
    page.locator(".rl-msgr .rl-brief").wait_for(timeout=WAKE_MS)
    report["aide_brief"] = page.locator(".rl-msgr .rl-brief").inner_text()[:600]
    check("the aide's thread holds its brief", len(str(report["aide_brief"])) > 20)
    thread = page.locator(".rl-msgr ol.rl-thread > li")
    lines = thread.count()
    page.locator(".rl-msgr").get_by_label("Message", exact=True).fill("How do I move a fleet?")
    page.locator(".rl-msgr").get_by_role("button", name="Send").click()
    page.locator(".rl-msgr ol.rl-thread > li").nth(lines + 1).wait_for(timeout=WAKE_MS)
    page.wait_for_timeout(300)
    check(
        "the aide answers in its thread",
        thread.count() >= lines + 2 and "Your aide" in thread.last.inner_text(),
        f"{lines} -> {thread.count()}",
    )
    check("focus stays in the messenger after the aide answers", in_messenger(page))
    shoot(page, "08-aide-thread")
    axe(page, "aide thread")
    page.locator(".rl-msgr").get_by_role("button", name="Back").click()
    person = page.locator(".rl-msgr .rl-msgr-item").nth(1)
    who = person.locator(".rl-msgr-item-text").inner_text().split("\n")[0]
    person.click()
    page.locator(".rl-msgr").get_by_label("Message", exact=True).fill(
        "Should we wait for the Senate before we move?"
    )
    page.locator(".rl-msgr").get_by_role("button", name="Send").click()
    page.locator(".rl-msgr .rl-answer").first.wait_for(timeout=WAKE_MS)
    report["consult"] = page.locator(".rl-msgr .rl-answer").first.inner_text()
    check(
        f"a consult with {who} shows the answer", page.locator(".rl-msgr .rl-answer").count() >= 1
    )
    check("focus stays in the messenger after a consult", in_messenger(page))
    shoot(page, "09-consult")
    page.locator(".rl-msgr").get_by_role("button", name="Back").click()
    page.locator(".rl-msgr").get_by_role("tab", name="Contacts").click()
    contacts = page.locator(".rl-msgr")
    report["contacts"] = contacts.inner_text()[:1200]
    check(
        "contacts are grouped",
        any(
            g in str(report["contacts"]).lower() for g in ("inner circle", "government", "foreign")
        ),
    )
    shoot(page, "10-contacts")
    axe(page, "contacts")
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    check("Esc closes the messenger", page.locator(".rl-msgr-panel").count() == 0)


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
    if host:
        advance(page, "13-run-now", RUN_NOW)


def narrow(page: Page) -> None:
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


if __name__ == "__main__":
    sys.exit(main())
