"""The war resolver: what an enacted declaration of war sets going."""

from datetime import date

from revisionist.core.ids import EntityId
from revisionist.core.ontology import Fact, Relationship
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.resolvers import apply_changes, war
from revisionist.core.realism.war import NewsEvent, NewsTopic, War, at_war, war_id_for
from revisionist.core.visibility import PUBLIC
from tests.test_realism_resolvers import Rig, rig

DAY = date(1941, 12, 11)
KEYS = ("gallup_declare_war_germany", "gallup_help_britain")


def declare(r: Rig, target: str = "usa", lever: str = "declare_war") -> Order:
    """Hitler's order, enacted on DAY."""
    return r.enact("hitler", lever, "reich_declaration", date(1941, 12, 10), [DAY], target=target)


def hitler_rig() -> Rig:
    """A rig with Hitler's seat."""
    return rig(seat="hitler")


def ent(r: Rig, key: str) -> EntityId:
    """A world key's entity id."""
    return EntityId(r.ids[key])


def test_an_enacted_declaration_yields_the_war_fact_relationship_and_news() -> None:
    r = hitler_rig()
    changes = war.resolve(r.state, declare(r))
    g, u = ent(r, "germany"), ent(r, "usa")
    assert [type(c) for c in changes] == [War, Fact, Relationship, NewsEvent]
    w, fact, rel, news = changes
    assert isinstance(w, War) and isinstance(fact, Fact)
    assert isinstance(rel, Relationship) and isinstance(news, NewsEvent)
    assert (w.war_id, w.a, w.b, w.since) == (war_id_for(g, u), g, u, DAY)
    assert w.declared_by == ent(r, "hitler")
    assert (fact.subject, fact.predicate, fact.obj, fact.scope) == (g, "at_war_with", u, PUBLIC)
    assert {rel.a, rel.b} == {g, u} and rel.disposition == -5 and rel.scope == PUBLIC
    assert news.topic is NewsTopic.WAR_DECLARED and (news.subject, news.obj) == (g, u)
    assert news.on == DAY and len(news.headline) <= 60
    assert news.headline == "Germany declares war on United States"
    assert [(f.label, f.value) for f in news.facts] == [
        ("Declared by", "Germany"),
        ("Against", "United States"),
        ("Date", "1941-12-11"),
    ]


def test_a_seeded_opinion_rises_and_a_gap_is_left_alone() -> None:
    r = hitler_rig()
    r.set_value(KEYS[0], 98)
    changes = war.resolve(r.state, declare(r))
    puts = [c for c in changes if isinstance(c, QuantityChange)]
    assert [(p.value, p.as_of) for p in puts] == [(100, DAY)]
    assert len(changes) == 5


def test_the_changes_fold_and_the_war_holds_in_both_orders() -> None:
    r = hitler_rig()
    changes = war.resolve(r.state, declare(r))
    r.fold_changes(changes)
    g, u = ent(r, "germany"), ent(r, "usa")
    assert at_war(r.state, g, u) and at_war(r.state, u, g)
    assert apply_changes(r.state, changes) is not None


def test_a_repeat_declaration_changes_nothing() -> None:
    r = hitler_rig()
    order = declare(r)
    r.fold_changes(war.resolve(r.state, order))
    assert war.resolve(r.state, order) == ()


def test_not_enacted_unknown_target_or_other_lever_yield_nothing() -> None:
    r = hitler_rig()
    order = r.draft("hitler", "declare_war", "reich_declaration", DAY, target="usa")
    assert war.resolve(r.state, order) == ()
    refused = r.settle(order, OrderStatus.REFUSED)
    assert war.resolve(r.state, refused) == ()
    assert war.resolve(r.state, declare(r, target="nowhere")) == ()
    assert war.resolve(r.state, declare(r, target="hitler")) == ()
    assert war.resolve(r.state, declare(r, target="germany")) == ()
    assert war.resolve(r.state, declare(r, lever="uboat_directive")) == ()


def test_it_is_deterministic() -> None:
    r = hitler_rig()
    order = declare(r)
    assert war.resolve(r.state, order) == war.resolve(r.state, order)
