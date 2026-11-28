"""Print the test files of one CI shard, one per line.

Every test file pytest would collect under ``tests/`` lands in exactly one shard.
Files are spread by their recorded run time (``scripts/ci_timings.json``, seconds per
file) so the shards finish at about the same time. A file with no recorded time counts
as the median recorded file, so a new test file joins a shard with no edit here or in
the workflow.

    python3 scripts/ci_shard.py --total 6 --index 0

To refresh the timings from a full run's
``pytest --durations=0 --durations-min=0`` output:

    python3 scripts/ci_shard.py --record durations.txt

Standard library only: CI runs it before the project's environment exists.
"""

import argparse
import json
import re
import statistics
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMINGS = Path(__file__).resolve().parent / "ci_timings.json"
PATTERNS = ("test_*.py", "*_test.py")
DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)s\s+(?:setup|call|teardown)\s+([^\s:]+\.py)::")


def test_files(root: Path) -> list[str]:
    """The files pytest's default ``python_files`` patterns match under ``root/tests``."""
    found = {p for pattern in PATTERNS for p in (root / "tests").rglob(pattern) if p.is_file()}
    return sorted(p.relative_to(root).as_posix() for p in found)


def load_timings(path: Path) -> dict[str, float]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    return {str(k): float(v) for k, v in data.items()}


def split(files: Sequence[str], timings: Mapping[str, float], total: int) -> list[list[str]]:
    """Longest first onto the lightest shard; ties go to the lower index and the earlier path.

    Each shard's files come back sorted, so the same inputs always give the same shards.
    """
    if total < 1:
        raise ValueError("total must be at least 1")
    known = [timings[f] for f in files if f in timings]
    fallback = statistics.median(known) if known else 1.0
    weight = {f: timings.get(f, fallback) for f in files}
    loads = [0.0] * total
    shards: list[list[str]] = [[] for _ in range(total)]
    for f in sorted(files, key=lambda f: (-weight[f], f)):
        i = min(range(total), key=lambda i: (loads[i], i))
        shards[i].append(f)
        loads[i] += weight[f]
    return [sorted(s) for s in shards]


def parse_durations(text: str) -> dict[str, float]:
    """Seconds per test file, summed over every setup, call and teardown line."""
    per_file: dict[str, float] = {}
    for line in text.splitlines():
        m = DURATION.match(line)
        if m:
            per_file[m.group(2)] = per_file.get(m.group(2), 0.0) + float(m.group(1))
    return {f: round(s, 2) for f, s in sorted(per_file.items())}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the test files of one CI shard.")
    parser.add_argument("--total", type=int, help="number of shards")
    parser.add_argument("--index", type=int, help="this shard, counted from 0")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--timings", type=Path, default=TIMINGS, help=argparse.SUPPRESS)
    parser.add_argument("--record", type=Path, metavar="LOG", help="rewrite the timings file")
    args = parser.parse_args(argv)

    if args.record is not None:
        timings = parse_durations(args.record.read_text())
        if not timings:
            print(f"no duration lines in {args.record}", file=sys.stderr)
            return 2
        args.timings.write_text(json.dumps(timings, indent=1, sort_keys=True) + "\n")
        print(f"{len(timings)} files written to {args.timings}")
        return 0

    if args.total is None or args.index is None:
        parser.error("--total and --index are required")
    if not 0 <= args.index < args.total:
        parser.error("--index must be at least 0 and below --total")
    files = test_files(args.root)
    shard = split(files, load_timings(args.timings), args.total)[args.index]
    if not shard:
        # An empty argument list would make pytest run the whole suite.
        print(f"shard {args.index} of {args.total} is empty", file=sys.stderr)
        return 2
    print("\n".join(shard))
    return 0


if __name__ == "__main__":
    sys.exit(main())
