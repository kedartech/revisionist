"""A superior's answer to an incident is his sealed choice until the due day (DFY).

The commander's view and feed read the same whether his superior is a person who answers
early or code that answers for him on the day: the answer lands at the same moment, and
nothing shown says who gave it. The world is ``tests/test_defiance.py``'s: Kara sends her
march to the Isle anyway, Olav carries it out, and Ilse is the superior who answers.
"""

from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, apply
from revisionist.core.ids import EventId, derived_id
from revisionist.core.project import project
from revisionist.core.realism import defiance
from revisionist.core.realism.defiance import Verdict
from revisionist.core.visibility import Visibility
from revisionist.engine import catchup, realism_tick
from revisionist.engine.store import MemoryStore, load_state
from tests.fog_twins import drawn_from
from tests.test_defiance import sent_and_carried
from tests.test_realism_locks import ILSE, KARA, OLAF, logged, seat
from tests.test_territory_model import CAMPAIGN


def _reads(store: MemoryStore) -> tuple[str, list[Any]]:
    """Kara's view as a model is given it, and every event her catch-up feeds her."""
    state = load_state(store, CAMPAIGN)
    fed = catchup.seat_events(store, CAMPAIGN, seat(KARA), 0, 999)
    return (
        project(state, seat(KARA)).model_dump_json(),
        [(f.wake, f.event.kind, f.event.payload.model_dump(mode="json")) for f in fed],
    )


def _game(tmp: Path, early: Verdict | None) -> list[tuple[str, list[Any]]]:
    """Kara's reads at each wake from the incident's opening until a wake after its answer
    lands, with Ilse answering ``early`` on the opening day, or silent."""
    with drawn_from(Counter()):
        store, incident = sent_and_carried(tmp)
        if early is not None:
            realism_tick.answer_incident(
                store, CAMPAIGN, seat(ILSE), incident.incident_id, early.value
            )
        seen = [_reads(store)]
        for _ in range(6):
            realism_tick.run_realism_tick(store, CAMPAIGN)
            seen.append(_reads(store))
            if load_state(store, CAMPAIGN).incidents[incident.incident_id].verdict is not None:
                break
        realism_tick.run_realism_tick(store, CAMPAIGN)
        seen.append(_reads(store))
    assert load_state(store, CAMPAIGN).incidents[incident.incident_id].verdict is not None
    return seen


def _card(tmp: Path) -> Verdict:
    with drawn_from(Counter()):
        store, incident = sent_and_carried(tmp)
    return defiance.card_verdict(load_state(store, CAMPAIGN), incident)


def test_the_commander_reads_the_same_whether_a_person_or_code_answers(tmp_path: Path) -> None:
    verdict = _card(tmp_path / "probe")
    person = _game(tmp_path / "person", verdict)
    code = _game(tmp_path / "code", None)
    assert len(person) == len(code)
    for n, (a, b) in enumerate(zip(person, code, strict=True)):
        assert a[0] == b[0], f"view differs at read {n}"
        assert a[1] == b[1], f"feed differs at read {n}"


def test_an_early_answer_lands_on_the_due_day_with_the_superiors_verdict(tmp_path: Path) -> None:
    store, incident = sent_and_carried(tmp_path)
    other = next(
        v for v in Verdict if v is not defiance.card_verdict(load_state(store, CAMPAIGN), incident)
    )
    filed = realism_tick.answer_incident(
        store, CAMPAIGN, seat(ILSE), incident.incident_id, other.value
    )
    assert isinstance(filed, ev.IncidentChoiceFiled) and filed.verdict is other
    state = load_state(store, CAMPAIGN)
    assert state.incidents[incident.incident_id].verdict is None
    assert not logged(store, ev.IncidentAnswered)
    for _ in range(6):
        realism_tick.run_realism_tick(store, CAMPAIGN)
        state = load_state(store, CAMPAIGN)
        if state.incidents[incident.incident_id].verdict is not None:
            break
    done = state.incidents[incident.incident_id]
    assert done.verdict is other and done.answered is not None and done.answered > incident.due
    (answered,) = logged(store, ev.IncidentAnswered)
    assert answered.verdict is other and not answered.by_card
    assert incident.incident_id not in state.incident_choices


def test_a_later_choice_before_the_day_replaces_the_first(tmp_path: Path) -> None:
    store, incident = sent_and_carried(tmp_path)
    for verdict in (Verdict.DISMISSED, Verdict.BACKED):
        realism_tick.answer_incident(
            store, CAMPAIGN, seat(ILSE), incident.incident_id, verdict.value
        )
    state = load_state(store, CAMPAIGN)
    assert state.incident_choices == {incident.incident_id: Verdict.BACKED}


def test_the_choice_is_sealed_to_the_superior_and_never_fed(tmp_path: Path) -> None:
    store, incident = sent_and_carried(tmp_path)
    realism_tick.answer_incident(store, CAMPAIGN, seat(ILSE), incident.incident_id, "backed")
    (filed,) = [e for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.IncidentChoiceFiled)]
    assert filed.scope.visibility is Visibility.PRIVATE
    assert filed.scope.known_by == frozenset({seat(ILSE)})
    assert "incident_choice_filed" in catchup.NEVER
    for person in (ILSE, KARA, OLAF):
        kinds = {f.event.kind for f in catchup.seat_events(store, CAMPAIGN, seat(person), 0, 999)}
        assert "incident_choice_filed" not in kinds


def test_who_answered_is_kept_from_every_seats_view(tmp_path: Path) -> None:
    store, incident = sent_and_carried(tmp_path)
    for _ in range(6):
        realism_tick.run_realism_tick(store, CAMPAIGN)
        if load_state(store, CAMPAIGN).incidents[incident.incident_id].verdict is not None:
            break
    state = load_state(store, CAMPAIGN)
    assert state.incidents[incident.incident_id].by_card
    for person in (ILSE, KARA):
        shown = project(state, seat(person)).incidents[incident.incident_id]
        assert shown.verdict is not None and not shown.by_card
        for f in catchup.seat_events(store, CAMPAIGN, seat(person), 0, 999):
            if isinstance(f.event.payload, ev.IncidentAnswered):
                assert not f.event.payload.by_card


def _filed(store: MemoryStore, payload: ev.Payload) -> Any:
    last = list(store.read(CAMPAIGN))[-1]
    seq = last.seq + 1
    event_id = EventId(derived_id(CAMPAIGN, "test", str(seq)))
    return last.model_copy(update={"payload": payload, "seq": seq, "event_id": event_id})


def test_the_log_takes_a_choice_only_from_the_superiors_seat_on_an_open_incident(
    tmp_path: Path,
) -> None:
    store, incident = sent_and_carried(tmp_path)
    state = load_state(store, CAMPAIGN)
    day = incident.opened

    def choice(who: Any, on: Any = day, iid: str = incident.incident_id) -> ev.IncidentChoiceFiled:
        return ev.IncidentChoiceFiled(
            incident_id=iid, seat_id=seat(who), verdict=Verdict.BACKED, on=on
        )

    assert apply(state, _filed(store, choice(ILSE))).incident_choices == {
        incident.incident_id: Verdict.BACKED
    }
    with pytest.raises(FoldError):
        apply(state, _filed(store, choice(KARA)))
    with pytest.raises(FoldError):
        apply(state, _filed(store, choice(ILSE, on=day - timedelta(days=1))))
    with pytest.raises(FoldError):
        apply(state, _filed(store, choice(ILSE, iid="no-such-incident")))
    answered = state.model_copy(
        update={
            "incidents": {
                incident.incident_id: incident.model_copy(update={"verdict": Verdict.BACKED})
            }
        }
    )
    with pytest.raises(FoldError):
        apply(answered, _filed(store, choice(ILSE)))
    with pytest.raises(FoldError):
        apply(state.model_copy(update={"rules": frozenset()}), _filed(store, choice(ILSE)))
