# GeoPackage Creator v0.28.0 — Changelog
**Release date:** 2026-06-12
**Status:** Production Ready

## Summary
Closes the remaining DGIWG Req 24 (Data Validity) failure found by the
DGIWG GeoPackage Compliance Validator. All 37 mandatory requirements now
PASS or are not applicable. No breaking changes.

---

## Bug Fixes

### Req 24: Bounding Box Mismatch (gpkg_contents vs RTree)
**Root cause:** GDAL writes the layer bounding box into `gpkg_contents` at
layer-creation time using the source data extent. For reprojected data this
bbox can differ from the RTree aggregate by tiny floating-point amounts, which
the DGIWG validator detects as a mismatch even when the printed values look
identical (more decimal places exist than the validator's display shows).

**Fix:** `_finalize_dgiwg_compliance()` now runs a SQL UPDATE at the end of
every conversion that pulls `MIN(minx)`, `MIN(miny)`, `MAX(maxx)`, `MAX(maxy)`
from each layer's RTree index (`rtree_<table>_geom`) and writes those exact
values back to `gpkg_contents`. This guarantees bit-for-bit agreement between
the declared envelope and the spatial index.

**New static method:** `GeoPackageConverter._fix_bbox_from_rtree(cur)`

---

### Req 24: Z/M Flag Inconsistency (declared z=0 but geometry header Z-flag=1)
**Root cause:** The source GDB (CanVec) stores line features with Z
coordinates. `copy_layer_to_geopackage()` already calls `g.FlattenTo2D()`
on each geometry, and the output layer is declared as a 2D type
(`wkbLineString`). However, the GPKG geometry binary header's envelope
indicator can still carry a Z component written by GDAL based on the
_source_ geometry dimensions before the flatten, causing the validator to
see `declared z=0 (prohibited)` vs `header Z-flag=1`.

**Fix:** A new post-write pass `_strip_z_from_2d_layers()` is called after
the sqlite3 connection is closed (so GDAL can open the file for update).
It re-opens the GPKG in GDAL update mode, identifies any layer declared as
`z=0` in `gpkg_geometry_columns` whose features still report `Is3D()=True`,
and rewrites those features with `FlattenTo2D()` inside a single transaction.
Layers with no residual Z are skipped entirely.

**New static method:** `GeoPackageConverter._strip_z_from_2d_layers(gpkg_path)`

---

## Engineering Notes
- Both fixes are in `core/converter.py` → `_finalize_dgiwg_compliance()`
- The method is idempotent; re-running on an already-fixed file is safe
- `info` dict returned by `_finalize_dgiwg_compliance()` gains two new keys:
  - `bbox_fixed_layers`: list of table names whose bbox was updated
  - `z_stripped_layers`: list of `(layer_name, feature_count)` tuples
- No changes to the public `convert()` API signature
- No changes to report format (new keys appear in `dgiwg_finalized` sub-dict)

## Validator Results (after fix)
| Req | Name | Status |
|-----|------|--------|
| 3 | Mandatory Extensions | PASS |
| 13 | WKT for CRS | PASS* |
| 18 | GeoPackage Metadata DMF | PASS |
| 19 | GeoPackage Metadata Document | PASS |
| 24 | Data Validity | **PASS** ← fixed |
| Overall | — | **CONFORMANT** |
