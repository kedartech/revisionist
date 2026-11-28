"""CI decisions: what a change set needs to run, and whether every job passed.

``decide`` reads changed paths on stdin, one per line as ``git diff --name-only``
prints them, and prints ``python=`` and ``web=`` (each ``true`` or ``false``) for
``$GITHUB_OUTPUT``. The Python tests are skipped only when every path is one no Python
test reads; any other path, including one this file does not know, runs them. The real
browser test is skipped only when every path is documentation (under ``docs/``, or a
Markdown file at the top of the repo): world data, engine code and CI files all change
what the room serves, so they run it as a path under ``web/`` does.

``gate`` reads the needed jobs' results from the environment and fails unless each
passed (the dependency audit always runs), or the pytest shards were skipped because
``decide`` said no Python changed,
or the browser job was skipped because ``decide`` said only documentation changed.

Standard library only: CI runs it before the project's environment exists.
"""

import os
import sys
from collections.abc import Iterable, Mapping, Sequence

# Client and docs paths the Python suite never opens.
SKIPPABLE_PREFIXES = ("docs/", "web/")
# Under those, the files Python tests or the code they run do open: the seat fixture
# (several tests), the portraits with their SOURCES.md (dossiers.PORTRAITS_DIR) and the
# canned smoke server (its start-up is tested).
READ_BY_TESTS = (
    "web/test/fixtures/",
    "web/assets/portraits/",
    "web/assets/flags/",
    "web/test/e2e/serve_canned.py",
)


def documentation(path: str) -> bool:
    """Under ``docs/``, or a Markdown file at the top of the repo (README.md, CONTRIBUTING.md)."""
    return path.startswith("docs/") or ("/" not in path and path.endswith(".md"))


def skippable(path: str) -> bool:
    if path.startswith(READ_BY_TESTS):
        return False
    return path.startswith(SKIPPABLE_PREFIXES) or documentation(path)


def needs_python(paths: Iterable[str]) -> bool:
    """True unless there is at least one path and every path is skippable."""
    changed = [p.strip() for p in paths if p.strip()]
    return not changed or not all(skippable(p) for p in changed)


def needs_browser(paths: Iterable[str]) -> bool:
    """True unless there is at least one path and every path is documentation."""
    changed = [p.strip() for p in paths if p.strip()]
    return not changed or not all(documentation(p) for p in changed)


def gate(results: Mapping[str, str]) -> list[str]:
    """The reasons the run is not green; empty when it is."""
    problems = [
        f"{job}: {results.get(job) or 'missing'}"
        for job in ("changes", "lint", "node", "audit")
        if results.get(job) != "success"
    ]
    pytest, python = results.get("pytest"), results.get("python")
    skipped_on_purpose = pytest == "skipped" and python == "false"
    if pytest != "success" and not skipped_on_purpose:
        problems.append(f"pytest: {pytest or 'missing'} (python changed: {python or 'unknown'})")
    browser, web = results.get("browser"), results.get("web")
    if browser != "success" and not (browser == "skipped" and web == "false"):
        problems.append(f"browser: {browser or 'missing'} (web changed: {web or 'unknown'})")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["decide"]:
        paths = sys.stdin.read().splitlines()
        print(f"python={'true' if needs_python(paths) else 'false'}")
        print(f"web={'true' if needs_browser(paths) else 'false'}")
        return 0
    if args == ["gate"]:
        keys = ("changes", "lint", "node", "audit", "pytest", "python", "browser", "web")
        results = {k: os.environ.get(f"RESULT_{k.upper()}", "") for k in keys}
        for k in keys:
            print(f"{k}: {results[k] or 'missing'}")
        problems = gate(results)
        for p in problems:
            print(f"not green: {p}", file=sys.stderr)
        return 1 if problems else 0
    print("usage: ci_changes.py decide|gate", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
