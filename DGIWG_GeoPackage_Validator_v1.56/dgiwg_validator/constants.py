"""Lookup tables and constants for the DGIWG validator (v1.56).

Pure data: no I/O, no network calls, no cross-module imports.
"""
import os
import math as _math
NET_TIMEOUT: int = 8
REQUIREMENTS = {
    # v1.49: Req 1 and Req 2 added as SKIPPED placeholders so the report table
    # starts at Req 1.  Both require OGC CITE TeamEngine and cannot be automated.
    1:  ("OGC Base Application",              "/req/base/application",                  "M"),
    2:  ("OGC Base GeoPackage",               "/req/base/geopackage",                   "M"),
    3:  ("Mandatory Extensions",              "/req/extensions/mandatory",              "M"),
    4:  ("Optional Extensions",               "/req/extensions/optional",               "C"),
    5:  ("Extensions Not Allowed",            "/req/extensions/not-allowed",            "M"),
    6:  ("Conditional Extensions",            "/req/extensions/conditional",            "C"),
    7:  ("Raster CRS Allowed",                "/req/crs/raster-allowed",                "M"),
    8:  ("CRS Raster Tile Matrix Set",        "/req/crs/raster-tile-matrix-set",        "M"),
    9:  ("2D Vector CRS",                     "/req/crs/2d-vector",                     "M"),
    10: ("3D Vector CRS",                     "/req/crs/3d-vector",                     "M"),
    11: ("Gridded 2D CRS",                    "/req/crs/gridded-crs-2d-allowed",        "M"),
    12: ("Gridded 3D CRS",                    "/req/crs/gridded-crs-3d-allowed",        "M"),
    13: ("WKT for CRS",                       "/req/crs/wkt",                           "M"),
    14: ("Compound CRS Usage",                "/req/crs/compound",                      "C"),
    15: ("Compound CRS WKT",                  "/req/crs/compound-wkt",                  "M"),
    16: ("Gridded Compound CRS WKT",          "/req/crs/gridded-crs-compound-wkt",      "C"),
    17: ("Gridded CRS Epoch WKT",             "/req/crs/gridded-crs-epoch-wkt",         "C"),
    18: ("GeoPackage Metadata DMF",           "/req/metadata/dmf",                      "M"),
    19: ("GeoPackage Metadata Document",      "/req/metadata/gpkg",                     "M"),
    20: ("Complete Row Metadata",             "/req/metadata/row",                      "M"),
    21: ("User Row Metadata",                 "/req/metadata/user",                     "C"),
    22: ("Product Metadata",                  "/req/metadata/product",                  "C"),
    23: ("Product Partial Metadata",          "/req/metadata/product-partial",          "C"),
    24: ("Data Validity",                     "/req/validity/data-validity",            "M"),
    25: ("Tile Matrix Width/Height",          "/req/tile/size-matrix",                  "M"),
    26: ("Tile Pyramid Data Size",            "/req/tile/size-data",                    "M"),
    27: ("Zoom Level Factor",                 "/req/zoom/factor",                       "M"),
    28: ("Multiple Zoom Matrix Sets",         "/req/zoom/matrix-sets-multiple",         "C"),
    29: ("Single Zoom Matrix Set",            "/req/zoom/matrix-sets-one",              "C"),
    30: ("Tile Matrix Set CRS BBox",          "/req/bbox/crs",                          "M"),
    31: ("Tile Layer Metadata",               "/req/metadata/tile",                     "C"),
    32: ("Feature Layer Metadata",            "/req/metadata/feature",                  "C"),
    33: ("Gridded Extension Core",            "/req/gridded/gridded-coverage-extension-core", "C"),
    34: ("Gridded Field Name Elevation",      "/req/gridded/field-name-elevation",      "C"),
    35: ("Gridded Center Value Elevation",    "/req/gridded/center-value-elevation",    "C"),
    36: ("Gridded Zoom Factor",               "/req/gridded/zoom-factor",               "C"),
    37: ("Gridded User Row Metadata",         "/req/gridded/metadata-gridded-user",     "C"),
}

# Extension table (per DGIWG Table 8): features / tiles / gridded
# M=Mandatory, O=Optional, N=Not Allowed, NA=Not Applicable, C=Conditional
EXTENSIONS_TABLE = {
    "gpkg_rtree_index":        {"features": "M",  "tiles": "NA", "gridded": "NA"},
    "gpkg_metadata":           {"features": "M",  "tiles": "M",  "gridded": "M"},
    "gpkg_crs_wkt":            {"features": "M",  "tiles": "M",  "gridded": "N"},
    "gpkg_crs_wkt_1_1":        {"features": "O",  "tiles": "O",  "gridded": "M"},
    "gpkg_schema":             {"features": "O",  "tiles": "O",  "gridded": "O"},
    "related_tables":          {"features": "O",  "tiles": "O",  "gridded": "O"},
    "gpkg_2d_gridded_coverage":{"features": "NA", "tiles": "NA", "gridded": "M"},
    "gpkg_geom_":              {"features": "N",  "tiles": "NA", "gridded": "NA"},
    "gpkg_zoom_other":         {"features": "NA", "tiles": "N",  "gridded": "NA"},
    "gpkg_webp":               {"features": "NA", "tiles": "N",  "gridded": "NA"},
}

# DGIWG Tables 11 & 12 — allowed CRS for raster tile pyramid (tiles data_type only).
# Per Req 7, UTM zones (EPSG 32601–32660 / 32701–32760, Table 11) ARE permitted for
# raster tile pyramids, as are 3395/3857/5041/5042 (Table 11) and 4326/4979 (Table 12).
# Lambert Conformal Conic (1SP/2SP) is also allowed "per product" (Table 11) but has
# no fixed EPSG code — it is detected from the WKT projection method in _r7() rather
# than by code membership.
ALLOWED_RASTER_CRS = {3395, 3857, 4326, 4979, 5041, 5042} | \
                       set(range(32601, 32661)) | set(range(32701, 32761))

# Human-readable description of the allowed raster CRS set, used in report messages so
# the 120 UTM codes are not dumped verbatim into the output.
ALLOWED_RASTER_CRS_DISPLAY = (
    "3395, 3857, 4326, 4979, 5041, 5042, UTM zones 32601-32660 / 32701-32760, "
    "and Lambert Conformal Conic (per-product code)"
)

ALLOWED_GRIDDED_2D_CRS = {3395, 3857, 4326, 5041, 5042} | \
                           set(range(32601, 32661)) | set(range(32701, 32761))

ALLOWED_GRIDDED_3D_CRS = {4979} | set(range(100100, 100400))

# DGIWG Table 10 — allowed CRS for vector feature layers
ALLOWED_VECTOR_CRS_2D = {4326}
ALLOWED_VECTOR_CRS_3D = {4979, 9518}
# OGC standard TileMatrixSet pixel sizes at zoom level 0 (OGC 17-083r4)
# pixel_size_at_zoom_N = pixel_z0 / 2^N
import math as _math
_WGS84_A = 6378137.0
OGC_PIXEL_Z0 = {
    3857: 2 * _math.pi * _WGS84_A / 256,   # WebMercatorQuad (metres)
    3395: 2 * _math.pi * _WGS84_A / 256,   # WorldMercatorWGS84Quad (metres)
    4326: 360.0 / 512,                      # WorldCRS84Quad (degrees, 2 tiles wide)
    4979: 360.0 / 512,                      # WorldCRS84Quad 3D (degrees)
    5041: 28881518.7 / 256,                 # UPSNorthWGS84Quad (metres)
    5042: 28881518.7 / 256,                 # UPSSouthWGS84Quad (metres)
}
OGC_PIXEL_TOL = 1e-4   # relative tolerance for pixel size comparison

# ──────────────────────────────────────────────────────────────────────────────
# CRS GEOGRAPHIC EXTENT TABLE  (v1.27)
# Valid area for each DGIWG-approved CRS, in CRS native units.
# Used by Req 11/12 (gridded CRS extent) and Req 30 (bbox cross-check).
# Sources: OGC 17-083r4 Annex D, EPSG geodetic parameter registry.
# Bounds: (min_x, min_y, max_x, max_y)
# ──────────────────────────────────────────────────────────────────────────────
CRS_EXTENT = {
    # Global / near-global projected CRS (metres)
    3857: (-20037508.3428, -20037508.3428,  20037508.3428,  20037508.3428),
    3395: (-20037508.3428, -15496570.7397,  20037508.3428,  18764656.2314),
    # Geographic CRS (degrees)
    4326: (-180.0, -90.0,  180.0,  90.0),
    4979: (-180.0, -90.0,  180.0,  90.0),
    # UPS Polar (metres) — valid inside respective polar circles
    5041: (-14440759.35, -14440759.35,  14440759.35,  14440759.35),
    5042: (-14440759.35, -14440759.35,  14440759.35,  14440759.35),
}
# UTM WGS84 North zones 1–60  (EPSG 32601–32660)
# Valid easting: 100 000–900 000 m; northing: 0–9 329 005 m (equator to ~84°N)
for _z in range(1, 61):
    CRS_EXTENT[32600 + _z] = (100000.0, 0.0,       900000.0, 9329005.0)
# UTM WGS84 South zones 1–60  (EPSG 32701–32760)
# Valid easting: 100 000–900 000 m; northing: 1 116 915–10 000 000 m (false northing)
for _z in range(1, 61):
    CRS_EXTENT[32700 + _z] = (100000.0, 1116915.0, 900000.0, 10000000.0)

# ──────────────────────────────────────────────────────────────────────────────
# DGIWG TABLE 36 — allowed (reference_scope, md_scope) combinations
# reference_scope → frozenset of allowed md_scope values
# Source: DGIWG STD-DP-19-005 v1.1 Table 36
# ──────────────────────────────────────────────────────────────────────────────
TABLE_36_ALLOWED = {
    "geopackage": frozenset({"undefined", "dataset", "series", "featureType",
                              "model", "tile", "attribute", "attributeType",
                              "collectionHardware", "collectionSession", "nonGeographicDataset",
                              "fieldSession", "software", "service", "dimensionGroup"}),
    "table":      frozenset({"dataset", "featureType", "feature", "tile", "model",
                              "series", "software", "service"}),
    "column":     frozenset({"featureType", "attribute", "attributeType"}),
    "row/col":    frozenset({"feature"}),
    "row":        frozenset({"feature", "tile", "model"}),
}

# ISO 19115 mandatory elements required in DGIWG DMF metadata
DMF_ISO_MANDATORY = [
    "fileIdentifier", "language", "characterSet",
    "hierarchyLevel", "contact", "dateStamp", "identificationInfo",
]


STATUS_ICON = {
    "PASS":    "✅",
    "FAIL":    "❌",
    "PASS*":   "⚠️",
    "SKIPPED": "⬜",
    "N/A":     "➖",
    "WARNING": "⚠️",
}

# DGIWG-required tile pixel dimensions (DGIWG STD-DP-19-005 v1.1 Req 8, 25, 26, 29)
# All tile tables must declare and store exactly this pixel size per tile.
TILE_SIZE: tuple[int, int] = (256, 256)
TILE_W, TILE_H = TILE_SIZE


# ──────────────────────────────────────────────────────────────────────────────
# DATABASE HELPERS
# ──────────────────────────────────────────────────────────────────────────────

STATUS_HTML_COLOR = {
    "PASS":    "#27ae60",
    "FAIL":    "#e74c3c",
    "PASS*":   "#f39c12",
    "SKIPPED": "#7f8c8d",
    "N/A":     "#95a5a6",
    "WARNING": "#e67e22",
}

STATUS_HTML_BG = {
    "PASS":    "#eafaf1",
    "FAIL":    "#fdedec",
    "PASS*":   "#fef9e7",
    "SKIPPED": "#f4f4f4",
    "N/A":     "#f8f9fa",
    "WARNING": "#fdebd0",
}

# Manual confirmation guidance per requirement
# (what_to_check, how_to_check_in_db_browser, sql_query)
MANUAL_GUIDANCE = {
    3: ("Confirm each mandatory extension row has a table_name pointing to a real table.",
        "DB Browser → Browse Data → gpkg_extensions. Check that gpkg_metadata and gpkg_crs_wkt rows have a non-empty table_name column.",
        "SELECT extension_name, table_name, scope FROM gpkg_extensions ORDER BY extension_name;"),
    4: ("Verify optional extensions are applied to the right tables.",
        "DB Browser → Browse Data → gpkg_extensions. Each optional extension should reference a real table_name.",
        "SELECT extension_name, table_name FROM gpkg_extensions WHERE extension_name IN ('gpkg_schema','related_tables');"),
    5: ("Confirm no disallowed extensions remain. Remove 'gdal_nw' before delivery if present.",
        "DB Browser → Execute SQL → run the query below. If 'gdal_nw' appears, run: DELETE FROM gpkg_extensions WHERE extension_name='gdal_nw'; to remove it before delivery. This script never modifies the file.",
        "SELECT extension_name FROM gpkg_extensions;"),
    6: (
        "⚠️ This requirement CANNOT be automated. It is always SKIPPED because the script has no access to your product profile. "
        "Req 6 asks whether conditional extensions (gpkg_schema, related_tables, gpkg_crs_wkt_1_1) are correctly used or omitted according to the DGIWG product profile that governs this dataset. "
        "To check manually: (1) Obtain the DGIWG product profile document that applies to this dataset (e.g. from your NSO or project authority). "
        "(2) Find the extensions table in that profile. "
        "(3) Compare what it requires against what is registered in gpkg_extensions. "
        "A conditional extension is a violation only if the profile explicitly prohibits it or requires it and it is absent.",
        "DB Browser → Browse Data → gpkg_extensions. List all registered extensions, then cross-reference against your product profile document.",
        "SELECT extension_name, table_name, scope FROM gpkg_extensions;"),
    7: ("Verify each CRS code is on the DGIWG Tables 11 & 12 approved list for raster tile "
        "pyramids: 3395, 3857, 4326, 4979, 5041, 5042, any UTM zone (32601-32660 / 32701-32760), "
        "or a per-product Lambert Conformal Conic CRS (1SP/2SP).",
        "DB Browser → Browse Data → gpkg_tile_matrix_set. Check the srs_id column for each row.",
        "SELECT table_name, srs_id FROM gpkg_tile_matrix_set;"),
    8: ("Verify the CRS is registered with correct scale denominators matching OGC TileMatrixSet.",
        "DB Browser → Browse Data → gpkg_spatial_ref_sys. Each srs_id used in gpkg_tile_matrix_set must have a non-empty definition.",
        "SELECT tms.table_name, tms.srs_id, srs.srs_name FROM gpkg_tile_matrix_set tms LEFT JOIN gpkg_spatial_ref_sys srs ON tms.srs_id=srs.srs_id;"),
    9: ("All 2D vector layers must use EPSG:4326 (WGS84 geographic coordinates).",
        "DB Browser → Browse Data → gpkg_geometry_columns. The srs_id column must be 4326 for all rows where z=0.",
        "SELECT table_name, srs_id, z FROM gpkg_geometry_columns WHERE z=0;"),
    10: ("All 3D vector layers must use EPSG:4979, 9518, or a UTM zone (32601–32660, 32701–32760).",
         "DB Browser → Browse Data → gpkg_geometry_columns. Check srs_id for rows where z != 0.",
         "SELECT table_name, srs_id, z FROM gpkg_geometry_columns WHERE z!=0;"),
    11: ("All 2D gridded coverage layers must use a CRS from DGIWG Tables 9 or 11.",
         "DB Browser → Execute SQL → run the query below. Check srs_id is in the approved list.",
         "SELECT tms.table_name, tms.srs_id FROM gpkg_tile_matrix_set tms JOIN gpkg_contents c ON tms.table_name=c.table_name WHERE c.data_type LIKE '%gridded%';"),
    12: ("All 3D gridded coverage layers must use EPSG:4979 or a compound CRS.",
         "DB Browser → Browse Data → gpkg_spatial_ref_sys. Look for COMPOUNDCRS in the definition column for gridded coverage srs_ids.",
         "SELECT srs_id, srs_name, definition FROM gpkg_spatial_ref_sys;"),
    13: (
        "WKT structural parsing and datum name cross-check are now automated (v1.47+). "
        "Automated checks: WKT2 keywords vs WKT1, axis names, prime meridian, angular units, datum name via pyproj. "
        "Residual manual steps (edge cases not covered by pyproj): "
        "(1) Axis order for projected CRS (Easting/Northing per EPSG). "
        "(2) Confirm no AUTHORITY[\"ESRI\",...] identifiers replace EPSG codes in ArcGIS files. "
        "(3) If pyproj unavailable, offline JSON cache covers 128 DGIWG CRS codes; "
        "manual datum cross-check recommended for custom or extended CRS codes.",
        "DB Browser → Browse Data → gpkg_spatial_ref_sys. Click the definition cell for each srs_id > 0 to read the full WKT string. Check for WKT2 keywords and correct axis ordering.",
        "SELECT srs_id, srs_name, definition, definition_12_063 FROM gpkg_spatial_ref_sys WHERE srs_id > 0;"),
    14: ("Confirm that compound CRS (COMPOUNDCRS) is only used on 3D data (z!=0).",
         "DB Browser → Execute SQL → run the query. Any row with z=0 and COMPOUNDCRS in its definition is a violation.",
         "SELECT gc.table_name, gc.z, srs.definition FROM gpkg_geometry_columns gc LEFT JOIN gpkg_spatial_ref_sys srs ON gc.srs_id=srs.srs_id;"),
    15: (
        "⚠️ Compound CRS keyword detection is automated, but FULL WKT2 structure is not validated — this is a known gap. "
        "DGIWG Tables 29–30 define the exact required structure. Manually verify: "
        "(1) The WKT must open with COMPOUNDCRS[\"<name>\", ... ] at the top level. "
        "(2) It must contain a horizontal component: either GEOGCRS[...] (geographic) or PROJCRS[...] (projected). "
        "(3) It must contain a vertical component: VERTCRS[...] with a named vertical datum. "
        "(4) Axis order in the horizontal component must match the EPSG definition (latitude first for geographic CRS). "
        "(5) The vertical datum name must correspond to a recognised ellipsoidal or orthometric height system.",
        "DB Browser → Browse Data → gpkg_spatial_ref_sys. For rows where definition contains COMPOUNDCRS, click the cell and verify both GEOGCRS/PROJCRS and VERTCRS sub-components are present and correctly formed.",
        "SELECT srs_id, srs_name, definition FROM gpkg_spatial_ref_sys WHERE definition LIKE '%COMPOUNDCRS%' OR definition LIKE '%COMPD_CS%';"),
    16: (
        "⚠️ Compound CRS detection for gridded data is automated, but WKT2 internal structure is not validated — this is a known gap. "
        "The definition_12_063 column (ISO WKT2) must be used for gridded 3D data per DGIWG. Manually verify: "
        "(1) The definition_12_063 column exists and is populated (not empty or 'undefined'). "
        "(2) Its content starts with COMPOUNDCRS[ at the top level. "
        "(3) A horizontal CRS sub-component (GEOGCRS or PROJCRS) is present. "
        "(4) A vertical CRS sub-component (VERTCRS) is present with a named vertical datum. "
        "If definition_12_063 is absent, the file predates GeoPackage 1.2 — the definition column is used as fallback but may contain WKT1 syntax which DGIWG does not accept for gridded 3D data.",
        "DB Browser → Browse Data → gpkg_spatial_ref_sys. Check the definition_12_063 column (if present) for COMPOUNDCRS entries used by gridded layers.",
        "SELECT srs_id, srs_name, definition, definition_12_063 FROM gpkg_spatial_ref_sys;"),
    17: (
        "⚠️ Epoch column detection is automated, but DYNAMIC/FRAMEEPOCH WKT content is not validated — this is a known gap. "
        "DGIWG requires that when an epoch value is set, the WKT definition must include the DYNAMIC keyword with FRAMEEPOCH inside it. "
        "Manually verify: "
        "(1) Run the SQL query to find rows with a non-NULL epoch value. "
        "(2) For each such row, open the definition (or definition_12_063) and confirm it contains DYNAMIC[FRAMEEPOCH[<value>]] where <value> matches the epoch number in the epoch column. "
        "(3) The FRAMEEPOCH value should be a decimal year (e.g. 2005.0 for ITRF2005). "
        "If the epoch column has a value but the WKT contains no DYNAMIC keyword, the CRS definition is incomplete and does not satisfy Req 17.",
        "DB Browser → Browse Data → gpkg_spatial_ref_sys. Filter for rows where the epoch column is not empty. Click the definition cell to inspect the full WKT for DYNAMIC[FRAMEEPOCH[...]].",
        "SELECT srs_id, epoch, definition, definition_12_063 FROM gpkg_spatial_ref_sys WHERE epoch IS NOT NULL;"),
    18: (
        "⚠️ Table presence and ISO 19115 element names are automated, but DMF FIELD VALUES and XML vocabulary are not — this is a known gap. "
        "The automated check confirms: (a) gpkg_metadata table exists, (b) at least one row is present, (c) the 7 required ISO 19115 element names appear somewhere in the XML. "
        "It does NOT check: (1) Whether the URI is exactly http://www.dgiwg.org/std/dmf (a DGIWG DMF record) or a permissible alternative. "
        "(2) Whether the fileIdentifier element contains a valid UUID or persistent identifier. "
        "(3) Whether the language element uses a valid ISO 639-2 three-letter code (e.g. 'eng'). "
        "(4) Whether the characterSet element uses a valid MD_CharacterSetCode codelist value (e.g. 'utf8'). "
        "(5) Whether the hierarchyLevel element uses a valid MD_ScopeCode value (e.g. 'dataset' or 'series'). "
        "(6) Whether the contact element has a populated organisationName and role. "
        "(7) Whether the dateStamp element is a valid ISO 8601 date. "
        "To check: click the metadata column in DB Browser to read the full XML and inspect each field value.",
        "DB Browser → Browse Data → gpkg_metadata. Click the metadata column for each row to read the full XML. Check md_standard_uri starts with http://www.dgiwg.org, and verify field values as described above.",
        "SELECT id, md_scope, md_standard_uri, mime_type, length(metadata) AS xml_length FROM gpkg_metadata;"),
    19: ("Verify gpkg_metadata_reference has rows correctly linking metadata to the file.",
         "DB Browser → Browse Data → gpkg_metadata_reference. There must be at least one row with reference_scope='geopackage' and NULL in table_name, column_name, and row_id_value.",
         "SELECT reference_scope, table_name, column_name, row_id_value, md_file_id FROM gpkg_metadata_reference;"),
    20: ("Confirm all required columns exist in gpkg_metadata and at least one geopackage-scope reference exists.",
         "DB Browser → Browse Data → gpkg_metadata. Expected columns: id, md_scope, md_standard_uri, mime_type, metadata.",
         "SELECT id, md_scope, md_standard_uri, mime_type FROM gpkg_metadata;"),
    21: ("Confirm all required columns exist in gpkg_metadata_reference.",
         "DB Browser → Browse Data → gpkg_metadata_reference. Expected columns: reference_scope, table_name, column_name, row_id_value, timestamp, md_file_id.",
         "PRAGMA table_info(gpkg_metadata_reference);"),
    22: ("Confirm at least one metadata record has md_scope set to 'series' (preferred) or 'dataset'.",
         "DB Browser → Browse Data → gpkg_metadata. Look in the md_scope column for the value 'series' or 'dataset'.",
         "SELECT id, md_scope, md_standard_uri FROM gpkg_metadata WHERE md_scope IN ('series','dataset');"),
    23: ("Confirm a metadata reference row exists with scope='geopackage' and NULL in table_name, column_name, and row_id_value.",
         "DB Browser → Browse Data → gpkg_metadata_reference. Find a row where reference_scope is 'geopackage' and the next three columns are empty (NULL).",
         "SELECT * FROM gpkg_metadata_reference WHERE reference_scope='geopackage' AND table_name IS NULL AND column_name IS NULL AND row_id_value IS NULL;"),
    24: ("Verify all tables in gpkg_contents physically exist, and that all cross-references are consistent.",
         "DB Browser → Execute SQL → run the query. No rows returned = tables exist as expected.",
         "SELECT c.table_name FROM gpkg_contents c WHERE NOT EXISTS (SELECT 1 FROM sqlite_master WHERE name=c.table_name);"),
    25: ("Confirm gpkg_tile_matrix has tile_width=256 and tile_height=256 for every zoom level.",
         "DB Browser → Browse Data → gpkg_tile_matrix. The tile_width and tile_height columns must be 256 for all rows.",
         "SELECT table_name, zoom_level, tile_width, tile_height FROM gpkg_tile_matrix WHERE tile_width!=256 OR tile_height!=256;"),
    26: (
        "⚠️ Tile BLOB pixel dimensions CANNOT be verified by reading SQLite metadata alone — this is a known gap. "
        "gpkg_tile_matrix declares tile_width/height=256 but the actual stored image BLOBs may differ. "
        "To verify: "
        "(1) First run the SQL query below to find your tile table name (replace <tile_table> with the table_name from gpkg_contents where data_type='tiles'). "
        "(2) In QGIS: open the file as a raster layer, zoom in to a tile boundary, and check the tile dimensions in the layer properties. "
        "(3) In DB Browser: SELECT zoom_level, tile_row, tile_column, length(tile_data) AS blob_bytes FROM <tile_table> LIMIT 10; — a PNG 256x256 tile is typically 5–50 KB; a TIFF 256x256 tile is ~200 KB. Unexpectedly large or small sizes indicate a dimension problem. "
        "(4) Programmatically (Python): use the Pillow library to decode a BLOB — from PIL import Image; import io; img = Image.open(io.BytesIO(blob_bytes)); print(img.size) — must be (256, 256).",
        "DB Browser → Execute SQL. First find your tile table name, then sample tile BLOBs.",
        "SELECT table_name FROM gpkg_contents WHERE data_type='tiles'; -- then: SELECT zoom_level, tile_row, tile_column, length(tile_data) AS blob_bytes FROM <tile_table> LIMIT 10;"),
    27: ("Confirm zoom levels are correctly numbered and each level has tile data.",
         "DB Browser → Browse Data → gpkg_tile_matrix. Check zoom_level values are sequential per table_name.",
         "SELECT table_name, zoom_level, matrix_width, matrix_height FROM gpkg_tile_matrix ORDER BY table_name, zoom_level;"),
    28: ("For multi-zoom tiles, confirm pixel size exactly halves at each step (factor of 2.0).",
         "DB Browser → Execute SQL → run the query. Check that pixel_x_size / (next zoom pixel_x_size) = 2.0.",
         "SELECT table_name, zoom_level, pixel_x_size, pixel_y_size FROM gpkg_tile_matrix ORDER BY table_name, zoom_level;"),
    29: ("For single-zoom tiles, confirm tile_width and tile_height are 256.",
         "DB Browser → Browse Data → gpkg_tile_matrix. Check tile_width and tile_height for single-zoom tables.",
         "SELECT table_name, tile_width, tile_height FROM gpkg_tile_matrix;"),
    30: ("Confirm the bounding box values are geographically valid for the stated CRS.",
         "DB Browser → Browse Data → gpkg_tile_matrix_set. For EPSG:4326, min_x and max_x must be between -180 and 180. min_y and max_y between -90 and 90.",
         "SELECT table_name, srs_id, min_x, min_y, max_x, max_y FROM gpkg_tile_matrix_set;"),
    31: ("Confirm each tile layer has a linked metadata record with md_scope='tile' or 'model'.",
         "DB Browser → Execute SQL → run the query. Each tile table name should appear in the results.",
         "SELECT r.table_name, m.md_scope FROM gpkg_metadata_reference r JOIN gpkg_metadata m ON r.md_file_id=m.id WHERE m.md_scope IN ('tile','model');"),
    32: ("Confirm each feature layer has a linked metadata record with md_scope='feature' or 'featureType'.",
         "DB Browser → Execute SQL → run the query. Each feature table name should appear in the results.",
         "SELECT r.table_name, m.md_scope FROM gpkg_metadata_reference r JOIN gpkg_metadata m ON r.md_file_id=m.id WHERE m.md_scope IN ('feature','featureType');"),
    33: ("Confirm the gpkg_2d_gridded_coverage extension is registered and both ancillary tables have correct columns.",
         "DB Browser → Browse Data → gpkg_2d_gridded_coverage_ancillary. All rows must have tile_matrix_set_name, field_name, quantity_definition, and grid_cell_encoding filled in.",
         "SELECT * FROM gpkg_2d_gridded_coverage_ancillary;"),
    34: ("Confirm field_name is 'Height' or 'Elevation' (case-sensitive) for gridded elevation/height layers.",
         "DB Browser → Browse Data → gpkg_2d_gridded_coverage_ancillary. For any row where quantity_definition contains 'elevation' or 'height', the field_name column must be exactly 'Height' or 'Elevation'. Any other value (e.g. 'elev', 'alt', 'hgt') is a FAIL.",
         "SELECT tile_matrix_set_name, field_name, quantity_definition FROM gpkg_2d_gridded_coverage_ancillary;"),
    35: ("Confirm grid_cell_encoding is exactly 'grid-value-is-center' for gridded elevation/height layers.",
         "DB Browser → Browse Data → gpkg_2d_gridded_coverage_ancillary. For any row where quantity_definition contains 'elevation' or 'height', the grid_cell_encoding column must be exactly 'grid-value-is-center'. Values like 'area', 'corner', or empty are a FAIL.",
         "SELECT tile_matrix_set_name, grid_cell_encoding, quantity_definition FROM gpkg_2d_gridded_coverage_ancillary;"),
    36: ("Confirm the pixel size halves exactly (factor of 2.0) at every zoom level transition for gridded elevation layers.",
         "DB Browser → Execute SQL → run the query. For each consecutive pair of zoom levels, (pixel_x_size at zoom N) / (pixel_x_size at zoom N+1) must equal exactly 2.0 (within 1% tolerance). Any other ratio is a FAIL.",
         "SELECT table_name, zoom_level, pixel_x_size, pixel_y_size FROM gpkg_tile_matrix WHERE table_name IN (SELECT tile_matrix_set_name FROM gpkg_2d_gridded_coverage_ancillary) ORDER BY table_name, zoom_level;"),
    37: ("Confirm partial metadata reference rows have valid md_scope values per DGIWG Table 36.",
         "DB Browser → Execute SQL → run the query. Each partial reference should resolve to a valid metadata record.",
         "SELECT r.reference_scope, m.md_scope FROM gpkg_metadata_reference r JOIN gpkg_metadata m ON r.md_file_id=m.id WHERE r.reference_scope IN ('table','row','column','row/col');"),
}


REQ_ROLLUP_META = {
    # v1.49: Req 1 and 2 added as permanent SKIPPED entries
    1: {
        "name": "OGC Base Application",
        "auditor_checks": ["Cannot be checked automatically — requires OGC CITE TeamEngine external test harness."],
        "manual_notes": "Not evaluated. Use OGC CITE TeamEngine with the GeoPackage test suite to verify Req 1 compliance.",
        "confidence": "Low",
        "confidence_reason": "Always SKIPPED — requires OGC CITE TeamEngine test harness not available in this validator.",
    },
    2: {
        "name": "OGC Base GeoPackage",
        "auditor_checks": ["Cannot be checked automatically — requires OGC CITE TeamEngine external test harness."],
        "manual_notes": "Not evaluated. Use OGC CITE TeamEngine with the GeoPackage test suite to verify Req 2 compliance.",
        "confidence": "Low",
        "confidence_reason": "Always SKIPPED — requires OGC CITE TeamEngine test harness not available in this validator.",
    },
    3: {
        "name": "Mandatory Extensions",
        "auditor_checks": [
            "Checks that every extension required for this file's data type is registered in the extensions table",
            "Verifies the table_name column is filled in for each required extension row",
            "Handles the difference between gpkg_crs_wkt (not allowed for gridded data) and gpkg_crs_wkt_1_1 (required for gridded data)",
        ],
        "manual_notes": "Test confirmed: gpkg_crs_wkt_1_1 was missing for gridded data. gpkg_crs_wkt was present but is explicitly prohibited for gridded. Both are real problems.",
        "confidence": "High",
        "confidence_reason": "All 24 files checked; all 3 PASS* results manually confirmed (3/3). FAIL results are structurally verified — required extensions absent.",
    },
    4: {
        "name": "Optional Extensions",
        "auditor_checks": ["Optional extensions are by definition allowed, so their presence cannot cause a failure. This check is informational only."],
        "manual_notes": "No disputes found. All 24 files returned PASS*; 10/24 manually confirmed. Optional extensions cannot fail by definition.",
        "confidence": "Medium",
        "confidence_reason": "10/24 PASS* results manually confirmed. The check is structurally sound (optional extensions can never fail), but confirmation is partial across the dataset.",
    },
    5: {
        "name": "Extensions Not Allowed",
        "auditor_checks": [
            "Looks at every row in the extensions table and compares it against the DGIWG allowed list",
            "Correctly ignores gpkg_ogr_contents — that is a GDAL database table, not a registered extension",
        ],
        "manual_notes": "Confirmed: the original reference validator incorrectly flagged gpkg_ogr_contents. It is not in the extensions table. Our validator correctly ignores it.",
        "confidence": "Low",
        "confidence_reason": "0/16 PASS* results manually confirmed. FAIL is reported accurately, but without your specific product profile we cannot always determine whether an unknown extension is truly prohibited.",
    },
    6: {
        "name": "Conditional Extensions",
        "auditor_checks": ["Cannot be checked automatically — depends on your DGIWG product profile. Always returns SKIPPED."],
        "manual_notes": "Not evaluated. Requires knowing which product profile applies.",
        "confidence": "Low",
        "confidence_reason": "Skipped for all 24 files — check never ran. Requires product profile context not available in the file.",
    },
    7: {
        "name": "Raster CRS Allowed",
        "auditor_checks": [
            "Checks the CRS code for every tile/raster layer against the DGIWG approved list",
            "For each standard CRS (3857, 4326, 3395, 5041, 5042), verifies pixel_x_size/pixel_y_size "
            "at every zoom level matches OGC 17-083r4 expected value (= pixel_z0 / 2^zoom) within 0.01% tolerance",
            "FAIL if any zoom level's pixel size deviates from expected OGC scale sequence",
            "PASS* only when CRS is allowed but scale denominator lookup not available (custom CRS codes)",
        ],
        "manual_notes": "Scale denominator arithmetic now fully automated for all standard DGIWG CRS. "
                        "PASS = CRS allowed AND pixel sizes match OGC 17-083r4 sequence exactly.",
        "confidence": "High",
        "confidence_reason": "Full scale denominator check added. CRS allowlist confirmed across all applicable files. "
                             "Scale denominator check is mathematically deterministic — no manual confirmation needed.",
    },
    8: {
        "name": "CRS Raster Tile Matrix Set",
        "auditor_checks": [
            "For each tile matrix set, verifies tile dimensions are exactly 256×256 pixels at all zoom levels",
            "Tile dimensions are read directly from gpkg_tile_matrix — covers all declared zoom levels",
            "PASS = all zoom levels have 256×256 tiles; FAIL = any non-standard tile size",
        ],
        "manual_notes": "Tile dimension check is deterministic — reads actual values from gpkg_tile_matrix. "
                        "PASS = all declared tile sizes are 256×256 per OGC standard.",
        "confidence": "High",
        "confidence_reason": "Tile dimension check is fully automated and mathematically exact. "
                             "No sampling — all zoom levels checked for every tile matrix set.",
    },
    9: {
        "name": "2D Vector CRS",
        "auditor_checks": [
            "Checks every 2D vector layer (roads, buildings, etc.) uses EPSG:4326 (WGS84 lat/lon)",
            "Verifies each geometry column individually — not just the file as a whole",
        ],
        "manual_notes": "All 8 applicable PASS* results manually confirmed (8/8). Only 8/24 files had 2D vector data; the rest were correctly SKIPPED.",
        "confidence": "High",
        "confidence_reason": "8/8 applicable PASS* results fully confirmed. EPSG:4326 check verified per geometry column for every applicable file.",
    },
    10: {
        "name": "3D Vector CRS",
        "auditor_checks": [
            "Checks 3D vector layers use an approved 3D CRS (EPSG:4979 or EPSG:9518)",
            "Only applies to layers where geometry includes a Z coordinate",
        ],
        "manual_notes": "Skipped for all 24 files — no 3D vector geometry found in any test file. Check logic is sound but unconfirmed across this dataset.",
        "confidence": "Low",
        "confidence_reason": "Skipped for all 24 files — check never ran on this dataset. Logic is implemented but there is no evidence of correct execution to report.",
    },
    11: {
        "name": "Gridded 2D CRS",
        "auditor_checks": [
            "Checks the CRS code for each gridded layer against the DGIWG 2D gridded CRS approved list",
            "Correctly routes 3D elevation data (EPSG:4979 or COMPOUNDCRS) to Req 12 instead",
            "Cross-checks the file's declared bounding box against the valid geographic extent "
            "of the CRS (CRS_EXTENT lookup table). Bbox exceeding CRS extent by >0.1% → FAIL.",
        ],
        "manual_notes": "CRS allowlist + bbox vs CRS extent both automated. "
                        "PASS = CRS allowed AND declared bbox within CRS valid area.",
        "confidence": "High",
        "confidence_reason": "Both CRS allowlist and bbox cross-check are deterministic. "
                             "CRS routing (2D vs 3D) verified across applicable files.",
    },
    12: {
        "name": "Gridded 3D CRS",
        "auditor_checks": [
            "Checks the CRS code for 3D gridded data against the DGIWG 3D gridded CRS approved list",
            "Cross-checks the file's declared bounding box against the valid CRS extent",
            "Detects 3D data by looking for EPSG:4979, COMPOUNDCRS in WKT, or CRS codes 100100-100399",
            "Returns SKIPPED when no 3D gridded layers are present",
        ],
        "manual_notes": "Bbox vs CRS extent cross-check added. PASS = CRS allowed AND bbox within valid CRS area.",
        "confidence": "Medium",
        "confidence_reason": "Few 3D gridded files in this dataset. Logic is correct and upgraded; "
                             "confidence remains Medium pending more 3D gridded test files.",
    },
    13: {
        "name": "WKT for CRS",
        "auditor_checks": [
            "Confirms WKT is present and non-empty for all CRS entries (srs_id > 0)",
            "Checks for WKT1 keywords (GEOGCS, PROJCS, VERT_CS, COMPD_CS) — FAIL if found",
            "Verifies PRIMEM is Greenwich, ANGLEUNIT is degree, axis names latitude/longitude",
            "Extracts DATUM keyword name from WKT",
            "Cross-checks extracted DATUM name against EPSG registry via pyproj (offline EPSG DB). "
            "Mismatch between WKT datum name and official EPSG datum name → FAIL. "
            "Known aliases (WGS 84 / World Geodetic System 1984) are accepted without penalty.",
            "Uses definition_12_063 (WKT2) when available, falls back to definition",
        ],
        "manual_notes": "Datum name cross-check via pyproj (offline EPSG DB) fully automated. "
                        "PASS = all CRS have valid WKT2 + datum name matches EPSG registry. "
                        "Install pyproj: pip install pyproj",
        "confidence": "High",
        "confidence_reason": "Datum name verification now automated via pyproj offline EPSG DB. "
                             "No internet required. Hard WKT rules (WKT1/PRIMEM/ANGLEUNIT/AXIS) unchanged.",
    },
    14: {
        "name": "Compound CRS Usage",
        "auditor_checks": [
            "Checks that COMPOUNDCRS is only used on 3D layers (with Z coordinate). A 2D layer with compound CRS violates DGIWG.",
            "The original reference validator had this logic backwards — it failed all compound CRS regardless of 2D/3D. This is corrected.",
        ],
        "manual_notes": "Only 8/24 PASS* results manually confirmed. All 24 files returned PASS* but confirmation is partial. Corrected logic confirmed on test files.",
        "confidence": "Medium",
        "confidence_reason": "8/24 PASS* results confirmed — partial confirmation. Corrected compound CRS logic is implemented and verified, but not confirmed across the full dataset.",
    },
    15: {
        "name": "Compound CRS WKT",
        "auditor_checks": [
            "SKIPPED when no vector tables use a compound CRS (correct behaviour)",
            "When compound CRS found — verifies COMPOUNDCRS[ keyword present",
            "Verifies horizontal component (GEOGCRS or PROJCRS) is present and nested inside COMPOUNDCRS",
            "Verifies vertical component (VERTCRS) is present and nested inside COMPOUNDCRS",
            "Extracts and reports DATUM names from both sub-components",
        ],
        "manual_notes": "Full WKT2 compound CRS structure now validated via bracket-depth parsing. PASS = valid nesting of horizontal + VERTCRS inside COMPOUNDCRS.",
        "confidence": "High",
        "confidence_reason": "Structural WKT2 validation fully automated. SKIPPED when no compound CRS — correct. PASS/FAIL based on actual WKT2 nesting.",
    },
    16: {
        "name": "Gridded Compound CRS WKT",
        "auditor_checks": [
            "SKIPPED when no gridded data or no compound CRS used — correct",
            "Prefers definition_12_063 for WKT2 validation; flags WKT1 fallback as non-conformant",
            "Validates COMPOUNDCRS structure — horizontal + VERTCRS nested inside COMPOUNDCRS",
            "FAIL if definition_12_063 absent when compound CRS is used (DGIWG requires WKT2)",
        ],
        "manual_notes": "Full WKT2 compound CRS structure validated for gridded tables. definition_12_063 absence with compound CRS now triggers FAIL.",
        "confidence": "High",
        "confidence_reason": "Full structural WKT2 validation automated for gridded compound CRS. SKIPPED when not applicable — correct.",
    },
    17: {
        "name": "Gridded CRS Epoch WKT",
        "auditor_checks": [
            "SKIPPED when epoch column absent or no epoch values set — correct",
            "Reads epoch column value for each srs_id where epoch IS NOT NULL",
            "Parses WKT for DYNAMIC[FRAMEEPOCH[<value>]] using regex",
            "Compares extracted FRAMEEPOCH value against epoch column — FAIL on mismatch",
            "Uses definition_12_063 when available (WKT2 preferred)",
        ],
        "manual_notes": "DYNAMIC[FRAMEEPOCH[value]] now fully automated — value extracted and matched against epoch column. PASS = values match exactly.",
        "confidence": "High",
        "confidence_reason": "Epoch WKT validation fully automated. SKIPPED when no epoch data — correct. PASS/FAIL based on FRAMEEPOCH value match.",
    },
    18: {
        "name": "GeoPackage Metadata DMF",
        "auditor_checks": [
            "FAIL if gpkg_metadata missing or empty (matches v1.0)",
            "Identifies DMF rows by URI containing dgiwg+dmf",
            "Validates md_standard_uri starts with http://www.dgiwg.org/std/dmf",
            "Parses XML — validates fileIdentifier as UUID (8-4-4-4-12 hex)",
            "Validates language as ISO 639-2 3-letter code",
            "Validates characterSet as MD_CharacterSetCode",
            "Validates hierarchyLevel as MD_ScopeCode",
            "Validates contact/organisationName non-empty",
            "Validates contact/role as CI_RoleCode",
            "Validates dateStamp as ISO 8601 date/datetime",
        ],
        "manual_notes": "Full DMF XML field-value validation automated. PASS = all 8 DMF fields valid. PASS* = no DMF URI row found (structural only).",
        "confidence": "High",
        "confidence_reason": "All 8 DMF field values validated by XML parsing. Only gap: cannot verify organisationName is a real organisation (no registry lookup).",
    },
    19: {
        "name": "GeoPackage Metadata Document",
        "auditor_checks": [
            "Confirms gpkg_metadata_reference table exists (v1.0 match)",
            "Validates all metadata rows: XML must be well-formed; mime_type must be 'text/xml'",
            "Confirms at least one geopackage-scope reference row exists "
            "(reference_scope='geopackage' with NULL table/column/row)",
            "Validates every reference_scope/md_scope combination against DGIWG Table 36",
        ],
        "manual_notes": "XML well-formedness, geopackage-scope row presence, and Table 36 pairings "
                        "all fully automated. PASS = all checks pass. No manual verification needed.",
        "confidence": "High",
        "confidence_reason": "All Req 19 checks are deterministic and automated. "
                             "Table 36 pairing check eliminates the remaining manual scope verification step.",
    },
    20: {
        "name": "Complete Row GeoPackage Metadata",
        "auditor_checks": [
            "Checks that the file-level metadata reference row has blank (NULL) values for table_name and row_id_value",
            "Confirms a timestamp is present",
        ],
        "manual_notes": "18/21 applicable PASS* results manually confirmed. Required column checks are structurally sound.",
        "confidence": "High",
        "confidence_reason": "18/21 PASS* results confirmed — strong confirmation rate across the dataset. Required NULL column checks are structurally verified.",
    },
    21: {
        "name": "User Row GeoPackage Metadata",
        "auditor_checks": [
            "Checks that required columns exist in gpkg_metadata_reference",
            "Validates every reference_scope/md_scope combination against DGIWG Table 36",
            "Checks for orphan references (md_file_id not in gpkg_metadata.id) → FAIL",
            "Validates timestamp format is ISO 8601",
        ],
        "manual_notes": "Table 36 scope pairing, orphan detection, and timestamp validation "
                        "all automated. PASS = all reference rows valid per Table 36.",
        "confidence": "High",
        "confidence_reason": "All three gaps (Table 36, orphan check, timestamp) now automated. "
                             "Check is deterministic with no manual confirmation required.",
    },
    22: {
        "name": "Product Metadata",
        "auditor_checks": [
            "Checks for at least one metadata record with md_scope in ('series','dataset')",
            "Parses XML of each product metadata row — validates well-formedness, "
            "checks at least one ISO 19115 mandatory element is present, checks mime_type='text/xml'",
        ],
        "manual_notes": "XML content validation automated — well-formedness and ISO 19115 element "
                        "presence both checked. PASS = product metadata present AND XML valid.",
        "confidence": "High",
        "confidence_reason": "XML parsing is deterministic. Both scope presence and XML content "
                             "validated. Cannot verify free-text fields (org names, descriptions) — that is genuinely manual.",
    },
    23: {
        "name": "Product Partial Metadata",
        "auditor_checks": [
            "Checks that the file-level reference uses scope='geopackage' with table_name, column_name, and row_id_value all set to NULL",
            "Matches the original reference validator check exactly",
        ],
        "manual_notes": "All 18 applicable PASS* results manually confirmed (18/18). NULL column constraint matches reference validator exactly.",
        "confidence": "High",
        "confidence_reason": "18/18 applicable PASS* results fully confirmed. NULL column constraint check matches reference validator and is completely verified for this dataset.",
    },
    24: {
        "name": "Data Validity (Table 37)",
        "auditor_checks": [
            "Checks gpkg_contents, gpkg_geometry_columns, gpkg_tile_matrix tables exist (ATS 5.1–5.5)",
            "Verifies every table listed in gpkg_contents physically exists (ATS 5.2)",
            "Checks md_file_id referential integrity (ATS 5.6)",
            "Samples up to 25 geometry BLOBs per feature table using Shapely. "
            "Strips GeoPackage binary header, decodes WKB, calls geom.is_valid — "
            "detects self-intersections, unclosed rings, duplicate vertices, etc.",
            "Shapely not installed → PASS* with install note (pip install shapely)",
        ],
        "manual_notes": "OGC geometry validity added via Shapely. "
                        "PASS = ATS 5.1-5.6 all pass AND all sampled geometries valid. "
                        "25 geometries per table sampled — not a full table scan.",
        "confidence": "High",
        "confidence_reason": "Shapely geometry validity check is deterministic (OGC Simple Features rules). "
                             "ATS 5.1-5.6 referential integrity checks unchanged and verified.",
    },
    25: {
        "name": "Tile Matrix Width/Height",
        "auditor_checks": [
            "Checks that required columns exist in the tile matrix set table (matching original reference validator for Req 25)",
            "Deeper check verifies actual tile width and height values are 256x256",
        ],
        "manual_notes": "17/23 applicable PASS* results manually confirmed. Column-presence check matches reference validator; actual 256x256 tile size verification is in the deeper check.",
        "confidence": "Medium",
        "confidence_reason": "17/23 PASS* results confirmed — good but not complete. Column-presence is structural and reliable; actual tile dimension verification requires deeper check.",
    },
    26: {
        "name": "Tile Pyramid Data Size",
        "auditor_checks": [
            "Checks all 8 required columns exist in gpkg_tile_matrix — missing table is treated as all columns missing (FAIL), not SKIPPED, to match v1.0",
            "Samples up to 5 tile BLOBs per zoom level per tile table using Pillow (PIL) — decodes actual pixel dimensions and compares against declared tile_width/tile_height",
            "All tile tables are checked, all zoom levels are sampled — checks every table declared in gpkg_tile_matrix",
            "Returns PASS when all sampled BLOBs match declared dimensions; FAIL on any mismatch or decode error",
            "Returns PASS* if Pillow is not installed (structural check only) — install with: pip install Pillow",
        ],
        "manual_notes": "BLOB pixel decode now fully automated via Pillow. PASS = all sampled tiles match declared 256×256. No manual verification required when Pillow is available.",
        "confidence": "High",
        "confidence_reason": "Pillow BLOB decode directly verifies actual stored tile pixel dimensions against gpkg_tile_matrix declarations. Structural check + pixel decode = full Req 26 coverage.",
    },
    27: {
        "name": "Zoom Level Factor",
        "auditor_checks": [
            "For each tile table, verifies that pixel_x_size and pixel_y_size each halve exactly "
            "(ratio = 0.5 ± 0.01%) at every zoom level transition",
            "Reads all zoom levels from gpkg_tile_matrix — no sampling, all transitions checked",
            "PASS = every transition has factor-of-2; FAIL = any deviation beyond 0.01% tolerance",
        ],
        "manual_notes": "Exact factor-of-2 arithmetic check is fully automated. "
                        "PASS = all zoom level pixel sizes halve correctly per DGIWG requirement.",
        "confidence": "High",
        "confidence_reason": "Factor-of-2 check is mathematically exact and deterministic. "
                             "Covers all zoom level transitions for every tile table.",
    },
    28: {
        "name": "Multiple Zoom Matrix Sets",
        "auditor_checks": [
            "Checks that pixel sizes get strictly smaller as zoom level increases (monotonic decrease)",
            "Matches the original reference validator exactly",
        ],
        "manual_notes": "11/19 applicable PASS* results manually confirmed. Pixel-size monotonicity check matches reference validator.",
        "confidence": "Medium",
        "confidence_reason": "11/19 PASS* results confirmed — just over half confirmed. Pixel monotonicity logic is sound and matches reference validator, but confirmation is partial.",
    },
    29: {
        "name": "Single Zoom Matrix Set",
        "auditor_checks": [
            "Checks tile dimension consistency across zoom levels per table",
            "FAIL when dimensions vary across zoom levels for the same table",
        ],
        "manual_notes": "Only 2/18 applicable PASS* results manually confirmed. Most files have multi-zoom layers; single-zoom check is rarely exercised.",
        "confidence": "Medium",
        "confidence_reason": "2/18 PASS* results confirmed — low confirmation rate, but the check logic is scoped correctly. Most files have multi-zoom layers where this check is N/A.",
    },
    30: {
        "name": "Tile Matrix Set CRS BBox",
        "auditor_checks": [
            "Validates bbox min < max (sanity check)",
            "Cross-checks declared bbox against the valid geographic extent of the CRS "
            "(CRS_EXTENT lookup table, covering all DGIWG-approved CRS codes + UTM zones). "
            "Bbox exceeding CRS extent by >0.1% → FAIL.",
        ],
        "manual_notes": "CRS extent cross-check added. PASS = bbox is sane AND within valid CRS area.",
        "confidence": "High",
        "confidence_reason": "CRS extent cross-check is deterministic. "
                             "Both sanity check and CRS range check fully automated for all DGIWG CRS codes.",
    },
    31: {
        "name": "Tile Layer Metadata",
        "auditor_checks": [
            "FAIL when gpkg_metadata_reference missing (v1.0 match)",
            "For each tile-scope metadata row: validates XML well-formedness, "
            "confirms at least one ISO 19115 mandatory element is present, "
            "validates reference_scope/md_scope combination per Table 36",
        ],
        "manual_notes": "XML content and Table 36 pairing now automated. "
                        "PASS = tile metadata present AND XML valid AND scope pairing correct.",
        "confidence": "High",
        "confidence_reason": "XML parsing and Table 36 check are deterministic. "
                             "Gap from v1.26 (content not schema-validated) fully closed.",
    },
    32: {
        "name": "Feature Layer Metadata",
        "auditor_checks": [
            "FAIL when gpkg_metadata_reference missing or no text/xml rows (v1.0 match)",
            "For each feature-scope metadata row: validates XML well-formedness, "
            "confirms at least one ISO 19115 mandatory element is present, "
            "validates reference_scope/md_scope combination per Table 36",
        ],
        "manual_notes": "XML content and Table 36 pairing now automated. "
                        "PASS = feature metadata present AND XML valid AND scope pairing correct.",
        "confidence": "High",
        "confidence_reason": "XML parsing and Table 36 check are deterministic. "
                             "Gap from v1.26 (content not schema-validated) fully closed.",
    },
    33: {
        "name": "Gridded Extension Core",
        "auditor_checks": [
            "Verifies the 2D gridded coverage extension is registered for all three required tables",
            "Checks all required columns are present in the gridded coverage ancillary table",
        ],
        "manual_notes": "All 9 applicable PASS* results manually confirmed (9/9). Extension registrations and required columns all confirmed.",
        "confidence": "High",
        "confidence_reason": "9/9 applicable PASS* results fully confirmed. Extension registration and column presence completely verified for all applicable files.",
    },
    34: {
        "name": "Gridded Field Name Elevation",
        "auditor_checks": ["Checks that field name is 'Height' or 'Elevation' when data represents elevation or height values"],
        "manual_notes": "All 9 applicable files returned PASS (not PASS*) — exact value check, fully deterministic. field_name=Height confirmed correct.",
        "confidence": "High",
        "confidence_reason": "All 9 applicable files returned PASS (fully confirmed, not PASS*). Exact value check is deterministic — no partial verification possible.",
    },
    35: {
        "name": "Gridded Center Value Elevation",
        "auditor_checks": ["Checks that grid_cell_encoding is set to 'grid-value-is-center' for elevation data"],
        "manual_notes": "All 9 applicable files returned PASS (not PASS*) — exact value check, fully deterministic. grid_cell_encoding=grid-value-is-center confirmed.",
        "confidence": "High",
        "confidence_reason": "All 9 applicable files returned PASS (fully confirmed, not PASS*). Exact value check is deterministic — no partial verification possible.",
    },
    36: {
        "name": "Gridded Zoom Factor",
        "auditor_checks": ["Checks that the pixel size halves exactly (factor of 2.0) at each zoom level for gridded elevation layers"],
        "manual_notes": "5/6 applicable files returned PASS (not PASS*); 1 returned FAIL. Exact factor check is fully deterministic.",
        "confidence": "High",
        "confidence_reason": "Applicable files returned PASS or FAIL — exact pixel-size factor check is mathematically precise and fully deterministic.",
    },
    37: {
        "name": "Gridded User Row Metadata",
        "auditor_checks": [
            "Checks metadata reference rows for gridded tables exist and link to valid gpkg_metadata.id",
            "Validates reference_scope/md_scope combinations per DGIWG Table 36",
            "Parses XML of each gridded metadata row — confirms ISO 19115 elements present",
        ],
        "manual_notes": "Table 36 pairing and XML content validation automated. "
                        "PASS = gridded metadata present, all scope pairings valid, XML well-formed.",
        "confidence": "High",
        "confidence_reason": "Table 36 and XML checks are deterministic. "
                             "Remaining gap from v1.26 (md_scope pairing not verified) fully closed.",
    },
}

# Confidence colours
CONFIDENCE_COLOR = {"High": "#27ae60", "Medium": "#f39c12", "Low": "#e74c3c"}
CONFIDENCE_BG    = {"High": "#eafaf1", "Medium": "#fef9e7", "Low": "#fdedec"}


# ──────────────────────────────────────────────────────────────────────────────
# LIKELY CAUSE DIAGNOSIS
# Per-requirement, per-tool probable root cause text shown as a separate column
# in the per-file report table when status is FAIL or PASS*.
# Structure: { req_num: { "QGIS/GDAL": str, "ArcGIS": str, "UNKNOWN": str,
#                         "PASS*": str (shown for PASS* regardless of tool) } }
# ──────────────────────────────────────────────────────────────────────────────

LIKELY_CAUSE: dict = {
    3: {
        "QGIS/GDAL": "Required extension(s) missing from gpkg_extensions. GDAL may not register all DGIWG-required extensions automatically — add missing rows manually.",
        "ArcGIS":    "Required extension(s) missing. ArcGIS does not always register DGIWG-required extensions. Add the missing rows to gpkg_extensions manually.",
        "UNKNOWN":   "Required extension(s) missing or incorrectly scoped in gpkg_extensions.",
        "PASS*":     "Extension table present; verify all required extensions are registered with the correct scope.",
    },
    4: {
        "PASS*": "Optional extension noted. No action required unless the product profile prohibits it.",
    },
    5: {
        "QGIS/GDAL": "GDAL automatically injects 'gdal_nw' (No-Write lock) into gpkg_extensions at creation. This is a known GDAL artifact — not intentional non-conformance. Fix: DELETE FROM gpkg_extensions WHERE extension_name='gdal_nw'; before delivery.",
        "ArcGIS":    "Disallowed extension found. ArcGIS may introduce non-DGIWG extensions during export. Remove any extension not on the DGIWG permitted list.",
        "UNKNOWN":   "Disallowed extension found. Identify its origin and remove it from gpkg_extensions before delivery.",
    },
    7: {
        "QGIS/GDAL": "Pixel size drift most likely caused by reprojection during GeoTIFF→GeoPackage conversion. Use gdalwarp with a target resolution matched exactly to OGC 17-083r4 values for the target CRS.",
        "ArcGIS":    "CRS not on DGIWG approved list, or pixel sizes deviate from OGC 17-083r4 standard values. ArcGIS may assign custom srs_id codes to reprojected data — verify all srs_id values are standard EPSG codes from the DGIWG list.",
        "UNKNOWN":   "CRS code not on DGIWG approved list, or scale denominators do not match OGC 17-083r4 for the declared CRS.",
    },
    8: {
        "QGIS/GDAL": "Scale denominators in gpkg_tile_matrix do not match OGC 17-083r4 for this CRS. Likely caused by reprojection introducing pixel size drift. Re-export using gdalwarp with exact target resolution.",
        "ArcGIS":    "Scale denominators do not match OGC 17-083r4 standard values. ArcGIS tile matrix values may not align with DGIWG-required scale sequences.",
        "UNKNOWN":   "Scale denominators deviate from OGC 17-083r4 expected values for this CRS.",
    },
    9: {
        "QGIS/GDAL": "2D vector feature table uses a CRS other than EPSG:4326. DGIWG requires all 2D vector features to use WGS 84 geographic 2D (srs_id=4326).",
        "ArcGIS":    "2D vector feature table CRS is not EPSG:4326. ArcGIS may export features in a projected CRS — re-export with geographic CRS EPSG:4326.",
        "UNKNOWN":   "2D vector feature table does not use required CRS EPSG:4326.",
    },
    10: {
        "QGIS/GDAL": "3D vector feature table uses an unsupported CRS. Must be EPSG:4979 or a UTM zone (32601–32760).",
        "ArcGIS":    "3D vector feature table uses an unsupported CRS. ArcGIS may assign a custom srs_id for reprojected 3D data.",
        "UNKNOWN":   "3D vector feature table does not use a DGIWG-approved 3D CRS.",
    },
    11: {
        "QGIS/GDAL": "Gridded 2D CRS not on approved list, or bounding box falls outside the valid CRS extent. Check that srs_id is from the DGIWG list and that the min/max coordinates are geographically correct.",
        "ArcGIS":    "Gridded 2D CRS not approved, or bbox in native projected units instead of degrees. Verify srs_id and bounding box values in gpkg_tile_matrix_set.",
        "UNKNOWN":   "Gridded 2D CRS not approved or bounding box extends beyond valid CRS extent.",
    },
    12: {
        "QGIS/GDAL": "Gridded 3D CRS not approved or bbox outside valid extent. Verify srs_id is EPSG:4979 or a DGIWG-approved compound CRS.",
        "ArcGIS":    "Gridded 3D CRS not approved or bbox in native units. Check srs_id and coordinate ranges.",
        "UNKNOWN":   "Gridded 3D CRS not approved or bounding box exceeds valid CRS extent.",
    },
    13: {
        "QGIS/GDAL": "WKT check passed for most CRS entries. Any mismatch is typically a datum name alias — review the flagged srs_id entry manually.",
        "ArcGIS":    "ArcGIS commonly produces WKT1 syntax (GEOGCS, PROJCS) instead of WKT2:2019, and uses AUTHORITY[\"ESRI\",...] identifiers. Both cause FAIL. Re-export using a DGIWG-compliant CRS definition, or update gpkg_spatial_ref_sys manually with correct WKT2 strings.",
        "UNKNOWN":   "WKT2:2019 syntax issues or datum name mismatch. Inspect the definition column in gpkg_spatial_ref_sys for each flagged srs_id.",
        "PASS*":     "Hard WKT rules passed. pyproj not installed — datum name cross-check could not be run. Install pyproj for full automated verification.",
    },
    14: {
        "QGIS/GDAL": "COMPOUNDCRS used on 2D features (z=0). Compound CRS is only valid when the geometry column has a non-zero Z coordinate.",
        "ArcGIS":    "COMPOUNDCRS used incorrectly on 2D features. ArcGIS may assign compound CRS regardless of geometry dimensionality.",
        "UNKNOWN":   "COMPOUNDCRS present but geometry does not have 3D (z≠0) coordinates.",
    },
    15: {
        "QGIS/GDAL": "Compound WKT2 structure incorrect — VERTCRS or horizontal sub-component missing or not nested inside COMPOUNDCRS. Likely a WKT syntax issue in gpkg_spatial_ref_sys.",
        "ArcGIS":    "ArcGIS WKT1 compound CRS syntax (COMPD_CS) is not WKT2-compliant. Must use COMPOUNDCRS[ with GEOGCRS/PROJCRS and VERTCRS sub-components.",
        "UNKNOWN":   "Compound WKT2 nesting structure is missing or malformed.",
        "PASS*":     "Compound CRS keyword structure confirmed. Verify the named vertical datum is geographically appropriate for this dataset.",
    },
    16: {
        "QGIS/GDAL": "Gridded compound CRS WKT2 structure incorrect in definition_12_063 column. Verify COMPOUNDCRS nesting with horizontal + VERTCRS components.",
        "ArcGIS":    "definition_12_063 absent or uses WKT1 compound syntax. DGIWG requires WKT2 in definition_12_063 for gridded compound CRS.",
        "UNKNOWN":   "Gridded compound CRS WKT2 structure missing or malformed in definition_12_063.",
    },
    17: {
        "QGIS/GDAL": "DYNAMIC[FRAMEEPOCH[value]] in WKT does not match the epoch column value. Check that the epoch column in gpkg_spatial_ref_sys matches the FRAMEEPOCH value in the WKT definition.",
        "ArcGIS":    "Epoch WKT not found or epoch value mismatch. ArcGIS may not populate DYNAMIC[FRAMEEPOCH] automatically.",
        "UNKNOWN":   "FRAMEEPOCH value in WKT does not match epoch column, or DYNAMIC keyword is absent.",
    },
    18: {
        "QGIS/GDAL": "DMF metadata not added after export. GDAL/QGIS does not automatically create DGIWG DMF metadata records. Must be added manually to gpkg_metadata with the correct URI and XML structure.",
        "ArcGIS":    "DMF metadata absent or XML field values invalid. ArcGIS generates Esri-format metadata that does not conform to DGIWG DMF requirements. DMF records must be added or corrected manually.",
        "UNKNOWN":   "DMF metadata row absent or XML field values (UUID, language code, role codes, date format) do not meet DGIWG requirements.",
        "PASS*":     "No DMF URI row found — structural check only. Add a gpkg_metadata row with URI containing 'dgiwg+dmf' and valid DMF XML content.",
    },
    19: {
        "QGIS/GDAL": "gpkg_metadata_reference missing, not well-formed XML, or missing geopackage-scope reference row. Verify that a row with reference_scope='geopackage' exists in gpkg_metadata_reference.",
        "ArcGIS":    "Metadata reference table may be incomplete. Verify XML well-formedness of all metadata rows and that a geopackage-scope reference exists.",
        "UNKNOWN":   "gpkg_metadata_reference missing required geopackage-scope row or contains malformed XML.",
    },
    20: {
        "PASS*":     "Required columns confirmed present. Verify that a geopackage-scope reference row exists in gpkg_metadata_reference with NULL table/column/row values.",
    },
    21: {
        "QGIS/GDAL": "gpkg_metadata_reference contains invalid md_scope/reference_scope pairings per DGIWG Table 36, or orphan md_file_id references. Review and correct the reference table.",
        "ArcGIS":    "Metadata reference scope pairings do not match DGIWG Table 36, or md_file_id references do not resolve to gpkg_metadata rows.",
        "UNKNOWN":   "Invalid Table 36 scope pairings or orphaned metadata references detected.",
    },
    22: {
        "QGIS/GDAL": "Product metadata XML missing or ISO 19115 elements absent. Product metadata must be added manually after GDAL export.",
        "ArcGIS":    "Product metadata XML elements do not satisfy ISO 19115 requirements. Esri metadata format differs from DGIWG product metadata requirements.",
        "UNKNOWN":   "Product metadata row absent or required ISO 19115 elements missing from XML.",
        "PASS*":     "Product metadata present. Verify that identificationInfo, language, and contact elements are correctly populated.",
    },
    23: {
        "QGIS/GDAL": "geopackage-scope NULL reference row missing in gpkg_metadata_reference for product metadata.",
        "ArcGIS":    "Product partial metadata reference row absent. ArcGIS metadata structure may not include the required NULL geopackage-scope reference.",
        "UNKNOWN":   "geopackage-scope NULL reference row missing for product metadata.",
    },
    24: {
        "QGIS/GDAL": "Referential integrity issue or geometry validity failure. If shapely is installed, invalid geometries (self-intersections, unclosed rings) were found. Run the SQL query in Manual Confirmation to identify affected rows.",
        "ArcGIS":    "Referential integrity issue or geometry validity failure. ArcGIS geometries are generally valid but verify gpkg_contents lists all data tables correctly.",
        "UNKNOWN":   "Referential integrity failure or OGC geometry validity violation detected.",
        "PASS*":     "Referential integrity checks passed. Install shapely for full WKB geometry validity sampling.",
    },
    25: {
        "QGIS/GDAL": "Tile matrix declared dimensions are not 256×256. This is unusual for GDAL — verify gpkg_tile_matrix rows for this table.",
        "ArcGIS":    "Tile matrix declared dimensions are not 256×256. ArcGIS may use different default tile sizes.",
        "UNKNOWN":   "gpkg_tile_matrix declares tile dimensions other than 256×256 pixels.",
    },
    26: {
        "QGIS/GDAL": "Actual tile BLOB pixel dimensions do not match 256×256, or tile encoding could not be verified. Check for non-standard tile generation during GDAL conversion.",
        "ArcGIS":    "Tile BLOB pixel dimensions may not match 256×256. Verify actual stored tiles match declared matrix dimensions.",
        "UNKNOWN":   "Tile BLOB pixel dimensions could not be confirmed as 256×256.",
        "PASS*":     "Declared tile dimensions are 256×256. Install Pillow to verify actual BLOB pixel dimensions.",
    },
    27: {
        "QGIS/GDAL": "Zoom level pixel sizes do not follow an exact factor-of-2 sequence. Likely caused by reprojection introducing fractional pixel size drift. Re-export with pixel sizes matched exactly to OGC 17-083r4 scale sequence.",
        "ArcGIS":    "Zoom level pixel size ratio is not exactly 0.5 between levels. ArcGIS tile pyramid may use approximate rather than exact factor-of-2 scaling.",
        "UNKNOWN":   "Pixel size does not halve exactly (factor 2.0) between consecutive zoom levels.",
    },
    28: {
        "QGIS/GDAL": "Multiple zoom matrix sets do not maintain exact factor-of-2 pixel size progression.",
        "ArcGIS":    "Multiple zoom matrix sets have inconsistent pixel size ratios.",
        "UNKNOWN":   "Factor-of-2 zoom progression not maintained across multiple tile matrix sets.",
    },
    29: {
        "QGIS/GDAL": "Single-zoom tile table has unexpected tile dimensions.",
        "ArcGIS":    "Single-zoom tile table dimensions do not conform to DGIWG requirements.",
        "UNKNOWN":   "Single-zoom tile table does not meet DGIWG tile dimension requirements.",
    },
    30: {
        "QGIS/GDAL": "Bounding box exceeds the valid extent of the declared CRS. Check that min_x/min_y/max_x/max_y in gpkg_tile_matrix_set are in the correct units and within the CRS valid area.",
        "ArcGIS":    "Bounding box likely stored in projected CRS units (metres) rather than geographic coordinates (degrees), or extends beyond the CRS valid extent.",
        "UNKNOWN":   "Bounding box values fall outside the valid geographic extent of the declared CRS.",
    },
    31: {
        "QGIS/GDAL": "Tile layer metadata row missing or XML does not contain required ISO 19115 elements. Add metadata rows for tile tables to gpkg_metadata and gpkg_metadata_reference.",
        "ArcGIS":    "Tile layer metadata XML missing required ISO 19115 elements.",
        "UNKNOWN":   "Tile layer metadata absent or ISO 19115 elements missing.",
        "PASS*":     "Tile layer metadata row present. Verify ISO 19115 mandatory elements are populated.",
    },
    32: {
        "QGIS/GDAL": "Feature layer metadata row missing or XML does not contain required ISO 19115 elements.",
        "ArcGIS":    "Feature layer metadata XML missing required ISO 19115 elements.",
        "UNKNOWN":   "Feature layer metadata absent or ISO 19115 elements missing.",
        "PASS*":     "Feature layer metadata row present. Verify ISO 19115 mandatory elements are populated.",
    },
    33: {
        "QGIS/GDAL": "gpkg_2d_gridded_coverage extension not registered or ancillary table missing. Run: INSERT INTO gpkg_extensions VALUES('gpkg_2d_gridded_coverage', NULL, NULL, 'http://www.geopackage.org/spec121/#extension_tiled_gridded_elevation_data', 'read-write');",
        "ArcGIS":    "gpkg_2d_gridded_coverage extension not registered. ArcGIS may not register gridded coverage extensions automatically.",
        "UNKNOWN":   "gpkg_2d_gridded_coverage extension missing or ancillary table columns absent.",
    },
    34: {
        "QGIS/GDAL": "field_name value in gpkg_2d_gridded_coverage_ancillary is not the required DGIWG value. Update: UPDATE gpkg_2d_gridded_coverage_ancillary SET field_name='<correct_value>';",
        "ArcGIS":    "field_name value does not match DGIWG requirement.",
        "UNKNOWN":   "field_name value in gpkg_2d_gridded_coverage_ancillary is invalid.",
    },
    35: {
        "QGIS/GDAL": "grid_cell_encoding is likely 'grid-value-is-area' (GDAL default) instead of the required 'grid-value-is-center'. Fix: UPDATE gpkg_2d_gridded_coverage_ancillary SET grid_cell_encoding='grid-value-is-center';",
        "ArcGIS":    "grid_cell_encoding value is not DGIWG-compliant. Verify and update gpkg_2d_gridded_coverage_ancillary.",
        "UNKNOWN":   "grid_cell_encoding value is not the required DGIWG value.",
    },
    36: {
        "QGIS/GDAL": "Zoom factor between gridded coverage levels is not 2.0. GDAL may use non-standard steps. Re-tile with factor=2 using gdalwarp or gdal_translate.",
        "ArcGIS":    "Zoom factor between gridded coverage levels is not exactly 2.0. Verify and re-export with correct zoom progression.",
        "UNKNOWN":   "pixel_x_size/pixel_y_size ratio between consecutive zoom levels is not 2.0 in gpkg_tile_matrix for this gridded coverage table.",
    },
    37: {
        "QGIS/GDAL": "Gridded user row metadata missing, Table 36 scope pairings invalid, or XML malformed. Add gridded metadata rows to gpkg_metadata and gpkg_metadata_reference.",
        "ArcGIS":    "Gridded user row metadata scope pairings or XML content do not meet DGIWG requirements.",
        "UNKNOWN":   "Gridded metadata reference scope pairings invalid or XML content missing required elements.",
        "PASS*":     "Gridded metadata rows present. Verify Table 36 scope pairings and ISO 19115 XML elements manually.",
    },
}
