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
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from revisionist import cli
from revisionist.core.state import MODEL_READ_RULES, Rule
from revisionist.core.world import LockDecl, PactClauseDecl, PactDecl, WarDecl, WorldFile
from revisionist.engine import campaign as cmp
from revisionist.engine import timeline as tl
from revisionist.engine.llm import Reply, Request
from revisionist.engine.web import map_api, new_game_api, server


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


SALT_STATEMENT = {
    "ask": "Speak to the nation on the march south.",
    "effect": {"kind": "statement", "theme": "the_march_south"},
}
"""What the canned aide reads any written order as in the Salt Strait smoke game: a
statement on the Marshal's theme, the one thing the smoke writes."""


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
        elif "treaty" in props:  # written orders on: only the Salt Strait smoke world has them
            out = {"asks": [SALT_STATEMENT], "reason": ""}
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


SALT_STRAIT = "salt-strait-realism"
"""The Salt Strait world the smoke's second walk starts; the canned server lists it beside
autumn 1941 and nothing else is changed in what it serves."""


def _offer_salt_strait() -> Callable[[], None]:
    """List Salt Strait among the new games; returns what puts the modules back, for a run
    inside another process (a test starts this file in its own interpreter)."""
    kept = (server.READY, server.OFFERED, new_game_api.figures)

    def undo() -> None:
        server.READY, server.OFFERED, new_game_api.figures = kept

    server.READY = (*server.READY, SALT_STRAIT)
    server.OFFERED = (*server.OFFERED, SALT_STRAIT)
    real = new_game_api.figures

    def figures(on: date, search: str, transport: Any) -> Any:
        """Nobody of the war's cast held power in 1900: the cast screen of a Salt Strait game
        asks by its start date and is told so with an empty list, not a 400 the page logs."""
        if not tl.WAR_START <= on <= tl.WAR_END:
            return []
        return real(on, search, transport)

    new_game_api.figures = figures
    return undo


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


def _named_forces(lever: Any, names: dict[str, str]) -> Any:
    """The force choice of a move form worded as the map names the piece ("The Ostrel Levy"),
    which is how the room finds the form that moves a picked piece. Salt Strait's own
    choices carry no words, so the room reads them as "Ostrel levy" and finds no form."""
    if lever.name != "move_force":
        return lever
    params = tuple(
        p.model_copy(update={"choice_labels": tuple(names[c] for c in p.choices)})
        if p.name == "force" and all(c in names for c in p.choices)
        else p
        for p in lever.params
    )
    return lever.model_copy(update={"params": params})


SALT_LEVIES = {"ostrel_levy": 5, "varda_levy": 3}
"""The two levies' strength, so the battle they fight lasts several days (the same tiers
tests/test_salt_strait_plays.py plays with)."""


def _set_up(feature: Any) -> Any:
    """The Ostrel levy in Harrow Pass, a step from Varda's coast; both levies at their strength."""
    update: dict[str, Any] = {}
    if feature.key == "ostrel_levy":
        update["places"] = ("harrow_fort",)
    if feature.key in SALT_LEVIES:
        update["tier"] = SALT_LEVIES[feature.key]
    return feature.model_copy(update=update)


def _salted(world: WorldFile) -> WorldFile:
    """Salt Strait as the smoke walks it, playing the Marshal: Varda and Ostrel at war from
    the start, the Ostrel levy standing in Harrow Pass a step from Varda's coast and Varda's
    levy, so the first march meets it; the three model-read rules on; and a secret pact of
    Ostrel and Kesh for the Marshal to publish. Any other world as it is."""
    if world.world != SALT_STRAIT:
        return world
    features = tuple(_set_up(f) for f in world.features)
    names = {f.key: f.name for f in world.features}
    cards = tuple(
        c.model_copy(
            update={
                "levers": tuple(_named_forces(lv, names) for lv in c.levers),
                **({"horizon_days": 1} if c.person == "general_aske" else {}),
            }
        )
        for c in world.cards
    )
    accord = PactDecl(
        key="salt_accord",
        name="The Salt Accord",
        parties=("ostrel", "kesh"),
        wording=(
            "Ostrel and Kesh each go to war within seven days on any power that newly"
            " attacks the other."
        ),
        clauses=(
            PactClauseDecl(type="defend", binds="ostrel", nation="kesh", days=7),
            PactClauseDecl(type="defend", binds="kesh", nation="ostrel", days=7),
        ),
        public=False,
        source="salt_strait",
    )
    return world.model_copy(
        update={
            "rules": tuple(sorted({*world.rules, *MODEL_READ_RULES})),
            "features": features,
            "cards": cards,
            "wars": (WarDecl(a="ostrel", b="varda", since=date(1900, 3, 1), source="salt_strait"),),
            "pacts": (*world.pacts, accord),
        }
    )


def _load_world(path: Path) -> WorldFile:
    return _salted(_locked(_LOAD_WORLD(path)))


_LOAD_WORLD = cmp.load_world


if __name__ == "__main__":
    os.environ.setdefault(map_api.MARK_SECRET_ENV, CANNED_MARK_SECRET)
    cli.transport_factory = Canned
    unoffer = _offer_salt_strait()
    cmp.load_world = _load_world  # every caller reads it through the module (LKM)
    sys.argv = ["revisionist", "web", "serve", "--offline-prose", "--port", *sys.argv[1:2]]
    try:
        cli.app()
    finally:
        cmp.load_world = _LOAD_WORLD  # a run inside another process leaves no lock behind
        unoffer()
