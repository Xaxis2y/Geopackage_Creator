# Changelog — GeoPackage Creator v0.30.4

Release date: 2026-06-18  
Type: Patch (bug-fix only)

---

## Bug Fixes

### 🔴 Critical

**`core/crs_converter.py` — file was truncated (SyntaxError)**  
The `_perform_conversion` method ended mid-f-string (`f"(EPSG:{source_epsg} → EPSG:"`),
causing an `ImportError` at startup and silently disabling all three CRS conversion
modes (A / B / C). The `_get_output_filename()` helper method was also entirely
absent, meaning any call to modes A, B, or C would have failed with `AttributeError`
even if the syntax error were somehow bypassed.  
Fixed: completed the f-string, added a `finally` block to release GDAL datasource
handles on both success and failure paths, and added the full `_get_output_filename()`
implementation.

---

### 🟠 Significant

**`core/validators.py` — `logger` used but never defined (NameError)**  
`OutputValidator.validate_gpkg_structure()` called `logger.warning()` when compliance
issues were detected, but the module contained no `import logging` and no
`logger = logging.getLogger(...)`. Any conversion that produced compliance warnings
would crash with `NameError: name 'logger' is not defined` — ironically making the
warning path the crash path.  
Fixed: added standard `logging` import and `NullHandler` logger.

**`core/converter.py` — DGIWG Req 24 helpers were dead code**  
`_fix_bbox_from_rtree()` and `_strip_z_from_2d_layers()` were introduced in v0.28.0
with docstrings citing DGIWG Req 24, and the `_finalize_dgiwg_compliance()` info dict
had slots for their results (`bbox_fixed_layers`, `z_stripped_layers`) — but neither
method was ever called. Bbox corrections and Z-flag strips silently did nothing,
leaving Req 24 partially unaddressed.  
Fixed: both helpers are now invoked from `_finalize_dgiwg_compliance()`. The sqlite3
connection is explicitly closed before `_strip_z_from_2d_layers()` runs its GDAL
update handle, preventing a write-lock deadlock.

---

### 🟡 Minor

**`core/dgiwg_compliance.py` — NATO security markings rejected in `validate_metadata_fields()`**  
`InputValidator.validate_security_level()` (v0.27.0) correctly accepts NATO markings
(`NATO SECRET`, `COSMIC TOP SECRET`, etc.), but the parallel static method
`DGIWGCompliance.validate_metadata_fields()` only checked the five national levels,
producing false validation failures for NATO-classified datasets.  
Fixed: imported `NATO_SECURITY_MARKINGS` and updated the security check.

**`core/metadata_handler.py` — `lineage` parameter silently discarded**  
`generate_package_metadata()` accepted a `lineage` argument (surfaced in the GUI and
CLI) but never emitted it in the generated XML. Provenance/source information passed
by the user was accepted, XML-escaped, and then dropped without error.  
Fixed: added `<gmd:lineage>/<gmd:LI_Lineage>/<gmd:statement>` inside
`<gmd:dataQualityInfo>` so lineage reaches the GeoPackage metadata record.

**`core/gdal_handler.py` — bare `raise` in `validate_geopackage_output()` lost exception type**  
Caught `Exception as e` then re-raised with a bare `raise`, making errors opaque to
callers that catch `ValidationError`. Unexpected exceptions now wrap in
`ValidationError(...) from e`; existing `ValidationError` instances pass through
unchanged.

---

## OGC / DGIWG Compliance (unchanged from v0.30.3)

- GP14 application_id (`0x47503134`), WAL checkpoint — Req 3 ✅
- 2D vector CRS = EPSG:4326 only — Req 9 ✅
- WKT2_2015 in `definition_12_063` (avoids ENSEMBLE datum mismatch) — Req 13 ✅
- DMF record with `https://dgiwg.org/std/dmf/2.0` URI — Req 18 ✅
- ISO 19115 package + layer metadata embedded — Req 19–20 ✅
- RTree bbox sync + Z-flag consistency (**now actually executed**) — Req 24 ✅
- Raster/gridded: foundations defined, conversion raises `NotImplementedError` — Req 25–37 N/A
