"""Secrets are checked when the server starts and never reach the log.

Every secret here is a made-up value. No key, password or ``.env`` file is read.
"""

import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from revisionist import cli
from revisionist.engine import campaign as cmp
from revisionist.engine import openrouter, seal
from revisionist.engine.llm import TransportError
from revisionist.engine.web import map_api, server
from tests.test_web import PASSWORD, Web, web  # noqa: F401

runner = CliRunner()

MASTER = "REVISIONIST_MASTER_KEY_FILE"
MARK = "REVISIONIST_MARK_SECRET"
FAKE_KEY = "sk-or-made-up-0123456789abcdef"
FAKE_DB_SECRET = "hunter2-made-up"


def _key_file(tmp_path: Path, mode: int) -> Path:
    path = tmp_path / "master.key"
    seal.new_master_key(path)
    path.chmod(mode)
    return path


def test_a_master_key_others_can_read_is_refused(tmp_path: Path) -> None:
    path = _key_file(tmp_path, 0o640)
    problems = cmp.secret_problems({MASTER: str(path)}, free_transport=False)
    assert problems and MASTER in problems[0]
    assert "readable by others" in problems[0]


def test_a_master_key_only_its_owner_can_read_passes(tmp_path: Path) -> None:
    path = _key_file(tmp_path, 0o600)
    assert cmp.secret_problems({MASTER: str(path)}, free_transport=False) == []


def test_no_master_key_set_is_not_a_problem() -> None:
    assert cmp.secret_problems({}, free_transport=False) == []


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://rv@db.example.net/rv",
        "postgresql://rv:@db.example.net:5432/rv",
        "postgres://rv@10.0.0.7/rv?sslmode=require",
    ],
)
def test_an_empty_database_password_off_localhost_is_refused(dsn: str) -> None:
    problems = cmp.secret_problems({"REVISIONIST_DB": dsn}, free_transport=False)
    assert problems and "REVISIONIST_DB" in problems[0]
    assert "db.example.net" not in problems[0] and "10.0.0.7" not in problems[0]


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://rv@localhost/rv",
        "postgresql://rv@127.0.0.1:5432/rv",
        "postgresql://rv@[::1]/rv",
        "postgresql://rv@/rv?host=/var/run/postgresql",
        f"postgresql://rv:{FAKE_DB_SECRET}@db.example.net/rv",
        "revisionist.db",
    ],
)
def test_a_local_or_passworded_database_passes(dsn: str) -> None:
    assert cmp.secret_problems({"REVISIONIST_DB": dsn}, free_transport=False) == []


def test_the_free_transport_with_no_key_is_refused() -> None:
    for environ in ({}, {openrouter.KEY_ENV: ""}, {openrouter.KEY_ENV: "  "}):
        problems = cmp.secret_problems(environ, free_transport=True)
        assert problems and openrouter.KEY_ENV in problems[0]
    assert cmp.secret_problems({openrouter.KEY_ENV: FAKE_KEY}, free_transport=True) == []
    assert cmp.secret_problems({}, free_transport=False) == []


def test_a_refusal_names_the_setting_and_never_its_value(tmp_path: Path) -> None:
    path = _key_file(tmp_path, 0o644)
    environ = {
        MASTER: str(path),
        "REVISIONIST_DB": "postgresql://rv:@db.example.net/rv",
        openrouter.KEY_ENV: " ",
    }
    text = "\n".join(cmp.secret_problems(environ, free_transport=True))
    assert MASTER in text and "REVISIONIST_DB" in text and openrouter.KEY_ENV in text
    assert str(path) not in text


def test_web_serve_refuses_before_it_opens_anything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _key_file(tmp_path, 0o644)
    monkeypatch.setenv(MASTER, str(path))
    opened: list[str] = []
    monkeypatch.setattr(cli, "_pg_store", lambda *a, **k: opened.append("store"))
    result = runner.invoke(cli.app, ["web", "serve", "--static", str(tmp_path)])
    assert result.exit_code == cli.EXIT_REFUSED
    assert MASTER in result.output and str(path) not in result.output
    assert opened == []


def test_web_serve_refuses_the_free_transport_with_no_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(openrouter.KEY_ENV, raising=False)
    monkeypatch.delenv(MASTER, raising=False)
    monkeypatch.setenv("REVISIONIST_DB", "revisionist.db")
    monkeypatch.setattr(cli, "_pg_store", lambda *a, **k: pytest.fail("opened the store"))
    result = runner.invoke(
        cli.app, ["web", "serve", "--static", str(tmp_path), "--transport", "openrouter"]
    )
    assert result.exit_code == cli.EXIT_REFUSED
    assert openrouter.KEY_ENV in result.output


def test_the_mark_secret_check_stays(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MARK, raising=False)
    with pytest.raises(ValueError, match=MARK):
        map_api.mark_secret()


# --- rule 2: the log -------------------------------------------------------------


class _Down:
    """A urlopen that fails with a message that quotes the request, key included."""

    def __call__(self, req: Any, timeout: float = 0) -> Any:
        auth = req.get_header("Authorization")
        raise urllib.error.URLError(f"cannot reach host with {auth}")


def test_a_scripted_session_writes_no_secret_to_the_log(
    web: Web,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mark = "ab" * 32
    monkeypatch.setenv(MARK, mark)
    caplog.set_level(logging.DEBUG)
    wrong = "a wrong passphrase 987"
    c, codes = web.signed_up("lorenzo")
    token = c.cookie
    assert c.call("/api/signin", {"handle": "lorenzo", "password": wrong})[0] == 401
    assert c.call("/api/signin", {"handle": "lorenzo", "password": PASSWORD})[0] == 200
    sign_in_token = c.cookie
    assert (
        c.call("/api/recover", {"handle": "lorenzo", "code": "nope", "password": wrong})[0] >= 400
    )
    assert c.call("/api/realism/nothing", {"campaign": "x"})[0] >= 400
    # A model call that fails, through the real free transport and the server's own words.
    monkeypatch.setattr(urllib.request, "urlopen", _Down())
    shared = openrouter.OpenRouterTransport(FAKE_KEY)
    with pytest.raises(TransportError) as failed:
        shared.start()
    server.model_down(failed.value)
    secrets_ = [PASSWORD, wrong, token, sign_in_token, FAKE_KEY, mark, *codes]
    logged = "\n".join(r.getMessage() for r in caplog.records)
    logged += "\n".join(str(r.exc_text or "") for r in caplog.records)
    assert logged
    for secret in secrets_:
        assert secret and secret not in logged, "a secret reached the log"
    assert os.environ[MARK] == mark
