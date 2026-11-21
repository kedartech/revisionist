"""`revisionist web serve --offline-prose` with canned model replies, for browser smoke runs.

No model is called. Pages are written from templates; the aide brief uses the template
aide; a directive is read as the first instrument whose fields can be filled from its
own limits and choices; counsel and the aide's help desk answer with a fixed line. Engine
v2: options fall back to the template, a free-text order reads as one ask aimed at its
addressee, the estimator rules that nothing changes, and three people held power on
every date. The cost on each reply is zero.

    REVISIONIST_DB=postgresql://... python web/test/e2e/serve_canned.py [PORT]
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from revisionist import cli
from revisionist.core.state import Rule
from revisionist.core.world import LockDecl, WorldFile
from revisionist.engine import campaign as cmp
from revisionist.engine.llm import Reply, Request
from revisionist.engine.web import map_api


def _directive(prompt: str) -> dict[str, Any]:
    found = re.search(r"## Their instruments\n(.*)\n\n## Today", prompt, re.S)
    for lever in json.loads(found.group(1)) if found else []:
        params: dict[str, Any] = {}
        for p in lever["params"]:
            if p["kind"] == "int" and p.get("lo") is not None:
                params[p["name"]] = p["lo"]
            elif p.get("choices"):
                params[p["name"]] = p["choices"][0]["value"]
            elif p["kind"] == "text":
                params[p["name"]] = "As instructed."
            else:
                break
        else:
            return {"lever": lever["lever"], "params": params, "reason": ""}
    return {"lever": "", "params": {}, "reason": "None of your instruments does this."}


HELD = [
    {
        "name": "Franklin D. Roosevelt",
        "title": "President of the United States",
        "side": "United States",
        "power": "Government",
    },
    {
        "name": "Henry L. Stimson",
        "title": "Secretary of War",
        "side": "United States",
        "power": "Government",
    },
    {
        "name": "Winston Churchill",
        "title": "Prime Minister",
        "side": "United Kingdom",
        "power": "Government",
    },
]
"""Who held power on any date, for the new-game screen."""


class Canned:
    def call(self, request: Request) -> Reply:
        props = set(request.schema.get("properties", {}))
        if request.call_class == "counsel":
            out: Any = {"text": "I would wait a week before deciding; the papers are not all in."}
        elif props == {"text", "lever"}:
            out = {"text": "Use the form for it under Standard forms on your desk.", "lever": ""}
        elif "lever" in props:
            out = _directive(request.prompt)
        elif props == {"options"}:
            out = {"options": []}  # the template offers instead
        elif props == {"asks", "reason"}:
            out = {"asks": [{"ask": "Escort the convoys as far as Iceland"}], "reason": ""}
        elif props == {"effects", "reason", "rationale"}:
            out = {
                "effects": [],
                "reason": "The office takes note.",
                "rationale": "A canned ruling for the smoke run: nothing changes.",
            }
        elif props == {"people"}:
            out = {"people": HELD}
        elif "summary" in props:
            out = {"summary": "", "drafts": []}
        else:
            raise RuntimeError(f"no canned reply for {request.call_class}")
        return Reply(out, request.model, 0, 0, 0, 0.0)


CANNED_MARK_SECRET = "c4" * 32
"""A fixed, public secret for throwaway smoke databases only; never a deployment's."""

CANNED_LOCK = {
    "key": "canned_reykjavik",
    "order": {"form": "detach_fleet", "params": {"to": "reykjavik"}},
    "decider": {"person": "knox"},
}
"""One lock the browser smoke walks (LKM): a detachment sent to Reykjavik waits on the
Secretary of the Navy. The smoke's own row, in the smoke's games only; the world file is
not changed."""


def _locked(world: WorldFile) -> WorldFile:
    """The world with ``locks`` on and the smoke's one row beside its own rows, where the
    world has the form the row names and no row of that key; any other world as it is. A
    world with locks of its own (autumn 1941 since KCD) keeps them: none holds this form."""
    forms = {lv.name for c in world.cards for lv in c.levers}
    keys = {r.key for r in world.locks}
    if CANNED_LOCK["key"] in keys or CANNED_LOCK["order"]["form"] not in forms:
        return world
    return world.model_copy(
        update={
            "rules": tuple(sorted({*world.rules, Rule.LOCKS})),
            "locks": (*world.locks, LockDecl.model_validate(CANNED_LOCK)),
        }
    )


def _load_world(path: Path) -> WorldFile:
    return _locked(_LOAD_WORLD(path))


_LOAD_WORLD = cmp.load_world


if __name__ == "__main__":
    os.environ.setdefault(map_api.MARK_SECRET_ENV, CANNED_MARK_SECRET)
    cli.transport_factory = Canned
    cmp.load_world = _load_world  # every caller reads it through the module (LKM)
    sys.argv = ["revisionist", "web", "serve", "--offline-prose", "--port", *sys.argv[1:2]]
    try:
        cli.app()
    finally:
        cmp.load_world = _LOAD_WORLD  # a run inside another process leaves no lock behind
