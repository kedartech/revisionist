"""The schema version moves with the schema (CONTRIBUTING.md, Rules).

Any change to the schema's shape (events, deltas, ontology, State, View) must
bump ``SCHEMA_VERSION`` and record the new fingerprint here. Descriptions and
titles are left out of the fingerprint, so a docstring edit needs no bump. Old
entries stay: they record which shape each number named.
"""

import hashlib
import json
from typing import Any

from revisionist.core import SCHEMA_VERSION
from revisionist.schema_export import build

FINGERPRINTS: dict[str, str] = {
    "11": "1770c651ebcae38a9273903012f29ecdc76628e52ca966b797f02d81674f6ce0",
    "12": "338078dee68421d3f8482f474ee45a1089c3aa0b9fb0ba384708e80e6c0df58e",
    "13": "52e4e8405f5b9b065def1ee6b47c686f0cbfb013b4cc836b3172db329a0e9921",
    "14": "541d333f00fdd0dd879c1499ced096a0cbecf298dffe3328637c5eb42c3a04f8",
    "15": "7ab8604b934d77c75ba385d502db7cdfd597f47c1086ccc2e20fa750c0ee0d61",
    "16": "bb4be1e8c0159133ac806ba87d8aec060ede948f340823136189f77bf59d8160",
    "17": "c8477129f2ff53adda71646ee8a1acdef15bb4ac5637fc1957d26e896556e410",
    "18": "b2684847c6d6e9e586d5df7c7b360232bfac26f7cd90fabfcce275d1837e9e57",
    "19": "9f8ee12a484964135f0d51519bfe0154300307c451a5a5e5a14bda0eaf87d5d6",
    "20": "14f347a0cc1b53e6b9cee3bb0c2d2179a782cc89905d8df3ea5cb3fa42d96e71",
    "21": "5dda6fdabe7f640c83181d1cc6bf70834ac71b10d68d1c7ed97e8c79c5ea3f87",
    "22": "9d6463f137de16ca071cf2933fee9d701300d198c4e1fdbac2ccdd81bf04018b",
    "23": "756a7f8aa87e26b1f8efdda4d5812bc98e2913978e854776e2e9d80b469c9065",
    "24": "c127f82e94590fdaa8e0ed5704989a59a4143dbb145eb66f2c799d342feb8f80",
    "25": "a95ce957edf238d4d4c7f0e5e7d7e7aaf1c120f9219158c077a27fbac23ccbb0",
    "26": "dcba6c9c7136e978068b9b175b51be9be43c034d0d3a1a1e32874cf71522ace3",
    "27": "c59b05b596061047d8597b977235e58e51f16e351c673ec5c1439c695e50de0a",
    "28": "1f6762e471ca4dd9cda303020bc73010f3091b63a2015e3f310dc76a64efb0b0",
    "29": "582b2953dabbc6e8853874b61e0dff2568b8c7cd8c3e2d2e89deb7527b877395",
    "30": "1906a399b0a3324f8ec6c437aea603ceab9f3ddef8c89bdd8cb5c6adb20af925",
}


def _shape(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _shape(v) for k, v in node.items() if k not in ("description", "title")}
    if isinstance(node, list):
        return [_shape(v) for v in node]
    return node


def fingerprint() -> str:
    text = json.dumps(_shape(build()), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def test_schema_version_matches_schema() -> None:
    actual = fingerprint()
    assert SCHEMA_VERSION in FINGERPRINTS, (
        f"SCHEMA_VERSION {SCHEMA_VERSION} has no fingerprint: add {actual!r} to FINGERPRINTS"
    )
    assert FINGERPRINTS[SCHEMA_VERSION] == actual, (
        "schema shape changed without a version bump: increment SCHEMA_VERSION in "
        f"src/revisionist/core/__init__.py and add {actual!r} to FINGERPRINTS under it"
    )


def test_fingerprints_are_unique() -> None:
    assert len(set(FINGERPRINTS.values())) == len(FINGERPRINTS)
