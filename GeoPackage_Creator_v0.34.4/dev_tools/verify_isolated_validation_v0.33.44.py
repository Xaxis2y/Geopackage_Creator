#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Release gate for v0.33.44's isolated XSD-validation design.

The probe runs twelve real conversions in freshly-created Python threads.
Each conversion writes a GeoPackage and invokes the ordinary
``MetadataHandler.validate_schema`` path.  The complete probe runs in a child
process so a native access violation during ordinary interpreter shutdown is
captured as an exit code while this parent still writes a durable log.
"""

from __future__ import annotations

import os
import ast
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "dev_tools" / "logs"
LOG_FILE = None


def log(message: str = "") -> None:
    print(message, flush=True)
    if LOG_FILE is not None:
        LOG_FILE.write(message + "\n")
        LOG_FILE.flush()
        os.fsync(LOG_FILE.fileno())


PROBE = r'''
import sys, tempfile, threading, sqlite3
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter

ROUNDS = 12

def create_source(tag, temporary_root):
    folder = Path(temporary_root) / f"source_{tag}"
    folder.mkdir(parents=True, exist_ok=True)
    shp = folder / "points.shp"
    ds = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(str(folder))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    layer = ds.CreateLayer("points", srs, ogr.wkbPoint)
    layer.CreateField(ogr.FieldDefn("name", ogr.OFTString))
    for index in range(3):
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetField("name", f"Point {index}")
        feature.SetGeometry(ogr.CreateGeometryFromWkt(f"POINT({-75 + index} {45 + index})"))
        layer.CreateFeature(feature)
        feature = None
    ds = None
    return str(shp)


temporary_root = tempfile.mkdtemp(prefix="gpkg_v03344_")
for round_number in range(ROUNDS):
    error = {}
    def convert_once():
        try:
            source = create_source(f"{round_number}", temporary_root)
            output = str(Path(temporary_root) / f"output_{round_number}.gpkg")
            result = GeoPackageConverter(profile="military").convert(
                source_geodatabase=source,
                output_geopackage=output,
                title=f"Isolated validation round {round_number}",
                abstract="Native stability verification",
                poc="Test User", org="Test Organization", nation="USA",
                security="UNCLASSIFIED", language="eng",
                topic_category="location", generate_reports=False,
            )
            if not result.get("success"):
                raise RuntimeError(result.get("error", "conversion returned failure"))
            if not Path(output).is_file():
                raise RuntimeError("conversion reported success but output is missing")
            with sqlite3.connect(output) as conn:
                app_id = conn.execute("PRAGMA application_id").fetchone()[0]
                user_version = conn.execute("PRAGMA user_version").fetchone()[0]
            if (app_id, user_version) != (0x47504B47, 10400):
                raise RuntimeError(
                    f"non-conformant GeoPackage header: application_id=0x{app_id:08X}, "
                    f"user_version={user_version}"
                )
        except Exception as exc:
            error["message"] = f"{type(exc).__name__}: {exc}"

    worker = threading.Thread(target=convert_once, name=f"conversion-{round_number}")
    worker.start()
    worker.join(timeout=180)
    if worker.is_alive():
        raise RuntimeError(f"round {round_number} timed out after 180 seconds")
    if error:
        raise RuntimeError(f"round {round_number} failed: {error['message']}")
    print(f"ROUND {round_number + 1}/{ROUNDS} OK", flush=True)

print("ALL 12 CONVERSIONS OK; returning normally for shutdown verification", flush=True)
'''


def main() -> int:
    global LOG_FILE
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"verify_isolated_validation_v0.33.44_{stamp}.log"
    LOG_FILE = open(log_path, "w", encoding="utf-8", buffering=1)
    log("=" * 78)
    log("  GeoPackage Creator v0.33.44 - isolated validation release gate")
    log("=" * 78)
    log(f"  log file: {log_path}")
    log(f"  python  : {sys.executable}")

    handler_source = ROOT / "core" / "metadata_handler.py"
    helper_source = ROOT / "core" / "schema_validation_worker.py"
    tree = ast.parse(handler_source.read_text(encoding="utf-8"))
    imports_lxml = any(
        isinstance(node, ast.Import) and any(alias.name == "lxml" or alias.name.startswith("lxml.") for alias in node.names)
        or isinstance(node, ast.ImportFrom) and (node.module == "lxml" or (node.module or "").startswith("lxml."))
        for node in ast.walk(tree)
    )
    if imports_lxml:
        log("FAIL: metadata_handler.py still imports lxml in the GDAL process")
        return 1
    if not helper_source.is_file():
        log("FAIL: isolated schema_validation_worker.py is missing")
        return 1
    log("  static isolation guard: PASS")

    probe_path = Path(tempfile.mkdtemp(prefix="gpkg_v03344_probe_")) / "probe.py"
    probe_path.write_text(PROBE, encoding="utf-8")
    try:
        completed = subprocess.run(
            [sys.executable, str(probe_path), str(ROOT)],
            capture_output=True,
            text=True,
            timeout=2400,
        )
    except subprocess.TimeoutExpired:
        log("FAIL: probe timed out after 40 minutes")
        return 1

    for line in completed.stdout.splitlines():
        log(f"  {line}")
    for line in completed.stderr.splitlines():
        log(f"  [stderr] {line}")
    log(f"  probe exit code: {completed.returncode}")

    if completed.returncode == 0:
        log("VERDICT: PASS - 12 real conversions and normal interpreter shutdown completed")
        return 0
    if completed.returncode in (3221225477, -1073741819, -11):
        log("VERDICT: FAIL - native access violation still occurred")
    else:
        log("VERDICT: FAIL - probe did not complete successfully")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        if LOG_FILE is not None:
            LOG_FILE.close()
