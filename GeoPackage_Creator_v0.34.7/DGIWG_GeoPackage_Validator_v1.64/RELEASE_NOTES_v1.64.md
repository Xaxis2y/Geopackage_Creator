# DGIWG GeoPackage Validator v1.64 — Final Operational Release

Release date: 2026-09-09

v1.64 is the final operational pre-validator release derived from v1.63. The v1.63 tree is preserved unchanged.

## Standards corrections

- GeoPackage identification now requires `PRAGMA application_id = 0x47504B47` (`GPKG`) and `10400 <= user_version < 10500`, matching GeoPackage 1.4.x as required by DGIWG STD-DP-19-005 v1.1.
- WKT1 and WKT2 representations are both accepted where the DGIWG profile permits them. Compound CRS checks validate the corresponding horizontal, vertical, and datum components for either syntax.
- Vector CRS requirements inspect every non-null geometry header and compare its GeoPackageBinary `srs_id` with `gpkg_geometry_columns.srs_id`.
- Registered vector CRS names are checked against the bundled EPSG cache when an entry is available.

## Reliability corrections

- Internal check exceptions now return `ERROR`, not a false data `FAIL`.
- Verdict precedence is `ERROR`, then `FAIL`, then reduced/external coverage states.
- Batch exit codes are deterministic: 0 for a clean automated run, 1 for data failures, and 2 for validator or file-processing errors.
- Missing `definition_12_063` no longer crashes raster CRS validation.
- Console output is configured for UTF-8, and the self-test completion line is ASCII-safe.
- The PyInstaller specification explicitly bundles Conda runtime DLLs required by SQLite, ctypes, and tkinter.
- Current reports no longer rely on historical 24-file confidence claims.

## Coverage boundaries

- Req 1, Req 2, and Req 6 remain external/manual requirements.
- Req 8 returns `PASS* / EVIDENCE_MISSING` after its structural subset passes; the OGC 17-083r2 TMS ATS A.1-A.16 and well-known scale-set evidence remain external.
- Req 18 returns `PASS* / EVIDENCE_MISSING` after deterministic DMF screening; official DGIWG DMF schema and ATS evidence remain external.
- Sampled geometry/tile checks remain explicitly marked with blocking PASS* reason codes where applicable.

## Packaging

- The clean source ZIP excludes `Docs`, build caches, local tests, reports, logs, PDFs, and superseded artifacts.
- The standalone EXE is built and delivered separately from the source ZIP.

This release is suitable for operational pre-validation and issue screening. It does not by itself constitute DGIWG or OGC certification.
