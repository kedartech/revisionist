"""Ideas with memory: the option generator reads the seat's record, and never
offers what the seat already has on its way."""

from datetime import date, timedelta
from pathlib import Path

from revisionist.core import events as ev
from revisionist.core import record
from revisionist.core.ontology import EntityKind
from revisionist.core.project import project
from revisionist.core.realism.agenda import Ask, Option, PlayStyle
from revisionist.engine import options, realism_tick, wake
from revisionist.engine.llm import Reply, Request
from revisionist.engine.store import MemoryStore
from tests.test_engine_v2_wake import CAMPAIGN, T0, Table, play


class _Spy:
    """Keeps each request and offers nothing, so the template stands in."""

    def __init__(self) -> None:
        self.requests: list[Request] = []

    def call(self, request: Request) -> Reply:
        self.requests.append(request)
        return Reply({"options": []}, "hand", 0, 0, 0, 0.0)


def _beginner() -> Table:
    t = Table(MemoryStore())
    options.set_style(t.store, CAMPAIGN, t.fdr, PlayStyle.BEGINNER)
    wake.open_wake(t.store, CAMPAIGN, T0)
    return t


def _offered(t: Table) -> list[str]:
    made = options.offer(t.state, t.fdr, None)
    assert made is not None
    return [o.label for o in made.offers[-1].options]


def test_an_option_already_on_its_way_is_not_offered_again() -> None:
    t = _beginner()
    made = options.offer(t.state, t.fdr, None)
    assert made is not None
    first = made.offers[-1].options[0]
    assert first.label in _offered(t)
    realism_tick.commit_order(t.store, CAMPAIGN, t.fdr, first.asks)
    after = _offered(t)
    assert first.label not in after and 3 <= len(after) <= 4


def test_the_same_words_to_the_same_person_are_not_offered_again() -> None:
    t = _beginner()
    stark = t.entity("stark")
    name = t.state.entities[stark].name
    label = f"Press {name} for support"
    assert label in _offered(t)
    realism_tick.commit_order(
        t.store, CAMPAIGN, t.fdr, [Ask(ask=f"Ask {name} to back our course", target=stark)]
    )
    after = _offered(t)
    assert label not in after and 3 <= len(after) <= 4


def test_the_prompt_carries_what_arrived_what_is_moving_and_what_was_offered(
    tmp_path: Path,
) -> None:
    t = _beginner()
    assert wake.offer_all(t.store, CAMPAIGN, None) == 1
    (offered,) = t.payloads(ev.OptionsOffered)
    taken, passed = offered.offers[-1].options[0], offered.offers[-1].options[1]
    realism_tick.commit_order(t.store, CAMPAIGN, t.fdr, taken.asks)
    words = "Tell the House leaders I want their count by Friday"
    realism_tick.commit_order(
        t.store, CAMPAIGN, t.fdr, [Ask(ask=words, target=t.entity("rayburn"))]
    )
    play(t, tmp_path, T0 + timedelta(hours=13))

    memory = record.build(t.state, list(t.store.read(CAMPAIGN)), t.fdr)
    new = memory.wakes[-1].papers
    assert new, "the tick brought papers"
    prompt = options.options_prompt(project(t.state, t.fdr), None, PlayStyle.BEGINNER, memory)
    assert "## Since the last wake" in prompt
    assert all(p.title in prompt for p in new)
    stated = [
        b.label
        for p in new
        for b in project(t.state, t.fdr).documents[p.doc_id].body
        if b.value is not None
    ]
    assert stated and all(label in prompt for label in stated[:2])
    assert words in prompt
    settled = [o for o in memory.orders if o.key in memory.wakes[-1].settled]
    assert settled and all(f'"came_of_it":"{o.status}"' in prompt for o in settled)
    assert all(f'"asked":"{o.asked}"' in prompt for o in settled)
    assert f'"label":"{taken.label}","taken":true' in prompt.replace(", ", ",").replace(": ", ":")
    assert f'"label":"{passed.label}","taken":false' in prompt.replace(", ", ",").replace(": ", ":")
    bare = options.options_prompt(project(t.state, t.fdr), None, PlayStyle.BEGINNER)
    assert "## Since the last wake" not in bare and words not in bare


def test_offer_all_hands_the_generator_the_seats_record(tmp_path: Path) -> None:
    t = _beginner()
    wake.offer_all(t.store, CAMPAIGN, None)
    words = "Tell the House leaders I want their count by Friday"
    realism_tick.commit_order(
        t.store, CAMPAIGN, t.fdr, [Ask(ask=words, target=t.entity("rayburn"))]
    )
    assert t.winston is not None
    theirs = "MARKER-ONLY-CHURCHILL-TYPED-THIS"
    realism_tick.commit_order(
        t.store, CAMPAIGN, t.winston, [Ask(ask=theirs, target=t.entity("pound"))]
    )
    spy = _Spy()
    assert wake.offer_all(t.store, CAMPAIGN, spy) == 1
    assert spy.requests and all(words in r.prompt for r in spy.requests)
    assert not any(theirs in r.prompt for r in spy.requests)


def test_an_option_offered_under_two_headings_is_listed_once() -> None:
    t = _beginner()
    twice = (
        record.OfferLine(label="Make a public statement"),
        record.OfferLine(label="Press the Speaker"),
        record.OfferLine(label="Make a public statement", taken=True),
    )
    page = record.WakePage(number=0, opened=date(1941, 9, 1), days_passed=0, offered=twice)
    memory = record.Record(seat=t.fdr, wakes=(page,))
    prompt = options.options_prompt(project(t.state, t.fdr), None, PlayStyle.BEGINNER, memory)
    assert prompt.count('"label":"Make a public statement"') == 1
    assert '{"label":"Make a public statement","taken":true}' in prompt
    assert '{"label":"Press the Speaker","taken":false}' in prompt


def test_no_idea_is_aimed_at_a_country() -> None:
    t = _beginner()
    for _ in range(2):
        made = options.offer(t.state, t.fdr, None)
        assert made is not None
        realism_tick.commit_order(t.store, CAMPAIGN, t.fdr, made.offers[-1].options[0].asks)
    made = options.offer(t.state, t.fdr, None)
    assert made is not None
    aimed = [o.to for o in made.offers[-1].options if o.to is not None]
    assert len(aimed) >= 2, "the first ideas are filed, so the list reaches the people to press"
    kinds = {who: t.state.entities[who].kind for who in aimed}
    assert all(kind is not EntityKind.POLITY for kind in kinds.values()), kinds


class _Says:
    """Answers every request with the same options."""

    def __init__(self, offered: list[Option]) -> None:
        self.reply = {"options": [o.model_dump(mode="json") for o in offered]}

    def call(self, request: Request) -> Reply:
        return Reply(self.reply, "hand", 0, 0, 0, 0.0)


def test_an_option_that_repeats_its_own_ask_is_not_offered() -> None:
    t = _beginner()
    sound = options.offer(t.state, t.fdr, None)
    assert sound is not None
    typed = t.shoot_on_sight()
    worded = Ask(ask="Ask Rayburn to hold the House", target=t.entity("rayburn"))
    twins = [
        Option(label="Shoot on sight, twice over", asks=(typed, typed)),
        Option(label="Press Rayburn, twice over", asks=(worded, worded)),
    ]
    made = options.offer(t.state, t.fdr, _Says([*twins, *sound.offers[-1].options]))
    assert made is not None
    labels = [o.label for o in made.offers[-1].options]
    assert labels == [o.label for o in sound.offers[-1].options]
    for option in made.offers[-1].options:
        fresh = _beginner()
        realism_tick.commit_order(fresh.store, CAMPAIGN, fresh.fdr, option.asks)
