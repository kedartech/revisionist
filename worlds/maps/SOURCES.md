# Map sources

Base border data for the map build (`scripts/map_build.py`). The files are not in the repo: they sit in
a cache outside it, and the build reads them from the directory named by `REVISIONIST_MAP_DATA`. The
build refuses a file whose SHA-256 differs from the one in the table below.

This file is the maintainer's record of what was downloaded. Map items read it and do not edit it; a new
or changed data file is a new download record, added here in its own commit.

## Natural Earth 1:10m, version 5.1.2

- Publisher: Natural Earth (Tom Patterson, Nathaniel Vaughn Kelso and contributors).
- Licence: public domain. "All versions of Natural Earth raster + vector map data found on this website
  are in the public domain. You may use the maps in any manner." (`LICENSE.md` at the tag below;
  https://www.naturalearthdata.com/about/terms-of-use/)
- Source: the `geojson` folder of https://github.com/nvkelso/natural-earth-vector at tag `v5.1.2`
  (commit `f1890d9f152c896d250a77557a5751a93d494776`; `VERSION` reads `5.1.2`). The files are GeoJSON
  as published; nothing was converted.
- Downloaded: 2026-11-17.

One row per file. `file` is the name inside `REVISIONIST_MAP_DATA`; `sha256` is the hex digest of the
file as downloaded.

| file | sha256 | bytes | url |
|---|---|---|---|
| ne_10m_admin_1_states_provinces.geojson | 22d0e3ad85eb3e27f17cabf8ba2d50e554fbc27a87796ff891d958185da62fb5 | 40726851 | https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_admin_1_states_provinces.geojson |
| ne_10m_land.geojson | 1ac90796408bc6ad6911d69448485d3c4dbf2190370080368a09976e1c9f7416 | 10157965 | https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_land.geojson |
| ne_10m_coastline.geojson | 6f75ae0e0de157b14946e2255eb1f5486d9a13819032e26d4610852d296788f6 | 10110735 | https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_coastline.geojson |

### What the files hold (read on download)

- `ne_10m_admin_1_states_provinces.geojson`: 4,596 present-day first-level units (CRS84, longitude and
  latitude). Each feature's properties carry `adm1_code` (the unit's code, for example `UKR-...`),
  `iso_3166_2`, `adm0_a3` (the country's three-letter code), `name`, `name_en`, `type_en` and `admin`.
  Units per country, for the 1941 theatres: Russia 86, Ukraine 25, Belarus 7, Poland 16, Finland 18,
  Estonia 15, Latvia 119, Lithuania 10, Moldova 40, Romania 42, China 32, Japan 47, Libya 22, Egypt 27,
  France 101, Malta 68. One geometry is not valid as published: `BRA-1294` (Goiás, Brazil), a ring
  self-intersection; the build repairs or skips it.
- `ne_10m_land.geojson`: 11 MultiPolygon features.
- `ne_10m_coastline.geojson`: 4,133 LineString features.

## Not used

CShapes 2.0 (CC BY-NC-SA 4.0) and historical-basemaps (GPL-3.0) are not copied here and no geometry
derived from them is committed. Either may be opened locally to compare a built border by eye; each such
comparison is recorded on the region's proof sheet.
