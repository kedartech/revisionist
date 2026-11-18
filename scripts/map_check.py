"""The map file checker, the one adjacency predicate, and the proof sheet.

A map file (``worlds/maps/<slug>.json``) holds a shared vertex list, the playable areas as
rings of vertex indices with a label point, and a ``backdrop`` of rings drawn and not in play.
``worlds/maps/README.md`` gives the format; this module reads it with the standard library
alone, and PyYAML for world files. The build (``scripts/map_build.py``) imports ``adjacent``
from here, so there is one definition of which areas touch.

Usage::

    python scripts/map_check.py check MAP.json
    python scripts/map_check.py check --world WORLD.yaml
    python scripts/map_check.py check --region STAGING.yaml
    python scripts/map_check.py adjacency MAP.json
    python scripts/map_check.py render MAP.json [--world W] [--recipe R ...] [--out DIR]

Coordinates are rounded to 4 decimals before any comparison and then held as integers
(ten-thousandths), so every test of position, orientation and crossing is exact.
"""

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import yaml

SCALE = 10_000  # 4 decimals
MIN_AREA = {"lonlat": 0.05, "flat": 25.0}  # square degrees, square units
MIN_SHARED = {"lonlat": 0.1, "flat": 2.0}  # degrees, units
EPS = 1e-9

Pt = tuple[int, int]
Seg = tuple[Pt, Pt]

_Loader: Any = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


@dataclass(frozen=True)
class Problem:
    """One failure, named by the face (an area key, ``backdrop N``, ``box`` or ``map``)."""

    code: str
    face: str
    text: str

    def __str__(self) -> str:
        return f"{self.face}: {self.text}"


@dataclass
class Report:
    problems: list[Problem] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- reading


@dataclass
class Ring:
    face: str
    index: int  # the ring's place in its face's list, from 1
    pts: list[Pt]  # closed: pts[0] == pts[-1]
    hole: bool
    outer: int  # index of the outer ring of its part (itself when outer)


@dataclass
class Face:
    name: str
    playable: bool
    rings: list[Ring]
    vertices: set[int]  # indices into the vertex list


@dataclass
class Map:
    coords: str
    box: tuple[int, int, int, int]
    faces: list[Face]
    labels: dict[str, Pt]

    def area_face(self, key: str) -> Face:
        for f in self.faces:
            if f.playable and f.name == key:
                return f
        raise KeyError(key)

    @property
    def areas(self) -> list[str]:
        return [f.name for f in self.faces if f.playable]


def q(v: float) -> int:
    return round(v * SCALE)


def unq(v: int) -> float:
    return v / SCALE


def load(path: Path) -> tuple[Any, str]:
    """The parsed file and the SHA-256 of its bytes."""
    data = Path(path).read_bytes()
    return json.loads(data), hashlib.sha256(data).hexdigest()


def _num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def _pair(v: Any) -> bool:
    return isinstance(v, list) and len(v) == 2 and all(_num(c) for c in v)


def _structure(raw: Any) -> list[Problem]:
    def bad(face: str, text: str) -> Problem:
        return Problem("format", face, text)

    if not isinstance(raw, dict):
        return [bad("map", "the file is not a JSON object")]
    out = []
    if raw.get("format") != 1:
        out.append(bad("map", f"format is {raw.get('format')!r}, not 1"))
    if raw.get("coords") not in MIN_AREA:
        out.append(bad("map", f"coords is {raw.get('coords')!r}, not lonlat or flat"))
    box = raw.get("box")
    if not (isinstance(box, list) and len(box) == 4 and all(_num(c) for c in box)):
        out.append(bad("map", "box is not [west, south, east, north]"))
    elif not (box[0] < box[2] and box[1] < box[3]):
        out.append(bad("map", "box has west >= east or south >= north"))
    verts = raw.get("vertices")
    if not (isinstance(verts, list) and all(_pair(v) for v in verts)):
        return [*out, bad("map", "vertices is not a list of [x, y] pairs")]
    areas, backdrop = raw.get("areas"), raw.get("backdrop", [])
    if not (isinstance(areas, dict) and areas):
        return [*out, bad("map", "areas is not a non-empty object")]
    if not isinstance(backdrop, list):
        return [*out, bad("map", "backdrop is not a list of rings")]

    def rings_ok(face: str, rings: Any) -> None:
        if not (isinstance(rings, list) and rings):
            out.append(bad(face, "rings is not a non-empty list"))
            return
        for n, ring in enumerate(rings, 1):
            if not (isinstance(ring, list) and all(isinstance(i, int) for i in ring)):
                out.append(bad(face, f"ring {n} is not a list of vertex indices"))
            elif any(not 0 <= i < len(verts) for i in ring):
                out.append(bad(face, f"ring {n} names a vertex index that does not exist"))

    for key, a in areas.items():
        if not (isinstance(a, dict) and _pair(a.get("label"))):
            out.append(bad(str(key), "an area needs rings and a label [x, y]"))
            continue
        rings_ok(str(key), a.get("rings"))
    if backdrop:
        rings_ok("backdrop", backdrop)
    return out


def _parts(face: str, rings: list[list[Pt]], playable: bool) -> list[Face]:
    """Group rings into parts (outer ring, then its holes). The backdrop gives one face per part."""
    built: list[Ring] = []
    outer = 0
    for n, pts in enumerate(rings, 1):
        hole = _signed2(pts) < 0
        if not hole:
            outer = n
        built.append(Ring(face, n, pts, hole, outer or n))
    if playable:
        return [Face(face, True, built, set())]
    faces: list[Face] = []
    for r in built:
        if not r.hole or not faces:
            faces.append(Face(f"backdrop {len(faces) + 1}", False, [], set()))
        r.face = faces[-1].name
        faces[-1].rings.append(r)
    return faces


def parse(raw: Any) -> Map:
    """The map with rounded integer coordinates; ``raw`` must have passed ``_structure``."""
    verts = [(q(x), q(y)) for x, y in raw["vertices"]]
    faces: list[Face] = []
    for key, a in raw["areas"].items():
        (face,) = _parts(str(key), [[verts[i] for i in r] for r in a["rings"]], True)
        face.vertices = {i for r in a["rings"] for i in r}
        faces.append(face)
    back = raw.get("backdrop", [])
    for face in _parts("backdrop", [[verts[i] for i in r] for r in back], False):
        face.vertices = {i for r in face.rings for i in back[r.index - 1]}
        faces.append(face)
    w, s, e, n = (q(c) for c in raw["box"])
    labels = {str(k): (q(a["label"][0]), q(a["label"][1])) for k, a in raw["areas"].items()}
    return Map(raw["coords"], (w, s, e, n), faces, labels)


# ---------------------------------------------------------------- exact geometry


def _signed2(pts: Sequence[Pt]) -> int:
    """Twice the signed area of a closed ring: positive when counter-clockwise."""
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in pairwise(pts))


def _cross(o: Pt, a: Pt, b: Pt) -> int:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(p: Pt, a: Pt, b: Pt) -> bool:
    """``p`` lies on the closed segment ``a``-``b``."""
    return (
        _cross(a, b, p) == 0
        and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    )


def _touch(s: Seg, t: Seg) -> bool:
    """The two closed segments share at least one point."""
    (a, b), (c, d) = s, t
    d1, d2, d3, d4 = _cross(c, d, a), _cross(c, d, b), _cross(a, b, c), _cross(a, b, d)
    if ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4)):
        return True
    return (
        _on_segment(a, c, d) or _on_segment(b, c, d) or _on_segment(c, a, b) or _on_segment(d, a, b)
    )


def _proper(s: Seg, t: Seg) -> bool:
    """The segments cross at a point inside both, not at an end of either."""
    (a, b), (c, d) = s, t
    d1, d2, d3, d4 = _cross(c, d, a), _cross(c, d, b), _cross(a, b, c), _cross(a, b, d)
    return ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4))


def _edges(pts: Sequence[Pt]) -> Iterator[Seg]:
    return pairwise(pts)


def _in_ring(p: Pt, pts: Sequence[Pt]) -> int:
    """1 strictly inside the closed ring, 0 on it, -1 outside."""
    inside = False
    for a, b in _edges(pts):
        if _on_segment(p, a, b):
            return 0
        if (a[1] > p[1]) != (b[1] > p[1]):
            # the edge crosses the horizontal through p; is the crossing right of p?
            c = _cross(a, b, p)
            if (c > 0) == (b[1] > a[1]):
                inside = not inside
    return 1 if inside else -1


def _in_face(p: Pt, face: Face) -> int:
    """1 strictly inside the face, 0 on its boundary, -1 outside (a hole is outside)."""
    best = -1
    for r in face.rings:
        if r.hole:
            continue
        where = _in_ring(p, r.pts)
        if where < 0:
            continue
        if where == 0:
            best = 0
            continue
        holes = [h for h in face.rings if h.hole and h.outer == r.index]
        hw = [_in_ring(p, h.pts) for h in holes]
        if any(w == 0 for w in hw):
            best = 0
        elif not any(w > 0 for w in hw):
            return 1
    return best


def _bbox(pts: Iterable[Pt]) -> tuple[int, int, int, int]:
    xs, ys = zip(*pts, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


class _Grid:
    """Buckets segments and points by cell, so the crossing tests look only at near things."""

    def __init__(self, box: tuple[int, int, int, int], items: int) -> None:
        w, s, e, n = box
        cells = max(1, min(512, int(math.sqrt(max(items, 1)) / 2)))
        self.x0, self.y0 = w, s
        self.size = max(1, -(-max(e - w, n - s) // cells))
        self.cells: dict[tuple[int, int], list[int]] = defaultdict(list)

    def _span(self, bb: tuple[int, int, int, int]) -> Iterator[tuple[int, int]]:
        x1, y1 = (bb[0] - self.x0) // self.size, (bb[1] - self.y0) // self.size
        x2, y2 = (bb[2] - self.x0) // self.size, (bb[3] - self.y0) // self.size
        for i in range(x1, x2 + 1):
            for j in range(y1, y2 + 1):
                yield i, j

    def add(self, n: int, bb: tuple[int, int, int, int]) -> None:
        for c in self._span(bb):
            self.cells[c].append(n)

    def near(self, bb: tuple[int, int, int, int]) -> set[int]:
        return {n for c in self._span(bb) for n in self.cells.get(c, ())}


# ---------------------------------------------------------------- the check


def check(raw: Any) -> list[Problem]:
    """Every failure of rule 2 of the format, each naming its face; empty when the map is sound."""
    out = _structure(raw)
    if out:
        return out
    m = parse(raw)
    out = _rings(m)
    if out:
        return out
    out = _box(m) + _crossings(m)
    if any(p.code == "ring" for p in out):
        return _dedupe(out)
    out += _holes(m) + _t_junctions(m)
    covered = _coverage(m)
    if covered:
        # Faces that tile the box (every edge matched, the box edges covered) cannot overlap,
        # so the search for which faces overlap runs only when the cover is broken.
        out += _overlaps(m, {(p.face, p.text) for p in out if p.code == "overlap"})
    out += covered + _small(m) + _labels(m)
    return _dedupe(out)


def _dedupe(problems: list[Problem]) -> list[Problem]:
    return list(dict.fromkeys(problems))


def _fmt(p: Pt) -> str:
    return f"({unq(p[0]):g}, {unq(p[1]):g})"


def _rings(m: Map) -> list[Problem]:
    out = []
    for f in m.faces:
        for r in f.rings:
            name = f"ring {r.index}"
            pts = r.pts
            if len(pts) < 2 or pts[0] != pts[-1]:
                out.append(
                    Problem("ring", f.name, f"{name} is open: its last vertex is not its first")
                )
                continue
            if len(set(pts)) < 3:
                out.append(Problem("ring", f.name, f"{name} has fewer than three corners"))
                continue
            if any(a == b for a, b in _edges(pts)):
                out.append(Problem("ring", f.name, f"{name} repeats a vertex in a row"))
                continue
            if len(set(pts[:-1])) != len(pts) - 1:
                out.append(Problem("ring", f.name, f"{name} passes through one point twice"))
                continue
            if r.index == 1 and r.hole:
                out.append(
                    Problem(
                        "ring",
                        f.name,
                        "ring 1 runs clockwise; an outer ring runs counter-clockwise",
                    )
                )
            segs = list(_edges(pts))
            for (a, b), (_, c) in zip(segs, [*segs[1:], segs[0]], strict=True):
                if (
                    _cross(a, b, c) == 0
                    and (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) < 0
                ):
                    out.append(Problem("ring", f.name, f"{name} turns back on itself at {_fmt(b)}"))
                    break
    return out


def _box(m: Map) -> list[Problem]:
    w, s, e, n = m.box
    out = []
    for f in m.faces:
        for r in f.rings:
            far = [p for p in r.pts if not (w <= p[0] <= e and s <= p[1] <= n)]
            if far:
                out.append(Problem("box", f.name, f"vertex {_fmt(far[0])} lies outside the box"))
                break
    return out


def _holes(m: Map) -> list[Problem]:
    out = []
    for f in m.faces:
        for h in f.rings:
            if not h.hole:
                continue
            outer = next(r for r in f.rings if r.index == h.outer)
            where = [_in_ring(p, outer.pts) for p in h.pts[:-1]]
            if any(w < 0 for w in where) or all(w == 0 for w in where):
                out.append(
                    Problem(
                        "hole",
                        f.name,
                        f"hole ring {h.index} is not inside its outer ring {outer.index}",
                    )
                )
    return out


def _all_segments(m: Map) -> tuple[list[tuple[Face, Ring, int, Seg]], _Grid]:
    segs = [(f, r, i, s) for f in m.faces for r in f.rings for i, s in enumerate(_edges(r.pts))]
    grid = _Grid(m.box, len(segs))
    for n, (*_, s) in enumerate(segs):
        grid.add(n, _bbox(s))
    return segs, grid


def _crossings(m: Map) -> list[Problem]:
    """Edges of two rings that cross: in one face a ring or hole fault, across faces an overlap."""
    segs, grid = _all_segments(m)
    out = []
    for n, (f, r, i, s) in enumerate(segs):
        for k in grid.near(_bbox(s)):
            if k <= n:
                continue
            g, t, j, u = segs[k]
            if t is r:
                last = len(r.pts) - 2
                if abs(i - j) > 1 and {i, j} != {0, last} and _touch(s, u):
                    out.append(
                        Problem("ring", f.name, f"ring {r.index} crosses itself near {_fmt(s[0])}")
                    )
                continue
            if not _proper(s, u):
                continue
            if g is not f:
                out.append(
                    Problem(
                        "overlap",
                        f.name,
                        f"overlaps {g.name}: their borders cross near {_fmt(s[0])}",
                    )
                )
                out.append(
                    Problem(
                        "overlap",
                        g.name,
                        f"overlaps {f.name}: their borders cross near {_fmt(u[0])}",
                    )
                )
            elif t.hole or r.hole:
                hole = t if t.hole else r
                out.append(
                    Problem(
                        "hole",
                        f.name,
                        f"hole ring {hole.index} crosses ring {r.index if hole is t else t.index}",
                    )
                )
            else:
                out.append(Problem("ring", f.name, f"rings {r.index} and {t.index} cross"))
    return out


def _t_junctions(m: Map) -> list[Problem]:
    """A vertex on another face's edge that that face does not use: a border that looks shared."""
    points: dict[Pt, set[str]] = defaultdict(set)
    for f in m.faces:
        for r in f.rings:
            for p in r.pts:
                points[p].add(f.name)
    keys = list(points)
    grid = _Grid(m.box, len(keys))
    for n, p in enumerate(keys):
        grid.add(n, (p[0], p[1], p[0], p[1]))
    out = []
    for f in m.faces:
        for r in f.rings:
            for a, b in _edges(r.pts):
                for k in grid.near(_bbox((a, b))):
                    p = keys[k]
                    if p in (a, b) or not _on_segment(p, a, b):
                        continue
                    text = f"vertex {_fmt(p)} lies on an edge of {f.name}, which lacks it"
                    out += [
                        Problem("vertex", owner, text) for owner in sorted(points[p] - {f.name})
                    ]
    return out


def _overlaps(m: Map, known: set[tuple[str, str]]) -> list[Problem]:
    """Faces whose interiors overlap without crossing borders: duplicates and one inside another."""
    directed: dict[Seg, list[str]] = defaultdict(list)
    for f in m.faces:
        for r in f.rings:
            for s in _edges(r.pts):
                directed[s].append(f.name)
    out = []
    pairs: set[tuple[str, str]] = set()
    for names in directed.values():
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                if a != b:
                    pairs.add((a, b) if a < b else (b, a))
    boxes = {f.name: _bbox(p for r in f.rings for p in r.pts) for f in m.faces}
    byname = {f.name: f for f in m.faces}
    for i, f in enumerate(m.faces):
        for g in m.faces[i + 1 :]:
            fb, gb = boxes[f.name], boxes[g.name]
            if fb[2] < gb[0] or gb[2] < fb[0] or fb[3] < gb[1] or gb[3] < fb[1]:
                continue
            key = (f.name, g.name) if f.name < g.name else (g.name, f.name)
            if key not in pairs and (_ring_inside(f, g, gb) or _ring_inside(g, f, fb)):
                pairs.add(key)
    for a, b in sorted(pairs):
        for x, y in ((a, b), (b, a)):
            text = f"overlaps {y}: one lies over the other"
            if not any(t.startswith(f"overlaps {y}:") for face, t in known if face == x):
                out.append(Problem("overlap", byname[x].name, text))
    return out


def _ring_inside(f: Face, g: Face, gb: tuple[int, int, int, int]) -> bool:
    """Some ring of ``f`` runs through the interior of ``g``."""
    corners = _points(g)
    sides = {e for r in g.rings for a, b in _edges(r.pts) for e in ((a, b), (b, a))}
    for r in f.rings:
        for p in r.pts[:-1]:
            if p not in corners and gb[0] <= p[0] <= gb[2] and gb[1] <= p[1] <= gb[3]:
                if _in_face(p, g) > 0:
                    return True
        for a, b in _edges(r.pts):
            if a in corners and b in corners and (a, b) not in sides:
                mid: Any = (Fraction(a[0] + b[0], 2), Fraction(a[1] + b[1], 2))
                if _in_face(mid, g) > 0:
                    return True
    return False


def _coverage(m: Map) -> list[Problem]:
    """The areas and the backdrop cover the box exactly, by area sum and by edge use."""
    w, s, e, n = m.box
    out = []
    total = sum(_signed2(r.pts) for f in m.faces for r in f.rings)
    want = 2 * (e - w) * (n - s)
    if total != want:
        out.append(
            Problem(
                "coverage",
                "box",
                f"the faces cover {total / 2 / SCALE**2:g} of the box's {want / 2 / SCALE**2:g}",
            )
        )
    use: dict[Seg, list[str]] = defaultdict(list)
    for f in m.faces:
        for r in f.rings:
            for seg in _edges(r.pts):
                use[seg].append(f.name)

    def side(seg: Seg) -> str | None:
        (x1, y1), (x2, y2) = seg
        if y1 == y2 == s and x2 > x1:
            return "south"
        if x1 == x2 == e and y2 > y1:
            return "east"
        if y1 == y2 == n and x2 < x1:
            return "north"
        if x1 == x2 == w and y2 < y1:
            return "west"
        return None

    covered = {"south": 0, "east": 0, "north": 0, "west": 0}
    for seg, names in sorted(use.items()):
        if len(names) > 1:
            continue  # used twice the same way: already an overlap
        back = use.get((seg[1], seg[0]), [])
        edge = side(seg)
        if edge and not back:
            covered[edge] += abs(seg[1][0] - seg[0][0]) + abs(seg[1][1] - seg[0][1])
        elif len(back) != 1:
            out.append(
                Problem(
                    "edge",
                    names[0],
                    f"edge {_fmt(seg[0])} to {_fmt(seg[1])} has no face on its other side",
                )
            )
    lengths = {"south": e - w, "north": e - w, "east": n - s, "west": n - s}
    for edge, length in lengths.items():
        if covered[edge] != length:
            out.append(
                Problem(
                    "coverage",
                    "box",
                    f"the {edge} edge of the box is covered for "
                    f"{unq(covered[edge]):g} of {unq(length):g}",
                )
            )
    return out


def _area2(face: Face) -> int:
    return sum(_signed2(r.pts) for r in face.rings)


def _small(m: Map) -> list[Problem]:
    least = MIN_AREA[m.coords]
    out = []
    for f in m.faces:
        size = _area2(f) / 2 / SCALE**2
        if f.playable and size < least:
            out.append(
                Problem("small", f.name, f"its area {size:g} is below the minimum {least:g}")
            )
    return out


def _labels(m: Map) -> list[Problem]:
    out = []
    for f in m.faces:
        if not f.playable:
            continue
        where = _in_face(m.labels[f.name], f)
        if where < 1:
            place = "on its border" if where == 0 else "outside it"
            out.append(Problem("label", f.name, f"label {_fmt(m.labels[f.name])} lies {place}"))
    return out


# ---------------------------------------------------------------- adjacency


def _line_key(a: Pt, b: Pt) -> tuple[tuple[int, int, int], int, int]:
    """The segment's line (reduced direction and offset) and its span along that line."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    g = math.gcd(dx, dy)
    dx, dy = dx // g, dy // g
    if dx < 0 or (dx == 0 and dy < 0):
        dx, dy = -dx, -dy
    off = dy * a[0] - dx * a[1]
    t1, t2 = dx * a[0] + dy * a[1], dx * b[0] + dy * b[1]
    return (dx, dy, off), min(t1, t2), max(t1, t2)


def _shared(m: Map) -> dict[tuple[str, str], float]:
    """The length of border each touching pair of areas shares, collinear pieces merged."""
    lines: dict[tuple[int, int, int], list[tuple[int, int, str]]] = defaultdict(list)
    for f in m.faces:
        if not f.playable:
            continue
        for r in f.rings:
            for a, b in _edges(r.pts):
                key, t1, t2 = _line_key(a, b)
                lines[key].append((t1, t2, f.name))
    out: dict[tuple[str, str], float] = defaultdict(float)
    for (dx, dy, _), spans in lines.items():
        unit = math.hypot(dx, dy) * SCALE
        spans.sort()
        for i, (_, a2, fa) in enumerate(spans):
            for b1, b2, fb in spans[i + 1 :]:
                if b1 >= a2:
                    break
                if fa != fb:
                    pair = (fa, fb) if fa < fb else (fb, fa)
                    out[pair] += (min(a2, b2) - b1) / unit
    return dict(out)


def _parse_checked(raw: Any) -> Map:
    problems = _structure(raw)
    if problems:
        raise ValueError("; ".join(map(str, problems)))
    return parse(raw)


def shared_length(raw: Any, a: str, b: str) -> float:
    """The length of border areas ``a`` and ``b`` share (degrees or units)."""
    m = _parse_checked(raw)
    for key in (a, b):
        m.area_face(key)
    return _shared(m).get((a, b) if a < b else (b, a), 0.0)


def _adjacent(m: Map, lengths: dict[tuple[str, str], float], a: str, b: str) -> bool:
    """The rule itself, given the shared lengths ``_shared`` measured."""
    return lengths.get((a, b) if a < b else (b, a), 0.0) + EPS >= MIN_SHARED[m.coords]


def adjacent(raw: Any, a: str, b: str) -> bool:
    """The one adjacency predicate: the shared border is at least ``MIN_SHARED`` long.

    Two areas meeting at a corner share no length and are not adjacent; a length exactly at
    the threshold counts. ``adjacency`` and the build both decide with it.
    """
    m = _parse_checked(raw)
    for key in (a, b):
        m.area_face(key)
    return _adjacent(m, _shared(m), a, b)


def _points(face: Face) -> set[Pt]:
    return {p for r in face.rings for p in r.pts}


def adjacency(raw: Any) -> list[tuple[str, str]]:
    """Every pair of areas the predicate accepts, each pair sorted, the list sorted."""
    m = _parse_checked(raw)
    lengths = _shared(m)
    owners: dict[Pt, set[str]] = defaultdict(set)
    for f in m.faces:
        if f.playable:
            for p in _points(f):
                owners[p].add(f.name)
    touching = set(lengths)
    for names in owners.values():
        ordered = sorted(names)
        touching |= {(x, y) for i, x in enumerate(ordered) for y in ordered[i + 1 :]}
    return sorted(pair for pair in touching if _adjacent(m, lengths, *pair))


def area(raw: Any, key: str) -> float:
    """An area's size: square degrees or square units, holes taken out."""
    return _area2(_parse_checked(raw).area_face(key)) / 2 / SCALE**2


def locate(raw: Any, x: float, y: float) -> tuple[list[str], list[str]]:
    """The areas that hold the point inside, and the areas on whose border it lies."""
    return _locate(_parse_checked(raw), (q(x), q(y)))


def _locate(m: Map, p: Pt) -> tuple[list[str], list[str]]:
    inside, border = [], []
    for f in m.faces:
        if f.playable:
            where = _in_face(p, f)
            if where > 0:
                inside.append(f.name)
            elif where == 0:
                border.append(f.name)
    return sorted(inside), sorted(border)


# ---------------------------------------------------------------- worlds


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.load(Path(path).read_text(), Loader=_Loader)
    return data if isinstance(data, dict) else {}


def map_path(world: Path, file: str) -> Path | None:
    """The map file a world names: in ``maps/`` beside it, beside it, or in a ``maps/`` above."""
    if not file:
        return None
    if Path(file).is_absolute():
        return Path(file) if Path(file).is_file() else None
    here = Path(world).resolve().parent
    for d in [here, *here.parents]:
        for cand in (d / "maps" / file, d / file):
            if cand.is_file():
                return cand
        if d.name == "maps":
            break
    return None


def _places(entities: Any) -> dict[str, dict[str, Any]]:
    """Location entities with coordinates, by key."""
    out = {}
    for e in entities or []:
        if isinstance(e, dict) and e.get("kind") == "location" and isinstance(e.get("at"), list):
            out[str(e["key"])] = e
    return out


def _chain(path: Path) -> list[tuple[Path, dict[str, Any]]]:
    """A staging world and the earlier ones it ``extends``, earliest first."""
    seen: list[tuple[Path, dict[str, Any]]] = []
    p: Path | None = Path(path).resolve()
    while p is not None:
        if any(p == q_ for q_, _ in seen):
            raise ValueError(f"{p} extends itself")
        data = _read_yaml(p)
        seen.append((p, data))
        ext = data.get("extends")
        p = (p.parent / str(ext)).resolve() if ext else None
    return seen[::-1]


def _union(chain: list[tuple[Path, dict[str, Any]]], key: str) -> list[Any]:
    return [item for _, data in chain for item in (data.get(key) or [])]


def _map_block(chain: list[tuple[Path, dict[str, Any]]]) -> tuple[Path, dict[str, Any]] | None:
    for p, data in reversed(chain):
        if isinstance(data.get("map"), dict):
            return p, data["map"]
    return None


def _check_against_map(
    chain: list[tuple[Path, dict[str, Any]]], places: dict[str, dict[str, Any]], report: Report
) -> Map | None:
    """The checks shared by the strict and the scoped mode; ``None`` when the map cannot be read."""
    block = _map_block(chain)
    out = report.problems
    if block is None:
        out.append(Problem("map", "map", "the world has no map block"))
        return None
    where, ref = block
    found = map_path(where, str(ref.get("file", "")))
    if found is None:
        out.append(Problem("map", "map", f"the map file {ref.get('file')!r} is not found"))
        return None
    raw, sha = load(found)
    out += check(raw)
    if any(p.code in ("format", "ring") for p in out):
        return None
    if ref.get("sha256") != sha:
        out.append(
            Problem(
                "hash",
                "map",
                f"the world names {ref.get('sha256')}, but {found.name} hashes to {sha}",
            )
        )
    if ref.get("coords", raw["coords"]) != raw["coords"]:
        out.append(
            Problem(
                "map", "map", f"the world says coords {ref.get('coords')}, the file {raw['coords']}"
            )
        )
    if "box" in ref and [float(c) for c in ref["box"]] != [float(c) for c in raw["box"]]:
        out.append(
            Problem(
                "map", "map", f"the world's box {ref['box']} differs from the file's {raw['box']}"
            )
        )
    m = parse(raw)
    keys = {str(a["key"]) for a in _union(chain, "territories") + _union(chain, "sea_zones")}
    for k in sorted(set(m.areas) - keys):
        out.append(
            Problem("keys", k, "is an area of the map but no territory or sea zone of the world")
        )
    for k in sorted(keys - set(m.areas)):
        out.append(
            Problem("keys", k, "is a territory or sea zone of the world but no area of the map")
        )
    _check_adjacency(raw, m, _union(chain, "adjacency"), out)
    _check_places(m, places, _union(chain, "territories"), out)
    return m


def _check_adjacency(raw: Any, m: Map, listed: list[Any], out: list[Problem]) -> None:
    derived = set(adjacency(raw))
    lengths = _shared(m)
    pairs: dict[tuple[str, str], tuple[str, bool]] = {}
    for entry in listed:
        if isinstance(entry, dict):
            a, b, crossing = str(entry.get("a")), str(entry.get("b")), bool(entry.get("crossing"))
        else:
            a, b, crossing = str(entry[0]), str(entry[1]), False
        for k in (a, b):
            if k not in m.areas:
                out.append(
                    Problem(
                        "adjacency", k, "is named in the adjacency list but is no area of the map"
                    )
                )
        pairs[(a, b) if a < b else (b, a)] = (a, crossing)
    for pair, (first, crossing) in sorted(pairs.items()):
        if pair not in derived and not crossing and set(pair) <= set(m.areas):
            got = lengths.get(pair, 0.0)
            out.append(
                Problem(
                    "adjacency",
                    first,
                    f"{pair[0]} and {pair[1]} are listed as adjacent but share {got:g} of border, "
                    f"below {MIN_SHARED[m.coords]:g}, and no crossing is declared",
                )
            )
    for pair in sorted(derived - set(pairs)):
        out.append(
            Problem(
                "adjacency",
                pair[0],
                f"{pair[0]} and {pair[1]} share {lengths[pair]:g} of border "
                "but are not listed as adjacent",
            )
        )


def _check_places(
    m: Map, places: dict[str, dict[str, Any]], territories: list[Any], out: list[Problem]
) -> None:
    found: dict[str, list[str]] = {}
    for key, e in sorted(places.items()):
        lat, lon = e["at"]
        inside, border = _locate(m, (q(lon), q(lat)))
        found[key] = inside
        if border:
            out.append(Problem("place", key, f"lies on the border of {' and '.join(border)}"))
        elif not inside:
            out.append(Problem("place", key, "lies in no area"))
        elif len(inside) > 1:
            out.append(Problem("place", key, f"lies in more than one area: {', '.join(inside)}"))
        within = e.get("within")
        if within in m.areas and inside and inside != [within]:
            out.append(
                Problem(
                    "place",
                    key,
                    f"lies in {', '.join(inside)}, not in {within}, where it is within",
                )
            )
    for t in territories:
        for site in t.get("sites") or []:
            if site in found and found[site] and found[site] != [t["key"]]:
                out.append(
                    Problem(
                        "place",
                        str(site),
                        f"is a site of {t['key']} but lies in {', '.join(found[site])}",
                    )
                )


def check_world(path: Path) -> Report:
    """The strict check: the whole world against its map."""
    report = Report()
    data = _read_yaml(path)
    _check_against_map([(Path(path), data)], _places(data.get("entities")), report)
    return report


def check_region(path: Path) -> Report:
    """The scoped check of a staging world (and the earlier staging worlds it ``extends``).

    The map is checked whole. The sites in scope are the staging worlds' location entities;
    each must lie in exactly one listed area, and when ``places_of`` names the world file,
    sit where that world puts it. The world's other places are left out of scope, by name.
    """
    report = Report()
    chain = _chain(Path(path))
    scope = _places(_union(chain, "entities"))
    _check_against_map(chain, scope, report)
    world_file = next(
        (p.parent / str(d["places_of"]) for p, d in reversed(chain) if d.get("places_of")), None
    )
    if world_file is not None:
        world = _places(_read_yaml(world_file).get("entities"))
        for key, e in sorted(scope.items()):
            if key not in world:
                report.problems.append(
                    Problem("place", key, f"is not a place of {world_file.name}")
                )
            elif [float(c) for c in world[key]["at"]] != [float(c) for c in e["at"]]:
                report.problems.append(
                    Problem(
                        "place",
                        key,
                        f"is at {e['at']} here but at {world[key]['at']} in {world_file.name}",
                    )
                )
        report.out_of_scope = sorted(set(world) - set(scope))
    return report


# ---------------------------------------------------------------- the proof sheet

WIDTH = 1200
STYLE = (
    ".area{fill:#efe6cf;stroke:#333;stroke-width:1;fill-rule:evenodd}"
    ".sea{fill:#d4e4ef}.backdrop{fill:#ddd;stroke:#999;stroke-width:.5;fill-rule:evenodd}"
    ".dim{opacity:.35}.adj{stroke:#a33;stroke-width:1.2}"
    ".crossing{stroke:#a33;stroke-width:1.2;stroke-dasharray:2 3}"
    ".cut{stroke:#06c;stroke-width:2;fill:none}.cut.gap{stroke-dasharray:6 4}"
    ".site{fill:#000}text{font:11px sans-serif}.name{font-weight:bold}.note{font-size:10px}"
)


def render(raw: Any, world: Any, recipes: Sequence[Any], name: str) -> dict[str, str]:
    """SVG proof sheets: one for the whole map (``name``), one per world region (``name-<region>``).

    Each draws the borders, the names, the sites, the adjacency as lines between labels, and the
    recipes' cut lines with their sources (a cut marked ``gap`` is dashed and says so).
    """
    m = _parse_checked(raw)
    world = world or {}
    areas = {
        str(a["key"]): a for a in (world.get("territories") or []) + (world.get("sea_zones") or [])
    }
    sea = {str(a["key"]) for a in world.get("sea_zones") or []}
    links: list[tuple[str, str, bool]] = []
    for entry in world.get("adjacency") or []:
        if isinstance(entry, dict):
            links.append((str(entry["a"]), str(entry["b"]), bool(entry.get("crossing"))))
        else:
            links.append((str(entry[0]), str(entry[1]), False))
    if not world:
        links = [(a, b, False) for a, b in adjacency(raw)]
    cuts = [c for r in recipes for c in (r or {}).get("cuts") or []]
    sites = _places(world.get("entities"))
    sheets = {name: _sheet(m, set(m.areas), areas, sea, links, cuts, sites, name)}
    regions = [str(r["key"]) for r in world.get("regions") or []]
    parent = {str(r["key"]): r.get("parent") for r in world.get("regions") or []}

    def under(region: Any, top: str) -> bool:
        seen = set()
        while region is not None and region not in seen:
            if region == top:
                return True
            seen.add(region)
            region = parent.get(region)
        return False

    for reg in regions:
        keys = {k for k, a in areas.items() if under(a.get("region"), reg) and k in m.areas}
        if keys:
            sheets[f"{name}-{reg}"] = _sheet(
                m, keys, areas, sea, links, cuts, sites, f"{name}: {reg}"
            )
    return sheets


def _sheet(
    m: Map,
    keys: set[str],
    areas: dict[str, Any],
    sea: set[str],
    links: list[tuple[str, str, bool]],
    cuts: list[Any],
    sites: dict[str, dict[str, Any]],
    title: str,
) -> str:
    if keys == set(m.areas):
        x0, y0, x1, y1 = (unq(c) for c in m.box)  # the whole map: the box is the frame
    else:
        focus = [p for f in m.faces if f.name in keys for r in f.rings for p in r.pts]
        x0, y0, x1, y1 = (unq(c) for c in _bbox(focus))
    pad = 0.04 * max(x1 - x0, y1 - y0)
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    squash = math.cos(math.radians((y0 + y1) / 2)) if m.coords == "lonlat" else 1.0
    k = WIDTH / ((x1 - x0) * squash)
    height = math.ceil((y1 - y0) * k) + 40

    def xy(px: float, py: float) -> str:
        return f"{(px - x0) * squash * k:.1f},{(y1 - py) * k + 30:.1f}"

    def path(face: Face) -> str:
        return " ".join(
            "M" + " L".join(xy(unq(x), unq(y)) for x, y in r.pts[:-1]) + " Z" for r in face.rings
        )

    def label(key: str) -> str:
        return xy(*(unq(c) for c in m.labels[key]))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}">',
        f"<style>{STYLE}</style>",
        f'<text x="8" y="18" class="name">{escape(title)}</text>',
    ]
    for f in m.faces:
        if not f.playable:
            parts.append(f'<path class="backdrop" d="{path(f)}"/>')
    for f in m.faces:
        if f.playable:
            cls = "area" + (" sea" if f.name in sea else "") + ("" if f.name in keys else " dim")
            parts.append(
                f'<path class="{cls}" d="{path(f)}"><title>{escape(f.name)}</title></path>'
            )
    for a, b, crossing in links:
        if a in m.labels and b in m.labels and (a in keys or b in keys):
            (ax, ay), (bx, by) = (label(a).split(","), label(b).split(","))
            cls = "crossing" if crossing else "adj"
            parts.append(f'<line class="{cls}" x1="{ax}" y1="{ay}" x2="{bx}" y2="{by}"/>')
    notes = []
    for c in cuts:
        line = c.get("line") or []
        cls = "cut gap" if c.get("gap") else "cut"
        pts = " ".join(xy(float(px), float(py)) for px, py in line)
        parts.append(f'<polyline class="{cls}" points="{pts}"/>')
        source = "gap: no source" if c.get("gap") else str(c.get("source", "no source given"))
        notes.append(f"cut {c.get('name', '?')}: {source}")
        if line:
            px, py = xy(float(line[0][0]), float(line[0][1])).split(",")
            parts.append(
                f'<text x="{px}" y="{py}" class="note">{escape(str(c.get("name", "?")))}</text>'
            )
    for key in sorted(m.labels):
        if key in keys:
            lx, ly = label(key).split(",")
            text = escape(str(areas.get(key, {}).get("name", key)))
            parts.append(f'<text x="{lx}" y="{ly}" class="name" text-anchor="middle">{text}</text>')
    for key, e in sorted(sites.items()):
        sx, sy = xy(float(e["at"][1]), float(e["at"][0])).split(",")
        parts.append(
            f'<circle class="site" cx="{sx}" cy="{sy}" r="2.5">'
            f"<title>{escape(key)}</title></circle>"
        )
        parts.append(
            f'<text x="{float(sx) + 4:.1f}" y="{sy}">{escape(str(e.get("name", key)))}</text>'
        )
    for i, note in enumerate(notes):
        y = height - 8 - 13 * (len(notes) - 1 - i)
        parts.append(f'<text x="8" y="{y}" class="note">{escape(note)}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------- command line


def _recipes(paths: Sequence[str]) -> list[Any]:
    out = []
    for p in map(Path, paths):
        files = sorted(p.glob("*.yaml")) if p.is_dir() else [p]
        out += [_read_yaml(f) for f in files]
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="map_check.py", description=(__doc__ or "").split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser(
        "check", help="check a map file, or a world (strict) or staging world (scoped)"
    )
    c.add_argument("map", nargs="?", type=Path)
    mode = c.add_mutually_exclusive_group()
    mode.add_argument("--world", type=Path)
    mode.add_argument("--region", type=Path)
    a = sub.add_parser("adjacency", help="print the adjacency the predicate derives, as YAML")
    a.add_argument("map", type=Path)
    r = sub.add_parser("render", help="write the SVG proof sheets")
    r.add_argument("map", type=Path)
    r.add_argument("--world", type=Path)
    r.add_argument("--recipe", action="append", default=[], help="a recipe file or directory")
    r.add_argument("--out", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    if args.cmd == "adjacency":
        raw, _ = load(args.map)
        print(
            yaml.safe_dump(
                {"adjacency": [list(p) for p in adjacency(raw)]}, default_flow_style=None
            ),
            end="",
        )
        return 0
    if args.cmd == "render":
        raw, _ = load(args.map)
        world = _read_yaml(args.world) if args.world else None
        args.out.mkdir(parents=True, exist_ok=True)
        for sheet, svg in render(raw, world, _recipes(args.recipe), args.map.stem).items():
            (args.out / f"{sheet}.svg").write_text(svg)
            print(args.out / f"{sheet}.svg")
        return 0
    if args.world or args.region:
        target = args.world or args.region
        report = check_world(args.world) if args.world else check_region(args.region)
    elif args.map:
        target = args.map
        report = Report(check(load(args.map)[0]))
    else:
        parser.error("check needs a map file, --world or --region")
    for p in report.problems:
        print(p)
    for key in report.out_of_scope:
        print(f"out of scope: {key}")
    if report.problems:
        print(f"FAIL {target}: {len(report.problems)} problem(s)")
        return 1
    print(f"ok {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
