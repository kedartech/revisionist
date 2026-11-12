"""The PROSE stage (Phase 4): one call per author per wake, pages only, numbers checked,
written once across a crash, and a failed call never stops the tick."""

import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import get_type_hints

import pytest

from revisionist.core import events as ev
from revisionist.core.events import CallCost
from revisionist.core.fold import state_hash
from revisionist.core.ids import DocumentId
from revisionist.core.project import project
from revisionist.core.realism.document import DocumentView
from revisionist.core.resolution import TickStage
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC
from revisionist.engine.llm import RecordedTransport, Reply, Request, Transport, TransportError
from revisionist.engine.prose import (
    Author,
    ClaudeProseWriter,
    ProseWriter,
    TemplateProseWriter,
    Written,
    prose_prompt,
    template_prose,
)
from revisionist.engine.realism_tick import run_realism_tick, write_opening
from revisionist.engine.store import EventStore, MemoryStore, SqliteStore, load_state
from tests.handwritten import PROSE
from tests.prose_scenario import CANARY, scenario
from tests.test_realism_tick import CAMPAIGN


class Counting:
    """Writes every page with the template and records each call's author and pages."""

    def __init__(self, invent: bool = False) -> None:
        self.calls: list[tuple[str, tuple[DocumentId, ...]]] = []
        self.invent = invent

    def write(self, author: Author, pages: Sequence[DocumentView]) -> Written:
        self.calls.append((author.name, tuple(p.doc_id for p in pages)))
        prose = {p.doc_id: template_prose(author, p) for p in pages}
        if self.invent:
            prose = {k: v + " Also 4,321 rifles." for k, v in prose.items()}
        return Written(prose=prose)


class Capturing:
    """Passes calls through to ``inner`` and keeps every request sent."""

    def __init__(self, inner: Transport) -> None:
        self.inner = inner
        self.sent: list[Request] = []

    def call(self, request: Request) -> Reply:
        self.sent.append(request)
        return self.inner.call(request)


class Failing:
    def call(self, request: Request) -> Reply:
        raise TransportError("model unavailable")


def written(store: EventStore) -> list[ev.DocumentWritten]:
    return [e.payload for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.DocumentWritten)]


def test_one_call_per_author_per_wake() -> None:
    store = MemoryStore()
    cora, bram = scenario(store)
    writer = Counting()
    result = run_realism_tick(store, CAMPAIGN, prose=writer)
    state = load_state(store, CAMPAIGN)
    authors = [name for name, _ in writer.calls]
    assert sorted(authors) == ["Bram Tull", "Cora Senn"]  # two authors, two calls
    by_author = {name: set(ids) for name, ids in writer.calls}
    assert cora in by_author["Cora Senn"] and bram in by_author["Bram Tull"]
    bram_pages = {
        k for k, d in state.documents.items() if d.view.author == state.documents[bram].view.author
    }
    assert by_author["Bram Tull"] == bram_pages
    assert result.written == len(state.documents)
    assert all(d.view.prose for d in state.documents.values())
    writer.calls.clear()
    run_realism_tick(store, CAMPAIGN, prose=writer)  # the next wake writes only its new pages
    fresh = {
        k for k, d in load_state(store, CAMPAIGN).documents.items() if k not in state.documents
    }
    assert {i for _, ids in writer.calls for i in ids} == fresh


def test_stage_marker_follows_feeds_and_costs_reach_tick_closed() -> None:
    store = MemoryStore()
    scenario(store)
    run_realism_tick(store, CAMPAIGN, prose=ClaudeProseWriter(RecordedTransport(PROSE)))
    log = list(store.read(CAMPAIGN))
    stages = [e.payload.stage for e in log if isinstance(e.payload, ev.TickStageCompleted)]
    assert stages[-2:] == [TickStage.FEEDS, TickStage.PROSE]
    (closed,) = [e.payload for e in log if isinstance(e.payload, ev.TickClosed)]
    assert [c.call_class for c in closed.costs] == ["prose", "prose"]
    assert all(c.usd > 0 for c in closed.costs)
    prose_events = [e for e in log if isinstance(e.payload, ev.DocumentWritten)]
    assert all("document_prose=" in e.versions.prompt for e in prose_events)


@pytest.fixture(params=["memory", "sqlite"])
def stores(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[list[EventStore]]:
    made: list[EventStore] = [
        MemoryStore() if request.param == "memory" else SqliteStore(tmp_path / f"{n}.db")
        for n in range(2)
    ]
    yield made
    for s in made:
        if isinstance(s, SqliteStore):
            s.close()


def test_a_crash_after_feeds_resumes_and_writes_each_page_once(stores: list[EventStore]) -> None:
    whole, broken = stores
    for store in stores:
        scenario(store)
    run_realism_tick(whole, CAMPAIGN, prose=TemplateProseWriter())
    cut = run_realism_tick(
        broken, CAMPAIGN, prose=TemplateProseWriter(), stop_after=TickStage.FEEDS
    )
    assert cut.stopped_after is TickStage.FEEDS and not written(broken)
    resumed = run_realism_tick(broken, CAMPAIGN, prose=TemplateProseWriter())
    assert resumed.resumed_from is TickStage.FEEDS
    assert state_hash(load_state(broken, CAMPAIGN)) == state_hash(load_state(whole, CAMPAIGN))
    ids = [w.doc_id for w in written(broken)]
    assert len(ids) == len(set(ids)) == len(load_state(broken, CAMPAIGN).documents)
    again = run_realism_tick(broken, CAMPAIGN, prose=TemplateProseWriter())  # a later wake
    later = [w.doc_id for w in written(broken)]
    assert len(later) == len(set(later)) and again.state_hash


def test_a_figure_not_on_the_page_drops_the_prose() -> None:
    store = MemoryStore()
    scenario(store)
    result = run_realism_tick(store, CAMPAIGN, prose=Counting(invent=True))
    state = load_state(store, CAMPAIGN)
    assert written(store) == []
    assert all(d.view.prose is None for d in state.documents.values())
    assert len(result.prose_dropped) == len(state.documents)
    assert all("4321" in why for why in result.prose_dropped)
    assert any(isinstance(e.payload, ev.TickClosed) for e in store.read(CAMPAIGN))


class SecondDraft:
    """Invents a figure on the first draft of the pages in ``bad`` (every page when
    empty), and writes cleanly when told why a draft was refused; ``fail_retry`` makes
    the second call fail instead. Records each call's pages and refusals."""

    def __init__(self, bad: Sequence[DocumentId] = (), fail_retry: bool = False) -> None:
        self.calls: list[tuple[tuple[DocumentId, ...], dict[DocumentId, str]]] = []
        self.bad = set(bad)
        self.fail_retry = fail_retry

    def write(self, author: Author, pages: Sequence[DocumentView]) -> Written:
        self.calls.append((tuple(p.doc_id for p in pages), dict(author.refused)))
        if author.refused and self.fail_retry:
            raise TransportError("model unavailable")
        prose = {}
        for p in pages:
            text = template_prose(author, p)
            if not author.refused and (not self.bad or p.doc_id in self.bad):
                text += " Also 4,321 rifles."
            prose[p.doc_id] = text
        return Written(prose=prose, cost=COST)


COST = CallCost(call_class="prose", model="m", input_tokens=1, output_tokens=1, usd=0.01)


def test_a_refused_draft_is_written_once_more_and_told_why() -> None:
    store = MemoryStore()
    scenario(store)
    writer = SecondDraft()
    result = run_realism_tick(store, CAMPAIGN, prose=writer)
    state = load_state(store, CAMPAIGN)
    assert all(d.view.prose and "4,321" not in d.view.prose for d in state.documents.values())
    assert result.prose_dropped == ()
    first = [c for c in writer.calls if not c[1]]
    again = [c for c in writer.calls if c[1]]
    assert len(first) == len(again) == 2  # one retry per author
    for (pages, _), (retried, why) in zip(first, again, strict=True):
        assert retried == pages and set(why) == set(pages)
        assert all("4321" in w for w in why.values())
    (closed,) = [e.payload for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.TickClosed)]
    assert len(closed.costs) == 4


def test_only_the_refused_pages_are_sent_again() -> None:
    store = MemoryStore()
    _, bram = scenario(store)
    writer = SecondDraft(bad=[bram])
    run_realism_tick(store, CAMPAIGN, prose=writer)
    again = [c for c in writer.calls if c[1]]
    assert again == [((bram,), {bram: again[0][1][bram]})]
    assert load_state(store, CAMPAIGN).documents[bram].view.prose


def test_a_page_refused_twice_is_dropped_after_one_retry() -> None:
    store = MemoryStore()
    scenario(store)
    writer = Counting(invent=True)
    result = run_realism_tick(store, CAMPAIGN, prose=writer)
    assert len(writer.calls) == 4  # two authors, one retry each
    assert written(store) == []
    assert len(result.prose_dropped) == len(load_state(store, CAMPAIGN).documents)


def test_a_failed_retry_leaves_the_page_bare_and_closes_the_tick() -> None:
    store = MemoryStore()
    scenario(store)
    result = run_realism_tick(store, CAMPAIGN, prose=SecondDraft(fail_retry=True))
    state = load_state(store, CAMPAIGN)
    assert result.state_hash and written(store) == []
    assert len(result.prose_dropped) == len(state.documents)
    (closed,) = [e.payload for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.TickClosed)]
    assert len(closed.costs) == 2  # the first drafts were paid for


def test_the_prompt_names_why_a_draft_was_refused_on_that_page_only() -> None:
    store = MemoryStore()
    _, bram = scenario(store)
    state = load_state(store, CAMPAIGN)
    page = state.documents[bram].view
    author = Author(entity=page.author, name="Bram Tull", refused={bram: "states 4321"})
    prompt = prose_prompt(author, [page])
    assert "states 4321" in prompt and "refused" in prompt
    assert "refused" not in prose_prompt(author.model_copy(update={"refused": {}}), [page])


def test_a_transport_failure_leaves_prose_none_and_closes_the_tick() -> None:
    store = MemoryStore()
    scenario(store)
    result = run_realism_tick(store, CAMPAIGN, prose=ClaudeProseWriter(Failing()))
    state = load_state(store, CAMPAIGN)
    assert result.state_hash
    assert all(d.view.prose is None for d in state.documents.values())
    assert all("call failed" in why for why in result.prose_dropped)
    (closed,) = [e.payload for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.TickClosed)]
    assert closed.costs == ()


def test_the_truth_canary_reaches_no_prose_request_and_no_view() -> None:
    store = MemoryStore()
    _, bram = scenario(store)
    assert any(
        r.canary == CANARY for r in load_state(store, CAMPAIGN).documents[bram].truth.truth_refs
    )
    transport = Capturing(RecordedTransport(PROSE))
    run_realism_tick(store, CAMPAIGN, prose=ClaudeProseWriter(transport))
    assert len(transport.sent) == 2
    for req in transport.sent:
        assert CANARY not in req.system + req.prompt + json.dumps(req.schema)
        assert "truth_refs" not in req.prompt and "loyalty" not in req.prompt
    state = load_state(store, CAMPAIGN)
    assert state.documents[bram].view.prose  # the recorded prose was written
    for seat in state.seats:
        assert CANARY not in project(state, seat).model_dump_json()


def test_a_writer_takes_pages_never_state() -> None:
    hints = get_type_hints(ProseWriter.write)
    assert hints["pages"] == Sequence[DocumentView] and hints["author"] is Author
    assert State not in hints.values()
    store = MemoryStore()
    scenario(store)
    state = load_state(store, CAMPAIGN)
    with pytest.raises(TypeError):
        TemplateProseWriter().write(Author(entity=next(iter(state.entities)), name="x"), [state])  # type: ignore[list-item]
    truth = next(iter(state.documents.values())).truth
    with pytest.raises(TypeError):
        ClaudeProseWriter(Failing()).write(Author(entity=truth.doc_id, name="x"), [truth])  # type: ignore[list-item]


def test_template_prose_states_only_the_page() -> None:
    from revisionist.core.realism.prose import invented_numbers

    store = MemoryStore()
    scenario(store)
    run_realism_tick(store, CAMPAIGN, prose=TemplateProseWriter())
    for doc in load_state(store, CAMPAIGN).documents.values():
        assert doc.view.prose and invented_numbers(doc.view.prose, doc.view) == ()


def test_a_page_with_no_lines_gets_a_kind_fit_acknowledgement_and_passes_the_check() -> None:
    from revisionist.core.realism.document import DocumentKind
    from revisionist.engine.prose import accepted

    store = MemoryStore()
    scenario(store)
    run_realism_tick(store, CAMPAIGN)
    page = next(iter(load_state(store, CAMPAIGN).documents.values())).view
    author = Author(entity=page.author, name="A. Clerk")
    for kind in (DocumentKind.CABLE, DocumentKind.LETTER, DocumentKind.MEMO, DocumentKind.PRESS):
        bare = page.model_copy(update={"kind": kind, "body": (), "prose": None})
        text = template_prose(author, bare)
        assert "nothing to report" not in text
        assert accepted([bare], Written(prose={bare.doc_id: text}))[1] == []
    cable = page.model_copy(update={"kind": DocumentKind.CABLE, "body": (), "prose": None})
    assert "Message received. Fuller report follows." in template_prose(author, cable)


def test_a_private_page_is_addressed_to_the_office_that_holds_it() -> None:
    from revisionist.engine.prose import author_of, page_lines, prose_prompt

    store = MemoryStore()
    scenario(store)
    run_realism_tick(store, CAMPAIGN)
    state = load_state(store, CAMPAIGN)
    private = next(d.view for d in state.documents.values() if d.view.scope.known_by)
    author = author_of(state, private.author, [private])
    (office,) = author.to.values()
    assert office and page_lines(private, author)["to"] == office
    assert f"To the {office}" in template_prose(
        author, private.model_copy(update={"kind": "letter"})
    )
    public = private.model_copy(update={"scope": PUBLIC})
    assert author_of(state, private.author, [public]).to == {}
    assert "to" not in page_lines(public, author_of(state, private.author, [public]))
    assert "recipient" not in prose_prompt(author, [private]).lower()


def test_a_line_with_no_figure_is_neither_prompted_nor_written() -> None:
    from datetime import date

    from revisionist.core.ids import EntityId
    from revisionist.core.realism.card import ChannelKind
    from revisionist.core.realism.document import BodyField, DocumentKind
    from revisionist.engine.prose import page_lines

    page = DocumentView(
        doc_id=DocumentId("D1"),
        kind=DocumentKind.REPORT,
        author=EntityId("E1"),
        issued=date(1941, 10, 1),
        arrives=date(1941, 10, 1),
        channel=ChannelKind.LETTER,
        title="A report",
        body=(
            BodyField(label="Tanks shipped", value=None),
            BodyField(label="Aircraft shipped", value=40),
        ),
        scope=PUBLIC,
    )
    author = Author(entity=EntityId("E1"), name="Harry Hopkins")
    assert [x["label"] for x in page_lines(page, author)["lines"]] == ["Aircraft shipped"]
    written = template_prose(author, page)
    assert "Aircraft shipped: 40." in written and "Tanks" not in written
    assert "nothing firm" not in written


# --- the opening papers, written at the begin ------------------------------------------


class Priced(Counting):
    """``Counting`` with a cost on every call."""

    def write(self, author: Author, pages: Sequence[DocumentView]) -> Written:
        out = super().write(author, pages)
        cost = ev.CallCost(
            call_class="prose", model="m", input_tokens=10, output_tokens=5, usd=0.01
        )
        return out.model_copy(update={"cost": cost})


def test_the_opening_papers_are_written_at_the_begin_and_not_again_on_the_first_tick() -> None:
    store = MemoryStore()
    cora, bram = scenario(store)
    writer = Counting()
    done = write_opening(store, CAMPAIGN, writer)
    state = load_state(store, CAMPAIGN)
    assert state.tick == 0
    assert sorted(name for name, _ in writer.calls) == ["Bram Tull", "Cora Senn"]
    assert state.documents[cora].view.prose and state.documents[bram].view.prose
    assert done.written == len(state.documents)
    writer.calls.clear()
    run_realism_tick(store, CAMPAIGN, prose=writer)
    assert not {cora, bram} & {i for _, ids in writer.calls for i in ids}


def test_the_opening_prose_costs_are_logged_once_outside_the_tick() -> None:
    store = MemoryStore()
    scenario(store)
    write_opening(store, CAMPAIGN, Priced())
    log = list(store.read(CAMPAIGN))
    (logged,) = [e.payload for e in log if isinstance(e.payload, ev.CostLogged)]
    assert [c.call_class for c in logged.costs] == ["prose", "prose"]
    assert not any(isinstance(e.payload, ev.TickOpened) for e in log)
    prose_events = [e for e in log if isinstance(e.payload, ev.DocumentWritten)]
    assert prose_events and all("document_prose=" in e.versions.prompt for e in prose_events)


def test_a_failed_opening_call_leaves_its_pages_to_the_first_tick() -> None:
    store = MemoryStore()
    cora, bram = scenario(store)
    done = write_opening(store, CAMPAIGN, ClaudeProseWriter(Failing()))
    assert done.written == 0 and all("call failed" in why for why in done.prose_dropped)
    assert all(d.view.prose is None for d in load_state(store, CAMPAIGN).documents.values())
    assert not any(isinstance(e.payload, ev.CostLogged) for e in store.read(CAMPAIGN))
    writer = Counting()
    run_realism_tick(store, CAMPAIGN, prose=writer)
    assert {cora, bram} <= {i for _, ids in writer.calls for i in ids}


class TickMeanwhile(Counting):
    """``Counting`` that opens a tick in the same store during its first call, as another
    writer (the host's close, a scheduler run) could while the opening prose is out."""

    def __init__(self, store: EventStore) -> None:
        super().__init__()
        self.store = store

    def write(self, author: Author, pages: Sequence[DocumentView]) -> Written:
        if not self.calls:
            run_realism_tick(self.store, CAMPAIGN, stop_after=TickStage.FEEDS)
        return super().write(author, pages)


def test_an_opening_overtaken_by_a_tick_writes_nothing_and_does_not_raise() -> None:
    store = MemoryStore()
    scenario(store)
    writer = TickMeanwhile(store)
    done = write_opening(store, CAMPAIGN, writer)
    assert writer.calls and done.written == 0
    assert written(store) == []
    assert not any(isinstance(e.payload, ev.CostLogged) for e in store.read(CAMPAIGN))


@pytest.mark.parametrize("stop_after", [TickStage.FEEDS, None])
def test_the_opening_is_written_only_before_the_first_tick(stop_after: TickStage | None) -> None:
    store = MemoryStore()
    scenario(store)
    run_realism_tick(store, CAMPAIGN, stop_after=stop_after)  # no writer: pages stay bare
    writer = Counting()
    done = write_opening(store, CAMPAIGN, writer)
    assert writer.calls == [] and done.written == 0
