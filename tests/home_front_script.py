"""The home-front game: the scripted proof (HFG), played through the engine.

The locked-orders script (``tests/locked_orders_script.py``) plays a season with the
leader and the commander both seated. This script plays the same season and adds the
home front: the leader files the bill, then offers one bloc of his own nation a price
for its votes (``realism_tick.make_offer``); once the act is law he files the order
that keeps the promise, or files nothing and lets it come due unmet. Every act goes
through an engine entry point, as a seat would make it from the web, each drawn from its
own id stream so two runs log the same ids.

Two casts:

- 1941: Roosevelt and Admiral King. Roosevelt sends the Neutrality revision and offers
  the House Democrats ``britain_supplied`` (Britain allotted Lend-Lease goods within
  thirty days of the act); he keeps it with a Lend-Lease finding for Britain.
- Salt Strait: Oren Vale and Brask. Oren sends the Salt Convoy Act and offers a bloc of
  the Salt Assembly one of its prices.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import OrderId
from revisionist.core.realism import effect as rx
from revisionist.core.realism import groups
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.pipeline import OrderStatus
from revisionist.core.realism.resolvers import qid
from revisionist.core.state import State
from revisionist.core.world import WorldFile
from revisionist.engine import realism_tick
from tests import locked_orders_script as lo
from tests.locked_orders_script import Cast, Form, Game, Script


@dataclass(frozen=True)
class Home:
    """What the home-front script needs from a world beyond the locked-orders cast."""

    cast: Cast
    nation: str
    measure: str
    """The bill the leader sends (``cast.bill``'s measure)."""
    bloc: str
    """The bloc the leader prices the bill with."""
    price: str
    """The price offered."""
    keep: Form | Ask
    """The leader's order that meets the price once the act is law: a form, or a written
    ask with its typed effect (``realism_tick.commit_order``), as the seat commits it."""


NINETEEN_41 = Home(
    cast=lo.NINETEEN_41,
    nation="usa",
    measure="neutrality_revision",
    bloc="house_democrats",
    price="britain_supplied",
    keep=(
        "lend_lease_finding",
        {"recipient": "uk", "share_pct": "40", "route": "hx_route"},
    ),
)


SALT_STRAIT = Home(
    cast=lo.SALT_STRAIT,
    nation="varda",
    measure="salt_convoy_act",
    bloc="free_traders",
    price="open_strait_word",
    keep=Ask(
        ask="Speak for the open strait",
        effect=rx.MakeStatement(theme="the_open_strait"),
    ),
)


# --- the war at sea (1941 copies only) ------------------------------------------------
#
# In the world as written the United States is at peace and sails no route of its own,
# so nothing it loses can move its groups. These changes, made to a copy, put it at war
# with Germany from the day before the season, put the HX convoys under its escort (its
# route, as from 16 September 1941), and set the U-boat arm at full strength off
# Argentia, on the convoys' path and out of the commander's way.

World = dict[str, Any]


def at_war(w: World) -> None:
    w["wars"].append({"a": "germany", "b": "usa", "since": "1941-08-31", "gap": True})


def escorted(w: World) -> None:
    for f in w["features"]:
        if f.get("key") == "hx_route":
            f["side"] = "usa"
        if f.get("key") == "uboat_arm":
            f["places"], f["tier"] = ["argentia"], 5


def felt_in_the_chambers(amount: int) -> Callable[[World], None]:
    """Each bloc of the United States' chambers is moved by losses at sea and in battle:
    ``amount`` for a month's losses at sea, a tenth of it for battle losses."""

    def change(w: World) -> None:
        for d in w["groups"]:
            if d["nation"] != "usa":
                continue
            for g in d["groups"]:
                if g.get("chamber"):
                    g.setdefault("moved_by", {}).update(
                        losses_at_sea=-amount, battle_losses=-max(1, amount // 10)
                    )

    return change


WAR: tuple[Callable[[World], None], ...] = (at_war, escorted)
HEAVY = 40
"""Support a chamber bloc loses for a month's losses at sea in the heavy-losses copy."""


@dataclass(frozen=True)
class HomeScript(Script):
    """The locked-orders script with the home front added."""

    offer: bool = True
    """The leader offers the bloc the price on the day he sends the bill."""
    keep: bool = True
    """Once the act is law the leader files the order that meets the price."""


FULL = HomeScript()


@dataclass
class Kept:
    """What the home-front script did, for the tests to read."""

    offer_id: str | None = None
    refused: str | None = None
    """The engine's words if it refused the offer."""
    keep: OrderId | None = None
    kept_filed: date | None = None


class HomeGame(Game):
    """One home-front game: a locked-orders game whose leader also prices his bill."""

    def __init__(
        self,
        home: Home,
        tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
        world: WorldFile | None = None,
    ) -> None:
        super().__init__(home.cast, tmp, monkeypatch, world)
        self.home = home
        self.kept = Kept()

    def play(self, script: Script = FULL) -> "HomeGame":
        super().play(script)
        return self

    @property
    def hs(self) -> HomeScript:
        s = self.script
        return s if isinstance(s, HomeScript) else HomeScript()

    def _steps(self, n: int) -> None:
        super()._steps(n)
        home, k, p = self.home, self.kept, self.played
        if n == 0 and self.hs.offer and p.bill is not None:
            try:
                with self.ids.drawn_by("leader:offer"):
                    made = realism_tick.make_offer(
                        self.store, self.cast.campaign, self.leader,
                        home.bloc, home.measure, home.price,
                    )  # fmt: skip
                k.offer_id = made.offer_id
            except ValueError as exc:
                k.refused = str(exc)
        state = self.state
        if self.hs.keep and k.keep is None and self.passed(state):
            k.keep = self._keep(home.keep)
            k.kept_filed = state.in_world_date
        keep = state.orders.get(k.keep) if k.keep is not None else None
        if keep is not None and keep.status is OrderStatus.MOVING:
            person = state.pipelines[keep.pipeline].steps[keep.step].person
            if person == self.cast.entity(self.cast.leader) and keep.held_choice is None:
                try:
                    self.step(self.leader, keep.order_id, f"leader:keep:{keep.step}")
                except ValueError:
                    pass

    def _keep(self, keep: Form | Ask) -> OrderId:
        if isinstance(keep, Ask):
            with self.ids.drawn_by("leader:keep"):
                return realism_tick.commit_order(
                    self.store, self.cast.campaign, self.leader, [keep]
                ).order_id
        return self.file(self.leader, keep, "leader:keep").order_id

    def passed(self, state: State) -> bool:
        q = state.quantities.get(qid(state, self.cast.passed))
        return q is not None and q.value == 1

    def support(self, bloc: str | None = None) -> int | None:
        return groups.support(
            self.state, self.cast.entity(self.home.nation), bloc or self.home.bloc
        )

    def moved(self, cause: Any = None) -> list[ev.GroupMoved]:
        nation = self.cast.entity(self.home.nation)
        return [
            m
            for m in self.logged(ev.GroupMoved)
            if m.polity == nation and (cause is None or m.cause is cause)
        ]


def home_game(
    home: Home,
    tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    script: HomeScript = FULL,
    changes: tuple[Callable[[dict[str, Any]], None], ...] = (),
) -> HomeGame:
    world = home.cast.world(tmp / "world", changes) if changes else None
    return HomeGame(home, tmp, monkeypatch, world).play(script)


__all__ = [
    "FULL",
    "HEAVY",
    "NINETEEN_41",
    "SALT_STRAIT",
    "WAR",
    "Home",
    "HomeGame",
    "HomeScript",
    "Kept",
    "at_war",
    "escorted",
    "felt_in_the_chambers",
    "home_game",
    "replace",
]
