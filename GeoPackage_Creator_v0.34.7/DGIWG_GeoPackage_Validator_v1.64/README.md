# DGIWG GeoPackage Validator v1.64

This Windows/Python tool performs operational pre-validation against the 37 requirements in DGIWG STD-DP-19-005 v1.1 and inherited GeoPackage checks. It writes per-file HTML/JSON reports plus batch HTML/CSV rollups.

It is not a certification authority. Requirements 1, 2, and 6 require external evidence. Requirement 8 covers a deterministic structural subset and still requires the OGC 17-083r2 Tile Matrix Set ATS A.1-A.16. Requirement 18 performs deterministic DMF screening and still requires the official DGIWG DMF schema/ATS.

## Quick start

Use Anaconda Prompt and a dedicated environment. Never install project dependencies into the base environment.

```bat
cd /d C:\Users\Son\Documents\DGIWG\DGIWG_GeoPackage_Validator_v1.64
conda env create -f environment.yml
conda activate dgiwg
python run_local_tests.py
python DGIWG_Validator_v1_64.py --offline --no-install C:\Data\example.gpkg
```

For an existing environment, use `conda env update -f environment.yml --prune`.

## Commands

```bat
python -m dgiwg_validator --help
python -m dgiwg_validator file.gpkg
python -m dgiwg_validator --recursive C:\Data\GeoPackages
python -m dgiwg_validator --offline --no-install --quiet --output-dir C:\QA\reports C:\Data
python -m dgiwg_validator --fail-fast C:\Data
```

With no file or folder argument, the validator opens a file picker.

## Status and verdict meanings

Requirement statuses:

- `PASS`: the implemented automated check completed and found no violation.
- `FAIL`: the input data violates a deterministic check.
- `ERROR`: the validator could not complete the check because of an internal or processing error.
- `PASS*`: no violation was found, but evidence is sampled, incomplete, or advisory; the reason chip explains which.
- `SKIPPED`: the requirement was not applicable or requires external evidence.

File verdicts:

- `VALIDATION ERROR`: at least one check returned `ERROR`.
- `NON-CONFORMANT (automated checks)`: at least one check returned `FAIL` and none returned `ERROR`.
- `PRE-VALIDATION PASSED — REDUCED COVERAGE`: no FAIL/ERROR, but one or more blocking `PASS*` coverage gaps remain.
- `PRE-VALIDATION PASSED — EXTERNAL CHECKS REQUIRED`: automated checks completed without failures or coverage gaps, but external requirements remain skipped.
- `CONFORMANT (automated scope)`: all applicable automated checks completed without FAIL, ERROR, blocking PASS*, or SKIPPED results.

Exit codes:

- `0`: automated pre-validation completed without FAIL or ERROR.
- `1`: one or more deterministic checks returned FAIL.
- `2`: a validator ERROR occurred or a file could not be processed.

## Key v1.64 corrections

- Enforces the GeoPackage 1.4 `application_id` (`GPKG`) and `user_version` 1.4.x required by DGIWG v1.1.
- Accepts permitted WKT1 and WKT2 CRS representations, including compound CRS structures.
- Separates validator execution errors from data non-conformance.
- Exhaustively checks non-null vector GeoPackageBinary header `srs_id` values against the declared geometry-column CRS.
- Validates registered CRS names against the bundled EPSG cache where available.
- Marks Req 8 and Req 18 as reduced-coverage checks instead of overstating full conformity.
- Removes historical corpus claims from current reports; confidence is based only on the current run.
- Uses UTF-8 console configuration and deterministic exit codes.
- Bundles required Conda runtime DLLs so the standalone EXE can load SQLite, ctypes, and tkinter correctly.
- Builds a clean source ZIP that excludes internal standards documents, build caches, reports, and local-test artifacts.

## Validation and release gate

```bat
cd /d C:\Users\Son\Documents\DGIWG\DGIWG_GeoPackage_Validator_v1.64
conda activate dgiwg
python -m compileall -q .
python run_local_tests.py
python package_release.py
pyinstaller --clean --noconfirm DGIWG_Validator.spec
dist\DGIWG_Validator_v1_64.exe --version
```

The source ZIP is created at `dist\DGIWG_GeoPackage_Validator_v1.64.zip`. The standalone executable is created separately at `dist\DGIWG_Validator_v1_64.exe` and is not placed inside the source ZIP.

## Release contents

- `DGIWG_Validator_v1_64.py`: versioned launcher.
- `dgiwg_validator\`: application package.
- `dgiwg_epsg_cache.json`: offline EPSG reference cache.
- `QUICKSTART.html`: concise operating guide.
- `DGIWG_GeoPackage_Validator_User_Manual_v1.64.docx`: full user manual.
- `run_local_tests.py`: regression and functional gate.
- `package_release.py`: clean source-package builder.
- `DGIWG_Validator.spec`, `01_create_environment.bat`, `02_build_exe.bat`: Windows executable build workflow.
- `RELEASE_NOTES_v1.64.md`: release scope and limitations.

## License

SPDX-License-Identifier: GPL-2.0-or-later. Copyright (c) 2026 Eui Soo SON.
