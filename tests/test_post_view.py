"""A commander held to his post: two worlds differing only in a fact of his own nation
that his post would not see give him the same view; his nation's chancellor tells them
apart. With ``post_view`` off the commander tells them apart too."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from revisionist.core.ids import QuantityId
from revisionist.core.project import project
from revisionist.core.realism.agreement import Agreement, Agreements
from revisionist.core.realism.detect import Confidence, Picture, Report, Source
from revisionist.core.realism.quantity import Quantity
from revisionist.core.state import State
from revisionist.core.visibility import Scope, Visibility
from tests import test_realism_locks as toy_locks

Twist = Callable[[State, int], State]


def _game(tmp_path: Path, *rules: str) -> State:
    def on(w: dict[str, Any]) -> None:
        w["rules"] = sorted({*w["rules"], "groups", *rules})

    tmp_path.mkdir(parents=True, exist_ok=True)
    return toy_locks.game(tmp_path, on)


def _support(state: State, n: int) -> State:
    held = state.groups.model_copy(update={"support": {toy_locks.NORRA: {"smiths": 40 + n}}})
    return state.model_copy(update={"groups": held})


def _treasury(state: State, n: int) -> State:
    day = state.in_world_date
    assert day is not None
    sealed = Scope(
        visibility=Visibility.RESTRICTED,
        known_by=frozenset({toy_locks.seat(toy_locks.ILSE), toy_locks.seat(toy_locks.KARA)}),
    )
    figure = Quantity(
        quantity_id=QuantityId("treasury"),
        owner=toy_locks.NORRA,
        name="Norra's treasury",
        value=100 + n,
        unit="crowns",
        as_of=day,
        scope=sealed,
    )
    return state.model_copy(update={"quantities": {**state.quantities, figure.quantity_id: figure}})


def _sealed_pact(state: State, n: int) -> State:
    day = state.in_world_date
    assert day is not None
    parties = (toy_locks.NORRA, toy_locks.key_id("sudland"))
    made = {
        f"pact{i}": Agreement(agreement_id=f"pact{i}", version="1", parties=parties, made=day)
        for i in range(n)
    }
    return state.model_copy(update={"agreements": Agreements(made=made)})


def _far_report(state: State, n: int) -> State:
    day = state.in_world_date
    assert day is not None
    far = Report(
        key="far",
        area=toy_locks.key_id("sudby"),
        seen=day,
        source=Source.CONTACT,
        rank=n,
        confidence=Confidence.A,
        arrives=day,
    )
    return state.model_copy(update={"reports": {toy_locks.NORRA: Picture(delivered={"far": far})}})


TWISTS: dict[str, Twist] = {
    "group support": _support,
    "sealed figure": _treasury,
    "sealed agreement": _sealed_pact,
    "report out of reach": _far_report,
}


@pytest.mark.parametrize("name", sorted(TWISTS))
def test_twin_worlds_differing_in_his_nations_books_look_alike_from_his_post(
    tmp_path: Path, name: str
) -> None:
    base = _game(tmp_path / "on", "post_view")
    plain = _game(tmp_path / "off")
    twist = TWISTS[name]
    kara, ilse = toy_locks.seat(toy_locks.KARA), toy_locks.seat(toy_locks.ILSE)
    a, b = twist(base, 0), twist(base, 1)
    assert project(a, kara) == project(b, kara), f"{name}: the post sees it"
    assert project(a, ilse) != project(b, ilse), f"{name}: the chancellor does not see it"
    assert project(twist(plain, 0), kara) != project(twist(plain, 1), kara), (
        f"{name}: with the rule off the general still sees it"
    )
