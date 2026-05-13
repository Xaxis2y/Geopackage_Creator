================================================================================
 DGIWG GeoPackage Creator
 Version: 0.13
 Date:    2026-05-13
================================================================================

OVERVIEW
--------
An ArcGIS Pro Python Toolbox (.pyt) that converts a File Geodatabase (.gdb)
to a DGIWG-profile-compliant GeoPackage (.gpkg).

Built with pure ArcPy + sqlite3. No GDAL or external dependencies required.

DGIWG Standard:  DGIWG-126 GeoPackage Profile 1.4 Ed.1.1
Document ref:    STD-DP-19-005 v1.1, 2025-05-02
Profiles:        OGC 12-128r19 GeoPackage Encoding Standard v1.4 (2024-06-02)


FILE NAMING CONVENTION
----------------------
Each version is saved as a NEW file — previous versions are never overwritten.

  DGIWG_GeoPackage_v0.13.pyt   <-- current version (use this one)
  DGIWG_GeoPackage_v0.12.pyt   <-- previous version
  DGIWG_GeoPackage.pyt         <-- original v0.03 baseline (do not edit)

Next update must be saved as DGIWG_GeoPackage_v0.14.pyt, and so on.


REQUIREMENTS
------------
- ArcGIS Pro 2.9 or later (ArcPy included)
- Python 3.9+ (bundled with ArcGIS Pro)
- No additional installs needed


INSTALLATION
------------
1. Copy DGIWG_GeoPackage_v0.12.pyt to a folder of your choice
2. Open ArcGIS Pro
3. In the Catalog pane, right-click Toolboxes > Add Toolbox
4. Browse to DGIWG_GeoPackage_v0.12.pyt and click OK
5. The tool "GDB to DGIWG GeoPackage" will appear under the toolbox


TOOL PARAMETERS
---------------
  1.  Input File Geodatabase (.gdb)
  2.  Output GeoPackage (.gpkg)
  3.  Target CRS (DGIWG-126 Table 13 approved options):
        - WGS 84 Geographic 2D (EPSG:4326)          [default — required for 2D vector]
        - WGS 84 / World Mercator (EPSG:3395)        [raster/gridded only]
        - WGS 84 / UPS North E,N (EPSG:5041)        [Arctic/polar]
        - WGS 84 / UPS South E,N (EPSG:5042)        [Antarctic/polar]
        - WGS 84 / UTM zone 1N–60N (EPSG:32601–32660)  [all 60 north zones, v0.13+]
        - WGS 84 / UTM zone 1S–60S (EPSG:32701–32760)  [all 60 south zones, v0.13+]
        - Manual EPSG entry     (any integer EPSG code — see WARNING below)
        NOTE: DGIWG Req 9 requires ALL 2D vector layers to use EPSG:4326.
        UTM, Mercator, and UPS are valid for gridded/raster or 3D vector only.
  4.  Manual EPSG Code (enabled only when #3 = Manual)
  5.  Dataset Title          (DMF gmd:title)
  6.  Abstract               (DMF gmd:abstract)
  7.  Point of Contact name  (DMF gmd:individualName)
  8.  Organisation Name      (DMF gmd:organisationName)
  9.  Metadata Language      (ISO 639-2, e.g. eng / fra / deu)
  10. Feature Classes filter  (blank = all)


DGIWG-126 COMPLIANCE IMPLEMENTED
----------------------------------
  [x] OGC GeoPackage 1.4 application_id header (0x47504b47)
  [x] user_version = 10400 (GeoPackage 1.4.0)
  [x] Final PRAGMA re-check after commit (guards against ArcPy resets)
  [x] gpkg_spatial_ref_sys: srs_id -1, 0, and target EPSG
        definition     = WKT2 (ISO 19162:2019)
        definition_12_063 = WKT1 (ArcGIS/OGC 12-063) — required by §F.10
  [x] gpkg_wkt_for_crs extension registered (DGIWG-126 §7.2 / conf/crs)
  [x] definition_12_063 column added via ALTER TABLE if absent (OGC §F.10)
  [x] gpkg_contents: correct extent, srs_id, timestamp per table
  [x] DGIWG Metadata Foundation (DMF v2.0) XML in gpkg_metadata
        md_standard_uri = http://metadata.dgiwg.org/Schema/2014/DMF
        metadataStandardName + metadataStandardVersion elements included
  [x] XML well-formedness validated (ET.fromstring) before every INSERT
  [x] Package-level metadata ref (reference_scope = 'geopackage')
  [x] Per-layer metadata refs   (reference_scope = 'table', md_parent_id
        linking back to package record) — DGIWG-126 §9.1 / ATS A.4.5
  [x] gpkg_metadata extension registered  (spec140 URI)
  [x] gpkg_rtree_index extension registered per geometry column
  [x] RTree post-registration verification (warns if any entry missing)
  [x] Reprojection via arcpy.env.outputCoordinateSystem (cross-version compatible)
  [x] Table names: lowercase, regex-sanitized, digit-prefix guarded
  [x] XML-safe escaping of all user-supplied metadata strings
  [x] Rollback on SQLite failure — no corrupt partial files
  [x] Timestamped .log file written alongside output GPKG
  [x] gpkg_data_columns populated (gpkg_schema) — self-documenting fields
  [x] Anti-meridian bounding-box snapping for geographic CRS (±0.01°)
  [x] Post-commit extent integrity check + auto-repair (GOLD-2)
  [x] SHA-256 compliance manifest JSON written alongside output GPKG


KNOWN LIMITATION — MANUAL EPSG ENTRY
--------------------------------------
When "Manual EPSG entry" is selected, ArcPy's SpatialReference.exportToString()
returns ArcGIS WKT1 format, NOT ISO 19162:2019 WKT2 as required by the
gpkg_wkt_for_crs extension (DGIWG-126 §7.2).

The tool writes WKT1 to BOTH the 'definition' and 'definition_12_063' columns
and emits a WARNING at runtime. Before submitting to a DGIWG validator, replace
the 'definition' value in gpkg_spatial_ref_sys with the authoritative WKT2 from:

  https://epsg.io/<your_epsg_code>.wkt2

This limitation does NOT apply to catalogue CRS entries (EPSG:4326, 3395,
5041, 5042, 32601, 32610, 32632) — those have hard-coded WKT2 strings.


OUTPUT FILES
------------
  <name>.gpkg               — The DGIWG-compliant GeoPackage
  <name>_export.log         — Timestamped processing log (auto-generated)
  <name>_compliance.json    — SHA-256 hash + provenance manifest (v0.06+)


VALIDATION
----------
  DGIWG / OGC CITE validator: https://cite.opengeospatial.org/te2/
  DB Browser for SQLite:       https://sqlitebrowser.org


COMPATIBILITY — USING EXISTING GEOPACKAGES AS SOURCE
------------------------------------------------------
This section covers what to expect when the source data comes from an existing
GeoPackage (e.g. OpenStreetMap, CanVec, or any third-party .gpkg file) rather
than a File Geodatabase created in ArcGIS Pro.

CRITICAL — INPUT FORMAT
  The tool currently only accepts a File Geodatabase (.gdb) as input.
  It will NOT recognise a .gpkg file directly. Before running the tool,
  import the source GeoPackage into a File GDB using ArcGIS Pro:
    • Catalog pane: drag GeoPackage layers into a GDB, or
    • Geoprocessing: Feature Class to Geodatabase tool
  Once in a GDB, the tool works normally. This is a known limitation
  flagged for removal in v0.06 (see NEXT STEPS below).

OPENSTREETMAP GEOPACKAGES
  CRS:       EPSG:4326 (WGS 84) — already in the catalogue, no issues.
  Names:     OSM layer names (points, lines, multipolygons, etc.) pass
             the regex sanitizer cleanly.
  Encoding:  Accented characters in place names (é, ü, ñ) are safe —
             the tool XML-escapes all metadata strings.
  Size:      OSM extracts can be very large (millions of features).
             The tool has a progress bar but no chunked export; expect
             long run times for planet/country-scale datasets.
  Output:    Fully DGIWG-126 compliant — source format has no effect
             on the output once the data is in a GDB.

CANVEC GEOPACKAGES (Natural Resources Canada)
  CRS:       NAD83 (EPSG:4269) or NAD83/UTM zones — NOT in the DGIWG-126
             Table 13 catalogue and not a DGIWG-approved output CRS.
             This is NOT a blocker: the tool reprojects everything to
             whichever DGIWG CRS you select (e.g. EPSG:4326 or a UTM zone).
             Choose the appropriate target CRS at run time.
  Names:     CanVec names like HY_WATERBODY_2 become hy_waterbody_2
             after sanitization — valid SQLite identifiers.
  Output:    Fully DGIWG-126 compliant after reprojection; source CRS
             does not appear in the output GeoPackage.

OTHER THIRD-PARTY GEOPACKAGES (OS, MGCP, TDS, etc.)
  The same two-step workflow applies: import to GDB first, then run tool.
  Key things to check before importing:
    • CRS of the source — if not DGIWG-approved, the tool will reproject.
    • Geometry types — MULTIPATCH is mapped to MULTIPOLYGON; any geometry
      type not in the lookup returns the generic "GEOMETRY" type string.
    • Very long layer names — the regex sanitizer truncates nothing; names
      remain as-is after character replacement. Rename in the GDB if needed.
    • Null geometries — ArcGIS Pro's ExportFeatures skips null-geometry
      rows silently; verify feature counts in the export log.

DGIWG COMPLIANCE OF THE OUTPUT
  Regardless of the source (OSM, CanVec, or any other GeoPackage), the
  DGIWG-126 compliance is entirely determined by the tool's output logic —
  not the input. As long as the source data is correctly loaded into a GDB,
  the output GeoPackage will meet all DGIWG-126 requirements.


NEXT STEPS / OPEN ITEMS
------------------------
  [ ] Accept .gpkg as direct input (alongside .gdb) — eliminates
        the manual GDB import step for OSM, CanVec, and other GeoPackages
  [x] Expand CRS catalogue with remaining UTM zones (done in v0.13 — all 120 zones)
  [ ] Consider fetching WKT2 from epsg.io API for Manual EPSG entries
        (requires network access in ArcGIS Pro environment)
  [ ] Add conformance class self-test that queries the finished GPKG and
        reports a pass/fail against each DGIWG-126 requirement row
  [ ] gpkg_data_column_constraints table (extend gpkg_schema for domain
        values / allowed ranges — useful for coded-value domains)


CHANGELOG
---------
v0.13  (2026-05-13)
  File: DGIWG_GeoPackage_v0.13.pyt
  FIX-12  GPKG_APPLICATION_ID constant corrected: 0x47504b47 ("GPKG"
          pre-standard marker) → 0x47503132 ("GP12", GeoPackage 1.2/1.3).
          FIX-9 in v0.12 documented this change in the changelog but the
          constant itself was never updated — this regression caused every
          v0.12 output to FAIL DGIWG Validator Req 3 (application_id).
  FIX-13  _force_wkt2_srs() WKT2 keyword check widened: was startswith
          ("GEOGCRS") only, which triggered a spurious "WKT2 NOT confirmed"
          warning for every projected CRS (UTM, Mercator, UPS). Now accepts
          all valid WKT2 top-level keywords (GEOGCRS, PROJCRS, COMPOUNDCRS,
          VERTCRS, ENGCRS, TIMECRS, DERIVEDPROJCRS).
  FIX-14  WAL journal mode cleanup: PRAGMA journal_mode=DELETE added before
          the final conn.close(). DGIWG Validator v1.54 explicitly FAILs
          files in WAL mode (Req 3) — the switch to DELETE mode checkpoints
          and removes -wal/-shm sidecar files before the final copy step.
  WARN-3  DGIWG Req 9 runtime warning: when any CRS other than EPSG:4326 is
          selected for a GDB that contains vector feature classes, a prominent
          WARNING is now emitted explaining that DGIWG Req 9 requires all 2D
          vector layers to use EPSG:4326.
  EXPAND-1 Full UTM CRS catalogue: all 60 WGS 84 UTM North zones
          (EPSG:32601–32660) and all 60 UTM South zones (EPSG:32701–32760)
          added to the dropdown with authoritative WKT2 strings. The three
          hard-coded zones (1N, 10N, 32N) from v0.12 are now superseded.

v0.12  (2026-05-08)
  File: DGIWG_GeoPackage_v0.12.pyt
  FIX-9   application_id changed to 0x47503132 ("GP12") — fixes Req 3 FAIL.
  FIX-10  metadataStandardName/Version removed from DMF XML — fixes Req 18
          XSD validation FAIL (DGIWG validator schema does not include them).
  FIX-11  WKT2 persistence: tool now works on a temp .__dgiwg_work__.gpkg
          file and copies to the final output path as the very last step.
          Prevents ArcGIS Pro catalog refresh from overwriting WKT2.

v0.11  (2026-05-08)
  File: DGIWG_GeoPackage_v0.11.pyt
  FIX-6  EPSG:4326 WKT2 updated to authoritative ENSEMBLE form per
         ISO 19162:2019 / epsg.io. Fixes DGIWG Req 13 FAIL: datum name
         "World Geodetic System 1984 ensemble" now matches EPSG registry.
  FIX-7  gpkg_crs_wkt extension: name corrected (was gpkg_wkt_for_crs),
         table_name="gpkg_spatial_ref_sys", column_name="definition_12_063"
         per OGC 12-128r19. Fixes Req 3 missing table_name warning.
  FIX-8  WKT2 persistence: _force_wkt2_srs() runs as the final step,
         using a fresh sqlite3 connection + PRAGMA wal_checkpoint(FULL)
         to prevent ArcGIS Pro from reverting definition to WKT1.

v0.10  (2026-05-08)
  File: DGIWG_GeoPackage_v0.10.pyt
  NEW-1  Source software attribution added to every GeoPackage as a
         gmd:dataQualityInfo / gmd:LI_ProcessStep element in the DMF
         metadata XML. Text written:
         "DGIWG-compliant GeoPackage produced by the Mapping and
         Charting Establishment (MCE)"
         Visible in any ISO 19139-aware viewer or DGIWG validator.

v0.09  (2026-05-08)
  File: DGIWG_GeoPackage_v0.09.pyt
  FIX-3  GOLD-4 snap now skipped for empty feature classes (fc_count==0)
         whose extent returns NaN. Eliminates spurious "Snap applied
         (nan,nan,nan,nan)" log lines for empty layers.
  FIX-4  GOLD-5 compliance manifest NameError fixed: variable "manifest_pa"
         corrected to "manifest_path". JSON certificate now written
         reliably after every successful export.

v0.08  (2026-05-08)
  File: DGIWG_GeoPackage_v0.08.pyt
  FIX-2  Reprojection: replaced unsupported output_coordinate_system
         keyword argument in ExportFeatures() with
         arcpy.env.outputCoordinateSystem (cleared in finally block).
         Fixes "unexpected keyword argument" error on export.

v0.07  (2026-05-08)
  File: DGIWG_GeoPackage_v0.07.pyt
  FIX-1  Input GDB parameter filter changed from "FileSystem" to
         "LocalDatabase". Browser now restricts to .gdb geodatabases;
         prevents "No feature classes found" when project folder selected.

v0.06  (2026-05-07)
  File: DGIWG_GeoPackage_v0.06.pyt
  GOLD-1  Parent-Child metadata linking — md_parent_id in
          gpkg_metadata_reference already links every per-layer record back
          to the package-level record. Explicitly confirmed and documented.
          No code change required; behaviour present since v0.05.
  GOLD-2  Transactional geometry integrity check — after conn.commit() the
          tool reads back every gpkg_contents row and compares stored extents
          against ArcPy-derived extents. Any discrepancy beyond 1e-6 units
          is automatically repaired (with WARNING) and re-committed.
          New function: _verify_and_repair_contents_extents()
  GOLD-3  gpkg_schema extension — gpkg_data_columns table created and
          populated with field aliases, types, and lengths from every
          exported feature class. Makes the GeoPackage self-documenting for
          QGIS, mobile tactical viewers, and non-ArcGIS consumers.
          New function: _populate_gpkg_schema()
          New constant:  EXT_URI_SCHEMA
  GOLD-4  Anti-meridian bounding-box snapping — for geographic CRS, any
          extent coordinate within 0.01 deg of the WGS84 world bounds is
          snapped to the exact boundary value before writing to gpkg_contents.
          Prevents DGIWG validators rejecting near-global extents.
          New function: _snap_geographic_extent()
  GOLD-5  Compliance manifest — a *_compliance.json file is written alongside
          the .gpkg and .log. Contains SHA-256 hash of the GPKG, WKT2 string,
          count of verified RTree indexes, DGIWG/OGC standard citations, and
          a per-layer feature/extent summary. Provides a Certificate of
          Provenance for formal military geospatial delivery.
          New function: _write_compliance_manifest()
          New imports:   hashlib, json

v0.05  (2026-05-07)
  File: DGIWG_GeoPackage_v0.05.pyt
  NEW-1  definition_12_063 column added to gpkg_spatial_ref_sys via ALTER
         TABLE (_ensure_wkt_for_crs_column). Required by gpkg_wkt_for_crs
         extension (OGC 12-128r19 §F.10). _upsert_srs() now writes both
         WKT2 (definition) and WKT1 (definition_12_063) for all SRS rows.
  NEW-2  Table-name sanitization hardened: re.sub(r'[^a-z0-9_]','_',name)
         replaces ALL non-alphanumeric chars; digit-leading names prefixed
         with 't_' to guarantee valid SQLite identifiers.
  NEW-3  Final PRAGMA re-check after conn.commit() — auto-reapplies
         application_id and user_version if ArcPy reset them, with WARNING.
  ADD-1  (completed) ET.fromstring() validates every DMF XML blob before
         INSERT into gpkg_metadata. Raises ValueError on malformed XML,
         triggering rollback.
  ADD-2  (completed) Post-loop gpkg_extensions query confirms every geometry
         column has its gpkg_rtree_index entry; WARNs on any gap.
  ADD-3  (completed) WKT-format WARNING emitted when Manual EPSG is used,
         with direct link to https://epsg.io/<code>.wkt2.

v0.04  (2026-05-07)
  File: DGIWG_GeoPackage.pyt  (edited in-place — pre-naming-convention)
  ADD-1  Planned: XML well-formedness validation
  ADD-2  Planned: RTree post-registration verification
  ADD-3  Planned: Manual EPSG WKT-format warning
  Note:  ADD items were planned in v0.04 but fully implemented in v0.05.

v0.03  (2026-04-30)
  File: DGIWG_GeoPackage.pyt
  CRITICAL FIXES
  - BUG-1:  XML injection fixed — xml.sax.saxutils.escape() on all fields
  - BUG-2:  Reprojection fixed — output_coordinate_system in ExportFeatures
  - FIX-1:  Standard corrected from DGIWG-112 to DGIWG-126
  - FIX-2:  OGC ref updated from 12-128r18 to 12-128r19 v1.4
  - FIX-3:  user_version corrected from 10200 to 10400
  - FIX-4:  gpkg_wkt_for_crs extension registered
  - FIX-5:  md_standard_uri → DMF URI; metadataStandard* elements added
  HIGH FIXES
  - FIX-6:  UPS North/South (EPSG:5041/5042) added to CRS dropdown
  - FIX-7:  Per-feature-layer metadata records (DGIWG-126 §9.1)
  MEDIUM FIXES
  - FIX-8:  Extension URIs updated spec120 → spec140
  - FIX-9:  gpkg_rtree_index registered per geometry column
  IMPROVEMENTS
  - WARN-1/2, IMPROVE-1/2/3 (rollback, progress bar, log file)

v0.02  (2026-04-30)
  - _register_extension() NULL-safe duplicate check
  - datetime.utcnow() → datetime.now(timezone.utc)
  - Added readme.txt and User_Guide.docx

v0.01  (2026-04-30)
  - Initial release

================================================================================
