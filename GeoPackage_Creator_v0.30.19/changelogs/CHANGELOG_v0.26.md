# Changelog — GeoPackage Creator v0.26.0

**Release Date:** June 9, 2026
**Type:** Critical Fix & Compliance Release

---

## Critical Bug Fixes

### BUG-6 — `core/converter.py`: ISO 19115 metadata never embedded in output
- **Problem:** `MetadataHandler` generated package- and layer-level ISO 19115
  XML, but the converter never called it and never wrote the metadata into the
  GeoPackage. Output files contained **no** `gpkg_metadata` or
  `gpkg_metadata_reference` tables, so they could not satisfy DGIWG metadata
  requirements, and `DGIWGCompliance.check_metadata_tables()` would always fail
  on the tool's own output. This affected every release since the metadata
  module was introduced.
- **Fix:** New conversion step ("Step 7b") generates package metadata, validates
  it against the ISO 19115 XSD, generates per-layer metadata, and embeds all of
  it via the new `GeoPackageConverter._embed_metadata()` method. The method
  implements the OGC GeoPackage Metadata Extension: creates
  `gpkg_metadata` / `gpkg_metadata_reference` (spec-conformant DDL), registers
  `gpkg_metadata` in `gpkg_extensions` (idempotent), writes one
  geopackage-scope record, and one table-scope record per layer linked via
  `md_parent_id`. The conversion result now includes `metadata_embedded`
  (record count).

### BUG-7 — `tests/`: Entire test suite failed at collection
- **Problem:** Every test module imported `geopackage_creator.core...`, but the
  project's package is the top-level `core` (the file `geopackage_creator.py`
  is a CLI module, not a package). `pytest` aborted during collection — the
  suite could not run at all.
- **Fix:** All test imports corrected to `from core import ...` /
  `from core.<module> import ...`. Usage examples in docstrings updated to
  match the real layout.

### BUG-8 — `schemas/iso19115-1.xsd`: Schema never loaded, validation silently disabled
- **Problem:** Two defects: (1) the header comment contained `--` (illegal in
  XML comments), so the file failed to parse; (2) the schema referenced
  `gco:*_PropertyType` types without an `xs:import` of the gco namespace, and
  the gco schema didn't define those types. `MetadataHandler` swallowed the
  load failure with a warning and **skipped all metadata validation**.
- **Fix:** Comment corrected; the four `*_PropertyType` definitions moved into
  `schemas/iso19115-gco.xsd` under the correct target namespace; proper
  `xs:import` added. The schema now loads, and generated metadata validates
  against it (verified by the test suite).

### BUG-9 — `core/__init__.py`: Missing export and stale version
- **Problem:** `GDALHandler` was not exported (breaking
  `from core import GDALHandler`), and `__version__` reported "0.20.0".
- **Fix:** `GDALHandler` added to imports and `__all__`; `__version__` now
  "0.26.0".

### BUG-10 — `core/config.py`: `KNOWN_NATION_CODES` incomplete
- **Problem:** The set contained 39 codes; documentation claims 42 and
  `test_nation_codes_count` requires ≥ 40.
- **Fix:** Added `CHE` (Switzerland), `IRL` (Ireland), `UKR` (Ukraine) — 42
  codes total, matching the documentation.

## Improvements

- **W-9** — `METADATA_MIME_TYPE` changed from the non-standard
  `application/xml+iso:19115` to `text/xml` (the value OGC GeoPackage
  validators expect in `gpkg_metadata.mime_type`). New constant
  `ISO_METADATA_STANDARD_URI = "http://www.isotc211.org/2005/gmd"` used for
  `md_standard_uri`.
- **W-10** — `test_schema_validation.py` asserted `"test layer"` but the
  handler titlecases layer names (`"Test Layer"`). Assertion corrected.
- **W-11** — `core/gdal_handler.py` missing newline at end of file; fixed.
- **W-12** — `VERSION.txt` was truncated mid-sentence; rebuilt in full.
- **W-13** — Stale version strings updated: GUI window title (was v0.24), GUI
  results window (v0.24), report HTML template (v0.24), `core/crs_converter.py`
  and `core/report_generator.py` headers (v0.25), `START_HERE.bat` (v0.25),
  `QUICKSTART.md` (v0.23/v0.21), `GDAL_INSTALLATION.txt` (v0.23),
  `GETTING_STARTED.md` (1.0.0-dev).

## New

- `tests/test_metadata_embedding.py` — 7 regression tests covering the metadata
  embedding feature: record counts, geopackage/table reference scopes,
  parent-child linkage, extension registration, idempotency, standard
  URI/MIME values, and verbatim XML storage. Pure SQLite — no GDAL required.
- `USER_MANUAL` — comprehensive end-user manual (installation, GUI, CLI,
  Python API, profiles, CRS modes, reports, troubleshooting), included in the
  release package.

## Files Changed

| File | Change |
|------|--------|
| `core/converter.py` | BUG-6 (metadata embedding step + `_embed_metadata()`) |
| `core/config.py` | BUG-10, W-9, version 0.26.0 |
| `core/__init__.py` | BUG-9 |
| `core/gdal_handler.py` | W-11 |
| `core/crs_converter.py` | W-13 |
| `core/report_generator.py` | W-13 |
| `geopackage_creator_gui.py` | W-13 |
| `schemas/iso19115-1.xsd` | BUG-8 |
| `schemas/iso19115-gco.xsd` | BUG-8 |
| `tests/*.py` | BUG-7, W-10 |
| `tests/test_metadata_embedding.py` | New |
| `START_HERE.bat`, `VERSION.txt`, `QUICKSTART.md`, `GDAL_INSTALLATION.txt`, `GETTING_STARTED.md`, `README.md` | W-12, W-13, doc refresh |
