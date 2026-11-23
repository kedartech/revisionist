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
on a `flat` map that is `[y, x]` in the map's units. On a `lonlat` map whose box runs past 180 (or -180),
a place keeps its longitude as written; a place outside the box is read whole turns (360) east or west
when that brings it inside, so Pearl Harbor at -158 lies where the map draws Hawaii, near 202
(`place_lon` in the checker; `locate` reads longitudes the same way).

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

## The build: `scripts/map_build.py`

The build turns recipe files and the border data into a map file and its world fragment. It is
build-time only: it imports the geometry tool (`shapely`, from the `map` dependency group), and nothing
the game runs imports it. It reads the data from the directory `REVISIONIST_MAP_DATA` names and never
reaches the network.

```
uv run --frozen --group map python scripts/map_build.py build worlds/maps/src/<slug>
```

It writes `worlds/maps/<slug>.json`, `worlds/maps/<slug>.world.yaml` and the object
`worlds/maps/objects/<sha256>.json`, appends the hash to the manifest, and prints the hash. `--slug`
names the map when the recipe directory's name is not the slug; `--simplify coverage|arcs` and
`--tolerance` override the defaults below.

A recipe is one YAML file per region under `worlds/maps/src/<slug>/`; the build reads every `*.yaml`
there in name order and joins their lists:

```yaml
map: {box: [west, south, east, north]}   # in at least one file; every file that gives it agrees
regions:
  - {key: baltic, name: The Baltic}
territories:
  - {key: estonia, name: Estonia, region: baltic, terrain: plain, sites: [tallinn],
     provinces: [EST-..., EST-...]}       # the data's own adm1_code of each present-day unit
cuts:
  - name: the 1940 line                    # a named line of [x, y] points (longitude, latitude)
    province: LTU-...                      # the unit it divides
    line: [[22.1, 56.5], [22.4, 55.9]]
    left: estonia                          # the territory left of the line, walking from its first point
    right: latvia                          # and right of it
    source: "the citation the points come from"   # or gap: true when no source is yet found
sea_zones:
  - {key: gulf, name: The Gulf, region: baltic, terrain: sea,
     polygon: [[19, 54.5], [25, 54.5], [25, 59.2], [19, 59.2]]}
rivers:
  - {key: river, name: The River, region: baltic, terrain: river, width: 0.25,
     borders: [[EST-..., LVA-...]],        # pairs of units whose shared border the river is
     polygon: [[24, 56], [28, 56], [28, 58], [24, 58]]}   # optional: the stretch it follows
crossings:
  - {a: estonia, b: gulf, name: the ferry, source: "..."}
```

What the build does, in order, refusing with a message that names the file, province, cut or area:

1. Reads the recipe files, and refuses a duplicate key, an unknown region, or boxes that disagree.
2. Checks each data file it reads (`ne_10m_admin_1_states_provinces.geojson` and
   `ne_10m_land.geojson`) against the SHA-256 that `SOURCES.md` records. It names any province code a
   recipe lists that the data lacks, and any province two territories (or a territory and a cut) claim.
3. Dissolves each territory's provinces into one area. Each cut splits its province along the line and
   gives each side to the territory the recipe names; a cut that does not cross its province from edge
   to edge fails. Several cuts may divide one province in turn: a side a cut leaves unnamed is what the
   next cut of that province divides, and a part no cut gives a territory fails.
4. Land is every province inside the box, claimed or not, and every island of the land file farther
   from every province than the simplify tolerance (an islet nearer a coast than that cannot be kept
   apart from it when the coast is simplified, and is water); the ocean is the box less the land. Each
   sea zone is its polygon cut from the ocean, so a coast is one border that the land territory and the sea zone share. Two zones over the
   same water fail. Each river zone is a strip `width` wide along the shared borders of its pairs of
   units (within its polygon when it gives one), taken from the land of those units, so the river
   parts its two banks and each bank shares a border with it; a pair that shares no border fails, as
   do two river zones over the same land. A river zone is listed with the sea zones. Land and water
   no recipe claims become the backdrop, so the areas and the backdrop cover the box exactly.
5. Nodes every border with every other, then simplifies all of them together, so neighbours keep one
   shared border: with the tool's `coverage_simplify` when it has one (GEOS 3.12 or later), and
   otherwise by splitting the borders into arcs at their junctions and simplifying each arc once
   (an arc the simplification makes cross another is simplified again with half the tolerance). The box
   edge is never simplified. The world fragment's first line records the path that built the map.
6. Derives the adjacency with the checker's `adjacency` (its `adjacent` predicate and `MIN_SHARED`) and
   adds each recipe crossing as `{a, b, crossing: <name>}`.
7. Writes the two files; the same inputs give the same bytes. An object already on disk with other
   bytes is never overwritten: the build fails instead.
8. A box that runs past 180 degrees east (or -180 west) takes provinces from across the date line with
   their longitudes shifted by 360, so a territory across the line stays one area.
9. Runs the checker's `check` on the map and writes nothing when it fails.

Defaults `[proposed]`: simplify tolerance 0.05 degrees; coordinates snapped to 4 decimals (the
the checker's) before any overlay; the coast is the admin-1 units' line, and a sliver of the land file
that touches a unit (the two files trace coasts a little apart), or an islet of it nearer a unit than the
tolerance, is water.

`tests/test_map_build.py` runs the build on a made-up fixture (`tests/maps/build-fixture.geojson` and
`build-fixture.recipe.yaml`) and skips when the tool is absent, as it is in CI.

## Licences

The base border data is Natural Earth 1:10m (public domain), recorded in `SOURCES.md`; the raw downloads
are never committed, only the built map file, the recipes and the proof sheets. CShapes 2.0
(CC BY-NC-SA 4.0) and historical-basemaps (GPL-3.0) are not copied into the repo, and no geometry derived
from them is committed, because kedartech may sell the game. They may be opened locally to compare a built
border by eye, and each such comparison is recorded on the proof sheet. A cut line's points come from its
cited source, never from tracing either dataset.
