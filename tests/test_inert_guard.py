"""No orderable effect lands nothing in silence: each changes the world or is named inert."""

from datetime import date
from typing import get_args

from revisionist.core.ids import FactId, derived_id
from revisionist.core.realism import effect as rx
from revisionist.core.realism.apply import _land
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.realism.quantity import RESOLVER_KEYS
from revisionist.core.realism.resolvers import ON_DAY, ON_ORDER
from tests.test_engine_v2_contract import CAMPAIGN, Slice

ON = date(1941, 9, 11)

INERT: tuple[str, ...] = ("measure outside a process", "disclosure that conceals")
"""Effects that change nothing by design; a new inert effect must be added here on purpose."""


def effects(sl: Slice) -> dict[str, rx.Effect]:
    """One instance of every effect kind, aimed at the slice."""
    fact = FactId(derived_id(CAMPAIGN, "inert-guard-fact"))
    return {
        "move_force": rx.MoveForce(force=sl.feature("us_atlantic_fleet"), to=sl.entity("argentia")),
        "engagement": rx.SetEngagement(
            force=sl.feature("us_atlantic_fleet"),
            zone="western Atlantic",
            rule=rx.Engagement.DEFEND,
        ),
        "allocate": rx.Allocate(recipient=sl.entity("uk"), what="munitions", amount=5, unit="tons"),
        "appointment": rx.Appointment(person=sl.entity("wallace"), office="envoy"),
        "statement": rx.MakeStatement(theme="freedom_of_the_seas"),
        "investigate": rx.Investigate(target=sl.entity("churchill"), question="his plans"),
        "deal": rx.Deal(counterparty=sl.entity("churchill"), offer=("ships",)),
        "disposition": rx.ShiftDisposition(
            of=sl.entity("churchill"), toward=sl.entity("roosevelt"), change=1
        ),
        "measure outside a process": rx.ProposeMeasure(
            title="A bill",
            clauses=(rx.Clause(kind=rx.ClauseKind.LIMIT, subject="a limit"),),
        ),
        "disclosure that conceals": rx.Disclosure(fact=fact, reveal=False),
    }


def test_every_effect_kind_changes_the_world_or_is_named_inert() -> None:
    """Kinds that land no event and reveal no fact are exactly the ones in INERT."""
    sl = Slice()
    silent = []
    for name, effect in effects(sl).items():
        events, revealed = _land(PassWorld(sl.state), effect, sl.fdr, sl.entity("roosevelt"), ON)
        if not events and not revealed:
            silent.append(name)
    assert sorted(silent) == sorted(INERT)


def test_the_guard_names_every_effect_kind() -> None:
    """A new member of the Effect union must be added to ``effects`` or this fails."""
    union = get_args(get_args(rx.Effect)[0])
    kinds = {t.model_fields["kind"].default for t in union}
    named = {e.kind for e in effects(Slice()).values()}
    assert named == kinds


def test_every_resolver_key_has_an_order_and_a_day_rule() -> None:
    """A resolver key with no function on either path would accept orders and do nothing."""
    assert set(ON_ORDER) == set(RESOLVER_KEYS) == set(ON_DAY)
