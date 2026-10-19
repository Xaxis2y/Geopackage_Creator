#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
dgiwg_gdb_audit_v2.2.py  (audit script version 2.2)

Independent audit of GeoPackage Creator v0.34.4 output against the DGIWG
GeoPackage Profile (DGIWG 126 Ed 1.1, STD-DP-19-005 v1.1).

v2.2 is wired to the two real ArcGIS Pro sample geodatabases:
    <Geopackage_Creator>\\Sample Data\\SampleData.gdb
        Airports_NoATT   Point, EPSG:3857
        Airports         Point, EPSG:3857 (with attachments)
        Airports__ATTACH attribute table with a BLOB column (photos, ~47 MB)
    <Geopackage_Creator>\\Sample Data\\States.gdb
        States           MultiPolygon, EPSG:4269 (NAD83)

This script does NOT use the bundled DGIWG validator for its verdicts. Every
check reads the produced .gpkg directly with sqlite3 / OGR and compares it with
the text of the profile. Use --with-validator to ALSO run the bundled
validator, so the two can be compared side by side.

Run from the Anaconda Prompt inside a DEDICATED environment (never base):

    conda activate geopackage
    python dgiwg_gdb_audit_v2.2.py --project "C:\\Users\\Son\\Documents\\Geopackage_Creator\\GeoPackage_Creator_v0.34.5_GitHub_Source_clean\\GeoPackage_Creator_v0.34.5"

Optional arguments:
    --samples   folder holding SampleData.gdb and States.gdb
                (default: the "Sample Data" folder next to this script)
    --gdb       an additional real .gdb to audit (repeatable)
    --raster    a raster (GeoTIFF etc.) to audit the tile path
    --synthetic also build the synthetic edge cases (ESRI-only CRS, PointZ,
                curve polygon, mixed Polygon/MultiPolygon after 500 features)
    --with-validator  also run the bundled DGIWG validator on each output
    --workdir   scratch / output folder
                (default: <project>\\dev_tools\\audit_work)

Outputs (send these back for review):
    <workdir>\\logs\\dgiwg_audit_<timestamp>.log   step-by-step log
    <workdir>\\logs\\dgiwg_audit_<timestamp>.json  machine-readable results
"""

import argparse
import datetime as dt
import json
import logging
import os
import platform
import shutil
import sqlite3
import sys
import traceback
import xml.etree.ElementTree as ET

AUDIT_VERSION = "2.2"

NS = {"gmd": "http://www.isotc211.org/2005/gmd",
      "gco": "http://www.isotc211.org/2005/gco"}

# DMF 2.0 elements marked [1] / [1..*] in Annex B, Figure B-1 of the profile.
DMF_MANDATORY_XPATHS = {
    "MDSTD.title (metadataStandardName)": ".//gmd:metadataStandardName",
    "MDSTD.version (metadataStandardVersion)": ".//gmd:metadataStandardVersion",
    "RSPURP (purpose)": ".//gmd:identificationInfo//gmd:purpose",
    "RSDLOC.language (resource language)":
        ".//gmd:MD_DataIdentification/gmd:language",
    "DGITYP.keyword (descriptiveKeywords)": ".//gmd:descriptiveKeywords",
    "RSLING (lineage)": ".//gmd:dataQualityInfo//gmd:lineage",
    "RSDFMT (distributionFormat)": ".//gmd:distributionInfo//gmd:distributionFormat",
}

# Table 16 (WGS 84 Geographic 2D) required gpkg_spatial_ref_sys values.
TABLE16_DESCRIPTION = ("Horizontal component of 3D system. Used by the GPS "
                       "satellite navigation system and for NATO military "
                       "geodetic surveying.")
TABLE16_SRS_NAMES = {"WGS 84",
                     "http://www.opengis.net/def/crs/EPSG/0/4326",
                     "http://www.opengis.net/def/crs/OGC/1.3/CRS84"}

# Table 8: extensions that are NOT allowed (features / tiles).
NOT_ALLOWED_PREFIXES = ("gpkg_geom_", "gpkg_zoom_other", "gpkg_webp")

# Table 11 / Table 12 raster CRS (EPSG codes). LCC is "per product".
RASTER_ALLOWED = ({3395, 3857, 4326, 4979, 5041, 5042}
                  | set(range(32601, 32661)) | set(range(32701, 32761)))
VECTOR_2D_ALLOWED = {4326}
VECTOR_3D_ALLOWED = {4979, 9518}

LINEAR_TYPES = {"POINT", "LINESTRING", "POLYGON", "MULTIPOINT",
                "MULTILINESTRING", "MULTIPOLYGON", "GEOMETRYCOLLECTION",
                "GEOMETRY"}

ESRI_ONLY_WKT = (
    'PROJCS["Custom_UTM_18N_NoAuthority",'
    'GEOGCS["GCS_Custom",DATUM["D_WGS_1984",'
    'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],'
    'PROJECTION["Transverse_Mercator"],PARAMETER["False_Easting",500000.0],'
    'PARAMETER["False_Northing",0.0],PARAMETER["Central_Meridian",-75.0],'
    'PARAMETER["Scale_Factor",0.9996],PARAMETER["Latitude_Of_Origin",0.0],'
    'UNIT["Meter",1.0]]')

log = logging.getLogger("dgiwg_audit")
RESULTS = []
TOOL_SELF_REPORT = {}


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def setup_logging(log_dir):
    os.makedirs(log_dir, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"dgiwg_audit_{stamp}.log")
    json_path = os.path.join(log_dir, f"dgiwg_audit_{stamp}.json")
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.setLevel(logging.DEBUG)
    log.addHandler(fh)
    log.addHandler(sh)
    return log_path, json_path


def record(case, check_id, ref, status, detail):
    RESULTS.append({"case": case, "check": check_id, "ref": ref,
                    "status": status, "detail": detail})
    level = logging.INFO if status in ("PASS", "INFO") else logging.WARNING
    log.log(level, "[%s] %s (%s) -> %s: %s", case, check_id, ref, status, detail)


# ---------------------------------------------------------------------------
# Optional synthetic edge cases (only with --synthetic)
# ---------------------------------------------------------------------------

def _new_gdb(path, ogr):
    drv = ogr.GetDriverByName("OpenFileGDB")
    if drv is None:
        raise RuntimeError("OpenFileGDB driver not available")
    if os.path.isdir(path):
        shutil.rmtree(path)
    return drv.CreateDataSource(path)


def _poly_wkt(x, y, d):
    return f"POLYGON(({x} {y},{x+d} {y},{x+d} {y+d},{x} {y+d},{x} {y}))"


def make_synthetic(work, ogr, osr):
    log.info("STEP 1b: creating synthetic edge-case inputs in %s", work)
    os.makedirs(work, exist_ok=True)
    inputs = {}

    try:  # G1: GDB layer in a CRS with NO EPSG authority
        p = os.path.join(work, "g1_gdb_esri_only_crs.gdb")
        ds = _new_gdb(p, ogr)
        srs = osr.SpatialReference()
        srs.ImportFromWkt(ESRI_ONLY_WKT)
        lyr = ds.CreateLayer("parcels", srs, ogr.wkbPolygon)
        lyr.CreateField(ogr.FieldDefn("name", ogr.OFTString))
        for i in range(5):
            f = ogr.Feature(lyr.GetLayerDefn())
            f.SetField("name", f"p{i}")
            f.SetGeometry(ogr.CreateGeometryFromWkt(
                _poly_wkt(445000 + i * 1000, 5030000, 500)))
            lyr.CreateFeature(f)
        ds = None
        inputs["G1_gdb_esri_only_crs"] = p
    except Exception:
        log.warning("G1 creation failed:\n%s", traceback.format_exc())

    try:  # G3: 3D points
        p = os.path.join(work, "g3_gdb_pointz.gdb")
        ds = _new_gdb(p, ogr)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        lyr = ds.CreateLayer("spot_heights", srs, ogr.wkbPoint25D)
        lyr.CreateField(ogr.FieldDefn("name", ogr.OFTString))
        for i in range(5):
            f = ogr.Feature(lyr.GetLayerDefn())
            f.SetField("name", f"h{i}")
            f.SetGeometry(ogr.CreateGeometryFromWkt(
                f"POINT Z ({-75.7 + i * 0.01} 45.4 {100 + i * 10})"))
            lyr.CreateFeature(f)
        ds = None
        inputs["G3_gdb_pointz"] = p
    except Exception:
        log.warning("G3 creation failed:\n%s", traceback.format_exc())

    try:  # G5: true-curve polygon
        p = os.path.join(work, "g5_gdb_curve.gdb")
        ds = _new_gdb(p, ogr)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        lyr = ds.CreateLayer("lakes", srs, ogr.wkbCurvePolygon)
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetGeometry(ogr.CreateGeometryFromWkt(
            "CURVEPOLYGON(CIRCULARSTRING(-75.7 45.4,-75.6 45.5,-75.5 45.4,"
            "-75.6 45.3,-75.7 45.4))"))
        lyr.CreateFeature(f)
        ds = None
        inputs["G5_gdb_curve"] = p
    except Exception:
        log.warning("G5 creation failed:\n%s", traceback.format_exc())

    try:  # T2: Polygon/MultiPolygon mix that appears after feature 500
        gpkg = os.path.join(work, "t2_mixed_after_500.gpkg")
        if os.path.exists(gpkg):
            os.remove(gpkg)
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(gpkg)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        lm = ds.CreateLayer("mixed", srs, ogr.wkbUnknown)
        for i in range(600):
            f = ogr.Feature(lm.GetLayerDefn())
            x = -75 + i * 0.001
            ring = (f"({x} 45,{x+0.0005} 45,{x+0.0005} 45.0005,"
                    f"{x} 45.0005,{x} 45)")
            wkt = f"POLYGON({ring})" if i < 550 else f"MULTIPOLYGON(({ring}))"
            f.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
            lm.CreateFeature(f)
        ds = None
        inputs["T2_mixed_after_500"] = gpkg
    except Exception:
        log.warning("T2 creation failed:\n%s", traceback.format_exc())

    for k, v in inputs.items():
        log.info("  synthetic input %s -> %s", k, v)
    return inputs


# ---------------------------------------------------------------------------
# Source inspection (used to detect silent data loss / Z loss / CRS issues)
# ---------------------------------------------------------------------------

def inspect_source(path, ogr):
    info = []
    ds = ogr.Open(path)
    if ds is None:
        log.error("Cannot open source %s", path)
        return info
    log.info("source driver: %s", ds.GetDriver().GetName())
    for i in range(ds.GetLayerCount()):
        lyr = ds.GetLayer(i)
        gt = lyr.GetGeomType()
        srs = lyr.GetSpatialRef()
        defn = lyr.GetLayerDefn()
        domains = 0
        binary_fields, fields = [], []
        for j in range(defn.GetFieldCount()):
            fd = defn.GetFieldDefn(j)
            fields.append(fd.GetName())
            if fd.GetType() == ogr.OFTBinary:
                binary_fields.append(fd.GetName())
            try:
                if fd.GetDomainName():
                    domains += 1
            except Exception:
                pass
        info.append({
            "name": lyr.GetName(),
            "geom_type": ogr.GeometryTypeToName(gt),
            "no_geometry": gt == ogr.wkbNone,
            "has_z": bool(ogr.GT_HasZ(gt)),
            "is_curve": bool(ogr.GT_IsNonLinear(gt)),
            "features": lyr.GetFeatureCount(),
            "epsg": (srs.GetAuthorityCode(None) if srs else None),
            "has_srs": srs is not None,
            "domain_fields": domains,
            "fields": fields,
            "binary_fields": binary_fields,
        })
    ds = None
    return info


# ---------------------------------------------------------------------------
# Output audit (vector)
# ---------------------------------------------------------------------------

def check_reprojection(case, src_path, src_layer, out_path, out_layer, ogr, osr,
                       limit=50):
    """Independently transform source geometries to EPSG:4326 and compare the
    envelopes with what the tool wrote (detects axis-order / datum errors)."""
    sds = ogr.Open(src_path)
    ods = ogr.Open(out_path)
    try:
        sl = sds.GetLayerByName(src_layer)
        ol = ods.GetLayerByName(out_layer)
        ssrs = sl.GetSpatialRef()
        if ssrs is None:
            record(case, f"L_reproject[{out_layer}]", "Req 9", "INFO",
                   "source has no CRS - nothing to compare")
            return
        ssrs = ssrs.Clone()
        ssrs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        tsrs = osr.SpatialReference()
        tsrs.ImportFromEPSG(4326)
        tsrs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        ct = osr.CoordinateTransformation(ssrs, tsrs)
        sl.ResetReading()
        ol.ResetReading()
        worst, n = 0.0, 0
        for sf, of in zip(sl, ol):
            sg, og = sf.GetGeometryRef(), of.GetGeometryRef()
            if sg is None or og is None:
                continue
            g = sg.Clone()
            if g.HasCurveGeometry(True):
                # v2.2: compare against the same 1-degree linearization the
                # tool applies, otherwise arc stroking is mis-reported as
                # a reprojection error.
                g = g.GetLinearGeometry(1.0)
            g.Transform(ct)
            e1, e2 = g.GetEnvelope(), og.GetEnvelope()
            worst = max(worst, max(abs(a - b) for a, b in zip(e1, e2)))
            n += 1
            if n >= limit:
                break
        record(case, f"L_reproject[{out_layer}]", "Req 9 / coordinate accuracy",
               "PASS" if (n and worst < 1e-6) else "FAIL",
               f"compared={n} features, worst envelope difference="
               f"{worst:.3e} degrees (tolerance 1e-6)")
    finally:
        sds = None
        ods = None


def audit_gpkg(case, src_path, out_path, src_info, ogr, osr):
    log.info("STEP 3: auditing %s (%s)", case, out_path)
    con = sqlite3.connect(out_path)
    q = lambda s, p=(): con.execute(s, p).fetchall()

    # 0. File-level OGC base sanity
    integrity = q("PRAGMA integrity_check")
    fk = q("PRAGMA foreign_key_check")
    app_id = q("PRAGMA application_id")[0][0]
    user_ver = q("PRAGMA user_version")[0][0]
    record(case, "00_file_level", "Req 1 (OGC base)",
           "PASS" if (integrity == [("ok",)] and not fk
                      and app_id == 0x47504B47 and user_ver == 10400)
           else "FAIL",
           f"integrity={integrity}, fk_violations={len(fk)}, "
           f"application_id={hex(app_id)}, user_version={user_ver}")

    # A. Extensions: Not Allowed / Mandatory (Req 3, 5; Table 8)
    ext_rows = q("SELECT table_name, column_name, extension_name "
                 "FROM gpkg_extensions")
    names = sorted({r[2] for r in ext_rows})
    banned = [n for n in names if n.startswith(NOT_ALLOWED_PREFIXES)]
    record(case, "A_not_allowed_ext", "Req 5 / Table 8",
           "FAIL" if banned else "PASS", f"registered={names}")
    contents = q("SELECT table_name, data_type FROM gpkg_contents")
    has_feat = any(r[1] == "features" for r in contents)
    mand = ["gpkg_metadata", "gpkg_crs_wkt"] + (
        ["gpkg_rtree_index"] if has_feat else [])
    missing = [m for m in mand if m not in names]
    record(case, "A2_mandatory_ext", "Req 3 / Table 8",
           "FAIL" if missing else "PASS", f"missing mandatory={missing}")

    # B. Geometry blob type vs declared type; curve rows
    ds = ogr.Open(out_path)
    gcols = q("SELECT table_name, geometry_type_name, srs_id, z "
              "FROM gpkg_geometry_columns")
    for tbl, decl, sid, z in gcols:
        lyr = ds.GetLayerByName(tbl)
        bad = curves = n = 0
        for feat in lyr:
            g = feat.GetGeometryRef()
            if g is None:
                continue
            n += 1
            name = g.GetGeometryName().upper()
            if name not in LINEAR_TYPES:
                curves += 1
            if decl.upper() != "GEOMETRY" and name != decl.upper():
                bad += 1
        lyr.ResetReading()
        record(case, f"B_geomtype[{tbl}]", "Req 1 + Table 8 F.1",
               "FAIL" if (bad or curves) else "PASS",
               f"declared={decl}, rows={n}, mismatched_rows={bad}, "
               f"curve_rows={curves}")

    # C. gpkg_contents bbox vs exact geometry extent (Table 37 rows 7-10)
    for tbl, mnx, mny, mxx, mxy in q(
            "SELECT table_name,min_x,min_y,max_x,max_y FROM gpkg_contents "
            "WHERE data_type='features'"):
        lyr = ds.GetLayerByName(tbl)
        if mnx is None:
            record(case, f"C_bbox[{tbl}]", "Table 37 rows 7-10", "INFO",
                   "bbox is NULL (allowed: no information available)")
            continue
        ex = lyr.GetExtent(force=1)  # (minx, maxx, miny, maxy)
        # v2.2: OGR GetExtent() returns values rounded to ~15 significant
        # digits while gpkg_contents holds full doubles, so compare with a
        # 1e-12 degree tolerance (the former float32 R-tree error was ~1e-6).
        tol = 1e-12
        literal_ok = (mnx >= ex[0] - tol and mny >= ex[2] - tol
                      and mxx <= ex[1] + tol and mxy <= ex[3] + tol)
        encloses = (mnx <= ex[0] + tol and mny <= ex[2] + tol
                    and mxx >= ex[1] - tol and mxy >= ex[3] - tol)
        record(case, f"C_bbox[{tbl}]", "Req 24 Table 37 rows 7-10",
               "PASS" if literal_ok else "FAIL",
               f"contents=({mnx!r},{mny!r},{mxx!r},{mxy!r}) "
               f"geom_extent=({ex[0]!r},{ex[2]!r},{ex[1]!r},{ex[3]!r}) "
               f"literal_rule_ok={literal_ok} encloses_data={encloses}")

    # D. CRS / dimension (Req 9, 10; Table 37 rows 11-14)
    for tbl, decl, sid, z in gcols:
        if z == 0:
            ok = sid in VECTOR_2D_ALLOWED
        elif z == 1:
            ok = sid in VECTOR_3D_ALLOWED
        else:
            ok = False
        why = " (undefined CRS)" if sid in (0, -1) else ""
        record(case, f"D_crs[{tbl}]", "Req 9 / Req 10 / Table 37 r11-13",
               "PASS" if ok else "FAIL", f"srs_id={sid}{why}, z={z}")

    # E. gpkg_spatial_ref_sys rows (Req 13, Table 16, Table 37 rows 1-2, 5)
    cols = [r[1] for r in q("PRAGMA table_info(gpkg_spatial_ref_sys)")]
    has_wkt2 = "definition_12_063" in cols
    sel = ("SELECT srs_id, srs_name, organization, description, definition"
           + (", definition_12_063" if has_wkt2 else ", NULL")
           + " FROM gpkg_spatial_ref_sys")
    for sid, sname, org, desc, wkt1, wkt2 in q(sel):
        if sid in (-1, 0):
            # v2.2: OGC GeoPackage Req 11 REQUIRES these two rows with
            # organization 'NONE' (undefined Cartesian / geographic CRS).
            # They are mandatory rows, not DGIWG data CRS: informational.
            record(case, f"E_srs[{sid}]", "OGC GPKG Req 11 (required row)",
                   "INFO", f"organization={org!r} is correct for this row")
            continue
        problems = []
        if org != "EPSG":
            problems.append(f"organization={org!r} (Table 37 row 1: EPSG)")
        d = (desc or "").strip().lower()
        if d in ("", "unknown", "tbd"):
            problems.append(f"description={desc!r} (Table 37 row 2)")
        if sid == 4326:
            if sname not in TABLE16_SRS_NAMES:
                problems.append(f"srs_name={sname!r} (Table 16)")
            if (desc or "").strip() != TABLE16_DESCRIPTION:
                problems.append(f"description={desc!r} != Table 16 text")
        if sid > 0 and not wkt2:
            problems.append("definition_12_063 is NULL")
        record(case, f"E_srs[{sid}]", "Req 13 / Table 16 / Table 37 r1-5",
               "FAIL" if problems else "PASS",
               "; ".join(problems) if problems else "ok")

    # F. gpkg_metadata extension registration rows (OGC Annex F.8)
    md_ext = sorted(str(r[0]) for r in q(
        "SELECT table_name FROM gpkg_extensions "
        "WHERE extension_name='gpkg_metadata'"))
    # v2.2: OGC GeoPackage 1.4 registers gpkg_metadata with table_name NULL
    # (package-wide); two per-table rows are the older (pre-1.2) pattern.
    # Both are accepted; neither is a DGIWG failure.
    record(case, "F_metadata_ext_rows", "OGC Annex F.8 (informational)",
           "PASS" if md_ext in (["None"],
                                ["gpkg_metadata", "gpkg_metadata_reference"])
           else "WARN", f"table_name values: {md_ext}")

    # G. Root metadata must be DMF or national (Table 37 rows 22-24)
    roots = q("SELECT m.id, m.md_scope, m.md_standard_uri FROM gpkg_metadata m "
              "JOIN gpkg_metadata_reference r ON r.md_file_id=m.id "
              "WHERE r.reference_scope='geopackage'")
    non_dmf = [r for r in roots if "dgiwg.org/std/dmf" not in (r[2] or "")]
    record(case, "G_root_metadata", "Req 24 Table 37 rows 22-24",
           "FAIL" if non_dmf else "PASS",
           f"geopackage-scope roots={roots}; non-DMF roots={non_dmf}")

    # H. Partial metadata must also be DMF (Req 18 / ATS 4.1)
    parts = q("SELECT m.id, m.md_scope, m.md_standard_uri, r.reference_scope, "
              "r.table_name, r.row_id_value, r.md_parent_id "
              "FROM gpkg_metadata m JOIN gpkg_metadata_reference r "
              "ON r.md_file_id=m.id WHERE r.reference_scope!='geopackage'")
    non_dmf_parts = [p for p in parts
                     if "dgiwg.org/std/dmf" not in (p[2] or "")]
    record(case, "H_partial_metadata", "Req 18 / Req 32 / ATS 4.1",
           "FAIL" if non_dmf_parts else "PASS",
           f"partial rows={len(parts)}, non-DMF partial rows={len(non_dmf_parts)}")
    if parts:
        record(case, "H2_partial_row_id_value", "Table 37 row 30 (ambiguous)",
               "INFO", "row_id_value for table-scope rows: "
               f"{sorted({p[5] for p in parts}, key=str)} "
               "(Table 35 says NULL, Table 37 row 30 says NOT NULL)")

    # I. DMF 2.0 mandatory elements (Annex B, Figure B-1 multiplicity)
    dmf = q("SELECT metadata FROM gpkg_metadata "
            "WHERE md_standard_uri LIKE '%dgiwg.org/std/dmf%'")
    if not dmf:
        record(case, "I_dmf_elements", "Req 18", "FAIL", "no DMF row")
    else:
        try:
            # v2.2: check EVERY DMF row (package + each table), not row 1.
            miss = []
            for i, (xml_text,) in enumerate(dmf):
                root = ET.fromstring(xml_text.encode("utf-8"))
                miss += [f"row{i}:{k}" for k, xp in DMF_MANDATORY_XPATHS.items()
                         if root.find(xp, NS) is None]
            record(case, "I_dmf_elements", "Req 18 / Annex B",
                   "FAIL" if miss else "PASS",
                   f"missing mandatory DMF elements: {miss}" if miss
                   else f"all checked elements present in {len(dmf)} DMF row(s)")
        except ET.ParseError as exc:
            record(case, "I_dmf_elements", "Req 18", "FAIL",
                   f"DMF XML not parseable: {exc}")

    # J-N: per-source-layer checks (geodatabase specific)
    gnames = {r[0] for r in gcols}
    ctypes = dict(contents)
    for s in src_info:
        tname = s["name"]
        if tname not in ctypes:
            record(case, f"K_layer_missing[{tname}]", "completeness", "FAIL",
                   "source layer not present in output")
            continue
        out_cols = [r[1] for r in q(f'PRAGMA table_info("{tname}")')]
        out_cols_l = {c.lower() for c in out_cols}

        # J. Attribute-only tables (e.g. ArcGIS attachment tables)
        if s["no_geometry"]:
            geom_row = tname in gnames
            record(case, f"J_attribute_table[{tname}]",
                   "Req 9 (undefined CRS) / OGC base",
                   "PASS" if (not geom_row and ctypes[tname] == "attributes")
                   else "FAIL",
                   f"data_type={ctypes[tname]}, has_geometry_column_row="
                   f"{geom_row}, columns={out_cols}")

        # K. completeness: feature count
        try:
            out_n = con.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
        except sqlite3.Error:
            out_n = None
        record(case, f"K_feature_count[{tname}]", "completeness",
               "PASS" if out_n == s["features"] else "FAIL",
               f"source={s['features']}, output={out_n}")

        # M. completeness: attribute columns and BLOBs
        lost = [f for f in s["fields"] if f.lower() not in out_cols_l]
        record(case, f"M_fields[{tname}]", "completeness",
               "WARN" if lost else "PASS",
               f"source fields={s['fields']}; missing in output={lost}; "
               f"BLOB fields in source={s['binary_fields']}")
        if s["binary_fields"]:
            kept, empty = [], []
            for bf in s["binary_fields"]:
                match = [c for c in out_cols_l if c == bf.lower()]
                if not match:
                    empty.append(bf)
                    continue
                n_blob = q(f'SELECT COUNT(*) FROM "{tname}" '
                           f'WHERE "{bf}" IS NOT NULL AND length("{bf}") > 0'
                           )[0][0]
                (kept if n_blob else empty).append(bf)
            record(case, f"M_blob_loss[{tname}]",
                   "completeness (ArcGIS attachments)",
                   "WARN" if empty else "PASS",
                   f"BLOB column(s) carried with data={kept}; "
                   f"missing/empty={empty}")

        if s["has_z"]:
            zrow = [g for g in gcols if g[0] == tname]
            zval = zrow[0][3] if zrow else None
            record(case, f"K_z_preserved[{tname}]", "Req 10 (3D vector)",
                   "WARN" if zval == 0 else "PASS",
                   f"source has Z; output z flag={zval} "
                   "(0 means elevation was discarded)")
        if s["is_curve"]:
            record(case, f"K_curve_source[{tname}]", "Table 8 F.1", "INFO",
                   f"source geometry type {s['geom_type']} is non-linear")
        if s["domain_fields"]:
            dc = q("SELECT COUNT(*) FROM sqlite_master "
                   "WHERE name='gpkg_data_column_constraints'")[0][0]
            n_con = (q("SELECT COUNT(*) FROM gpkg_data_column_constraints")[0][0]
                     if dc else 0)
            record(case, f"K_domains[{tname}]", "completeness (Ext F.9 optional)",
                   "WARN" if n_con == 0 else "PASS",
                   f"source has {s['domain_fields']} domain field(s); "
                   f"output gpkg_data_column_constraints rows={n_con}")

        # L. coordinate accuracy of the reprojection
        if (not s["no_geometry"]) and tname in gnames:
            sid = [g[2] for g in gcols if g[0] == tname][0]
            if sid == 4326:
                try:
                    check_reprojection(case, src_path, tname, out_path,
                                       tname, ogr, osr)
                except Exception:
                    record(case, f"L_reproject[{tname}]", "Req 9", "FAIL",
                           "comparison crashed:\n" + traceback.format_exc())

        # N. Source CRS vs what the tool detected
        if not s["no_geometry"]:
            record(case, f"N_source_crs[{tname}]", "Req 9", "INFO",
                   f"source EPSG authority={s['epsg']}, has_srs={s['has_srs']}")

    ds = None
    con.close()


# ---------------------------------------------------------------------------
# Output audit (raster tiles)
# ---------------------------------------------------------------------------

def audit_tiles(case, path):
    log.info("STEP 3R: auditing raster/tile output %s", path)
    con = sqlite3.connect(path)
    q = lambda s, p=(): con.execute(s, p).fetchall()

    tables = [r[0] for r in q(
        "SELECT table_name FROM gpkg_contents WHERE data_type='tiles'")]
    if not tables:
        record(case, "R0_tiles", "-", "FAIL", "no tiles table in gpkg_contents")
        return
    names = sorted({r[0] for r in q("SELECT extension_name FROM gpkg_extensions")})
    banned = [n for n in names if n.startswith(NOT_ALLOWED_PREFIXES)]
    record(case, "R1_not_allowed_ext", "Req 5 / Table 8",
           "FAIL" if banned else "PASS", f"registered={names}")
    miss = [m for m in ("gpkg_metadata", "gpkg_crs_wkt") if m not in names]
    record(case, "R2_mandatory_ext", "Req 3 / Table 8",
           "FAIL" if miss else "PASS", f"missing={miss}")

    n_md = q("SELECT COUNT(*) FROM sqlite_master "
             "WHERE name='gpkg_metadata'")[0][0]
    n_dmf = (q("SELECT COUNT(*) FROM gpkg_metadata WHERE md_standard_uri "
               "LIKE '%dgiwg.org/std/dmf%'")[0][0] if n_md else 0)
    record(case, "R3_dmf_metadata", "Req 18/19/20",
           "PASS" if n_dmf else "FAIL",
           f"gpkg_metadata table present={bool(n_md)}, DMF rows={n_dmf}")

    cols = [r[1] for r in q("PRAGMA table_info(gpkg_spatial_ref_sys)")]
    record(case, "R4_wkt_column", "Req 13",
           "PASS" if "definition_12_063" in cols else "FAIL",
           f"definition_12_063 present={'definition_12_063' in cols}")

    for t in tables:
        srs_id, mnx, mny, mxx, mxy = q(
            "SELECT srs_id,min_x,min_y,max_x,max_y FROM gpkg_tile_matrix_set "
            "WHERE table_name=?", (t,))[0]
        record(case, f"R5_crs[{t}]", "Req 7 / Req 8",
               "PASS" if srs_id in RASTER_ALLOWED else "FAIL",
               f"srs_id={srs_id}")
        tm = q("SELECT zoom_level,matrix_width,matrix_height,tile_width,"
               "tile_height,pixel_x_size,pixel_y_size FROM gpkg_tile_matrix "
               "WHERE table_name=? ORDER BY zoom_level", (t,))
        bad_size = [r[0] for r in tm if r[3] != 256 or r[4] != 256]
        record(case, f"R6_tile_size[{t}]", "Req 25",
               "FAIL" if bad_size else "PASS",
               f"zoom levels not 256x256={bad_size}")
        bad_f = []
        for a, b in zip(tm, tm[1:]):
            if b[0] != a[0] + 1:
                bad_f.append(f"non-adjacent {a[0]}->{b[0]}")
            elif abs(a[5] / b[5] - 2.0) > 1e-6 or abs(a[6] / b[6] - 2.0) > 1e-6:
                bad_f.append(f"{a[0]}->{b[0]} factor={a[5]/b[5]:.6f}")
        record(case, f"R7_zoom_factor[{t}]", "Req 27",
               "FAIL" if bad_f else "PASS", f"violations={bad_f}")
        ref = {4326: (0.703125, 2, 1), 3857: (156543.03392804097, 1, 1),
               3395: (156543.03392804097, 1, 1)}.get(srs_id)
        if ref is None:
            record(case, f"R8_tms_match[{t}]", "Req 8 / Req 28 / ATS 3.2",
                   "INFO", f"srs_id={srs_id}: TMS comparison not implemented "
                   "in this script - verify manually against OGC 17-083r2")
        else:
            px0, w0, h0 = ref
            off = []
            for z, mw, mh, _, _, px, py in tm:
                if (abs(px / (px0 / 2 ** z) - 1) > 1e-6
                        or mw != w0 * 2 ** z or mh != h0 * 2 ** z):
                    off.append(z)
            record(case, f"R8_tms_match[{t}]", "Req 8 / Req 28 / ATS 3.2",
                   "FAIL" if off else "PASS",
                   f"zoom levels not matching the standard TMS grid={off}")
    con.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run_case(case, src, out, GeoPackageConverter, ogr, osr,
             raster=False, with_validator=False):
    if os.path.exists(out):
        os.remove(out)
    src_info = [] if raster else inspect_source(src, ogr)
    for s in src_info:
        log.info("[%s] source layer %s", case, s)
    try:
        kwargs = dict(
            title="DGIWG audit input",
            abstract="DGIWG audit input dataset", poc="ES",
            org="Audit Org", nation="CAN", security="UNCLASSIFIED",
            generate_reports=False)
        if with_validator:
            kwargs["run_dgiwg_validation"] = True
        res = GeoPackageConverter().convert(src, out, **kwargs)
        log.info("[%s] success=%s dgiwg_compliant=%s error=%s", case,
                 res.get("success"), res.get("dgiwg_compliant"),
                 res.get("error"))
        log.info("[%s] crs_conversion=%s", case, res.get("crs_conversion"))
        for w in res.get("warnings", []):
            log.info("[%s] tool warning: %s", case, w)
        TOOL_SELF_REPORT[case] = res.get("dgiwg_compliant")
        RESULTS.append({"case": case, "check": "tool_self_report",
                        "ref": "-", "status": "INFO",
                        "detail": {"success": res.get("success"),
                                   "dgiwg_compliant": res.get("dgiwg_compliant"),
                                   "warnings": res.get("warnings", [])}})
        if with_validator:
            v = res.get("dgiwg_validation") or {}
            RESULTS.append({"case": case, "check": "bundled_validator",
                            "ref": "-", "status": "INFO",
                            "detail": {k: v.get(k) for k in
                                       ("available", "conformant", "error",
                                        "summary", "passed", "failed")}})
            log.info("[%s] bundled validator: %s", case,
                     {k: v.get(k) for k in v if k != "results"})
        if res.get("success") and os.path.exists(out):
            if raster:
                audit_tiles(case, out)
            else:
                audit_gpkg(case, src, out, src_info, ogr, osr)
        else:
            record(case, "conversion", "-", "FAIL",
                   f"tool did not produce an output: {res.get('error')}")
    except Exception:
        log.error("[%s] conversion crashed:\n%s", case, traceback.format_exc())
        record(case, "conversion", "-", "FAIL", "conversion crashed (see log)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True,
                    help="GeoPackage Creator project root (contains core/)")
    ap.add_argument("--samples", default=None,
                    help='Folder holding SampleData.gdb and States.gdb')
    ap.add_argument("--gdb", action="append", default=[],
                    help="Additional real .gdb to audit (repeatable)")
    ap.add_argument("--raster", default=None,
                    help="Raster (GeoTIFF etc.) to audit the tile path")
    ap.add_argument("--synthetic", action="store_true",
                    help="Also build synthetic edge-case inputs")
    ap.add_argument("--with-validator", action="store_true",
                    help="Also run the bundled DGIWG validator per output")
    ap.add_argument("--workdir", default=None,
                    help="Output folder (default: <project>/dev_tools/audit_work)")
    args = ap.parse_args()

    project = os.path.abspath(args.project)
    work = os.path.abspath(args.workdir or os.path.join(
        project, "dev_tools", "audit_work"))
    log_path, json_path = setup_logging(os.path.join(work, "logs"))

    log.info("DGIWG audit script v%s", AUDIT_VERSION)
    log.info("Python %s | %s", sys.version.split()[0], platform.platform())
    log.info("Executable: %s", sys.executable)
    log.info("CONDA_DEFAULT_ENV=%s", os.environ.get("CONDA_DEFAULT_ENV"))
    if os.environ.get("CONDA_DEFAULT_ENV") in (None, "base"):
        log.warning("Not running in a dedicated conda env - activate it first")

    try:
        from osgeo import gdal, ogr, osr
        gdal.UseExceptions()
        ogr.UseExceptions()
        osr.UseExceptions()
        log.info("GDAL %s", gdal.__version__)
        for drv in ("OpenFileGDB", "FileGDB", "GPKG"):
            log.info("driver %s available: %s", drv,
                     ogr.GetDriverByName(drv) is not None)
    except Exception:
        log.error("GDAL import failed:\n%s", traceback.format_exc())
        return 2

    sys.path.insert(0, project)
    try:
        from core.converter import GeoPackageConverter
        log.info("GeoPackage Creator imported from %s", project)
    except Exception:
        log.error("Tool import failed:\n%s", traceback.format_exc())
        return 3

    # Locate the sample geodatabases.
    samples = args.samples
    if not samples:
        here = os.path.dirname(os.path.abspath(__file__))
        for cand in (os.path.join(here, "Sample Data"),
                     os.path.join(os.path.dirname(project), "Sample Data"),
                     os.path.join(os.path.dirname(os.path.dirname(project)),
                                  "Sample Data")):
            if os.path.isdir(cand):
                samples = cand
                break
    inputs = {}
    if samples:
        for case, name in (("S1_SampleData", "SampleData.gdb"),
                           ("S2_States", "States.gdb")):
            p = os.path.join(samples, name)
            if os.path.isdir(p):
                inputs[case] = p
            else:
                log.warning("sample geodatabase not found: %s", p)
    else:
        log.warning("no --samples folder found; pass --samples explicitly")
    for i, g in enumerate(args.gdb, 1):
        gname = os.path.basename(os.path.normpath(g))
        inputs["X%d_%s" % (i, gname)] = g
    if args.synthetic:
        inputs.update(make_synthetic(work, ogr, osr))
    if not inputs and not args.raster:
        log.error("nothing to audit")
        return 4

    log.info("STEP 2: running GeoPackageConverter.convert() per case")
    for case, src in inputs.items():
        log.info("---- case %s <- %s", case, src)
        run_case(case, src, os.path.join(work, f"{case}.gpkg"),
                 GeoPackageConverter, ogr, osr,
                 with_validator=args.with_validator)

    if args.raster:
        run_case("RASTER", args.raster, os.path.join(work, "RASTER.gpkg"),
                 GeoPackageConverter, ogr, osr, raster=True,
                 with_validator=args.with_validator)

    counts = {}
    for r in RESULTS:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    log.info("SUMMARY: %s", counts)
    for case, claimed in TOOL_SELF_REPORT.items():
        nfail = sum(1 for r in RESULTS
                    if r["case"] == case and r["status"] == "FAIL")
        log.info("tool self-report vs audit [%s]: tool dgiwg_compliant=%s, "
                 "independent audit FAIL count=%d", case, claimed, nfail)
    for r in RESULTS:
        if r["status"] == "FAIL":
            log.info("FAIL  [%s] %s (%s)", r["case"], r["check"], r["ref"])
    with open(json_path, "w", encoding="utf-8") as fp:
        json.dump({"audit_version": AUDIT_VERSION,
                   "gdal": gdal.__version__, "results": RESULTS},
                  fp, indent=2, default=str)
    log.info("Log:  %s", log_path)
    log.info("JSON: %s", json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
