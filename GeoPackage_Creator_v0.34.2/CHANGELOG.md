# GeoPackage Creator — Change Log

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
