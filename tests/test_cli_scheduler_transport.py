"""``scheduler run --transport``: ``claude`` ticks as before; ``openrouter`` builds its
transport as ``web serve`` does (one shared, guarded, free-models-only transport), so the
free instance never reaches for the ``claude`` CLI. Nothing is called: ``sch.run`` and the
store are stubs, or the tick runs on a memory store with a recording fake transport."""

import configparser
import shlex
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from revisionist import cli
from revisionist.engine import campaign as cmp
from revisionist.engine import openrouter
from revisionist.engine import scheduler as sch
from revisionist.engine.llm import ClaudeCli, Reply, Request, TransportError
from revisionist.engine.store import MemoryStore
from tests.test_engine_v2_wake import CAMPAIGN, T0, Table

runner = CliRunner()
ENV = "REVISIONIST_SCHEDULER_TRANSPORT"


class Ran:
    """What ``scheduler run`` handed to ``sch.run``, and how the store was treated."""

    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}
        self.runs = 0
        self.closed = 0


class _Store:
    def __init__(self, seen: Ran) -> None:
        self.seen = seen

    def close(self) -> None:
        self.seen.closed += 1


@pytest.fixture
def ran(monkeypatch: pytest.MonkeyPatch) -> Iterator[Ran]:
    seen = Ran()

    def fake_run(store: object, clock: object, **kwargs: Any) -> list[sch.Outcome]:
        seen.runs += 1
        seen.kwargs = kwargs
        return []

    monkeypatch.delenv(ENV, raising=False)
    monkeypatch.delenv(openrouter.KEY_ENV, raising=False)
    monkeypatch.setattr(cli, "_pg_store", lambda *a: _Store(seen))
    monkeypatch.setattr(sch, "run", fake_run)
    yield seen


@pytest.fixture
def no_claude(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """``cli.transport_factory`` is the Claude CLI's; any call to it is a failure."""
    calls: list[str] = []

    def claude() -> ClaudeCli:
        calls.append("claude")
        raise AssertionError("the claude transport was built")

    monkeypatch.setattr(cli, "transport_factory", claude)
    return calls


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    seen: list[object] = []
    monkeypatch.setenv(openrouter.KEY_ENV, "sk-test")
    monkeypatch.setattr(openrouter.OpenRouterTransport, "start", lambda self: seen.append(self))
    return seen


def test_the_default_transport_is_the_claude_cli_as_before(ran: Ran) -> None:
    assert cli.transport_factory is cmp.live_transport
    for args in ([], ["--transport", "claude"]):
        result = runner.invoke(cli.app, ["scheduler", "run", *args])
        assert result.exit_code == 0, result.output
        made = ran.kwargs["transport_factory"]()
        assert type(made) is ClaudeCli
        assert ran.kwargs["offline"] is False


def test_the_default_follows_a_swapped_transport_factory(
    ran: Ran, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = object()
    monkeypatch.setattr(cli, "transport_factory", lambda: fake)
    assert runner.invoke(cli.app, ["scheduler", "run"]).exit_code == 0
    assert ran.kwargs["transport_factory"]() is fake


def test_openrouter_shares_one_guarded_transport_and_builds_no_claude(
    ran: Ran, started: list[object], no_claude: list[str]
) -> None:
    result = runner.invoke(cli.app, ["scheduler", "run", "--transport", "openrouter"])
    assert result.exit_code == 0, result.output
    factory = ran.kwargs["transport_factory"]
    first = factory()
    assert isinstance(first, openrouter.OpenRouterTransport) and factory() is first
    assert started == [first]
    assert no_claude == []
    assert "sk-test" not in result.output
    assert ran.closed == 1


def test_the_instance_names_its_transport_in_its_env(
    ran: Ran, started: list[object], no_claude: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV, "openrouter")
    assert runner.invoke(cli.app, ["scheduler", "run"]).exit_code == 0
    assert isinstance(ran.kwargs["transport_factory"](), openrouter.OpenRouterTransport)
    assert no_claude == []


def test_the_flag_beats_the_env(ran: Ran, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV, "openrouter")
    assert runner.invoke(cli.app, ["scheduler", "run", "--transport", "claude"]).exit_code == 0
    assert type(ran.kwargs["transport_factory"]()) is ClaudeCli


def test_an_unknown_transport_is_refused(ran: Ran, monkeypatch: pytest.MonkeyPatch) -> None:
    result = runner.invoke(cli.app, ["scheduler", "run", "--transport", "gpt"])
    assert result.exit_code == 2 and ran.runs == 0
    monkeypatch.setenv(ENV, "gpt")
    result = runner.invoke(cli.app, ["scheduler", "run"])
    assert result.exit_code == 2 and ran.runs == 0


def test_openrouter_without_a_key_ticks_nothing(ran: Ran, no_claude: list[str]) -> None:
    result = runner.invoke(cli.app, ["scheduler", "run", "--transport", "openrouter"])
    assert result.exit_code != 0 and openrouter.KEY_ENV in result.output
    assert ran.runs == 0 and no_claude == [] and ran.closed == 1


def test_openrouter_that_cannot_read_its_usage_ticks_nothing(
    ran: Ran, monkeypatch: pytest.MonkeyPatch, no_claude: list[str]
) -> None:
    def down(self: object) -> None:
        raise TransportError("openrouter: key usage could not be read")

    monkeypatch.setenv(openrouter.KEY_ENV, "sk-test")
    monkeypatch.setattr(openrouter.OpenRouterTransport, "start", down)
    result = runner.invoke(cli.app, ["scheduler", "run", "--transport", "openrouter"])
    assert result.exit_code != 0 and "usage" in result.output
    assert ran.runs == 0 and no_claude == [] and ran.closed == 1


def test_an_offline_run_builds_no_transport_at_all(ran: Ran, no_claude: list[str]) -> None:
    result = runner.invoke(cli.app, ["scheduler", "run", "--transport", "openrouter", "--offline"])
    assert result.exit_code == 0, result.output  # no key needed: nothing is called
    assert ran.kwargs["offline"] is True and no_claude == []


# --- the tick itself, on the free transport ------------------------------------------------


class Recorder:
    """Stands in for the shared OpenRouter transport: records each call, answers nothing."""

    def __init__(self) -> None:
        self.classes: list[str] = []

    def start(self) -> None:
        return

    def call(self, request: Request) -> Reply:
        self.classes.append(request.call_class)
        raise TransportError("recorded")


def test_a_deadline_close_on_the_free_instance_calls_only_the_shared_transport(
    ran: Ran, monkeypatch: pytest.MonkeyPatch, no_claude: list[str], tmp_path: Path
) -> None:
    """A wake that closes with nobody there: the aide plays and the next wake opens, and
    every model call goes to the one free transport, none to the Claude CLI."""
    from revisionist.engine import runner as engine_runner

    shared = Recorder()
    monkeypatch.setattr(openrouter.OpenRouterTransport, "from_env", lambda *a, **k: shared)
    table = Table(MemoryStore())
    engine_runner.play_tick(
        table.store,
        CAMPAIGN,
        offline=True,
        transport_factory=cmp.live_transport,
        briefings=tmp_path,
        warn=lambda _m: None,
        now=T0,
    )
    assert runner.invoke(cli.app, ["scheduler", "run", "--transport", "openrouter"]).exit_code == 0
    factory: Callable[[], Any] = ran.kwargs["transport_factory"]
    engine_runner.play_tick(
        table.store,
        CAMPAIGN,
        offline=False,
        transport_factory=factory,
        briefings=tmp_path,
        warn=lambda _m: None,
        now=T0 + timedelta(hours=12),
    )
    assert no_claude == []
    assert "options" in shared.classes, "the aide and the next offers asked the free transport"
    assert set(shared.classes) <= set(openrouter.DEFAULT_MODELS) | {"aide", "estimator"}
    state = table.state
    assert state.wake is not None and state.wake.number == 1 and not state.wake.closed


# --- the templated unit pair ---------------------------------------------------------------

UNITS = Path(__file__).resolve().parents[1] / "deploy" / "systemd"


def _unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read_string((UNITS / name).read_text())
    return parser


def test_the_service_template_reads_the_instances_own_env_and_runs_the_scheduler() -> None:
    service = _unit("revisionist-scheduler@.service")["Service"]
    assert service["EnvironmentFile"] == "%h/.config/revisionist/%i.env"  # required: no `-`
    argv = shlex.split(service["ExecStart"].replace("%h", "/home/u"))
    assert Path(argv[0]).name == "revisionist" and argv[1:] == ["scheduler", "run"]
    assert runner.invoke(cli.app, [*argv[1:], "--help"]).exit_code == 0
    assert (
        service["Type"] == "oneshot"
        and "%i" in _unit("revisionist-scheduler@.service")["Unit"]["Description"]
    )


def test_the_service_template_keeps_the_hardening_of_the_single_unit() -> None:
    template = _unit("revisionist-scheduler@.service")["Service"]
    single = _unit("revisionist-scheduler.service")["Service"]
    keys = [k for k in single if k not in {"EnvironmentFile", "ExecStart", "Environment"}]
    assert {k: template[k] for k in keys} == {k: single[k] for k in keys}
    assert template["Environment"] == single["Environment"]


def test_the_timer_template_starts_the_service_of_its_own_instance() -> None:
    timer = _unit("revisionist-scheduler@.timer")["Timer"]
    assert timer["OnCalendar"] == "*:0/10" and timer["Persistent"] == "true"
    assert timer["Unit"] == "revisionist-scheduler@%i.service"
    assert _unit("revisionist-scheduler@.timer")["Install"]["WantedBy"] == "timers.target"


def test_the_help_names_the_setting_the_env_files_use() -> None:
    result = runner.invoke(cli.app, ["scheduler", "run", "--help"], terminal_width=200)
    assert ENV in result.output
