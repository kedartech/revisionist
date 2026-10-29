"""The estimator (engine v2, spec §8.3): the free-play rule.

For a routed part no code rule covers (``RoutedPart.effect`` is None), one
engine-side call returns typed effects from the closed vocabulary
(``core.realism.effect``) and a reason written from the issuer's view. Code clamps
the effects to the bounds and lands them as ``EffectsEstimated``; a replay reads
that event and never calls the model again.

Contract names only (engine-v2 addendum). Wave A4 builds the prompt, transport,
clamp, failure path and recording under these names.
"""

ESTIMATOR_MODEL = "claude-sonnet-5-5"
"""[proposed] ``REVISIONIST_MODEL_ESTIMATOR`` overrides it per call."""
CALL_CLASS = "estimator"
"""``Request.call_class`` and ``CallCost.call_class`` for every estimator call."""
PROMPT = "estimator"
"""The system prompt: ``engine/prompts/estimator.md``, read by ``prompt_text``."""
RECORDING = "realism-estimator-autumn.json"
"""Recorded replies under ``tests/recordings/``, keyed by ``Request.key()``."""
