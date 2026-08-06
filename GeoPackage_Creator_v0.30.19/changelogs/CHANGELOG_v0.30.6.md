# Changelog — GeoPackage Creator v0.30.6

**Release date:** 2026-07-24
**Type:** Pre-release audit / bug-fix release (no new features)

This release is the result of a full pre-release code audit of v0.30.5. It
fixes one critical regression and several correctness issues found during the
review. There are no functional changes to the conversion algorithm itself.

---

## Critical

### C-1 — Restored three public `GeoPackageConverter` methods (`core/converter.py`)

`list_available_profiles()`, `get_active_profile_config()` and
`get_supported_input_formats()` had been **deleted** from the converter. They
disappeared during the v0.30.1 hot-fix that removed an *unterminated
triple-quoted docstring* SyntaxError: the entire method block was cut out along
with the broken docstring instead of just repairing the docstring.

Impact:

* Five unit tests in `tests/test_converter.py` failed with `AttributeError`.
* The public Python API advertised in the module documentation was broken.
* The shipped GUI and CLI never called these methods, so the end-user app still
  ran — which is why the regression went unnoticed.

All three methods are restored with their original behaviour.

---

## Fixes

### F-1 — `validate_geopackage_output()` missing cleanup (`core/gdal_handler.py`)

The method carried a comment promising *"BUG-18: use try/finally so the
datasource handle is always released,"* but the `finally` clause and the
general-exception handler were absent — the method body ended at
`except ValidationError: raise`. As a result a non-GeoPackage input raised a raw
GDAL exception instead of a friendly `ValidationError`, and the datasource
handle was never explicitly released. Both are now restored.

### F-2 — Report "Validation Results" always showed failure (`core/report_generator.py`)

The HTML and PDF reports read validation keys (`ogc_compliant`,
`dgiwg_compliant`, `geometry_valid`, `metadata_valid`) that
`OutputValidator.validate_gpkg_structure()` never emits. Its real keys are
`compliant`, `gdal_readable`, `dgiwg_spatial_indexes`, `user_version_ok` and
`metadata_tables`. Consequently the **Validation Results** section of every
report displayed "No / Issues" even for a fully valid, DGIWG-compliant
GeoPackage. A new `_normalize_validation()` helper maps the real keys to the
report flags (with backward-compatible fallback to the legacy keys), and both
the HTML and PDF sections now use it.

### F-3 — GUI Security dropdown missing "RESTRICTED" (`geopackage_creator_gui.py`)

The Security Level combo box offered only UNCLASSIFIED / CONFIDENTIAL / SECRET /
TOP SECRET, omitting **RESTRICTED**, one of the five valid ISO 19115 / DGIWG
national classification levels. It has been added.

### F-4 — Type-annotation cleanup (`core/dgiwg_compliance.py`)

`full_compliance_check()` was annotated `-> Dict[str, any]` using the builtin
`any` instead of `typing.Any`. Corrected.

---

## Housekeeping

* Version bumped to **0.30.6** across all code, packaging and documentation
  files (`core/__init__.py`, `core/config.py`, `packaging/version_info.txt`,
  the PyInstaller spec, build scripts, GUI title, report templates, etc.).
* Added `release_test_v0.30.6.py` — a self-contained end-to-end test harness
  that verifies the environment, runs the pytest suite, exercises a full
  conversion (including a non-DGIWG EPSG:3857 → EPSG:4326 reprojection), checks
  every fix above, runs the bundled DGIWG validator gate, and writes a log file.
* Added `package_release_v0.30.6.py` — an automated, reproducible ZIP packager.

---

## Known items deferred (not changed in this release)

These were identified during the audit but intentionally left unchanged because
they are low-impact and/or require a live GDAL build to validate safely:

* `core/gdal_handler_concurrency.py` is **dead code** — nothing imports it, and
  it duplicates the `GDALHandler` class name with an older, inferior
  implementation (no geometry-type detection, no fault-tolerant copy, no lock
  timeout). Recommend removing it in a future release (the PyInstaller spec
  lists `core.gdal_handler_concurrency` as a hidden import, so remove both
  together).
* `core/crs_converter.py` Mode B copies the source file to a `.gpkg` name with
  `shutil.copy` when source and target EPSG match, which is only correct for a
  single-file source. Low priority (optional multi-version feature).
* Packaging: the spec lists `osgeo.gdal_array` as a hidden import and collects
  all `osgeo` submodules while `numpy` is in `excludes`. `gdal_array` needs
  numpy. In practice the app's imports never load `gdal_array`, but this should
  be confirmed on the first frozen build.
