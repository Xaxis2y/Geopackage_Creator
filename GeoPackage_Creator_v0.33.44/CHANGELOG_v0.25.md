# Changelog — GeoPackage Creator v0.25.0

**Release Date:** June 5, 2026  
**Type:** Bug Fix & Quality Improvement Release

---

## Bug Fixes

### BUG-1 — `core/config.py`: `SECURITY_CODE_MAP` duplicate definition
- **Problem:** `SECURITY_CODE_MAP` was defined twice. The second definition mapped
  `"TOP SECRET"` to `"top_secret"`, overwriting the first definition's ISO 19115
  compliant value `"topSecret"`. This caused non-standard code values to be
  written into metadata XML for TOP SECRET datasets.
- **Fix:** Removed the second `SECURITY_CODE_MAP` block entirely. The single
  remaining definition uses the ISO 19115 standard code values throughout.

### BUG-2 — `core/crs_converter.py`: Incomplete `DGIWG_APPROVED_CRS`
- **Problem:** The module defined its own `DGIWG_APPROVED_CRS` set containing
  only 28 of the 60 NATO UTM zones (EPSG:32633–32660). Zones 32601–32632 were
  missing, causing Mode A/B/C CRS validation to incorrectly reject data in those
  zones as "non-DGIWG-approved."
- **Fix:** `DGIWG_APPROVED_CRS` is now derived from `core/config.py` (the single
  source of truth), which contains all 62 approved codes (WGS84, Web Mercator,
  and all 60 UTM zones 32601–32660).

### BUG-3 — `core/crs_converter.py`: `_perform_conversion()` output as Shapefile
- **Problem:** The output driver was hardcoded as `'ESRI Shapefile'`, so CRS
  conversions (Mode A, B, C) produced `.shp` files instead of `.gpkg` files.
  This was a fundamental defect in v0.24's headline CRS conversion feature.
- **Fix:** Output driver changed to `'GPKG'`. Spatial index (`SPATIAL_INDEX=YES`)
  is applied to converted layers. `_get_output_filename()` always produces a
  `.gpkg` extension regardless of input format. Added explicit `IOError` when
  `CreateDataSource` returns `None`.

### BUG-4 — `geopackage_creator.py`: CLI `--security TOP_SECRET` fails at runtime
- **Problem:** The `argparse` choices list used `'TOP_SECRET'` (underscore), but
  `SECURITY_LEVELS` and all internal validators expect `'TOP SECRET'` (space).
  Passing `--security TOP_SECRET` from the CLI caused a runtime
  `ValidationError` immediately after argument parsing.
- **Fix:** Changed the argparse choice to `'TOP SECRET'` and updated the help
  text to note that shell quoting is required (`--security "TOP SECRET"`).

### BUG-5 — `tests/test_config.py`: `"boundaryPolygons"` not in `TOPIC_CATEGORIES`
- **Problem:** `TestTopicCategories.test_topic_categories_includes_required`
  asserted `"boundaryPolygons"` was in `TOPIC_CATEGORIES`. The correct ISO 19115
  value is `"boundaries"`. This test always failed when executed.
- **Fix:** Assertion changed to `"boundaries"`.

---

## Improvements

### W-1 — `core/config.py`: `METADATA_MIME_TYPE` duplicate definition removed
- Second definition `"text/xml"` was silently overwriting the correct value
  `"application/xml+iso:19115"`. Removed the first (incorrect) definition and
  its associated comment block.

### W-2 — `core/crs_converter.py`: Explicit error on `CreateDataSource` failure
- Replaced walrus-operator pattern (`if output_ds := ...`) with explicit `None`
  check and `IOError` raise, making failures visible rather than silently skipped.

### W-3 — `core/converter.py`: `strict_crs_validation` parameter added
- `GeoPackageConverter.convert()` gains `strict_crs_validation: bool = False`.
  When `True`, the conversion aborts with a `ValidationError` if any layer has a
  non-DGIWG-approved CRS. When `False` (default), the existing behaviour of
  adding a warning and continuing is preserved for backward compatibility.

### W-4 — `core/converter.py`: Duplicate `result["success"] = True` removed
- `result["success"] = True` was assigned at Step 9 and again at the end of the
  function. Removed the Step 9 assignment; success is now set exactly once at
  the end, just before the return, after all steps complete.

### W-5 — `core/converter.py`: `source_ds` resource leak fixed
- `source_ds = ogr.Open(...)` is now wrapped in a `try/finally` block so that
  `source_ds = None` is always executed, even when an exception occurs during
  CRS validation or layer copying.

### W-6 — `core/report_generator.py`: `_build_pdf_sections()` implemented
- Previously returned an empty list, producing blank PDF reports when reportlab
  was installed. Now generates proper reportlab `Paragraph`, `Table`, and
  `Spacer` flowables for five sections: Conversion Info, Input/Output Files,
  CRS, Performance Metrics, and Validation Results.

### W-7 — `START_HERE.bat`: Version string updated
- All occurrences of `v0.23` updated to `v0.25`.

### W-8 — `tests/test_metadata_handler.py`: Invalid `NATO_RESTRICTED` removed
- `"NATO_RESTRICTED"` is not in `SECURITY_LEVELS` and would cause
  `validate_security_level()` to raise at runtime. Replaced with `"RESTRICTED"`,
  which is a valid security level, completing the full five-level parametrize set.

---

## Files Changed

| File | Change type |
|------|-------------|
| `core/config.py` | Bug fix (BUG-1, W-1), version bump |
| `core/crs_converter.py` | Bug fix (BUG-2, BUG-3, W-2) |
| `core/converter.py` | Improvement (W-3, W-4, W-5) |
| `core/report_generator.py` | Improvement (W-6), version string |
| `geopackage_creator.py` | Bug fix (BUG-4) |
| `START_HERE.bat` | Version string (W-7) |
| `VERSION.txt` | Version bump to 0.25.0 |
| `tests/test_config.py` | Bug fix (BUG-5) |
| `tests/test_metadata_handler.py` | Improvement (W-8) |
