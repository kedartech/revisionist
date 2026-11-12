"""Feeds: documents that report the truth through an author's bias (pillar 3).

``due_feeds`` says which feeds owe a document today; ``issue`` writes one. The
bias is arithmetic on the true figure, drawn from a seed, so a replay writes the
same page. No model is involved: prose is added later, from the view alone.
"""

import hashlib
from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, DocumentId, SeatId, derived_id
from revisionist.core.realism import actors
from revisionist.core.realism.document import (
    BodyField,
    DocumentTruth,
    DocumentView,
    Feed,
    TruthRef,
)
from revisionist.core.realism.geography import Feature, Sight, SightRef
from revisionist.core.state import State
from revisionist.core.visibility import Scope, Visibility

NO_CHANGE = "No change since"
"""The one line of a page that would say word for word what the feed last stated."""
RESTATE_DAYS = 14
"""[proposed] A feed states its page in full again once its last full page is this old,
so a sighting on the map is not drawn as stale (``STALE_DAYS`` in the web snapshot)."""

TITLE = 60
"""A document title's length limit (``Label``)."""


def seed_for_day(campaign_id: CampaignId, today: date) -> str:
    return hashlib.blake2b(
        f"{campaign_id}\x1f{today.isoformat()}".encode(), digest_size=16
    ).hexdigest()


def _start(state: State, feed: Feed) -> date | None:
    """The campaign start as this feed sees it: the earliest ``as_of`` among the
    quantities it reports, else today's in-world date."""
    dates = [state.quantities[q].as_of for q in feed.reports if q in state.quantities]
    return min(dates) if dates else state.in_world_date


def _last_issued(state: State, feed: Feed) -> date | None:
    issued = [d.view.issued for d in state.documents.values() if d.truth.feed == feed.feed_id]
    return max(issued) if issued else None


def next_issue(state: State, feed: Feed) -> date | None:
    """The day ``feed`` next owes a document, or None for a gap cadence. The first
    issue falls due at the start (see ``_start``), the next ``every_days`` after the
    last one issued."""
    if feed.every_days is None:
        return None
    last = _last_issued(state, feed)
    return _start(state, feed) if last is None else last + timedelta(days=feed.every_days)


def due_feeds(state: State, today: date) -> list[Feed]:
    """Feeds owing a document on or before ``today``. A gap cadence never fires."""
    due: list[Feed] = []
    for feed in state.feeds.values():
        when = next_issue(state, feed)
        if when is not None and when <= today:
            due.append(feed)
    return due


def _draw(seed: str, feed: Feed, quantity: str, tag: str, n: int) -> int:
    """A deterministic integer in [0, n)."""
    key = f"{seed}\x1f{feed.feed_id}\x1f{quantity}\x1f{tag}"
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big") % n


def _report(seed: str, feed: Feed, quantity: str, true: int) -> int | None:
    """What the author claims for one figure: skewed, noised, or left out."""
    bias = feed.bias
    if _draw(seed, feed, quantity, "omit", 100) < bias.omit_pct:
        return None
    noise = _draw(seed, feed, quantity, "noise", 2 * bias.noise_pct + 1) - bias.noise_pct
    return (true * (100 + bias.skew_pct + noise) + 50) // 100


def _sight(state: State, seed: str, feed: Feed, f: Feature) -> BodyField | None:
    """Where the author places one feature: where it is, or nothing (left out).
    A force under way is placed where it set out from until it arrives."""
    if _draw(seed, feed, f.feature_id, "omit", 100) < feed.bias.omit_pct:
        return None
    words = " \N{EN DASH} ".join(state.entities[p].name for p in f.places)
    return BodyField(
        label=f.name,
        value=words if len(words) <= 60 else words[:59] + "…",
        sight=Sight(kind=f.kind, side=f.side, places=f.places),
    )


def _holders(state: State, feed: Feed) -> frozenset[SeatId]:
    persons = {p for p, c in state.cards.items() if feed.feed_id in c.feeds}
    return frozenset(
        s.seat_id
        for s in state.seats.values()
        if s.embodies in persons and s.seat_id in actors.readers(state)
    )


def _last_full(state: State, feed: Feed) -> DocumentView | None:
    """The feed's latest page that stated its lines, passing over no-change pages."""
    return max(
        (
            d.view
            for d in state.documents.values()
            if d.truth.feed == feed.feed_id and [line.label for line in d.view.body] != [NO_CHANGE]
        ),
        key=lambda v: v.issued,
        default=None,
    )


def _repeats(state: State, feed: Feed, body: tuple[BodyField, ...], today: date) -> date | None:
    """The day of the feed's last full page when today's page would say it again word for
    word, sightings included, and that page is under ``RESTATE_DAYS`` old; else None. A page
    with no lines (a cable the prose writes from its title) is never a repeat."""
    if not body:
        return None
    last = _last_full(state, feed)
    if last is None or last.body != body or (today - last.issued).days >= RESTATE_DAYS:
        return None
    return last.issued


def issue(state: State, feed: Feed, today: date, seed: str) -> ev.DocumentIssued | None:
    """The document ``feed`` issues today, or None when no seat holds the feed
    (a non-public scope needs a holder, and a feed no one receives is not a document)
    or when every line it would carry is left blank (nothing to state). A page that would
    repeat the feed's last full page word for word is one line instead: no change since
    that page's date. It places nothing, so the map keeps the full page's sighting."""
    holders = _holders(state, feed)
    if not holders:
        return None
    refs: list[TruthRef] = []
    body: list[BodyField] = []
    for qid in feed.reports:
        q = state.quantities[qid]
        refs.append(TruthRef(quantity_id=qid, value=q.value))
        claimed = None if q.value is None else _report(seed, feed, qid, q.value)
        body.append(BodyField(label=q.name, value=claimed, unit=q.unit))
    seen: list[SightRef] = []
    for fid in feed.sights:
        f = state.features[fid]
        line = _sight(state, seed, feed, f)
        if line is not None:
            seen.append(SightRef(feature_id=fid, places=f.places))
            body.append(line)
    if body and all(line.value is None for line in body):
        return None
    title = f"{feed.name}, {today.isoformat()}"
    since = _repeats(state, feed, tuple(body), today)
    if since is not None:
        body, seen = [BodyField(label=NO_CHANGE, value=f"{since.day} {since:%B %Y}")], []
        tail = f", {today.isoformat()}: no change"
        name = (
            feed.name
            if len(feed.name) + len(tail) <= TITLE
            else feed.name[: TITLE - len(tail) - 1] + "…"
        )
        title = name + tail
    doc_id = DocumentId(derived_id(state.campaign_id, feed.feed_id, today.isoformat()))
    arrives = today + timedelta(days=(feed.latency_days or 0) + feed.bias.delay_days)
    view = DocumentView(
        doc_id=doc_id,
        kind=feed.kind,
        author=feed.author,
        issued=today,
        arrives=arrives,
        channel=feed.channel,
        classification=feed.classification,
        title=title,
        body=tuple(body),
        scope=Scope(visibility=Visibility.PRIVATE, known_by=holders),
    )
    truth = DocumentTruth(
        doc_id=doc_id,
        feed=feed.feed_id,
        truth_refs=tuple(refs),
        bias=feed.bias,
        sightings=tuple(seen),
    )
    return ev.DocumentIssued(document=view, truth=truth)
