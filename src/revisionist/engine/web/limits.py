"""What a caller may spend or repeat: the sign-in throttle and the hook for later limits."""

from __future__ import annotations

import threading
import time
from typing import Any

SIGNIN_TRIES = 10
"""Failed sign-ins (or recoveries) per handle per 15 minutes."""
SIGNIN_WINDOW_S = 900


class Refusal:
    """A turn-away the caller sends as a reply with `refused: true`; never raised."""

    def __init__(self, message: str) -> None:
        self.message = message

    def reply(self) -> dict[str, Any]:
        return {"refused": True, "message": self.message}


class SigninThrottle:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}

    def throttled(self, handle: str) -> bool:
        key = handle.strip().casefold()
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._failures.get(key, []) if now - t < SIGNIN_WINDOW_S]
            self._failures[key] = recent
            return len(recent) >= SIGNIN_TRIES

    def failed(self, handle: str) -> None:
        with self._lock:
            self._failures.setdefault(handle.strip().casefold(), []).append(time.monotonic())


def check(store: Any, account_id: Any, campaign_id: Any, action: str, now: Any) -> Refusal | None:
    return None


def address(handler: Any, what: str) -> Refusal | None:
    return None
