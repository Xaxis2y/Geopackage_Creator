# GeoPackage Creator - GUI Usage Guide

## Getting Started

### How to Launch the GUI

```bash
python geopackage_creator_gui.py
```

Or, on Windows, double-click:
- Double-click the `geopackage_creator_gui.py` file

## GUI Layout

### 1️⃣ File Selection

**Source .gdb**: Select the `.gdb` folder
- Click the "Browse..." button
- **Important**: Do not double-click the folder
- Select the `.gdb` folder with a **single click**
- Click the "Select Folder" button
- ✓ The `.gdb` folder path is displayed

**Output .gpkg**: Path for the GeoPackage file to save
- Click the "Browse..." button
- Enter a file name (e.g., `output.gpkg`)
- Choose the save folder
- Click "Save"

### 2️⃣ Metadata (Required)

| Field | Description | Example |
|------|------|------|
| **Title** | Dataset name | "Building Structures" |
| **Organization** | Agency/organization name | "City Urban Planning Team" |
| **Nation Code** | ISO 3166-1 code | "CAN" (Canada), "USA" |
| **Point of Contact** | Contact person's name | "John Doe" |
| **Abstract** | Dataset description | Enter a detailed description |

### 3️⃣ Optional Metadata

| Field | Default | Options |
|------|-------|------|
| **Security Level** | UNCLASSIFIED | CONFIDENTIAL, SECRET, TOP SECRET |
| **Language Code** | eng | Language codes (eng, fra, deu, etc.) |
| **Topic Category** | geoscientificInformation | transportation, boundaries, etc. |
| **Profile** | default | military, civilian, high_security |

### 4️⃣ Progress/Log

The conversion progress and detailed logs are shown in real time.

## Usage Example

### Step-by-Step Guide

1. **Launch the GUI**
   ```bash
   python geopackage_creator_gui.py
   ```

2. **Select the Source .gdb**
   - Click "Browse..."
   - Select the folder path:
     ```
     C:\Users\Son\Documents\ArcGIS\Projects\geopackage_creator\Default.gdb
     ```
   - Click "Select Folder"

3. **Specify the Output .gpkg path**
   - Click "Browse..."
   - Specify the save path: `C:\output\my_data.gpkg`
   - Click "Save"

4. **Enter the required information**
   - Title: `Road Network Data`
   - Organization: `City Planning Department`
   - Nation Code: `USA`
   - Point of Contact: `John Doe`
   - Abstract: `Road network vector data for city planning`

5. **Start the conversion**
   - Click the "Convert to GeoPackage" button
   - Watch the progress in the Log window

6. **Check the results**
   - A success message appears when the conversion completes
   - Detailed results are shown in the Log window
   - Verify the output file path

## Key Features

### ✓ Selecting the .gdb folder correctly
- In the Windows file browser, **select the folder itself** (do not navigate into it)
- Do not double-click the folder
- The GUI automatically handles the correct path

### ✓ Real-time logging
- Displays conversion progress in real time
- Shows error/warning messages
- Shows detailed statistics after conversion completes

### ✓ Validation
- Validates all required fields
- Checks whether the file path exists
- Verifies the `.gdb` folder is valid

### ✓ Multithreaded processing
- Keeps the GUI responsive
- The UI stays responsive even during long conversions

## Troubleshooting

### Problem 1: "Selected folder does not end with '.gdb'"
**Cause**: Wrong folder selected
**Solution**:
- Select a folder that ends with `.gdb`
- Example: `Default.gdb`

### Problem 2: "Source folder not found"
**Cause**: The path does not exist
**Solution**:
- Verify that the path is correct
- Check folder access permissions

### Problem 3: An error occurs during conversion
**How to check**:
- Review the error message in the Log window
- If needed, copy it to the clipboard to share

## Advanced Usage

### Using Different Profiles

**Military Profile**
```
Profile: military
Security Level: CONFIDENTIAL or SECRET
Language Code: eng
```

**Civilian Profile**
```
Profile: civilian
Security Level: UNCLASSIFIED
Topic Category: planningCadastre
```

### Metadata Entry Tips

**Writing the Abstract**:
- Describe the purpose of the dataset
- Key characteristics (e.g., number of layers, number of features)
- Accuracy and quality information
- Update frequency

Example:
```
This dataset contains building structure vector data
prepared according to 2026 urban planning standards.
It includes approximately 50,000 polygon features, and
all features have been converted to the WGS84 coordinate
system (EPSG:4326). The accuracy is ±5 meters.
```

## Verifying the Output File

After conversion completes:
- A GeoPackage file (`.gpkg`) is created
- Compliant with the OGC 1.4 standard
- Compliant with DGIWG requirements
- Includes metadata
- Includes R-Tree spatial indexes

### Opening in QGIS

```
QGIS → Layer → Add Layer → Add Vector Layer
→ Data Source: [the generated .gpkg file]
```

## Command-Line Version Also Available

If the GUI is inconvenient, use the CLI version:

```bash
python geopackage_creator.py \
    --source Default.gdb \
    --output output.gpkg \
    --title "My Dataset" \
    --org "My Organization" \
    --nation USA \
    --poc "John Doe" \
    --abstract "Dataset description"
```

## Support

If you run into problems:

- Make sure GDAL/osgeo is installed for the Python you are launching with
  (run `python -c "from osgeo import ogr"` — it should print nothing and exit 0).
- Install dependencies with `pip install -r requirements.txt`.
- On Windows, launch with `START_HERE.bat`, which uses the Anaconda Python that
  ships with GDAL.
- See `INSTALLATION_GUIDE.md` and `GDAL_INSTALLATION.txt` for setup help, and
  `VERSION.txt` / the newest `changelogs/CHANGELOG_v*.md` for release history.
