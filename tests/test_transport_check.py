"""``web check-transport``: one fixed text to each free model, every word must come back.

A fake transport stands in for the models; the guarded transport runs against the
fake HTTP layer of ``test_openrouter``. No network, no key.
"""

import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from typer.testing import CliRunner

from revisionist import cli
from revisionist.engine import openrouter as orr
from revisionist.engine import transport_check as tc
from revisionist.engine.llm import Reply, Request, TransportError
from revisionist.engine.openrouter import DOTS, ERNIE, FLINT
from tests.test_openrouter import Clock, Script, says
from tests.test_openrouter import Fake as HttpFake

runner = CliRunner()
IDS = ["a/one:free", "b/two:free", "c/three:free"]


def same(text: str) -> str:
    return text


def labelled(text: str) -> str:
    return text.replace("Smolensk", "[ADDRESS]")


def dashed(text: str) -> str:
    for place in tc.PLACES:
        text = text.replace(place, "")
    return text


class Models:
    """Answers each request by model id: a rewrite of the text it was sent, or an error."""

    def __init__(self, answers: dict[str, Callable[[str], str] | Exception] | None = None) -> None:
        self.answers = answers or {}
        self.requests: list[Request] = []

    def call(self, request: Request) -> Reply:
        self.requests.append(request)
        answer = self.answers.get(request.model, same)
        if isinstance(answer, Exception):
            raise answer
        assert tc.TEXT in request.prompt
        return Reply({"echo": answer(tc.TEXT)}, request.model, 10, 10, 0, 0.0)


def verdicts(models: Models) -> tuple[int, list[tc.Verdict], str]:
    found = tc.run(models, IDS)
    return tc.exit_code(found), found, "\n".join(tc.report(found))


def test_the_text_holds_places_names_a_date_and_a_number() -> None:
    for word in (*tc.PLACES, *tc.PEOPLE, tc.DATE, tc.NUMBER):
        assert word in tc.TEXT and word in tc.WORDS
    assert len(tc.PLACES) >= 3 and len(tc.PEOPLE) >= 2


def test_every_word_back_from_every_model_is_exit_0() -> None:
    models = Models()
    code, found, _ = verdicts(models)
    assert code == 0
    assert [r.model for r in models.requests] == IDS
    assert len({r.call_class for r in models.requests}) == 3
    assert [v.model for v in found] == IDS and not any(v.lost or v.error for v in found)


def test_a_label_in_place_of_a_word_is_exit_1_and_names_model_and_word() -> None:
    code, found, text = verdicts(Models({IDS[1]: labelled}))
    assert code == 1
    assert found[1].lost == ("Smolensk",) and found[1].labels == ("[ADDRESS]",)
    assert IDS[1] in text and "Smolensk" in text and "guardrail" in text
    assert not found[0].lost and not found[2].lost


def test_dashes_and_no_label_is_exit_1() -> None:
    code, found, text = verdicts(Models({IDS[0]: dashed}))
    assert code == 1
    assert found[0].lost == tc.PLACES and found[0].labels == ()
    assert all(p in text for p in tc.PLACES) and "guardrail" in text


def test_one_model_unreachable_is_exit_2() -> None:
    down = TransportError("openrouter: no free model answered (check_3)")
    code, found, text = verdicts(Models({IDS[2]: down}))
    assert code == 2
    assert found[2].error and not found[2].lost
    assert IDS[2] in text and "no verdict" in text


def test_a_reply_without_the_echo_is_no_verdict() -> None:
    class Empty(Models):
        def call(self, request: Request) -> Reply:
            return Reply({"text": "ok"}, request.model, 1, 1, 0, 0.0)

    code, found, _ = verdicts(Empty())
    assert code == 2 and all(v.error for v in found)


def test_a_lost_word_outweighs_an_unreachable_model() -> None:
    down = TransportError("openrouter: no free model answered (check_3)")
    code, _, _ = verdicts(Models({IDS[0]: dashed, IDS[2]: down}))
    assert code == 1


def test_one_of_two_copies_of_a_word_lost_is_exit_1() -> None:
    assert tc.TEXT.count("Smolensk") == 2
    code, found, _ = verdicts(Models({IDS[0]: lambda t: t.replace("Smolensk", "", 1)}))
    assert code == 1 and found[0].lost == ("Smolensk",)


def test_an_empty_routing_table_is_no_verdict() -> None:
    models = Models()
    found = tc.run(models, [])
    assert tc.exit_code(found) == 2 and models.requests == []
    assert "no model" in "\n".join(tc.report(found))


# --- through the guarded transport ---------------------------------------------------


@pytest.fixture
def http() -> Iterator[tuple[HttpFake, Script]]:
    script = Script()
    fake = HttpFake(script)
    yield fake, script
    fake.close()


@pytest.fixture
def unlogged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orr, "_labels_logged", set(), raising=False)


def guarded(fake: HttpFake, environ: dict[str, str] | None = None) -> tuple[Any, list[str]]:
    clock = Clock()
    env = {orr.KEY_ENV: "test-key-SENTINEL"} | (environ or {})
    return tc.openrouter(env, base=fake.base, clock=clock.mono, now=clock.now, sleep=clock.sleep)


def test_each_model_in_the_routing_table_is_asked_once_through_the_guarded_transport(
    http: tuple[HttpFake, Script],
) -> None:
    fake, script = http
    for model in (ERNIE, FLINT, DOTS):
        script.chat[model] = [says({"echo": tc.TEXT})]
    transport, ids = guarded(fake)
    assert isinstance(transport, orr.OpenRouterTransport)
    assert ids == [ERNIE, FLINT, DOTS]
    assert tc.exit_code(tc.run(transport, ids)) == 0
    assert [p["model"] for p in script.posts] == [ERNIE, FLINT, DOTS]
    assert all(tc.TEXT in p["messages"][1]["content"] for p in script.posts)


def test_the_routing_table_follows_the_instance_models_setting(
    http: tuple[HttpFake, Script],
) -> None:
    fake, _ = http
    only = {"prose": [DOTS], "counsel": [], "options": [DOTS], "estimator": []}
    _, ids = guarded(fake, {orr.MODELS_ENV: json.dumps(only)})
    assert ids == [DOTS]


def test_a_reply_the_guarded_transport_refuses_for_a_label_is_exit_1(
    http: tuple[HttpFake, Script], unlogged: None
) -> None:
    fake, script = http
    script.chat[ERNIE] = [says({"echo": labelled(tc.TEXT)})]
    script.chat[FLINT] = [says({"echo": tc.TEXT})]
    script.chat[DOTS] = [says({"echo": tc.TEXT})]
    transport, ids = guarded(fake)
    found = tc.run(transport, ids)
    assert tc.exit_code(found) == 1
    assert found[0].labels == ("[ADDRESS]",) and not found[0].error
    assert [p["model"] for p in script.posts] == [ERNIE, FLINT, DOTS]


# --- the command ---------------------------------------------------------------------


def command(monkeypatch: pytest.MonkeyPatch, models: Models, *args: str) -> tuple[int, str, Models]:
    monkeypatch.setattr(tc, "openrouter", lambda *a, **k: (models, IDS))
    result = runner.invoke(cli.app, ["web", "check-transport", *args])
    return result.exit_code, result.output, models


@pytest.mark.parametrize(
    ("answers", "code"),
    [({}, 0), ({IDS[1]: labelled}, 1), ({IDS[0]: dashed}, 1), ({IDS[2]: TransportError("x")}, 2)],
)
def test_the_command_prints_a_line_a_model_and_exits_with_the_verdict(
    monkeypatch: pytest.MonkeyPatch, answers: dict[str, Any], code: int
) -> None:
    got, out, models = command(monkeypatch, Models(answers), "--transport", "openrouter")
    assert got == code, out
    assert len(models.requests) == 3
    assert all(model in out for model in IDS)


def test_the_command_without_a_key_makes_no_call_and_gives_no_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(orr.KEY_ENV, raising=False)
    monkeypatch.delenv(orr.MODELS_ENV, raising=False)
    result = runner.invoke(cli.app, ["web", "check-transport", "--transport", "openrouter"])
    assert result.exit_code == 2 and orr.KEY_ENV in result.output


def test_the_command_checks_the_openrouter_transport_only(monkeypatch: pytest.MonkeyPatch) -> None:
    got, out, models = command(monkeypatch, Models(), "--transport", "claude")
    assert got == 2 and "openrouter" in out
    assert models.requests == []
