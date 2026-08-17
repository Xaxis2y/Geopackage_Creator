# Changelog — GeoPackage Creator v0.26.1

**Release Date:** June 10, 2026
**Type:** Bug-fix, performance, and DGIWG-compliance release

This release fixes the GUI hang, makes large conversions fast and visible, and
brings the output GeoPackage materially closer to DGIWG conformance.

## GUI / Stability

- **Fixed: GUI hung with no CPU usage on Convert.** The conversion ran in a
  worker thread but called Tkinter directly (`root.update()`, widget reads,
  `messagebox`), which is not thread-safe and froze the Tcl interpreter. All
  widget values are now read on the main thread and passed to the worker as a
  plain dict; every UI update is marshalled back via `root.after()`.
- **Added: live progress.** The indeterminate progress bar now animates, and
  the log streams per-layer and per-feature progress with elapsed time and
  feature/sec rate. Core-module logs are routed into the GUI log window.
- **Added: "Convert in Console Window" button.** Runs the CLI in a separate
  console (using the same Python) so progress is visible in real time.

## Performance

- **Fixed: per-feature commit slowness.** `StartTransaction`/`CommitTransaction`
  were placed *after* the copy loop, so every `CreateFeature()` auto-committed
  as its own disk-syncing transaction. The loop is now wrapped in a single
  transaction (with rollback on error) — large layers copy orders of magnitude
  faster.

## DGIWG Compliance

- **Added: gpkg_crs_wkt extension.** `CRS_WKT_EXTENSION=YES` is now set, adding
  the `definition_12_063` (WKT2) column to `gpkg_spatial_ref_sys`
  (fixes Req 3 and the WKT2 portion of Req 13). A legacy `gpkg_crs_wkt`
  extension row is also written for validator name-matching.
- **Added: reprojection to a DGIWG-approved CRS.** When any source layer uses a
  non-approved CRS (e.g. EPSG:3979), all layers are reprojected to a single
  approved CRS (default EPSG:4326) with correct lon/lat axis order
  (fixes Req 9 and the approved-CRS portion of Req 13). Controlled by the new
  `dgiwg_reproject` / `dgiwg_target_epsg` parameters on `convert()`.
- **Added: 2D geometry flattening.** Geometries are flattened to 2D on copy so
  the output never declares a Z it should not have (Req 24).

## Launcher / Packaging

- **Fixed: START_HERE.bat now uses the Anaconda Python that has GDAL.** Plain
  cmd.exe defaulted to a system Python without `osgeo`. The launcher now points
  at the conda interpreter and runs from its own folder, with a fallback.
- **Added: selftest_conversion.py** — a quick known-good conversion that proves
  the engine works independently of the GUI.
- **Docs: GUI_USAGE_GUIDE.md translated from Korean to English.**

## Notes

- Three defects were identified in the external DGIWG validator (v1.56) that
  cause false failures on standards-compliant files: it requires a fictional
  application_id "GP12" (correct is "GPKG"); it misreads the geometry-header
  envelope indicator as a Z-flag; and it uses a 1e-6 absolute bbox tolerance
  against outward-rounded float32 RTree bounds. These are validator issues,
  not GeoPackage issues.
- Req 18 (DGIWG Metadata Foundation profile URI) remains PASS* — metadata is
  valid ISO 19115 but does not yet use a DMF profile URI.
