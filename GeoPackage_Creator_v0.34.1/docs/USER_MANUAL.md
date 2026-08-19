# GeoPackage Creator — User Manual

**Version 0.34.1 | August 19, 2026**
**OGC GeoPackage 1.4 & DGIWG Compliant**

---

## 1. What is GeoPackage Creator?

GeoPackage Creator is a desktop tool that converts military and civilian spatial data into **DGIWG-compliant GeoPackage files (.gpkg)**. It is designed for GIS analysts, defense mapping agencies, and NATO/partner-nation organizations that need to share geospatial data in a standardized, single-file format.

### What it does

It takes your source spatial data — ESRI File Geodatabases (.gdb), Shapefiles (.shp), GeoJSON, or PostGIS databases — and produces an OGC GeoPackage 1.4 file that automatically satisfies all DGIWG (Defense Geospatial Information Working Group) requirements:

- **R-Tree spatial indexes** on every layer (DGIWG-mandatory)
- **ISO 19115 metadata** embedded directly in the file (package-level + per-layer)
- **DGIWG-approved coordinate reference systems** (WGS 84, Web Mercator, NATO UTM zones)
- **Security classification** labeling (UNCLASSIFIED through TOP SECRET)
- **DGIWG validation** report with pass/fail results for all 37 requirements

A GeoPackage is a single SQLite file. Any GIS application that supports OGC standards — QGIS, ArcGIS, GDAL, NGA tools — can open it directly.

### Who it is for

- GIS analysts producing data for NATO/coalition operations
- Defense mapping agencies publishing geospatial products
- Operators running batch conversions from the command line
- Developers integrating GeoPackage conversion into data pipelines

### What it does NOT do (yet)

- Raster tile conversion (planned — see `ROADMAP_RASTER.md`)
- Direct editing of existing GeoPackages
- Direct support for ArcPy or QGIS Python environments (uses only osgeo/GDAL)

---

## 2. Installation

### 2.1 System Requirements

| Component | Minimum | Tested |
|-----------|---------|--------|
| Python | 3.8 | 3.11 |
| GDAL | 3.6.0 | **3.13.2** (conda-forge) |
| OS | Windows 10, macOS 12, Ubuntu 20.04 | Windows 10/11 |
| Disk | 500 MB | — |

> **GDAL 3.13.2** is the version tested and recommended for this release
> (moved from 3.13.1 in v0.30.13 - a support decision, not a bug fix; see
> `CHANGELOG_v0.30.13.md`). Earlier 3.x versions (>= 3.6.0) should work but
> are not actively tested.
>
> v0.34 runs ISO metadata schema validation and DGIWG validation in isolated
> helper processes. This keeps GDAL and lxml/libxml2 out of the same process,
> preventing the Windows shutdown crash found in earlier releases.

### 2.2 Create the supported Conda environment (recommended)

On Windows, open **Anaconda Prompt**, change to the GeoPackage Creator folder,
and run:

```bat
conda env create -f environment.yml
conda activate geopackage
```

This is the supported first-time setup. It installs the tested GDAL build and
all Python dependencies, including `lxml`, `reportlab`, `pytest`, and
`ttkbootstrap` for the GUI. Do not run the application from Anaconda's base
environment. If the environment already exists, update it with:

```bat
conda env update -n geopackage -f environment.yml --prune
conda activate geopackage
```

You may alternatively double-click `Anaconda_Start.bat`, which creates and
activates the same environment interactively.

### 2.3 Installing GDAL manually (alternative)

GDAL includes native C++ libraries and cannot be installed with a simple `pip install`. Choose one method:

**Option A — Conda (recommended for all platforms)**
```bash
conda install -c conda-forge gdal=3.13.2 lxml
```
Or create a fresh environment:
```bash
conda create -n geopackage -c conda-forge python=3.11 gdal=3.13.2 lxml
conda activate geopackage
```

**Option B — OSGeo4W (Windows only)**

1. Download from https://trac.osgeo.org/osgeo4w/
2. Run the installer -> Express Desktop Install
3. Ensure GDAL 3.11.x is selected
4. Open OSGeo4W Shell for all subsequent commands

**Option C — System package manager**

Ubuntu/Debian: `sudo apt-get install gdal-bin python3-gdal`
macOS (Homebrew): `brew install gdal`

Full details are in `GDAL_INSTALLATION.txt`.

### 2.4 Installing Python dependencies manually

From the GeoPackage Creator folder:
```bash
pip install -r requirements.txt
```

### 2.5 Verifying the installation

```bash
python -c "from osgeo import gdal; print('GDAL', gdal.__version__)"
python -c "import ttkbootstrap; print('ttkbootstrap OK')"
python geopackage_creator.py --help
```

Both commands should succeed. GDAL 3.13.2 will print `GDAL 3.13.2`.

---

## 3. Quick Start

### 3.1 Windows launcher

Double-click `START_HERE.bat`. A menu appears:
- **Option 1** — launches the graphical interface
- **Option 2** — guided command-line conversion

### 3.2 First conversion via GUI

```
python geopackage_creator_gui.py
```

1. Browse to your source `.gdb` folder (or `.shp`/`.geojson` file)
2. Choose an output `.gpkg` path
3. Fill in Title, Organization, Nation Code, Point of Contact, Abstract
4. Click **Convert**

Progress appears in the log panel. A results window opens when finished.

### 3.3 First conversion via command line

```bash
python geopackage_creator.py \
    --source data/roads.gdb \
    --output output/roads.gpkg \
    --title "Road Network" \
    --org "Defense Mapping Agency" \
    --nation USA
```

---

## 4. The Graphical Interface (GUI)

Start with: `python geopackage_creator_gui.py`

### 4.1 File Selection

**Source FileGDB** — click Browse. Select the File Geodatabase *folder itself*
(do not double-click into it). A `.gdb` suffix is conventional but not required
when the folder contains `GEODATABASE_FILE_*` markers. Shapefiles and GeoJSON
can be selected as files.

**Output .gpkg** — the destination GeoPackage file. The parent folder must exist.

### 4.2 Metadata (Required)

| Field | Description |
|-------|-------------|
| Title | Dataset title recorded in ISO 19115 metadata |
| Organization | Producing agency |
| Nation Code | ISO 3166-1 alpha-3 (e.g., USA, GBR, DEU) — must be one of the 42 NATO/partner codes (Appendix A) |
| Point of Contact | Responsible person's name |
| Abstract | Dataset description (at least 10 characters) |

### 4.3 Optional Metadata

**Security Level** — UNCLASSIFIED (default), RESTRICTED, CONFIDENTIAL, SECRET, or TOP SECRET. Always choose the highest classification that applies to any data in the package.

**Language Code** — ISO 639-2 code, default `eng`.

**Topic Category** — one of the 19 ISO 19115 categories (Appendix B).

**Profile** — preset combination of settings (see section 7).

### 4.4 CRS Conversion

If your source data uses a coordinate reference system not approved by DGIWG, use one of these modes:

| Mode | Behavior |
|------|----------|
| A | Reprojects all layers to WGS 84 (EPSG:4326) |
| B | Writes three output files: WGS 84, Web Mercator, and UTM 33N |
| C | Reprojects to the EPSG code you enter in the Target EPSG field |

Leave the mode unset if the source CRS is already DGIWG-approved.

### 4.5 Report Generation

When enabled, three reports are written next to the output file:

- `<name>_report.html` — human-readable, for review and archiving
- `<name>_report.json` — machine-readable, for pipelines and audits
- `<name>_report.pdf` — printable (requires the reportlab package)

### 4.6 Running and reading results

Click **Convert**. The log panel shows each step in real time. When finished, a results window shows layers copied, features written, DGIWG compliance status, embedded metadata records, and report file paths. Use **Clear Log** to reset between runs.

---

## 5. The Command-Line Interface (CLI)

```
python geopackage_creator.py --source SOURCE --output OUTPUT --title TITLE --org ORG --nation NATION [options]
```

### 5.1 Required arguments

| Argument | Description |
|----------|-------------|
| `--source`, `-s` | Source: .gdb folder, .shp, .geojson, or PostGIS connection string |
| `--output`, `-o` | Output GeoPackage path (.gpkg) |
| `--title`, `-t` | Dataset title |
| `--org` | Organization name |
| `--nation` | ISO 3166-1 alpha-3 nation code (e.g., USA) |

### 5.2 Optional arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--abstract`, `-a` | Dataset description | — |
| `--poc`, `-p` | Point of contact | — |
| `--security` | Classification level (quote values with spaces: `--security "TOP SECRET"`) | profile setting |
| `--language` | ISO 639-2 language code | `eng` |
| `--category` | ISO 19115 topic category | profile setting |
| `--ref-date` | Reference date (YYYY-MM-DD) | today |
| `--profile` | default, military, civilian, high_security | `default` |
| `-v` | Verbose logging | off |
| `--quiet` | Suppress non-error output | off |

### 5.3 Examples

Unclassified civilian conversion:
```bash
python geopackage_creator.py -s parcels.shp -o parcels.gpkg \
    -t "Cadastral Parcels" --org "City GIS" --nation USA --profile civilian
```

Classified military conversion:
```bash
python geopackage_creator.py -s ops.gdb -o ops.gpkg \
    -t "Operational Areas" --org "Defense Mapping Agency" --nation GBR \
    --profile military --security SECRET --category intelligenceMilitary
```

Exit code is 0 on success and non-zero on failure — suitable for batch scripts.

---

## 6. The Python API

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
    security="CONFIDENTIAL",          # optional -- defaults from profile
    language="eng",                   # optional
    topic_category="transportation",  # optional
    ref_date="2026-06-16",            # optional -- defaults to today
    crs_conversion_mode=None,         # 'a', 'b', 'c', or None
    crs_target_epsg=None,             # required for mode 'c'
    generate_reports=True,
    strict_crs_validation=False,      # True = abort on non-DGIWG CRS
)

if result["success"]:
    print(result["output_path"], result["layer_count"], result["total_features"])
    print("Metadata records embedded:", result["metadata_embedded"])
else:
    print("Error:", result["error"])
```

The result dictionary also contains `dgiwg_compliant`, `r_tree_indexes`, `crs_conversion`, `reports` (paths to HTML/JSON/PDF), `performance`, and `warnings`.

---

## 7. Conversion Profiles

| Profile | Security | Language | Topic Category |
|---------|----------|----------|----------------|
| default | UNCLASSIFIED | eng | location |
| military | CONFIDENTIAL | eng | intelligenceMilitary |
| civilian | UNCLASSIFIED | eng | environment |
| high_security | SECRET | eng | intelligenceMilitary |

Profiles provide defaults only — any value you pass explicitly overrides the profile. All profiles enable R-Tree spatial indexes (DGIWG-mandatory).

---

## 8. Coordinate Reference Systems

DGIWG approves three CRS families:
- **WGS 84** — EPSG:4326
- **Web Mercator** — EPSG:3857
- **NATO UTM zones** — EPSG:32601–32660 (zones 1N through 60N)

If source data uses any other CRS, the tool warns by default (or aborts when `strict_crs_validation=True`). Use a CRS conversion mode to fix this automatically.

---

## 9. Metadata and Security Classification

The tool generates ISO 19115 metadata XML and validates it against the bundled schema (`schemas/`). Two records are created per conversion: one package-level record and one per layer.

Metadata is embedded directly in the GeoPackage using the OGC Metadata Extension: records are stored in `gpkg_metadata`, linked through `gpkg_metadata_reference`, and the extension is registered in `gpkg_extensions`. QGIS, GDAL, and any OGC-aware client can read it.

Security classification appears in metadata as `MD_SecurityConstraints` with ISO 19115 code values (e.g., TOP SECRET -> `topSecret`). Always select the highest classification of any content in the package.

---

## 10. Conversion Reports

Unless disabled, three reports are written next to the output GeoPackage:

- `<name>_report.html` — human-readable; open in any browser
- `<name>_report.json` — machine-readable; use in auditing pipelines
- `<name>_report.pdf` — printable (requires: `pip install reportlab`)

Reports include conversion parameters, processed layers, CRS validation results, performance metrics, and per-requirement DGIWG compliance results.

---

## 11. Validation and Compliance

After every conversion the tool verifies:

- Output opens as a valid GeoPackage
- Required tables present: `gpkg_contents`, `gpkg_spatial_ref_sys`, `gpkg_geometry_columns`, `gpkg_extensions`
- Every layer has an R-Tree spatial index
- Declared CRS is recorded in `gpkg_spatial_ref_sys`
- Metadata tables populated

The result is reported as `dgiwg_compliant` in the conversion results and in all reports.

To validate independently, run the bundled DGIWG Validator:
```bash
python DGIWG_GeoPackage_Validator_v1.62/DGIWG_Validator_v1_62.py output.gpkg
```
Or load the file in QGIS -> Layer Properties -> Metadata.

---

## 12. Testing the Installation

The tool ships with a pytest suite (240+ tests):

```bash
pip install pytest
pytest
```

Tests cover configuration, validators, metadata generation, metadata embedding, and integration (integration tests require GDAL).

---

## 13. Troubleshooting

**"No module named 'osgeo'"**
GDAL Python bindings are not installed. Install with `conda install -c conda-forge gdal=3.13.2 lxml` and verify with `python -c "from osgeo import gdal; print(gdal.__version__)"`.

**"GDAL GPKG driver not available"**
The installed GDAL build lacks GeoPackage support. Install GDAL 3.6+ from conda-forge or OSGeo4W.

**"Nation code 'XYZ' not in NATO/partner nation list"**
Use one of the 42 approved ISO 3166-1 alpha-3 codes (Appendix A).

**"Security level not valid"**
Use exactly: UNCLASSIFIED, RESTRICTED, CONFIDENTIAL, SECRET, or TOP SECRET. On the command line, quote values with spaces: `--security "TOP SECRET"`.

**"EPSG code not in DGIWG-approved CRS list"**
The source CRS is not approved. Use CRS conversion Mode A or C, or accept the warning if compliance is not required.

**GUI does not start ("No module named 'tkinter'")**
On Linux: `sudo apt-get install python3-tk`. Windows and macOS python.org installers include tkinter by default.

**PDF report missing**
Install reportlab: `pip install reportlab`. HTML and JSON reports are unaffected.

**Source FileGDB not recognized**
Select the geodatabase folder itself, not a file inside it. A folder without a
`.gdb` suffix is valid when it contains `GEODATABASE_FILE_*` markers.

**"database is locked"**
Close the output file in QGIS or any other application before converting.

---

## Appendix A — Approved Nation Codes (42)

ALB, AUS, AUT, BEL, BGR, CAN, CHE, CHL, COL, CZE, DEU, DNK, ESP, EST, FIN, FRA, GBR, GRC, HRV, HUN, IRL, ISL, ITA, JPN, KOR, LTU, LUX, LVA, MKD, MNE, NLD, NOR, NZL, POL, PRT, ROU, SVK, SVN, SWE, TUR, UKR, USA

---

## Appendix B — ISO 19115 Topic Categories (19)

farming, biota, boundaries, climatologyMeteorologyAtmosphere, economy, elevation, environment, geoscientificInformation, health, imageryBaseMapsEarthCover, intelligenceMilitary, inlandWaters, location, oceans, planningCadastre, society, structure, transportation, utilitiesCommunication

---

## Appendix C — DGIWG-Approved CRS

| EPSG | Name |
|------|------|
| 4326 | WGS 84 (geographic) |
| 3857 | Web Mercator (projected) |
| 32601–32660 | NATO UTM zones 1N–60N |

---

## Appendix D — Version History

| Version | Date | Summary |
|---------|------|---------|
| **0.30.1** | 2026-06-18 | Updated GDAL to 3.13.1. Fixed `converter.py` truncated docstring (unterminated triple-quoted string at `get_active_profile_config`). |
| 0.30.0 | 2026-06-18 | Fix 1: `application_id` changed to GP14 (0x47503134) to match `user_version=10400` (GeoPackage 1.4) — resolves OGC validation failure. Fix 2: WKT2 format switched to WKT2_2015 so EPSG:4326 uses `DATUM[...]` instead of `ENSEMBLE[...]` — resolves DGIWG Req 13 offline datum-name mismatch. DGIWG validator updated to accept GP13/GP14 as conformant. |
| 0.29.1 | 2026-06-16 | Documentation overhaul; GDAL 3.13.1 explicitly documented; build scripts updated. No code changes from 0.29.0. |
| 0.29.0 | 2026-06-15 | Fixed false-failure: `success` flag now set before report generation. Fixed DGIWG Validator Req 24 false FAIL (Z/M flags read from WKB type code, not header envelope bits). Unified version strings. |
| 0.28.0 | 2026-06-12 | Fixed bounding box mismatch in `gpkg_contents`. Fixed Z/M consistency post-write. |
| 0.27.0 | 2026-06-11 | Per-data-type DGIWG CRS policy. DGIWG DMF metadata (Req 18). Raster foundations (no
