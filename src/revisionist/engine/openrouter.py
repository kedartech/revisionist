"""Free OpenRouter models behind the ``Transport`` protocol, guarded to spend nothing.

For a shared instance that must not run on the host's Claude login. Each call kind
has an ordered list of ``:free`` models; a kind with no list is refused, so the
engine's own no-model fallback runs, as it does after the last model fails.

Guards, each refusing with ``TransportError`` before a request leaves:

- every model id ends in ``:free``, at construction and on every call;
- the live listing prices the model at 0 (re-read hourly; a model gone or priced is
  skipped);
- the key's usage is read at start-up and every ``USAGE_EVERY`` calls; a rise, or a
  reply that reports a cost, refuses every call until a restart;
- at most ``PER_MINUTE`` calls a minute, across every kind;
- a day-quota 429 refuses every call until 00:00 UTC.

The key comes from ``$REVISIONIST_OPENROUTER_KEY`` and goes only into the request's
Authorization header. Errors and log lines carry a status code, a model id or a call
kind, never a header, a response body, a prompt or a reply.
"""

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from revisionist.engine.llm import Reply, Request, TransportError, cli_schema

BASE = "https://openrouter.ai/api/v1"
KEY_ENV = "REVISIONIST_OPENROUTER_KEY"
MODELS_ENV = "REVISIONIST_OPENROUTER_MODELS"
"""JSON ``{"kind": ["vendor/model:free", ...]}``; each kind given replaces the default's."""

ERNIE = "baidu/ernie-5.5-flash-preview:free"
DOTS = "dots-studio/dots-3-note-preview:free"
FLINT = "recursive/flint-v1.0:free"
DEFAULT_MODELS: Mapping[str, tuple[str, ...]] = {
    "prose": (ERNIE, FLINT, DOTS),
    "counsel": (ERNIE, FLINT, DOTS),
    "options": (ERNIE, DOTS, FLINT),
    "estimator": (FLINT, ERNIE, DOTS),
}
"""Order from the free-model replay's pass rates, then speed. Aide, build, pitch,
held-power and session-zero kinds are absent: their no-model fallbacks run."""

MAX_TOKENS = 32000
"""Reasoning models spend most of a smaller cap thinking and cut the JSON off."""
TIMEOUT_S = 420.0
PER_MINUTE = 15
USAGE_EVERY = 25
LISTING_TTL_S = 3600.0
UPSTREAM_STRIKES = 3
UPSTREAM_REST_S = 600.0
MINUTE_WAIT_S = 60.0
PRICES = ("prompt", "completion", "request", "image", "web_search", "internal_reasoning")
log = logging.getLogger(__name__)


def free_id(model: object) -> str:
    if not isinstance(model, str) or not model.endswith(":free") or model.count(":") != 1:
        raise TransportError(f"openrouter: refused: {model!r} is not a :free model id")
    return model


def _table(models: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for kind, ids in models.items():
        if not isinstance(kind, str) or isinstance(ids, str) or not isinstance(ids, list | tuple):
            raise TransportError("openrouter: the model table maps a call kind to a list of ids")
        out[kind] = tuple(free_id(m) for m in ids)
    return out


def _zero(value: object) -> bool:
    try:
        return float(str(value)) == 0.0
    except ValueError:
        return False


def listed_free(model: str, listing: Any) -> dict[str, Any] | None:
    """The listing's entry for ``model`` when every price it shows is 0, else None."""
    data = listing.get("data") if isinstance(listing, dict) else None
    entry = next((m for m in data or () if isinstance(m, dict) and m.get("id") == model), None)
    pricing = entry.get("pricing") if entry is not None else None
    if not isinstance(pricing, dict) or "prompt" not in pricing or "completion" not in pricing:
        return None
    if not all(_zero(pricing[p]) for p in PRICES if p in pricing):
        return None
    return entry


def _limit(body: Any) -> str:
    """Which 429: ``day``, ``minute`` or ``upstream`` (anything else counts as upstream)."""
    found = body.get("error") if isinstance(body, dict) else None
    err: dict[str, Any] = found if isinstance(found, dict) else {}
    meta = err["metadata"] if isinstance(err.get("metadata"), dict) else {}
    text = f"{err.get('message', '')} {meta.get('raw', '')}".lower()
    if any(w in text for w in ("per-day", "per day", "daily")):
        return "day"
    if any(w in text for w in ("per-min", "per min")):
        return "minute"
    return "upstream"


def read_json(text: str) -> Any:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rstrip().removesuffix("```")
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        return json.loads(t[a : b + 1]) if 0 <= a < b else None


class Bucket:
    """At most ``per_min`` takes in any 60 seconds; a take past that waits."""

    def __init__(
        self, per_min: int, clock: Callable[[], float], sleep: Callable[[float], None]
    ) -> None:
        self.per_min, self.clock, self.sleep = per_min, clock, sleep
        self.sent: list[float] = []
        self.lock = threading.Lock()

    def take(self) -> None:
        while True:
            with self.lock:
                now = self.clock()
                self.sent = [t for t in self.sent if now - t < 60.0]
                if len(self.sent) < self.per_min:
                    self.sent.append(now)
                    return
                wait = 60.0 - (now - self.sent[0]) + 0.05
            self.sleep(wait)


class OpenRouterTransport:
    def __init__(
        self,
        key: str,
        models: Mapping[str, Any] | None = None,
        *,
        base: str = BASE,
        timeout_s: float = TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not key:
            raise TransportError(f"openrouter: {KEY_ENV} is not set")
        self.models = _table(DEFAULT_MODELS if models is None else models)
        self.base, self.timeout_s = base, timeout_s
        self.clock, self.now, self.sleep = clock, now, sleep
        self.bucket = Bucket(PER_MINUTE, clock, sleep)
        self._headers: Callable[[], dict[str, str]] = lambda: {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Title": "revisionist",
        }
        self._lock = threading.Lock()
        self._listing: tuple[float, Any] | None = None
        self._baseline: float | None = None
        self._since = 0
        self._stopped = ""
        self._quota_until: datetime | None = None
        self._strikes: dict[str, int] = {}
        self._resting: dict[str, float] = {}

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ, **kw: Any) -> "OpenRouterTransport":
        models = dict(DEFAULT_MODELS)
        if raw := environ.get(MODELS_ENV):
            try:
                given = json.loads(raw)
            except json.JSONDecodeError:
                raise TransportError(f"openrouter: {MODELS_ENV} is not JSON") from None
            if not isinstance(given, dict):
                raise TransportError(f"openrouter: {MODELS_ENV} is not a JSON object")
            models |= _table(given)
        return cls(environ.get(KEY_ENV, "").strip(), models, **kw)

    def __repr__(self) -> str:
        return f"OpenRouterTransport(base={self.base!r}, kinds={sorted(self.models)})"

    # --- http --------------------------------------------------------------------

    def _send(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method, headers=self._headers()
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"{}")
            except ValueError:
                return exc.code, {}
            finally:
                exc.close()
        except Exception as exc:  # the name only: messages can quote the request
            log.warning("openrouter: %s %s failed: %s", method, path, type(exc).__name__)
            return 0, {}

    # --- guards --------------------------------------------------------------------

    def start(self) -> None:
        """Read the key's usage now: the value every later read is held to."""
        with self._lock:
            if self._baseline is not None:
                return
        used = self._usage()
        with self._lock:
            self._baseline, self._since = used, 0

    def _usage(self) -> float:
        status, body = self._send("GET", "/key")
        data = body.get("data") if isinstance(body, dict) else None
        if status != 200 or not isinstance(data, dict) or "usage" not in data:
            raise TransportError(f"openrouter: key usage could not be read (http {status})")
        return float(data["usage"])

    def _stop(self, why: str) -> None:
        with self._lock:
            first, self._stopped = not self._stopped, self._stopped or why
        if first:
            log.error("openrouter: %s; every call is refused until a restart", why)

    def _open(self) -> None:
        with self._lock:
            stopped, until = self._stopped, self._quota_until
        if stopped:
            raise TransportError(f"openrouter: refused: {stopped}")
        if until is not None and self.now() < until:
            raise TransportError("openrouter: the free daily limit is spent until 00:00 UTC")

    def _spend_check(self) -> None:
        with self._lock:
            due = self._baseline is None or self._since >= USAGE_EVERY
        if not due:
            return
        if self._baseline is None:
            self.start()
            return
        used = self._usage()
        with self._lock:
            self._since = 0
            rose = used > self._baseline
        if rose:
            self._stop("key usage rose since start-up")
            self._open()

    def _current_listing(self) -> Any:
        with self._lock:
            kept = self._listing
        if kept is not None and self.clock() - kept[0] < LISTING_TTL_S:
            return kept[1]
        status, listing = self._send("GET", "/models")
        if status != 200 or not isinstance(listing, dict):
            raise TransportError(f"openrouter: the model listing could not be read (http {status})")
        with self._lock:
            self._listing = (self.clock(), listing)
        return listing

    # --- calls ---------------------------------------------------------------------

    def call(self, request: Request) -> Reply:
        kind = request.call_class
        models = tuple(free_id(m) for m in self.models.get(kind, ()))
        if not models:
            raise TransportError(f"openrouter: {kind} calls are off on this instance")
        self._open()
        listing = self._current_listing()
        for model in models:
            with self._lock:
                resting = self.clock() < self._resting.get(model, float("-inf"))
            entry = None if resting else listed_free(model, listing)
            if entry is None:
                log.info("openrouter: %s skipped for %s", model, kind)
                continue
            reply = self._try(model, entry, request)
            if reply is not None:
                return reply
        raise TransportError(f"openrouter: no free model answered ({kind})")

    def _try(self, model: str, entry: dict[str, Any], request: Request) -> Reply | None:
        body = self._body(model, entry, request)
        for attempt in (1, 2):
            self._open()
            self._spend_check()
            self.bucket.take()
            free_id(body["model"])
            with self._lock:
                self._since += 1
            status, resp = self._send("POST", "/chat/completions", body)
            if status == 429:
                limit = _limit(resp)
                log.warning("openrouter: 429 (%s) from %s", limit, model)
                if limit == "day":
                    midnight = (self.now() + timedelta(days=1)).date()
                    with self._lock:
                        self._quota_until = datetime.combine(midnight, datetime.min.time(), UTC)
                    self._open()
                if limit == "minute":
                    if attempt == 1:
                        self.sleep(MINUTE_WAIT_S)
                        continue
                    raise TransportError("openrouter: at the per-minute limit")
                self._strike(model)
                return None
            with self._lock:
                self._strikes[model] = 0
            usage = resp.get("usage") if isinstance(resp, dict) else None
            cost = usage.get("cost") if isinstance(usage, dict) else None
            if cost is not None and not _zero(cost):
                self._stop(f"a reply from {model} reported a cost")
                self._open()
            if status != 200:
                log.warning("openrouter: http %d from %s (%s)", status, model, request.call_class)
                return None
            return self._reply(model, resp, usage)
        return None

    def _strike(self, model: str) -> None:
        with self._lock:
            self._strikes[model] = self._strikes.get(model, 0) + 1
            if self._strikes[model] >= UPSTREAM_STRIKES:
                self._strikes[model] = 0
                self._resting[model] = self.clock() + UPSTREAM_REST_S

    def _body(self, model: str, entry: dict[str, Any], request: Request) -> dict[str, Any]:
        schema = cli_schema(request.schema)
        ask = "\n\nReply with one JSON object only, no prose and no code fence, that validates "
        ask += "against this JSON Schema:\n" + json.dumps(schema, ensure_ascii=False)
        body: dict[str, Any] = {
            "model": model,
            "models": [model],
            "provider": {"allow_fallbacks": False},
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt + ask},
            ],
            "temperature": 0.7,
            "max_tokens": MAX_TOKENS,
        }
        params = entry.get("supported_parameters") or ()
        if "response_format" in params or "structured_outputs" in params:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": request.call_class, "strict": False, "schema": schema},
            }
        return body

    def _reply(self, model: str, resp: Any, usage: Any) -> Reply | None:
        choices = resp.get("choices") if isinstance(resp, dict) else None
        first = choices[0] if isinstance(choices, list) and choices else {}
        message = first.get("message") if isinstance(first, dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        try:
            output = read_json(text) if isinstance(text, str) else None
        except json.JSONDecodeError:
            output = None
        if not isinstance(output, dict):
            log.warning("openrouter: no JSON object from %s", model)
            return None
        used = usage if isinstance(usage, dict) else {}
        return Reply(
            output=output,
            model=model,
            input_tokens=int(used.get("prompt_tokens") or 0),
            output_tokens=int(used.get("completion_tokens") or 0),
            cached_tokens=0,
            usd=0.0,
        )


__all__ = [
    "DEFAULT_MODELS",
    "KEY_ENV",
    "MODELS_ENV",
    "Bucket",
    "OpenRouterTransport",
    "free_id",
    "listed_free",
]
