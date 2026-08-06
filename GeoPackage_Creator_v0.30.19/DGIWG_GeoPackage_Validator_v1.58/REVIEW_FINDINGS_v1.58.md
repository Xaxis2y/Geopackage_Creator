# DGIWG Validator — Pre-Release Review Findings (v1.57 → v1.58)

Review date: 2026-08-05. Scope: full code review of all 12 modules (~10,500 lines), spec cross-check against DGIWG STD-DP-19-005 v1.1 (May 2, 2025), and end-to-end functional testing with synthetic GeoPackages.

## Overall Verdict

The validator is logically sound and release-ready as a pre-release. Architecture is clean (config/constants/checks/forensics/report separation), error isolation per file and per check is correct, offline mode is safe for air-gapped networks, and the verdict logic (PASS / PASS* / FAIL / SKIPPED) behaves as designed. All 37 requirements of STD-DP-19-005 v1.1 are covered with correct M/C compliance flags, verified line-by-line against Table 6 of the official v1.1 document.

Functional test results (v1.58): 40/40 assertions passed. A conformant synthetic file produces 0 FAIL; files with 10+ deliberate violations (wrong CRS, WKT1, 512-px tiles, WEBP blobs, zoom gaps, missing metadata, invalid geometry, missing rtree) are all detected; corrupt/empty files are skipped gracefully; `--fail-fast` exits 1; batch reports (HTML/JSON/CSV rollup) render without errors.

## Bugs Found and Fixed in v1.58

1. `_EPSG_API` NameError (checks.py, Req 13): referenced but never imported from net.py. The exception was silently swallowed, so the EPSG REST API last-resort datum lookup never executed. Fixed by importing it.
2. Missing `gpkg_extensions` table crashed Req 3/4/5 into generic "Exception during check: no such table" FAILs. Per OGC, the table is optional. Now: Req 3 FAILs with the named list of missing mandatory extensions; Req 4 returns PASS* (optional extensions cannot fail by definition); Req 5 returns PASS* and still runs the WEBP BLOB scan.
3. Req 26 false PASS: a tile table with declared=512×512 and stored=512×512 passed Req 26 because only stored-vs-declared was compared. DGIWG requires 256×256 stored tiles; non-conformance was only caught indirectly via Req 8. Both the Pillow path and the stdlib header-parser fallback now FAIL on non-256 stored tiles.
4. Req 1/2 names and identifiers were from a pre-1.1 edition ("OGC Base Application", `/req/base/application`). Aligned with v1.1 Table 6: "GeoPackage Base definition" `/req/geopackage/base` and "GeoPackage Options definition" `/req/geopackage/options`. Req 15 identifier corrected to `/req/crs/crs-compound-wkt`.
5. Req 10 guidance text wrongly mentioned UTM zones as allowed 3D vector CRS. Spec Table 13 permits only EPSG:4979 and EPSG:9518 — the code allowlist was already correct; the MANUAL_GUIDANCE and LIKELY_CAUSE texts were fixed to match.
6. Dead duplicate `check_req()` in utils.py referenced `_CHECK_DISPATCH`, which exists only in checks.py — calling it would always produce a masked NameError FAIL. Removed (never called at runtime, but a maintenance trap).
7. `_net_check_uri()` bypassed the `--offline` gate (built its own urllib request). Its only call site was guarded, but the helper itself now returns an OFFLINE result — defense in depth for air-gapped systems.
8. Offline runs labeled the EPSG/scale internet checks "NETWORK ERROR — could not be reached". Now labeled "OFFLINE MODE — suppressed by --offline flag" when the cause is the flag, not the network.
9. Req 24 bbox pass-message interpolated `_feat_count` left over from a previous loop, reporting the wrong table's feature count. Message rewritten without the stale variable.
10. `datetime.utcnow()` (deprecated since Python 3.12) replaced with `datetime.now(timezone.utc)` in the Req 3 last_change check.
11. Version strings: JSON `schema_version` and the argparse description were hardcoded "1.57"; both now read `__version__` so they can never drift again. SPDX/GPL-2.0-or-later copyright headers added to all 12 source files.

## Remaining Observations (not changed — design decisions for you)

- Verdict "CONFORMANT" is currently unreachable: Req 4 always returns PASS* (and Req 20/23 are PASS*-capped), so the best achievable verdict is "LIKELY CONFORMANT (partial checks)". This is arguably honest (PASS* means partially automated), but if you want a reachable top grade, Req 4 could return PASS when no optional extensions are registered.
- Req 1/2/6 are permanently SKIPPED (CITE TeamEngine / product profile needed) yet the file can still be labeled conformant-ish. Consider a one-line banner note that full conformance additionally requires the OGC CITE base suites.
- Req 26/24 sample BLOBs (5 per zoom / 25 per table by default). Fine for practice; `--sample-size` already lets auditors deepen coverage. Full-scan mode could be a future flag.
- `--quiet` still prints "HTML report written:" per file (html_report.py/rollup.py print unconditionally). Harmless; suppress if you want strictly minimal output.
- `_manual_checks()` returns 3-tuples normally but 4-tuples on error paths. Consumers index rather than unpack, so nothing breaks, but normalizing to one shape would be cleaner.
- `_http_get`/`_http_head` are imported by checks.py but never called (dead imports).
- The User Manual docx is still v1.56 — update before the public release.
- The old launcher `DGIWG_Validator_v1_57.py` is still in the folder (I don't delete files without your OK). `package_release.py` excludes old launchers from the release zip automatically, so the zip is clean either way.

## Spec Coverage Summary (STD-DP-19-005 v1.1)

All 37 requirements implemented or explicitly SKIPPED-with-reason: automated (fully or partially): 3, 4, 5, 7–37; not automatable by design: 1, 2 (OGC CITE TeamEngine), 6 (product-profile context). CRS allowlists verified against Tables 11–14; vector CRS against Table 13 (2D: 4326; 3D: 4979, 9518); metadata scope pairings against Table 36; tile rules (256×256, factor-2 zoom, OGC 17-083r4 scale sequence) all enforced.

## How to Test Locally (Anaconda Prompt)

Never install into the base environment — create a dedicated one:

    conda create -n dgiwg_test python=3.11 -y
    conda activate dgiwg_test
    pip install shapely Pillow pyproj lxml
    cd C:\Users\Son\Documents\DGIWG\DGIWG_GeoPackage_Validator_v1.57
    python run_local_tests.py

Expected: "RESULT: 40/40 assertions passed / ALL TESTS PASSED". A detailed step-by-step log `local_test_log_<timestamp>.txt` is written next to the script — send it back if anything fails. Then build the release archive:

    python package_release.py

Output: `dist\DGIWG_GeoPackage_Validator_v1.58_pre.zip` with VERSION.txt inside.
