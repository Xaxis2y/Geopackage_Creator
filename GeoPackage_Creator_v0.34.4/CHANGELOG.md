# GeoPackage Creator — Change Log

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
