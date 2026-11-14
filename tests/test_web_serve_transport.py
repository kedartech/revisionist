"""``web serve --transport``: ``claude`` builds the room exactly as before; ``openrouter``
shares one guarded transport and answers the aide from templates."""

from collections.abc import Iterator
from typing import Any

import pytest
from typer.testing import CliRunner

from revisionist import cli
from revisionist.engine import campaign as cmp
from revisionist.engine import openrouter
from revisionist.engine.llm import ClaudeCli, TransportError
from revisionist.engine.web import server

runner = CliRunner()


class Served:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}
        self.served = 0


class _Store:
    def close(self) -> None:
        return


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> Iterator[Served]:
    seen = Served()

    class App:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            seen.kwargs = kwargs

    def serve(app: Any, host: str, port: int) -> None:
        seen.served += 1

    monkeypatch.setattr(cli, "_pg_store", lambda *a: _Store())
    monkeypatch.setattr(server, "App", App)
    monkeypatch.setattr(server, "serve", serve)
    yield seen


def test_the_default_transport_is_the_claude_cli_as_before(served: Served) -> None:
    assert cli.transport_factory is cmp.live_transport
    for args in ([], ["--transport", "claude"]):
        result = runner.invoke(cli.app, ["web", "serve", *args])
        assert result.exit_code == 0, result.output
        made = served.kwargs["transport_factory"]()
        assert type(made) is ClaudeCli
        assert (made.binary, made.timeout_s) == ("claude", 300)
        assert served.kwargs["template_aide"] is False
        assert served.kwargs["offline_prose"] is False


def test_the_default_follows_a_swapped_transport_factory(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = object()
    monkeypatch.setattr(cli, "transport_factory", lambda: fake)
    assert runner.invoke(cli.app, ["web", "serve"]).exit_code == 0
    assert served.kwargs["transport_factory"]() is fake


def test_openrouter_shares_one_transport_and_uses_the_template_aide(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[object] = []
    monkeypatch.setenv(openrouter.KEY_ENV, "sk-test")
    monkeypatch.setattr(openrouter.OpenRouterTransport, "start", lambda self: started.append(self))
    result = runner.invoke(cli.app, ["web", "serve", "--transport", "openrouter"])
    assert result.exit_code == 0, result.output
    factory = served.kwargs["transport_factory"]
    first = factory()
    assert isinstance(first, openrouter.OpenRouterTransport) and factory() is first
    assert started == [first]
    assert served.kwargs["template_aide"] is True
    assert served.kwargs["offline_prose"] is False
    assert "sk-test" not in result.output


def test_openrouter_without_a_key_does_not_serve(served: Served) -> None:
    result = runner.invoke(cli.app, ["web", "serve", "--transport", "openrouter"])
    assert result.exit_code != 0 and openrouter.KEY_ENV in result.output
    assert served.served == 0


def test_openrouter_that_cannot_read_its_usage_does_not_serve(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(self: object) -> None:
        raise TransportError("openrouter: key usage could not be read")

    monkeypatch.setenv(openrouter.KEY_ENV, "sk-test")
    monkeypatch.setattr(openrouter.OpenRouterTransport, "start", down)
    result = runner.invoke(cli.app, ["web", "serve", "--transport", "openrouter"])
    assert result.exit_code != 0 and "usage" in result.output
    assert served.served == 0


def test_an_unknown_transport_is_refused(served: Served) -> None:
    result = runner.invoke(cli.app, ["web", "serve", "--transport", "gpt"])
    assert result.exit_code == 2 and served.served == 0
