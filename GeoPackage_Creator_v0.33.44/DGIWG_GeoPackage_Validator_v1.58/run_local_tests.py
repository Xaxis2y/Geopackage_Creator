# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
DGIWG Validator v1.58 — Local Self-Test Harness (Anaconda Prompt)
=================================================================

Run this from the project folder (the folder containing dgiwg_validator/).

RECOMMENDED SETUP (Anaconda Prompt) — always use a dedicated environment,
NEVER install packages into the base environment:

    conda create -n dgiwg_test python=3.11 -y
    conda activate dgiwg_test
    pip install shapely Pillow pyproj lxml
    cd C:\\Users\\Son\\Documents\\DGIWG\\DGIWG_GeoPackage_Validator_v1.57
    python run_local_tests.py

The script:
  1. Generates 3 synthetic GeoPackages using ONLY the Python stdlib
     (embedded base64 PNG/WEBP tiles, hand-built WKB geometry — no GDAL,
     no shapely, no Pillow required for generation).
       good_tiles.gpkg — well-formed EPSG:3857 pyramid + DMF metadata
       bad_mixed.gpkg  — 10+ deliberate violations
       features.gpkg   — EPSG:4326 features, valid + bowtie polygon,
                         no rtree, no extensions/metadata tables
  2. Runs the validator on them in --offline mode.
  3. Compares every produced requirement status against an expectation
     table (adjusted automatically for missing optional libraries).
  4. Checks --fail-fast exit code and invalid-file skip handling.
  5. Writes a detailed step-by-step log:  local_test_log_<timestamp>.txt

Exit code: 0 = all assertions passed, 1 = one or more failures.
Send the generated log file back for review if anything fails.
"""
import os
import io
import sys
import json
import glob
import math
import base64
import sqlite3
import struct
import subprocess
import datetime
import shutil
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
TEST_ROOT = os.path.join(HERE, "local_test")
GPKG_DIR = os.path.join(TEST_ROOT, "test_gpkg")
REPORT_DIR = os.path.join(TEST_ROOT, "reports")
LOG_PATH = os.path.join(
    HERE, f"local_test_log_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"
)

_LOG_FH = None


def log(msg, echo=True):
    """Append a timestamped line to the log file (and stdout)."""
    global _LOG_FH
    line = f"[{datetime.datetime.now():%H:%M:%S}] {msg}"
    if _LOG_FH is None:
        _LOG_FH = open(LOG_PATH, "w", encoding="utf-8")
    _LOG_FH.write(line + "\n")
    _LOG_FH.flush()
    if echo:
        print(line)


# ──────────────────────────────────────────────────────────────────────────────
# Embedded binary assets (base64) — no image library needed for generation
# ──────────────────────────────────────────────────────────────────────────────
PNG_256 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAQAAAAEAAQMAAABmvDolAAAAA1BMVEUAAACnej3aAAAAH0lEQVR4"
    "nO3BAQ0AAADCoPdPbQ43oAAAAAAAAAAAvg0hAAAB8Wch7gAAAABJRU5ErkJggg=="
)
PNG_512 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAgAAAAIAAQMAAADOtka5AAAAA1BMVEUAAACnej3aAAAANklEQVR4"
    "nO3BAQEAAACCIP+vbkhAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB8G4IAAAHSeInw"
    "AAAAAElFTkSuQmCC"
)
WEBP_512 = base64.b64decode(
    "UklGRggCAABXRUJQVlA4IPwBAABQOgCdASoAAgACPm02mUmkIyKhIAgAgA2JaW7hd2EbQAnsA99s"
    "nIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHv"
    "tk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ"
    "99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJ"
    "yHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77"
    "ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkP"
    "fbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32yc"
    "h77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2"
    "TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych6wAAP7/54AAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAA"
)

WKT2_3857 = (
    'PROJCRS["WGS 84 / Pseudo-Mercator",BASEGEOGCRS["WGS 84",'
    'ENSEMBLE["World Geodetic System 1984 ensemble",'
    'MEMBER["World Geodetic System 1984 (Transit)"],'
    'MEMBER["World Geodetic System 1984 (G2296)"],'
    'ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]],'
    'ENSEMBLEACCURACY[2.0]],PRIMEM["Greenwich",0,'
    'ANGLEUNIT["degree",0.0174532925199433]],ID["EPSG",4326]],'
    'CONVERSION["Popular Visualisation Pseudo-Mercator",'
    'METHOD["Popular Visualisation Pseudo Mercator",ID["EPSG",1024]],'
    'PARAMETER["Latitude of natural origin",0,'
    'ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8801]],'
    'PARAMETER["Longitude of natural origin",0,'
    'ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8802]],'
    'PARAMETER["False easting",0,LENGTHUNIT["metre",1],ID["EPSG",8806]],'
    'PARAMETER["False northing",0,LENGTHUNIT["metre",1],ID["EPSG",8807]]],'
    'CS[Cartesian,2],AXIS["easting (X)",east,ORDER[1],'
    'LENGTHUNIT["metre",1]],AXIS["northing (Y)",north,ORDER[2],'
    'LENGTHUNIT["metre",1]],USAGE[SCOPE["Web mapping and visualisation."],'
    'AREA["World between 85.06 S and 85.06 N."],BBOX[-85.06,-180,85.06,180]],'
    'ID["EPSG",3857]]'
)

WKT2_4326 = (
    'GEOGCRS["WGS 84",ENSEMBLE["World Geodetic System 1984 ensemble",'
    'MEMBER["World Geodetic System 1984 (Transit)"],'
    'MEMBER["World Geodetic System 1984 (G2296)"],'
    'ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]],'
    'ENSEMBLEACCURACY[2.0]],PRIMEM["Greenwich",0,'
    'ANGLEUNIT["degree",0.0174532925199433]],CS[ellipsoidal,2],'
    'AXIS["geodetic latitude (Lat)",north,ORDER[1],'
    'ANGLEUNIT["degree",0.0174532925199433]],'
    'AXIS["geodetic longitude (Lon)",east,ORDER[2],'
    'ANGLEUNIT["degree",0.0174532925199433]],'
    'USAGE[SCOPE["Horizontal component of 3D system."],AREA["World."],'
    'BBOX[-90,-180,90,180]],ID["EPSG",4326]]'
)

WKT1_27700 = (
    'PROJCS["OSGB36 / British National Grid",GEOGCS["OSGB36",'
    'DATUM["Ordnance_Survey_of_Great_Britain_1936",'
    'SPHEROID["Airy 1830",6377563.396,299.3249646]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
    'PROJECTION["Transverse_Mercator"],UNIT["metre",1],'
    'AUTHORITY["EPSG","27700"]]'
)

DMF_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<gmd:MD_Metadata xmlns:gmd="http://www.isotc211.org/2005/gmd"
                 xmlns:gco="http://www.isotc211.org/2005/gco">
  <gmd:fileIdentifier><gco:CharacterString>{uuid.uuid4()}</gco:CharacterString></gmd:fileIdentifier>
  <gmd:language><gco:CharacterString>eng</gco:CharacterString></gmd:language>
  <gmd:characterSet>
    <gmd:MD_CharacterSetCode codeList="http://www.isotc211.org/2005/resources/Codelist/gmxCodelists.xml#MD_CharacterSetCode"
                             codeListValue="utf8">utf8</gmd:MD_CharacterSetCode>
  </gmd:characterSet>
  <gmd:hierarchyLevel>
    <gmd:MD_ScopeCode codeList="http://www.isotc211.org/2005/resources/Codelist/gmxCodelists.xml#MD_ScopeCode"
                      codeListValue="dataset">dataset</gmd:MD_ScopeCode>
  </gmd:hierarchyLevel>
  <gmd:contact>
    <gmd:CI_ResponsibleParty>
      <gmd:organisationName><gco:CharacterString>Test Org</gco:CharacterString></gmd:organisationName>
      <gmd:role>
        <gmd:CI_RoleCode codeList="http://www.isotc211.org/2005/resources/Codelist/gmxCodelists.xml#CI_RoleCode"
                         codeListValue="pointOfContact">pointOfContact</gmd:CI_RoleCode>
      </gmd:role>
    </gmd:CI_ResponsibleParty>
  </gmd:contact>
  <gmd:dateStamp><gco:Date>2026-08-01</gco:Date></gmd:dateStamp>
  <gmd:identificationInfo><gco:CharacterString>test dataset</gco:CharacterString></gmd:identificationInfo>
</gmd:MD_Metadata>"""


# ──────────────────────────────────────────────────────────────────────────────
# Stdlib-only geometry builders
# ──────────────────────────────────────────────────────────────────────────────
def wkb_polygon(rings):
    """Build little-endian WKB for a POLYGON from [[(x, y), ...], ...]."""
    out = [b"\x01", struct.pack("<I", 3), struct.pack("<I", len(rings))]
    for ring in rings:
        out.append(struct.pack("<I", len(ring)))
        for x, y in ring:
            out.append(struct.pack("<dd", x, y))
    return b"".join(out)


def gpkg_geom_blob(wkb, srs_id):
    """GeoPackage geometry BLOB: GP header (no envelope, LE) + WKB."""
    return b"GP" + bytes([0, 0x01]) + struct.pack("<i", srs_id) + wkb


# ──────────────────────────────────────────────────────────────────────────────
# GeoPackage generators (pure sqlite3)
# ──────────────────────────────────────────────────────────────────────────────
def base_schema(conn, gpkg12=True):
    c = conn.cursor()
    c.execute("PRAGMA application_id = %d" % (0x47503132 if gpkg12 else 0x47503130))
    c.execute("PRAGMA user_version = 10201")
    c.executescript("""
    CREATE TABLE gpkg_spatial_ref_sys (
      srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY,
      organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
      definition TEXT NOT NULL, description TEXT);
    CREATE TABLE gpkg_contents (
      table_name TEXT PRIMARY KEY, data_type TEXT NOT NULL,
      identifier TEXT UNIQUE, description TEXT DEFAULT '',
      last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
      min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE,
      srs_id INTEGER);
    """)
    c.execute("""INSERT INTO gpkg_spatial_ref_sys VALUES
      ('Undefined cartesian SRS', -1, 'NONE', -1, 'undefined', 'undefined cartesian'),
      ('Undefined geographic SRS', 0, 'NONE', 0, 'undefined', 'undefined geographic')""")
    return c


def make_good_tiles(path):
    log(f"STEP: generating {os.path.basename(path)} (conformant tile pyramid)")
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    c = base_schema(conn, gpkg12=True)
    c.execute("ALTER TABLE gpkg_spatial_ref_sys ADD COLUMN definition_12_063 TEXT NOT NULL DEFAULT 'undefined'")
    c.execute("INSERT INTO gpkg_spatial_ref_sys "
              "(srs_name, srs_id, organization, organization_coordsys_id, definition, description, definition_12_063) "
              "VALUES ('WGS 84 / Pseudo-Mercator', 3857, 'EPSG', 3857, ?, 'Web Mercator', ?)",
              (WKT2_3857, WKT2_3857))
    c.executescript("""
    CREATE TABLE gpkg_tile_matrix_set (
      table_name TEXT PRIMARY KEY, srs_id INTEGER NOT NULL,
      min_x DOUBLE NOT NULL, min_y DOUBLE NOT NULL,
      max_x DOUBLE NOT NULL, max_y DOUBLE NOT NULL);
    CREATE TABLE gpkg_tile_matrix (
      table_name TEXT NOT NULL, zoom_level INTEGER NOT NULL,
      matrix_width INTEGER NOT NULL, matrix_height INTEGER NOT NULL,
      tile_width INTEGER NOT NULL, tile_height INTEGER NOT NULL,
      pixel_x_size DOUBLE NOT NULL, pixel_y_size DOUBLE NOT NULL,
      CONSTRAINT pk_ttm PRIMARY KEY (table_name, zoom_level));
    CREATE TABLE osm_tiles (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      zoom_level INTEGER NOT NULL, tile_column INTEGER NOT NULL,
      tile_row INTEGER NOT NULL, tile_data BLOB NOT NULL,
      UNIQUE (zoom_level, tile_column, tile_row));
    CREATE TABLE gpkg_extensions (
      table_name TEXT, column_name TEXT, extension_name TEXT NOT NULL,
      definition TEXT NOT NULL, scope TEXT NOT NULL,
      CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name));
    CREATE TABLE gpkg_metadata (
      id INTEGER PRIMARY KEY, md_scope TEXT NOT NULL DEFAULT 'dataset',
      md_standard_uri TEXT NOT NULL, mime_type TEXT NOT NULL DEFAULT 'text/xml',
      metadata TEXT NOT NULL DEFAULT '');
    CREATE TABLE gpkg_metadata_reference (
      reference_scope TEXT NOT NULL, table_name TEXT, column_name TEXT,
      row_id_value INTEGER, timestamp DATETIME NOT NULL,
      md_file_id INTEGER NOT NULL, md_parent_id INTEGER);
    """)
    ext = 20037508.342789244
    c.execute("INSERT INTO gpkg_tile_matrix_set VALUES ('osm_tiles', 3857, ?, ?, ?, ?)",
              (-ext, -ext, ext, ext))
    c.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, min_x, min_y, max_x, max_y, srs_id, last_change) "
              "VALUES ('osm_tiles', 'tiles', 'osm_tiles', ?, ?, ?, ?, 3857, '2026-08-01T00:00:00Z')",
              (-ext, -ext, ext, ext))
    pz0 = 2 * math.pi * 6378137.0 / 256
    for z in range(0, 3):
        n = 2 ** z
        px = pz0 / (2 ** z)
        c.execute("INSERT INTO gpkg_tile_matrix VALUES ('osm_tiles', ?, ?, ?, 256, 256, ?, ?)",
                  (z, n, n, px, px))
        for col in range(n):
            for row in range(n):
                c.execute("INSERT INTO osm_tiles (zoom_level, tile_column, tile_row, tile_data) "
                          "VALUES (?,?,?,?)", (z, col, row, PNG_256))
    c.executescript("""
    INSERT INTO gpkg_extensions VALUES
      ('gpkg_metadata', NULL, 'gpkg_metadata',
       'http://www.geopackage.org/spec121/#extension_metadata', 'read-write'),
      ('gpkg_metadata_reference', NULL, 'gpkg_metadata',
       'http://www.geopackage.org/spec121/#extension_metadata', 'read-write'),
      ('gpkg_spatial_ref_sys', 'definition_12_063', 'gpkg_crs_wkt',
       'http://www.geopackage.org/spec121/#extension_crs_wkt', 'read-write');
    """)
    c.execute("INSERT INTO gpkg_metadata (id, md_scope, md_standard_uri, mime_type, metadata) "
              "VALUES (1, 'series', 'https://dgiwg.org/std/dmf/2.0', 'text/xml', ?)", (DMF_XML,))
    c.execute("INSERT INTO gpkg_metadata_reference VALUES "
              "('geopackage', NULL, NULL, NULL, '2026-08-01T00:00:00Z', 1, NULL)")
    c.execute("INSERT INTO gpkg_metadata_reference VALUES "
              "('table', 'osm_tiles', NULL, NULL, '2026-08-01T00:00:00Z', 1, NULL)")
    conn.commit()
    conn.close()
    log(f"  created ({os.path.getsize(path)} bytes)")


def make_bad_mixed(path):
    log(f"STEP: generating {os.path.basename(path)} (deliberate violations)")
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    c = base_schema(conn, gpkg12=False)          # violation: GeoPackage 1.0 id
    c.execute("INSERT INTO gpkg_spatial_ref_sys VALUES "
              "('OSGB36 / British National Grid', 27700, 'EPSG', 27700, ?, NULL)",
              (WKT1_27700,))                     # violations: WKT1 + CRS 27700
    c.executescript("""
    CREATE TABLE gpkg_tile_matrix_set (
      table_name TEXT PRIMARY KEY, srs_id INTEGER NOT NULL,
      min_x DOUBLE NOT NULL, min_y DOUBLE NOT NULL,
      max_x DOUBLE NOT NULL, max_y DOUBLE NOT NULL);
    CREATE TABLE gpkg_tile_matrix (
      table_name TEXT NOT NULL, zoom_level INTEGER NOT NULL,
      matrix_width INTEGER NOT NULL, matrix_height INTEGER NOT NULL,
      tile_width INTEGER NOT NULL, tile_height INTEGER NOT NULL,
      pixel_x_size DOUBLE NOT NULL, pixel_y_size DOUBLE NOT NULL,
      CONSTRAINT pk_ttm PRIMARY KEY (table_name, zoom_level));
    CREATE TABLE uk_tiles (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      zoom_level INTEGER NOT NULL, tile_column INTEGER NOT NULL,
      tile_row INTEGER NOT NULL, tile_data BLOB NOT NULL);
    CREATE TABLE gpkg_extensions (
      table_name TEXT, column_name TEXT, extension_name TEXT NOT NULL,
      definition TEXT NOT NULL, scope TEXT NOT NULL);
    """)
    # violations: disallowed gdal_nw extension + invalid scope value
    c.execute("INSERT INTO gpkg_extensions VALUES "
              "('uk_tiles', NULL, 'gdal_nw', 'GDAL no-write lock', 'bogus-scope')")
    c.execute("INSERT INTO gpkg_tile_matrix_set VALUES ('uk_tiles', 27700, 0, 0, 700000, 1300000)")
    # violation: last_change not ISO 8601
    c.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, min_x, min_y, max_x, max_y, srs_id, last_change) "
              "VALUES ('uk_tiles', 'tiles', 'uk_tiles', 0, 0, 700000, 1300000, 27700, 'not-a-date')")
    # violations: 512x512 declared+stored, zoom gap 0->2, non-factor-2 pixel sizes
    c.execute("INSERT INTO gpkg_tile_matrix VALUES ('uk_tiles', 0, 1, 1, 512, 512, 2734.375, 2734.375)")
    c.execute("INSERT INTO gpkg_tile_matrix VALUES ('uk_tiles', 2, 4, 4, 512, 512, 911.458333, 911.458333)")
    c.execute("INSERT INTO uk_tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (0,0,0,?)", (PNG_512,))
    # violation: WEBP tile blob
    c.execute("INSERT INTO uk_tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (2,0,0,?)", (WEBP_512,))
    # violation: no gpkg_metadata / gpkg_metadata_reference at all
    conn.commit()
    conn.close()
    log(f"  created ({os.path.getsize(path)} bytes)")


def make_features(path):
    log(f"STEP: generating {os.path.basename(path)} (features, invalid geometry)")
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    c = base_schema(conn, gpkg12=True)
    c.execute("INSERT INTO gpkg_spatial_ref_sys VALUES "
              "('WGS 84', 4326, 'EPSG', 4326, ?, 'World Geodetic System 1984')",
              (WKT2_4326,))
    c.executescript("""
    CREATE TABLE gpkg_geometry_columns (
      table_name TEXT NOT NULL, column_name TEXT NOT NULL,
      geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL,
      z TINYINT NOT NULL, m TINYINT NOT NULL,
      CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name));
    CREATE TABLE parcels (
      fid INTEGER PRIMARY KEY AUTOINCREMENT,
      geom BLOB, name TEXT, status TEXT);
    """)
    c.execute("INSERT INTO gpkg_geometry_columns VALUES ('parcels','geom','POLYGON',4326,0,0)")
    c.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, min_x, min_y, max_x, max_y, srs_id, last_change) "
              "VALUES ('parcels','features','parcels',0,0,2,2,4326,'2026-08-01T00:00:00Z')")
    valid = wkb_polygon([[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]])
    bowtie = wkb_polygon([[(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)]])  # self-intersecting
    for wkb, name in ((valid, "ok"), (bowtie, "bowtie")):
        c.execute("INSERT INTO parcels (geom, name) VALUES (?, ?)",
                  (gpkg_geom_blob(wkb, 4326), name))
    # violations: no rtree, no gpkg_extensions, no metadata tables,
    #             'status' column 100% NULL
    conn.commit()
    conn.close()
    log(f"  created ({os.path.getsize(path)} bytes)")


# ──────────────────────────────────────────────────────────────────────────────
# Test driver
# ──────────────────────────────────────────────────────────────────────────────
def have(mod):
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def run_validator(args):
    cmd = [sys.executable, "-m", "dgiwg_validator"] + args
    log(f"STEP: running {' '.join(cmd)}")
    env = dict(os.environ)
    env["PYTHONPATH"] = HERE + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=HERE)
    for line in (proc.stdout + proc.stderr).splitlines():
        log(f"  | {line}", echo=False)
    log(f"  exit code = {proc.returncode}")
    return proc


def main():
    failures = []
    checks = 0

    log("=" * 70)
    log("DGIWG Validator local self-test")
    log(f"Python     : {sys.version.split()[0]}  ({sys.executable})")
    log(f"Project dir: {HERE}")
    sys.path.insert(0, HERE)
    try:
        import dgiwg_validator
        log(f"Validator  : v{dgiwg_validator.__version__}")
    except Exception as exc:
        log(f"FATAL: cannot import dgiwg_validator package: {exc}")
        sys.exit(1)

    libs = {m: have(m) for m in ("shapely", "PIL", "pyproj", "lxml")}
    log(f"Optional libs: " + ", ".join(f"{k}={'OK' if v else 'MISSING'}"
                                        for k, v in libs.items()))
    if not all(libs.values()):
        log("NOTE: missing libs reduce check depth. In your dedicated conda env run:")
        log("      pip install shapely Pillow pyproj lxml")

    # 1. Generate test data ---------------------------------------------------
    if os.path.isdir(TEST_ROOT):
        shutil.rmtree(TEST_ROOT)
    os.makedirs(GPKG_DIR)
    make_good_tiles(os.path.join(GPKG_DIR, "good_tiles.gpkg"))
    make_bad_mixed(os.path.join(GPKG_DIR, "bad_mixed.gpkg"))
    make_features(os.path.join(GPKG_DIR, "features.gpkg"))
    with open(os.path.join(GPKG_DIR, "junk.gpkg"), "w") as fh:
        fh.write("this is not a sqlite database")   # must be skipped gracefully

    # 2. Batch run ------------------------------------------------------------
    proc = run_validator(["--offline", "--no-install", "--quiet",
                          "--output-dir", REPORT_DIR, GPKG_DIR])
    checks += 1
    if proc.returncode != 0:
        failures.append(f"batch run exit code {proc.returncode} (expected 0)")
    checks += 1
    if "not a valid" not in (proc.stdout + proc.stderr):
        failures.append("junk.gpkg was not reported as skipped/invalid")

    # 3. Load JSON reports ----------------------------------------------------
    reports = {}
    for jf in glob.glob(os.path.join(REPORT_DIR, "*_DGIWG_Report*.json")):
        data = json.load(open(jf, encoding="utf-8"))
        reports[data["file"]] = data
        log(f"  report loaded: {os.path.basename(jf)}  verdict={data['verdict']}")
    checks += 1
    if len(reports) != 3:
        failures.append(f"expected 3 JSON reports, found {len(reports)}")

    # 4. Expectation tables ---------------------------------------------------
    exp_good = {3: "PASS", 7: "PASS", 8: "PASS", 13: "PASS*", 18: "PASS",
                19: "PASS", 21: "PASS", 22: "PASS", 25: "PASS", 27: "PASS",
                30: "PASS", 24: "PASS" if libs["shapely"] else "PASS*",
                26: "PASS" if libs["PIL"] else "PASS*"}
    exp_bad = {3: "FAIL", 5: "FAIL", 7: "FAIL", 8: "FAIL", 13: "FAIL",
               18: "FAIL", 19: "FAIL", 25: "FAIL", 26: "FAIL", 27: "FAIL"}
    exp_feat = {3: "FAIL", 4: "PASS*", 5: "PASS*", 9: "PASS*",
                24: "FAIL" if libs["shapely"] else "PASS*",
                18: "FAIL", 19: "FAIL"}
    tables = {"good_tiles.gpkg": exp_good,
              "bad_mixed.gpkg": exp_bad,
              "features.gpkg": exp_feat}

    for fname, expect in tables.items():
        data = reports.get(fname)
        if not data:
            failures.append(f"{fname}: report missing")
            continue
        for req, want in expect.items():
            checks += 1
            got = data["requirements"].get(str(req), {}).get("status", "ABSENT")
            if got == want:
                log(f"  OK   {fname} Req {req}: {got}")
            else:
                failures.append(f"{fname} Req {req}: got {got}, expected {want}")
                log(f"  FAIL {fname} Req {req}: got {got}, expected {want}")
                log(f"       detail: {data['requirements'].get(str(req), {}).get('detail','')[:300]}",
                    echo=False)

    # verdict-level assertions
    checks += 3
    if reports.get("good_tiles.gpkg", {}).get("counts", {}).get("FAIL", 1) != 0:
        failures.append("good_tiles.gpkg has FAILs — should have none")
    if reports.get("bad_mixed.gpkg", {}).get("verdict") != "NON-CONFORMANT":
        failures.append("bad_mixed.gpkg verdict is not NON-CONFORMANT")
    if reports.get("features.gpkg", {}).get("verdict") != "NON-CONFORMANT":
        failures.append("features.gpkg verdict is not NON-CONFORMANT")

    # cascade root-cause note must fire for features.gpkg
    checks += 1
    if not reports.get("features.gpkg", {}).get("cascade_root_cause"):
        failures.append("features.gpkg: cascade_root_cause note missing")

    # 5. Rollup outputs -------------------------------------------------------
    for out in ("DGIWG_GPKG_FINAL_REPORT.html", "DGIWG_GPKG_FINAL_REPORT.csv"):
        checks += 1
        if not os.path.isfile(os.path.join(REPORT_DIR, out)):
            failures.append(f"rollup output missing: {out}")

    # 6. fail-fast exit code --------------------------------------------------
    proc_ff = run_validator(["--offline", "--no-install", "--quiet", "--fail-fast",
                             "--output-dir", os.path.join(TEST_ROOT, "ff"),
                             os.path.join(GPKG_DIR, "bad_mixed.gpkg")])
    checks += 1
    if proc_ff.returncode != 1:
        failures.append(f"--fail-fast exit code {proc_ff.returncode} (expected 1)")

    # 7. Summary ----------------------------------------------------------------
    log("=" * 70)
    log(f"RESULT: {checks - len(failures)}/{checks} assertions passed")
    if failures:
        log("FAILURES:")
        for f in failures:
            log(f"  ✗ {f}")
        log(f"Log file: {LOG_PATH}")
        log("Send this log file back for analysis.")
        sys.exit(1)
    log("ALL TESTS PASSED ✔")
    log(f"Log file: {LOG_PATH}")
    sys.exit(0)


if __name__ == "__main__":
    main()
