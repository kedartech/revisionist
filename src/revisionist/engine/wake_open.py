"""What runs right after a wake opens.

``runner.play_tick`` calls ``before_offers`` as soon as the tick has opened the next
wake, then makes that wake's offers, then calls ``after_open``; so the web's commit and
close, the scheduler's deadline close and the CLI tick all reach both. Wake 0 opens at
the begin, with everyone present, and runs neither.
"""

import logging

from revisionist.core.ids import CampaignId
from revisionist.engine.notice import Notifier
from revisionist.engine.store import EventStore
from revisionist.engine.web import held

log = logging.getLogger(__name__)


def before_offers(store: EventStore, campaign_id: CampaignId, wake: int) -> None:
    """File the orders seats gave after committing an earlier wake, in the order given,
    so the offers are made from the desk as it stands. A failure is logged and never
    stops the tick: the wake is already open."""
    try:
        held.file_held(store, campaign_id, wake)
    except Exception:
        log.exception("held orders for wake %s of %s were not filed", wake, campaign_id)


def after_open(
    store: EventStore, campaign_id: CampaignId, wake: int, *, notifier: Notifier | None
) -> None:
    """Send each human seat its notice for ``wake``. A notice that fails is logged and
    never stops the tick: the wake is already open."""
    if notifier is None or wake == 0:
        return
    try:
        notifier.wake_opened(store, campaign_id, wake)
    except Exception:
        log.exception("notices for wake %s of %s were not sent", wake, campaign_id)


__all__ = ["after_open", "before_offers"]
