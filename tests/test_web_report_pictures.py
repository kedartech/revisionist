"""A report carries its kind's picture (KPC): with ``kinds_in_battle`` on, a report that names a
kind of the world with a picture carries the picture's key, so the client draws only what the
report's mark carries. A report naming no kind, or a kind with no picture, carries none, and with
the switch off the report is sent as today. A wrong report is shaped as a right one.

Run: uv run pytest tests/test_web_report_pictures.py -q
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from revisionist.core.realism import kinds
from tests.test_battle_kinds import figures
from tests.test_odds import report, seen
from tests.test_web_piece_kinds import block, play


def reports(*changes: Any, kind: str | None = "levy", on: bool = True, tmp: Path) -> list[Any]:
    state = seen(play(tmp, *changes, on=on), report(kind=kind))
    return list(block(state)["map"]["reports"])


def test_a_report_naming_a_kind_carries_its_picture(tmp_path: Path) -> None:
    (r,) = reports(figures("levy", picture="infantry"), tmp=tmp_path)
    assert (r["kind"], r["picture"]) == ("levy", "infantry")
    assert r["picture"] in {p.value for p in kinds.Picture}


def test_a_report_naming_no_kind_carries_no_picture(tmp_path: Path) -> None:
    (r,) = reports(figures("levy", picture="infantry"), kind=None, tmp=tmp_path)
    assert r["kind"] is None
    assert "picture" not in r


def test_a_kind_with_no_picture_gives_the_report_none(tmp_path: Path) -> None:
    (r,) = reports(tmp=tmp_path)
    assert r["kind"] == "levy"
    assert "picture" not in r


def test_with_the_switch_off_a_report_is_sent_as_today(tmp_path: Path) -> None:
    (r,) = reports(figures("levy", picture="infantry"), on=False, tmp=tmp_path)
    assert "picture" not in r
