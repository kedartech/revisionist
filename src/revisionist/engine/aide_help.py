"""The aide's help desk (realism): the player asks their aide how to do something.

The aide answers as a subordinate on the principal's own staff, from the seat's
``View`` only: which standard form on the desk does it and who carries it, or that
it lies beyond the desk and who might act instead. It also explains a directive or
order that did not go through. It never files, never speaks for anyone on the card
(that is counsel), and never names a figure. The template path needs no model.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from revisionist.core._base import Model
from revisionist.core.events import CallCost
from revisionist.core.realism.card import Lever, ParamKind, words
from revisionist.core.state import View
from revisionist.engine.aide import AIDE_MODEL
from revisionist.engine.llm import Request, Transport, TransportError, prompt_text

QUESTION_MAX = 600
TEXT_MAX = 900


class Answer(Model):
    text: str
    lever: str = ""
    """A lever on the desk the answer points to, to open its form; "" for none."""
    cost: CallCost | None = None


HELP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "lever": {"type": "string"}},
    "required": ["text", "lever"],
    "additionalProperties": False,
}


def _view_only(view: object) -> View:
    if not isinstance(view, View):
        raise TypeError(f"the aide reads a View, not {type(view).__name__}")
    return view


def _lever_label(x: Lever) -> str:
    return x.label or words(x.name)


def help_prompt(view: View, question: str, failed: str = "") -> str:
    """The desk first (stable between questions), then what failed, then the question."""
    desk = _view_only(view).desk
    levers = [
        {
            "lever": x.name,
            "label": _lever_label(x),
            "summary": x.summary,
            "params": [
                {
                    "label": p.label or words(p.name),
                    "kind": p.kind.value,
                    **({"choices": list(p.choice_labels or p.choices)} if p.choices else {}),
                }
                for p in x.params
            ],
        }
        for x in (desk.levers if desk is not None else ())
    ]
    contacts = [
        {
            "name": view.entities[c.person].name,
            "by": words(c.channel.value).lower(),
            **(
                {"office": view.cards[c.person].office}
                if c.person in view.cards and view.cards[c.person].office
                else {}
            ),
        }
        for c in (desk.inner_circle if desk is not None else ())
        if c.person in view.entities
    ]
    principal = view.entities[view.me.embodies].name
    office = desk.office if desk is not None else ""
    head = {
        "powers": list(desk.powers) if desk is not None else [],
        "limits": list(desk.constraints) if desk is not None else [],
        "answerable_to": [
            view.entities[p].name for p in (desk.principals if desk else ()) if p in view.entities
        ],
    }
    out = (
        f"## Your principal\n{principal}" + (f", {office}" if office else "") + "\n"
        f"{json.dumps(head, ensure_ascii=False)}\n\n"
        f"## Their standard forms\n{json.dumps(levers, ensure_ascii=False)}\n\n"
        f"## Within their reach\n{json.dumps(contacts, ensure_ascii=False)}\n\n"
        f"## Today\n{view.in_world_date.isoformat() if view.in_world_date else ''}\n\n"
    )
    if failed:
        out += f"## What just did not go through\n{failed}\n\n"
    return out + f"## They ask\n{question}"


class Helper(Protocol):
    def answer(self, view: View, question: str, failed: str = "") -> Answer: ...


@dataclass
class ClaudeHelper:
    transport: Transport
    model: str = AIDE_MODEL
    max_usd: float = 0.10
    requests: list[Request] = field(default_factory=list)

    def answer(self, view: View, question: str, failed: str = "") -> Answer:
        req = Request(
            call_class="aide",
            model=self.model,
            system=prompt_text("aide_help"),
            prompt=help_prompt(view, question, failed),
            schema=HELP_SCHEMA,
            max_usd=self.max_usd,
        )
        self.requests.append(req)
        reply = self.transport.call(req)
        out = reply.output if isinstance(reply.output, dict) else {}
        return Answer(
            text=str(out.get("text", "")).strip(),
            lever=str(out.get("lever", "")).strip(),
            cost=reply.cost("aide"),
        )


_WORD = re.compile(r"[a-z]{4,}")


def _stems(text: str) -> set[str]:
    return {w[:5] for w in _WORD.findall(text.lower())}


def best_lever(view: View, text: str) -> Lever | None:
    """The desk's lever whose label, summary and choices share most words with ``text``."""
    desk = _view_only(view).desk
    asked = _stems(text)
    best, score = None, 0
    for x in desk.levers if desk is not None else ():
        said = " ".join(
            [x.name, _lever_label(x), x.summary]
            + [" ".join(p.choice_labels or p.choices) for p in x.params]
        )
        n = len(asked & _stems(said.replace("_", " ")))
        if n > score:
            best, score = x, n
    return best


def _how(x: Lever) -> str:
    choices = [p for p in x.params if p.kind is ParamKind.ENUM]
    picks = "; ".join(
        f"{(p.label or words(p.name)).lower()}: {', '.join(p.choice_labels or p.choices)}"
        for p in choices
    )
    line = f"Use “{_lever_label(x)}” under Standard forms on your desk"
    line += f" ({x.summary.rstrip('.')})" if x.summary else ""
    return line + (f". You choose {picks}." if picks else ".")


class TemplateHelper:
    """Word overlap against the desk's forms; no model."""

    def answer(self, view: View, question: str, failed: str = "") -> Answer:
        _view_only(view)
        desk = view.desk
        found = best_lever(view, question)
        lead = f"That did not go through: {failed.rstrip('.')}. " if failed else ""
        if found is not None:
            text = lead + _how(found) + " Or write a directive and I will read it as that form."
            return Answer(text=text, lever=found.name)
        forms = ", ".join(f"“{_lever_label(x)}”" for x in (desk.levers if desk else ()))
        powers = "; ".join(desk.powers) if desk is not None and desk.powers else ""
        text = lead + "I can find no form on your desk that does that."
        if forms:
            text += f" The forms you hold are {forms}."
        if powers:
            text += f" Your office gives you: {powers}."
        text += " If it lies with someone else, consult them in their window and ask them to act."
        return Answer(text=text)


def answer(view: View, question: str, helper: Helper, failed: str = "") -> Answer:
    """What the aide says. A failed call falls back to the template; a lever the desk
    does not hold is dropped; an over-long answer is cut."""
    _view_only(view)
    try:
        said = helper.answer(view, question, failed)
    except TransportError:
        said = TemplateHelper().answer(view, question, failed)
    if not said.text:
        said = (
            TemplateHelper().answer(view, question, failed).model_copy(update={"cost": said.cost})
        )
    levers = {x.name for x in (view.desk.levers if view.desk is not None else ())}
    text = said.text if len(said.text) <= TEXT_MAX else said.text[: TEXT_MAX - 1] + "…"
    return said.model_copy(
        update={"text": text, "lever": said.lever if said.lever in levers else ""}
    )


__all__ = [
    "HELP_SCHEMA",
    "QUESTION_MAX",
    "Answer",
    "ClaudeHelper",
    "Helper",
    "TemplateHelper",
    "answer",
    "best_lever",
    "help_prompt",
]
