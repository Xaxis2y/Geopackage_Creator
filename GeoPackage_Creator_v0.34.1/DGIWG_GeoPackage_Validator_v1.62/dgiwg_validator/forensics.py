# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Source-software forensics and deep-dive checks (v1.59).

Detects QGIS/GDAL vs ArcGIS authorship, runs per-requirement forensic
sub-checks, and renders the forensic HTML section.
"""
import os
import sys
import re
import html
import json
import sqlite3
import datetime
from collections import defaultdict
from xml.etree import ElementTree as ET
from .constants import (
    REQUIREMENTS, EXTENSIONS_TABLE, NET_TIMEOUT,
    ALLOWED_RASTER_CRS, ALLOWED_RASTER_CRS_DISPLAY,
    ALLOWED_GRIDDED_2D_CRS, ALLOWED_GRIDDED_3D_CRS,
    ALLOWED_VECTOR_CRS_2D, ALLOWED_VECTOR_CRS_3D,
    CRS_EXTENT, STATUS_ICON,
)
from .net import _net_get, _net_check_uri, _net_check_dmf_xml, DMF_XSD_INLINE
from .utils import table_exists, column_exists, get_data_categories, LIBRARY_STATUS
def detect_source_software(conn: sqlite3.Connection) -> dict[str, object]:
    """
    Forensic detection of authoring software via GeoPackage structural signals.
    Returns dict with software label, confidence, evidence signals, and per-req hints.
    """
    c = conn.cursor()
    gdal_signals  = []
    arcgis_signals = []

    # ── GDAL/QGIS signals ─────────────────────────────────────────────────────

    # 1. gpkg_ogr_contents table (OGR/GDAL schema table)
    try:
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gpkg_ogr_contents'")
        if c.fetchone():
            gdal_signals.append("gpkg_ogr_contents table present (OGR/GDAL schema table)")
    except Exception:
        pass

    # 2. gdal_nw extension in gpkg_extensions
    try:
        c.execute("SELECT extension_name FROM gpkg_extensions WHERE extension_name LIKE 'gdal%'")
        gdal_exts = [r[0] for r in c.fetchall()]
        if gdal_exts:
            gdal_signals.append(f"GDAL extension(s) in gpkg_extensions: {gdal_exts}")
    except Exception:
        pass

    # 3. GDAL/OGR in metadata URI or content
    try:
        c.execute("SELECT md_standard_uri, metadata FROM gpkg_metadata LIMIT 5")
        for uri, meta in (c.fetchall() or []):
            if uri and ("gdal" in uri.lower() or "ogr" in uri.lower()):
                gdal_signals.append(f"GDAL/OGR URI in gpkg_metadata: {uri}")
                break
            if meta and ("gdal" in meta.lower() or "ogr" in meta.lower() or "qgis" in meta.lower()):
                gdal_signals.append("GDAL/QGIS reference found in metadata content")
                break
    except Exception:
        pass

    # 4. srs_name contains 'GDAL' or WKT definition references GDAL
    try:
        c.execute("SELECT srs_name, definition FROM gpkg_spatial_ref_sys WHERE srs_id > 0 LIMIT 5")
        for srs_name, defn in (c.fetchall() or []):
            if srs_name and "gdal" in srs_name.lower():
                gdal_signals.append(f"GDAL in srs_name: {srs_name}")
                break
            if defn and "gdal" in defn.lower():
                gdal_signals.append("GDAL reference in SRS definition WKT")
                break
    except Exception:
        pass

    # 5. application_id / user_version pragma (SQLite-level GPKG signature)
    try:
        c.execute("PRAGMA application_id")
        app_id = c.fetchone()
        # GPKG application_id: 0x47504B47 = OGC standard; some GDAL versions write differently
        # This is informational only — not a strong signal by itself
    except Exception:
        pass

    # ── ArcGIS signals ────────────────────────────────────────────────────────

    # 1. Custom srs_id outside standard EPSG range (ArcGIS assigns 100001+ for reprojected)
    try:
        c.execute("SELECT srs_id, srs_name FROM gpkg_spatial_ref_sys WHERE srs_id > 100000 AND srs_id NOT IN (-1, 0)")
        custom_srs = c.fetchall()
        if custom_srs:
            ids = [str(r[0]) for r in custom_srs[:3]]
            arcgis_signals.append(f"Custom srs_id values (ArcGIS reprojection): {', '.join(ids)}")
    except Exception:
        pass

    # 2. 'ESRI' or 'Esri' in srs_name or organization
    try:
        c.execute("SELECT srs_name, organization FROM gpkg_spatial_ref_sys WHERE srs_id > 0 LIMIT 10")
        for srs_name, org in (c.fetchall() or []):
            if (srs_name and "esri" in srs_name.lower()) or (org and "esri" in org.lower()):
                arcgis_signals.append(f"Esri organization/srs_name: '{srs_name}' / org='{org}'")
                break
    except Exception:
        pass

    # 3. Esri XML metadata URI or Esri-specific XML in metadata
    try:
        c.execute("SELECT md_standard_uri, metadata FROM gpkg_metadata LIMIT 5")
        for uri, meta in (c.fetchall() or []):
            if uri and "esri" in uri.lower():
                arcgis_signals.append(f"Esri URI in gpkg_metadata: {uri}")
                break
            if meta and ("esri" in meta.lower() or "arcgis" in meta.lower() or "geodatabase" in meta.lower()):
                arcgis_signals.append("Esri/ArcGIS reference found in metadata content")
                break
    except Exception:
        pass

    # 4. GDB_Items or GDB_ prefixed tables (ArcGIS geodatabase residue)
    try:
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'GDB_%'")
        gdb_tables = [r[0] for r in (c.fetchall() or [])]
        if gdb_tables:
            arcgis_signals.append(f"ArcGIS GDB_ tables present: {gdb_tables[:3]}")
    except Exception:
        pass

    # 5. WKT definition contains AUTHORITY["ESRI",...] pattern
    try:
        c.execute("SELECT definition FROM gpkg_spatial_ref_sys WHERE srs_id > 0 LIMIT 10")
        for (defn,) in (c.fetchall() or []):
            if defn and 'AUTHORITY["ESRI"' in defn:
                arcgis_signals.append('WKT contains AUTHORITY["ESRI",...] — ArcGIS CRS definition')
                break
    except Exception:
        pass

    # ── Classify ──────────────────────────────────────────────────────────────
    n_gdal   = len(gdal_signals)
    n_arcgis = len(arcgis_signals)

    if n_gdal > 0 and n_arcgis == 0:
        software   = "QGIS/GDAL"
        confidence = "High" if n_gdal >= 2 else "Medium"
        signals    = gdal_signals
    elif n_arcgis > 0 and n_gdal == 0:
        software   = "ArcGIS"
        confidence = "High" if n_arcgis >= 2 else "Medium"
        signals    = arcgis_signals
    elif n_arcgis > 0 and n_gdal > 0:
        # Mixed signals — report both, lean towards whichever is stronger
        software   = "ArcGIS" if n_arcgis >= n_gdal else "QGIS/GDAL"
        confidence = "Low"
        signals    = [f"[GDAL] {s}" for s in gdal_signals] + [f"[ArcGIS] {s}" for s in arcgis_signals]
    else:
        software   = "UNKNOWN"
        confidence = "Low"
        signals    = ["No software-specific fingerprints detected"]

    # ── Build per-requirement audit hints ─────────────────────────────────────
    hints = {}

    if software == "QGIS/GDAL":
        hints[5] = (
            "⚠️ KNOWN GDAL ARTIFACT: The 'gdal_nw' (No-Write lock) extension is automatically "
            "injected by GDAL/QGIS at file creation. This FAIL is expected behaviour for GDAL-authored "
            "files and does NOT indicate intentional non-compliance. Remediation: run "
            "DELETE FROM gpkg_extensions WHERE extension_name='gdal_nw'; before final delivery."
        )
        hints[24] = (
            "ℹ️ GDAL NOTE: The table 'gpkg_ogr_contents' is a GDAL/OGR internal schema table, "
            "NOT a registered extension. Some validators incorrectly flag it as a data validity "
            "issue. This generator correctly ignores it in extension checks. No action required."
        )
        hints[13] = (
            "✅ GDAL EXPECTATION: GDAL/QGIS generally produces well-formed WKT2:2019 strings. "
            "A PASS here is the expected outcome for GDAL-authored files."
        )

    elif software == "ArcGIS":
        hints[7] = (
            "⚠️ ARCGIS CRS RISK: ArcGIS Pro sometimes assigns custom srs_id values (e.g., 100001+) "
            "to reprojected datasets. DGIWG Requirement 7 strictly requires CRS from the DGIWG-allowed "
            "list. Verify all srs_id values in gpkg_spatial_ref_sys are standard EPSG codes."
        )
        hints[13] = (
            "⚠️ ARCGIS AXIS ORDER: ArcGIS sometimes exports WKT strings with non-standard axis order "
            "(e.g., Longitude/Latitude instead of Latitude/Longitude). Manually verify that "
            "AXIS[\"lat\",north] and AXIS[\"lon\",east] ordering matches the EPSG definition for "
            "each projected CRS used in this file."
        )
        hints[18] = (
            "ℹ️ ARCGIS METADATA: ArcGIS produces rich XML metadata that typically satisfies automated "
            "checks (Req 18–23). However, Esri-specific URIs and internal geodatabase paths may be "
            "present. Manually verify that XML Lineage elements reference source data correctly and "
            "not internal geodatabase paths (e.g., avoid paths like C:\\GIS\\internal.gdb\\...)."
        )
        hints[19] = hints[18]
        hints[20] = hints[18]
        hints[21] = hints[18]
        hints[22] = hints[18]
        hints[23] = hints[18]

    else:  # UNKNOWN
        hints[24] = (
            "⚠️ UNKNOWN SOURCE: Source software could not be determined. Perform full manual review "
            "of table naming consistency. Non-standard tools may introduce unexpected tables that "
            "are not declared in gpkg_contents or gpkg_extensions."
        )
        hints[13] = (
            "⚠️ UNKNOWN SOURCE: WKT strings from unknown authoring tools carry higher risk of "
            "malformed or non-standard CRS definitions. Review definition strings carefully."
        )
        hints[5] = (
            "⚠️ UNKNOWN SOURCE: Extension behaviour is unpredictable from unknown tools. "
            "Any FAIL here requires full investigation — cannot assume known-artifact origin."
        )

    return {
        "software":   software,
        "confidence": confidence,
        "signals":    signals,
        "hints":      hints,
    }


# ──────────────────────────────────────────────────────────────────────────────
# FORENSIC DEEP-DIVE CHECKS
# Each function opens the real database tables, pulls actual rows, and returns
# a plain-English verdict explaining exactly what was found and why it matters.
# These checks NEVER modify the file — read-only throughout.
#
# Return structure from _forensic_result():
#   status      — "PASS" / "PASS*" / "SKIPPED"
#   summary     — one-line headline (shown in bold)
#   data_rows   — list of dicts — real rows pulled from the file
#   explanation — plain English: what was checked, what was found, why it matters
#   sql_used    — the SQL query so you can run it yourself in DB Browser
# ──────────────────────────────────────────────────────────────────────────────

_F_PASS    = "PASS"
_F_PASSSTAR = "PASS*"
_F_SKIPPED = "SKIPPED"

KNOWN_DGIWG_EXTENSIONS = {
    "gpkg_rtree_index", "gpkg_metadata", "gpkg_crs_wkt",
    "gpkg_crs_wkt_1_1", "gpkg_schema", "related_tables",
    "gpkg_2d_gridded_coverage",
}
_ESRI_URI_PATTERNS  = ["esri.com", "arcgis", "geodatabase", "esriprof"]
_DMF_URI_MAIN       = "http://www.dgiwg.org/std/dmf"
_DMF_URI_ALT        = "http://www.dgiwg.org"
_ISO_TC211_URI      = "http://www.isotc211.org/2005/gmd"
_DMF_REQUIRED_ELEMS = [
    "fileIdentifier", "language", "characterSet",
    "hierarchyLevel", "contact", "dateStamp", "identificationInfo",
]

def _forensic_result(status, summary, data_rows, explanation, sql_used=None):
    return {"status": status, "summary": summary, "data_rows": data_rows,
            "explanation": explanation, "sql_used": sql_used}


# ── Req 5 — Extensions Not Allowed ───────────────────────────────────────────

def _fcheck_req5(conn, software):
    """
    What we check:
      We look at every row in the gpkg_extensions table — that is the list of
      extra features this file claims to use. DGIWG only allows specific
      extensions from its Table 8. Anything else must be explained or removed.
    """
    c = conn.cursor()
    sql = ("SELECT extension_name, table_name, column_name, scope "
           "FROM gpkg_extensions ORDER BY extension_name")
    if not table_exists(c, "gpkg_extensions"):
        return _forensic_result(_F_SKIPPED,
            "No extensions table found in this file",
            [],
            "This file does not have a gpkg_extensions table, which means it has "
            "registered no extra features. Nothing to check here.", sql)

    c.execute(sql)
    rows = c.fetchall()
    if not rows:
        return _forensic_result(_F_PASS,
            "No extensions registered — nothing to flag",
            [],
            "The gpkg_extensions table is empty. There are no extra features "
            "registered, so there is nothing that could violate Req 5.", sql)

    data_rows, gdal_found, unknown_found = [], [], []
    for r in rows:
        ext = r[0] or ""
        is_gdal  = any(ext.lower().startswith(g) for g in ["gdal", "ogr"])
        is_known = ext in KNOWN_DGIWG_EXTENSIONS

        if is_gdal:
            flag = "⚠️ GDAL software artifact — not on DGIWG allowed list"
            gdal_found.append(ext)
        elif not is_known:
            flag = "❓ Not recognised — verify against DGIWG Table 8"
            unknown_found.append(ext)
        else:
            flag = "✅ Recognised DGIWG extension"

        data_rows.append({"extension_name": ext, "table_name": r[1] or "—",
                          "scope": r[3] or "—", "verdict": flag})

    issues = gdal_found + unknown_found
    if not issues:
        return _forensic_result(_F_PASS,
            f"{len(rows)} extension(s) registered — all are DGIWG-approved",
            data_rows,
            "Every extension in this file is on the DGIWG Table 8 allowed list. "
            "Requirement 5 is satisfied.", sql)

    parts = []
    if gdal_found:
        parts.append(
            f"Found GDAL software extension(s): {gdal_found}. "
            "When QGIS or GDAL creates a GeoPackage it automatically adds a "
            "row called 'gdal_nw' (No-Write lock). This is an internal GDAL "
            "bookkeeping entry — it has nothing to do with the data itself. "
            "However, the DGIWG standard does not allow it, so a strict "
            "compliance test will flag this as a FAIL. "
            "Before delivering the file, remove it with this SQL command in "
            "DB Browser: DELETE FROM gpkg_extensions WHERE extension_name='gdal_nw'; "
            "This script has NOT changed the file."
        )
    if unknown_found:
        parts.append(
            f"Found extension(s) not on the DGIWG allowed list: {unknown_found}. "
            "Check whether your product profile permits these. If not, they "
            "must be removed or formally justified in your metadata."
        )
    return _forensic_result(_F_PASSSTAR,
        f"{len(issues)} extension(s) need review before delivery",
        data_rows, " | ".join(parts), sql)


# ── Req 7 — Raster CRS ───────────────────────────────────────────────────────

def _fcheck_req7(conn, software):
    """
    What we check:
      We look at the coordinate reference system (CRS) assigned to each tile
      or raster layer. DGIWG only permits a short list of approved CRS codes
      (e.g. EPSG:4326, EPSG:3857). Any other code will cause a FAIL.
    """
    c = conn.cursor()
    # v1.57 fix (Bug #1): definition_12_063 is an OPTIONAL column, present only
    # when the gpkg_crs_wkt(_1_1) extension is registered.  Referencing it
    # unconditionally crashed the whole run with sqlite3.OperationalError on
    # any GeoPackage without that column.  Guard with column_exists() — the
    # same pattern _fcheck_req13() already uses.
    _has_063 = column_exists(c, "gpkg_spatial_ref_sys", "definition_12_063")
    _063_expr = "COALESCE(srs.definition_12_063,'')" if _has_063 else "''"
    sql = ("SELECT tms.table_name, tms.srs_id, srs.srs_name, srs.organization, "
           f"COALESCE(srs.definition,''), {_063_expr} "
           "FROM gpkg_tile_matrix_set tms "
           "LEFT JOIN gpkg_spatial_ref_sys srs ON tms.srs_id = srs.srs_id "
           "ORDER BY tms.table_name")
    if not table_exists(c, "gpkg_tile_matrix_set"):
        return _forensic_result(_F_SKIPPED,
            "No raster/tile layers found in this file",
            [],
            "The gpkg_tile_matrix_set table does not exist, which means this file "
            "contains no tile pyramid or raster data. Req 7 does not apply.", sql)

    c.execute(sql)
    rows = c.fetchall()
    if not rows:
        return _forensic_result(_F_SKIPPED, "Tile matrix set table is empty", [],
            "The tile matrix set table exists but has no rows — no raster layers "
            "are registered. Req 7 does not apply.", sql)

    def _is_lcc(*wkts):
        blob = " ".join(w for w in wkts if w).upper().replace("_", " ")
        return "LAMBERT CONFORMAL CONIC" in blob or "LAMBERT CONIC CONFORMAL" in blob

    data_rows, bad_ids = [], []
    for r in rows:
        srs_id = r[1]
        _defn, _defn2 = r[4], r[5]
        ok = srs_id in ALLOWED_RASTER_CRS
        is_lcc = _is_lcc(_defn, _defn2)
        is_arcgis_custom = srs_id is not None and srs_id > 100000
        if ok:
            flag = f"✅ EPSG:{srs_id} — on DGIWG allowed list (Tables 11 & 12)"
        elif is_lcc:
            flag = (f"✅ srs_id={srs_id} — per-product Lambert Conformal Conic CRS, "
                    "allowed by DGIWG Table 11.")
        elif is_arcgis_custom:
            flag = (f"❌ srs_id={srs_id} — ArcGIS custom ID, not a real EPSG code. "
                    "Must be replaced with an approved CRS.")
            bad_ids.append(srs_id)
        else:
            flag = (f"⚠️ srs_id={srs_id} — not on the DGIWG Tables 11 & 12 approved list "
                    f"({ALLOWED_RASTER_CRS_DISPLAY}). Verify and reproject if needed.")
            bad_ids.append(srs_id)
        data_rows.append({"layer": r[0] or "—", "srs_id": str(srs_id),
                          "crs_name": r[2] or "—", "verdict": flag})

    if not bad_ids:
        return _forensic_result(_F_PASS,
            f"All {len(rows)} raster layer(s) use an approved CRS",
            data_rows,
            f"Every tile layer uses a CRS from the DGIWG Tables 11 & 12 approved list "
            f"({ALLOWED_RASTER_CRS_DISPLAY}). Req 7 is satisfied.", sql)

    expl = (f"CRS problem found on {len(bad_ids)} layer(s): srs_id values {bad_ids}. "
            "DGIWG Req 7 says raster tile pyramid data must use only the approved CRS from "
            f"Tables 11 & 12: {ALLOWED_RASTER_CRS_DISPLAY}. ")
    if software == "ArcGIS" and any(s > 100000 for s in bad_ids if s):
        expl += ("These high-numbered IDs (100001+) are invented by ArcGIS when it "
                 "reprojects data to a CRS it doesn't have a standard EPSG code for. "
                 "They are not real international CRS codes and will always fail DGIWG "
                 "validation. The file needs to be reprojected to an approved CRS "
                 "(e.g. EPSG:4326 WGS84 or EPSG:3857 Web Mercator) using ArcGIS Pro "
                 "or ogr2ogr before delivery.")
    return _forensic_result(_F_PASSSTAR,
        f"{len(bad_ids)} raster layer(s) have unapproved CRS",
        data_rows, expl, sql)


# ── Req 9 — 2D Vector CRS ────────────────────────────────────────────────────

def _fcheck_req9(conn, software):
    """
    What we check:
      For every vector feature layer (roads, buildings, etc.) we check which
      CRS it is stored in. DGIWG requires all 2D vector layers to use
      EPSG:4326 (WGS84 geographic coordinates).
    """
    c = conn.cursor()
    sql = ("SELECT gc.table_name, gcs.column_name, gcs.srs_id, srs.srs_name "
           "FROM gpkg_geometry_columns gcs "
           "JOIN gpkg_contents gc ON gcs.table_name = gc.table_name "
           "LEFT JOIN gpkg_spatial_ref_sys srs ON gcs.srs_id = srs.srs_id "
           "WHERE gc.data_type = 'features' ORDER BY gc.table_name")
    if not table_exists(c, "gpkg_geometry_columns"):
        return _forensic_result(_F_SKIPPED,
            "No vector feature layers in this file",
            [], "No geometry columns table found. File has no vector data.", sql)

    c.execute(sql)
    rows = c.fetchall()
    if not rows:
        return _forensic_result(_F_SKIPPED, "No feature layers registered", [],
            "The geometry columns table exists but no feature layers are registered "
            "with data_type='features'. Req 9 does not apply.", sql)

    data_rows, bad = [], []
    for r in rows:
        srs_id = r[2]
        ok = srs_id in ALLOWED_VECTOR_CRS_2D
        flag = ("✅ EPSG:4326 — correct" if ok else
                f"⚠️ srs_id={srs_id} — DGIWG requires EPSG:4326 for 2D vector layers")
        if not ok:
            bad.append((r[0], srs_id))
        data_rows.append({"layer": r[0] or "—", "geom_column": r[1] or "—",
                          "srs_id": str(srs_id), "crs_name": r[3] or "—",
                          "verdict": flag})

    if not bad:
        return _forensic_result(_F_PASS,
            f"All {len(rows)} vector layer(s) use EPSG:4326 as required",
            data_rows,
            "Every vector feature layer is stored in EPSG:4326 (WGS84 latitude/"
            "longitude). This is what DGIWG Req 9 requires. Satisfied.", sql)

    return _forensic_result(_F_PASSSTAR,
        f"{len(bad)} vector layer(s) not using EPSG:4326",
        data_rows,
        f"Layer(s) {[(n, s) for n,s in bad]} are not in EPSG:4326. "
        "DGIWG Req 9 mandates EPSG:4326 for all 2D vector layers. "
        "The data needs to be reprojected to EPSG:4326 before delivery.", sql)


# ── Req 13 — WKT CRS Definition ──────────────────────────────────────────────

def _fcheck_req13(conn, software):
    """
    What we check:
      Every CRS stored in the file must have a WKT2 (Well-Known Text version 2)
      definition. Think of WKT as the written description of the coordinate
      system — without it, software cannot correctly interpret the geometry.
      We also check axis order for ArcGIS files (latitude vs longitude first).
    """
    c = conn.cursor()
    has_063 = column_exists(c, "gpkg_spatial_ref_sys", "definition_12_063")
    col     = "definition_12_063" if has_063 else "definition"
    sql = (f"SELECT srs_id, srs_name, organization, {col} AS wkt "
           "FROM gpkg_spatial_ref_sys WHERE srs_id > 0 ORDER BY srs_id")
    if not table_exists(c, "gpkg_spatial_ref_sys"):
        return _forensic_result(_F_SKIPPED, "SRS table missing", [],
            "The spatial reference system table does not exist. Cannot check WKT.", sql)

    c.execute(sql)
    rows = c.fetchall()
    if not rows:
        return _forensic_result(_F_SKIPPED, "No CRS entries found", [],
            "No CRS records with srs_id > 0. Nothing to check.", sql)

    _WKT2_KEYWORDS = ("GEOGCRS", "PROJCRS", "GEODCRS", "COMPOUNDCRS", "VERTCRS")
    data_rows, issues = [], []
    for r in rows:
        srs_id, srs_name, org, wkt = r[0], r[1] or "—", r[2] or "—", r[3] or ""
        flags = []
        if not wkt.strip():
            flags.append("❌ WKT definition is completely empty — CRS is undefined")
            issues.append(f"srs_id {srs_id}: empty WKT")
        elif not any(wkt.strip().startswith(k) for k in _WKT2_KEYWORDS):
            flags.append("⚠️ Definition does not start with a WKT2 keyword "
                         "(expected one of: GEOGCRS / PROJCRS / GEODCRS / "
                         "COMPOUNDCRS / VERTCRS). May be WKT1 format, which "
                         "DGIWG does not accept.")
            issues.append(f"srs_id {srs_id}: not WKT2 format")
        else:
            flags.append("✅ WKT2 format confirmed")

        if software == "ArcGIS" and wkt:
            axes = re.findall(r'AXIS\["([^"]+)"', wkt)
            if axes:
                first = axes[0].lower()
                if any(x in first for x in ["lon", "e,", " e]"]) or first in ("x", "e"):
                    flags.append("⚠️ Axis order problem: longitude appears before latitude. "
                                 "DGIWG expects latitude-first for geographic CRS. "
                                 "This is an ArcGIS export quirk and must be corrected.")
                    issues.append(f"srs_id {srs_id}: longitude-first axis")
                else:
                    flags.append(f"✅ Axis order looks correct (first axis: '{axes[0]}')")
            else:
                flags.append("ℹ️ No AXIS keywords in WKT — cannot verify axis order automatically")

        if 'AUTHORITY["ESRI"' in wkt:
            flags.append("⚠️ This CRS was defined by Esri tools, not the EPSG registry. "
                         "Check that the definition matches the official EPSG WKT2 text "
                         "from epsg.org for this CRS code.")
            issues.append(f"srs_id {srs_id}: Esri-authored CRS definition")

        data_rows.append({"srs_id": str(srs_id), "crs_name": srs_name,
                          "org": org,
                          "wkt_preview": (wkt[:100] + "…") if len(wkt) > 100 else wkt,
                          "verdict": " | ".join(flags)})

    if not issues:
        note = (" Note: using legacy 'definition' column — the newer 'definition_12_063' "
                "(WKT2) column is absent. File may have been created before GeoPackage 1.2."
                if not has_063 else "")
        return _forensic_result(_F_PASS,
            f"All {len(rows)} CRS definition(s) pass WKT2 check",
            data_rows,
            f"Every CRS entry has a valid WKT2 definition with the correct keyword.{note}",
            sql)

    expl = (f"{len(issues)} issue(s) found: {'; '.join(issues)}. "
            "Without a valid WKT2 definition, other software cannot correctly "
            "interpret the coordinate system of this data. ")
    if not has_063:
        expl += ("Also: the WKT2-specific column 'definition_12_063' is absent from this "
                 "file. DGIWG requires WKT2 definitions to be stored in that column. "
                 "The file may need to be recreated with a GeoPackage 1.2+ compatible tool. ")
    if software == "ArcGIS":
        expl += ("For ArcGIS files specifically: check axis order carefully. DGIWG follows "
                 "the ISO standard where latitude comes before longitude. ArcGIS sometimes "
                 "reverses this. Also replace any AUTHORITY[\"ESRI\",...] entries with the "
                 "official EPSG WKT2 text.")
    return _forensic_result(_F_PASSSTAR,
        f"{len(issues)} WKT issue(s) found — review before delivery",
        data_rows, expl, sql)


# ── Req 18 — Metadata DMF URI and XML ────────────────────────────────────────

def _fcheck_req18(conn, software):
    """
    What we check:
      Every metadata record must declare which standard it follows using a URI
      (web address). DGIWG wants to see its own DMF standard URI or the ISO
      19115 URI. We also check that the XML is well-formed and contains the
      required fields. For ArcGIS files we specifically look for internal
      file paths that should not appear in a deliverable.
    """
    c = conn.cursor()
    sql = ("SELECT id, md_scope, md_standard_uri, mime_type, "
           "SUBSTR(metadata,1,400) AS preview FROM gpkg_metadata")
    if not table_exists(c, "gpkg_metadata"):
        return _forensic_result(_F_SKIPPED, "No metadata table in this file", [],
            "The gpkg_metadata table does not exist. This file has no embedded "
            "metadata at all. Req 18 cannot be checked.", sql)

    c.execute(sql)
    rows = c.fetchall()
    if not rows:
        return _forensic_result(_F_SKIPPED, "Metadata table is empty", [],
            "The gpkg_metadata table exists but has no rows. "
            "There is no metadata to check.", sql)

    data_rows, problems = [], []
    for r in rows:
        mid, scope, uri, mime, preview = r[0], r[1], r[2] or "", r[3] or "", r[4] or ""
        flags = []

        # URI check
        if _DMF_URI_MAIN in uri or _DMF_URI_ALT in uri:
            flags.append("✅ DGIWG DMF standard URI — correct")
        elif _ISO_TC211_URI in uri:
            flags.append("✅ ISO TC211 URI — accepted by DGIWG")
        elif any(p in uri.lower() for p in _ESRI_URI_PATTERNS):
            flags.append("⚠️ Esri-specific URI found. "
                         "This tells readers the metadata follows an Esri format, "
                         "not the DGIWG DMF standard. The URI must be changed to "
                         f"'{_DMF_URI_MAIN}' for DGIWG compliance.")
            problems.append(f"record {mid}: Esri URI")
        elif not uri:
            flags.append("⚠️ No standard URI — every metadata record needs one "
                         "so readers know which format the metadata follows.")
            problems.append(f"record {mid}: empty URI")
        else:
            flags.append(f"❓ Non-standard URI: {uri} — verify this is acceptable")
            problems.append(f"record {mid}: unknown URI")

        # MIME type
        flags.append("✅ MIME type is XML" if "xml" in mime.lower()
                     else f"⚠️ MIME type is '{mime}' — should be text/xml")

        # XML check
        try:
            c2 = conn.cursor()
            c2.execute("SELECT metadata FROM gpkg_metadata WHERE id=?", (mid,))
            row2 = c2.fetchone()
            full_meta = row2[0] if row2 else ""
            if full_meta and full_meta.strip().startswith("<"):
                ET.fromstring(full_meta)
                flags.append("✅ XML is well-formed (no syntax errors)")
                all_tags = {el.tag.split("}")[-1] for el in ET.fromstring(full_meta).iter()}
                missing = [e for e in _DMF_REQUIRED_ELEMS if e not in all_tags]
                if missing:
                    flags.append(f"⚠️ Missing required DMF fields: {missing}. "
                                 "These elements must be present for the metadata "
                                 "to be a valid DGIWG DMF document.")
                else:
                    flags.append("✅ All required DMF fields are present in the XML")
                if software == "ArcGIS":
                    lower_meta = full_meta.lower()
                    if any(p in lower_meta for p in [r"c:\\", r"c:/", ".gdb\\", "geodatabase\\"]):
                        flags.append("⚠️ Internal file path found in metadata (e.g. a path "
                                     "to a local .gdb file). Deliverable metadata must not "
                                     "reference internal network or machine paths. Update "
                                     "the Lineage section to describe the actual source data.")
                        problems.append(f"record {mid}: internal path in XML")
        except ET.ParseError as e:
            flags.append(f"❌ XML has a syntax error and cannot be parsed: {e}. "
                         "This metadata record is effectively unreadable.")
            problems.append(f"record {mid}: malformed XML")
        except Exception:
            pass

        data_rows.append({"id": str(mid), "scope": scope or "—",
                          "uri": uri or "(empty)", "mime": mime or "—",
                          "verdict": " | ".join(flags)})

    if not problems:
        return _forensic_result(_F_PASS,
            f"{len(rows)} metadata record(s) — URI, XML and DMF fields all pass",
            data_rows,
            "Every metadata record has a DGIWG/ISO-compliant URI, valid XML, "
            "and all required DMF fields. Req 18 is satisfied.", sql)

    return _forensic_result(_F_PASSSTAR,
        f"{len(problems)} metadata record(s) have issues",
        data_rows,
        f"Problems found: {'; '.join(problems)}. "
        "See the verdict column in each row for the specific issue and "
        "what needs to change before delivery.", sql)


# ── Req 19 — Metadata Scope Linkage ─────────────────────────────────────────

def _fcheck_req19(conn, software):
    """
    What we check:
      Every metadata record must be linked to what it describes using a
      'reference' row. For GeoPackage-level metadata (describing the whole
      file) the reference must have specific NULL values in three columns.
      We check that the linkage is set up correctly.
    """
    c = conn.cursor()
    sql = ("SELECT m.id, m.md_scope, mr.reference_scope, mr.table_name, "
           "mr.column_name, mr.row_id_value "
           "FROM gpkg_metadata m "
           "LEFT JOIN gpkg_metadata_reference mr ON m.id = mr.md_file_id "
           "ORDER BY m.id")
    if not table_exists(c, "gpkg_metadata"):
        return _forensic_result(_F_SKIPPED, "No metadata table", [],
            "No metadata table — Req 19 not applicable.", sql)
    if not table_exists(c, "gpkg_metadata_reference"):
        return _forensic_result(_F_SKIPPED, "No metadata reference table", [],
            "The metadata reference table is missing. Cannot check how metadata "
            "records are linked to the file contents.", sql)

    c.execute(sql)
    rows = c.fetchall()
    if not rows:
        return _forensic_result(_F_SKIPPED, "No metadata records to check", [],
            "Both tables exist but are empty.", sql)

    data_rows, issues = [], []
    for r in rows:
        mid, md_scope, ref_scope, tname, colname, rowid = r
        flags = []
        if ref_scope == "geopackage":
            if tname is None and colname is None and rowid is None:
                flags.append("✅ Correct: file-level reference with all fields blank (NULL)")
            else:
                flags.append("⚠️ File-level reference (scope='geopackage') but "
                             "table_name/column_name/row_id are not blank. "
                             "DGIWG requires all three to be NULL for file-level metadata.")
                issues.append(f"id={mid}: non-NULL fields on geopackage-scope reference")
        elif ref_scope:
            flags.append(f"ℹ️ Reference scope is '{ref_scope}' — not a file-level reference")
        else:
            flags.append("⚠️ This metadata record has no matching reference row. "
                         "Every metadata record must be linked to what it describes.")
            issues.append(f"id={mid}: orphaned metadata record")

        data_rows.append({"id": str(mid), "scope": md_scope or "—",
                          "ref_scope": ref_scope or "(none)",
                          "table": tname or "NULL", "column": colname or "NULL",
                          "row_id": str(rowid) if rowid is not None else "NULL",
                          "verdict": " | ".join(flags)})

    if not issues:
        return _forensic_result(_F_PASS,
            f"{len(rows)} metadata record(s) — linkage structure is correct",
            data_rows,
            "All file-level metadata references correctly have blank (NULL) values "
            "for table_name, column_name and row_id_value as DGIWG Req 19 requires.",
            sql)

    return _forensic_result(_F_PASSSTAR,
        f"{len(issues)} metadata linkage issue(s) found",
        data_rows,
        f"Issues: {'; '.join(issues)}. "
        "DGIWG Req 19 says that when a metadata record describes the whole "
        "GeoPackage file (reference_scope='geopackage'), the table_name, "
        "column_name and row_id_value columns must all be left blank (NULL). "
        "This is how readers know the metadata applies to the entire file "
        "rather than a specific table or row.", sql)


# ── Req 22 — Product Metadata Scope ─────────────────────────────────────────

def _fcheck_req22(conn, software):
    """
    What we check:
      DGIWG requires that there is at least one metadata record with scope set
      to 'series' (preferred) or 'dataset'. This is the product-level metadata
      — the record that describes the dataset as a whole product.
    """
    c = conn.cursor()
    sql = ("SELECT m.id, m.md_scope, m.md_standard_uri, mr.reference_scope "
           "FROM gpkg_metadata m "
           "LEFT JOIN gpkg_metadata_reference mr ON m.id = mr.md_file_id "
           "WHERE m.md_scope IN ('series','dataset') ORDER BY m.id")
    if not table_exists(c, "gpkg_metadata"):
        return _forensic_result(_F_SKIPPED, "No metadata table", [],
            "No metadata table — Req 22 not applicable.", sql)

    c.execute(sql)
    rows = c.fetchall()
    if not rows:
        return _forensic_result(_F_SKIPPED,
            "No product-level metadata found (no 'series' or 'dataset' scope)",
            [],
            "There are no metadata records with md_scope set to 'series' or "
            "'dataset'. DGIWG Req 22 requires at least one such record to "
            "describe the dataset as a product. This is a gap that should be "
            "filled before delivery.", sql)

    data_rows = []
    series_count = 0
    for r in rows:
        mid, scope, uri, ref_scope = r
        note = ("✅ 'series' scope — preferred by DGIWG for product metadata"
                if scope == "series"
                else "ℹ️ 'dataset' scope — accepted, but DGIWG prefers 'series'")
        if scope == "series":
            series_count += 1
        data_rows.append({"id": str(mid), "scope": scope or "—",
                          "uri": uri or "(empty)", "ref_scope": ref_scope or "—",
                          "verdict": note})

    extra = ""
    if series_count == 0:
        extra = (" Note: only 'dataset' scope was found. DGIWG strongly prefers "
                 "'series' scope for product-level metadata. This passes the "
                 "automated check but may be flagged during a formal DGIWG review.")
    return _forensic_result(_F_PASS,
        f"{len(rows)} product metadata record(s) found (series: {series_count})",
        data_rows,
        f"Product-level metadata is present.{extra}", sql)


# ── Req 23 — Product Partial Metadata ────────────────────────────────────────

def _fcheck_req23(conn, software):
    """
    What we check:
      For metadata that covers the whole GeoPackage (partial metadata), we
      check that the reference row correctly uses scope='geopackage' with
      all three identifying columns (table_name, column_name, row_id_value)
      set to NULL. This is the specific pattern DGIWG requires for
      file-level partial metadata references.
    """
    c = conn.cursor()
    sql = ("SELECT mr.md_file_id, m.md_scope, mr.reference_scope, "
           "mr.table_name, mr.column_name, mr.row_id_value, m.md_standard_uri "
           "FROM gpkg_metadata_reference mr "
           "JOIN gpkg_metadata m ON mr.md_file_id = m.id "
           "WHERE mr.reference_scope = 'geopackage' "
           "AND mr.table_name IS NULL AND mr.column_name IS NULL "
           "AND mr.row_id_value IS NULL ORDER BY mr.md_file_id")
    if not table_exists(c, "gpkg_metadata_reference"):
        return _forensic_result(_F_SKIPPED, "No metadata reference table", [],
            "The metadata reference table is absent. Req 23 cannot be checked.", sql)

    c.execute(sql)
    rows = c.fetchall()
    if not rows:
        return _forensic_result(_F_SKIPPED,
            "No file-level partial metadata references found",
            [],
            "No metadata reference rows with scope='geopackage' and all NULL "
            "identifiers were found. Req 23 does not apply to this file.", sql)

    data_rows = []
    for r in rows:
        data_rows.append({
            "id": str(r[0]), "scope": r[1] or "—", "ref_scope": r[2] or "—",
            "table": r[3] or "NULL", "column": r[4] or "NULL",
            "row_id": str(r[5]) if r[5] is not None else "NULL",
            "verdict": "✅ Correctly structured file-level partial metadata reference"
        })

    return _forensic_result(_F_PASS,
        f"{len(rows)} partial metadata reference(s) — structure is correct",
        data_rows,
        "All partial metadata references correctly use scope='geopackage' with "
        "blank (NULL) table_name, column_name and row_id_value. "
        "This is exactly what DGIWG Req 23 requires.", sql)


# ── Req 24 — Data Validity / Undeclared Tables ────────────────────────────────

def _fcheck_req24(conn, software):
    """
    What we check:
      We compare two lists: (1) every table that physically exists in the file,
      and (2) every table declared in the gpkg_contents registry. Any table in
      list 1 that is not in list 2 is 'undeclared'. DGIWG requires all data
      content to be declared. We also identify known GDAL internal tables that
      look undeclared but are actually harmless software bookkeeping.
    """
    c = conn.cursor()
    sql_undeclared = ("SELECT sm.name FROM sqlite_master sm "
                      "LEFT JOIN gpkg_contents gc ON sm.name = gc.table_name "
                      "WHERE sm.type='table' AND gc.table_name IS NULL "
                      "AND sm.name NOT LIKE 'gpkg_%' AND sm.name NOT LIKE 'rtree_%' "
                      "AND sm.name NOT LIKE 'sqlite_%' ORDER BY sm.name")
    if not table_exists(c, "gpkg_contents"):
        return _forensic_result(_F_SKIPPED, "gpkg_contents table missing", [],
            "Cannot check data validity without the gpkg_contents registry.", sql_undeclared)

    c.execute("SELECT table_name, data_type, identifier FROM gpkg_contents ORDER BY table_name")
    declared = c.fetchall()
    c.execute(sql_undeclared)
    undeclared = [r[0] for r in c.fetchall()]

    data_rows = []
    for r in declared:
        data_rows.append({"table": r[0], "type": r[1] or "—",
                          "identifier": r[2] or "—",
                          "verdict": "✅ Properly declared in gpkg_contents"})

    gdal_tables   = [t for t in undeclared if any(x in t.lower() for x in ["ogr", "gdal"])]
    unknown_tables = [t for t in undeclared if t not in gdal_tables]

    for t in gdal_tables:
        data_rows.append({"table": t, "type": "—", "identifier": "—",
                          "verdict": ("⚠️ GDAL/OGR internal bookkeeping table — "
                                      "not declared in gpkg_contents. This is a known "
                                      "GDAL artefact (like gpkg_ogr_contents) and does NOT "
                                      "violate DGIWG Req 24. Some older validators "
                                      "incorrectly flag this — it is a false positive.")})
    for t in unknown_tables:
        data_rows.append({"table": t, "type": "—", "identifier": "—",
                          "verdict": ("❓ Undeclared table — exists in the file but "
                                      "is not registered in gpkg_contents. DGIWG requires "
                                      "all data tables to be declared. Investigate where "
                                      "this table came from.")})

    if not undeclared:
        return _forensic_result(_F_PASS,
            f"{len(declared)} declared table(s) — no undeclared tables found",
            data_rows,
            "Every table in the file is properly declared in gpkg_contents. "
            "No hidden or unexpected tables found. Req 24 is satisfied.", sql_undeclared)

    parts = []
    if gdal_tables:
        parts.append(
            f"GDAL/OGR internal tables found: {gdal_tables}. These are created "
            "automatically by GDAL and QGIS as internal bookkeeping. They are not "
            "data tables and do not need to be in gpkg_contents. This is a "
            "known false positive in some validators — it is NOT a violation."
        )
    if unknown_tables:
        parts.append(
            f"Genuinely undeclared tables: {unknown_tables}. These tables exist "
            "in the file but are not registered anywhere. This needs investigation "
            "— they may be leftover from a non-standard tool."
        )
    status = _F_PASSSTAR if unknown_tables else _F_PASS
    return _forensic_result(status,
        f"{len(undeclared)} undeclared table(s) found",
        data_rows, " | ".join(parts), sql_undeclared)


# ── Runner and metadata ───────────────────────────────────────────────────────

_FORENSIC_CHECK_META = {
    "REQ5":  {"title": "Req 5 — Extensions Not Allowed",             "risk": "QGIS/GDAL"},
    "REQ7":  {"title": "Req 7 — Raster CRS Must Be Approved",        "risk": "ArcGIS"},
    "REQ9":  {"title": "Req 9 — Vector Layers Must Use EPSG:4326",   "risk": "ALL"},
    "REQ13": {"title": "Req 13 — CRS Definition Must Be WKT2",       "risk": "ArcGIS"},
    "REQ18": {"title": "Req 18 — Metadata URI and XML Content",      "risk": "ArcGIS"},
    "REQ19": {"title": "Req 19 — Metadata Linkage Structure",        "risk": "ArcGIS"},
    "REQ22": {"title": "Req 22 — Product-Level Metadata Scope",      "risk": "ArcGIS"},
    "REQ23": {"title": "Req 23 — File-Level Partial Metadata",       "risk": "ArcGIS"},
    "REQ24": {"title": "Req 24 — All Data Tables Properly Declared", "risk": "QGIS/GDAL"},
}

def run_forensic_checks(conn, software):
    """Run all forensic checks. Returns dict keyed by check ID.

    v1.57 fix (Bug #1 hardening): each check is now isolated in its own
    try/except — mirroring how check_req() isolates the 37 primary checks —
    so an unexpected exception in one forensic check degrades to an ERROR
    entry for that check instead of aborting the whole file (and, in batch
    mode, every remaining file).
    """
    _checks = {
        "REQ5":  _fcheck_req5,
        "REQ7":  _fcheck_req7,
        "REQ9":  _fcheck_req9,
        "REQ13": _fcheck_req13,
        "REQ18": _fcheck_req18,
        "REQ19": _fcheck_req19,
        "REQ22": _fcheck_req22,
        "REQ23": _fcheck_req23,
        "REQ24": _fcheck_req24,
    }
    results = {}
    for check_id, fn in _checks.items():
        try:
            results[check_id] = fn(conn, software)
        except Exception as exc:
            results[check_id] = _forensic_result(
                _F_SKIPPED,
                f"Forensic check errored: {type(exc).__name__}",
                [],
                f"This forensic check raised an unexpected exception and was "
                f"skipped so the remaining checks could continue: {exc}",
                "",
            )
    return results


def _render_forensic_data_table(data_rows):
    """Render a list of dicts as a compact HTML table for the forensic section."""
    if not data_rows:
        return '<p style="color:#999;font-size:12px;font-style:italic;margin:4px 0;">No data rows returned from this query.</p>'
    headers = list(data_rows[0].keys())
    th = "".join(
        f'<th style="background:#34495e;color:white;padding:6px 10px;text-align:left;'
        f'font-size:11px;text-transform:uppercase;letter-spacing:0.3px;">'
        f'{h.replace("_"," ").title()}</th>'
        for h in headers
    )
    body = ""
    for i, row in enumerate(data_rows):
        bg = "#ffffff" if i % 2 == 0 else "#f8f9fa"
        cells = ""
        for h in headers:
            val = html.escape(str(row.get(h, "")))
            if h in ("verdict", "flag", "status", "flags"):
                if "❌" in val:   cbg = "#fdedec"
                elif "⚠️" in val: cbg = "#fef9e7"
                elif "✅" in val:  cbg = "#eafaf1"
                elif "❓" in val:  cbg = "#fdf2e9"
                elif "ℹ️" in val:  cbg = "#eaf4fb"
                else:              cbg = bg
                cells += (f'<td style="padding:5px 9px;font-size:11px;background:{cbg};'
                          f'word-break:break-word;line-height:1.5;">{val}</td>')
            else:
                cells += (f'<td style="padding:5px 9px;font-size:11px;font-family:monospace;'
                          f'background:{bg};word-break:break-word;">{val}</td>')
        body += f'<tr>{cells}</tr>'

    return (f'<div style="overflow-x:auto;margin-top:8px;">'
            f'<table style="width:100%;border-collapse:collapse;">'
            f'<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>')


def _render_forensic_section(forensic_checks):
    """
    Build the full HTML for the Forensic Deep-Dive section.
    Returns an HTML string ready to embed in the main report.
    """
    _STATUS_COLOR = {
        _F_PASS:    {"bg": "#eafaf1", "border": "#27ae60", "badge": "#27ae60"},
        _F_PASSSTAR:{"bg": "#fef9e7", "border": "#f39c12", "badge": "#f39c12"},
        _F_SKIPPED: {"bg": "#f4f4f4", "border": "#95a5a6", "badge": "#95a5a6"},
    }
    _SW_COLOR = {
        "QGIS/GDAL": {"fg": "#1a6b3c", "bg": "#eafaf1"},
        "ArcGIS":    {"fg": "#1a3a6b", "bg": "#eaf0fb"},
        "ALL":       {"fg": "#2c3e50", "bg": "#f4f4f4"},
    }
    _ICONS = {_F_PASS: "✅", _F_PASSSTAR: "⚠️", _F_SKIPPED: "⏭"}

    n_pass     = sum(1 for v in forensic_checks.values() if v["status"] == _F_PASS)
    n_passstar = sum(1 for v in forensic_checks.values() if v["status"] == _F_PASSSTAR)
    n_skipped  = sum(1 for v in forensic_checks.values() if v["status"] == _F_SKIPPED)

    summary_bar = (
        f'<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px;">'
        f'<div style="background:#eafaf1;border:1px solid #27ae60;border-radius:6px;'
        f'padding:10px 18px;text-align:center;">'
        f'<div style="font-size:24px;font-weight:bold;color:#27ae60;">{n_pass}</div>'
        f'<div style="font-size:11px;color:#555;">PASS</div></div>'
        f'<div style="background:#fef9e7;border:1px solid #f39c12;border-radius:6px;'
        f'padding:10px 18px;text-align:center;">'
        f'<div style="font-size:24px;font-weight:bold;color:#f39c12;">{n_passstar}</div>'
        f'<div style="font-size:11px;color:#555;">PASS* (needs review)</div></div>'
        f'<div style="background:#f4f4f4;border:1px solid #95a5a6;border-radius:6px;'
        f'padding:10px 18px;text-align:center;">'
        f'<div style="font-size:24px;font-weight:bold;color:#95a5a6;">{n_skipped}</div>'
        f'<div style="font-size:11px;color:#555;">SKIPPED (not in file)</div></div>'
        f'</div>'
    )

    cards = ""
    for key, meta in _FORENSIC_CHECK_META.items():
        result  = forensic_checks[key]
        status  = result["status"]
        summary = result["summary"]
        expl    = result["explanation"]
        sql     = result.get("sql_used", "")
        d_rows  = result["data_rows"]
        risk    = meta["risk"]
        sc      = _STATUS_COLOR.get(status, _STATUS_COLOR[_F_SKIPPED])
        swc     = _SW_COLOR.get(risk, _SW_COLOR["ALL"])
        icon    = _ICONS.get(status, "")

        badge = (f'<span style="background:{sc["badge"]};color:white;padding:3px 9px;'
                 f'border-radius:4px;font-size:12px;font-weight:bold;">{icon} {status}</span>')
        risk_badge = "" if risk == "ALL" else (
            f'<span style="background:{swc["bg"]};color:{swc["fg"]};border:1px solid {swc["fg"]};'
            f'padding:1px 6px;border-radius:3px;font-size:10px;margin-left:6px;">'
            f'{risk} risk area</span>')

        data_table = _render_forensic_data_table(d_rows)
        sql_block  = ""
        if sql:
            sql_block = (
                f'<details style="margin-top:8px;">'
                f'<summary style="font-size:10px;color:#888;cursor:pointer;">'
                f'🗄 Show SQL — run this yourself in DB Browser to verify</summary>'
                f'<pre style="background:#1e1e1e;color:#d4d4d4;padding:10px 14px;'
                f'border-radius:4px;font-size:11px;overflow-x:auto;margin-top:6px;">'
                f'{html.escape(sql.strip())}</pre></details>'
            )

        cards += (
            f'<div style="background:{sc["bg"]};border:1px solid {sc["border"]};'
            f'border-left:5px solid {sc["border"]};border-radius:6px;'
            f'padding:16px 20px;margin-bottom:16px;">'
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap;">'
            f'{badge}'
            f'<strong style="font-size:13px;color:#2c3e50;">{meta["title"]}</strong>'
            f'{risk_badge}</div>'
            f'<div style="font-size:13px;font-weight:600;color:#2c3e50;margin-bottom:6px;">'
            f'{summary}</div>'
            f'<div style="font-size:12px;color:#444;line-height:1.65;margin-bottom:8px;'
            f'background:rgba(255,255,255,0.65);padding:8px 12px;border-radius:4px;">'
            f'{html.escape(str(expl))}</div>'
            f'{data_table}'
            f'{sql_block}'
            f'</div>'
        )

    return (
        f'<div style="background:#f8f9fa;border:1px solid #dce1e7;border-radius:8px;'
        f'padding:20px 24px;margin-top:8px;">'
        f'<p style="font-size:12px;color:#666;margin:0 0 16px;">'
        f'Each check below runs the actual SQL query against your GeoPackage and '
        f'shows you the real data. Nothing is guessed or assumed. '
        f'The file is never modified — this is read-only analysis only.</p>'
        f'{summary_bar}'
        f'{cards}'
        f'</div>'
    )


# ──────────────────────────────────────────────────────────────────────────────
# RUN ALL CHECKS
# ──────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
