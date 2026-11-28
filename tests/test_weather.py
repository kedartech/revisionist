"""Weather by season (KWX).

The toy world names its kinds of weather and, for each region and month, which one holds;
a region with no row of its own takes the row of the region it lies in. Each test sets the
weather it needs over the toy world's regions (the mainland, the north and south within
it, the waters) and switches ``weather`` on, unless it says otherwise.

The toy world starts on 2 April 1900, so April turns to May on day 29. Norra's levy stands
on the Norra Plain (north): a step into the Norra Hills takes it 7 days, and from there a
step into the Sudland Coast (south, plain) 5. Sudland's galleys stand in the Gulf (waters);
a step into the Open Sea (deep) takes them 3 days.
"""

from collections.abc import Callable
from datetime import date, timedelta
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.realism import battle, territory
from revisionist.core.state import State
from tests import test_world_locks_1941 as locks_1941
from tests import test_world_locks_uk_1941 as locks_uk
from tests.test_adjacency_moves import World, day, entity, fold_changes, piece, send, walk, where
from tests.test_adjacency_moves import play as territories_play
from tests.test_battle_kinds import figures
from tests.test_battles import payloads, to_coast
from tests.test_rule_names import BASELINE_1941
from tests.test_territory_model import created, raw_toy, refused, variant

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
APR_30, MAY_1 = day(28), day(29)
DAY_1, DAY_12 = day(1), day(12)
COAST = entity("sudland_coast")
FAIR = {"key": "fair", "name": "Fair"}
_dirs = count()


def months(**held: str) -> dict[str, str]:
    """A region's row: fair every month but those named."""
    return {m: held.get(m, "fair") for m in MONTHS}


def sky(*kinds: dict[str, Any], on: bool = True, **rows: dict[str, str]) -> Callable[[World], None]:
    """The world's weather: fair and ``kinds``; the mainland and the waters fair all year
    but for ``rows``, which may also give the north or the south a row of its own; and the
    rule on unless ``on`` is false."""

    def change(w: World) -> None:
        w["weather"] = {
            "kinds": [FAIR, *kinds],
            "regions": {"mainland": months(), "waters": months(), **rows},
        }
        if on:
            w["rules"] = [*w.get("rules", ()), "weather"]

    return change


def weather(key: str, **effects: Any) -> dict[str, Any]:
    return {"key": key, "name": key.title(), **effects}


def tmp_in(tmp: Path) -> Path:
    where = tmp / f"w{next(_dirs)}"
    where.mkdir()
    return where


def play(tmp: Path, *changes: Callable[[World], None]) -> State:
    return territories_play(tmp_in(tmp), *changes)


def compiles(tmp: Path, *changes: Callable[[World], None]) -> State:
    def change(w: World) -> None:
        w["rules"] = ["territories"]
        for c in changes:
            c(w)

    return created(variant(tmp_in(tmp), change))[1]


def refusals(tmp: Path, *changes: Callable[[World], None]) -> tuple[str, ...]:
    def change(w: World) -> None:
        w["rules"] = ["territories"]
        for c in changes:
            c(w)

    return refused(variant(tmp_in(tmp), change))


def due(state: State, key: str) -> int:
    """Days from the toy world's start to the piece's next step."""
    found = piece(state, key).step_due
    assert found is not None
    return (found - day(0)).days


# --- rule 1: a world names its weather by region and month -------------------------------


def test_the_toy_world_names_its_weather_by_region_and_month(tmp_path: Path) -> None:
    def on(w: World) -> None:
        w["rules"] = [*w["rules"], "weather"]

    state = compiles(tmp_path, on)
    assert state.map is not None and state.map.weather is not None
    held = state.map.weather
    assert set(held.kinds) == {k["key"] for k in raw_toy()["weather"]["kinds"]}
    assert set(held.regions) == set(raw_toy()["weather"]["regions"])
    for row in held.regions.values():
        assert len(row) == 12


def test_with_the_rule_off_the_weather_is_left_out_unread(tmp_path: Path) -> None:
    state = compiles(tmp_path)
    assert state.map is not None and state.map.weather is None
    unread = compiles(tmp_path, sky(on=False, mainland={"jan": "hail"}))
    assert unread.map is not None and unread.map.weather is None


def test_with_the_rule_off_a_world_with_weather_compiles_as_one_without(tmp_path: Path) -> None:
    def none(w: World) -> None:
        w.pop("weather")

    def payloads_of(state_changes: Callable[[World], None]) -> list[Any]:
        def change(w: World) -> None:
            w["rules"] = ["territories"]
            state_changes(w)

        events, _ = created(variant(tmp_in(tmp_path), change))
        return [e.payload for e in events]

    assert payloads_of(none) == payloads_of(lambda w: None)


def test_a_region_takes_its_parents_row_unless_it_has_its_own(tmp_path: Path) -> None:
    from revisionist.core.realism import weather as wx

    state = compiles(
        tmp_path,
        sky(
            weather("thaw"),
            weather("frost"),
            mainland=months(apr="thaw"),
            south=months(apr="frost"),
        ),
    )
    hills, coast = entity("norra_hills"), entity("sudland_coast")
    assert wx.holds(state, hills, day(0)).key == "thaw"  # type: ignore[union-attr]
    assert wx.holds(state, coast, day(0)).key == "frost"  # type: ignore[union-attr]
    assert wx.holds(state, coast, MAY_1).key == "fair"  # type: ignore[union-attr]


def test_the_same_region_and_month_always_give_the_same_weather(tmp_path: Path) -> None:
    from revisionist.core.realism import weather as wx

    state = compiles(tmp_path, sky(weather("thaw"), mainland=months(apr="thaw")))
    hills = entity("norra_hills")
    seen = {wx.holds(state, hills, date(year, 4, d)).key for year in (1900, 1901) for d in (1, 30)}  # type: ignore[union-attr]
    assert seen == {"thaw"}


# --- rule 5: the compile refuses a region or a month left out, and unknown names ---------


def test_with_the_rule_on_a_world_with_no_weather_has_none(tmp_path: Path) -> None:
    def on_alone(w: World) -> None:
        w.pop("weather")
        w["rules"] = [*w["rules"], "weather"]

    state = send(play(tmp_path, on_alone), "ilse", "norra_levy", "sudby")
    assert due(state, "norra_levy") == 7


def test_a_region_left_out_is_refused(tmp_path: Path) -> None:
    def no_waters(w: World) -> None:
        del w["weather"]["regions"]["waters"]

    found = refusals(tmp_path, sky(), no_waters)
    assert "weather: no row for region waters or a region it lies in" in found


def test_a_month_left_out_is_refused(tmp_path: Path) -> None:
    def no_may(w: World) -> None:
        del w["weather"]["regions"]["mainland"]["may"]

    assert "weather: region mainland leaves out may" in refusals(tmp_path, sky(), no_may)


def test_a_row_for_an_unknown_region_or_weather_is_refused(tmp_path: Path) -> None:
    found = refusals(tmp_path, sky(atlantis=months(), mainland=months(may="hail")))
    assert "weather: unknown region atlantis" in found
    assert "weather: region mainland names hail in may, which is no kind of weather" in found


@pytest.mark.parametrize(
    ("effect", "problem"),
    [
        ({"slows": [{"days": 1, "pieces": ["zeppelin"]}]}, "zeppelin, which is no kind or domain"),
        ({"figures": [{"pieces": ["cog"], "attack": -1}]}, "cog, which is no kind or domain"),
        ({"closes": [{"pieces": ["envoy"]}]}, "envoy, which is no kind or domain"),
        ({"slows": [{"days": 1, "terrain": ["swamp"]}]}, "unknown terrain swamp"),
        ({"closes": [{"pieces": ["sea"], "terrain": ["reef"]}]}, "unknown terrain reef"),
    ],
)
def test_a_weather_that_names_no_kind_or_terrain_of_the_world_is_refused(
    tmp_path: Path, effect: dict[str, Any], problem: str
) -> None:
    def no_envoys(w: World) -> None:
        w["piece_kinds"] = [k for k in w["piece_kinds"] if k["domain"] != "envoy"]
        w["features"] = [f for f in w["features"] if f.get("piece") != "herald"]

    found = refusals(tmp_path, no_envoys, sky(weather("odd", **effect)))
    assert f"weather odd: {problem}" in "\n".join(found)


def test_a_kind_or_a_domain_of_the_world_is_named_without_refusal(tmp_path: Path) -> None:
    effects = {
        "slows": [{"days": 1, "pieces": ["galley", "land"], "terrain": ["hills", "deep"]}],
        "figures": [{"pieces": ["levy", "air"], "defence": 1}],
        "closes": [{"pieces": ["sea"], "terrain": ["deep"]}],
    }
    assert compiles(tmp_path, sky(weather("odd", **effects))).map is not None


# --- keeps: with the rule off nothing changes ---------------------------------------------


def test_with_the_rule_off_the_weather_changes_no_step(tmp_path: Path) -> None:
    slow = weather("thaw", slows=[{"days": 4}])
    off = send(
        play(tmp_path, sky(slow, on=False, mainland=months(apr="thaw"))),
        "ilse",
        "norra_levy",
        "sudby",
    )
    plain = send(play(tmp_path), "ilse", "norra_levy", "sudby")
    assert due(off, "norra_levy") == due(plain, "norra_levy") == 7


def test_the_1941_digest_with_the_rule_off_is_the_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    """1941 names the rule; taken out with the other piece switches and the third-run
    switches, the scripted run is the baseline."""
    world = locks_1941._world()
    assert "weather" in {r.value for r in world.rules}
    assert locks_1941.run_digest(locks_uk.without_third_run(world), monkeypatch) == BASELINE_1941


# --- rule 2: weather adds days to a step, by terrain and by the kind or domain -----------


THAW_HILLS = weather("thaw", slows=[{"days": 2, "terrain": ["hills"], "pieces": ["land"]}])


def test_a_weather_adds_days_to_a_step_into_the_terrain_it_names(tmp_path: Path) -> None:
    state = send(
        play(tmp_path, sky(THAW_HILLS, mainland=months(apr="thaw"))), "ilse", "norra_levy", "sudby"
    )
    assert due(state, "norra_levy") == 7 + 2
    assert piece(state, "norra_levy").arrives == day(7 + 2 + 5)


def test_a_weather_adds_nothing_to_a_step_into_other_terrain(tmp_path: Path) -> None:
    plain_only = weather("thaw", slows=[{"days": 2, "terrain": ["plain"]}])
    state = send(
        play(tmp_path, sky(plain_only, mainland=months(apr="thaw"))), "ilse", "norra_levy", "sudby"
    )
    assert due(state, "norra_levy") == 7
    assert piece(state, "norra_levy").arrives == day(7 + 5 + 2)


def test_a_weather_slows_only_the_kinds_and_domains_it_names(tmp_path: Path) -> None:
    galleys_only = weather("gales", slows=[{"days": 2, "pieces": ["galley"]}])
    land_only = weather("mud", slows=[{"days": 2, "pieces": ["land"]}])
    for kind, levy, galleys in ((galleys_only, 7, 3 + 2), (land_only, 7 + 2, 3)):
        row = months(apr=kind["key"])
        state = play(tmp_path, sky(kind, mainland=row, waters=row))
        state = send(state, "ilse", "norra_levy", "sudby")
        state = send(state, "tomas", "sudland_galleys", "open_sea")
        assert (due(state, "norra_levy"), due(state, "sudland_galleys")) == (levy, galleys)


def test_a_step_reads_the_weather_of_the_area_it_enters(tmp_path: Path) -> None:
    """The levy leaves the north for the hills, in the north: a slow in the south alone
    does not reach the first step, and reaches the second."""
    mud = weather("mud", slows=[{"days": 2, "pieces": ["land"]}])
    state = send(play(tmp_path, sky(mud, south=months(apr="mud"))), "ilse", "norra_levy", "sudby")
    assert due(state, "norra_levy") == 7
    assert piece(state, "norra_levy").arrives == day(7 + 5 + 2)


# --- rule 3: a step is counted with the weather of the day it begins ---------------------


def test_a_step_begun_the_day_before_the_month_turns_keeps_its_days(tmp_path: Path) -> None:
    state = play(tmp_path, sky(THAW_HILLS, mainland=months(apr="thaw")))
    begun = send(state, "ilse", "norra_levy", "norra_hills", on=APR_30)
    assert piece(begun, "norra_levy").step_due == APR_30 + timedelta(days=7 + 2)
    after, stepped = walk(begun, APR_30, APR_30 + timedelta(days=10))
    assert [s.on for s in stepped] == [APR_30 + timedelta(days=9)]
    assert where(after, "norra_levy") == entity("norra_hills")


def test_a_step_begun_the_day_the_month_turns_takes_the_new_months_days(tmp_path: Path) -> None:
    state = play(tmp_path, sky(THAW_HILLS, mainland=months(apr="thaw")))
    begun = send(state, "ilse", "norra_levy", "norra_hills", on=MAY_1)
    assert piece(begun, "norra_levy").step_due == MAY_1 + timedelta(days=7)


def test_each_later_step_is_counted_with_the_weather_of_the_day_it_begins(tmp_path: Path) -> None:
    """Sent on 22 April: the step into the hills is not slowed and ends on 29 April, in the
    thaw, so the step into the coast takes 2 days more; sent on 24 April, it ends on 1 May
    and the next step takes its 5 days."""
    thaw_plain = weather("thaw", slows=[{"days": 2, "terrain": ["plain"]}])
    state = play(tmp_path, sky(thaw_plain, mainland=months(apr="thaw")))
    for sent, second in ((day(20), 7), (day(22), 5)):
        begun = send(state, "ilse", "norra_levy", "sudby", on=sent)
        _, stepped = walk(begun, sent, sent + timedelta(days=20))
        first_in = sent + timedelta(days=7)
        assert [s.on for s in stepped] == [first_in, first_in + timedelta(days=second)]


# --- rule 2: weather closes an area to a named kind or domain ----------------------------


GALES = weather("gales", closes=[{"pieces": ["sea"], "terrain": ["deep"]}])
FLOOD = weather("flood", closes=[{"pieces": ["levy"], "terrain": ["plain"]}])


def test_a_closed_area_refuses_a_course_into_it_while_the_weather_holds(tmp_path: Path) -> None:
    state = play(tmp_path, sky(GALES, waters=months(apr="gales")))
    galleys = piece(state, "sudland_galleys")
    found = territory.plan(state, galleys, entity("open_sea"), on=day(0))
    assert isinstance(found, territory.Refused)
    assert "closed to The Sudland Galleys by Gales" in found.reason
    sent = send(state, "tomas", "sudland_galleys", "open_sea")
    assert not piece(sent, "sudland_galleys").path
    opened = territory.plan(state, galleys, entity("open_sea"), on=MAY_1)
    assert isinstance(opened, territory.Plan) and opened.days == (3,)


def test_a_closure_names_its_kinds_and_its_terrain(tmp_path: Path) -> None:
    shallow = weather("fog", closes=[{"pieces": ["sea"], "terrain": ["shallows"]}])
    levies = weather("fog", closes=[{"pieces": ["levy"]}])
    for kind in (shallow, levies):
        state = play(tmp_path, sky(kind, waters=months(apr="fog")))
        galleys = piece(state, "sudland_galleys")
        assert isinstance(
            territory.plan(state, galleys, entity("open_sea"), on=day(0)), territory.Plan
        )


def test_a_course_whose_later_step_would_begin_into_a_closed_area_is_refused(
    tmp_path: Path,
) -> None:
    """The coast is closed to the levy in May. Sent on 25 April, its step into the coast
    would begin on 2 May; sent on 20 April, it begins on 27 April and is taken, though it
    ends in May."""
    state = play(tmp_path, sky(FLOOD, south=months(may="flood")))
    late = send(state, "ilse", "norra_levy", "sudby", on=day(23))
    assert not piece(late, "norra_levy").path
    early, _ = walk(send(state, "ilse", "norra_levy", "sudby", on=day(18)), day(18), day(45))
    assert where(early, "norra_levy") == COAST


def test_a_piece_under_way_halts_before_a_step_that_would_begin_into_a_closed_area(
    tmp_path: Path,
) -> None:
    """A levy already under way to the coast: due in the hills on 2 May, it stops there;
    due there on 27 April, it goes on into the coast."""
    state = play(tmp_path, sky(FLOOD, south=months(may="flood")))

    def under_way(in_hills: date) -> State:
        moving = piece(state, "norra_levy").model_copy(
            update={
                "path": (entity("norra_hills"), COAST),
                "step_due": in_hills,
                "bound_for": COAST,
                "arrives": in_hills + timedelta(days=5),
            }
        )
        return fold_changes(state, [moving])

    late, _ = walk(under_way(day(30)), day(1), day(45))
    assert where(late, "norra_levy") == entity("norra_hills")
    assert not piece(late, "norra_levy").path
    early, _ = walk(under_way(day(25)), day(1), day(45))
    assert where(early, "norra_levy") == COAST


# --- rules 2 and 4: a battle's round reads the weather of its day ------------------------


def rounds(
    tmp: Path, *changes: Callable[[World], None], first: date = DAY_1, last: date = DAY_12
) -> list[ev.BattleRound]:
    """The coast battle's rounds from ``first`` to ``last``: Norra's levy steps into the
    coast on day 12."""
    g = to_coast(tmp_in(tmp), *changes)
    found: list[ev.BattleRound] = payloads(g.walk(first, last), ev.BattleRound)
    return found


def kinds_count(w: World) -> None:
    w["rules"] = [*w["rules"], "kinds_in_battle"]


def score_shift(tmp: Path, *changes: Callable[[World], None]) -> tuple[int, int]:
    """How far ``changes`` move each side's first-round score against the fair world."""
    (base, *_) = rounds(tmp, sky())
    (changed, *_) = rounds(tmp, *changes)
    assert changed.draws == base.draws
    return changed.scores[0] - base.scores[0], changed.scores[1] - base.scores[1]


MIRE = weather("mire", figures=[{"pieces": ["levy"], "attack": -1}])


def test_a_weather_changes_a_kinds_figure_in_a_battle(tmp_path: Path) -> None:
    assert score_shift(tmp_path, kinds_count, sky(MIRE, south=months(apr="mire"))) == (-1, 0)


def test_a_figure_change_names_its_figure_and_its_kinds(tmp_path: Path) -> None:
    firm = weather("frost", figures=[{"pieces": ["land"], "defence": 1}])
    galleys = weather("frost", figures=[{"pieces": ["galley"], "attack": -2, "defence": -2}])
    assert score_shift(tmp_path, kinds_count, sky(firm, south=months(apr="frost"))) == (0, 1)
    assert score_shift(tmp_path, kinds_count, sky(galleys, south=months(apr="frost"))) == (0, 0)


def test_a_figure_after_the_weather_is_held_to_1_to_5(tmp_path: Path) -> None:
    deep = weather("mire", figures=[{"pieces": ["levy"], "attack": -4}])
    assert score_shift(tmp_path, kinds_count, sky(deep, south=months(apr="mire"))) == (-2, 0)


def test_the_weather_of_the_fight_changes_the_figures_not_the_weather_elsewhere(
    tmp_path: Path,
) -> None:
    assert score_shift(tmp_path, kinds_count, sky(MIRE, north=months(apr="mire"))) == (0, 0)


def test_with_kinds_off_a_weathers_figures_change_no_score(tmp_path: Path) -> None:
    assert score_shift(tmp_path, sky(MIRE, south=months(apr="mire"))) == (0, 0)


def test_each_round_reads_the_weather_of_its_own_day(tmp_path: Path) -> None:
    """The world starts on 18 April, so the levy steps into the coast on 30 April: the
    first round is fought in April, the second on 1 May, in the mire."""

    def late_start(w: World) -> None:
        w["start_date"] = date(1900, 4, 18)

    span = {"first": date(1900, 4, 19), "last": date(1900, 5, 3)}
    fair = rounds(tmp_path, late_start, kinds_count, sky(MIRE), **span)
    mired = rounds(tmp_path, late_start, kinds_count, sky(MIRE, south=months(may="mire")), **span)
    assert [r.on for r in fair[:2]] == [date(1900, 4, 30), date(1900, 5, 1)]
    assert [r.on for r in mired[:2]] == [r.on for r in fair[:2]]
    assert mired[0].scores == fair[0].scores
    assert mired[1].draws == fair[1].draws
    assert mired[1].scores == (fair[1].scores[0] - 1, fair[1].scores[1])


# --- rule 2: weather grounds the air in or into its region ------------------------------


STORM = weather("storm", grounds_air=True)


@pytest.mark.parametrize("kinds", [False, True], ids=["kinds off", "kinds on"])
def test_grounded_air_gives_no_support_into_the_region(tmp_path: Path, kinds: bool) -> None:
    switch = (kinds_count,) if kinds else ()
    assert score_shift(tmp_path, *switch, sky(STORM, south=months(apr="storm"))) == (-1, 0)


@pytest.mark.parametrize("kinds", [False, True], ids=["kinds off", "kinds on"])
def test_grounded_air_gives_no_support_from_the_region(tmp_path: Path, kinds: bool) -> None:
    """Norra's kites stand on the Norra Plain, in the north."""
    switch = (kinds_count,) if kinds else ()
    assert score_shift(tmp_path, *switch, sky(STORM, north=months(apr="storm"))) == (-1, 0)


@pytest.mark.parametrize("kinds", [False, True], ids=["kinds off", "kinds on"])
def test_air_is_grounded_in_its_own_region_only(tmp_path: Path, kinds: bool) -> None:
    """The waters border the coast and the plain; a storm there keeps no kite down."""
    switch = (kinds_count,) if kinds else ()
    assert score_shift(tmp_path, *switch, sky(STORM, waters=months(apr="storm"))) == (0, 0)


def test_grounded_air_is_read_on_each_rounds_own_day(tmp_path: Path) -> None:
    """As in the figures' test, the first round is fought on 30 April, the second on 1 May,
    under the storm; kinds of piece do not count."""

    def late_start(w: World) -> None:
        w["start_date"] = date(1900, 4, 18)

    span = {"first": date(1900, 4, 19), "last": date(1900, 5, 3)}
    calm = rounds(tmp_path, late_start, sky(STORM), **span)
    storm = rounds(tmp_path, late_start, sky(STORM, south=months(may="storm")), **span)
    assert [r.on for r in storm[:2]] == [date(1900, 4, 30), date(1900, 5, 1)]
    assert storm[0].scores == calm[0].scores
    assert storm[1].draws == calm[1].draws
    assert storm[1].scores == (calm[1].scores[0] - 1, calm[1].scores[1])


def test_grounded_air_gives_no_support_the_next_month_unless_it_holds(tmp_path: Path) -> None:
    assert score_shift(tmp_path, sky(STORM, south=months(may="storm"))) == (0, 0)


def test_grounded_air_neither_strikes_nor_covers(tmp_path: Path) -> None:
    """The galleys in the Gulf strike one step and cover: they cancel Norra's kites and
    support Sudland. A storm over the waters stops both."""
    galleys = figures("galley", strike_steps=1, covers=True)
    (calm, *_) = rounds(tmp_path, kinds_count, galleys, sky(STORM))
    (storm, *_) = rounds(tmp_path, kinds_count, galleys, sky(STORM, waters=months(apr="storm")))
    assert storm.draws == calm.draws
    assert (storm.scores[0] - calm.scores[0], storm.scores[1] - calm.scores[1]) == (1, -1)


def test_the_air_rule_reads_the_weather_of_the_day_it_is_given(tmp_path: Path) -> None:
    """The odds call the battle's own air rule; with no day given it is the world's today."""
    grounded = to_coast(tmp_in(tmp_path), sky(STORM, south=months(apr="storm"))).state
    calm = to_coast(tmp_in(tmp_path), sky(STORM)).state
    norra = entity("norra")
    assert battle._air(calm, norra, COAST)
    assert not battle._air(grounded, norra, COAST)
    assert battle._air(grounded, norra, COAST, MAY_1)
