"""The newsstand: each seat reads its home paper, a domestic opposition or neutral
paper, and an adversary's, and every paper prints the same public facts."""

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import EntityId, SeatId
from revisionist.core.ontology import Entity, EntityKind, Fact, Seat, SeatKind
from revisionist.core.realism.card import Conflict, SeatCard
from revisionist.core.realism.press import news_pages, papers
from revisionist.core.realism.war import (
    NEUTRAL,
    OPPOSITION,
    Outlet,
    War,
    outlet_for,
    war_id_for,
)
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.core.world_compile import compile_world
from revisionist.engine import campaign as cmp
from tests.test_press import DAY, SECRET, folded, news
from tests.test_war_contract import CAMPAIGN, FDR, GER, SEAT, USA, world

UK, CHURCHILL = EntityId("uk"), EntityId("churchill")
SWISS, HITLER = EntityId("swiss"), EntityId("hitler")
LEDGER, SENTINEL = EntityId("ledger"), EntityId("sentinel")
TIMES, BOTE, GAZETTE = EntityId("times"), EntityId("bote"), EntityId("gazette")
SEAT_UK = SeatId("seat-churchill")


def _org(key: EntityId, parent: EntityId, *tags: str) -> Entity:
    return Entity(
        entity_id=key,
        kind=EntityKind.ORG,
        name=key,
        parent=parent,
        tags=frozenset({"press", *tags}),
    )


def _outlet(key: EntityId, polity: EntityId) -> Outlet:
    return Outlet(outlet_id=key, polity=polity, name=f"The {key}", voice="Plain.")


def stand(*, sentinel_first: bool = False) -> State:
    """Two seats (US, UK), a German and a Swiss paper, and a US opposition daily."""
    state = world()
    extra = [
        Entity(entity_id=UK, kind=EntityKind.POLITY, name="uk"),
        Entity(entity_id=SWISS, kind=EntityKind.POLITY, name="swiss"),
        Entity(entity_id=CHURCHILL, kind=EntityKind.PERSON, name="W", parent=UK),
        Entity(entity_id=HITLER, kind=EntityKind.PERSON, name="H", parent=GER),
        _org(SENTINEL, USA, OPPOSITION),
        _org(TIMES, UK),
        _org(BOTE, GER),
        _org(GAZETTE, SWISS, NEUTRAL),
    ]
    ledger = state.outlets[LEDGER]
    rest = [_outlet(TIMES, UK), _outlet(BOTE, GER), _outlet(GAZETTE, SWISS)]
    us = [_outlet(SENTINEL, USA), ledger] if sentinel_first else [ledger, _outlet(SENTINEL, USA)]
    seat = Seat(seat_id=SEAT_UK, kind=SeatKind.PLAYER, name="w", embodies=CHURCHILL)
    return state.model_copy(
        update={
            "entities": {**state.entities, **{e.entity_id: e for e in extra}},
            "seats": {**state.seats, SEAT_UK: seat},
            "outlets": {o.outlet_id: o for o in [*us, *rest]},
        }
    )


def card(person: EntityId, *against: EntityId) -> SeatCard:
    return SeatCard(
        person=person,
        office="Head",
        horizon_days=7,
        opposes=tuple(Conflict(against=a, over="the war") for a in against),
    )


def with_cards(state: State, *cards: SeatCard) -> State:
    return state.model_copy(update={"cards": {**state.cards, **{c.person: c for c in cards}}})


def ids(found: tuple[Outlet, ...]) -> list[EntityId]:
    return [o.outlet_id for o in found]


def test_the_home_paper_is_never_the_opposition_daily() -> None:
    home = outlet_for(stand(sentinel_first=True), SEAT)
    assert home is not None and home.outlet_id == LEDGER


def test_a_country_with_an_opposition_daily_reads_it_second() -> None:
    assert ids(papers(stand(sentinel_first=True), FDR)) == [LEDGER, SENTINEL]


def test_a_country_without_one_reads_the_neutral_paper_second() -> None:
    assert ids(papers(stand(), CHURCHILL)) == [TIMES, GAZETTE]


def test_the_adversary_is_the_first_opposed_power_that_is_not_its_own() -> None:
    state = with_cards(stand(), card(FDR, FDR, HITLER, UK))
    assert ids(papers(state, FDR)) == [LEDGER, SENTINEL, BOTE]
    state = with_cards(stand(), card(CHURCHILL, GER, USA))
    assert ids(papers(state, CHURCHILL)) == [TIMES, GAZETTE, BOTE]


def test_with_nothing_opposed_a_war_names_the_adversary() -> None:
    war = War(war_id=war_id_for(GER, UK), a=GER, b=UK, since=DAY, declared_by=HITLER)
    state = stand().model_copy(update={"wars": {war.war_id: war}})
    assert ids(papers(state, CHURCHILL)) == [TIMES, GAZETTE, BOTE]
    assert ids(papers(state, FDR)) == [LEDGER, SENTINEL]


def test_a_country_with_no_paper_of_its_own_reads_none() -> None:
    state = with_cards(stand(), card(HITLER, UK))
    outlets = {k: o for k, o in state.outlets.items() if k != BOTE}
    assert papers(state.model_copy(update={"outlets": outlets}), HITLER) == ()
    assert papers(state, EntityId("loose")) == ()


def test_a_paper_is_read_once_when_two_rules_name_it() -> None:
    swiss = Entity(entity_id=EntityId("tell"), kind=EntityKind.PERSON, name="T", parent=SWISS)
    state = stand()
    state = state.model_copy(update={"entities": {**state.entities, swiss.entity_id: swiss}})
    assert ids(papers(state, swiss.entity_id)) == [GAZETTE]
    state = with_cards(state, card(swiss.entity_id, SWISS, GER))
    assert ids(papers(state, swiss.entity_id)) == [GAZETTE, BOTE]


def test_every_paper_prints_the_same_public_facts() -> None:
    state = with_cards(stand(), card(FDR, GER), card(CHURCHILL, GER))
    state = folded(state, ev.NewsReported(news=news()))
    fact = Fact(fact_id="f1", subject=FDR, predicate="plans", obj=SECRET, scope=private_to(SEAT))
    state = folded(state, ev.FactAsserted(fact=fact))
    pages = news_pages(state, DAY)
    by_author = {p.document.author: p for p in pages}
    assert set(by_author) == {LEDGER, SENTINEL, TIMES, GAZETTE, BOTE}
    assert {p.document.body for p in pages} == {news().facts}
    assert {p.truth.news_id for p in pages} == {"n1"}
    for author, page in by_author.items():
        title = f"{state.outlets[author].name}: {news().headline}"
        assert page.document.title == (title if len(title) <= 60 else title[:59] + "…")
    assert by_author[BOTE].document.scope.known_by == {SEAT, SEAT_UK}
    assert by_author[GAZETTE].document.scope.known_by == {SEAT_UK}
    assert by_author[SENTINEL].document.scope.known_by == {SEAT}
    assert SECRET not in "".join(p.model_dump_json() for p in pages)


def test_a_seat_sees_one_page_from_each_of_its_three_papers() -> None:
    from revisionist.core.project import project

    state = with_cards(stand(), card(FDR, GER))
    state = folded(state, ev.NewsReported(news=news()))
    state = folded(state, *news_pages(state, DAY))
    state = state.model_copy(update={"in_world_date": DAY})
    seen = project(state, SEAT).documents.values()
    assert sorted(p.author for p in seen) == sorted([LEDGER, SENTINEL, BOTE])


def test_autumn_1941_gives_every_leader_three_papers() -> None:
    state = replay(
        compile_world(cmp.load_world(cmp.world_path("autumn-1941")), CAMPAIGN, cmp.versions())
    )
    by_name = {e.name: e.entity_id for e in state.entities.values()}
    sentinel, gazette = "The Heartland Sentinel", "The Alpine Gazette"
    expected = {
        "Franklin D. Roosevelt": ["The Washington Ledger", sentinel, "Der Reichsbote"],
        "Winston Churchill": ["The London Chronicle", gazette, "Der Reichsbote"],
        "Joseph Stalin": ["Krasnaya Zarya", gazette, "Der Reichsbote"],
        "Adolf Hitler": ["Der Reichsbote", gazette, "Krasnaya Zarya"],
        "Fumimaro Konoe": ["The Rising Sun Courier", gazette, "The Chungking Herald"],
        "Hideki Tojo": ["The Rising Sun Courier", gazette, "The Chungking Herald"],
        "Benito Mussolini": ["Gazzetta dell'Impero", gazette, "The London Chronicle"],
        "Chiang Kai-shek": ["The Chungking Herald", gazette, "The Rising Sun Courier"],
    }
    found = {name: [o.name for o in papers(state, by_name[name])] for name in expected}
    assert found == expected
