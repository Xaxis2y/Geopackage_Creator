# GeoPackage Creator — User Manual

**Version 0.26.0 | June 9, 2026**
**OGC GeoPackage 1.4 & DGIWG Compliant**

---

## 1. Introduction

GeoPackage Creator converts spatial data — ESRI File Geodatabases (.gdb), Shapefiles (.shp), GeoJSON files, and PostGIS databases — into OGC GeoPackage 1.4 files (.gpkg) that satisfy Defense Geospatial Information Working Group (DGIWG) requirements.

A GeoPackage is a single, open-standard SQLite file that holds vector layers, spatial indexes, and metadata. DGIWG adds defense-specific requirements on top of the OGC standard: approved coordinate reference systems, mandatory R-Tree spatial indexes, ISO 19115 metadata, and security classification labeling. This tool enforces all of them automatically.

### 1.1 Who is this manual for?

Anyone who needs to produce DGIWG-compliant GeoPackages: GIS analysts using the graphical interface, operators running batch conversions from the command line, and developers integrating the Python API.

### 1.2 What the tool produces

Each conversion creates a .gpkg file containing all source layers with R-Tree spatial indexes, embedded ISO 19115 metadata (package-level and per-layer), security classification constraints, and — optionally — HTML, JSON, and PDF conversion reports written next to the output file.

## 2. Installation

### 2.1 Requirements

The tool requires Python 3.8 or newer and GDAL 3.6 or newer with Python bindings. The lxml package is needed for metadata schema validation, reportlab for PDF reports, and tkinter for the GUI (included with most Python installations).

### 2.2 Installing GDAL

GDAL must be installed separately because it includes native libraries. Choose one option:

Conda (recommended): `conda install -c conda-forge gdal`

OSGeo4W (Windows): download from https://trac.osgeo.org/osgeo4w/ and select GDAL during setup.

System package manager: on Ubuntu/Debian `sudo apt-get install gdal-bin python3-gdal`; on macOS `brew install gdal`.

Full details are in `GDAL_INSTALLATION.txt`.

### 2.3 Installing Python dependencies

From the tool folder run:

```bash
pip install -r requirements.txt
```

### 2.4 Verifying the installation

```bash
python -c "from osgeo import ogr; print('GDAL OK')"
python geopackage_creator.py --help
```

If both commands succeed, the tool is ready.

## 3. Quick Start

### 3.1 Windows launcher

Double-click `START_HERE.bat`. A menu offers the GUI (option 1) or a guided command-line conversion (option 2).

### 3.2 First conversion via GUI

Run `python geopackage_creator_gui.py`, select the source .gdb folder and output .gpkg path, fill in Title, Organization, Nation Code, Point of Contact, and Abstract, then press Convert. Progress appears in the log panel and a results window opens when finished.

### 3.3 First conversion via command line

```bash
python geopackage_creator.py \
    --source data/roads.gdb \
    --output output/roads.gpkg \
    --title "Road Network" \
    --org "Defense Mapping Agency" \
    --nation USA
```

## 4. The Graphical Interface (GUI)

Start the GUI with `python geopackage_creator_gui.py`.

### 4.1 File Selection

**Source .gdb** — click Browse to select the source. For File Geodatabases select the .gdb *folder itself* (do not double-click into it). Shapefiles and GeoJSON files can be selected as files.

**Output .gpkg** — choose where the GeoPackage will be written. The folder must exist and be writable.

### 4.2 Metadata (Required)

**Title** — dataset title recorded in ISO 19115 metadata.
**Organization** — producing agency or organization.
**Nation Code** — ISO 3166-1 alpha-3 code of the producer nation (e.g., USA, GBR, DEU). Must be one of the 42 NATO/partner codes (Appendix A).
**Point of Contact** — responsible person's name.
**Abstract** — dataset description (at least 10 characters).

### 4.3 Optional Metadata

**Security Level** — UNCLASSIFIED (default), RESTRICTED, CONFIDENTIAL, SECRET, or TOP SECRET. Choose the highest classification that applies to any data in the package.
**Language Code** — ISO 639-2 code, default `eng`.
**Topic Category** — one of the 19 ISO 19115 categories (Appendix B).
**Profile** — preset combination of settings (section 7).

### 4.4 CRS Conversion

**Mode A** — automatically reprojects data in a non-DGIWG CRS to WGS 84 (EPSG:4326).
**Mode B** — produces multiple versions of the output: WGS 84, Web Mercator, and UTM 33N.
**Mode C** — reprojects to the EPSG code you enter in the Target EPSG field.
Leave the mode unset for no conversion. All converted outputs are GeoPackages with spatial indexes.

### 4.5 Report Generation

When enabled, HTML, JSON, and PDF conversion reports are written next to the output file (e.g., `roads_report.html`). Reports include conversion details, file information, CRS results, performance metrics, and validation results.

### 4.6 Running and reading results

Press Convert. The log panel shows each step in real time. The results window summarizes layers copied, features written, DGIWG compliance status, embedded metadata records, and report paths. Use Clear Log to reset the panel between runs.

## 5. The Command-Line Interface (CLI)

```
python geopackage_creator.py --source SOURCE --output OUTPUT --title TITLE --org ORG --nation NATION [options]
```

### 5.1 Required arguments

| Argument | Description |
|----------|-------------|
| `--source`, `-s` | Source file: .gdb folder, .shp, .geojson, or PostGIS connection string |
| `--output`, `-o` | Output GeoPackage path (.gpkg) |
| `--title`, `-t` | Dataset title for metadata |
| `--org` | Organization name |
| `--nation` | ISO 3166-1 alpha-3 nation code (e.g., USA) |

### 5.2 Optional arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--abstract`, `-a` | Dataset description | — |
| `--poc`, `-p` | Point of contact | — |
| `--security` | UNCLASSIFIED, RESTRICTED, CONFIDENTIAL, SECRET, TOP SECRET (quote values containing spaces: `--security "TOP SECRET"`) | profile setting |
| `--language` | ISO 639-2 language code | profile setting (eng) |
| `--category` | ISO 19115 topic category | profile setting |
| `--ref-date` | Reference date, YYYY-MM-DD | today |
| `--profile` | default, military, civilian, high_security | default |
| `-v` | Verbose logging | off |
| `--quiet` | Suppress non-error output | off |

CRS conversion modes and report toggles are available through the GUI and the Python API; the CLI generates reports by default.

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

The exit code is 0 on success and non-zero on failure, so the CLI can be used in batch scripts.

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
    security="CONFIDENTIAL",          # optional, defaults from profile
    language="eng",                   # optional
    topic_category="transportation",  # optional
    ref_date="2026-06-09",            # optional, defaults to today
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

## 7. Conversion Profiles

| Profile | Security | Language | Topic Category |
|---------|----------|----------|----------------|
| default | UNCLASSIFIED | eng | location |
| military | CONFIDENTIAL | eng | intelligenceMilitary |
| civilian | UNCLASSIFIED | eng | environment |
| high_security | SECRET | eng | intelligenceMilitary |

Profiles only provide defaults — any value you pass explicitly overrides the profile. All profiles enable R-Tree spatial indexes (DGIWG-mandatory).

## 8. Coordinate Reference Systems

DGIWG approves these CRS: WGS 84 (EPSG:4326), Web Mercator (EPSG:3857), and all 60 NATO UTM zones (EPSG:32601–32660).

If source data uses another CRS, the tool warns by default (or aborts when `strict_crs_validation=True`). To fix non-approved CRS automatically, use a conversion mode: Mode A reprojects to WGS 84; Mode B writes three outputs (WGS 84, Web Mercator, UTM 33N); Mode C reprojects to an EPSG code you specify. Converted outputs are always GeoPackages with spatial indexes.

## 9. Metadata and Security Classification

The tool generates ISO 19115 metadata XML — one package-level record describing the whole dataset and one record per layer — and validates it against the bundled ISO 19115 schema (`schemas/`).

Since v0.26, metadata is embedded directly in the GeoPackage using the OGC Metadata Extension: records are stored in `gpkg_metadata`, linked through `gpkg_metadata_reference` (geopackage scope for the package record, table scope for layer records), and the extension is registered in `gpkg_extensions`. Any standards-aware client (QGIS, GDAL, validators) can read it.

Security classification appears in metadata as an ISO 19115 `MD_SecurityConstraints` element with the standard code values (e.g., TOP SECRET → `topSecret`). Always select the highest classification of any content in the package.

## 10. Conversion Reports

Unless disabled, three reports are written next to the output GeoPackage:

`<name>_report.html` — human-readable report for review and archiving.
`<name>_report.json` — machine-readable results for pipelines and audits.
`<name>_report.pdf` — printable report (requires the reportlab package).

Reports cover conversion parameters, processed files and layers, CRS validation and conversion results, performance metrics, and output validation findings.

## 11. Validation and Compliance

After every conversion the tool verifies that the output opens as a GeoPackage and contains the required tables (`gpkg_contents`, `gpkg_spatial_ref_sys`, `gpkg_geometry_columns`, `gpkg_extensions`), that every layer has an R-Tree spatial index, that the declared CRS is recorded in `gpkg_spatial_ref_sys`, and that metadata tables are present and populated. The result is reported as `dgiwg_compliant` in the conversion results.

To validate independently, you can run the OGC GeoPackage validator or load the file in QGIS and inspect Layer Properties → Metadata.

## 12. Testing the Installation

The tool ships with a pytest suite (240+ tests):

```bash
pip install pytest
pytest
```

Configuration, validator, metadata-generation, and metadata-embedding tests run on any machine. Integration tests create real spatial data and require GDAL.

## 13. Troubleshooting

**"No module named 'osgeo'"** — GDAL Python bindings are not installed. See section 2.2; verify with `python -c "from osgeo import ogr"`.

**"GDAL GPKG driver not available"** — the GDAL build lacks GeoPackage support. Install GDAL 3.6+ from conda-forge or OSGeo4W.

**"Nation code 'XYZ' not in NATO/partner nation list"** — use one of the 42 approved ISO 3166-1 alpha-3 codes (Appendix A).

**"Security level not valid"** — use exactly one of: UNCLASSIFIED, RESTRICTED, CONFIDENTIAL, SECRET, TOP SECRET. On the command line, quote values with spaces: `--security "TOP SECRET"`.

**"EPSG code not in DGIWG-approved CRS list"** — the source CRS is not approved. Use CRS conversion Mode A or C, or accept the warning if compliance is not required.

**GUI does not start ("No module named 'tkinter'")** — install tkinter (Windows/macOS python.org installers include it; on Linux `sudo apt-get install python3-tk`).

**PDF report missing** — install reportlab: `pip install reportlab`. HTML and JSON reports are unaffected.

**Source .gdb not recognized** — select the .gdb folder itself, not a file inside it, and verify with `ogrinfo yourdata.gdb`.

**Output file locked / "database is locked"** — close the file in QGIS or other applications before converting. The tool serializes concurrent writes to the same file, but other programs holding the file open will block it.

## Appendix A — Approved Nation Codes (42)

ALB, AUS, AUT, BEL, BGR, CAN, CHE, CHL, COL, CZE, DEU, DNK, ESP, EST, FIN, FRA, GBR, GRC, HRV, HUN, IRL, ISL, ITA, JPN, KOR, LTU, LUX, LVA, MKD, MNE, NLD, NOR, NZL, POL, PRT, ROU, SVK, SVN, SWE, TUR, UKR, USA

## Appendix B — ISO 19115 Topic Categories (19)

farming, biota, boundaries, climatologyMeteorologyAtmosphere, economy, elevation, environment, geoscientificInformation, health, imageryBaseMapsEarthCover, intelligenceMilitary, inlandWaters, location, oceans, planningCadastre, society, structure, transportation, utilitiesCommunication

## Appendix C — DGIWG-Approved CRS

EPSG:4326 (WGS 84), EPSG:3857 (Web Mercator), EPSG:32601–32660 (NATO UTM zones 1N–60N)

## Appendix D — Version History

v0.26 (June 9, 2026): metadata now embedded in output (critical fix), ISO 19115 schema validation restored, test suite repaired, 42 nation codes, documentation refreshed.
v0.25: security code map, CRS list, and output-driver fixes.
v0.24: CRS auto-conversion (3 modes), HTML/JSON/PDF reports, performance metrics.
v0.23/v0.22: GUI, .gdb folder picker, real-time logging, multi-threading.

---

*GeoPackage Creator v0.26.0 — OGC GeoPackage 1.4 & DGIWG Compliant*
