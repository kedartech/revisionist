"""1941 offices: what each rests on, how its holder is removed, the ladders and the bands (OFD).

Every line is written from Ava's sourcing note
(``kedartech/revisionist/reports/2026-11-21-revisionist-third-run-sourcing.md`` and its four
1941 sheets) or left out as a gap: a key the note does not give is not written, and the
world file marks it ``# gap: true`` beside the asset, as the groups rows do. No line is
guessed: the posts, office and defiance rules run on what is written and read the rest as
absent.

With ``posts``, ``office`` and ``defiance`` taken out of a copy's rules, the scripted run's
digest (``run_digest`` of ``tests/test_world_locks_1941.py``) equals the third run's
baseline, so the office data moves nothing while the switches are off.
"""

from datetime import date
from typing import Any

import pytest

from revisionist.core.state import Rule
from revisionist.core.world import RemovalDecl, WorldFile
from revisionist.core.world_compile import WorldError
from tests import test_world_locks_1941 as locks_1941
from tests.test_rule_names import SHIPPED_1941

THREE = (Rule.POSTS, Rule.OFFICE, Rule.DEFIANCE)

HEADS: dict[str, tuple[str, tuple[str, ...], RemovalDecl | None]] = {
    # US (U1, U2): the Electoral College is not in the world, so rests_on is a gap; the
    # term ends at noon on 20 January 1945 (Twentieth Amendment; third term begun 20 Jan
    # 1941). Impeachment needs two chambers and two thirds, which no removal way carries.
    "us_presidency": ("roosevelt", (), RemovalDecl(by="term", ends=date(1945, 1, 20))),
    # UK (K1, K2): the confidence of the Commons; resignation on losing it.
    "uk_premiership": ("churchill", ("commons",), RemovalDecl(by="vote", chamber="commons")),
    # USSR (S1, S2): the party; formal removal lies with the Supreme Soviet, which is not in
    # the world, and no rule is found for the party post: a gap.
    "soviet_chairmanship": ("stalin", ("party",), None),
    # Germany (G1, G2): the party and the armed forces; removal is a gap.
    "reich_chancellorship": ("hitler", ("party", "wehrmacht_command"), None),
    # Japan (J1, J2): the cooperation of the Army and the Navy; the Emperor appoints and
    # dismisses (Meiji Constitution, arts. 10, 55).
    "japan_premiership": ("konoe", ("army", "navy"), RemovalDecl(by="person", person="hirohito")),
    # Italy (I1, I2): the King and the Fascist Party; the King revokes (Statuto art. 65; law
    # of 24 December 1925, art. 2).
    "italian_premiership": (
        "mussolini",
        ("crown", "fascist_party"),
        RemovalDecl(by="person", person="victor_emmanuel"),
    ),
    # China (C1, C2): no removal procedure is found, and Chiang's base is his four offices,
    # not a group: both are gaps.
    "chinese_chairmanship": ("chiang", (), None),
    # Finland (F1, F2): the electors and the cabinet are not in the world, and the note
    # gives no day the term ends: both are gaps.
    "finnish_presidency": ("ryti", (), None),
}
"""Each nation's head's post: its holder, what it rests on, and how its holder is removed."""

MILITARY: dict[str, tuple[str, tuple[str, ...]]] = {
    "atlantic_fleet_command": ("king", ("us_presidency",)),  # U3: the President
    "home_fleet_command": ("tovey", ("uk_premiership",)),  # K3: the Prime Minister
    "uboat_command": ("doenitz", ("reich_chancellorship",)),  # G3: Hitler, personally
    "combined_fleet_command": ("yamamoto", ()),  # J3: the Emperor, who holds no post here
    "battle_fleet_command": ("iachino", ("italian_premiership",)),  # I3: Mussolini
    "western_front_command": ("timoshenko", ("soviet_chairmanship",)),  # S3, S8: Stalin
    "ninth_war_area_command": ("xue_yue", ()),  # C3: a gap
    "finnish_supreme_command": ("mannerheim", ()),  # F3: a gap
}
"""Each military post: its holder and the posts whose holders may move him. No ladder and
no act without leave is sourced for any of them, so neither is written."""


def _world() -> WorldFile:
    return locks_1941._world()


def _asset(world: WorldFile, key: str) -> Any:
    return next(a for a in world.assets if a.key == key)


def _without(world: WorldFile, rules: tuple[Rule, ...]) -> WorldFile:
    off = {r.value for r in rules}
    return world.model_copy(update={"rules": tuple(r for r in world.rules if r not in off)})


# --- rule 5: the world's rules gain posts, office and defiance; it compiles ----------------


def test_the_world_switches_on_posts_office_and_defiance_and_compiles() -> None:
    world = _world()
    assert {r.value for r in THREE} <= set(world.rules)
    locks_1941._compile(world)


# --- rule 1: each head's post, from Ava's note --------------------------------------------


@pytest.mark.parametrize("key", sorted(HEADS))
def test_each_heads_post_rests_on_and_is_removed_as_the_note_says(key: str) -> None:
    world = _world()
    holder, rests_on, removed_by = HEADS[key]
    a = _asset(world, key)
    assert a.controller == holder
    assert a.rests_on == rests_on
    assert a.removed_by == removed_by
    assert not a.ladder and not a.moved_by and not a.without_leave


# --- rules 2, 3 and 4: each military post, its ladder, who moves it, its acts --------------


@pytest.mark.parametrize("key", sorted(MILITARY))
def test_each_military_post_names_who_may_move_its_holder(key: str) -> None:
    world = _world()
    holder, moved_by = MILITARY[key]
    a = _asset(world, key)
    assert a.kind.value == "office" and a.controller == holder
    assert a.moved_by == moved_by
    assert a.ladder == ()  # gap: no lesser command or staff post is sourced
    assert a.without_leave == ()  # gap: no act without leave is sourced
    assert not a.rests_on and a.removed_by is None


@pytest.mark.parametrize("key", sorted({**HEADS, **MILITARY}))
def test_each_holders_card_names_his_post(key: str) -> None:
    world = _world()
    holder = HEADS[key][0] if key in HEADS else MILITARY[key][0]
    assert locks_1941._card(world, holder).post == key


def test_a_ladder_that_loops_is_refused() -> None:
    world = _world()
    loop = {"uboat_command": ("home_fleet_command",), "home_fleet_command": ("uboat_command",)}
    looped = [
        a.model_copy(update={"ladder": loop[a.key]}) if a.key in loop else a for a in world.assets
    ]
    with pytest.raises(WorldError, match="ladder loops back"):
        locks_1941._compile(world.model_copy(update={"assets": tuple(looped)}))


# --- keeps: the three switches off fold as the baseline -----------------------------------


def test_with_the_three_switches_out_the_scripted_digest_is_the_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    off = _without(_world(), THREE)
    assert not {r.value for r in THREE} & set(off.rules)
    assert locks_1941.run_digest(off, monkeypatch) == SHIPPED_1941
