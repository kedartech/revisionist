# Map files

A world's map is one JSON file in this directory, `worlds/maps/<slug>.json`. A world file names it in
its `map` block (`coords`, `file`, `sha256`, `box`), and the map is found beside the world under
`worlds/maps/`. The file can be written by hand (Salt Strait, the test maps) or by the build script
(`scripts/map_build.py`, from the recipes under `worlds/maps/src/<slug>/` and the border data
`SOURCES.md` records). Everything that reads it, the checker included, uses the standard library alone;
nothing imports the geometry tool.

## The format

```json
{
  "format": 1,
  "coords": "flat",
  "box": [0, 0, 100, 100],
  "vertices": [[0, 0], [50, 0], [100, 0], [0, 50], [50, 50], [100, 50], [0, 100], [50, 100], [100, 100]],
  "areas": {
    "marsh": {"rings": [[0, 1, 4, 3, 0]], "label": [25, 25]},
    "ridge": {"rings": [[1, 2, 5, 4, 1]], "label": [75, 25]},
    "bay": {"rings": [[4, 5, 8, 7, 4]], "label": [75, 75]}
  },
  "backdrop": [[3, 4, 7, 6, 3]]
}
```

- `format`: 1.
- `coords`: `lonlat` (x is longitude, y is latitude, in degrees) or `flat` (x and y in units of the
  world's own plane, y up). A ring that crosses the date line keeps longitudes beyond 180.
- `box`: `[west, south, east, north]`, the frame of the map. The areas and the backdrop cover it
  exactly.
- `vertices`: every point, `[x, y]`, once. Faces name points by index, so two neighbours that use the
  same indices share their border by construction.
- `areas`: the playable areas by key (each key is a territory or sea zone of the world). An area has
  `rings`, lists of vertex indices, and a `label`, the point `[x, y]` where its name and its pieces are
  drawn; the label lies inside the area.
- `backdrop`: rings of land and water that are drawn and not in play. They have no key and no rule
  reads them.

Rings, for every reader: a face (an area, or one part of the backdrop) is one or more parts; each part
is an outer ring running counter-clockwise (x right, y up), followed by its holes running clockwise. A
ring is closed: its last index is its first. A hole is not in the face. An island is a part of its own.
The backdrop's list is read the same way, and each of its parts is one face, named `backdrop 1`,
`backdrop 2` and so on in the checker's messages.

A place in a world file gives `at` as `[y, x]`, latitude first, as the world files already write places;
on a `flat` map that is `[y, x]` in the map's units.

Areas are measured in square degrees for `lonlat` and square units for `flat`. Coordinates are rounded
to 4 decimals before any comparison.

## The checker: `scripts/map_check.py`

Three commands:

- `python scripts/map_check.py check MAP.json` checks the file alone. It fails, naming the face, on a
  ring that is open or crosses itself; a hole outside its outer ring; two faces (playable or backdrop,
  a duplicate included) whose interiors overlap; any part of the box no face covers (by area sum, and by
  edge use: each interior edge is used once in each direction, each box edge once); a vertex that lies
  on another face's edge without being one of its vertices (a border that only looks shared); a vertex
  outside the box; an area smaller than the minimum (0.05 square degrees, or 25 square units); a label
  outside its area or on its border.
- `python scripts/map_check.py check --world WORLD.yaml` is the strict check of a whole world: every check
  above on the map the world names, and it fails when the world's `sha256`, `coords` or `box` differ from
  the file; when the map's area keys differ from the world's territories and sea zones; when the world's
  `adjacency` list has a pair the adjacency predicate rejects and no `crossing` names, or lacks a pair it
  accepts; when a place lies in no area, in more than one, or on a border (a failure, not a tie); when a
  place lies outside the area it is `within`; or when a territory lists a site that lies elsewhere.
- `python scripts/map_check.py check --region STAGING.yaml` is the scoped check of a staging world, for a
  region built before the whole world is converted. The staging world carries a `map` block, the region's
  `regions`, `territories`, `sea_zones` and `adjacency`, and the sites in scope as `location` entities
  with `at` copied from the world file; `places_of` names that world file, and `extends` names an earlier
  staging world whose lists it adds to. The whole map gets every check above; the areas, adjacency and
  sites of the staging chain stand in for the world's; each site in scope must lie in exactly one listed
  area and at the same `at` as in the world; the world's other places are printed as `out of scope`. The
  scoped mode is not used once the world itself carries the territories.
- `python scripts/map_check.py adjacency MAP.json` prints the adjacency the predicate derives, as YAML.
- `python scripts/map_check.py render MAP.json [--world W] [--recipe R ...] [--out DIR]` writes the SVG
  proof sheets: one for the whole map (`<slug>.svg`) and one per region of the world
  (`<slug>-<region>.svg`), with the borders, the names, the sites, the adjacency as lines between labels
  (a declared crossing dashed), and each recipe cut line with its source (a cut marked `gap: true` is
  dashed and says it has no source). `--recipe` takes recipe files or their directory.

The adjacency predicate is `adjacent(map, a, b)` in the checker and nowhere else; the build imports it.
Two areas are adjacent when the edges they share, after rounding and with collinear pieces split by
extra vertices merged, add up to at least `MIN_SHARED`: 0.1 degrees on a `lonlat` map, 2 units on a
`flat` one. A length exactly at the threshold counts; two areas that meet only at a corner are not
adjacent.

## Map objects

Every map is also kept, byte for byte, as `worlds/maps/objects/<sha256>.json`, and its hash is appended
to `worlds/maps/objects/MANIFEST`. The manifest is append-only; an object is never overwritten, and no
object a stored game names is removed. A world file selects the map for new games; a stored game is
served the object named by its own stored hash. `tests/test_map_files.py` checks every map in this
directory, every object's name against its hash, every hash a world or staging world under `worlds/`
names, and every hash in the manifest. It needs neither the geometry tool nor the border data, so it runs
in CI.

## Licences

The base border data is Natural Earth 1:10m (public domain), recorded in `SOURCES.md`; the raw downloads
are never committed, only the built map file, the recipes and the proof sheets. CShapes 2.0
(CC BY-NC-SA 4.0) and historical-basemaps (GPL-3.0) are not copied into the repo, and no geometry derived
from them is committed, because kedartech may sell the game. They may be opened locally to compare a built
border by eye, and each such comparison is recorded on the proof sheet. A cut line's points come from its
cited source, never from tracing either dataset.
