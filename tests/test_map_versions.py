"""Map versions kept for stored games (MAR): a game made on one map is served that map
after the world names a corrected one, and the objects are checked, copied, backed up
and restored with the database.

The backup scripts run here against stand-in ``pg_dump``, ``pg_restore`` and ``psql``
that copy a SQLite file, so no Postgres client tools are needed.
"""

import hashlib
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from revisionist import cli
from revisionist.core.ids import CampaignId
from revisionist.engine import campaign as cmp
from revisionist.engine import maps
from revisionist.engine.store import load_state
from revisionist.engine.web import map_api
from tests import test_adjacency_moves as adj
from tests import test_territory_model as tm

runner = CliRunner()
BACKUP = Path(__file__).resolve().parents[1] / "deploy" / "backup"


class Games:
    """A SQLite store holding one game on each of two versions of the toy map."""

    def __init__(self, tmp: Path, objects: Path) -> None:
        self.objects = objects
        self.db = tmp / "games.db"
        store = cmp.open_store(self.db)
        self.old = self.make(tmp / "h1", store, None)
        self.new = self.make(
            tmp / "h2", store, lambda b: b["areas"]["isle"].update(label=[251, 101])
        )
        self.h1 = self.sha(tmp / "h1")
        self.h2 = self.sha(tmp / "h2")

    @staticmethod
    def sha(folder: Path) -> str:
        return hashlib.sha256((folder / "toy.map.json").read_bytes()).hexdigest()

    def make(self, folder: Path, store: Any, edit: Any) -> CampaignId:
        folder.mkdir()
        world = tm.variant(folder, adj.with_rule, edit)
        assert world.map_data is not None
        sha = hashlib.sha256(world.map_data).hexdigest()
        (self.objects / f"{sha}.json").write_bytes(world.map_data)
        return cmp.new_campaign(store, world)

    def served(self, campaign: CampaignId) -> Any:
        store = cmp.open_store(self.db)
        return map_api.map_reply(load_state(store, campaign))


@pytest.fixture
def games(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Games:
    objects, named = tmp_path / "objects", tmp_path / "named"
    objects.mkdir()
    named.mkdir()
    monkeypatch.setenv(maps.OBJECTS_ENV, str(objects))
    monkeypatch.setattr(maps, "MAPS_DIR", named)
    monkeypatch.setenv("REVISIONIST_DB", str(tmp_path / "games.db"))
    made = Games(tmp_path, objects)
    (named / "toy.map.json").write_bytes((tmp_path / "h2" / "toy.map.json").read_bytes())
    return made


def run(*args: str) -> Any:
    return runner.invoke(cli.app, ["db", "map-objects", *args])


def test_each_game_is_served_the_map_it_was_made_on(games: Games) -> None:
    old, new = games.served(games.old), games.served(games.new)
    assert old["file"]["sha256"] == games.h1 and new["file"]["sha256"] == games.h2
    assert old["map"] != new["map"]
    assert old["map"]["areas"]["isle"]["label"] != [251, 101]
    assert new["map"]["areas"]["isle"]["label"] == [251, 101]


def test_verify_lists_each_hash_and_passes_with_both_objects(games: Games) -> None:
    out = run("verify")
    assert out.exit_code == 0, out.output
    for campaign, sha in ((games.old, games.h1), (games.new, games.h2)):
        assert any(campaign in line and sha in line for line in out.output.splitlines())


def test_verify_fails_naming_the_campaign_whose_object_is_missing(games: Games) -> None:
    (games.objects / f"{games.h1}.json").unlink()
    out = run("verify")
    assert out.exit_code != 0
    fail = [line for line in out.output.splitlines() if line.startswith("FAIL ")]
    assert len(fail) == 1 and games.old in fail[0] and games.new not in fail[0]
    assert games.served(games.old)["refused"] is True
    assert games.served(games.new)["refused"] is False


def test_verify_fails_for_an_object_whose_bytes_hash_differently(games: Games) -> None:
    (games.objects / f"{games.h1}.json").write_bytes(b'{"areas": {}}')
    out = run("verify")
    assert out.exit_code != 0 and games.old in out.output


def test_verify_takes_one_campaign(games: Games) -> None:
    (games.objects / f"{games.h1}.json").unlink()
    assert run("verify", "--campaign", games.new).exit_code == 0
    assert run("verify", "--campaign", games.old).exit_code != 0


def test_copy_restores_both_games_into_a_clean_directory(
    games: Games, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = {c: games.served(c) for c in (games.old, games.new)}
    clean = tmp_path / "clean"
    out = run("copy", "--to", str(clean))
    assert out.exit_code == 0, out.output
    assert sorted(p.name for p in clean.glob("*.json")) == sorted(
        f"{sha}.json" for sha in (games.h1, games.h2)
    )
    shutil.rmtree(games.objects)
    games.objects.mkdir()
    assert run("verify").exit_code != 0
    monkeypatch.setenv(maps.OBJECTS_ENV, str(clean))
    assert run("verify").exit_code == 0
    assert {c: games.served(c) for c in before} == before


def test_copy_fails_when_an_object_is_missing_or_corrupt(games: Games, tmp_path: Path) -> None:
    (games.objects / f"{games.h2}.json").write_bytes(b"{}")
    (games.objects / f"{games.h1}.json").unlink()
    out = run("copy", "--to", str(tmp_path / "clean"))
    assert out.exit_code != 0
    assert games.old in out.output and games.new in out.output
    assert not list((tmp_path / "clean").glob("*.json"))


def test_copy_never_changes_the_source(games: Games, tmp_path: Path) -> None:
    before = {p.name: p.read_bytes() for p in games.objects.iterdir()}
    assert run("copy", "--to", str(tmp_path / "clean")).exit_code == 0
    assert {p.name: p.read_bytes() for p in games.objects.iterdir()} == before


# --- the scripts ----------------------------------------------------------------------


def stand_ins(folder: Path) -> Path:
    """pg_dump, pg_restore and psql that copy a SQLite file named as the database."""
    folder.mkdir()
    py = "import sqlite3, sys; sqlite3.connect(sys.argv[1]).backup(sqlite3.connect(sys.argv[2]))"
    copy = f'"{sys.executable}" -c "{py}"'
    args = "for a; do case $a in"
    scripts = {
        "pg_dump": (
            f"{args} --file=*) f=${{a#--file=}};; --dbname=*) d=${{a#--dbname=}};; esac; done\n"
            f'{copy} "$d" "$f"\n'
        ),
        "pg_restore": (
            f"{args} --list) exit 0;; --dbname=*) d=${{a#--dbname=}};; *) f=$a;; esac; done\n"
            f'{copy} "$f" "$d"\n'
        ),
        "psql": "exit 0\n",
    }
    for name, body in scripts.items():
        path = folder / name
        path.write_text("#!/usr/bin/env bash\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return folder


def script(name: str, env: dict[str, str], tools: Path) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if not k.startswith("REVISIONIST_")}
    base["PATH"] = f"{tools}{os.pathsep}{base['PATH']}"
    return subprocess.run(
        [str(BACKUP / name)], env=base | env, capture_output=True, text=True, check=False
    )


@pytest.fixture
def box(games: Games, tmp_path: Path) -> dict[str, Any]:
    (tmp_path / "offbox").mkdir()
    return {
        "tools": stand_ins(tmp_path / "bin"),
        "dumps": tmp_path / "dumps",
        "offbox": tmp_path / "offbox",
        "env": {
            "REVISIONIST_ADMIN_DSN": str(tmp_path / "games.db"),
            "REVISIONIST_BACKUP_DIR": str(tmp_path / "dumps"),
            "REVISIONIST_BACKUP_DEST": str(tmp_path / "offbox"),
            "REVISIONIST_BIN": str(Path(sys.executable).parent / "revisionist"),
            maps.OBJECTS_ENV: str(games.objects),
        },
    }


def test_the_backup_copies_the_map_objects_beside_the_dumps_and_off_the_box(
    games: Games, box: dict[str, Any]
) -> None:
    done = script("revisionist-backup.sh", box["env"], box["tools"])
    assert done.returncode == 0, done.stderr
    names = sorted(f"{sha}.json" for sha in (games.h1, games.h2))
    assert sorted(p.name for p in (box["dumps"] / "map-objects").glob("*.json")) == names
    assert sorted(p.name for p in (box["offbox"] / "map-objects").glob("*.json")) == names


def test_the_backup_keeps_an_object_no_game_names_and_needs_no_database(
    games: Games, box: dict[str, Any]
) -> None:
    spare = b'{"areas": {}}'
    sha = hashlib.sha256(spare).hexdigest()
    (games.objects / f"{sha}.json").write_bytes(spare)
    box["env"]["REVISIONIST_ADMIN_DSN"] = str(box["dumps"].parent / "absent.db")
    dump = box["tools"] / "pg_dump"
    dump.write_text(
        '#!/usr/bin/env bash\nfor a; do case $a in --file=*) touch "${a#--file=}";; esac; done\n'
    )
    done = script("revisionist-backup.sh", box["env"], box["tools"])
    assert done.returncode == 0, done.stderr
    assert (box["dumps"] / "map-objects" / f"{sha}.json").read_bytes() == spare


def test_the_backup_fails_for_an_object_whose_bytes_do_not_hash_to_its_name(
    games: Games, box: dict[str, Any]
) -> None:
    (games.objects / f"{games.h1}.json").write_bytes(b"{}")
    done = script("revisionist-backup.sh", box["env"], box["tools"])
    assert done.returncode != 0 and games.h1 in done.stdout + done.stderr


def test_copy_all_refuses_a_campaign(games: Games, tmp_path: Path) -> None:
    out = run("copy", "--all", "--campaign", games.old, "--to", str(tmp_path / "x"))
    assert out.exit_code != 0 and not (tmp_path / "x").exists()


def test_the_drill_restores_the_objects_with_the_database_and_verifies_them(
    games: Games, box: dict[str, Any], tmp_path: Path
) -> None:
    assert script("revisionist-backup.sh", box["env"], box["tools"]).returncode == 0
    shutil.rmtree(games.objects)
    games.objects.mkdir()
    drill = script("revisionist-restore-drill.sh", box["env"], box["tools"])
    assert drill.returncode == 0, drill.stderr
    assert "restore drill passed" in drill.stdout
    assert games.h1 in drill.stdout and games.h2 in drill.stdout


def test_the_drill_fails_when_the_backup_holds_no_objects(
    games: Games, box: dict[str, Any]
) -> None:
    assert script("revisionist-backup.sh", box["env"], box["tools"]).returncode == 0
    shutil.rmtree(box["dumps"] / "map-objects")
    drill = script("revisionist-restore-drill.sh", box["env"], box["tools"])
    assert drill.returncode != 0 and "restore drill passed" not in drill.stdout


def test_the_drill_reads_no_object_from_the_live_directory(
    games: Games, box: dict[str, Any]
) -> None:
    assert script("revisionist-backup.sh", box["env"], box["tools"]).returncode == 0
    shutil.rmtree(box["dumps"] / "map-objects")
    assert (games.objects / f"{games.h1}.json").is_file()
    drill = script("revisionist-restore-drill.sh", box["env"], box["tools"])
    assert drill.returncode != 0
