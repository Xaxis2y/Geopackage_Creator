# GeoPackage Creator - Quick Start Guide (v0.34)

## How to Start

### 1. Create and activate the environment (Windows / Anaconda Prompt)

Open **Anaconda Prompt**, change to this project folder, and run:

```bat
conda env create -f environment.yml
conda activate geopackage
```

This is required before running the GUI or CLI: it installs GDAL, lxml,
reportlab, pytest, and `ttkbootstrap`. If `geopackage` already exists, update
it with:

```bat
conda env update -n geopackage -f environment.yml --prune
conda activate geopackage
```

Alternatively, double-click `Anaconda_Start.bat` to create and activate the
same environment. Do not run the tool from Anaconda's base environment.

### 2. **Using the GUI (Easiest)**

The simplest way - just run the GUI application:

```bash
python geopackage_creator_gui.py
```

Then:
1. Click "Browse..." next to "Source FileGDB"
2. Select the FileGDB folder itself (click once, do not open it). A `.gdb`
   suffix is conventional but not required when `GEODATABASE_FILE_*` markers exist.
3. Fill in the required metadata (Title, Organization, Nation Code, etc.)
4. Click "Convert to GeoPackage"
5. Watch the progress in the log window

See `GUI_USAGE_GUIDE.md` for detailed instructions.

### 3. **Basic Usage (Command Line)**

The simplest way to convert data:

```bash
python geopackage_creator.py \
    --source input.gdb \
    --output output.gpkg \
    --title "My Dataset" \
    --org "My Organization" \
    --nation "USA"
```

### 4. **What You Need to Provide**

**Required:**
- `--source` - Your data file (supports .gdb, .shp, .geojson, PostGIS)
- `--output` - Output GeoPackage file name (.gpkg)
- `--title` - What to call your dataset
- `--org` - Organization name
- `--nation` - ISO country code (USA, GBR, DEU, FRA, etc.)

**Optional but recommended:**
- `--abstract` - Description of the data
- `--poc` - Person responsible for the data
- `--security` - Classification (UNCLASSIFIED, CONFIDENTIAL, SECRET)
- `--profile` - Conversion profile (default, military, civilian, high_security)

### 5. **Example: Converting a Shapefile**

```bash
python geopackage_creator.py \
    --source roads.shp \
    --output roads.gpkg \
    --title "Road Network" \
    --abstract "Primary and secondary roads for the region" \
    --poc "Jane Smith" \
    --org "Transportation Department" \
    --nation "USA" \
    --security UNCLASSIFIED \
    --profile military
```

### 6. **Example: Converting a File Geodatabase (GDB)**

```bash
python geopackage_creator.py \
    --source buildings.gdb \
    --output buildings.gpkg \
    --title "Building Footprints" \
    --abstract "2D building outlines for urban areas" \
    --poc "Major John Wilson" \
    --org "Defense Mapping Agency" \
    --nation "USA" \
    --security CONFIDENTIAL \
    --language eng \
    --category military_bases \
    --ref-date 2026-06-03 \
    --profile military
```

### 5. **Understanding the Output**

When conversion completes successfully, you'll see:

```
============================================================
✓ CONVERSION SUCCESSFUL
============================================================
Output:           output.gpkg
Layers:           3
Total Features:   15,234
DGIWG Compliant:  True
R-Tree Indexes:   True

Layers Created:
  • buildings: 8,945 features (Polygon)
  • roads: 4,321 features (LineString)
  • points_of_interest: 1,968 features (Point)
============================================================
```

### 6. **Using as a Python Module**

If you want to use it in your own Python code:

```python
from geopackage_creator import GeoPackageConverter

# Create converter with military profile
converter = GeoPackageConverter(profile='military')

# Convert your data
result = converter.convert(
    source_geodatabase='input.gdb',
    output_geopackage='output.gpkg',
    title='My Dataset',
    abstract='Description of the data',
    poc='Your Name',
    org='Your Organization',
    nation='USA',
    security='UNCLASSIFIED',
    language='eng',
    topic_category='military_bases',
    ref_date='2026-06-03'
)

# Check result
if result['success']:
    print(f"Created: {result['output_path']}")
    print(f"Layers: {result['layer_count']}")
    print(f"Features: {result['total_features']}")
    print(f"DGIWG Compliant: {result['dgiwg_compliant']}")
else:
    print(f"Error: {result['error']}")
```

## Conversion Profiles

Choose the profile that best fits your use case:

| Profile | Use Case | Default Security | Default Language |
|---------|----------|------------------|------------------|
| `default` | Standard GIS operations | UNCLASSIFIED | eng |
| `military` | NATO/Defense operations | CONFIDENTIAL | eng |
| `civilian` | Public GIS data | UNCLASSIFIED | eng |
| `high_security` | Classified/restricted data | SECRET | eng |

## Common Commands

**File Geodatabase → GeoPackage**
```bash
python geopackage_creator.py -s data.gdb -o data.gpkg --title "Data" --org "Org" --nation "USA"
```

**Shapefile → GeoPackage**
```bash
python geopackage_creator.py -s data.shp -o data.gpkg --title "Data" --org "Org" --nation "USA"
```

**GeoJSON → GeoPackage**
```bash
python geopackage_creator.py -s data.geojson -o data.gpkg --title "Data" --org "Org" --nation "USA"
```

**With Full Metadata**
```bash
python geopackage_creator.py \
    -s input.gdb -o output.gpkg \
    --title "Dataset Title" \
    --abstract "Full description" \
    --poc "Contact Name" \
    --org "Organization" \
    --nation "USA" \
    --security CONFIDENTIAL \
    --language eng \
    --category transportation \
    --ref-date 2026-06-03 \
    --profile military
```

## Troubleshooting

**Error: Source file not found**
- Check that your file path is correct
- Make sure the file exists in the current directory or provide absolute path

**Error: GDAL not found**
- Install GDAL: `pip install gdal` or use OSGeo4W
- On Linux: `sudo apt-get install gdal-bin python3-gdal`
- On macOS: `brew install gdal`

**Error: CRS not DGIWG-approved**
- Your data uses a coordinate system not on the approved list
- Reproject to: WGS84 (EPSG:4326), Web Mercator (EPSG:3857), or NATO UTM zones
- Use QGIS or GDAL to reproject before conversion

**Error: Nation code not recognized**
- Use ISO 3166-1 alpha-3 codes: USA, GBR, DEU, FRA, etc.
- Not: "United States" or "US" - must be 3-letter code

## What Gets Created

Your output GeoPackage (.gpkg) file will contain:

✓ All layers from source data
✓ R-Tree spatial indexes (DGIWG requirement)
✓ ISO 19115 metadata
✓ Proper geometry type handling
✓ Attribute tables
✓ Coordinate reference system information

## Next Steps

1. **Verify the output**: Open in QGIS or ArcGIS to check
2. **Share with others**: GeoPackages work across all major GIS software
3. **Deploy**: Use in maps, analysis, or data services
4. **Archive**: Store for long-term reference

## Getting Help

For detailed API reference, see: `USER_MANUAL.md`

For more complex scenarios:
- Check Python module usage examples above
- Review the test cases in `tests/`
- Read docstrings in `core/converter.py`

---

**GeoPackage Creator v0.34** | OGC 1.4 & DGIWG Compliant | August 17, 2026
