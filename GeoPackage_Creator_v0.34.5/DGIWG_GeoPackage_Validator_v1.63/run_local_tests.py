# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
DGIWG Validator v1.60 — Local Self-Test Harness (Anaconda Prompt)
=================================================================

Run this from the project folder (the folder containing dgiwg_validator/).

RECOMMENDED SETUP (Anaconda Prompt) — always use a dedicated environment,
NEVER install packages into the base environment.  Installing into `base`
is the single most common cause of dependency conflicts and unexplained
runtime failures on these machines:

    conda create -n dgiwg_test python=3.11 -y
    conda activate dgiwg_test
    pip install shapely Pillow pyproj lxml
    cd C:\\Users\\Son\\Documents\\DGIWG\\DGIWG_GeoPackage_Validator_v1.59
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
  5. Regression tests carried over from v1.59:
       • version stamp is 1.60 in package, VERSION.txt, launcher, JSON schema
       • Req 4 returns PASS (not PASS*) when no optional extensions exist
       • --quiet emits no report-written chatter
       • every manual-check entry is a uniform 4-tuple
       • the conformance-scope banner is present in per-file and rollup HTML
       • Req 18 always states whether XSD validation ran
       • lxml is probed and reported as an optional library
       • release assets (QUICKSTART.html, v1.60 manual, v1_60 launcher) exist
  6. NEW IN v1.60 — regression tests for this release's fixes:
       • _decode_gpkg_geom_header() derives Z/M from the WKB type code, not
         from the flags byte (the v1.59 decoder fails this test)
       • a 2D feature table written WITH XY envelopes — the case that produced
         the false failure — reports no Req 24 Z/M mismatch end to end
       • Req 33 gives a readable FAIL, not a generic exception, when a gridded
         file has no gpkg_extensions table
       • net._http_get / _http_head refuse to touch the network under --offline
       • rollup.py has no __main__ guard calling an undefined main()
       • package_release.py never bundles a "_superseded_*"/"_to_delete_*"
         housekeeping folder into the staged release or the zip
  7. Writes a detailed step-by-step log:  local_test_log_<timestamp>.txt

Exit code: 0 = all assertions passed, 1 = one or more failures.
Send the generated log file back for review if anything fails.
"""
import os
import io
import re
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

    EXPECTED_VERSION = "1.63"
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
    # v1.59 semantic changes reflected here:
    #   Req 4  — PASS when no optional extension is registered (was always PASS*)
    #   Req 18 — PASS only when lxml is present so the XSD stage actually ran;
    #            PASS* otherwise, because field checks alone are a partial result
    # v1.61 semantic changes (reason-coded PASS*; see RELEASE_NOTES_v1.61.md):
    #   Req 9, 10, 12, 28, 29, 33 — exhaustive checks now return PASS (not PASS*)
    #     on clean data; still FAIL on a genuine violation (see positive-control
    #     tests in the v1.61 section below).
    #   Req 14 — PASS when checked and clean; SKIPPED (not PASS*) when the file
    #     has no vector geometry columns AND no compound CRS in the SRS table —
    #     good_tiles.gpkg is tiles-only, so this now reads SKIPPED.
    #   Req 5  — the WEBP tile-format scan now honours --sample-size and
    #     returns bare PASS once the scan has covered every stored tile BLOB
    #     (not just a fixed first-10 sample); features.gpkg has no tile tables
    #     at all, so its scan trivially covers "everything" (zero to scan) and
    #     reads PASS, not PASS*.
    exp_good = {3: "PASS", 4: "PASS", 7: "PASS", 8: "PASS", 13: "PASS*",
                18: "PASS" if libs["lxml"] else "PASS*",
                19: "PASS", 21: "PASS", 22: "PASS", 25: "PASS", 27: "PASS",
                30: "PASS", 24: "PASS" if libs["shapely"] else "PASS*",
                # v1.61: Req 26 now distinguishes a fully-decoded tile table
                # (bare PASS) from a partially-sampled one (PASS*/SAMPLED).
                # good_tiles.gpkg's zoom 2 has 16 stored tiles, more than the
                # default 5-per-zoom sample, so this is a genuine coverage
                # gap at default --sample-size — expect PASS* here, and see
                # the dedicated v1.61 coverage-accounting test below for
                # proof it becomes a bare PASS once --sample-size covers
                # every stored tile.
                26: "PASS*" if libs["PIL"] else "PASS*",
                # v1.61: legacy unconditional-PASS* sites now reachable PASS
                28: "PASS", 29: "PASS",
                # v1.61: no vector geometry + no compound CRS -> SKIPPED, not PASS*
                9: "SKIPPED", 10: "SKIPPED", 12: "SKIPPED", 14: "SKIPPED",
                33: "SKIPPED"}
    exp_bad = {3: "FAIL", 5: "FAIL", 7: "FAIL", 8: "FAIL", 13: "FAIL",
               18: "FAIL", 19: "FAIL", 25: "FAIL", 26: "FAIL", 27: "FAIL"}
    exp_feat = {3: "FAIL", 4: "PASS", 5: "PASS", 9: "PASS",
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

    # ─────────────────────────────────────────────────────────────────────────
    # v1.59 REGRESSION TESTS
    # ─────────────────────────────────────────────────────────────────────────

    # 7. Version stamp consistency -------------------------------------------
    log("STEP: v1.59 — version stamp consistency")
    checks += 1
    if dgiwg_validator.__version__ != EXPECTED_VERSION:
        failures.append(f"package __version__ is {dgiwg_validator.__version__}, "
                        f"expected {EXPECTED_VERSION}")
    else:
        log(f"  OK   package __version__ = {EXPECTED_VERSION}")

    checks += 1
    _launcher = os.path.join(HERE, f"DGIWG_Validator_v{EXPECTED_VERSION.replace('.', '_')}.py")
    if not os.path.isfile(_launcher):
        failures.append(f"launcher missing: {os.path.basename(_launcher)}")
    else:
        log(f"  OK   launcher present: {os.path.basename(_launcher)}")

    checks += 1
    _vtxt = os.path.join(HERE, "VERSION.txt")
    if not os.path.isfile(_vtxt):
        failures.append("VERSION.txt missing")
    else:
        _vraw = open(_vtxt, encoding="utf-8").read()
        if EXPECTED_VERSION not in _vraw:
            failures.append(f"VERSION.txt does not mention {EXPECTED_VERSION}")
        else:
            log(f"  OK   VERSION.txt states {EXPECTED_VERSION}")

    checks += 1
    _schema_versions = {d.get("schema_version") for d in reports.values()}
    if _schema_versions != {EXPECTED_VERSION}:
        failures.append(f"JSON schema_version = {_schema_versions}, "
                        f"expected {{'{EXPECTED_VERSION}'}}")
    else:
        log(f"  OK   JSON schema_version = {EXPECTED_VERSION} in all reports")

    checks += 1
    _pv = run_validator(["--version"])
    if EXPECTED_VERSION not in (_pv.stdout + _pv.stderr):
        failures.append(f"--version did not report {EXPECTED_VERSION}")
    else:
        log(f"  OK   --version reports {EXPECTED_VERSION}")

    # 8. --quiet is actually quiet -------------------------------------------
    # v1.58 printed "HTML report written:" / "Rollup HTML written:" /
    # "Rollup CSV  written:" regardless of --quiet.  The step-2 batch run above
    # used --quiet, so its captured output is the evidence.
    log("STEP: v1.59 — --quiet suppresses report-written chatter")
    _quiet_out = proc.stdout + proc.stderr
    for _noisy in ("HTML report written:", "Rollup HTML written:", "Rollup CSV  written:"):
        checks += 1
        if _noisy in _quiet_out:
            failures.append(f"--quiet still printed: {_noisy!r}")
            log(f"  FAIL --quiet still printed {_noisy!r}")
        else:
            log(f"  OK   --quiet suppressed {_noisy!r}")

    # --quiet must still print the one-line-per-file summary
    checks += 1
    if "good_tiles.gpkg" not in _quiet_out:
        failures.append("--quiet suppressed the per-file summary line as well")
    else:
        log("  OK   --quiet still prints the per-file summary line")

    # 9. Manual-check tuples are uniform 4-tuples -----------------------------
    # v1.58 mixed 3-tuples (success paths) with 4-tuples (error paths), so any
    # downstream `a, b, c = manual` unpack was a latent ValueError.
    log("STEP: v1.59 — _manual_checks() returns uniform 4-tuples")
    try:
        from dgiwg_validator.checks import _manual_checks
        from dgiwg_validator.utils import open_gpkg
        _shapes = {}
        for _gp in ("good_tiles.gpkg", "bad_mixed.gpkg", "features.gpkg"):
            _conn = open_gpkg(os.path.join(GPKG_DIR, _gp))
            try:
                _mc = _manual_checks(_conn.cursor())
            finally:
                _conn.close()
            for _k, _v in _mc.items():
                if isinstance(_k, int):
                    _shapes.setdefault(len(_v) if isinstance(_v, tuple) else -1,
                                       []).append(f"{_gp}:Req{_k}")
        checks += 1
        if set(_shapes) == {4}:
            log(f"  OK   all {sum(len(v) for v in _shapes.values())} manual entries are 4-tuples")
        else:
            _bad = {k: v[:5] for k, v in _shapes.items() if k != 4}
            failures.append(f"_manual_checks returned non-4-tuples: {_bad}")
            log(f"  FAIL non-4-tuple manual entries: {_bad}")
        # a real unpack must not raise
        checks += 1
        try:
            for _k, _v in _mc.items():
                if isinstance(_k, int):
                    _c, _t, _n, _u = _v
            log("  OK   4-way unpack of every manual entry succeeds")
        except ValueError as _ue:
            failures.append(f"manual entry unpack failed: {_ue}")
    except Exception as _mce:
        checks += 2
        failures.append(f"manual-tuple shape test could not run: {_mce}")

    # 10. Conformance-scope banner present -----------------------------------
    log("STEP: v1.59 — conformance-scope banner in HTML outputs")
    _per_file_html = sorted(glob.glob(os.path.join(REPORT_DIR, "*_DGIWG_Report*.html")))
    checks += 1
    if not _per_file_html:
        failures.append("no per-file HTML reports found for scope-banner check")
    else:
        _missing_banner = [
            os.path.basename(h) for h in _per_file_html
            if "Scope of this verdict" not in open(h, encoding="utf-8").read()
        ]
        if _missing_banner:
            failures.append(f"scope banner missing from: {_missing_banner}")
            log(f"  FAIL scope banner missing from {_missing_banner}")
        else:
            log(f"  OK   scope banner present in all {len(_per_file_html)} per-file reports")

    checks += 1
    _rollup_html = os.path.join(REPORT_DIR, "DGIWG_GPKG_FINAL_REPORT.html")
    if not os.path.isfile(_rollup_html):
        failures.append("rollup HTML missing for scope-banner check")
    elif "Scope of these verdicts" not in open(_rollup_html, encoding="utf-8").read():
        failures.append("scope banner missing from rollup HTML")
    else:
        log("  OK   scope banner present in rollup HTML")

    # 11. Req 18 always states the XSD outcome -------------------------------
    log("STEP: v1.59 — Req 18 reports XSD validation status")
    checks += 1
    _r18_detail = reports.get("good_tiles.gpkg", {}) \
                         .get("requirements", {}).get("18", {}).get("detail", "")
    if "XSD structural validation" not in _r18_detail:
        failures.append("Req 18 detail does not state the XSD validation status")
        log(f"  FAIL Req 18 detail: {_r18_detail[:200]}")
    else:
        _expect_word = "ENABLED" if libs["lxml"] else "SKIPPED"
        checks += 1
        if _expect_word not in _r18_detail:
            failures.append(f"Req 18 XSD status should say {_expect_word} "
                            f"(lxml {'present' if libs['lxml'] else 'absent'})")
        else:
            log(f"  OK   Req 18 XSD status = {_expect_word} (lxml "
                f"{'present' if libs['lxml'] else 'absent'})")

    # 12. lxml is probed as an optional library ------------------------------
    log("STEP: v1.59 — lxml included in the optional-library probe")
    checks += 1
    try:
        from dgiwg_validator.utils import _probe_optional_libraries, LIBRARY_STATUS
        _probe_optional_libraries(interactive_mode=False, skip_install=True)
        if "lxml" not in LIBRARY_STATUS:
            failures.append("LIBRARY_STATUS has no 'lxml' entry — probe not wired up")
        else:
            log(f"  OK   LIBRARY_STATUS['lxml'] = {LIBRARY_STATUS['lxml']}")
    except Exception as _pe:
        failures.append(f"optional-library probe test could not run: {_pe}")

    # 13. Release assets present ---------------------------------------------
    log("STEP: v1.59 — release assets present")
    _assets = [
        "QUICKSTART.html",
        f"DGIWG_GeoPackage_Validator_User_Manual_v{EXPECTED_VERSION}.docx",
        "package_release.py",
        "dgiwg_epsg_cache.json",
    ]
    for _a in _assets:
        checks += 1
        if not os.path.isfile(os.path.join(HERE, _a)):
            failures.append(f"release asset missing: {_a}")
            log(f"  FAIL missing asset: {_a}")
        else:
            log(f"  OK   asset present: {_a}")

    checks += 1
    _qs = os.path.join(HERE, "QUICKSTART.html")
    if os.path.isfile(_qs):
        _qs_raw = open(_qs, encoding="utf-8").read()
        if EXPECTED_VERSION not in _qs_raw:
            failures.append(f"QUICKSTART.html does not mention v{EXPECTED_VERSION}")
        else:
            log(f"  OK   QUICKSTART.html mentions v{EXPECTED_VERSION}")
    else:
        failures.append("QUICKSTART.html missing — cannot check its version stamp")

    # 14. package_release.py never bundles workspace housekeeping folders ----
    # Regression test for a real bug: a folder used to park files an update
    # superseded (this machine's device bridge cannot delete outright, so
    # such folders get named "_superseded_<old-version>" or "_to_delete...")
    # was not in package_release.py's exclude list because the list only
    # matched exact names, and the parking folder's name changes every
    # release. It was copied straight into the staged release and zipped in
    # — including any old release zip sitting inside it — roughly doubling
    # the archive size without anything in the build output calling it out.
    # This builds into a throwaway location so it never touches dist\ from a
    # real release, plants a fake parking folder (with a decoy zip inside, to
    # mimic exactly what happened), runs the packager, and asserts neither
    # the staged folder nor the archive contains a "_superseded"/"_to_delete"
    # entry.
    log("STEP: v1.59 — packager excludes _superseded_*/_to_delete_* folders")
    try:
        import subprocess as _sp
        import tempfile as _tempfile
        _pkg_test_dir = os.path.join(_tempfile.gettempdir(), "dgiwg_pkg_test")
        if os.path.isdir(_pkg_test_dir):
            shutil.rmtree(_pkg_test_dir)
        shutil.copytree(
            HERE, _pkg_test_dir,
            ignore=shutil.ignore_patterns(
                "dist", "local_test", "__pycache__", ".git",
                "local_test_log_*.txt",
            ),
        )
        _decoy_dir = os.path.join(_pkg_test_dir, "_superseded_v0")
        os.makedirs(_decoy_dir, exist_ok=True)
        with open(os.path.join(_decoy_dir, "old_release.zip"), "wb") as _df:
            _df.write(b"decoy bytes standing in for a stale release zip")
        _pkg_proc = _sp.run(
            [sys.executable, "package_release.py"],
            capture_output=True, text=True, cwd=_pkg_test_dir,
        )
        checks += 1
        if _pkg_proc.returncode != 0:
            failures.append(
                f"package_release.py exited {_pkg_proc.returncode} in the "
                f"housekeeping-exclusion test: {_pkg_proc.stdout[-400:]} "
                f"{_pkg_proc.stderr[-400:]}"
            )
        else:
            _test_dist = os.path.join(_pkg_test_dir, "dist")
            _leaked_staged = []
            _leaked_zip = []
            for _root, _dirs, _files in os.walk(_test_dist):
                if any(d.startswith(("_superseded", "_to_delete")) for d in _dirs):
                    _leaked_staged.append(_root)
            _built_zips = glob.glob(os.path.join(_test_dist, "*.zip"))
            for _zp in _built_zips:
                with __import__("zipfile").ZipFile(_zp) as _zf:
                    _leaked_zip.extend(
                        n for n in _zf.namelist()
                        if "_superseded" in n or "_to_delete" in n
                    )
            if _leaked_staged or _leaked_zip:
                failures.append(
                    "package_release.py bundled a housekeeping folder into the "
                    f"release — staged: {_leaked_staged}, in zip: {_leaked_zip}"
                )
                log(f"  FAIL housekeeping folder leaked — staged: {_leaked_staged}, "
                    f"in zip: {_leaked_zip}")
            elif not _built_zips:
                failures.append("housekeeping-exclusion test: no zip was built to check")
            else:
                log("  OK   _superseded_v0/ excluded from both the staged folder "
                    f"and {os.path.basename(_built_zips[0])}")
        shutil.rmtree(_pkg_test_dir, ignore_errors=True)
    except Exception as _pkge:
        checks += 1
        failures.append(f"housekeeping-exclusion test could not run: {_pkge}")

    # 15. v1.60 — geometry header Z/M decode (unit-level regression) ------------
    log("STEP: v1.60 — Z/M derived from WKB type code, not the flags byte")
    try:
        from dgiwg_validator.utils import _decode_gpkg_geom_header

        def _mk_blob(env_code, wkb):
            """GeoPackage geometry BLOB with the given envelope code + WKB payload."""
            _env_len = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[env_code]
            _flags = (env_code << 1) | 0x01           # little-endian header
            return (b"GP" + bytes([0, _flags])
                    + struct.pack("<i", 4326)
                    + b"\x00" * _env_len + wkb)

        _wkb_xy   = struct.pack("<BI", 1, 1) + struct.pack("<dd", 1.0, 2.0)
        _wkb_xyz  = struct.pack("<BI", 1, 1001) + struct.pack("<ddd", 1.0, 2.0, 3.0)
        _wkb_xym  = struct.pack("<BI", 1, 2001) + struct.pack("<ddd", 1.0, 2.0, 3.0)
        _wkb_xyzm = struct.pack("<BI", 1, 3001) + struct.pack("<dddd", 1.0, 2.0, 3.0, 4.0)

        # (label, envelope_code, wkb, expected_has_z, expected_has_m)
        _zm_cases = [
            ("2D geom + XY envelope (GDAL/QGIS default)", 1, _wkb_xy,   False, False),
            ("2D geom, no envelope",                      0, _wkb_xy,   False, False),
            ("3D geom, no envelope",                      0, _wkb_xyz,  True,  False),
            ("3D geom + XYZ envelope",                    2, _wkb_xyz,  True,  False),
            ("XYM geom + XYM envelope",                   3, _wkb_xym,  False, True),
            ("XYZM geom + XYZM envelope",                 4, _wkb_xyzm, True,  True),
        ]
        for _label, _env, _wkb, _exp_z, _exp_m in _zm_cases:
            checks += 1
            _h = _decode_gpkg_geom_header(_mk_blob(_env, _wkb))
            if _h is None:
                failures.append(f"Z/M decode: {_label} — header returned None")
                log(f"  FAIL {_label}: header is None")
            elif _h["has_z"] != _exp_z or _h["has_m"] != _exp_m:
                failures.append(
                    f"Z/M decode: {_label} — got has_z={_h['has_z']}, "
                    f"has_m={_h['has_m']}, expected {_exp_z}/{_exp_m}"
                )
                log(f"  FAIL {_label}: has_z={_h['has_z']} has_m={_h['has_m']} "
                    f"(expected {_exp_z}/{_exp_m})")
            else:
                log(f"  OK   {_label}: has_z={_exp_z} has_m={_exp_m}")

        # header_size must follow the envelope indicator, not a guess
        checks += 1
        _hs = {c: _decode_gpkg_geom_header(_mk_blob(c, _wkb_xy))["header_size"]
               for c in (0, 1, 2, 3, 4)}
        if _hs != {0: 8, 1: 40, 2: 56, 3: 56, 4: 72}:
            failures.append(f"envelope header_size table wrong: {_hs}")
            log(f"  FAIL header_size per envelope code: {_hs}")
        else:
            log("  OK   header_size matches the envelope indicator for codes 0-4")

        # reserved envelope indicator (5-7) must be reported, not silently used
        checks += 1
        _bad_env = b"GP" + bytes([0, (5 << 1) | 0x01]) + struct.pack("<i", 4326) + _wkb_xy
        _hbad = _decode_gpkg_geom_header(_bad_env)
        if _hbad is None or _hbad["envelope_valid"] is not False:
            failures.append("reserved envelope indicator 5 was not flagged invalid")
            log("  FAIL reserved envelope indicator 5 not flagged")
        else:
            log("  OK   reserved envelope indicator 5 reported as invalid")

        # non-GeoPackage payload must be flagged, not parsed
        checks += 1
        _nomagic = b"XX" + bytes([0, 0x01]) + struct.pack("<i", 4326) + _wkb_xy
        _hnm = _decode_gpkg_geom_header(_nomagic)
        if _hnm is None or _hnm["magic_ok"] is not False:
            failures.append("missing 'GP' magic marker was not flagged")
            log("  FAIL missing 'GP' magic not flagged")
        else:
            log("  OK   missing 'GP' magic marker reported")
    except Exception as _zme:
        checks += 1
        failures.append(f"Z/M decode regression test could not run: {_zme}")
        log(f"  FAIL Z/M decode test errored: {_zme}")

    # 16. v1.60 — end-to-end: envelopes must not trigger a Req 24 Z/M failure ---
    log("STEP: v1.60 — 2D features with XY envelopes produce no Req 24 Z/M mismatch")
    try:
        _env_dir = os.path.join(TEST_ROOT, "envelopes")
        os.makedirs(_env_dir, exist_ok=True)
        _env_gpkg = os.path.join(_env_dir, "env2d.gpkg")
        if os.path.exists(_env_gpkg):
            os.remove(_env_gpkg)
        _ec = sqlite3.connect(_env_gpkg)
        _ecc = base_schema(_ec, gpkg12=True)
        _ecc.execute("INSERT INTO gpkg_spatial_ref_sys VALUES "
                     "('WGS 84', 4326, 'EPSG', 4326, ?, 'World Geodetic System 1984')",
                     (WKT2_4326,))
        _ecc.executescript("""
        CREATE TABLE gpkg_geometry_columns (
          table_name TEXT NOT NULL, column_name TEXT NOT NULL,
          geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL,
          z TINYINT NOT NULL, m TINYINT NOT NULL,
          CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name));
        CREATE TABLE env_poly (
          fid INTEGER PRIMARY KEY AUTOINCREMENT, geom BLOB, name TEXT);
        """)
        # z=0, m=0 — the declaration that the v1.59 decoder contradicted for
        # every geometry carrying an envelope.
        _ecc.execute("INSERT INTO gpkg_geometry_columns VALUES "
                     "('env_poly','geom','POLYGON',4326,0,0)")
        _ecc.execute(
            "INSERT INTO gpkg_contents (table_name,data_type,identifier,"
            "min_x,min_y,max_x,max_y,srs_id,last_change) VALUES "
            "('env_poly','features','env_poly',0,0,1,1,4326,'2026-08-01T00:00:00Z')"
        )
        # Polygon WKB + a real XY envelope — envelope code 1, flags bit 1 set.
        # Under the v1.59 decoder every one of these read as "header Z-flag=1".
        for _n in range(4):
            _ring = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
            _wkb = wkb_polygon([_ring])
            _env = struct.pack("<dddd", 0.0, 1.0, 0.0, 1.0)   # minx,maxx,miny,maxy
            _blob = (b"GP" + bytes([0, (1 << 1) | 0x01])
                     + struct.pack("<i", 4326) + _env + _wkb)
            _ecc.execute("INSERT INTO env_poly (geom,name) VALUES (?,?)",
                         (_blob, f"poly{_n}"))
        _ec.commit()
        _ec.close()

        _env_reports = os.path.join(_env_dir, "reports")
        run_validator(["--offline", "--no-install", "--quiet",
                                   "--output-dir", _env_reports, _env_gpkg])
        _env_json = glob.glob(os.path.join(_env_reports, "*_DGIWG_Report*.json"))
        checks += 1
        if not _env_json:
            failures.append("envelope test: no JSON report was produced")
            log("  FAIL envelope test produced no report")
        else:
            _r24 = json.load(open(_env_json[0], encoding="utf-8"))["requirements"].get("24", {})
            _det = _r24.get("detail", "")
            if "Z/M consistency" in _det:
                failures.append(
                    "Req 24 still reports a Z/M mismatch for 2D geometries "
                    f"carrying an XY envelope: {_det[:300]}"
                )
                log(f"  FAIL Req 24 Z/M mismatch on enveloped 2D geometry: {_det[:200]}")
            else:
                log("  OK   no Req 24 Z/M mismatch for 2D geometries with XY envelopes")
    except Exception as _enve:
        checks += 1
        failures.append(f"envelope end-to-end test could not run: {_enve}")
        log(f"  FAIL envelope end-to-end test errored: {_enve}")

    # 17. v1.60 — Req 33 must not crash when gpkg_extensions is absent ----------
    log("STEP: v1.60 — Req 33 readable FAIL when gpkg_extensions is absent")
    try:
        from dgiwg_validator.checks import _r33
        _g33 = os.path.join(TEST_ROOT, "r33_noext.gpkg")
        if os.path.exists(_g33):
            os.remove(_g33)
        _c33 = sqlite3.connect(_g33)
        _c33.execute(
            "CREATE TABLE gpkg_2d_gridded_coverage_ancillary ("
            "id INTEGER PRIMARY KEY, tile_matrix_set_name TEXT, datatype TEXT, "
            "scale REAL, offset REAL, precision REAL, data_null REAL, "
            "grid_cell_encoding TEXT, uom TEXT, field_name TEXT, "
            "quantity_definition TEXT)"
        )
        _c33.commit()
        _st33, _dt33 = _r33(_c33.cursor())
        _c33.close()
        checks += 1
        if "Exception during check" in _dt33 or "no such table" in _dt33.lower():
            failures.append(f"Req 33 still crashes without gpkg_extensions: {_dt33[:200]}")
            log(f"  FAIL Req 33 raw exception: {_dt33[:160]}")
        elif _st33 != "FAIL" or "gpkg_extensions" not in _dt33:
            failures.append(
                f"Req 33 without gpkg_extensions returned {_st33}: {_dt33[:200]}"
            )
            log(f"  FAIL Req 33 unexpected result {_st33}: {_dt33[:160]}")
        else:
            log("  OK   Req 33 reports the missing gpkg_extensions table in plain text")
    except Exception as _r33e:
        checks += 1
        failures.append(f"Req 33 no-extensions test could not run: {_r33e}")
        log(f"  FAIL Req 33 no-extensions test errored: {_r33e}")

    # 18. v1.60 — every HTTP helper honours --offline ---------------------------
    log("STEP: v1.60 — net._http_get / _http_head are gated by --offline")
    try:
        from dgiwg_validator import config as _cfg
        from dgiwg_validator import net as _net
        _prev_offline = _cfg.OFFLINE
        _cfg.OFFLINE = True
        try:
            _og, _rg = _net._http_get("http://example.invalid/should-never-be-fetched")
            _oh, _rh = _net._http_head("http://example.invalid/should-never-be-fetched")
        finally:
            _cfg.OFFLINE = _prev_offline
        checks += 1
        if _og is not False or "OFFLINE" not in str(_rg).upper():
            failures.append(f"_http_get ignored --offline: {(_og, _rg)}")
            log(f"  FAIL _http_get under --offline returned {(_og, _rg)}")
        else:
            log("  OK   _http_get refuses to run under --offline")
        checks += 1
        if _oh is not False or "OFFLINE" not in str(_rh).upper():
            failures.append(f"_http_head ignored --offline: {(_oh, _rh)}")
            log(f"  FAIL _http_head under --offline returned {(_oh, _rh)}")
        else:
            log("  OK   _http_head refuses to run under --offline")
    except Exception as _offe:
        checks += 1
        failures.append(f"--offline gate test could not run: {_offe}")
        log(f"  FAIL --offline gate test errored: {_offe}")

    # 19. v1.60 — rollup.py has no __main__ guard calling an undefined name -----
    log("STEP: v1.60 — rollup.py __main__ guard removed")
    try:
        _rollup_src = open(os.path.join(HERE, "dgiwg_validator", "rollup.py"),
                           encoding="utf-8").read()
        checks += 1
        # Match an actual guard statement, not the comment that explains its
        # removal: a line starting with `if __name__` at column 0.
        _guard = re.search(r'^if\s+__name__\s*==', _rollup_src, re.MULTILINE)
        if _guard:
            failures.append("rollup.py still calls an undefined main() in a __main__ guard")
            log("  FAIL rollup.py __main__ guard still present")
        else:
            log("  OK   rollup.py has no __main__ guard calling an undefined main()")
    except Exception as _rue:
        checks += 1
        failures.append(f"rollup __main__ test could not run: {_rue}")

    # 20. Summary ----------------------------------------------------------------
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
