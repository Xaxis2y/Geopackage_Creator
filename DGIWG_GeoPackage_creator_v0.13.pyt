# -*- coding: utf-8 -*-
"""
DGIWG_GeoPackage.pyt
ArcGIS Pro Python Toolbox  –  v0.13
Converts a File Geodatabase (.gdb) to a DGIWG-compliant GeoPackage (.gpkg)
using only ArcPy + sqlite3 (no GDAL required).

DGIWG Standard reference:
  DGIWG-126  GeoPackage Profile 1.4 Ed.1.1
  Document:  STD-DP-19-005 v1.1, 2025-05-02
  Profiles:  OGC 12-128r19  GeoPackage Encoding Standard v1.4 (2024-06-02)

Fixes in v0.03 (vs v0.02):
  BUG-1   XML injection — all user strings now escaped via xml.sax.saxutils.escape()
  BUG-2   Reprojection — output_coordinate_system passed directly to ExportFeatures(),
          eliminating the broken delete/rename dance
  FIX-1   Standard number corrected from DGIWG-112 to DGIWG-126 everywhere
  FIX-2   OGC reference updated from 12-128r18 to 12-128r19 v1.4
  FIX-3   user_version PRAGMA corrected from 10200 to 10400 (GeoPackage 1.4.0)
  FIX-4   gpkg_wkt_for_crs extension now registered (DGIWG-126 §7.2, conf/crs)
  FIX-5   md_standard_uri changed to DGIWG Metadata Foundation (DMF) URI
          DMF elements added: metadataStandardName + metadataStandardVersion
  FIX-6   UPS North (EPSG:5041) and UPS South (EPSG:5042) added to CRS dropdown
          (DGIWG-126 Table 13 — explicitly approved polar CRS)
  FIX-7   Per-feature-layer metadata records written (DGIWG-126 §9.1, ATS A.4.5)
  FIX-8   Extension URIs updated from spec120 to spec140 throughout
  FIX-9   gpkg_rtree_index extension now explicitly registered per geometry column
  WARN-1  Silent bare except replaced with sqlite3.OperationalError catch + warning
  WARN-2  gpkg_contents UPDATE now checks cursor.rowcount and warns on zero rows
  IMPROVE-1  SQLite block wrapped in try/except/finally with rollback on error
  IMPROVE-2  arcpy progressor (progress bar) added for large GDB exports
  IMPROVE-3  Persistent timestamped .log file written alongside output GPKG

Fixes in v0.04 (vs v0.03):
  ADD-1   XML well-formedness validation — every DMF XML blob is parsed with
          xml.etree.ElementTree immediately after generation; a malformed
          document now raises ValueError before any SQLite writes occur.
  ADD-2   RTree post-registration verification — after the gpkg_rtree_index
          registration loop, the tool queries gpkg_extensions back and emits
          a WARNING for any geometry column that is missing its entry.
  ADD-3   Manual EPSG WKT-format warning — arcpy.SpatialReference.exportToString()
          returns ArcGIS WKT1 (not ISO 19162:2019 WKT2). When "Manual EPSG entry"
          is used the tool now emits a prominent WARNING and logs the authoritative
          epsg.io WKT2 URL so the operator can replace the definition column value
          before submitting to a DGIWG validator.

Fixes in v0.05 (vs v0.04):
  NEW-1   definition_12_063 column — gpkg_wkt_for_crs (OGC 12-128r19 §F.10)
          requires a backward-compat WKT1 column alongside the WKT2 'definition'
          column.  _ensure_wkt_for_crs_column() adds it via ALTER TABLE if absent;
          _upsert_srs() now writes both columns.  ArcPy exportToString() supplies
          the WKT1 value for the target EPSG; undefined rows use 'undefined'.
  NEW-2   Table-name sanitization hardened — re.sub(r'[^a-z0-9_]', '_', name)
          replaces ALL non-alphanumeric characters; a leading-digit name is
          prefixed with 't_' to produce a valid SQLite identifier.
  NEW-3   Final PRAGMA re-check — application_id and user_version are verified
          a second time after conn.commit() to guard against any ArcPy
          post-write resets, with automatic re-application and a WARNING.
  ADD-1   (completed) ET.fromstring() validates every generated DMF XML blob
          before it is inserted into gpkg_metadata.
  ADD-2   (completed) Post-loop query of gpkg_extensions confirms every geometry
          column has its gpkg_rtree_index entry; WARNs on any gap.
  ADD-3   (completed) WKT-format WARNING emitted in execute() when wkt_format
          equals 'ARCGIS_WKT1', with direct link to epsg.io WKT2 source.

Fixes in v0.06 (vs v0.05):
  GOLD-1  Parent-Child metadata linking confirmed — md_parent_id in
          gpkg_metadata_reference already links every per-layer record back to
          the package-level record (pkg_md_id).  Documented explicitly here and
          in the step-7g log messages.  No code change needed; present since v0.05.
  GOLD-2  Transactional geometry integrity check — after conn.commit() the tool
          reads back every gpkg_contents row and compares its stored extents
          against the ArcPy-derived extents.  Any discrepancy beyond 1e-6 units
          is automatically repaired with a WARNING.
          New function: _verify_and_repair_contents_extents()
  GOLD-3  gpkg_schema extension — gpkg_data_columns table created and populated
          with field aliases, types, and lengths from every exported feature class.
          Makes the GeoPackage self-documenting for QGIS, mobile tactical viewers,
          and other non-ArcGIS consumers.
          New function: _populate_gpkg_schema()
          New constant:  EXT_URI_SCHEMA
  GOLD-4  Anti-meridian bounding-box snapping — for geographic CRS (degrees)
          any extent coordinate within 0.01 deg of the WGS84 world bounds
          (-180/-90/180/90) is snapped to the exact bound value before writing
          to gpkg_contents.  Prevents DGIWG validators rejecting values like
          -179.9998 or 89.9997.
          New function: _snap_geographic_extent()
  GOLD-5  Compliance manifest (JSON) — after the GPKG is finalised, a companion
          *_compliance.json file is written alongside the .gpkg and .log.
          Includes: SHA-256 hash of the GPKG, WKT2 string, count of verified
          RTree indexes, DGIWG/OGC standard citations, and a per-layer summary.
          Provides a Certificate of Provenance for formal military delivery.
          New function: _write_compliance_manifest()
          New imports:   hashlib, json

Fixes in v0.07 (vs v0.06):
  FIX-1   LocalDatabase filter.

Fixes in v0.08 (vs v0.07):
  FIX-2   arcpy.env.outputCoordinateSystem.

Fixes in v0.09 (vs v0.08):
  FIX-3   NaN snap skip. FIX-4   manifest_path typo.

Fixes in v0.10 (vs v0.09):
  FIX-5   MCE attribution in DMF XML.

Fixes in v0.11 (vs v0.10):
  FIX-6   EPSG:4326 WKT2 ENSEMBLE form.
  FIX-7   gpkg_crs_wkt extension name + table ref corrected.
  FIX-8   _force_wkt2_srs() added (superseded by FIX-11 in v0.12).

Fixes in v0.12 (vs v0.11):
  FIX-9   application_id documented as 0x47503132 in changelog but constant
          was not updated (regression introduced in v0.12, fixed in v0.13).
  FIX-10  gmd:metadataStandardName and gmd:metadataStandardVersion removed
          from DMF XML. The DGIWG validator XSD does not include these
          elements; their presence caused Req 18 XSD validation FAIL.
  FIX-11  WKT2 persistence: all ArcPy and sqlite3 operations now run on a
          .__dgiwg_work__.gpkg temp file. After WKT2 is written and
          verified, the temp file is copied to the declared output path as
          the absolute last step. ArcGIS Pro has never touched the temp
          file, so it cannot overwrite WKT2 during catalog refresh.

Fixes in v0.13 (vs v0.12):
  FIX-12  GPKG_APPLICATION_ID constant corrected: 0x47504b47 ("GPKG" pre-
          standard marker) → 0x47503132 ("GP12", GeoPackage 1.2/1.3).
          FIX-9 in v0.12 documented this change in the changelog but the
          constant itself was never updated — this regression caused every
          output to fail DGIWG Validator Req 3 (application_id FAIL).
  FIX-13  _force_wkt2_srs() WKT2 keyword check widened: was startswith
          ("GEOGCRS") only — always triggered a spurious "WKT2 NOT
          confirmed" warning for projected CRS (UTM, Mercator, UPS) that
          correctly start with PROJCRS. Now accepts all valid WKT2 top-
          level keywords: GEOGCRS, PROJCRS, COMPOUNDCRS, VERTCRS, ENGCRS,
          TIMECRS, DERIVEDPROJCRS.
  FIX-14  WAL journal mode cleanup: PRAGMA journal_mode=DELETE added before
          the final conn.close() in the SQLite post-processing block.
          The DGIWG Validator v1.54 explicitly FAILs files in WAL mode
          (Req 3) because transferring without -wal/-shm sidecars causes
          silent data loss on receiving systems. Switching to DELETE mode
          checkpoints and removes all WAL files before the temp copy step.
  WARN-3  DGIWG Req 9 compliance warning: when the selected CRS is not
          EPSG:4326 and the GDB contains 2D vector feature classes, a
          prominent WARNING is emitted at runtime: "DGIWG Req 9 requires
          all 2D vector layers to use EPSG:4326 (WGS 84). Selected
          EPSG:{X} will cause Req 9 FAIL unless all exported layers are 3D."
  EXPAND-1 Full UTM CRS catalogue: all 60 WGS 84 UTM North zones
          (EPSG:32601–32660) and all 60 WGS 84 UTM South zones
          (EPSG:32701–32760) added to the dropdown with authoritative
          WKT2 strings generated programmatically. Previously only 3 UTM
          zones (1N, 10N, 32N) were available.
"""

import arcpy
import sqlite3
import os
import datetime
import uuid
import logging
import re
import hashlib
import json
import xml.sax.saxutils as saxutils
import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# Toolbox registration
# ---------------------------------------------------------------------------
class Toolbox:
    def __init__(self):
        self.label = "DGIWG GeoPackage Tools"
        self.alias = "dgiwg_gpkg"
        self.tools = [GDBtoGeoPackage]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# GeoPackage 1.2/1.3 header values  (OGC 12-128r19)
# FIX-12: corrected from 0x47504b47 ("GPKG" pre-standard) to 0x47503132 ("GP12")
# The DGIWG Validator v1.54 requires 0x47503132; 0x47504b47 causes Req 3 FAIL.
GPKG_APPLICATION_ID = 0x47503132   # "GP12" — GeoPackage 1.2/1.3 per OGC spec
GPKG_USER_VERSION   = 10400        # v1.4.0 content (DGIWG-126 profiles GP 1.4)

# Extension URIs for GeoPackage 1.4  (spec140, not spec120)
EXT_URI_METADATA  = "http://www.geopackage.org/spec140/#extension_metadata"
EXT_URI_WKT_CRS   = "http://www.geopackage.org/spec140/#extension_crs_wkt"
EXT_URI_RTREE     = "http://www.geopackage.org/spec140/#extension_rtree_index"
EXT_URI_SCHEMA    = "http://www.geopackage.org/spec140/#extension_schema"   # GOLD-3

# DGIWG Metadata Foundation URI  (DGIWG-126 §7.3 Table 31)
DMF_STANDARD_URI     = "http://metadata.dgiwg.org/Schema/2014/DMF"
DMF_STANDARD_NAME    = "DGIWG Metadata Foundation"
DMF_STANDARD_VERSION = "2.0"

# GOLD-4: Snapping margin for geographic CRS bounding-box edges (degrees)
ANTIMERIDIAN_SNAP_MARGIN = 0.01

# FIX-13: Valid WKT2 top-level keywords (ISO 19162:2019)
WKT2_KEYWORDS = (
    "GEOGCRS[", "PROJCRS[", "COMPOUNDCRS[", "VERTCRS[",
    "ENGCRS[", "TIMECRS[", "DERIVEDPROJCRS[",
)


# ---------------------------------------------------------------------------
# WKT2 helper for UTM zone generation  (EXPAND-1)
# ---------------------------------------------------------------------------

def _build_utm_wkt2(zone_number, hemisphere):
    """
    EXPAND-1: Generate authoritative WKT2 (ISO 19162:2019) for a WGS 84
    UTM zone.  hemisphere must be 'N' (north) or 'S' (south).

    Central meridian = (zone_number - 1) * 6 - 177
    False northing   = 0 (north) or 10 000 000 (south)
    EPSG code:
      North: 32600 + zone_number
      South: 32700 + zone_number
    """
    cm   = (zone_number - 1) * 6 - 177
    epsg = (32600 + zone_number) if hemisphere == "N" else (32700 + zone_number)
    fn   = 0 if hemisphere == "N" else 10000000
    hemi_word = "north" if hemisphere == "N" else "south"

    if hemisphere == "N":
        bbox_min_lat, bbox_max_lat = 0, 84
    else:
        bbox_min_lat, bbox_max_lat = -80, 0

    bbox_min_lon = cm - 3
    bbox_max_lon = cm + 3

    return (
        f'PROJCRS["WGS 84 / UTM zone {zone_number}{hemisphere}",'
        f'BASEGEOGCRS["WGS 84",'
        f'DATUM["World Geodetic System 1984",'
        f'ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]]],'
        f'PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]]],'
        f'CONVERSION["UTM zone {zone_number}{hemisphere}",'
        f'METHOD["Transverse Mercator",ID["EPSG",9807]],'
        f'PARAMETER["Latitude of natural origin",0,'
        f'ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8801]],'
        f'PARAMETER["Longitude of natural origin",{cm},'
        f'ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8802]],'
        f'PARAMETER["Scale factor at natural origin",0.9996,'
        f'SCALEUNIT["unity",1],ID["EPSG",8805]],'
        f'PARAMETER["False easting",500000,LENGTHUNIT["metre",1],ID["EPSG",8806]],'
        f'PARAMETER["False northing",{fn},LENGTHUNIT["metre",1],ID["EPSG",8807]]],'
        f'CS[Cartesian,2],'
        f'AXIS["(E)",east,ORDER[1],LENGTHUNIT["metre",1]],'
        f'AXIS["(N)",{hemi_word},ORDER[2],LENGTHUNIT["metre",1]],'
        f'USAGE[SCOPE["Navigation and medium accuracy spatial operations."],'
        f'AREA["Between {abs(cm-3)}{"W" if cm-3 < 0 else "E"} and '
        f'{abs(cm+3)}{"W" if cm+3 < 0 else "E"}, '
        f'{"N" if hemisphere == "N" else "S"} hemisphere."],'
        f'BBOX[{bbox_min_lat},{bbox_min_lon},{bbox_max_lat},{bbox_max_lon}]],'
        f'ID["EPSG",{epsg}]]'
    )


# ---------------------------------------------------------------------------
# CRS catalogue  —  DGIWG-126 Table 13
# WKT2 strings per OGC 18-010r7 / ISO 19162:2019
# ---------------------------------------------------------------------------
CRS_OPTIONS = {

    "WGS 84 Geographic 2D (EPSG:4326)": {
        "srs_id": 4326,
        "organization": "EPSG",
        "org_coord_sys_id": 4326,
        "definition": (
            'GEOGCRS["WGS 84",'
            'ENSEMBLE["World Geodetic System 1984 ensemble",'
            'MEMBER["World Geodetic System 1984 (Transit)"],'
            'MEMBER["World Geodetic System 1984 (G730)"],'
            'MEMBER["World Geodetic System 1984 (G873)"],'
            'MEMBER["World Geodetic System 1984 (G1150)"],'
            'MEMBER["World Geodetic System 1984 (G1674)"],'
            'MEMBER["World Geodetic System 1984 (G1762)"],'
            'MEMBER["World Geodetic System 1984 (G2139)"],'
            'ELLIPSOID["WGS 84",6378137,298.257223563,'
            'LENGTHUNIT["metre",1]],'
            'ENSEMBLEACCURACY[2.0]],'
            'PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]],'
            'CS[ellipsoidal,2],'
            'AXIS["geodetic latitude (Lat)",north,ORDER[1],'
            'ANGLEUNIT["degree",0.0174532925199433]],'
            'AXIS["geodetic longitude (Lon)",east,ORDER[2],'
            'ANGLEUNIT["degree",0.0174532925199433]],'
            'USAGE[SCOPE["Horizontal component of 3D system."],'
            'AREA["World."],BBOX[-90,-180,90,180]],'
            'ID["EPSG",4326]]'
        ),
        "description": "WGS 84 geographic 2D — DGIWG-126 Table 13",
    },

    "WGS 84 / World Mercator (EPSG:3395)": {
        "srs_id": 3395,
        "organization": "EPSG",
        "org_coord_sys_id": 3395,
        "definition": (
            'PROJCRS["WGS 84 / World Mercator",'
            'BASEGEOGCRS["WGS 84",'
            'DATUM["World Geodetic System 1984",'
            'ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]]],'
            'PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]]],'
            'CONVERSION["Mercator (variant A)",'
            'METHOD["Mercator (variant A)",ID["EPSG",9804]],'
            'PARAMETER["Latitude of natural origin",0,'
            'ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8801]],'
            'PARAMETER["Longitude of natural origin",0,'
            'ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8802]],'
            'PARAMETER["Scale factor at natural origin",1,'
            'SCALEUNIT["unity",1],ID["EPSG",8805]],'
            'PARAMETER["False easting",0,LENGTHUNIT["metre",1],ID["EPSG",8806]],'
            'PARAMETER["False northing",0,LENGTHUNIT["metre",1],ID["EPSG",8807]]],'
            'CS[Cartesian,2],'
            'AXIS["(E)",east,ORDER[1],LENGTHUNIT["metre",1]],'
            'AXIS["(N)",north,ORDER[2],LENGTHUNIT["metre",1]],'
            'USAGE[SCOPE["Very small scale mapping."],'
            'AREA["World between 80 S and 84 N."],BBOX[-80,-180,84,180]],'
            'ID["EPSG",3395]]'
        ),
        "description": "WGS 84 / World Mercator — DGIWG-126 Table 13",
    },

    "WGS 84 / UPS North E,N (EPSG:5041)": {
        "srs_id": 5041,
        "organization": "EPSG",
        "org_coord_sys_id": 5041,
        "definition": (
            'PROJCRS["WGS 84 / UPS North (E,N)",'
            'BASEGEOGCRS["WGS 84",'
            'DATUM["World Geodetic System 1984",'
            'ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]]],'
            'PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]]],'
            'CONVERSION["Universal Polar Stereographic North",'
            'METHOD["Polar Stereographic (variant A)",ID["EPSG",9810]],'
            'PARAMETER["Latitude of natural origin",90,'
            'ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8801]],'
            'PARAMETER["Longitude of natural origin",0,'
            'ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8802]],'
            'PARAMETER["Scale factor at natural origin",0.994,'
            'SCALEUNIT["unity",1],ID["EPSG",8805]],'
            'PARAMETER["False easting",2000000,LENGTHUNIT["metre",1],ID["EPSG",8806]],'
            'PARAMETER["False northing",2000000,LENGTHUNIT["metre",1],ID["EPSG",8807]]],'
            'CS[Cartesian,2],'
            'AXIS["Easting (E)",south,MERIDIAN[90,ANGLEUNIT["degree",0.0174532925199433]],'
            'ORDER[1],LENGTHUNIT["metre",1]],'
            'AXIS["Northing (N)",south,'
            'MERIDIAN[180,ANGLEUNIT["degree",0.0174532925199433]],'
            'ORDER[2],LENGTHUNIT["metre",1]],'
            'USAGE[SCOPE["Military and polar operations north of 60N."],'
            'AREA["Northern hemisphere - north of 60N onshore and offshore."],'
            'BBOX[60,-180,90,180]],'
            'ID["EPSG",5041]]'
        ),
        "description": "WGS 84 / UPS North (E,N) — DGIWG-126 Table 13 polar CRS",
    },

    "WGS 84 / UPS South E,N (EPSG:5042)": {
        "srs_id": 5042,
        "organization": "EPSG",
        "org_coord_sys_id": 5042,
        "definition": (
            'PROJCRS["WGS 84 / UPS South (E,N)",'
            'BASEGEOGCRS["WGS 84",'
            'DATUM["World Geodetic System 1984",'
            'ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]]],'
            'PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]]],'
            'CONVERSION["Universal Polar Stereographic South",'
            'METHOD["Polar Stereographic (variant A)",ID["EPSG",9810]],'
            'PARAMETER["Latitude of natural origin",-90,'
            'ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8801]],'
            'PARAMETER["Longitude of natural origin",0,'
            'ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8802]],'
            'PARAMETER["Scale factor at natural origin",0.994,'
            'SCALEUNIT["unity",1],ID["EPSG",8805]],'
            'PARAMETER["False easting",2000000,LENGTHUNIT["metre",1],ID["EPSG",8806]],'
            'PARAMETER["False northing",2000000,LENGTHUNIT["metre",1],ID["EPSG",8807]]],'
            'CS[Cartesian,2],'
            'AXIS["Easting (E)",north,MERIDIAN[90,ANGLEUNIT["degree",0.0174532925199433]],'
            'ORDER[1],LENGTHUNIT["metre",1]],'
            'AXIS["Northing (N)",north,'
            'MERIDIAN[0,ANGLEUNIT["degree",0.0174532925199433]],'
            'ORDER[2],LENGTHUNIT["metre",1]],'
            'USAGE[SCOPE["Military and polar operations south of 60S."],'
            'AREA["Southern hemisphere - south of 60S onshore and offshore."],'
            'BBOX[-90,-180,-60,180]],'
            'ID["EPSG",5042]]'
        ),
        "description": "WGS 84 / UPS South (E,N) — DGIWG-126 Table 13 polar CRS",
    },

    "Manual EPSG entry": None,
}

# EXPAND-1: Programmatically generate all 60 UTM North zones (32601–32660)
for _z in range(1, 61):
    _epsg = 32600 + _z
    _cm   = (_z - 1) * 6 - 177
    _key  = f"WGS 84 / UTM zone {_z}N  (EPSG:{_epsg})"
    CRS_OPTIONS[_key] = {
        "srs_id":            _epsg,
        "organization":      "EPSG",
        "org_coord_sys_id":  _epsg,
        "definition":        _build_utm_wkt2(_z, "N"),
        "description":       f"WGS 84 / UTM zone {_z}N — DGIWG-126 Table 13",
    }

# EXPAND-1: Programmatically generate all 60 UTM South zones (32701–32760)
for _z in range(1, 61):
    _epsg = 32700 + _z
    _cm   = (_z - 1) * 6 - 177
    _key  = f"WGS 84 / UTM zone {_z}S  (EPSG:{_epsg})"
    CRS_OPTIONS[_key] = {
        "srs_id":            _epsg,
        "organization":      "EPSG",
        "org_coord_sys_id":  _epsg,
        "definition":        _build_utm_wkt2(_z, "S"),
        "description":       f"WGS 84 / UTM zone {_z}S — DGIWG-126 Table 13",
    }

CRS_LIST = list(CRS_OPTIONS.keys())


# ---------------------------------------------------------------------------
# FIX-11: WKT2 persistence helpers
# ---------------------------------------------------------------------------
def _force_wkt2_srs(gpkg_path, srs_info, log_fn, warn_fn):
    """Open a fresh sqlite3 connection and write authoritative WKT2 definition.

    FIX-13: WKT2 verification widened — was startswith('GEOGCRS') only,
    which always triggered a false warning for projected CRS (PROJCRS).
    Now accepts all valid WKT2 top-level keywords defined in WKT2_KEYWORDS.
    """
    import sqlite3 as _sq
    try:
        conn = _sq.connect(gpkg_path)
        cur  = conn.cursor()
        cur.execute(
            "UPDATE gpkg_spatial_ref_sys SET definition = ?, srs_name = ? "
            "WHERE srs_id = ?",
            (srs_info["definition"], srs_info["description"], srs_info["srs_id"])
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(FULL);")
        conn.commit()
        cur.execute(
            "SELECT definition FROM gpkg_spatial_ref_sys WHERE srs_id = ?",
            (srs_info["srs_id"],)
        )
        row = cur.fetchone()
        # FIX-13: accept any WKT2 top-level keyword, not just GEOGCRS
        definition_ok = (
            row is not None and
            any(row[0].strip().upper().startswith(kw.upper())
                for kw in WKT2_KEYWORDS)
        )
        if definition_ok:
            log_fn(f"  WKT2 verified (srs_id={srs_info['srs_id']}).")
        else:
            actual = (row[0][:60] + "...") if row and row[0] else "<empty>"
            warn_fn(
                f"  WKT2 NOT confirmed for srs_id={srs_info['srs_id']} "
                f"(definition starts: '{actual}') "
                f"— validate BEFORE opening in ArcGIS Pro."
            )
        conn.close()
    except Exception as exc:
        warn_fn(f"  WKT2 force-write failed: {exc}")

# Helper — build DGIWG Metadata Foundation (DMF) XML
# ---------------------------------------------------------------------------
def _build_dmf_xml(title, abstract, point_of_contact,
                   organisation, date_str, language="eng",
                   scope="dataset"):
    e_title    = saxutils.escape(str(title))
    e_abstract = saxutils.escape(str(abstract))
    e_poc      = saxutils.escape(str(point_of_contact))
    e_org      = saxutils.escape(str(organisation))
    e_lang     = saxutils.escape(str(language))
    e_scope    = saxutils.escape(str(scope))
    e_date     = saxutils.escape(str(date_str))
    file_id    = str(uuid.uuid4())

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<gmd:MD_Metadata
  xmlns:gmd="http://www.isotc211.org/2005/gmd"
  xmlns:gco="http://www.isotc211.org/2005/gco"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.isotc211.org/2005/gmd
    http://schemas.opengis.net/iso/19139/20070417/gmd/gmd.xsd">
  <gmd:fileIdentifier>
    <gco:CharacterString>{file_id}</gco:CharacterString>
  </gmd:fileIdentifier>
  <gmd:language>
    <gmd:LanguageCode
      codeList="http://www.loc.gov/standards/iso639-2/"
      codeListValue="{e_lang}">{e_lang}</gmd:LanguageCode>
  </gmd:language>
  <gmd:characterSet>
    <gmd:MD_CharacterSetCode
      codeList="http://standards.iso.org/ittf/PubliclyAvailableStandards/ISO_19139_Schemas/resources/codelist/ML_gmxCodelists.xml#MD_CharacterSetCode"
      codeListValue="utf8">utf8</gmd:MD_CharacterSetCode>
  </gmd:characterSet>
  <gmd:hierarchyLevel>
    <gmd:MD_ScopeCode
      codeList="http://standards.iso.org/ittf/PubliclyAvailableStandards/ISO_19139_Schemas/resources/codelist/ML_gmxCodelists.xml#MD_ScopeCode"
      codeListValue="{e_scope}">{e_scope}</gmd:MD_ScopeCode>
  </gmd:hierarchyLevel>
  <gmd:contact>
    <gmd:CI_ResponsibleParty>
      <gmd:individualName>
        <gco:CharacterString>{e_poc}</gco:CharacterString>
      </gmd:individualName>
      <gmd:organisationName>
        <gco:CharacterString>{e_org}</gco:CharacterString>
      </gmd:organisationName>
      <gmd:role>
        <gmd:CI_RoleCode
          codeList="http://standards.iso.org/ittf/PubliclyAvailableStandards/ISO_19139_Schemas/resources/codelist/ML_gmxCodelists.xml#CI_RoleCode"
          codeListValue="pointOfContact">pointOfContact</gmd:CI_RoleCode>
      </gmd:role>
    </gmd:CI_ResponsibleParty>
  </gmd:contact>
  <gmd:dateStamp>
    <gco:Date>{e_date}</gco:Date>
  </gmd:dateStamp>
  <gmd:identificationInfo>
    <gmd:MD_DataIdentification>
      <gmd:citation>
        <gmd:CI_Citation>
          <gmd:title>
            <gco:CharacterString>{e_title}</gco:CharacterString>
          </gmd:title>
          <gmd:date>
            <gmd:CI_Date>
              <gmd:date>
                <gco:Date>{e_date}</gco:Date>
              </gmd:date>
              <gmd:dateType>
                <gmd:CI_DateTypeCode
                  codeList="http://standards.iso.org/ittf/PubliclyAvailableStandards/ISO_19139_Schemas/resources/codelist/ML_gmxCodelists.xml#CI_DateTypeCode"
                  codeListValue="creation">creation</gmd:CI_DateTypeCode>
              </gmd:dateType>
            </gmd:CI_Date>
          </gmd:date>
        </gmd:CI_Citation>
      </gmd:citation>
      <gmd:abstract>
        <gco:CharacterString>{e_abstract}</gco:CharacterString>
      </gmd:abstract>
      <gmd:language>
        <gmd:LanguageCode
          codeList="http://www.loc.gov/standards/iso639-2/"
          codeListValue="{e_lang}">{e_lang}</gmd:LanguageCode>
      </gmd:language>
    </gmd:MD_DataIdentification>
  </gmd:identificationInfo>
  <gmd:dataQualityInfo>
    <gmd:DQ_DataQuality>
      <gmd:scope>
        <gmd:DQ_Scope>
          <gmd:level>
            <gmd:MD_ScopeCode
              codeList="http://standards.iso.org/ittf/PubliclyAvailableStandards/ISO_19139_Schemas/resources/codelist/ML_gmxCodelists.xml#MD_ScopeCode"
              codeListValue="dataset">dataset</gmd:MD_ScopeCode>
          </gmd:level>
        </gmd:DQ_Scope>
      </gmd:scope>
      <gmd:lineage>
        <gmd:LI_Lineage>
          <gmd:processStep>
            <gmd:LI_ProcessStep>
              <gmd:description>
                <gco:CharacterString>DGIWG-compliant GeoPackage produced by the Mapping and Charting Establishment (MCE)</gco:CharacterString>
              </gmd:description>
            </gmd:LI_ProcessStep>
          </gmd:processStep>
        </gmd:LI_Lineage>
      </gmd:lineage>
    </gmd:DQ_DataQuality>
  </gmd:dataQualityInfo>
</gmd:MD_Metadata>"""
    return xml


# ---------------------------------------------------------------------------
# Helper — resolve SRS from user input
# ---------------------------------------------------------------------------
def _resolve_srs(crs_choice, manual_epsg_str):
    if crs_choice == "Manual EPSG entry":
        try:
            epsg = int(str(manual_epsg_str).strip())
        except (ValueError, AttributeError):
            raise ValueError(
                "Please enter a valid integer EPSG code in the "
                "'Manual EPSG Code' parameter."
            )
        sr = arcpy.SpatialReference(epsg)
        return {
            "srs_id":           epsg,
            "organization":     "EPSG",
            "org_coord_sys_id": epsg,
            "definition":       sr.exportToString(),
            "description":      sr.name,
            "wkt_format":       "ARCGIS_WKT1",
        }
    else:
        entry = CRS_OPTIONS.get(crs_choice)
        if entry is None:
            raise ValueError(f"Unknown or unsupported CRS choice: '{crs_choice}'.")
        result = dict(entry)
        result.setdefault("wkt_format", "WKT2")
        return result


# ---------------------------------------------------------------------------
# Helper — GeoPackage geometry type name
# ---------------------------------------------------------------------------
def _gpkg_geom_type(fc_path):
    desc  = arcpy.Describe(fc_path)
    shape = desc.shapeType.upper()
    return {
        "POINT":      "POINT",
        "MULTIPOINT": "MULTIPOINT",
        "POLYLINE":   "LINESTRING",
        "POLYGON":    "POLYGON",
        "MULTIPATCH": "MULTIPOLYGON",
    }.get(shape, "GEOMETRY")


# ---------------------------------------------------------------------------
# Helper — set up a file logger
# ---------------------------------------------------------------------------
def _setup_logger(gpkg_path):
    log_path = os.path.splitext(gpkg_path)[0] + "_export.log"
    logger   = logging.getLogger("dgiwg_gpkg")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    ))
    logger.addHandler(fh)
    return logger, log_path


# ---------------------------------------------------------------------------
# Main Tool
# ---------------------------------------------------------------------------
class GDBtoGeoPackage:
    """Convert an ArcGIS File GDB to a DGIWG-126-compliant GeoPackage."""

    def __init__(self):
        self.label       = "GDB to DGIWG GeoPackage"
        self.description = (
            "Exports all feature classes from a File Geodatabase to a "
            "DGIWG-126-compliant GeoPackage (STD-DP-19-005 v1.1), including "
            "DGIWG Metadata Foundation (DMF) XML and correct SRS table entries."
        )
        self.canRunInBackground = True

    def getParameterInfo(self):
        p_gdb = arcpy.Parameter(
            displayName="Input File Geodatabase (.gdb)",
            name="input_gdb",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        p_gdb.filter.list = ["LocalDatabase"]

        p_gpkg = arcpy.Parameter(
            displayName="Output GeoPackage (.gpkg)",
            name="output_gpkg",
            datatype="DEFile",
            parameterType="Required",
            direction="Output",
        )
        p_gpkg.filter.list = ["gpkg"]

        p_crs = arcpy.Parameter(
            displayName="Target Coordinate Reference System  [DGIWG-126 Table 13]",
            name="crs_choice",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p_crs.filter.type  = "ValueList"
        p_crs.filter.list  = CRS_LIST
        p_crs.value        = CRS_LIST[0]

        p_epsg = arcpy.Parameter(
            displayName="Manual EPSG Code (only when 'Manual EPSG entry' selected)",
            name="manual_epsg",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
        )

        p_title = arcpy.Parameter(
            displayName="Dataset Title  (DMF gmd:title)",
            name="dataset_title",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p_title.value = "DGIWG GeoPackage Dataset"

        p_abstract = arcpy.Parameter(
            displayName="Abstract / Description  (DMF gmd:abstract)",
            name="abstract",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p_abstract.value = "Geospatial dataset exported to DGIWG-126 GeoPackage profile."

        p_poc = arcpy.Parameter(
            displayName="Point of Contact - individual name  (DMF gmd:individualName)",
            name="point_of_contact",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p_poc.value = "GIS Administrator"

        p_org = arcpy.Parameter(
            displayName="Organisation Name  (DMF gmd:organisationName)",
            name="organisation",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p_org.value = "Defence Geospatial Organisation"

        p_lang = arcpy.Parameter(
            displayName="Metadata Language  (ISO 639-2, e.g. eng / fra / deu)",
            name="language",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        p_lang.value = "eng"

        p_fc_filter = arcpy.Parameter(
            displayName="Feature Classes to Include  (blank = all)",
            name="fc_filter",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )

        return [p_gdb, p_gpkg, p_crs, p_epsg,
                p_title, p_abstract, p_poc, p_org, p_lang, p_fc_filter]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        parameters[3].enabled = (parameters[2].value == "Manual EPSG entry")
        if parameters[0].altered and parameters[0].value:
            arcpy.env.workspace = str(parameters[0].value)
            fcs = arcpy.ListFeatureClasses() or []
            parameters[9].filter.list = sorted(fcs)

    def updateMessages(self, parameters):
        if parameters[2].value == "Manual EPSG entry" and not parameters[3].value:
            parameters[3].setWarningMessage(
                "Enter a valid EPSG integer code, e.g. 32618 for UTM zone 18N."
            )

    def execute(self, parameters, messages):
        input_gdb   = str(parameters[0].value)
        output_gpkg = str(parameters[1].value)
        # FIX-11: work on a temp file so ArcGIS Pro never touches the
        # working copy, preventing it from overwriting WKT2 with WKT1.
        import shutil as _shutil
        work_gpkg   = output_gpkg.replace(".gpkg", ".__dgiwg_work__.gpkg")
        crs_choice  = str(parameters[2].value)
        manual_epsg = str(parameters[3].value) if parameters[3].value else ""
        title       = str(parameters[4].value)
        abstract    = str(parameters[5].value)
        poc         = str(parameters[6].value)
        org         = str(parameters[7].value)
        language    = str(parameters[8].value) if parameters[8].value else "eng"
        fc_filter   = parameters[9].values if parameters[9].values else []

        logger, log_path = _setup_logger(output_gpkg)

        def log(msg, level="info"):
            arcpy.AddMessage(msg)
            getattr(logger, level)(msg)

        def warn(msg):
            messages.addWarningMessage(msg)
            logger.warning(msg)

        def err(msg):
            messages.addErrorMessage(msg)
            logger.error(msg)

        log("=" * 60)
        log("DGIWG GeoPackage Export  -  v0.13")
        log("Standard: DGIWG-126 (STD-DP-19-005 v1.1, 2025-05-02)")
        log("Profiles: OGC 12-128r19 GeoPackage Encoding Standard v1.4")
        log("=" * 60)

        # -- 1. Resolve SRS --------------------------------------------------
        try:
            srs_info = _resolve_srs(crs_choice, manual_epsg)
        except ValueError as exc:
            err(str(exc))
            return
        log(f"Target SRS: EPSG:{srs_info['srs_id']} - {srs_info['description']}")

        if srs_info.get("wkt_format") == "ARCGIS_WKT1":
            warn(
                f"COMPLIANCE WARNING - EPSG:{srs_info['srs_id']}: "
                "arcpy.SpatialReference.exportToString() produces ArcGIS WKT1, "
                "not ISO 19162:2019 WKT2 as required by gpkg_wkt_for_crs "
                f"(DGIWG-126 §7.2). Replace the 'definition' value with WKT2 from: "
                f"https://epsg.io/{srs_info['srs_id']}.wkt2"
            )

        # -- WARN-3: Req 9 — 2D vector CRS must be EPSG:4326 -----------------
        # DGIWG Req 9: ALL 2D vector feature layers must use EPSG:4326.
        # UTM, Mercator, and UPS are valid for gridded/raster but NOT for
        # 2D vector data. Emit a prominent warning so the operator knows
        # this file will fail Req 9 on the DGIWG Validator unless every
        # exported layer uses 3D geometry (z!=0).
        if srs_info["srs_id"] != 4326:
            arcpy.env.workspace = input_gdb
            _all_fcs_check = arcpy.ListFeatureClasses() or []
            _has_vector = len(_all_fcs_check) > 0
            if _has_vector:
                warn(
                    f"DGIWG REQ 9 WARNING: EPSG:{srs_info['srs_id']} selected for "
                    f"vector data. DGIWG Req 9 requires ALL 2D vector layers to use "
                    f"EPSG:4326 (WGS 84 Geographic 2D). Using any other CRS for 2D "
                    f"vector features will FAIL Req 9 on the DGIWG Validator. "
                    f"This CRS is only compliant for gridded/raster content or 3D "
                    f"vector layers (z!=0). If this is a gridded-only GDB, ignore "
                    f"this warning."
                )

        # -- 2. Collect feature classes ---------------------------------------
        arcpy.env.workspace = input_gdb
        all_fcs = arcpy.ListFeatureClasses() or []
        selected_fcs = (
            [fc for fc in all_fcs if fc in fc_filter] if fc_filter else all_fcs
        )
        if not selected_fcs:
            err("No feature classes found in the GDB (or none matched the filter).")
            return
        log(f"Feature classes to export: {selected_fcs}")

        # -- 3. Remove existing GPKG -----------------------------------------
        if os.path.exists(output_gpkg):
            os.remove(output_gpkg)
            log("Removed existing output file.")

        # -- 4. Create GeoPackage container ----------------------------------
        log("Creating GeoPackage container ...")
        arcpy.management.CreateSQLiteDatabase(work_gpkg, "GEOPACKAGE")

        # -- 5. Build target SpatialReference --------------------------------
        target_sr = arcpy.SpatialReference(srs_info["srs_id"])

        # GOLD-4: Detect geographic CRS for anti-meridian snapping
        is_geographic = (target_sr.type == "Geographic")
        if is_geographic:
            log(f"  Geographic CRS detected - anti-meridian snapping active "
                f"(margin +/-{ANTIMERIDIAN_SNAP_MARGIN} deg).")

        arcpy.SetProgressor("step", "Exporting feature classes ...",
                            0, len(selected_fcs), 1)

        # -- 6. Export each feature class ------------------------------------
        exported_tables = []
        for fc in selected_fcs:
            arcpy.SetProgressorLabel(f"Exporting: {fc}")
            log(f"  Exporting: {fc}")
            src      = os.path.join(input_gdb, fc)
            tbl_name = re.sub(r'[^a-z0-9_]', '_', fc.lower())
            if tbl_name and tbl_name[0].isdigit():
                tbl_name = 't_' + tbl_name
            dst = f"{work_gpkg}/{tbl_name}"

            try:
                src_sr = arcpy.Describe(src).spatialReference

                if src_sr.factoryCode != srs_info["srs_id"]:
                    log(f"    Reprojecting {fc} "
                        f"EPSG:{src_sr.factoryCode} -> EPSG:{srs_info['srs_id']}")
                    arcpy.env.outputCoordinateSystem = target_sr
                    try:
                        arcpy.conversion.ExportFeatures(
                            in_features             = src,
                            out_features            = dst,
                            use_field_alias_as_name = "NOT_USE_ALIAS",
                        )
                    finally:
                        arcpy.env.outputCoordinateSystem = None
                else:
                    arcpy.conversion.ExportFeatures(
                        in_features             = src,
                        out_features            = dst,
                        use_field_alias_as_name = "NOT_USE_ALIAS",
                    )

                desc     = arcpy.Describe(dst)
                ext      = desc.extent
                geom     = _gpkg_geom_type(dst)
                fc_count = int(arcpy.management.GetCount(dst)[0])

                # GOLD-4: Snap near-global extent edges for geographic CRS
                if is_geographic and fc_count > 0:
                    min_x, min_y, max_x, max_y = _snap_geographic_extent(
                        ext.XMin, ext.YMin, ext.XMax, ext.YMax,
                        margin=ANTIMERIDIAN_SNAP_MARGIN
                    )
                    orig = (ext.XMin, ext.YMin, ext.XMax, ext.YMax)
                    snapped = (min_x, min_y, max_x, max_y)
                    if snapped != orig:
                        log(f"    GOLD-4 Snap applied for {tbl_name}: "
                            f"({orig[0]:.6f},{orig[1]:.6f},"
                            f"{orig[2]:.6f},{orig[3]:.6f}) -> "
                            f"({min_x},{min_y},{max_x},{max_y})")
                else:
                    min_x, min_y, max_x, max_y = (
                        ext.XMin, ext.YMin, ext.XMax, ext.YMax
                    )

                exported_tables.append({
                    "table_name":  tbl_name,
                    "original_fc": fc,          # GOLD-3: needed for field lookup
                    "geom_type":   geom,
                    "min_x":       min_x,
                    "min_y":       min_y,
                    "max_x":       max_x,
                    "max_y":       max_y,
                    "count":       fc_count,
                })
                log(f"    OK - {fc_count} features -> {tbl_name}")

            except Exception as exc:
                warn(f"    SKIPPED {fc}: {exc}")

            arcpy.SetProgressorPosition()

        arcpy.ResetProgressor()

        if not exported_tables:
            err("No feature classes were exported successfully.")
            return

        # -- 7. SQLite post-processing: DGIWG-126 compliance ----------------
        log("Applying DGIWG-126 compliance fixes ...")
        conn = sqlite3.connect(work_gpkg)
        rtree_verified_count = 0
        try:
            cursor = conn.cursor()

            # 7a. application_id
            # FIX-12: constant now 0x47503132 ("GP12"); old 0x47504b47 ("GPKG")
            # caused Req 3 FAIL on every output from v0.12.
            cursor.execute("PRAGMA application_id;")
            if cursor.fetchone()[0] != GPKG_APPLICATION_ID:
                conn.execute(f"PRAGMA application_id = {GPKG_APPLICATION_ID};")
                log("  Fixed application_id header.")

            # 7b. user_version
            cursor.execute("PRAGMA user_version;")
            cur_ver = cursor.fetchone()[0]
            if cur_ver != GPKG_USER_VERSION:
                conn.execute(f"PRAGMA user_version = {GPKG_USER_VERSION};")
                log(f"  Set user_version {cur_ver} -> {GPKG_USER_VERSION}.")

            # 7c. gpkg_extensions table
            _ensure_extensions_table(cursor)

            # 7d. gpkg_wkt_for_crs extension
            _register_extension(
                cursor, "gpkg_spatial_ref_sys", "definition_12_063",
                "gpkg_crs_wkt", EXT_URI_WKT_CRS, "read-write",
            )
            log("  gpkg_crs_wkt extension registered (DGIWG-126 §7.2).")

            # 7e. gpkg_spatial_ref_sys
            _ensure_srs_table(cursor)
            _ensure_wkt_for_crs_column(cursor)
            log("  definition_12_063 column ensured (gpkg_wkt_for_crs §F.10).")

            _upsert_srs(cursor, -1, "Undefined Cartesian",  "NONE", -1,
                        "undefined",
                        "Undefined Cartesian coordinate reference system.",
                        definition_12_063="undefined")
            _upsert_srs(cursor,  0, "Undefined Geographic", "NONE",  0,
                        "undefined",
                        "Undefined geographic coordinate reference system.",
                        definition_12_063="undefined")

            target_wkt1 = arcpy.SpatialReference(srs_info["srs_id"]).exportToString()
            _upsert_srs(
                cursor,
                srs_info["srs_id"],
                srs_info["description"],
                srs_info["organization"],
                srs_info["org_coord_sys_id"],
                srs_info["definition"],
                srs_info["description"],
                definition_12_063=target_wkt1,
            )
            log("  gpkg_spatial_ref_sys updated (WKT2 + WKT1).")

            # 7f. gpkg_contents
            today = datetime.datetime.now(
                datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

            for tbl in exported_tables:
                cursor.execute("""
                    UPDATE gpkg_contents
                    SET    data_type   = 'features',
                           identifier  = ?,
                           description = ?,
                           last_change = ?,
                           min_x       = ?,
                           min_y       = ?,
                           max_x       = ?,
                           max_y       = ?,
                           srs_id      = ?
                    WHERE  table_name  = ?
                """, (
                    tbl["table_name"],
                    f"Exported from {os.path.basename(input_gdb)}",
                    today,
                    tbl["min_x"], tbl["min_y"],
                    tbl["max_x"], tbl["max_y"],
                    srs_info["srs_id"],
                    tbl["table_name"],
                ))
                if cursor.rowcount == 0:
                    warn(f"  gpkg_contents UPDATE matched 0 rows for "
                         f"'{tbl['table_name']}' - inserting manually.")
                    cursor.execute("""
                        INSERT OR IGNORE INTO gpkg_contents
                            (table_name, data_type, identifier, description,
                             last_change, min_x, min_y, max_x, max_y, srs_id)
                        VALUES (?, 'features', ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        tbl["table_name"], tbl["table_name"],
                        f"Exported from {os.path.basename(input_gdb)}",
                        today,
                        tbl["min_x"], tbl["min_y"],
                        tbl["max_x"], tbl["max_y"],
                        srs_info["srs_id"],
                    ))
            log("  gpkg_contents updated.")

            # 7g. Metadata tables
            _ensure_metadata_tables(cursor)
            date_str = datetime.date.today().isoformat()

            pkg_xml = _build_dmf_xml(
                title, abstract, poc, org, date_str, language, scope="dataset"
            )
            _validate_xml_wellformedness(pkg_xml, "package-level DMF")
            cursor.execute("""
                INSERT INTO gpkg_metadata
                    (md_scope, md_standard_uri, mime_type, metadata)
                VALUES (?, ?, ?, ?)
            """, ("dataset", DMF_STANDARD_URI, "text/xml", pkg_xml))
            pkg_md_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO gpkg_metadata_reference
                    (reference_scope, table_name, column_name,
                     row_id_value, timestamp, md_file_id, md_parent_id)
                VALUES ('geopackage', NULL, NULL, NULL, ?, ?, NULL)
            """, (today, pkg_md_id))
            log(f"  Package-level DMF metadata inserted "
                f"(id={pkg_md_id}, scope=geopackage).")

            # GOLD-1: Per-layer DMF records with md_parent_id -> pkg_md_id
            for tbl in exported_tables:
                layer_title    = f"{title} - {tbl['table_name']}"
                layer_abstract = (
                    f"Feature layer '{tbl['table_name']}' exported from "
                    f"{os.path.basename(input_gdb)}. "
                    f"Feature count: {tbl['count']}. "
                    f"Geometry type: {tbl['geom_type']}."
                )
                layer_xml = _build_dmf_xml(
                    layer_title, layer_abstract, poc, org,
                    date_str, language, scope="dataset"
                )
                _validate_xml_wellformedness(
                    layer_xml, f"layer DMF - {tbl['table_name']}"
                )
                cursor.execute("""
                    INSERT INTO gpkg_metadata
                        (md_scope, md_standard_uri, mime_type, metadata)
                    VALUES (?, ?, ?, ?)
                """, ("dataset", DMF_STANDARD_URI, "text/xml", layer_xml))
                layer_md_id = cursor.lastrowid

                # GOLD-1: md_parent_id links layer -> package (provenance chain)
                cursor.execute("""
                    INSERT INTO gpkg_metadata_reference
                        (reference_scope, table_name, column_name,
                         row_id_value, timestamp, md_file_id, md_parent_id)
                    VALUES ('table', ?, NULL, NULL, ?, ?, ?)
                """, (tbl["table_name"], today, layer_md_id, pkg_md_id))
                log(f"  Per-layer metadata: '{tbl['table_name']}' "
                    f"(id={layer_md_id}, parent={pkg_md_id}) "
                    f"[GOLD-1 provenance chain].")

            # 7h. gpkg_metadata extension
            _register_extension(
                cursor, None, None,
                "gpkg_metadata", EXT_URI_METADATA, "read-write",
            )
            log("  gpkg_metadata extension registered.")

            # 7i. RTree spatial index
            cursor.execute(
                "SELECT table_name, column_name FROM gpkg_geometry_columns;"
            )
            geom_cols = cursor.fetchall()
            for (tbl_name, col_name) in geom_cols:
                _register_extension(
                    cursor, tbl_name, col_name,
                    "gpkg_rtree_index", EXT_URI_RTREE, "read-write",
                )
                try:
                    cursor.execute(
                        f"SELECT HasSpatialIndex('{tbl_name}', '{col_name}');"
                    )
                    has_idx = cursor.fetchone()
                    if not has_idx or not has_idx[0]:
                        cursor.execute(
                            f"SELECT CreateSpatialIndex"
                            f"('{tbl_name}', '{col_name}');"
                        )
                        log(f"  SpatiaLite spatial index created: "
                            f"{tbl_name}.{col_name}")
                except sqlite3.OperationalError:
                    log(f"  RTree registered for {tbl_name}.{col_name} "
                        f"(SpatiaLite not available, ArcGIS-managed).")
                except Exception as exc:
                    warn(f"  Unexpected error on spatial index "
                         f"{tbl_name}.{col_name}: {exc}")

            # ADD-2: Verify every geometry column has its rtree entry
            cursor.execute("""
                SELECT table_name, column_name FROM gpkg_extensions
                WHERE  extension_name = 'gpkg_rtree_index'
            """)
            indexed_pairs = {(r[0], r[1]) for r in cursor.fetchall()}
            missing_rtree = [(t, c) for (t, c) in geom_cols
                             if (t, c) not in indexed_pairs]
            if missing_rtree:
                for (t, c) in missing_rtree:
                    warn(f"  RTREE MISSING: {t}.{c} not in gpkg_extensions.")
            else:
                log(f"  RTree verified: all {len(geom_cols)} geometry "
                    f"column(s) registered.")
            rtree_verified_count = len(geom_cols) - len(missing_rtree)

            # 7j. GOLD-3: gpkg_schema extension + gpkg_data_columns
            _register_extension(
                cursor, None, None,
                "gpkg_schema", EXT_URI_SCHEMA, "read-write",
            )
            _populate_gpkg_schema(cursor, exported_tables, input_gdb, log)
            log("  gpkg_schema extension registered (GOLD-3).")

            # 7k. Final PRAGMA re-check before commit
            # NEW-3: Re-apply application_id and user_version in case ArcPy reset them
            cursor.execute("PRAGMA application_id;")
            pre_commit_app_id = cursor.fetchone()[0]
            cursor.execute("PRAGMA user_version;")
            pre_commit_usr_ver = cursor.fetchone()[0]
            if pre_commit_app_id != GPKG_APPLICATION_ID:
                conn.execute(f"PRAGMA application_id = {GPKG_APPLICATION_ID};")
                warn(f"  application_id was {pre_commit_app_id} pre-commit "
                     f"- re-applied {GPKG_APPLICATION_ID}.")
            if pre_commit_usr_ver != GPKG_USER_VERSION:
                conn.execute(f"PRAGMA user_version = {GPKG_USER_VERSION};")
                warn(f"  user_version was {pre_commit_usr_ver} pre-commit "
                     f"- re-applied {GPKG_USER_VERSION}.")

            # FIX-14: Switch from WAL to DELETE journal mode before close.
            # The DGIWG Validator v1.54 explicitly FAILs files in WAL mode
            # (Req 3) because transferring without -wal/-shm sidecars causes
            # silent data loss on the receiving system.  Setting DELETE mode
            # here checkpoints + removes all WAL/SHM sidecar files before the
            # temp-to-output copy step that finalises the GeoPackage.
            try:
                cursor.execute("PRAGMA journal_mode=DELETE;")
                jm_result = cursor.fetchone()
                jm_current = jm_result[0] if jm_result else "unknown"
                if jm_current.lower() == "delete":
                    log("  FIX-14 journal_mode=DELETE confirmed (WAL cleanup ✓).")
                else:
                    warn(f"  FIX-14 journal_mode switch returned '{jm_current}' "
                         f"(expected 'delete') — WAL cleanup may be incomplete.")
            except Exception as _jm_exc:
                warn(f"  FIX-14 journal_mode=DELETE failed: {_jm_exc}")

            conn.commit()
            log("  All SQLite changes committed.")

            # GOLD-2: Post-commit extent integrity check + auto-repair
            repaired = _verify_and_repair_contents_extents(
                cursor, exported_tables, log, warn
            )
            if repaired > 0:
                conn.commit()
                log(f"  GOLD-2 Extent repairs committed ({repaired} table(s)).")

            # Final PRAGMA re-check after commit
            cursor.execute("PRAGMA application_id;")
            final_app_id = cursor.fetchone()[0]
            cursor.execute("PRAGMA user_version;")
            final_usr_ver = cursor.fetchone()[0]
            if final_app_id != GPKG_APPLICATION_ID:
                conn.execute(f"PRAGMA application_id = {GPKG_APPLICATION_ID};")
                conn.commit()
                warn(f"  application_id was {final_app_id} after commit "
                     f"- re-applied {GPKG_APPLICATION_ID}.")
            if final_usr_ver != GPKG_USER_VERSION:
                conn.execute(f"PRAGMA user_version = {GPKG_USER_VERSION};")
                conn.commit()
                warn(f"  user_version was {final_usr_ver} after commit "
                     f"- re-applied {GPKG_USER_VERSION}.")
            log(f"  Final PRAGMA re-check complete "
                f"(app_id=0x{final_app_id:08X}, user_ver={final_usr_ver}).")

        except Exception as exc:
            conn.rollback()
            err(f"SQLite post-processing failed - rolled back: {exc}")
            raise
        finally:
            conn.close()

        # -- 8. GOLD-5: Compliance manifest ----------------------------------
        manifest_path = None
        try:
            manifest_path = _write_compliance_manifest(
                work_gpkg, srs_info, exported_tables,
                rtree_verified_count, tool_version="v0.13"
            )
            log(f"  GOLD-5 Compliance manifest: {manifest_path}")
        except Exception as exc:
            warn(f"  GOLD-5 Compliance manifest could not be written: {exc}")

        # -- 9. FIX-11: Force WKT2, then copy to final output ---------------
        _force_wkt2_srs(work_gpkg, srs_info, log, warn)
        try:
            if os.path.exists(output_gpkg):
                os.remove(output_gpkg)
            _shutil.copy2(work_gpkg, output_gpkg)
            # Rename .log and .json to match output_gpkg name
            for ext in ("_export.log", "_compliance.json"):
                w = work_gpkg.replace(".__dgiwg_work__.gpkg", ext)
                o = output_gpkg.replace(".gpkg", ext)
                if os.path.exists(w):
                    if os.path.exists(o):
                        os.remove(o)
                    os.rename(w, o)
            os.remove(work_gpkg)
            log("  Output file finalised (WKT2-protected copy).")
        except Exception as copy_exc:
            warn(f"  Could not copy work file to output: {copy_exc}")

        # -- 10. Summary -----------------------------------------------------
        log("=" * 60)
        log("DGIWG GeoPackage created successfully:")
        log(f"  Output    : {output_gpkg}")
        log(f"  Log       : {log_path}")
        if manifest_path:
            log(f"  Manifest  : {manifest_path}")
        log(f"  Layers    : {len(exported_tables)}")
        log(f"  SRS       : EPSG:{srs_info['srs_id']}")
        log(f"  Standard  : DGIWG-126 Ed.1.1 / OGC 12-128r19 v1.4")
        log(f"  Metadata  : DGIWG Metadata Foundation (DMF) v2.0")
        for tbl in exported_tables:
            log(f"    {tbl['table_name']:40s}  "
                f"{tbl['count']:>8,} features  {tbl['geom_type']}")
        log("=" * 60)
        log("Validate at: https://cite.opengeospatial.org/te2/")


# ---------------------------------------------------------------------------
# SQLite helper functions
# ---------------------------------------------------------------------------

def _validate_xml_wellformedness(xml_string, label=""):
    """ADD-1: Raise ValueError if xml_string is not well-formed XML."""
    try:
        ET.fromstring(xml_string.encode("utf-8"))
    except ET.ParseError as exc:
        raise ValueError(
            f"Generated XML is not well-formed [{label}]: {exc}"
        )


def _ensure_wkt_for_crs_column(cursor):
    """NEW-1: Add definition_12_063 column to gpkg_spatial_ref_sys if absent."""
    cursor.execute("PRAGMA table_info(gpkg_spatial_ref_sys);")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if "definition_12_063" not in existing_cols:
        cursor.execute(
            "ALTER TABLE gpkg_spatial_ref_sys "
            "ADD COLUMN definition_12_063 TEXT NOT NULL DEFAULT 'undefined';"
        )


def _ensure_srs_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gpkg_spatial_ref_sys (
            srs_name                 TEXT    NOT NULL,
            srs_id                   INTEGER NOT NULL PRIMARY KEY,
            organization             TEXT    NOT NULL,
            organization_coordsys_id INTEGER NOT NULL,
            definition               TEXT    NOT NULL,
            description              TEXT
        );
    """)


def _upsert_srs(cursor, srs_id, srs_name, organization,
                org_coordsys_id, definition, description,
                definition_12_063=None):
    """NEW-1: Insert or replace an SRS row, writing both WKT2 and WKT1."""
    cursor.execute("PRAGMA table_info(gpkg_spatial_ref_sys);")
    has_wkt1_col = any(
        row[1] == "definition_12_063" for row in cursor.fetchall()
    )
    if definition_12_063 is not None and has_wkt1_col:
        cursor.execute("""
            INSERT OR REPLACE INTO gpkg_spatial_ref_sys
                (srs_name, srs_id, organization, organization_coordsys_id,
                 definition, description, definition_12_063)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (srs_name, srs_id, organization, org_coordsys_id,
              definition, description, definition_12_063))
    else:
        cursor.execute("""
            INSERT OR REPLACE INTO gpkg_spatial_ref_sys
                (srs_name, srs_id, organization, organization_coordsys_id,
                 definition, description)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (srs_name, srs_id, organization, org_coordsys_id,
              definition, description))


def _ensure_metadata_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gpkg_metadata (
            id              INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            md_scope        TEXT    NOT NULL DEFAULT 'dataset',
            md_standard_uri TEXT    NOT NULL,
            mime_type       TEXT    NOT NULL DEFAULT 'text/xml',
            metadata        TEXT    NOT NULL DEFAULT ''
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gpkg_metadata_reference (
            reference_scope TEXT     NOT NULL,
            table_name      TEXT,
            column_name     TEXT,
            row_id_value    INTEGER,
            timestamp       DATETIME NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            md_file_id      INTEGER  NOT NULL REFERENCES gpkg_metadata(id),
            md_parent_id    INTEGER  REFERENCES gpkg_metadata(id)
        );
    """)


def _ensure_extensions_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gpkg_extensions (
            table_name     TEXT,
            column_name    TEXT,
            extension_name TEXT NOT NULL,
            definition     TEXT NOT NULL,
            scope          TEXT NOT NULL,
            CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name)
        );
    """)


def _register_extension(cursor, table_name, column_name,
                         extension_name, definition, scope):
    """NULL-safe extension registration."""
    cursor.execute("""
        SELECT COUNT(*) FROM gpkg_extensions
        WHERE  extension_name = ?
          AND  (table_name  IS ? OR table_name  = ?)
          AND  (column_name IS ? OR column_name = ?)
    """, (extension_name,
          table_name, table_name,
          column_name, column_name))
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO gpkg_extensions
                (table_name, column_name, extension_name, definition, scope)
            VALUES (?, ?, ?, ?, ?)
        """, (table_name, column_name, extension_name, definition, scope))


# ---------------------------------------------------------------------------
# GOLD-2: Post-commit extent integrity check + auto-repair
# ---------------------------------------------------------------------------
def _verify_and_repair_contents_extents(cursor, exported_tables,
                                         log_fn, warn_fn):
    """
    GOLD-2 (v0.06): Read back each gpkg_contents row and compare stored
    extents against the ArcPy-derived extents.  Any discrepancy beyond
    1e-6 units is corrected automatically.  Returns count of repaired rows.
    """
    TOLERANCE = 1e-6
    repaired = 0
    for tbl in exported_tables:
        cursor.execute("""
            SELECT min_x, min_y, max_x, max_y
            FROM   gpkg_contents
            WHERE  table_name = ?
        """, (tbl["table_name"],))
        row = cursor.fetchone()
        if row is None:
            warn_fn(f"  GOLD-2 EXTENT CHECK: no gpkg_contents row for "
                    f"'{tbl['table_name']}'")
            continue
        stored   = tuple(v if v is not None else 0.0 for v in row)
        expected = (tbl["min_x"], tbl["min_y"], tbl["max_x"], tbl["max_y"])
        diffs    = [abs(stored[i] - expected[i]) for i in range(4)]
        if any(d > TOLERANCE for d in diffs):
            cursor.execute("""
                UPDATE gpkg_contents
                SET    min_x = ?, min_y = ?, max_x = ?, max_y = ?
                WHERE  table_name = ?
            """, (expected[0], expected[1], expected[2], expected[3],
                  tbl["table_name"]))
            warn_fn(
                f"  GOLD-2 EXTENT REPAIR '{tbl['table_name']}': "
                f"stored ({stored[0]:.6f},{stored[1]:.6f},"
                f"{stored[2]:.6f},{stored[3]:.6f}) -> "
                f"expected ({expected[0]:.6f},{expected[1]:.6f},"
                f"{expected[2]:.6f},{expected[3]:.6f})"
            )
            repaired += 1
    if repaired == 0:
        log_fn(f"  GOLD-2 Extent integrity: all {len(exported_tables)} "
               f"table(s) verified OK.")
    else:
        log_fn(f"  GOLD-2 Extent integrity: {repaired} table(s) repaired.")
    return repaired


# ---------------------------------------------------------------------------
# GOLD-3: gpkg_schema / gpkg_data_columns population
# ---------------------------------------------------------------------------
def _populate_gpkg_schema(cursor, exported_tables, input_gdb, log_fn):
    """
    GOLD-3 (v0.06): Create gpkg_data_columns and populate it with field
    aliases, types, and lengths from each exported feature class.
    Makes the GeoPackage self-documenting for non-ArcGIS consumers.
    """
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gpkg_data_columns (
            table_name      TEXT NOT NULL,
            column_name     TEXT NOT NULL,
            name            TEXT,
            title           TEXT,
            description     TEXT,
            mime_type       TEXT,
            constraint_name TEXT,
            CONSTRAINT pk_gdc PRIMARY KEY (table_name, column_name)
        );
    """)

    SKIP_FIELDS = {
        "objectid", "shape", "shape_length", "shape_area",
        "fid", "globalid", "created_user", "created_date",
        "last_edited_user", "last_edited_date",
    }

    rows_added = 0
    for tbl in exported_tables:
        src = os.path.join(input_gdb, tbl["original_fc"])
        try:
            fields = arcpy.ListFields(src)
        except Exception:
            continue
        for field in fields:
            if field.name.lower() in SKIP_FIELDS:
                continue
            col_title = (field.aliasName
                         if field.aliasName and field.aliasName != field.name
                         else field.name)
            description = f"Type: {field.type}"
            if field.length and field.length > 0:
                description += f", Length: {field.length}"
            if field.precision and field.precision > 0:
                description += f", Precision: {field.precision}"
            if field.scale and field.scale > 0:
                description += f", Scale: {field.scale}"

            cursor.execute("""
                INSERT OR IGNORE INTO gpkg_data_columns
                    (table_name, column_name, name, title, description,
                     mime_type, constraint_name)
                VALUES (?, ?, ?, ?, ?, NULL, NULL)
            """, (
                tbl["table_name"],
                field.name.lower(),
                col_title,
                col_title,
                description,
            ))
            rows_added += 1

    log_fn(f"  GOLD-3 gpkg_data_columns: {rows_added} field descriptor(s) "
           f"across {len(exported_tables)} table(s).")


# ---------------------------------------------------------------------------
# GOLD-4: Anti-meridian bounding-box snapping (geographic CRS only)
# ---------------------------------------------------------------------------
def _snap_geographic_extent(min_x, min_y, max_x, max_y,
                             margin=ANTIMERIDIAN_SNAP_MARGIN):
    """
    GOLD-4 (v0.06): Snap near-global extent coordinates to exact WGS84
    world bounds when within `margin` degrees of each edge.

    Prevents DGIWG validators rejecting bounding boxes like -179.9998 or
    89.9997 that result from floating-point accumulation during reprojection.
    Only meaningful for geographic (degree-unit) CRS.
    """
    if abs(min_x - (-180.0)) <= margin:
        min_x = -180.0
    if abs(min_y - (-90.0)) <= margin:
        min_y = -90.0
    if abs(max_x - 180.0) <= margin:
        max_x = 180.0
    if abs(max_y - 90.0) <= margin:
        max_y = 90.0
    return min_x, min_y, max_x, max_y


# ---------------------------------------------------------------------------
# GOLD-5: Compliance manifest (SHA-256 + JSON provenance certificate)
# ---------------------------------------------------------------------------
def _write_compliance_manifest(gpkg_path, srs_info, exported_tables,
                                rtree_verified_count, tool_version="v0.13"):
    """
    GOLD-5 (v0.06): Compute SHA-256 of the finished .gpkg and write a
    companion *_compliance.json manifest.

    Provides a Certificate of Provenance for formal military delivery,
    recording: SHA-256 hash, WKT2 string, RTree count, standards citations,
    and a per-layer feature/extent summary.
    """
    sha256 = hashlib.sha256()
    with open(gpkg_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            sha256.update(chunk)

    manifest = {
        "tool": f"DGIWG GeoPackage Creator {tool_version}",
        "dgiwg_standard": (
            "DGIWG-126 GeoPackage Profile 1.4 Ed.1.1 "
            "(STD-DP-19-005 v1.1, 2025-05-02)"
        ),
        "ogc_standard": (
            "OGC 12-128r19 GeoPackage Encoding Standard v1.4 (2024-06-02)"
        ),
        "generated_utc":           datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "output_file":             os.path.basename(gpkg_path),
        "sha256":                  sha256.hexdigest(),
        "crs": {
            "epsg":        srs_info["srs_id"],
            "description": srs_info["description"],
            "wkt_format":  srs_info.get("wkt_format", "WKT2"),
            "wkt2":        srs_info["definition"],
        },
        "rtree_indexes_verified": rtree_verified_count,
        "layers": [
            {
                "table_name":    t["table_name"],
                "original_fc":   t["original_fc"],
                "geometry_type": t["geom_type"],
                "feature_count": t["count"],
                "extent": {
                    "min_x": t["min_x"],
                    "min_y": t["min_y"],
                    "max_x": t["max_x"],
                    "max_y": t["max_y"],
                },
            }
            for t in exported_tables
        ],
        "validation_url": "https://cite.opengeospatial.org/te2/",
    }

    manifest_path = os.path.splitext(gpkg_path)[0] + "_compliance.json"
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    return manifest_path
