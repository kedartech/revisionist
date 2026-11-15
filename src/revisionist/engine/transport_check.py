"""A $0 check that each free model reads the prompt as it was sent.

OpenRouter's Sensitive Info guardrail rewrites a request before any model sees it: a
place or a name becomes a label such as ``[ADDRESS]``, or a gap the model writes
around with dashes. The transport refuses a reply that carries a label, but a reply
written around a gap passes. So each model in the routing table is sent one fixed
text of places, names, a date and a number and asked to copy it back; a word that
does not come back means the prompt was damaged on the way.

Every call goes through the guarded ``OpenRouterTransport``: free model ids only, the
key's usage read at start-up and held to.
"""

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from revisionist.engine.llm import Request, Transport, TransportError
from revisionist.engine.openrouter import KEY_ENV, LABEL, MODELS_ENV, OpenRouterTransport

PLACES = ("Smolensk", "Leningrad", "Kiev", "Odessa", "Halifax", "Liverpool")
PEOPLE = ("Erich Raeder", "Alfred Jodl")
DATE = "22 June 1941"
NUMBER = "412"
WORDS = (*PLACES, *PEOPLE, DATE, NUMBER)
TEXT = (
    f"On {DATE} Army Group Centre stood at Smolensk with {NUMBER} tanks. "
    "The front ran Leningrad \u2013 Smolensk \u2013 Kiev \u2013 Odessa. "
    "HX convoys sailed Halifax \u2013 Liverpool. Signed, Erich Raeder and Alfred Jodl."
)
SYSTEM = "You are a careful copyist."
PROMPT = (
    "Text between the marks:\n<<<" + TEXT + ">>>\n\n"
    "echo: copy the text exactly as you received it, character for character."
)
SCHEMA = {
    "type": "object",
    "properties": {"echo": {"type": "string"}},
    "required": ["echo"],
    "additionalProperties": False,
}

OK, LOST, NO_VERDICT = 0, 1, 2


@dataclass(frozen=True)
class Verdict:
    model: str
    lost: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    """Labels the reply held; a reply the transport refused for one has no ``lost``."""
    error: str = ""
    """Why there is no verdict: the model could not be reached or sent no copy."""

    @property
    def damaged(self) -> bool:
        return bool(self.lost or self.labels)

    def line(self) -> str:
        if self.error:
            return f"{self.model}: no verdict: {self.error}"
        if not self.damaged:
            return f"{self.model}: every word came back"
        parts = [f"lost {', '.join(self.lost)}"] if self.lost else ["reply refused"]
        if self.labels:
            parts.append(f"labels {', '.join(self.labels)}")
        return f"{self.model}: {'; '.join(parts)}"


def kind(index: int) -> str:
    return f"check_{index + 1}"


def judge(transport: Transport, model: str, call_class: str) -> Verdict:
    request = Request(
        call_class=call_class, model=model, system=SYSTEM, prompt=PROMPT, schema=SCHEMA
    )
    try:
        reply = transport.call(request)
    except TransportError as exc:
        labels = tuple(sorted(set(LABEL.findall(str(exc)))))
        return Verdict(model, labels=labels) if labels else Verdict(model, error=str(exc))
    echo = reply.output.get("echo") if isinstance(reply.output, dict) else None
    if not isinstance(echo, str):
        return Verdict(model, error="the reply held no copy of the text")
    lost = tuple(w for w in WORDS if echo.count(w) < TEXT.count(w))
    return Verdict(model, lost=lost, labels=tuple(sorted(set(LABEL.findall(echo)))))


def run(transport: Transport, ids: Sequence[str]) -> list[Verdict]:
    """One call per model, in order; ``ids[i]`` is routed by the call kind ``kind(i)``."""
    return [judge(transport, model, kind(i)) for i, model in enumerate(ids)]


def exit_code(verdicts: Sequence[Verdict]) -> int:
    """A lost word is a verdict even when another model gave none; no model is none."""
    if any(v.damaged for v in verdicts):
        return LOST
    if not verdicts or any(v.error for v in verdicts):
        return NO_VERDICT
    return OK


def report(verdicts: Sequence[Verdict]) -> list[str]:
    lines = [v.line() for v in verdicts] or ["no model in the routing table"]
    code = exit_code(verdicts)
    if code == LOST:
        lines.append(
            "A word was lost on the way to a model: check the account's guardrails "
            "(Sensitive Info) before serving the free instance."
        )
    elif code == NO_VERDICT:
        lines.append("A model gave no verdict: run the check again before serving.")
    return lines


def openrouter(environ: Mapping[str, str] = os.environ, **kw: Any) -> tuple[Transport, list[str]]:
    """The guarded transport with one call kind per model of the instance's routing
    table, and those models in first-use order."""
    table = OpenRouterTransport.from_env(environ, **kw).models
    ids = list(dict.fromkeys(m for models in table.values() for m in models))
    routes = {kind(i): [m] for i, m in enumerate(ids)}
    env = {KEY_ENV: environ.get(KEY_ENV, ""), MODELS_ENV: json.dumps(routes)}
    return OpenRouterTransport.from_env(env, **kw), ids


__all__ = ["WORDS", "Verdict", "exit_code", "openrouter", "report", "run"]
