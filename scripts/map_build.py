"""Build a map file and its world fragment from a recipe and the cached border data.

Build-time only: the game never imports this script. It needs the geometry tool from the ``map``
dependency group (``uv run --group map python scripts/map_build.py build worlds/maps/src/<slug>``)
and the Natural Earth files in the directory ``REVISIONIST_MAP_DATA`` names, each checked against
the SHA-256 recorded in ``worlds/maps/SOURCES.md``. Nothing here reaches the network.

A recipe is one YAML file per region under ``worlds/maps/src/<slug>/``. The build dissolves each
territory's present-day provinces, cuts provinces along the recipe's lines, cuts each sea zone
from the ocean (the box less the land), leaves the rest of the box to the backdrop, simplifies every
border once for both its sides, derives the adjacency with the checker's predicate, runs the
checker, and writes ``<slug>.json``, ``<slug>.world.yaml`` and the map's object under ``objects/``.
The format is in ``worlds/maps/README.md``.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from types import ModuleType
from typing import Any

import shapely
import yaml
from shapely import affinity, ops
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.geometry import box as make_box
from shapely.geometry.polygon import orient
from shapely.strtree import STRtree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _load_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("map_check", HERE / "map_check.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


map_check = _load_check()

PROVINCES = "ne_10m_admin_1_states_provinces.geojson"
"""The admin-1 units: territories are dissolved from them, and they are the land on every coast."""
LAND = "ne_10m_land.geojson"
"""Land polygons: only the islands no unit holds or touches are taken from it."""
CODE = "adm1_code"
DEFAULT_TOLERANCE = 0.05
"""Simplify tolerance in degrees. [proposed]"""
GRID = 1 / map_check.SCALE
"""Every coordinate is snapped to the checker's 4 decimals before any overlay. [proposed]"""
LIST_KEYS = ("regions", "territories", "cuts", "sea_zones", "crossings")
MANIFEST_HEAD = (
    "# Map objects: one SHA-256 per line, each naming worlds/maps/objects/<sha256>.json.\n"
    "# Append only: a line is never edited or removed, and no object a stored game names is "
    "deleted.\n"
)

Geom = Any  # a shapely geometry; the tool ships no type information this repo checks


class BuildError(Exception):
    """The build refuses: the message names the file, province, cut, area or zone at fault."""


@dataclass(frozen=True)
class Built:
    map_path: Path
    world_path: Path
    sha256: str
    simplify: str


# ---------------------------------------------------------------- the recipe


def _recipe_files(paths: Sequence[Path]) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        files += sorted(p.glob("*.yaml")) if p.is_dir() else [p]
    if not files:
        raise BuildError("no recipe files found")
    return files


def read_recipes(paths: Sequence[Path]) -> dict[str, Any]:
    """The recipe files merged: their lists joined in file order, the one box they agree on."""
    merged: dict[str, Any] = {k: [] for k in LIST_KEYS}
    box: list[float] | None = None
    box_from = ""
    for f in _recipe_files(paths):
        doc = yaml.safe_load(f.read_text()) or {}
        if not isinstance(doc, dict):
            raise BuildError(f"{f.name}: a recipe is a mapping")
        unknown = sorted(set(doc) - {*LIST_KEYS, "map"})
        if unknown:
            raise BuildError(f"{f.name}: unknown keys {unknown}")
        if doc.get("map") is not None:
            raw = doc["map"].get("box") if isinstance(doc["map"], dict) else None
            if not (isinstance(raw, list) and len(raw) == 4):
                raise BuildError(f"{f.name}: map.box is not [west, south, east, north]")
            if box is not None and [float(c) for c in raw] != [float(c) for c in box]:
                raise BuildError(f"{f.name}: its box {raw} differs from {box_from}'s box {box}")
            box, box_from = raw, f.name
        for k in LIST_KEYS:
            merged[k] += list(doc.get(k) or [])
    if box is None:
        raise BuildError(
            "no recipe file gives the map box (map: {box: [west, south, east, north]})"
        )
    merged["box"] = box
    _check_keys(merged)
    return merged


def _check_keys(r: dict[str, Any]) -> None:
    regions = [str(g["key"]) for g in r["regions"]]
    areas = [str(a["key"]) for a in r["territories"] + r["sea_zones"]]
    for kind, keys in (("region", regions), ("area", areas)):
        seen: set[str] = set()
        for k in keys:
            if k in seen:
                raise BuildError(f"{k}: the {kind} key is given twice")
            seen.add(k)
    for a in r["territories"] + r["sea_zones"]:
        if str(a.get("region")) not in regions:
            raise BuildError(f"{a['key']}: its region {a.get('region')!r} is not listed")
    for z in r["sea_zones"]:
        if not (isinstance(z.get("polygon"), list) and len(z["polygon"]) >= 3):
            raise BuildError(f"{z['key']}: a sea zone needs a polygon of at least three points")
    terr = {str(t["key"]) for t in r["territories"]}
    for c in r["cuts"]:
        name = c.get("name", "?")
        if not (c.get("province") and isinstance(c.get("line"), list) and len(c["line"]) >= 2):
            raise BuildError(f"cut {name}: needs a province and a line of two or more points")
        if not (c.get("source") or c.get("gap")):
            raise BuildError(f"cut {name}: needs a source line (or gap: true)")
        sides = [c.get("left"), c.get("right")]
        if not any(sides):
            raise BuildError(f"cut {name}: names no territory for either side")
        for k in sides:
            if k and k not in terr:
                raise BuildError(f"cut {name}: {k} is not a territory")
    for x in r["crossings"]:
        for k in (x.get("a"), x.get("b")):
            if k not in areas:
                raise BuildError(f"crossing {x.get('name', '?')}: {k} is not an area")


# ---------------------------------------------------------------- the data


def recorded(sources: Path) -> dict[str, str]:
    """``file -> sha256`` from the table in SOURCES.md."""
    out: dict[str, str] = {}
    for line in Path(sources).read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.lstrip().startswith("|") and len(cells) >= 2 and len(cells[1]) == 64:
            out[cells[0]] = cells[1].lower()
    return out


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(data: Path, sources: Path, names: Sequence[str]) -> None:
    """Refuse, naming the file, when a data file is missing, unrecorded or other bytes."""
    rec = recorded(sources)
    for name in names:
        if name not in rec:
            raise BuildError(f"{name}: {Path(sources).name} records no SHA-256 for it")
        path = Path(data) / name
        if not path.is_file():
            raise BuildError(f"{name}: not found in {data}")
        got = _sha_file(path)
        if got != rec[name]:
            raise BuildError(
                f"{name}: its SHA-256 is {got}, but {Path(sources).name} records {rec[name]}"
            )


def _polygonal(g: Geom) -> Geom:
    """Only the polygons of ``g``, made valid and snapped to the grid."""
    if not g.is_valid:
        g = shapely.make_valid(g)
    parts = [p for p in shapely.get_parts(g) if p.geom_type in ("Polygon", "MultiPolygon")]
    return shapely.set_precision(shapely.union_all(parts), GRID) if parts else Polygon()


def _shifts(box: Sequence[float]) -> list[float]:
    """Longitude shifts that bring a unit into a box that crosses the date line."""
    out = [0.0]
    if box[2] > 180:
        out.append(360.0)
    if box[0] < -180:
        out.append(-360.0)
    return out


def _inside(g: Geom, frame: Geom, shifts: Sequence[float]) -> Geom | None:
    """The part of ``g`` inside the frame, taken across the date line too; None when nothing is."""
    pieces = []
    for dx in shifts:
        moved = affinity.translate(g, xoff=dx) if dx else g
        if moved.intersects(frame):
            pieces.append(_polygonal(moved).intersection(frame, grid_size=GRID))
    found = shapely.union_all(pieces, grid_size=GRID) if pieces else None
    if found is None or found.is_empty or found.area == 0:
        return None
    return _polygonal(found)


def load_units(path: Path, box: Sequence[float]) -> tuple[set[str], dict[str, Geom]]:
    """Every unit code in the file, and each unit's part inside the box (date line unwrapped)."""
    doc = json.loads(Path(path).read_text())
    frame = make_box(*box)
    shifts = _shifts(box)
    codes: set[str] = set()
    inside: dict[str, Geom] = {}
    for feat in doc["features"]:
        code = str(feat["properties"][CODE])
        codes.add(code)
        found = _inside(shape(feat["geometry"]), frame, shifts)
        if found is not None:
            inside[code] = found
    return codes, inside


def load_land(path: Path, box: Sequence[float], units: Geom) -> Geom:
    """The land inside the box: the units, and every island of the land file that no unit touches.

    The two files trace coasts a little apart; a sliver of the land file that touches a unit is that
    difference, not an island, and is left out so each coast stays the unit's own line.
    """
    doc = json.loads(Path(path).read_text())
    frame = make_box(*box)
    shifts = _shifts(box)
    found = [_inside(shape(f["geometry"]), frame, shifts) for f in doc["features"]]
    extra = [g for g in found if g is not None]
    if not extra:
        return units
    rest = _polygonal(shapely.union_all(extra, grid_size=GRID).difference(units, grid_size=GRID))
    islands = [p for p in shapely.get_parts(rest) if p.area > 0 and p.distance(units) > GRID]
    return shapely.union_all([units, *islands], grid_size=GRID)


# ---------------------------------------------------------------- dissolve and cut


def _owners(recipe: dict[str, Any], codes: set[str]) -> dict[str, str]:
    """Province code -> the territory (or ``cut <name>``) that claims it; refuses a double claim."""
    owner: dict[str, str] = {}
    for t in recipe["territories"]:
        for code in t.get("provinces") or []:
            if code not in codes:
                raise BuildError(
                    f"{code}: territory {t['key']} lists it, but the data has no such province"
                )
            if code in owner:
                raise BuildError(f"{code}: claimed by both {owner[code]} and {t['key']}")
            owner[code] = str(t["key"])
    for c in recipe["cuts"]:
        code = str(c["province"])
        if code not in codes:
            raise BuildError(f"cut {c['name']}: the data has no province {code}")
        if code in owner and not owner[code].startswith("cut "):
            raise BuildError(f"{code}: claimed by both {owner[code]} and cut {c['name']}")
        owner.setdefault(code, f"cut {c['name']}")
    return owner


def _side(piece: Geom, line: LineString) -> int:
    """+1 when the piece lies left of the line (walking from its first point), -1 when right."""
    p = piece.point_on_surface()
    pts = list(line.coords)
    best, sign = float("inf"), 0
    for (ax, ay), (bx, by) in pairwise(pts):
        d = LineString([(ax, ay), (bx, by)]).distance(p)
        cross = (bx - ax) * (p.y - ay) - (by - ay) * (p.x - ax)
        if d < best - 1e-12 and cross != 0:
            best, sign = d, 1 if cross > 0 else -1
    return sign


def split_sides(geom: Geom, line: LineString, name: str, code: str) -> tuple[Geom, Geom]:
    """The parts of ``geom`` left and right of the line; refuses a line that does not cross it."""
    ends = [Point(line.coords[0]), Point(line.coords[-1])]
    if any(geom.contains(e) for e in ends):
        raise BuildError(
            f"cut {name}: its line ends inside {code}; it must cross from edge to edge"
        )
    pieces = list(shapely.get_parts(ops.split(geom, line)))
    left = [p for p in pieces if _side(p, line) > 0]
    right = [p for p in pieces if _side(p, line) < 0]
    if len(pieces) < 2 or not left or not right:
        raise BuildError(f"cut {name}: its line does not cross {code} from edge to edge")
    return _polygonal(shapely.union_all(left)), _polygonal(shapely.union_all(right))


def territories(recipe: dict[str, Any], units: dict[str, Geom], codes: set[str]) -> dict[str, Geom]:
    """Each territory: its provinces dissolved, plus the cut parts the recipe gives it."""
    _owners(recipe, codes)
    parts: dict[str, list[Geom]] = defaultdict(list)
    for t in recipe["territories"]:
        parts[str(t["key"])] += [units[c] for c in t.get("provinces") or [] if c in units]
    by_province: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in recipe["cuts"]:
        by_province[str(c["province"])].append(c)
    for code, cuts in by_province.items():
        rest = units.get(code)
        for c in cuts:
            if rest is None or rest.is_empty:
                raise BuildError(
                    f"cut {c['name']}: nothing of {code} is left inside the box to cut"
                )
            line = LineString([(float(x), float(y)) for x, y in c["line"]])
            left, right = split_sides(rest, line, str(c["name"]), code)
            rest = None
            for key, part in ((c.get("left"), left), (c.get("right"), right)):
                if key:
                    parts[str(key)].append(part)
                else:
                    rest = part if rest is None else shapely.union_all([rest, part], grid_size=GRID)
        if rest is not None and not rest.is_empty:
            raise BuildError(f"{code}: a part its cuts give no territory is left over")
    out: dict[str, Geom] = {}
    for t in recipe["territories"]:
        key = str(t["key"])
        g = shapely.union_all(parts[key], grid_size=GRID) if parts[key] else Polygon()
        if g.is_empty or g.area == 0:
            raise BuildError(f"{key}: the territory has no land inside the box")
        out[key] = _polygonal(g)
    return out


def sea_zones(recipe: dict[str, Any], land: Geom, frame: Geom) -> dict[str, Geom]:
    """Each sea zone: its polygon cut from the ocean. Refuses two zones over the same water."""
    ocean = _polygonal(frame.difference(land, grid_size=GRID))
    out: dict[str, Geom] = {}
    for z in recipe["sea_zones"]:
        key = str(z["key"])
        poly = _polygonal(Polygon([(float(x), float(y)) for x, y in z["polygon"]]))
        g = _polygonal(poly.intersection(ocean, grid_size=GRID))
        if g.is_empty or g.area == 0:
            raise BuildError(f"{key}: the sea zone's polygon covers no ocean inside the box")
        for other, h in out.items():
            if g.intersection(h, grid_size=GRID).area > 0:
                raise BuildError(f"{key}: the sea zone covers water {other} already covers")
        out[key] = _polygonal(g)
    return out


# ---------------------------------------------------------------- one coverage of the box


def coverage(rough: list[tuple[str | None, Geom]], frame: Geom) -> list[tuple[str | None, Geom]]:
    """The faces noded together, so every vertex on a border is a vertex of both its sides.

    ``rough`` is (key, geometry), the backdrop as key ``None``. Every boundary is noded with every
    other and polygonized; each piece goes to the face it overlaps most; the pieces are joined per
    key.
    """
    lines = [g.boundary for _, g in rough] + [frame.boundary]
    noded = shapely.union_all(lines, grid_size=GRID)
    pieces = shapely.get_parts(shapely.polygonize(shapely.get_parts(noded)))
    return _assign(pieces, rough)


def _assign(pieces: Any, rough: list[tuple[str | None, Geom]]) -> list[tuple[str | None, Geom]]:
    geoms = [g for _, g in rough]
    tree = STRtree(geoms)
    got: dict[int, list[Geom]] = defaultdict(list)
    for p in pieces:
        cands = tree.query(p, predicate="intersects")
        if len(cands) == 0:
            raise BuildError(
                f"a piece of the map near {p.point_on_surface().coords[0]} has no face"
            )
        best = max(cands, key=lambda i: (p.intersection(geoms[i]).area, -i))
        got[int(best)].append(p)
    out = []
    for i, (key, _) in enumerate(rough):
        if got[i]:
            out.append((key, shapely.union_all(got[i], grid_size=GRID)))
        elif key is not None:
            raise BuildError(f"{key}: the area vanished when the borders were noded")
    return out


# ---------------------------------------------------------------- simplify together


def has_coverage_simplify() -> bool:
    """Whether the installed tool has GEOS coverage simplification (GEOS 3.12 or later)."""
    return hasattr(shapely, "coverage_simplify") and shapely.geos_version >= (3, 12, 0)


def simplify_coverage(
    faces: list[tuple[str | None, Geom]], tol: float
) -> list[tuple[str | None, Geom]]:
    """The tool's coverage simplifier: each shared edge is simplified once. The box edge is kept."""
    out = shapely.coverage_simplify([g for _, g in faces], tol, simplify_boundary=False)
    return [(k, shapely.set_precision(g, GRID)) for (k, _), g in zip(faces, out, strict=True)]


def _ends(line: Geom) -> set[tuple[float, float]]:
    c = list(line.coords)
    return {c[0], c[-1]}


def _crossing_arcs(arcs: list[Geom]) -> set[int]:
    """Arcs that cross themselves or meet another arc anywhere but at shared end points."""
    bad = {i for i, a in enumerate(arcs) if not a.is_simple}
    tree = STRtree(arcs)
    for i, a in enumerate(arcs):
        for j in tree.query(a):
            if j <= i:
                continue
            meet = a.intersection(arcs[j])
            if meet.is_empty:
                continue
            pts = {(p.x, p.y) for p in shapely.get_parts(meet) if p.geom_type == "Point"}
            if meet.geom_type not in ("Point", "MultiPoint") or not pts <= (
                _ends(a) & _ends(arcs[j])
            ):
                bad |= {i, int(j)}
    return bad


def simplify_arcs(
    faces: list[tuple[str | None, Geom]], tol: float
) -> list[tuple[str | None, Geom]]:
    """Split every border into arcs at its junctions, simplify each arc once, rebuild the faces.

    An arc that the simplification makes cross itself or another arc is simplified again with half
    the tolerance, down to none. Arcs on the box edge are left as they are.
    """
    frame = make_box(*shapely.total_bounds([g for _, g in faces]))
    noded = shapely.union_all([g.boundary for _, g in faces], grid_size=GRID)
    arcs = list(shapely.get_parts(shapely.line_merge(noded)))
    fixed = [a.covered_by(frame.exterior) for a in arcs]
    tols = [0.0 if f else tol for f in fixed]

    def simp(i: int) -> Geom:
        if tols[i] <= GRID:
            return arcs[i]
        s = shapely.simplify(arcs[i], tols[i], preserve_topology=False)
        if arcs[i].is_ring and len(s.coords) < 4:
            s = shapely.simplify(arcs[i], tols[i], preserve_topology=True)
        return s

    done = [simp(i) for i in range(len(arcs))]
    for _ in range(40):
        bad = _crossing_arcs(done)
        if not bad:
            break
        for i in bad:
            tols[i] = tols[i] / 2 if tols[i] > GRID else 0.0
            done[i] = simp(i)
    pieces = shapely.get_parts(shapely.polygonize(done))
    return _assign(pieces, faces)


# ---------------------------------------------------------------- the map file


def _q(v: float) -> float:
    r = round(float(v), 4)
    return 0.0 if r == 0 else r


def _parts_sorted(g: Geom) -> list[Polygon]:
    polys = [
        orient(p, 1.0) for p in shapely.get_parts(g) if p.geom_type == "Polygon" and p.area > 0
    ]
    return sorted(polys, key=lambda p: min((_q(x), _q(y)) for x, y in p.exterior.coords))


def _label(g: Geom) -> list[float]:
    big = max(_parts_sorted(g), key=lambda p: p.area)
    for cand in (
        ops.polylabel(big, tolerance=max(GRID, big.length / 2000)),
        big.point_on_surface(),
    ):
        pt = Point(_q(cand.x), _q(cand.y))
        if big.contains(pt) and big.exterior.distance(pt) > GRID / 2:
            return [pt.x, pt.y]
    pt = big.point_on_surface()
    return [_q(pt.x), _q(pt.y)]


class _Vertices:
    def __init__(self) -> None:
        self.points: list[list[float]] = []
        self.index: dict[tuple[float, float], int] = {}

    def ring(self, coords: Any) -> list[int]:
        pts = [(_q(x), _q(y)) for x, y in coords]
        pts = [p for i, p in enumerate(pts[:-1]) if i == 0 or p != pts[i - 1]]
        if pts and pts[-1] == pts[0]:
            pts.pop()
        start = pts.index(min(pts))
        pts = pts[start:] + pts[:start]
        out = []
        for p in [*pts, pts[0]]:
            if p not in self.index:
                self.index[p] = len(self.points)
                self.points.append([p[0], p[1]])
            out.append(self.index[p])
        return out

    def rings(self, g: Geom) -> list[list[int]]:
        out = []
        for p in _parts_sorted(g):
            out.append(self.ring(p.exterior.coords))
            holes = sorted(p.interiors, key=lambda h: min((_q(x), _q(y)) for x, y in h.coords))
            out += [self.ring(h.coords) for h in holes]
        return out


def map_document(faces: list[tuple[str | None, Geom]], box: list[Any]) -> dict[str, Any]:
    v = _Vertices()
    areas = {str(k): {"rings": v.rings(g), "label": _label(g)} for k, g in faces if k is not None}
    back = shapely.union_all([g for k, g in faces if k is None], grid_size=GRID)
    backdrop = v.rings(back) if not back.is_empty else []
    return {
        "format": 1,
        "coords": "lonlat",
        "box": box,
        "vertices": v.points,
        "areas": areas,
        "backdrop": backdrop,
    }


def dump_map(doc: dict[str, Any]) -> bytes:
    """The map as JSON, one vertex and one area per line, the same bytes for the same document."""

    def c(x: Any) -> str:
        return json.dumps(x, separators=(",", ":"))

    lines = [
        f'{{"format":{doc["format"]},"coords":{c(doc["coords"])},"box":{c(doc["box"])},',
        '"vertices":[',
        ",\n".join(c(p) for p in doc["vertices"]),
        '],"areas":{',
        ",\n".join(f"{c(k)}:{c(a)}" for k, a in doc["areas"].items()),
        f'}},"backdrop":{c(doc["backdrop"])}}}',
    ]
    return ("\n".join(lines) + "\n").encode()


# ---------------------------------------------------------------- the world fragment


def _flow(item: Any) -> str:
    text: str = yaml.safe_dump(item, default_flow_style=True, width=10_000, sort_keys=False)
    return text.strip()


def world_fragment(
    recipe: dict[str, Any], raw: dict[str, Any], slug: str, sha: str, how: str, tol: float
) -> str:
    """Regions, territories, sea zones and adjacency, as a world file writes them."""
    derived = map_check.adjacency(raw)
    crossings = {}
    for x in recipe["crossings"]:
        a, b = sorted((str(x["a"]), str(x["b"])))
        crossings[(a, b)] = {"a": a, "b": b, "crossing": str(x.get("name") or "a crossing")}
    head = {"coords": "lonlat", "file": f"{slug}.json", "sha256": sha, "box": recipe["box"]}
    lines = [
        f"# Built by scripts/map_build.py from the recipe {slug}; "
        f"simplify {how}, tolerance {tol:g}.",
        "# Do not edit by hand: change the recipe and build again.",
        f"map: {_flow(head)}",
        "regions:",
        *(f"  - {_flow({'key': g['key'], 'name': g['name']})}" for g in recipe["regions"]),
        "territories:",
    ]
    keep = ("key", "name", "region", "terrain", "sites")
    for t in recipe["territories"]:
        lines.append(f"  - {_flow({k: t[k] for k in keep if k in t})}")
    lines.append("sea_zones:" if recipe["sea_zones"] else "sea_zones: []")
    for z in recipe["sea_zones"]:
        lines.append(
            f"  - {_flow({k: z[k] for k in ('key', 'name', 'region', 'terrain') if k in z})}"
        )
    pairs = [list(p) for p in derived if tuple(p) not in crossings]
    entries: list[Any] = pairs + [crossings[k] for k in sorted(crossings)]
    lines.append("adjacency:" if entries else "adjacency: []")
    lines += [f"  - {_flow(e)}" for e in entries]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- the build


def _write_object(out: Path, sha: str, data: bytes) -> None:
    objects = out / "objects"
    obj = objects / f"{sha}.json"
    objects.mkdir(parents=True, exist_ok=True)
    if not obj.exists():
        obj.write_bytes(data)
    manifest = objects / "MANIFEST"
    text = manifest.read_text() if manifest.exists() else MANIFEST_HEAD
    if sha not in text.split():
        text = (text if text.endswith("\n") or not text else text + "\n") + sha + "\n"
    manifest.write_text(text)


def build(
    recipes: Sequence[Path],
    *,
    data: Path,
    sources: Path,
    out: Path,
    slug: str,
    simplify: str = "auto",
    tolerance: float = DEFAULT_TOLERANCE,
) -> Built:
    """Build the map and its world fragment into ``out``; refuse with ``BuildError``."""
    recipe = read_recipes(recipes)
    verify(data, sources, [PROVINCES, LAND])
    how = simplify if simplify != "auto" else ("coverage" if has_coverage_simplify() else "arcs")
    if how not in ("coverage", "arcs"):
        raise BuildError(f"simplify {simplify!r}: not auto, coverage or arcs")
    if how == "coverage" and not has_coverage_simplify():
        raise BuildError("simplify coverage: the installed tool has no coverage_simplify")
    box = [float(c) for c in recipe["box"]]
    frame = make_box(*box)
    codes, units = load_units(Path(data) / PROVINCES, box)
    terr = territories(recipe, units, codes)
    held = shapely.union_all(list(units.values()), grid_size=GRID) if units else Polygon()
    land = load_land(Path(data) / LAND, box, held)
    seas = sea_zones(recipe, land, frame)
    rough: list[tuple[str | None, Geom]] = [*terr.items(), *seas.items()]
    taken = shapely.union_all([g for _, g in rough], grid_size=GRID)
    back = _polygonal(frame.difference(taken, grid_size=GRID))
    if not back.is_empty and back.area > 0:
        rough.append((None, back))
    faces = coverage(rough, frame)
    if tolerance > 0:
        faces = (
            simplify_coverage(faces, tolerance)
            if how == "coverage"
            else simplify_arcs(faces, tolerance)
        )
    raw = map_document(faces, recipe["box"])
    problems = map_check.check(raw)
    if problems:
        raise BuildError("the built map fails the check:\n" + "\n".join(map(str, problems)))
    data_bytes = dump_map(raw)
    sha = hashlib.sha256(data_bytes).hexdigest()
    world = world_fragment(recipe, raw, slug, sha, how, tolerance)
    out = Path(out)
    obj = out / "objects" / f"{sha}.json"
    if obj.exists() and obj.read_bytes() != data_bytes:
        raise BuildError(
            f"objects/{sha}.json exists with other bytes; an object is never overwritten"
        )
    out.mkdir(parents=True, exist_ok=True)
    map_path, world_path = out / f"{slug}.json", out / f"{slug}.world.yaml"
    map_path.write_bytes(data_bytes)
    world_path.write_text(world)
    _write_object(out, sha, data_bytes)
    return Built(map_path, world_path, sha, how)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="map_build.py", description=(__doc__ or "").split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build <slug>.json and <slug>.world.yaml from recipe files")
    b.add_argument("recipe", nargs="+", type=Path, help="recipe files or their directory")
    b.add_argument("--slug", help="the map's name (default: the recipe directory's name)")
    b.add_argument("--data", type=Path, default=os.environ.get("REVISIONIST_MAP_DATA"))
    b.add_argument("--sources", type=Path, default=ROOT / "worlds" / "maps" / "SOURCES.md")
    b.add_argument("--out", type=Path, default=ROOT / "worlds" / "maps")
    b.add_argument("--simplify", choices=("auto", "coverage", "arcs"), default="auto")
    b.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    args = parser.parse_args(argv)
    if args.data is None:
        parser.error("no data directory: set REVISIONIST_MAP_DATA or pass --data")
    first = args.recipe[0]
    slug = args.slug or (first.name if first.is_dir() else first.parent.name)
    try:
        built = build(
            args.recipe,
            data=args.data,
            sources=args.sources,
            out=args.out,
            slug=slug,
            simplify=args.simplify,
            tolerance=args.tolerance,
        )
    except BuildError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print(f"{built.sha256}  {built.map_path}")
    print(f"world fragment: {built.world_path} (simplify {built.simplify})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
