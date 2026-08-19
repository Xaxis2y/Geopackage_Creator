# DGIWG GeoPackage Compliance Validator

**Version:** 1.62 (Release)  
**Standard:** DGIWG STD-DP-19-005 v1.1 (GeoPackage Profile 1.4, Edition 1.1)  
**License:** GPL-2.0-or-later  
**Copyright:** © 2026 Eui Soo SON

---

## What This Tool Does

The DGIWG GeoPackage Compliance Validator checks whether GeoPackage files (.gpkg) conform to the Defence Geospatial Information Working Group (DGIWG) standard for geospatial data. It validates:

- **Structure & metadata** — required tables, columns, data types, spatial reference systems
- **Tile pyramids** — zoom levels, zoom_level constraints, tile matrix definitions
- **Feature tables** — geometry encoding, coordinate ranges, mandatory fields
- **Optional extensions** — registered extensions and their compliance
- **XSD validation** — detailed metadata document structure (when lxml is installed)

Output includes per-file HTML reports with detailed pass/fail breakdown and a rollup CSV for batch analysis.

---

## Quick Start

### 1. Install (Anaconda Prompt)

Never install into `base` — always use a dedicated environment:

```batch
conda create -n dgiwg python=3.11 -y
conda activate dgiwg
pip install -r requirements.txt
```

### 2. Run

Navigate to the project folder and run one of these:

**Single file:**
```batch
python DGIWG_Validator_v1_62.py path\to\file.gpkg
```

**Folder (all GeoPackages):**
```batch
python DGIWG_Validator_v1_62.py path\to\folder
```

**Module form:**
```batch
python -m dgiwg_validator path\to\file.gpkg
```

### 3. Read Results

- **HTML report** — `<filename>_UNKNOWN_DGIWG_Report.html` (detailed, color-coded)
- **JSON report** — `<filename>_UNKNOWN_DGIWG_Report.json` (machine-readable)
- **Rollup CSV** — `rollup_DGIWG_Validation.csv` (batch summary)

**Verdict meanings:**
- **CONFORMANT** — every requirement was executed and passed
- **AUTOMATED CHECKS CONFORMANT — EXTERNAL REVIEW REQUIRED** — automated checks passed, but skipped requirements still need external evidence
- **LIKELY CONFORMANT** — passes, but some checks skipped (partial mode)
- **NON-CONFORMANT** — fails one or more checks
- **VALIDATION ERROR — REVIEW REQUIRED** — the validator could not complete one or more checks; this is not a data failure

For full documentation, see **QUICKSTART.html** or **DGIWG_GeoPackage_Validator_User_Manual_v1.62.docx**.

---

## Key Features

| Feature | Details |
|---|---|
| **Offline mode** | `--offline` disables internet checks (default: enabled) |
| **Quiet output** | `--quiet` suppresses report-written chatter, prints only summaries |
| **Fail-fast** | `--fail-fast` stops after the first non-conformant file or validator error |
| **Custom output** | `--output-dir path` saves reports to a specific folder |
| **Recursive** | `--recursive` searches subdirectories for .gpkg files |
| **Help & version** | `--help` or `--version` |

**Example — batch validation, offline, quiet:**
```batch
python -m dgiwg_validator --recursive --offline --quiet --output-dir ./reports ./data
```

---

## Installation & Testing

### Option A: Quick Test (No Pip Install)

If you just want to test without installing dependencies system-wide:

```batch
conda activate dgiwg
cd path\to\DGIWG_GeoPackage_Validator_v1.62
python run_local_tests.py
```

Expected output:
```
RESULT: 62/62 assertions passed
ALL TESTS PASSED ✔
```

A detailed log file `local_test_log_<timestamp>.txt` is written either way.

### Option B: Full Setup (Recommended)

```batch
conda activate dgiwg
pip install shapely Pillow pyproj lxml
cd path\to\DGIWG_GeoPackage_Validator_v1.62
python run_local_tests.py
python package_release.py
```

---

## Optional Dependencies

The validator works without these, but performance and coverage improve with them installed:

| Package | Purpose | Impact if missing |
|---|---|---|
| **shapely** | Geometry validation | Geometry checks skipped; reports `PASS*` |
| **Pillow** | Image tile inspection | Tile image validation skipped; reports `PASS*` |
| **pyproj** | CRS transformation | CRS checks use basic logic only; reports `PASS*` |
| **lxml** | XSD metadata validation | Req 18 skips structural checks; reports `PASS*` |

Install all: `pip install shapely Pillow pyproj lxml`

---

## Documentation

| File | Purpose |
|---|---|
| **QUICKSTART.html** | Single-page quick reference — what the tool does, setup, how to read verdicts, flags, troubleshooting |
| **DGIWG_GeoPackage_Validator_User_Manual_v1.62.docx** | Comprehensive manual — complete option reference, exit codes, requirements table, limitations, self-test procedure |
| **RELEASE_NOTES_v1.62.md** | Detailed changelog — behavioral changes, robustness fixes, testing updates |
| **README.md** | This file — overview and quick start |

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'shapely'"

Install optional dependencies:
```batch
conda activate dgiwg
pip install shapely Pillow pyproj lxml
```

### "is not a valid SQLite/GeoPackage file"

The file is corrupted or not a GeoPackage. Validator skips it and continues.

### Report says "PASS\*" everywhere

One or more optional libraries are missing. Install them:
```batch
pip install shapely Pillow pyproj lxml
```

### Exit code is 1 (non-conformant or validator error)

The file fails one or more DGIWG requirements, or the validator could not complete a requirement. See the HTML or JSON report for details. Use `--fail-fast` to stop after the first failure or error.

### "Access is denied" on Windows during package build

Close all Python processes and manually delete the `dist\` folder:
```batch
taskkill /F /IM python.exe
rmdir /s /q dist
python package_release.py
```

For more help, see **QUICKSTART.html** troubleshooting table.

---

## Release Notes

**v1.62 (2026-08-13) — First Full Release**

Major fixes in this version:
- **Req 4:** CONFORMANT verdict is now reachable (was impossible in v1.58)
- **Req 18:** XSD validation outcome now always reported; `lxml` added to probe
- **--quiet flag:** Now actually suppresses report-written chatter
- **4-tuple normalization:** Manual checks return uniform structure
- **Key-type filtering:** Fragile hardcoded blocklists replaced with type-based selection
- **Packaging:** Prefix-based directory exclusion prevents stale folders in archives

See **RELEASE_NOTES_v1.62.md** for complete details.

---

## Development & Testing

### Run Self-Tests

```batch
conda activate dgiwg
cd path\to\project
python run_local_tests.py
```

This generates test GeoPackages, runs validation, and verifies 66 regression assertions.
For the complete Anaconda Prompt verification run, execute `run_anaconda_validation.bat` and retain its log.

### Build the Script Release Archive

```batch
python package_release.py
```

Output:
- `dist\DGIWG_GeoPackage_Validator_v1.62\` — staged folder
- `dist\DGIWG_GeoPackage_Validator_v1.62.zip` — release archive (~0.18 MB)

The manifest check aborts if required assets are missing (launcher, manual, quick-start, etc.).
The GitHub script release contains only the Python package, launcher, documentation,
offline CRS cache, and test/build scripts. Compiled executables and local reports are
not part of this script release.

---

## Files in This Release

### Core Package
- `dgiwg_validator/` — main package (8 Python modules)
- `DGIWG_Validator_v1_62.py` — launcher script

### Documentation
- `README.md` — this file
- `QUICKSTART.html` — quick-start reference
- `DGIWG_GeoPackage_Validator_User_Manual_v1.62.docx` — full manual
- `RELEASE_NOTES_v1.62.md` — changelog

### Testing & Building
- `run_local_tests.py` — 66 regression tests
- `package_release.py` — release packaging script

### Data
- `dgiwg_epsg_cache.json` — embedded EPSG database
- `VERSION.txt` — version metadata

### Excluded (Maintainer Only)
- `build_manual.js` — generates User Manual (requires Node.js)
- `REVIEW_FINDINGS_*.md` — internal pre-release notes

---

## Project Structure

```
DGIWG_GeoPackage_Validator_v1.62/
├── dgiwg_validator/           # Core validation package
│   ├── __init__.py            # Version and exports
│   ├── __main__.py            # Entry point for -m dgiwg_validator
│   ├── main.py                # CLI argument parsing
│   ├── checks.py              # All 32 DGIWG requirements
│   ├── config.py              # Configuration & flags
│   ├── constants.py           # Requirement definitions (auto-docs)
│   ├── html_report.py         # HTML report generation
│   ├── rollup.py              # CSV rollup and batch reporting
│   ├── utils.py               # Utilities (library probe, scoring)
│   ├── forensics.py           # Metadata inspection
│   └── net.py                 # Network operations (online mode)
├── DGIWG_Validator_v1_62.py   # Launcher (runs -m dgiwg_validator)
├── VERSION.txt                # Release metadata
├── dgiwg_epsg_cache.json      # EPSG codes (offline reference)
├── README.md                  # This file
├── QUICKSTART.html            # Quick-start guide
├── DGIWG_GeoPackage_Validator_User_Manual_v1.62.docx  # Full manual
├── RELEASE_NOTES_v1.62.md     # Changelog
├── run_local_tests.py         # Test suite (62 assertions)
├── package_release.py         # Release builder
└── requirements.txt           # Python dependencies
```

---

## Requirements

- **Python:** 3.11+
- **OS:** Windows, Linux, macOS
- **DGIWG Standard:** STD-DP-19-005 v1.1
- **GeoPackage:** Version 1.4 (SQLite 3.9+)

Optional dependencies (greatly recommended): `shapely`, `Pillow`, `pyproj`, `lxml`

---

## License

**SPDX-License-Identifier: GPL-2.0-or-later**  
**Copyright (c) 2026 Eui Soo SON**

---

## Support & Feedback

For issues, questions, or feedback about this validator, see the troubleshooting section above or consult the **User Manual** and **QUICKSTART.html** included in this release.

---

*DGIWG GeoPackage Compliance Validator v1.62*  


