"""An inquiry's report is signed by whoever carried the inquiry out, never by the issuer."""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, OrderId, derived_id
from revisionist.core.realism import effect as rx
from revisionist.core.realism.apply import apply_due, reporter
from revisionist.core.realism.document import DocumentKind
from revisionist.core.visibility import private_to
from tests.test_realism_resolvers import CAMPAIGN, Rig

FILED = date(1941, 9, 11)


def inquiry(r: Rig, executor: str | None = None) -> list[ev.DocumentIssued]:
    """Stalin orders an inquiry into Hitler; the papers that land for him."""
    stalin = r.seats["stalin"]
    fields: dict[str, object] = {
        "route": rx.Route.COMMAND,
        "domain": "public_word" if executor is None else "military_operations",
    }
    if executor is not None:
        fields["executor"] = EntityId(r.ids[executor])
    order = rx.RoutedOrder(
        order_id=OrderId(derived_id(CAMPAIGN, "sgn-order", executor or "none")),
        issuer=stalin,
        filed=FILED,
        parts=(rx.RoutedPart.model_validate(fields),),
    )
    r.add(ev.OrderRouted(order=order))
    inquire = rx.Investigate(target=EntityId(r.ids["hitler"]), question="What is Hitler planning?")
    r.add(ev.EffectsEstimated(order_id=order.order_id, part=0, effects=(inquire,), reason="Asked."))
    r.add(ev.OrderExecuted(order_id=order.order_id, part=0, on=FILED, fidelity=rx.Fidelity.FULL))
    docs = [p for p in apply_due(r.state, FILED) if isinstance(p, ev.DocumentIssued)]
    assert all(d.document.scope == private_to(stalin) for d in docs)
    return docs


def stalin_rig() -> Rig:
    r = Rig()
    r.seat("stalin")
    r.close_session_zero()
    return r


def reports(docs: list[ev.DocumentIssued]) -> list[ev.DocumentIssued]:
    return [d for d in docs if d.document.kind is DocumentKind.REPORT]


def test_stalins_inquiry_is_not_signed_by_stalin() -> None:
    r = stalin_rig()
    (inq,) = reports(inquiry(r))
    assert inq.document.title.startswith("Inquiry into")
    assert inq.document.author != r.ids["stalin"]


def test_the_inquiry_is_signed_by_the_one_who_carried_it_out() -> None:
    r = stalin_rig()
    (inq,) = reports(inquiry(r, executor="shaposhnikov"))
    assert inq.document.author == r.ids["shaposhnikov"]


def test_with_no_executor_the_inquiry_is_signed_by_the_issuers_aide() -> None:
    r = stalin_rig()
    docs = inquiry(r)
    (inq,) = reports(docs)
    order = next(iter(r.state.routed.values()))
    author, _ = reporter(r.state, order, 0)
    assert author == r.ids["molotov"]
    assert inq.document.author == author
    (receipt,) = [d for d in docs if d.document.kind is not DocumentKind.REPORT]
    assert receipt.document.author == author
