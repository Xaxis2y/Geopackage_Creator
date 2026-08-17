# GeoPackage Creator (DGIWG-Compliant)

**Version 0.30.23** | August 14, 2026 | OGC GeoPackage 1.4 & DGIWG Compliant

## Overview

GeoPackage Creator is a standalone, GDAL-based Python tool that converts spatial data (ESRI File Geodatabases, Shapefiles, GeoJSON, PostGIS) into OGC GeoPackage 1.4 files that meet Defense Geospatial Information Working Group (DGIWG) requirements. It runs anywhere Python and GDAL are available — no ArcGIS license required.

It provides three interfaces: a graphical application (tkinter GUI), a command-line tool, and a Python API.

## What is DGIWG?

DGIWG (Defense Geospatial Information Working Group) is an international organization that establishes geospatial standards for defense and security applications. GeoPackages created by this tool implement DGIWG metadata, security classification, CRS, and spatial-index requirements.

## Folder Contents

Reorganized in v0.30.15/v0.30.16 to keep the project root readable - see
`changelogs/CHANGELOG_v0.30.16.md` (or `VERSION.txt`) for the record of that
cleanup. That reorganization described moving superseded files into an
`archive/` folder and built release zips into `release_dist/` - as of this
snapshot (v0.30.19) `archive/` still does not exist in the tree, and the
`dev_tools/` QA-harness scripts it described had also gone missing (rebuilt
fresh in v0.30.18 as `run_release_check_v0.30.18.py` - see
`CHANGELOG_v0.30.18.md`). `release_dist/` now does exist, populated by
running `package_release_v0.30.19.py` (see below). The tree below is what
is actually on disk now, not what an earlier changelog said should be
there - if the two ever disagree again, trust the tree and flag it, the
way this entry itself does.

```
GeoPackage_Creator/
├── geopackage_creator.py        # Command-line interface
├── geopackage_creator_gui.py    # Graphical interface (tkinter + ttkbootstrap)
├── START_HERE.bat               # Windows launcher (GUI or CLI)
├── Anaconda_Start.bat           # Anaconda Prompt launcher (creates/activates the conda env)
├── package_release_v0.30.19.py  # Current release packager (builds release_dist/*.zip)
├── environment.yml              # Conda environment spec (pinned GDAL version + pip: ttkbootstrap)
├── requirements.txt             # Pip requirements
├── VERSION.txt                  # Full version history (all releases, newest first)
├── core/                        # Library modules
│   ├── config.py                # DGIWG constants, profiles, approved CRS
│   ├── converter.py             # Main orchestrator (GeoPackageConverter)
│   ├── gdal_handler.py          # GDAL/OGR I/O (+ concurrency variant)
│   ├── validators.py            # Input/output/CRS validation
│   ├── metadata_handler.py      # ISO 19115 metadata generation
│   ├── dgiwg_compliance.py      # DGIWG compliance checks
│   ├── crs_converter.py         # CRS detection & conversion (Modes A/B/C)
│   ├── validation_gate.py       # Locates/invokes the bundled DGIWG validator
│   └── report_generator.py      # HTML / JSON / PDF conversion reports
├── schemas/                     # ISO 19115 / GML XSD schemas
├── tests/                       # Pytest suite
├── packaging/                   # Windows .exe build pipeline (PyInstaller)
├── DGIWG_GeoPackage_Validator_v1.58/  # Bundled DGIWG GeoPackage Validator (v0.30.17+)
├── docs/                        # User-facing documentation
│   ├── USER_MANUAL.md / .docx   # Detailed user manual
│   ├── QUICKSTART.md            # 5-minute quick start
│   ├── GETTING_STARTED.md       # Developer-oriented guide
│   ├── GUI_USAGE_GUIDE.md       # GUI guide (Korean)
│   ├── INSTALLATION_GUIDE.md    # Install guide
│   ├── GDAL_INSTALLATION.txt    # GDAL setup instructions
│   ├── DEPENDENCIES.txt         # Dependency reference
│   ├── QUICK_FIX_CONDA.txt      # Conda troubleshooting
│   └── ROADMAP_RASTER.md        # Raster support roadmap
├── changelogs/                  # Every CHANGELOG_vX.Y.Z.md, oldest to newest
├── dev_tools/                   # QA/diagnostic harness, not part of the shipped tool
│   └── run_release_check_v0.30.18.py / .bat   # Pre-release gate (rebuilt v0.30.18)
└── release_dist/                # Built release zip output (created by the packager, not a fresh-checkout fixture)
    ├── GeoPackage_Creator_v0.30.19.zip
    └── RELEASE_INFO_v0.30.19.txt
```

Not currently present: `archive/` (superseded-file storage) - created on
demand if a future reorganization needs it; nothing currently creates it.
`release_dist/` is not a fresh-checkout fixture either, but unlike
`archive/` it does exist right now, populated by the last packager run.

## Key Features

- **Multi-format input** — File Geodatabase (.gdb), Shapefile (.shp), GeoJSON, PostGIS
- **OGC GeoPackage 1.4 output** — created with `VERSION=1.4` and validated after creation
- **Embedded ISO 19115 metadata** *(new in v0.26)* — package- and layer-level metadata written into `gpkg_metadata` / `gpkg_metadata_reference` via the OGC Metadata Extension
- **DGIWG security classifications** — UNCLASSIFIED, RESTRICTED, CONFIDENTIAL, SECRET, TOP SECRET, plus NATO markings (NATO RESTRICTED … COSMIC TOP SECRET) and releasability statements *(new in v0.27)*
- **Per-data-type DGIWG CRS policy** *(new in v0.27)* — enforces the DGIWG GeoPackage Profile per data type: 2D vector = WGS 84 (4326) only (Req 9); 3D vector = 4979/9518; tiles/gridded = 3395, 3857, 4326, UPS 5041/5042, UTM north 32601–32660 **and south 32701–32760**; optional `strict_crs_validation`
- **CRS auto-conversion** — Mode A (to WGS84), Mode B (multi-version output), Mode C (user-specified EPSG)
- **R-Tree spatial indexes** — created on every layer (DGIWG-mandatory)
- **DGIWG Metadata Foundation (DMF) record** *(new in v0.27)* — every GeoPackage carries a DMF 2.0 metadata row (`https://dgiwg.org/std/dmf/2.0`) so validator Req 18 fully PASSes
- **DGIWG validator gate** *(new in v0.27)* — `--validate` runs the external DGIWG GeoPackage Validator (all 37 requirements) after conversion and embeds the per-requirement table in the reports
- **Raster foundations** *(new in v0.27)* — tile/gridded CRS policy, 256×256 / zoom-factor-2 constants and validation helpers (`core/raster_support.py`); full raster conversion planned for v0.28 (see `ROADMAP_RASTER.md`)
- **Conversion reports** — HTML, JSON, and PDF generated alongside the output
- **Conversion profiles** — `default`, `military`, `civilian`, `high_security`
- **42 NATO / partner nation codes**, 28+ ISO 639-2 language codes, 19 ISO 19115 topic categories

## Requirements

- Python 3.8+
- GDAL ≥ 3.6 with Python bindings (`osgeo`) — see `docs/GDAL_INSTALLATION.txt`
- `lxml` (metadata schema validation) — `pip install -r requirements.txt`
- `reportlab` (optional, for PDF reports)
- tkinter (bundled with most Python installs, for the GUI)
- `ttkbootstrap==2.2.0` *(new in v0.30.18)* — GUI theming. Pip only, not on
  conda-forge; `environment.yml` installs it via its `pip:` section, or run
  `pip install ttkbootstrap==2.2.0` manually — see `docs/DEPENDENCIES.txt`

## Quick Start

**Windows:** double-click `START_HERE.bat` and choose GUI or command line.

**GUI:**
```bash
python geopackage_creator_gui.py
```

**Command line:**
```bash
python geopackage_creator.py \
    --source data/roads.gdb \
    --output output/roads.gpkg \
    --title "Road Network" \
    --org "Defense Mapping Agency" \
    --nation USA \
    --security "UNCLASSIFIED" \
    --profile default
```

**Python API:**
```python
from core import GeoPackageConverter

converter = GeoPackageConverter(profile="military")
result = converter.convert(
    source_geodatabase="input.gdb",
    output_geopackage="output.gpkg",
    title="Military Road Network",
    abstract="Vector road network for NATO operations",
    poc="Jane Smith",
    org="Defense Mapping Agency",
    nation="USA",
)
print(result["success"], result["metadata_embedded"])
```

See **docs/USER_MANUAL.md** for full documentation and **docs/QUICKSTART.md** for a 5-minute walkthrough.

## Testing

```bash
pip install pytest
pytest
```

Note: most integration tests create real spatial data and therefore require GDAL to be installed. The metadata, config, validator, and embedding tests run without spatial data.

## Standards Compliance

- OGC GeoPackage 1.4 (user_version 10400)
- DGIWG GeoPackage profile (per-data-type approved CRS, R-Tree indexes, security metadata, DMF record)
- ISO 19115 (geographic metadata in the ISO 19139 `gmd` encoding, embedded via the GeoPackage Metadata Extension)
- DGIWG Metadata Foundation (DMF) 2.0
- ISO 639-2 (language codes), ISO 3166-1 alpha-3 (nation codes)

### Note: application_id `GP12` vs OGC `GPKG` (deliberate design decision)

OGC GeoPackage 1.2+ specifies the SQLite header `application_id` as `GPKG`
(0x47504B47) with the version in `user_version` (10400 = 1.4.0). The DGIWG
GeoPackage Validator, however, requires the legacy version-encoding marker
`GP12` (0x47503132) and reports Req 3 as FAIL for `GPKG`. Because these two
rules conflict, this tool intentionally writes **`application_id = GP12` and
`user_version = 10400`** during DGIWG finalization. GDAL and QGIS recognise
both markers; some strict OGC tools may warn about the non-standard
application_id. **Do not "fix" this** without re-testing against the DGIWG
validator — see `changelogs/CHANGELOG_v0.26.2.md` and `HANDOFF_NOTES_2026-06-10.md`.

## Version

**Current:** v0.30.23 — see `changelogs/CHANGELOG_v0.30.23.md` and
`VERSION.txt` (the project root's `VERSION.txt` is the authoritative,
full, newest-first history; individual `changelogs/CHANGELOG_vX.Y.Z.md`
files cover one release each).
**Release status:** CANDIDATE — pending verification on the target machine.
v0.30.20's `libxml2=2.14` pin fixed a real version mismatch but was proven,
on the real machine, NOT to fix the crash itself. Diagnostics in v0.30.21/22
(also run on the real machine) found the actual cause: a compiled XSD schema
that survives a GDAL write crashes the process, on every write, regardless of
libxml2 version agreement. v0.30.23 removes the compiled-schema cache in
`core/metadata_handler.py` entirely — every validation now compiles a fresh
schema, used immediately and discarded, which is the only pattern proven safe
by direct testing. This fix has NOT yet been run on the target machine. Run
`dev_tools\run_release_check_v0.30.23.py` there — its `batch_conversion_cycle`
stage is the decisive check — then a real GDB→GPKG conversion and DGIWG
validation before distributing. See `VERSION.txt`'s v0.30.23 entry.
**Maintained for:** Multi-platform DGIWG-compliant geospatial data conversion
