# GeoPackage Creator — Change Log

## v0.34.5 — 2026-10-15

DGIWG GeoPackage Profile 1.4 conformance fixes, found by an independent
audit (`dev_tools/dgiwg_gdb_audit_v2.2.py`) run against ArcGIS Pro file
geodatabases (`SampleData.gdb`, `States.gdb`) plus synthetic edge cases.

- **Metadata (Req 18-24, Annex B).** The package AND every table now carry a
  complete DMF 2.0 record (metadataStandardName/Version, purpose, resource
  language, geospatial-type keyword, dates, lineage, distribution format,
  security constraints, extent, reference system). Table-scope rows use the
  DMF standard URI; the non-DMF ISO 19139 root row (a Table 37 rows 22-24
  violation) is no longer written. New `generate_dmf_layer_metadata()`.
- **Geometry-less tables** (ArcGIS `__ATTACH` tables, plain tables) are now
  written as GeoPackage `attributes` tables: no geometry column, no
  `gpkg_geometry_columns` row, no R-tree, no undefined-CRS geometry.
- **BLOB columns are preserved** (ArcGIS attachment `DATA`); they used to be
  dropped silently.
- **CRS detection.** `resolve_epsg()` reads the ROOT authority (the old
  `GetAttrValue("AUTHORITY",1)` could return a nested datum/spheroid code or
  None for ESRI-only definitions). Layers whose CRS has no EPSG authority are
  rewritten to a clean EPSG definition; layers with no CRS at all produce an
  explicit warning. Reprojection is decided per layer.
- **EPSG:4326 row** in `gpkg_spatial_ref_sys` now carries the exact Table 16
  `srs_name` and `description`.
- **Geometry.** The layer type is determined from ALL features (was the first
  500) after curve linearization; true curves are linearized (1 degree step);
  geometry type is coerced back to the declared type after `MakeValid()`;
  dropped Z/M values, linearized curves and repaired geometries are reported
  as warnings.
- **Exact bounding boxes.** `gpkg_contents` bbox is the exact double-precision
  data extent (was float32 R-tree values that could sit ~1e-6 inside the data).
- **Compliance flag.** `dgiwg_compliant` is now a stricter structural
  self-check (application_id, user_version, per-table R-tree, 2D vector CRS,
  DMF root + per-table metadata, gpkg_crs_wkt) and is forced to `False` when a
  requested DGIWG validator run fails or cannot run. New `dgiwg_verified`.
- **Validator gate.** The validator subprocess now runs with
  `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8`; on Windows it previously died with
  a cp1252 `UnicodeEncodeError` before writing a report.
- **Bundled validator (v1.63) corrections.** Req 3 wrongly FAILED the standard
  OGC `application_id` `GPKG` (0x47504B47) and demanded a non-existent `GP12`
  marker; it now checks `GPKG` + `user_version >= 10200`. The Req 18 DMF XSD
  now accepts `metadataStandardName/Version` and the other ISO MD_Metadata
  children.
- **Config.** Removed EPSG:4978 from the 3D vector CRS set (profile lists
  4326/4979/9518); raster tile CRS set now includes the WGS 84 UTM zones.
- Added `tests/test_v0345_fixes.py` and extended DMF/config tests (345 tests).
- Not changed in this release: the raster path (`raster_support.py`) and the
  CRS conversion Modes A/B/C were not reworked; 3D (Z) vector output is still
  flattened to 2D (with a warning).

## v0.34.4 — 2026-09-04

- Release version bump only -- no functional change since v0.34.3. All
  v0.34.3 fixes verified for real on Windows/conda before this release:
  full pytest suite (327 tests) green, `dev_tools/run_release_check_v0.30.23.py`
  all-stages-PASSED, and an actual `BUILD_EXE.bat`/PyInstaller build
  succeeded with the bundled v1.63 DGIWG validator (confirming the
  v1.62->v1.63 hardcoded-path fix works end-to-end, not just in source).

## v0.34.3 — 2026-09-03

- Fixed `--validate` being silently broken by any in-place bundled-validator
  version bump: `core/validation_gate.py` and `packaging/app_main.py` used
  to hardcode the launcher filename `DGIWG_Validator_v1_62.py`, which broke
  outright (`FileNotFoundError` / a failed PyInstaller build) the moment the
  bundled validator was upgraded to v1.63 without a matching code change.
  Both now discover the launcher (and, in `GeoPackageCreator.spec`, the
  bundled folder itself) by glob pattern instead, so the next validator
  version bump no longer requires touching application code.
- Fixed the frozen `.exe` silently ignoring an explicit `--validator-path`
  / `DGIWG_VALIDATOR_PATH` override and always running the bundled DGIWG
  validator instead: the resolved validator directory is now passed to the
  isolated `--dgiwg-validator-worker` subprocess via an environment
  variable, so a non-default validator install is honored in the packaged
  build the same way it already was when run from source.
- `packaging/version_info.txt`: the numeric `filevers`/`prodvers` tuple had
  drifted to `(0, 34, 0, 0)` while the `FileVersion`/`ProductVersion`
  strings correctly said `0.34.2.0` -- the release-check's version-string
  gate only ever regex-matched the string, not the tuple. Both now agree.
- Added test coverage for `InputValidator.resolve_source_path()` (the
  CANVEC `GEODATABASE_FILE_*` unwrap added in v0.34.0) and for
  `core.validation_gate.run_dgiwg_validation()` / `find_validator()`
  (the subprocess-isolated DGIWG validation path added in v0.34.0), neither
  of which had any test before this release despite both being real,
  crash-motivated behavior changes.
- Removed the dead `shapely` hidden-import entries from
  `GeoPackageCreator.spec` and the unused `shapely` package from
  `BUILD_EXE.bat`'s conda env-creation command: nothing in the app imports
  it, it isn't in `requirements.txt`/`environment.yml`, and PyInstaller was
  logging `ERROR: Hidden import 'shapely' not found` on every build because
  of it (harmless to the build, but ERROR-level noise a clean build log
  shouldn't have).

## v0.34.2 — 2026-08-19

- Cleaned the source release layout for distribution.
- Consolidated release history into this single file.
- Removed historical diagnostic probes, candidate patches, duplicate manuals,
  old packaging scripts, generated artifacts, and per-version changelog files.
- Updated runtime, GUI, CLI, Windows version resources, and release checks to
  v0.34.2.

## v0.34.1 — 2026-08-19

- Refreshed release metadata and version identifiers.
- Added explicit `LICENSE` and `COPYRIGHT.md` notices.

## v0.34.0 — 2026-08-17

- Bundled DGIWG GeoPackage Validator upgraded to v1.62.
- DGIWG validation moved to a helper process to isolate GDAL and lxml native
  libraries.
- FileGDB folder detection accepts `GEODATABASE_FILE_*` markers without a
  `.gdb` suffix.
- Standard OGC GeoPackage header behavior uses `GPKG` and `user_version=10400`.

## v0.30.23 — 2026-08-14

- Removed the process-wide compiled XML schema cache.
- Added the real 8-cycle conversion regression gate for the schema lifetime
  crash fix.

## v0.30.20 and earlier

Historical fixes covered GDAL/libxml2 pinning, metadata validation, CRS
conversion, DGIWG compliance, reporting, GUI workflows, packaging, and test
stability. The detailed historical development record is intentionally not
included in the clean distribution archive.
