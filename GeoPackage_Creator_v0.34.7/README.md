# GeoPackage Creator (DGIWG-Compliant)

**Version 0.34.7** | October 19, 2026 | OGC GeoPackage 1.4 & DGIWG profile pre-validation

## Overview

GeoPackage Creator is a standalone, GDAL-based Python tool that converts spatial data (ESRI File Geodatabases, Shapefiles, GeoJSON, PostGIS) into OGC GeoPackage 1.4 files that meet Defense Geospatial Information Working Group (DGIWG) requirements. It runs anywhere Python and GDAL are available — no ArcGIS license required.

It provides three interfaces: a graphical application (tkinter GUI), a command-line tool, and a Python API.

## What is DGIWG?

DGIWG (Defense Geospatial Information Working Group) is an international organization that establishes geospatial standards for defense and security applications. GeoPackages created by this tool implement DGIWG metadata, security classification, CRS, and spatial-index requirements.

## Folder Contents

The release source includes the application, schemas, bundled v1.64 validator,
documentation, tests, and release-verification scripts. The GitHub-ready
source-only archive excludes generated build folders, frozen executables,
validation runs, logs, caches, compiled Python files, and sample geodatabase
data. It contains source and documentation only so it can be committed to or
uploaded to GitHub without carrying local build artifacts.

## Copyright and license

Copyright (c) 2026 Eui Soo SON. This project is licensed under
`GPL-2.0-or-later`; see [LICENSE](LICENSE) and [COPYRIGHT.md](COPYRIGHT.md).

```
GeoPackage_Creator/
├── geopackage_creator.py        # Command-line interface
├── geopackage_creator_gui.py    # Graphical interface (tkinter + ttkbootstrap)
├── START_HERE.bat               # Windows launcher (GUI or CLI)
├── Anaconda_Start.bat           # Anaconda Prompt launcher (creates/activates the conda env)
├── CHANGELOG.md                 # Consolidated release history
├── dev_tools/                   # Current release verification scripts
├── environment.yml              # Conda environment spec (pinned GDAL version + pip: ttkbootstrap)
├── requirements.txt             # Pip requirements
├── VERSION.txt                  # Current version and pointer to CHANGELOG.md
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
├── DGIWG_GeoPackage_Validator_v1.64/  # Bundled DGIWG GeoPackage Validator source
├── docs/                        # Technical setup and GUI documentation
│   ├── GUI_USAGE_GUIDE.md       # GUI guide
│   ├── GDAL_INSTALLATION.txt    # GDAL setup instructions
│   ├── DEPENDENCIES.txt         # Dependency reference
│   └── ROADMAP_RASTER.md        # Raster support roadmap
└── CHANGELOG.md                 # Consolidated release history
```

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

### Windows: create the Conda environment first

Open **Anaconda Prompt**, then run these commands from the project folder:

```bat
conda env create -f environment.yml
conda activate geopackage
```

This installs the tested GDAL build plus lxml, reportlab, pytest, and the GUI
dependency `ttkbootstrap`. If the environment already exists, use
`conda env update -n geopackage -f environment.yml --prune` instead of creating
it again. You can also double-click `Anaconda_Start.bat`; it creates and
activates the same environment interactively.

After activation, start the application with `START_HERE.bat` or one of the
commands below. Do not use Anaconda's base environment for the application.

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

See **USER_MANUAL.md** for full documentation and **QUICKSTART.md** for a 5-minute walkthrough.

## Testing

```bash
conda activate geopackage
python -m pytest -q
```

Note: most integration tests create real spatial data and therefore require GDAL to be installed. The metadata, config, validator, and embedding tests run without spatial data.

### Release validation

Run the release validation from an activated, dedicated `geopackage` Conda
environment. Do not install the dependencies into Anaconda's `base`
environment.

```bat
python validate_geopackage_creator_v0347.py --samples "C:\path\to\GeoPackage_Creator_v0.34.7" --exe "C:\path\to\v0.34.7\dist\GeoPackageCreator.exe"
```

The validation runner records the full pytest suite, bundled DGIWG validator
self-tests, independent FileGDB audits, full-coverage validator output, and
frozen-EXE version/help checks in a timestamped `validation_runs` folder. The
`--exe` value must be the actual v0.34.7 executable; an example or placeholder
path is reported as a technical failure.

Regenerate the v0.34.7 evidence after building the executable. The evidence
must include the application test suite, the v1.64 bundled-validator
self-tests, independent SampleData and States FileGDB audits, full-coverage
validator output, and frozen-EXE version/help checks. These results are
software pre-validation evidence, not formal DGIWG or OGC certification.

## Standards Compliance

- OGC GeoPackage 1.4 (user_version 10400)
- DGIWG GeoPackage profile (per-data-type approved CRS, R-Tree indexes, security metadata, DMF record)
- ISO 19115 (geographic metadata in the ISO 19139 `gmd` encoding, embedded via the GeoPackage Metadata Extension)
- DGIWG Metadata Foundation (DMF) 2.0
- ISO 639-2 (language codes), ISO 3166-1 alpha-3 (nation codes)

### External acceptance boundaries

The bundled validator cannot independently establish every external acceptance
condition. Requirements 1 and 2 require OGC CITE/TeamEngine testing; the
conditional-extension decision in Requirement 6 depends on the selected
product profile; and Requirement 26 requires real tile data when raster
coverage is claimed. A feature-only GeoPackage can legitimately report tile
requirements as not applicable or evidence-missing. Formal DGIWG acceptance
must therefore be confirmed against the applicable product profile and test
authority.

### GeoPackage header compatibility

Outputs use the standard OGC GeoPackage `application_id = GPKG`
(`0x47504B47`) and `user_version = 10400` for GeoPackage 1.4.

## Version

**Current:** v0.34.7.

v0.34.7 keeps the v0.34.6 Req. 24 precision-aware RTree bounding-box fix and
validation evidence gate, and upgrades the bundled validator to
`DGIWG_GeoPackage_Validator_v1.64`. The release validation runner now invokes
the v1.64 launcher and writes v0.34.7 evidence paths. See `CHANGELOG.md` for
the complete release history.
**Maintained for:** Multi-platform GeoPackage conversion with DGIWG profile
pre-validation and explicit external-acceptance boundaries.
