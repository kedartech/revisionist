"""Every committed map passes the checker and is kept as an object named by its hash.

Needs neither the geometry tool nor the border data, so it runs in CI.
"""

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
THREE = Path(__file__).resolve().parent / "maps" / "three-areas.json"
GAP = Path(__file__).resolve().parent / "maps" / "counterexamples" / "gap.json"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("map_check", ROOT / "scripts" / "map_check.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mc = _load()
Loader: Any = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def problems(worlds: Path) -> list[str]:
    """What is wrong with the maps, their objects and the hashes named under ``worlds``."""
    out: list[str] = []
    objects = worlds / "maps" / "objects"
    for path in sorted((worlds / "maps").glob("*.json")):
        raw, sha = mc.load(path)
        out += [f"maps/{path.name}: {p}" for p in mc.check(raw)]
        if not (objects / f"{sha}.json").is_file():
            out.append(f"maps/{path.name}: no object {sha}.json")
    for obj in sorted(objects.glob("*.json")):
        if obj.stem != _sha(obj):
            out.append(f"maps/objects/{obj.name}: its content hashes to {_sha(obj)}")
    for path in sorted(worlds.rglob("*.yaml")):
        data = yaml.load(path.read_text(), Loader=Loader)
        ref = data.get("map") if isinstance(data, dict) else None
        if not isinstance(ref, dict) or "sha256" not in ref:
            continue
        name, sha = path.relative_to(worlds), str(ref["sha256"])
        found = mc.map_path(path, str(ref.get("file", "")))
        if found is None:
            out.append(f"{name}: its map file {ref.get('file')} is missing")
        elif _sha(found) != sha:
            out.append(f"{name}: names {sha}, but {found.name} hashes to {_sha(found)}")
        if not (objects / f"{sha}.json").is_file():
            out.append(f"{name}: names {sha}, which has no object")
    manifest = objects / "MANIFEST"
    if not manifest.is_file():
        return [*out, "maps/objects/MANIFEST is missing"]
    lines = manifest.read_text().splitlines()
    listed = [s.split()[0] for s in lines if s.strip() and not s.lstrip().startswith("#")]
    out += [f"MANIFEST: {s} has no object" for s in listed if not (objects / f"{s}.json").is_file()]
    out += [
        f"maps/objects/{obj.name}: not in the MANIFEST"
        for obj in sorted(objects.glob("*.json"))
        if obj.stem not in listed
    ]
    return out


def test_the_committed_maps_objects_and_world_hashes_hold() -> None:
    assert problems(ROOT / "worlds") == []


def tree(tmp_path: Path) -> Path:
    """A worlds directory holding the three-area map, its object and a world that names it."""
    worlds = tmp_path / "worlds"
    objects = worlds / "maps" / "objects"
    objects.mkdir(parents=True)
    shutil.copy(THREE, worlds / "maps" / "three-areas.json")
    sha = _sha(THREE)
    shutil.copy(THREE, objects / f"{sha}.json")
    (objects / "MANIFEST").write_text(f"# one hash per line, appended, never edited\n{sha}\n")
    world = {"world": "toy", "map": {"coords": "flat", "file": "three-areas.json", "sha256": sha}}
    (worlds / "toy.yaml").write_text(yaml.safe_dump(world))
    return worlds


def test_a_good_tree_passes(tmp_path: Path) -> None:
    assert problems(tree(tmp_path)) == []


def test_every_map_in_the_directory_is_checked(tmp_path: Path) -> None:
    worlds = tree(tmp_path)
    shutil.copy(GAP, worlds / "maps" / "late.json")
    found = problems(worlds)
    assert any(p.startswith("maps/late.json: box: ") for p in found), found
    assert any(p.startswith("maps/late.json: no object") for p in found), found


def test_a_world_whose_hash_differs_from_its_map_fails(tmp_path: Path) -> None:
    worlds = tree(tmp_path)
    data = json.loads(THREE.read_text())
    data["areas"]["marsh"]["label"] = [20, 20]
    (worlds / "maps" / "three-areas.json").write_text(json.dumps(data))
    assert any(p.startswith("toy.yaml: names ") and "hashes to" in p for p in problems(worlds))


def test_an_object_whose_name_is_not_its_hash_fails(tmp_path: Path) -> None:
    worlds = tree(tmp_path)
    objects = worlds / "maps" / "objects"
    shutil.copy(GAP, objects / f"{_sha(THREE)}.json")
    assert any("its content hashes to" in p for p in problems(worlds))


def test_a_hash_a_staging_world_names_needs_an_object(tmp_path: Path) -> None:
    worlds = tree(tmp_path)
    staging = worlds / "maps" / "src" / "toy"
    staging.mkdir(parents=True)
    sha = "1" * 64
    (staging / "south.world.yaml").write_text(
        yaml.safe_dump({"map": {"file": "three-areas.json", "sha256": sha}})
    )
    found = problems(worlds)
    assert f"maps/src/toy/south.world.yaml: names {sha}, which has no object" in found, found


def test_a_hash_in_the_manifest_needs_an_object(tmp_path: Path) -> None:
    worlds = tree(tmp_path)
    manifest = worlds / "maps" / "objects" / "MANIFEST"
    manifest.write_text(manifest.read_text() + "2" * 64 + "\n")
    assert f"MANIFEST: {'2' * 64} has no object" in problems(worlds)


def test_an_object_not_in_the_manifest_fails(tmp_path: Path) -> None:
    worlds = tree(tmp_path)
    manifest = worlds / "maps" / "objects" / "MANIFEST"
    manifest.write_text("# empty\n")
    assert f"maps/objects/{_sha(THREE)}.json: not in the MANIFEST" in problems(worlds)


def test_a_missing_manifest_fails(tmp_path: Path) -> None:
    worlds = tree(tmp_path)
    (worlds / "maps" / "objects" / "MANIFEST").unlink()
    assert problems(worlds) == ["maps/objects/MANIFEST is missing"]
