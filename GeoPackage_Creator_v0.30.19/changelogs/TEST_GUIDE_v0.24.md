# GeoPackage Creator v0.24 - Test Guide

## Overview

This guide explains how to test v0.24 features:
- CRS Automatic Conversion (3 modes)
- Automatic Report Generation (HTML/JSON/PDF)
- Performance Metrics
- Real-time Progress Logging

## Prerequisites

```bash
# Install GDAL (OSGeo4W or Conda)
# See GDAL_INSTALLATION.txt

# Install dependencies
pip install lxml

# Optional for PDF reports
pip install reportlab
```

## Test Cases

### Test Case 1: Basic Conversion (No CRS conversion)

**Steps:**
1. Open GeoPackage Creator GUI
2. Select source .gdb file
3. Specify output .gpkg path
4. Fill all required metadata
5. Set CRS Conversion: "None"
6. Enable reports: HTML ✓, JSON ✓
7. Click "Convert to GeoPackage"

**Expected Results:**
- ✓ GeoPackage created
- ✓ HTML report generated
- ✓ JSON report generated
- ✓ Conversion duration displayed

**Validation:**
```bash
# Check GeoPackage structure
ogrinfo output.gpkg

# Check HTML report
Open in browser: output_report.html

# Check JSON report
cat output_report.json
```

---

### Test Case 2: Mode A - Auto Conversion

**Steps:**
1. Select source file with non-DGIWG CRS (e.g., UTM)
2. Set CRS Conversion: "Mode A (Auto-convert)"
3. Enable reports
4. Click "Convert"

**Expected Results:**
- ✓ Non-DGIWG CRS detected
- ✓ Auto-converted to WGS84 (EPSG:4326)
- ✓ Output CRS is EPSG:4326
- ✓ Report shows conversion details

**Verification:**
```bash
# Check output CRS
ogrinfo output.gpkg -sql "SELECT * FROM gpkg_spatial_ref_sys"

# Verify in report
grep "source_epsg\|target_epsg" output_report.json
```

---

### Test Case 3: Mode B - Multi-Version Generation

**Steps:**
1. Select source .gdb file
2. Set CRS Conversion: "Mode B (Multi-version)"
3. Enable reports
4. Click "Convert"

**Expected Results:**
- ✓ Multiple output files generated:
  - output_WGS84.shp (or .gdb)
  - output_WebMercator.shp
  - output_UTM_33N.shp
- ✓ All files created successfully
- ✓ Report shows all generated files
- ✓ Performance metrics displayed

**Verification:**
```bash
# List generated files
ls output_*

# Check each file's CRS
ogrinfo output_WGS84.shp | grep "EPSG"
ogrinfo output_WebMercator.shp | grep "EPSG"
ogrinfo output_UTM_33N.shp | grep "EPSG"
```

---

### Test Case 4: Mode C - Custom CRS

**Steps:**
1. Select source .gdb file
2. Set CRS Conversion: "Mode C (Custom)"
3. Select Target EPSG: "3857" (Web Mercator)
4. Enable reports
5. Click "Convert"

**Expected Results:**
- ✓ Source CRS detected
- ✓ Converted to EPSG:3857 (Web Mercator)
- ✓ Output file has Web Mercator CRS
- ✓ Conversion logged in report

**Verification:**
```bash
# Verify target CRS
ogrinfo output.gpkg | grep "EPSG:3857"
```

---

### Test Case 5: Report Generation (All Formats)

**Steps:**
1. Enable all report formats:
   - HTML ✓
   - JSON ✓
   - PDF ✓
2. Run conversion
3. Click "View Results" button

**Expected Results:**
- ✓ HTML report generated and viewable in browser
- ✓ JSON report generated with structured data
- ✓ PDF report generated (if reportlab installed)
- ✓ "View Results" button shows all reports
- ✓ Can open each report from results window

**Verification:**
```bash
# Check file existence
ls output_report.*

# Validate JSON
python -m json.tool output_report.json > /dev/null

# Open HTML in browser
open output_report.html  # macOS
xdg-open output_report.html  # Linux
start output_report.html  # Windows
```

---

### Test Case 6: Performance Metrics

**Steps:**
1. Select a moderate-sized dataset
2. Run conversion
3. Check log output

**Expected Results:**
- ✓ Execution time displayed (seconds)
- ✓ Features processed shown
- ✓ Layers processed shown
- ✓ Performance metrics in reports

**Verification:**
```bash
# Check performance data in JSON report
grep "duration\|memory\|features_per_sec" output_report.json
```

---

### Test Case 7: DGIWG Compliance Validation

**Steps:**
1. Convert file with DGIWG-approved CRS
2. Check validation results
3. Verify compliance status

**Expected Results:**
- ✓ DGIWG-approved CRS recognized
- ✓ Compliance status = True
- ✓ R-Tree indexes created
- ✓ Metadata ISO 19115 compliant

**Verification:**
```bash
# Check DGIWG status
grep "dgiwg_compliant" output_report.json

# Verify R-Tree indexes
ogrinfo output.gpkg | grep -i "index"
```

---

## Test Data

### Quick Test Dataset

If you don't have OSM data, create a simple test:

**Option 1: Download OSM sample**
```bash
# Download small OSM sample (~50MB)
# Use QGIS: Layer → Add Layer → OpenStreetMap XYZ

# Export to shapefile
Layer → Save As → Format: ESRI Shapefile
```

**Option 2: Use provided test data**
```bash
# If available in project
ls test_data/
```

---

## Test Report Template

**Use this template to document test results:**

```markdown
## Test Results - v0.24

Date: YYYY-MM-DD
Tester: [Your Name]
Platform: Windows/macOS/Linux

### Test Case 1: Basic Conversion
- Status: ✓ PASS / ✗ FAIL
- Notes: [Any issues or observations]

### Test Case 2: Mode A - Auto Conversion
- Status: ✓ PASS / ✗ FAIL
- Notes: [CRS conversion details]

### Test Case 3: Mode B - Multi-Version
- Status: ✓ PASS / ✗ FAIL
- Notes: [File generation details]

### Test Case 4: Mode C - Custom CRS
- Status: ✓ PASS / ✗ FAIL
- Notes: [Custom CRS details]

### Test Case 5: Report Generation
- Status: ✓ PASS / ✗ FAIL
- Notes: [Report format details]

### Test Case 6: Performance
- Duration: X.XX seconds
- Memory: X MB
- Notes: [Performance observations]

### Test Case 7: DGIWG Compliance
- Status: ✓ PASS / ✗ FAIL
- Notes: [Compliance details]

## Summary
- Total Tests: 7
- Passed: X
- Failed: X
- Overall Status: ✓ READY FOR RELEASE / ✗ ISSUES FOUND

## Issues Found
- [Issue 1]
- [Issue 2]
```

---

## CLI Testing (Optional)

**For developers who prefer command-line testing:**

```python
from core.converter import GeoPackageConverter

# Test basic conversion
converter = GeoPackageConverter(profile='default')
result = converter.convert(
    source_geodatabase='test.gdb',
    output_geopackage='test.gpkg',
    title='Test Dataset',
    abstract='Testing v0.24 features',
    poc='Tester',
    org='Test Org',
    nation='USA',
    # New v0.24 parameters
    crs_conversion_mode='a',
    generate_reports=True,
)

# Check results
print(f"Success: {result['success']}")
print(f"CRS Conversion: {result['crs_conversion']}")
print(f"Reports: {result['reports']}")
print(f"Duration: {result['performance']['duration']:.2f}s")
```

---

## Troubleshooting

### GDAL Installation Issues
- See GDAL_INSTALLATION.txt
- Verify with: `python -c "from osgeo import ogr; print('OK')"`

### Report Generation Fails
- HTML/JSON should work without extra libraries
- PDF requires: `pip install reportlab`
- Falls back to HTML if reportlab missing

### Performance Slow
- Check system resources
- Large datasets may take time
- See performance metrics in reports

### CRS Conversion Errors
- Verify EPSG code exists
- Check source CRS is supported
- See error details in log

---

## Release Checklist

Before releasing v0.24, verify:

- ✓ All 7 test cases pass
- ✓ No critical bugs found
- ✓ Reports generate correctly
- ✓ CRS conversion works (3 modes)
- ✓ Performance is acceptable
- ✓ DGIWG compliance validated
- ✓ Documentation complete
- ✓ Version updated to v0.24

---

## Next Steps

After testing:
1. Document any issues
2. Fix critical bugs
3. Update version to v0.24
4. Create final release zip
5. Update documentation

---

## Support

For issues or questions:
- Check log messages in GUI
- Review error details in reports
- See documentation files
- Check TEST_GUIDE_v0.24.md (this file)
