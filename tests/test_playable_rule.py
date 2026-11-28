"""Who can be played, worked out from the world by a rule (PBR).

With ``playable_rule`` on, a card is playable when it commands something outright and
can be played: an authority domain, a form of its own through one of its pipelines, an
inner circle with someone other than the person, three aims with conditions, and on the
military path a domain that names a force. It must also meet the world's floor: a rank at
or above the world's line, or a force it commands of a tier at or above the world's tier
line (2 and 3 when the world sets none). A world may hold a card back; that flag only
removes. The roster is the cards the rule admits, less those held back, and the hand flag
is not read. The toy world plays each clause; the shipped worlds are played with the rule
switched on in a copy: every card it admits is claimed and files a form in a first wake.
"""

import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, SeatId, derived_id
from revisionist.core.realism.card import ParamKind, SeatCard
from revisionist.core.roster import Floor, admits, claimable
from revisionist.core.state import Rule, State
from revisionist.core.world import CharacterDecl, PlayableFloorDecl, WorldFile
from revisionist.core.world_compile import WorldError, compile_world, object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, runner, session_zero, wake
from revisionist.engine.session_zero import StepRefusedError
from revisionist.engine.store import MemoryStore, load_state

ROOT = Path(__file__).resolve().parents[1]
TOY = ROOT / "tests" / "worlds" / "territory-toy.yaml"
CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
T0 = datetime(2030, 1, 1, tzinfo=UTC)
World = dict[str, Any]
SHIPPING = {"check": "quantity_at", "quantity": "norra_shipping", "op": "ge", "value": 1}


def _complete(person: str, aide: str, force: str) -> World:
    """A card that meets every clause of the rule, above the default floor by rank."""
    return {
        "authority": [
            {"name": "army", "effects": ["move_force"], "executor": aide, "forces": [force]}
        ],
        "inner_circle": [{"person": aide, "channel": "in_person"}],
        "pipelines": ["field_order"],
        "levers": [
            {
                "name": "move_piece",
                "pipeline": "field_order",
                "resolver": "movement",
                "params": [
                    {"name": "force", "kind": "enum", "choices": [force]},
                    {"name": "to", "kind": "enum", "choices": ["isle", "sudby", "norrhavn"]},
                ],
            }
        ],
        "aims": [f"{person} aim one.", f"{person} aim two.", f"{person} aim three."],
        "aim_rules": [
            {"aim": n, "rule": f"Aim {n} holds.", "condition": SHIPPING} for n in (1, 2, 3)
        ],
        "reach": {"rank": 3},
    }


def raw(*changes: Callable[[World], None], rule: bool = True) -> World:
    """The toy world with complete cards for Ilse and Tomas, each with an aide, and the
    rule on (unless ``rule`` is false); then ``changes``."""
    w: World = yaml.safe_load(TOY.read_text())
    w["rules"] = ["territories", "aims", "command"] + (["playable_rule"] if rule else [])
    w["entities"] += [
        {"key": "edda", "kind": "person", "name": "Edda Lind", "parent": "norra"},
        {"key": "jon", "kind": "person", "name": "Jon Sted", "parent": "sudland"},
    ]
    w["pipelines"] = [
        {
            "key": "field_order",
            "name": "A field order",
            "source": "toy",
            "steps": [{"person": "edda", "kind": "clerical", "days": 1}],
        }
    ]
    ilse, tomas = w["cards"]
    ilse.update(_complete("ilse", "edda", "norra_levy"))
    tomas.update(_complete("tomas", "jon", "sudland_levy"))
    for c in changes:
        c(w)
    return w


def world(*changes: Callable[[World], None], rule: bool = True) -> WorldFile:
    found = WorldFile.model_validate(raw(*changes, rule=rule))
    board = (TOY.parent / "toy.map.json").read_bytes()
    return found.model_copy(update={"map_data": board})


def compiled(*changes: Callable[[World], None], rule: bool = True) -> State:
    return replay(compile_world(world(*changes, rule=rule), CAMPAIGN, cmp.versions()))


def refused(*changes: Callable[[World], None], rule: bool = True) -> tuple[str, ...]:
    with pytest.raises(WorldError) as caught:
        compile_world(world(*changes, rule=rule), CAMPAIGN, cmp.versions())
    return caught.value.problems


def card(key: str, **fields: Any) -> Callable[[World], None]:
    def change(w: World) -> None:
        next(c for c in w["cards"] if c["person"] == key).update(fields)

    return change


def off_roster(key: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["roster"] = [ch for ch in w["roster"] if ch["entity"] != key]

    return change


def floor(**line: int) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["playable_floor"] = line

    return change


def tier(key: str, value: int) -> Callable[[World], None]:
    def change(w: World) -> None:
        next(f for f in w["features"] if f["key"] == key)["tier"] = value

    return change


def entity(key: str) -> EntityId:
    return EntityId(object_id(CAMPAIGN, "entity", key))


TOMAS_REFUSED = "character tomas: on the roster, but the playable rule does not admit it"


DEFAULT = Floor()


def reasons(state: State, key: str, line: Floor = DEFAULT) -> tuple[str, ...]:
    return admits(state, state.cards[entity(key)], line)


# --- Rule 1: the card commands something outright and can be played -----------------


def test_a_complete_card_is_admitted_and_the_roster_is_the_admitted_cards() -> None:
    state = compiled()
    assert reasons(state, "ilse") == () and reasons(state, "tomas") == ()
    assert set(state.roster) == {entity("ilse"), entity("tomas")}
    assert all(state.cards[p].playable for p in state.roster)
    assert all(c.reason is None for c in claimable(state))


def test_a_card_with_no_authority_domain_is_not_admitted() -> None:
    no_domain = card("tomas", authority=[], path="political")
    problems = refused(no_domain)
    assert f"{TOMAS_REFUSED}: it commands nothing outright" in problems
    assert reasons(compiled(no_domain, off_roster("tomas")), "tomas") == (
        "it commands nothing outright",
    )


def test_a_card_with_no_form_of_its_own_is_not_admitted() -> None:
    no_form = card("tomas", levers=[])
    assert f"{TOMAS_REFUSED}: it has no form of its own" in refused(no_form)
    assert reasons(compiled(no_form, off_roster("tomas")), "tomas") == (
        "it has no form of its own",
    )


def test_a_card_whose_inner_circle_is_only_the_person_is_not_admitted() -> None:
    alone = card("tomas", inner_circle=[{"person": "tomas", "channel": "in_person"}])
    assert f"{TOMAS_REFUSED}: it has no one in its inner circle" in refused(alone)
    state = compiled(alone, off_roster("tomas"))
    assert reasons(state, "tomas") == ("it has no one in its inner circle",)
    empty = compiled(card("tomas", inner_circle=[]), off_roster("tomas"))
    assert reasons(empty, "tomas") == ("it has no one in its inner circle",)


def test_a_card_without_three_aims_with_conditions_is_not_admitted() -> None:
    two_rules = card(
        "tomas",
        aim_rules=[{"aim": n, "rule": f"Aim {n}.", "condition": SHIPPING} for n in (1, 3)],
    )
    assert f"{TOMAS_REFUSED}: it has 2 of three aims with conditions" in refused(two_rules)
    two_aims = card(
        "tomas",
        aims=["One.", "Two."],
        aim_rules=[{"aim": n, "rule": f"Aim {n}.", "condition": SHIPPING} for n in (1, 2)],
    )
    state = compiled(two_aims, off_roster("tomas"))
    assert reasons(state, "tomas") == ("it has 2 of three aims with conditions",)


def test_a_commander_whose_domains_name_no_force_is_not_admitted() -> None:
    domain = {"name": "army", "effects": ["move_force"], "executor": "jon"}
    no_force = card("tomas", path="military", authority=[domain])
    state = compiled(no_force, off_roster("tomas"))
    assert reasons(state, "tomas") == ("it is a commander with no force named in a domain",)
    # A political card is not held to the force clause; its rank clears the floor.
    assert reasons(compiled(card("tomas", authority=[domain])), "tomas") == ()


def test_the_force_clause_is_read_only_with_command_on() -> None:
    domain = {"name": "army", "effects": ["move_force"], "executor": "jon"}

    def no_command(w: World) -> None:
        w["rules"].remove("command")

    state = compiled(no_command, card("tomas", path="military", authority=[domain]))
    assert reasons(state, "tomas") == ()


# --- Rule 2: the floor ------------------------------------------------------------------


def test_a_card_under_the_default_floor_by_rank_and_by_tier_is_not_admitted() -> None:
    low = card("tomas", reach={"rank": 1})
    problems = refused(low)
    assert f"{TOMAS_REFUSED}: it is under the floor: rank 1, no force of tier 3" in problems
    assert reasons(compiled(card("tomas", reach={"rank": 2})), "tomas") == ()


def test_a_force_at_the_tier_line_lifts_a_card_of_low_rank_over_the_floor() -> None:
    low = card("tomas", reach={"rank": 0})
    assert reasons(compiled(low, tier("sudland_levy", 3)), "tomas") == ()
    assert reasons(compiled(low, tier("sudland_levy", 2), off_roster("tomas")), "tomas") == (
        "it is under the floor: rank 0, no force of tier 3",
    )


def test_the_world_sets_its_own_floor() -> None:
    raised = floor(rank=4, tier=5)
    assert f"{TOMAS_REFUSED}: it is under the floor: rank 3, no force of tier 5" in refused(raised)
    lowered = floor(rank=0, tier=0)
    state = compiled(lowered, card("tomas", reach={"rank": 0}))
    assert set(state.roster) == {entity("ilse"), entity("tomas")}


def test_a_world_that_sets_only_one_line_keeps_the_default_for_the_other() -> None:
    assert PlayableFloorDecl.model_validate({"rank": 4}).tier == 3
    assert PlayableFloorDecl.model_validate({"tier": 1}).rank == 2


# --- Rule 3: the hold-back flag only removes ---------------------------------------------


def test_a_card_held_back_is_off_the_roster_and_not_claimable() -> None:
    state = compiled(card("tomas", held_back=True), off_roster("tomas"))
    assert set(state.roster) == {entity("ilse")}
    assert not state.cards[entity("tomas")].playable


def test_a_card_held_back_may_not_be_on_the_roster() -> None:
    problems = refused(card("tomas", held_back=True))
    assert "character tomas: held back, so it may not be on the roster" in problems


def test_holding_back_a_card_the_rule_refuses_does_not_admit_it() -> None:
    state = compiled(card("tomas", held_back=True, levers=[]), off_roster("tomas"))
    assert not state.cards[entity("tomas")].playable
    assert entity("tomas") not in state.roster


# --- Rule 4: the roster is the admitted cards; the hand flag is not read ------------------


def test_an_admitted_card_off_the_roster_and_not_held_back_is_refused() -> None:
    problems = refused(off_roster("tomas"))
    assert "card tomas: the playable rule admits it, so it is on the roster or held back" in (
        problems
    )


def test_the_hand_flag_is_not_read_with_the_rule_on() -> None:
    state = compiled(card("tomas", playable=False))
    assert state.cards[entity("tomas")].playable
    assert entity("tomas") in state.roster
    assert f"{TOMAS_REFUSED}: it has no form of its own" in refused(
        card("tomas", playable=True, levers=[])
    )


def test_with_the_rule_off_the_hand_flag_stands_and_the_new_keys_are_not_read() -> None:
    state = compiled(card("tomas", held_back=True, levers=[]), floor(rank=5), rule=False)
    assert state.cards[entity("tomas")].playable
    assert set(state.roster) == {entity("ilse"), entity("tomas")}
    problems = refused(card("tomas", playable=False), rule=False)
    assert "character tomas: a realism roster lists only playable cards" in problems


def test_the_rule_needs_the_aims_rule() -> None:
    def no_aims(w: World) -> None:
        w["rules"].remove("aims")

    assert "rules: playable_rule needs aims" in refused(no_aims)


# --- Rule 5: claimable takes the rule as its body; the asset rule is not applied ----------


def contested(w: World) -> None:
    """A contest over the border, which brings the older asset rule in: Tomas holds no
    office, force or network asset, so he fails it."""
    w["contests"] = [
        {"key": "border", "kind": "rivalry", "name": "The Border War", "prize": "The hills",
         "sides": ["norra", "sudland"], "countdown_days": 30},
    ]  # fmt: skip
    w["rules"].append("contests")


def test_the_asset_rule_is_not_applied_with_the_rule_on() -> None:
    assert any("tomas" in p or "Tomas" in p for p in refused(contested, rule=False))
    state = compiled(contested)
    by_name = {c.name: c for c in claimable(state)}
    assert by_name["Tomas Brand"].reason is None


def test_a_card_that_no_longer_meets_the_rule_is_not_claimable_and_says_why() -> None:
    state = compiled()
    tomas = entity("tomas")
    stripped = state.cards[tomas].model_copy(update={"levers": ()})
    state = state.model_copy(update={"cards": {**state.cards, tomas: stripped}})
    by_name = {c.name: c for c in claimable(state)}
    assert (
        by_name["Tomas Brand"].reason == "Tomas Brand cannot be played: it has no form of its own."
    )
    assert by_name["Ilse Varg"].reason is None


def _store(*changes: Callable[[World], None]) -> MemoryStore:
    store = MemoryStore()
    store.append_all(compile_world(world(*changes), CAMPAIGN, cmp.versions()))
    return store


def test_the_claim_takes_who_the_rule_admits_where_the_asset_rule_would_refuse() -> None:
    store = _store(contested)
    session_zero.claim(store, CAMPAIGN, SeatId("seat-one"), "Tomas Brand")
    assert load_state(store, CAMPAIGN).roster[entity("tomas")].claimed_by == SeatId("seat-one")


def test_the_claim_refuses_a_card_that_no_longer_meets_the_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store()
    tomas = entity("tomas")
    opened = session_zero._open

    def stripped(store: MemoryStore, campaign_id: CampaignId) -> State:
        state = opened(store, campaign_id)
        bare = state.cards[tomas].model_copy(update={"authority": ()})
        return state.model_copy(update={"cards": {**state.cards, tomas: bare}})

    monkeypatch.setattr(session_zero, "_open", stripped)
    with pytest.raises(StepRefusedError) as caught:
        session_zero.claim(store, CAMPAIGN, SeatId("seat-one"), "Tomas Brand")
    assert str(caught.value) == "Tomas Brand cannot be played: it commands nothing outright."


# --- Rule 6: the report ------------------------------------------------------------------


def _report(path: Path) -> str:
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "playable_report.py"), str(path)],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    return done.stdout


def test_the_report_names_each_card_admitted_or_not_and_why_against_the_hand_flag(
    tmp_path: Path,
) -> None:
    def edda_carded(w: World) -> None:
        edda = {"person": "edda", "office": "Steward of Norra", "horizon_days": 14}
        w["cards"].append({**edda, **_complete("edda", "ilse", "norra_kites")})

    w = raw(card("tomas", levers=[]), edda_carded, rule=False)
    path = tmp_path / "world.yaml"
    path.write_text(yaml.safe_dump(w, sort_keys=False))
    (tmp_path / "toy.map.json").write_bytes((TOY.parent / "toy.map.json").read_bytes())
    out = _report(path)
    lines = out.splitlines()
    assert "Edda Lind (edda): admitted; not flagged by hand" in lines
    assert "Ilse Varg (ilse): admitted; flagged by hand" in lines
    assert "Tomas Brand (tomas): not admitted: it has no form of its own; flagged by hand" in lines
    assert "Floor: rank 2, force tier 3 (set by the world)" in lines
    assert "Admitted and flagged by hand: Ilse Varg" in lines
    assert "Admitted and not flagged by hand: Edda Lind" in lines
    assert "Flagged by hand and not admitted: Tomas Brand" in lines


# --- Accept: each shipped world with the rule on in a copy --------------------------------

SHIPPED_FLOORS: dict[str, PlayableFloorDecl | None] = {
    "autumn-1941": None,
    "civil-war-1862": None,
    # Salt Strait's cards carry no rank and its forces are of tier 2 at most, so the
    # default floor admits nobody there; the copy takes the lines that let its forces count.
    "salt-strait-realism": PlayableFloorDecl(rank=2, tier=2),
}


def ruled_copy(name: str) -> tuple[WorldFile, list[str]]:
    """``name`` with the rule on and the roster made the cards the rule admits, each listed
    as the world lists it where it does; and the keys of those cards."""
    shipped = cmp.load_world(cmp.world_path(name))
    line = SHIPPED_FLOORS[name]
    state = replay(compile_world(shipped, CAMPAIGN, cmp.versions()))
    keys = {v: k for k, v in _ids(shipped).items()}
    held = {c.person for c in shipped.cards if c.held_back}
    floor_ = Floor() if line is None else Floor(rank=line.rank, tier=line.tier)
    admitted = [
        keys[p]
        for p, c in state.cards.items()
        if not admits(state, c, floor_) and keys[p] not in held
    ]
    listed = {ch.entity: ch for ch in shipped.roster}
    roster = tuple(
        listed.get(k) or CharacterDecl(entity=k, pitch="p", reach="r", composite=False)
        for k in sorted(admitted)
    )
    copy = shipped.model_copy(
        update={
            "rules": tuple(dict.fromkeys((*shipped.rules, Rule.PLAYABLE_RULE))),
            "roster": roster,
            "playable_floor": line,
            "roster_limit": (min(2, len(roster)), 40),
        }
    )
    return copy, sorted(admitted)


def _ids(w: WorldFile) -> dict[str, str]:
    from revisionist.core.world_compile import resolve_keys

    return resolve_keys(w, CAMPAIGN)


def _params(state: State, seat: SeatId, lever: Any) -> list[dict[str, str]]:
    """Ways to fill the form, every parameter given: the n-th choice of each list."""
    tries: list[dict[str, str]] = []
    widest = max((len(p.choices) for p in lever.params), default=1)
    for pick in range(widest):
        given: dict[str, str] = {}
        for p in lever.params:
            if p.kind is ParamKind.ENUM:
                given[p.name] = p.choices[min(pick, len(p.choices) - 1)]
            elif p.kind is ParamKind.INT:
                given[p.name] = str(p.lo)
            elif p.kind is ParamKind.TEXT:
                given[p.name] = "As ordered."
            else:
                person = state.seats[seat].embodies
                given[p.name] = str(state.cards[person].inner_circle[0].person)
        tries.append(given)
    return tries


def _first_wake_with_a_form(events: list[ev.Event], key: str, tmp: Path) -> str:
    """Claim ``key``, open play, file the first of its forms that files, close the first
    wake. Returns the lever filed."""
    store = MemoryStore()
    store.append_all(events)
    person = EntityId(object_id(CAMPAIGN, "entity", key))
    seat = SeatId(derived_id(CAMPAIGN, "seat", person))
    name = load_state(store, CAMPAIGN).entities[person].name
    session_zero.claim(store, CAMPAIGN, seat, name)
    realism_tick.open_play(store, CAMPAIGN)
    tick = dict(
        offline=True,
        transport_factory=cmp.live_transport,
        briefings=tmp / "briefings",
        warn=lambda _m: None,
    )
    runner.play_tick(store, CAMPAIGN, now=T0, **tick)  # type: ignore[arg-type]
    state = load_state(store, CAMPAIGN)
    assert state.wake is not None and not state.wake.closed
    filed = ""
    order = None
    for lever in state.cards[person].levers:
        for given in _params(state, seat, lever):
            try:
                order = realism_tick.file_order(store, CAMPAIGN, seat, lever.name, given)
            except ValueError:
                continue
            filed = lever.name
            break
        if filed:
            break
    assert filed and order is not None, f"{key}: no form of the card files"
    number = state.wake.number
    wake.commit(store, CAMPAIGN, seat, state.wake.deadline)
    runner.play_tick(store, CAMPAIGN, now=state.wake.deadline, **tick)  # type: ignore[arg-type]
    after = load_state(store, CAMPAIGN)
    # Filed: drafted to land, or held by a lock with the form on the hold.
    logged = [e.payload.model_dump_json() for e in store.read(CAMPAIGN)]
    assert any(order.order_id in p for p in logged)
    assert after.wake is not None and after.wake.number > number
    return filed


@pytest.mark.parametrize("name", sorted(SHIPPED_FLOORS))
def test_every_card_the_rule_admits_is_claimed_and_files_a_form_in_a_first_wake(
    name: str, tmp_path: Path
) -> None:
    copy, admitted = ruled_copy(name)
    events = compile_world(copy, CAMPAIGN, cmp.versions())
    state = replay(events)
    assert admitted, f"{name}: the rule admits nobody"
    assert {k for k in admitted} == {
        k for k, v in _ids(copy).items() if EntityId(v) in state.roster
    }
    for key in admitted:
        assert _first_wake_with_a_form(events, key, tmp_path / key)


def test_the_floor_and_the_hold_back_reach_no_card_shape() -> None:
    """Both are world keys only: the card keeps its one playable mark."""
    assert "held_back" not in SeatCard.model_fields
    assert "playable_floor" not in State.model_fields
