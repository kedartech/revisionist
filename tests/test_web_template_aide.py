"""A room served with ``template_aide`` answers the aide's brief and help desk from
templates, while prose and options keep their transport."""

from typing import Any

from revisionist.engine.llm import TransportError
from tests.test_web import Client, Web, _florence, web  # noqa: F401
from tests.test_web_realism import Realism, post, solo  # noqa: F401


class Counting:
    def __init__(self) -> None:
        self.kinds: list[str] = []

    def call(self, request: Any) -> Any:
        self.kinds.append(request.call_class)
        raise TransportError("openrouter: aide calls are off on this instance")


def test_the_template_aide_briefs_and_helps_without_a_model_call(
    solo: tuple[Realism, Client],  # noqa: F811
) -> None:
    game, ada = solo
    app = game.web.app
    transport = Counting()
    app.transport_factory = lambda: transport
    app.offline_prose = False
    app.template_aide = True
    status, out = post(ada, "aide")
    assert status == 200 and out["refused"] is False, out
    assert out["brief"]["summary"]
    status, out = post(ada, "help", question="How do I raise money for the harbour?")
    assert status == 200 and out["refused"] is False, out
    assert out["help"][-1]["from"] == "aide" and out["help"][-1]["text"]
    assert "aide" not in transport.kinds


def test_without_the_template_aide_the_brief_goes_to_the_transport(
    solo: tuple[Realism, Client],  # noqa: F811
) -> None:
    game, ada = solo
    app = game.web.app
    transport = Counting()
    app.transport_factory = lambda: transport
    app.offline_prose = False
    status, out = post(ada, "aide")
    assert status == 200 and out["refused"] is True
    assert transport.kinds == ["aide"]
