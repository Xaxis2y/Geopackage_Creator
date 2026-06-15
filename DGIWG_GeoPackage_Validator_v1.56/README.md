# DGIWG GeoPackage Compliance Validator

Validate GeoPackage (`.gpkg`) files against the **DGIWG GeoPackage Profile (STD-DP-19-005 v1.1)** and generate per-file HTML + JSON compliance reports, plus a batch roll-up summary.

**Version:** 1.56 · Checks Requirements 1–37 · Pure-Python core (no mandatory third-party dependencies).

---

## Features

- **Full requirement coverage** — evaluates DGIWG Requirements 1–37 (CRS, extensions, metadata, tile matrix, gridded coverage, data validity, and more), each scored as `PASS`, `FAIL`, `PASS*` (conditional/fallback), or `SKIPPED`.
- **Forensic source-software detection** — fingerprints the producing software (QGIS/GDAL, ArcGIS, or Unknown) and tags reports accordingly, with software-specific audit hints.
- **HTML + JSON reports** — a human-readable HTML report and a machine-readable JSON companion (CI/CD friendly) are written for every file.
- **Batch & folder processing** — validate a single file, a folder, or many of each in one run; a roll-up report aggregates the results.
- **Online or air-gapped** — verifies EPSG/OGC URIs over the network, or runs fully offline with `--offline` (uses a bundled EPSG cache; affected checks return `PASS*`).
- **Optional accuracy boosters** — uses `pyproj`, `shapely`, and `Pillow` if present for deeper checks, and falls back gracefully to structural checks when they are absent.
- **Interactive or CLI** — run with no arguments for a file-picker dialog, or pass paths/flags for scripted use.

## Requirements

- **Python 3.10+** (uses modern type-union syntax)
- No mandatory third-party packages — the core runs on the standard library alone.
- **Optional** (recommended for fuller coverage):

  ```bash
  pip install pyproj shapely Pillow
  ```

  | Library  | Enables                                            |
  |----------|----------------------------------------------------|
  | `pyproj` | Req 13 — datum/EPSG name cross-check (offline)      |
  | `shapely`| Req 24 — OGC geometry validity (WKB decode)        |
  | `Pillow` | Req 26 — tile BLOB pixel-dimension decode          |

  If these are missing, the validator prompts to install them (suppress with `--no-install`).

## Installation

No install step is required — clone or download the repository and run it in place.

```bash
git clone <repo-url>
cd DGIWG_GeoPackage_Validator_v1.56
```

## Usage

### Interactive (file picker)

Double-click `DGIWG_Validator_v1_56.py`, or run:

```bash
python DGIWG_Validator_v1_56.py
```

### Command line

```bash
# Validate a single file
python DGIWG_Validator_v1_56.py myfile.gpkg

# Validate every .gpkg in a folder
python DGIWG_Validator_v1_56.py /path/to/folder/

# Run as a module
python -m dgiwg_validator myfile.gpkg

# Explicit flags (equivalent to positional args; repeatable)
python -m dgiwg_validator --file map_data.gpkg
python -m dgiwg_validator --dir "C:\Data\Project_Alpha"

# Air-gapped network — skip all EPSG/OGC internet checks
python -m dgiwg_validator --offline myfile.gpkg
```

### Options

| Flag                | Description                                                                 |
|---------------------|-----------------------------------------------------------------------------|
| `--file FILE`       | Validate a single `.gpkg` file (repeatable).                                |
| `--dir FOLDER`      | Validate all `.gpkg` files in a folder (repeatable).                        |
| `--recursive`       | Search folders recursively for `.gpkg` files.                              |
| `--offline`         | Disable all internet checks; affected checks return `PASS*`.               |
| `--no-install`      | Skip optional-library install prompts.                                      |
| `--sample-size N`   | BLOBs sampled per table for Req 24 & 26 (default: 25).                      |
| `--timeout SECONDS` | Network timeout for HTTP checks (default: 8s).                              |
| `--output-dir DIR`  | Write all reports to this folder instead of the default `reports/`.        |
| `--json`            | (Retained for compatibility — JSON is now always written.)                 |
| `--quiet`           | Suppress per-file progress banners.                                         |
| `--fail-fast`       | Stop after the first file with any `FAIL` result (exits with code 1).      |
| `--version`         | Print version and exit.                                                     |

## Output

For each GeoPackage, the validator writes:

- `<name>_<SOFTWARE>_DGIWG_Report.html` — full per-file HTML report
- `<name>_<SOFTWARE>_DGIWG_Report.json` — machine-readable companion (verdict, counts, per-requirement status/detail)

In batch/folder mode, reports are collected in a `reports/` subfolder (or `--output-dir`), alongside an aggregated **roll-up** summary.

Each report yields an overall verdict plus counts of `PASS`, `FAIL`, `PASS*`, and `SKIPPED` requirements.

## Project structure

```
DGIWG_Validator_v1_56.py          # Double-click / CLI launcher
dgiwg_validator/
├── __init__.py
├── __main__.py                   # `python -m dgiwg_validator`
├── main.py                       # Entry-point logic & CLI parsing
├── checks.py                     # Requirement checks (Req 1–37)
├── constants.py                  # Requirement & extension lookup tables
├── forensics.py                  # Source-software detection
├── net.py                        # EPSG/OGC network checks + offline cache
├── html_report.py                # HTML report rendering
├── rollup.py                     # Batch roll-up aggregation
└── utils.py                      # GeoPackage I/O, optional-lib probing, helpers
DGIWG_GeoPackage_Validator_User_Manual_v1.56.docx   # Full user manual
```

## Documentation

See `DGIWG_GeoPackage_Validator_User_Manual_v1.56.docx` for the complete user manual.

## Notes

- Non-GeoPackage files and empty SQLite stubs (missing core tables such as `gpkg_contents` / `gpkg_spatial_ref_sys`) are detected and skipped.
- GeoPackages are opened **read-only**; the validator never modifies input files.
- Requirements 1 and 2 require OGC CITE TeamEngine and are reported as `SKIPPED` (cannot be automated here).
