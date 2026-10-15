# DGIWG GeoPackage Compliance Validator

**Version:** 1.63 (Release)  
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
pip install shapely Pillow pyproj lxml
```

### 2. Run

Navigate to the project folder and run one of these:

**Single file:**
```batch
python DGIWG_Validator_v1_63.py path\to\file.gpkg
```

**Folder (all GeoPackages):**
```batch
python DGIWG_Validator_v1_63.py path\to\folder
```

**Module form:**
```batch
python -m dgiwg_validator path\to\file.gpkg
```

### 3. Read Results

- **HTML report** — `<filename>_UNKNOWN_DGIWG_Report.html` (detailed, color-coded)
- **JSON report** — `<filename>_UNKNOWN_DGIWG_Report.json` (machine-readable)
- **Rollup CSV** — `rollup_DGIWG_Validation.csv` (batch summary)

**Verdict meanings (since v1.61):**
- **CONFORMANT (automated scope)** — no failures, and every check that passed was fully evidenced
- **CONFORMANT — REDUCED COVERAGE** — no failures, but the tool could not fully verify one or more requirements (a sample, or missing optional data/library)
- **NON-CONFORMANT** — fails one or more checks

For full documentation, see **QUICKSTART.html** or **DGIWG_GeoPackage_Validator_User_Manual_v1.63.docx**.

---

## Key Features

| Feature | Details |
|---|---|
| **Offline mode** | `--offline` disables internet checks (default: enabled) |
| **Quiet output** | `--quiet` suppresses report-written chatter, prints only summaries |
| **Fail-fast** | `--fail-fast` stops after first non-conformant file |
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
cd path\to\DGIWG_GeoPackage_Validator_v1.63
python run_local_tests.py
```

Expected output:
```
RESULT: 84/84 assertions passed
ALL TESTS PASSED ✔
```

A detailed log file `local_test_log_<timestamp>.txt` is written either way.

### Option B: Full Setup (Recommended)

```batch
conda activate dgiwg
pip install shapely Pillow pyproj lxml
cd path\to\DGIWG_GeoPackage_Validator_v1.63
python run_local_tests.py
python package_release.py
```

---

### Option C: Build a Standalone .exe (No Python Needed to Run It)

Package the validator into a single `DGIWG_Validator_v1_63.exe` that runs on any Windows PC with no
Python, Anaconda, or pip installs required at run time:

```batch
01_create_environment.bat
02_build_exe.bat
```

Output: `dist\DGIWG_Validator_v1_63.exe`. See **BUILD_EXE_QUICKSTART.html** for the full walkthrough,
including drag-and-drop usage, sharing the exe with other machines, and troubleshooting.

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
| **DGIWG_GeoPackage_Validator_User_Manual_v1.63.docx** | Comprehensive manual — complete option reference, exit codes, requirements table, limitations, self-test procedure |
| **RELEASE_NOTES_v1.63.md** | Detailed changelog — behavioral changes, robustness fixes, testing updates |
| **README.md** | This file — overview and quick start |
| **BUILD_EXE_QUICKSTART.html** | How to build the standalone `.exe` with Anaconda + PyInstaller |

Release notes for earlier versions (v1.60, v1.61) have been moved to `_superseded_pre_v1.63/` to
keep this folder to the current release only; they are still summarized below and the files
themselves are preserved there, not deleted.

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

### Exit code is 1 (non-conformant)

The file fails one or more DGIWG requirements. See the HTML or JSON report for details. Use `--fail-fast` to stop after the first failure.

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

**v1.63 (2026-09-03) — Consistency & Cleanup Release**

No changes to requirement-checking logic or verdicts. This release brings the project folder
back in sync after v1.62 shipped without its documentation being updated to match, and removes a
personal/organizational attribution block from generated reports at the author's request:

- The launcher, `__init__.py`, README, QUICKSTART.html, BUILD_EXE_QUICKSTART.html, the build
  scripts (`01_create_environment.bat`, `02_build_exe.bat`, `DGIWG_Validator.spec`,
  `environment.yml`) and the User Manual all still referenced **v1.61** (or, in the manual's header/
  title-page/cover fields, v1.59 and v1.60) even though the package itself (`__init__.__version__`,
  `VERSION.txt`) had already moved to v1.62. Every current-version reference across these files is
  now v1.63 and consistent with `dgiwg_validator.__version__`, the single source of truth
  `package_release.py` reads from.
- The stray duplicate launcher `DGIWG_Validator_v1_61.py`, the superseded `DGIWG_Validator_v1_62.py`
  (whose docstring itself still incorrectly said "v1.61" — a leftover copy-paste from when it was
  created), the superseded manual (`..._v1.62.docx`), and the old per-version `RELEASE_NOTES_v1.60.md`
  / `RELEASE_NOTES_v1.61.md` files were moved into `_superseded_pre_v1.63/` rather than deleted, so
  the history is preserved but no longer mixed in with the current release's files.
- Stale build/test log files (`build_exe_log_*.txt`, `env_setup_log_*.txt`, `local_test_log_*.txt`)
  from previous local builds were removed — they are regenerated on every run and carried no lasting
  value.
- Historical narrative text that documents *when* a feature shipped (e.g. "the PASS* reason chip,
  added in v1.61" in QUICKSTART.html and the manual's "What's New in v1.61" section) was deliberately
  **left untouched** — only current-version identity stamps (titles, headers, footers, file-name
  references, folder paths) were bumped to v1.63, so the changelog history stays accurate.
- A personal/organizational attribution block (name and rank, personal email address, and
  organization/unit names) was removed from every place it appeared in generated output and
  documentation — the per-file HTML report footer (`html_report.py`), the rollup HTML report footer
  (`rollup.py`), QUICKSTART.html's footer, and the manual's title page, "11. Support" section, and
  page footer — and replaced everywhere with just `SPDX-License-Identifier: GPL-2.0-or-later` /
  `Copyright (c) 2026 Eui Soo SON`. This is a genuine content change to `html_report.py` and
  `rollup.py` (what text those two modules print), not just documentation; no check logic in either
  file changed. See `RELEASE_NOTES_v1.63.md` §5 for the full list of files touched.
- `package_release.py`'s `EXCLUDE_DIRS` did not exclude `build\` (only `dist\` was excluded), so a
  local PyInstaller `.exe` build's ~50 MB intermediate cache would have been zipped straight into
  the release archive. Fixed by adding `"build"` to `EXCLUDE_DIRS`.

See **RELEASE_NOTES_v1.63.md** for complete details.

---

**v1.61 (2026-09-02) — Reachable CONFORMANT Verdict**

Fixes the "known limitation" v1.60 documented and shipped anyway: the
`CONFORMANT` verdict was structurally unreachable, because ten requirements
returned `PASS*` unconditionally and six more did so on common clean-data
paths, while `score_results()` required zero `PASS*` anywhere. Every PASS*
result now carries a reason — `Sampled`, `Evidence missing`, or `Advisory` —
and only the first two hold back the top verdict, which is now a 3-tier
ladder: `NON-CONFORMANT` / `CONFORMANT — REDUCED COVERAGE` /
`CONFORMANT (automated scope)`. A clean synthetic file with full optional
libraries installed and appropriate `--sample-size` now genuinely reaches
`CONFORMANT (automated scope)` — proven end-to-end, not just asserted. Two
further defects surfaced during that verification and are fixed here too:
Req 5's WEBP scan ignored `--sample-size` (always read only the first 10
tiles), and Req 13's axis-order check matched `GEOGCRS[` as a substring of
`BASEGEOGCRS[`, wrongly treating every projected CRS as geographic, and
could not parse the `AXIS[...,north,ORDER[1],...]` form real PROJ/GDAL
output uses.

See **`_superseded_pre_v1.63/RELEASE_NOTES_v1.61.md`** for complete details.

---

**v1.60 (2026-09-02) — Correctness Release**

Six defects removed; nothing added. One changes a verdict earlier builds could
produce on conformant files:
- **Req 24 (critical):** Z/M presence was read from the GeoPackage flags byte
  bits 1–2, which are the *envelope indicator*, not Z/M flags. Every 2D layer
  written with XY envelopes — the GDAL/QGIS default — was falsely failed with
  "declared z=0 (prohibited) but header Z-flag=1", and genuine 3D geometry
  without an envelope was missed. Z/M now comes from the WKB geometry type code.
  **Re-run any file that failed Req 24 on Z/M consistency.**
- **Req 33:** absent `gpkg_extensions` produced a generic exception FAIL
  (the Bug B class fixed for Req 3/4/5 in v1.58, missed here)
- **`--offline`:** two ungated HTTP helpers in `net.py` could still reach the
  network on an air-gapped system
- **Req 24 ATS 5.4/5.5:** two gridded `data_type` spellings were unrecognised,
  skipping the missing-table checks
- **Req 26:** `--sample-size` ignored on the no-Pillow path; success line quoted
  a leaked loop variable
- **Forensics Req 18:** the ArcGIS internal-path detector used doubled
  backslashes in raw strings and had never matched anything

Known limitation, unchanged and deliberate at the time: the `CONFORMANT` verdict was
still unreachable — Req 5, 9, 10, 12, 14, 20, 23, 28, 29 and 33 returned `PASS*` even on
clean data. This was fixed in v1.61 (above). See `_superseded_pre_v1.63/RELEASE_NOTES_v1.60.md` §5.

See **`_superseded_pre_v1.63/RELEASE_NOTES_v1.60.md`** for complete details.

---

**v1.59 (2026-08-13) — First Full Release**

Major fixes in this version:
- **Req 4:** CONFORMANT verdict is now reachable (was impossible in v1.58)
- **Req 18:** XSD validation outcome now always reported; `lxml` added to probe
- **--quiet flag:** Now actually suppresses report-written chatter
- **4-tuple normalization:** Manual checks return uniform structure
- **Key-type filtering:** Fragile hardcoded blocklists replaced with type-based selection
- **Packaging:** Prefix-based directory exclusion prevents stale folders in archives

See **RELEASE_NOTES_v1.59.md** for complete details (not shipped in this folder).

---

## Development & Testing

### Run Self-Tests

```batch
conda activate dgiwg
cd path\to\project
python run_local_tests.py
```

This generates test GeoPackages, runs validation, and verifies 84 assertions.

### Build Release Archive

```batch
python package_release.py
```

Output:
- `dist\DGIWG_GeoPackage_Validator_v1.63\` — staged folder
- `dist\DGIWG_GeoPackage_Validator_v1.63.zip` — release archive

The manifest check aborts if required assets are missing (launcher, manual, quick-start, etc.).

---

## Files in This Release

### Core Package
- `dgiwg_validator/` — main package (8 Python modules)
- `DGIWG_Validator_v1_63.py` — launcher script

### Documentation
- `README.md` — this file
- `QUICKSTART.html` — quick-start reference
- `DGIWG_GeoPackage_Validator_User_Manual_v1.63.docx` — full manual
- `RELEASE_NOTES_v1.63.md` — changelog

### Testing & Building
- `run_local_tests.py` — 84 regression tests
- `package_release.py` — release packaging script
- `environment.yml`, `01_create_environment.bat`, `02_build_exe.bat`, `DGIWG_Validator.spec` — build the standalone `.exe` (see BUILD_EXE_QUICKSTART.html)

### Data
- `dgiwg_epsg_cache.json` — embedded EPSG database
- `VERSION.txt` — version metadata

### Archived (superseded, kept for history — not part of the release zip)
- `_superseded_pre_v1.63/` — the v1.61 and v1.62 launchers, the v1.62 manual, and the v1.60/v1.61
  release notes, retired when the project moved to v1.63. `package_release.py` already excludes any
  folder starting with `_superseded` or `_to_delete` from the release archive by name prefix.

### Excluded (Maintainer Only)
- `build_manual.js` — generates User Manual (requires Node.js)
- `REVIEW_FINDINGS_*.md` — internal pre-release notes

---

## Project Structure

```
DGIWG_GeoPackage_Validator_v1.63/
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
├── DGIWG_Validator_v1_63.py   # Launcher (runs -m dgiwg_validator)
├── VERSION.txt                # Release metadata
├── dgiwg_epsg_cache.json      # EPSG codes (offline reference)
├── README.md                  # This file
├── QUICKSTART.html            # Quick-start guide
├── DGIWG_GeoPackage_Validator_User_Manual_v1.63.docx  # Full manual
├── RELEASE_NOTES_v1.63.md     # Changelog
├── run_local_tests.py         # Test suite (84 assertions)
├── package_release.py         # Release builder
└── _superseded_pre_v1.63/     # Archived v1.60-v1.62 files (not shipped)
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

*DGIWG GeoPackage Compliance Validator v1.63*  
