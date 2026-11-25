"""The CI shard split: every test file in exactly one shard, in a stable order."""

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_shard.py"


def shard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_shard", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree(root: Path, *names: str) -> Path:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    return root


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, list[str]]:
    code = shard().main(list(args))
    return code, capsys.readouterr().out.split()


@pytest.mark.parametrize("total", [1, 2, 3, 4, 5, 8])
def test_every_repo_test_file_lands_in_exactly_one_shard(total: int) -> None:
    m = shard()
    files = m.test_files(ROOT)
    shards = m.split(files, m.load_timings(m.TIMINGS), total)
    flat = [f for s in shards for f in s]
    assert len(shards) == total
    assert sorted(flat) == files
    assert len(flat) == len(set(flat))
    assert "tests/test_ci_shard.py" in files
    assert all(s for s in shards)


def test_the_recorded_times_cover_most_of_the_repo_test_files() -> None:
    m = shard()
    files = m.test_files(ROOT)
    timed = [f for f in files if f in m.load_timings(m.TIMINGS)]
    assert len(timed) * 4 >= len(files) * 3, f"{len(timed)} of {len(files)} test files have a time"


def test_the_files_are_the_ones_pytest_collects(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        "tests/test_a.py",
        "tests/b_test.py",
        "tests/sub/test_c.py",
        "tests/conftest.py",
        "tests/handwritten.py",
        "tests/recordings/test_data.json",
        "src/test_not_here.py",
    )
    assert shard().test_files(root) == ["tests/b_test.py", "tests/sub/test_c.py", "tests/test_a.py"]


def test_the_split_is_stable_and_each_shard_is_sorted() -> None:
    m = shard()
    files = [f"tests/test_{i:02}.py" for i in range(20)]
    timings = {f: float(i % 7) for i, f in enumerate(files)}
    first = m.split(files, timings, 4)
    assert m.split(list(reversed(files)), dict(reversed(timings.items())), 4) == first
    assert all(s == sorted(s) for s in first)


def test_the_split_balances_by_recorded_time() -> None:
    m = shard()
    timings = {"tests/test_big.py": 10.0, "tests/test_a.py": 4.0, "tests/test_b.py": 3.0}
    timings |= {"tests/test_c.py": 3.0}
    assert m.split(sorted(timings), timings, 2) == [
        ["tests/test_big.py"],
        ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"],
    ]


def test_a_new_file_is_picked_up_with_no_timing_or_edit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tree(tmp_path / "repo", "tests/test_a.py", "tests/test_b.py", "tests/test_c.py")
    timings = tmp_path / "timings.json"
    timings.write_text(json.dumps({"tests/test_a.py": 5.0, "tests/test_b.py": 1.0}))
    common = ["--root", str(root), "--timings", str(timings), "--total", "2"]
    before = [run(capsys, *common, "--index", str(i))[1] for i in range(2)]
    tree(root, "tests/test_new.py")
    after = [run(capsys, *common, "--index", str(i))[1] for i in range(2)]
    assert sorted(f for s in before for f in s) == [
        "tests/test_a.py",
        "tests/test_b.py",
        "tests/test_c.py",
    ]
    assert sum(s.count("tests/test_new.py") for s in after) == 1
    assert sorted(f for s in after for f in s) == sorted(
        [*before[0], *before[1], "tests/test_new.py"]
    )


def test_an_empty_shard_is_refused_rather_than_running_everything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tree(tmp_path, "tests/test_only.py")
    args = ["--root", str(root), "--timings", str(tmp_path / "none.json"), "--total", "2"]
    assert run(capsys, *args, "--index", "0") == (0, ["tests/test_only.py"])
    assert run(capsys, *args, "--index", "1") == (2, [])


def test_record_sums_each_files_setup_call_and_teardown(tmp_path: Path) -> None:
    log = tmp_path / "durations.txt"
    log.write_text(
        "============ slowest durations ============\n"
        "2.50s setup    tests/test_pg.py::test_one\n"
        "1.25s call     tests/test_pg.py::test_one\n"
        "0.25s teardown tests/test_pg.py::test_two[a-b]\n"
        "0.10s call     tests/sub/test_x.py::TestK::test_y\n"
        "1 passed in 4.10s\n"
    )
    out = tmp_path / "timings.json"
    assert shard().main(["--record", str(log), "--timings", str(out)]) == 0
    assert json.loads(out.read_text()) == {"tests/sub/test_x.py": 0.1, "tests/test_pg.py": 4.0}


WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SHARD_COUNT = 6
HEAVIEST_RECORDED_SECONDS = 800


def workflow_shards() -> list[int]:
    text = WORKFLOW.read_text()
    job = text.split("\n  pytest:\n", 1)[1].split("\n  browser:", 1)[0]
    match = re.search(r"^\s+shard:\s*\[([^\]]*)\]", job, re.MULTILINE)
    assert match is not None, "the pytest job has no shard list"
    return [int(n) for n in match.group(1).split(",")]


def test_the_workflow_shard_list_is_the_six_way_split() -> None:
    assert workflow_shards() == list(range(1, SHARD_COUNT + 1))


def test_the_heaviest_shard_stays_well_under_the_job_limit() -> None:
    m = shard()
    timings = m.load_timings(m.TIMINGS)
    shards = m.split(m.test_files(ROOT), timings, len(workflow_shards()))
    heaviest = max(sum(timings.get(f, 0.0) for f in s) for s in shards)
    assert heaviest <= HEAVIEST_RECORDED_SECONDS, f"heaviest shard records {heaviest:.0f}s"
