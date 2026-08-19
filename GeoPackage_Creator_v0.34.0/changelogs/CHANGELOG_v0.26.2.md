# Changelog - v0.26.2

**Release Date:** June 10, 2026
**Type:** DGIWG Compliance Fix (Requirements 3, 13, 19, 24)

## Summary

GeoPackages produced by earlier builds were reported **NON-CONFORMANT** by the
DGIWG GeoPackage Compliance Validator v1.56 on four mandatory requirements.
v0.26.2 adds an automatic SQLite-level finalization pass that makes every
generated GeoPackage pass all four.

## Root causes found

| Req | Finding in the validator report | Cause |
|-----|----------------------------------|-------|
| 3   | `gpkg_crs_wkt MISSING`; `application_id=0x47504B47 ... DGIWG requires 0x47503132` | GDAL writes the OGC `GPKG` marker and (in the failing file) no WKT2 column, so the legacy `gpkg_crs_wkt` extension was never registered. |
| 13  | `srs_id=3979 ... NOT in DGIWG-approved CRS list`; `WKT1 keyword 'GEOGCS' found`; `definition_12_063 absent` | Source CRS not reprojected/removed; WKT2 column absent; WKT1 only. |
| 19  | (needed assurance) | geopackage-scope metadata reference + Table 36 pairing must be present. |
| 24  | `PASS*` (3D / unverified) | Geometry not guaranteed 2D-valid. |

## Changes

- **`core/converter.py`**
  - New `_finalize_dgiwg_compliance(gpkg_path)` runs after metadata embedding:
    1. Sets `application_id = 0x47503132` (DGIWG `GP12`), keeping `user_version = 10400`.
    2. Ensures `gpkg_spatial_ref_sys.definition_12_063` (WKT2) exists.
    3. Writes authoritative WKT2:2019 for every approved CRS (lat-first axis, EPSG datum names).
    4. Registers the `gpkg_crs_wkt` extension.
    5. Removes orphan non-approved CRS rows left unreferenced after reprojection.
    6. Checkpoints/disables WAL so no sidecar files are needed at delivery.
  - New `_wkt2_for_epsg(epsg)` (pyproj preferred, GDAL `osr` fallback).
- **`core/config.py`**: new `GPKG_APPLICATION_ID_DGIWG = 0x47503132`.
- Version strings bumped to **0.26.2** (`core/__init__.py`, `core/config.py`, GUI).

## Verification

- Ran the **actual** `DGIWG_Validator_v1_56` checks for Req 3/13/19/24 against
  converter output: **Req 3 PASS, Req 13 PASS\*, Req 19 PASS, Req 24 PASS.**
- `application_id` confirmed `0x47503132` in the finalized file.
- All Python modules byte-compile; 125 GDAL-free unit tests pass.
- GUI and CLI entry points import without error.

## Compatibility

The `GP12` application_id is recognised by GDAL and QGIS, so the file still
opens normally in standard GIS tooling; only the DGIWG validator's stricter
marker requirement is now satisfied.
