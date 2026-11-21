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
    "31": "809b92d2518dda1caa3fed5630c0e66270f24c34f80af87249b0f9da14e312d4",
    "32": "4a93895111155a186b9d31c883034c54f61a1d364b923eaf7b168b46318be9fa",
    "33": "ccd9d035154f957d69baad22e972886af664ae53d0b55c8638abc286117cb39f",
    "34": "621ad93fd195ba87f39d1ea45874a0583fa343863279b34a227da4f32a015ca2",
    "35": "99f28059984400f431867c6006fd4ea056cf0e396907452960a06484b5619eca",
    "36": "f67c1d7224bd20a36cbb25b53112f84b817c29d35a4acefdf6a629f836a99419",
    "37": "234f099c94b7074bd3fce49f9e0bb99d7bb60c11f33c556d3f0b712954cf616a",
    "38": "778ee9f35712ce668f491185b1fc8874ee23a07357866634efd4712afbeb35f0",
    "39": "11774e4c11db80bf3226fb67608d826523705af49b5a501f6a348b9bd2212e3c",
    "40": "8ca9b5f7aeb30666a8a3168504c67b07c8da21daa67b91216a77f2af17ae4652",
    "41": "d78a37e5191acf65e1879907af0046f658c5b70ca1aa7f00878e21646d566a90",
    "42": "392f9dc85ff629e457d33754c8dcdf84a4fc8afdd5aaaaad4300a07613aa9e87",
    "43": "a801f11a64b8dee97d610a7ff0aa0ea510876235e6b9297b862db6c55e3460ae",
    "44": "4fa5f57a9629662ad5982629040e5d3b83c84be93a387892e52f89194b148598",
    "45": "756402d0116341cb5ec52f3864146d3f0ef8e64eb228aabded807f7258abdc05",
    "46": "98788a0354258031ad600719ea990e524001047dcdf54731ccb51f1944aab772",
    "47": "6338f22614b309a0306a6e94b3d0f934de0836185d62cf5009848adb0d92acc3",
    "48": "4628225067fe34d839f8241479968249ccc753229a134391e3a69d59bc17c4d6",
    "49": "d99dfb0f8ae463fadd8f5b482a3f68d65a50db16b35429eea2259bc586ac146c",
    "50": "eb554207800ac2f9aa109a04206911620305d63851ba39dbf839ee5158bf07c6",
    "51": "b72e151e46e786678c72618fe513246eb6a4b91da792dc61bb796aba9326b628",
    "52": "f4ff9f9fce8b577556a3f2cc5ed802e902113bbad6e06a03ea7fc893400e7218",
    "53": "b7794b0c59f76e82b8963e3970b4a155bc0bd97205e59012f98d3877d49bd1ce",
    "54": "f1b07c327c90e29512eaee01d35b7d42f56c5aa0ad3e4bd3a6729df7a8c29a8e",
    "55": "d881e8440001457fafd5089b61710e57610454b55dd97b990778c5340fa4a57b",
    "56": "c40c00542f7a8e78057e22959f5a7aebbf3eb2d74fbec7989fe41c9ed8fbd904",
    "57": "621aae796e48c86496c33aa761bac545f71cb7b51140cd3dc782f675192b747b",
    "58": "28ca4ca3ff0d9c8b8a930ba73efee3eac06a8f9752d6adfc788bef8cbbad42f6",
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
