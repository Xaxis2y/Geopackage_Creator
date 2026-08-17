#!/usr/bin/env python3
"""Run twelve real CLI conversions through the frozen executable."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "dev_tools" / "logs"


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "GeoPackageCreator.exe"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"verify_frozen_exe_v0.33.44_{datetime.now():%Y%m%d_%H%M%S}.log"
    with log_path.open("w", encoding="utf-8", buffering=1) as log:
        def write(text: str) -> None:
            print(text, flush=True); log.write(text + "\n"); log.flush(); os.fsync(log.fileno())
        write(f"Frozen EXE gate; executable: {exe}")
        if not exe.is_file():
            write("FAIL: executable not found. Build first with packaging\\build_windows.ps1 -UseCurrentEnv")
            return 1
        from osgeo import ogr, osr
        temp = Path(tempfile.mkdtemp(prefix="gpkg_frozen_"))
        for number in range(12):
            folder = temp / f"src_{number}"; folder.mkdir()
            source = folder / "points.shp"
            ds = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(str(folder))
            srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
            layer = ds.CreateLayer("points", srs, ogr.wkbPoint)
            layer.CreateField(ogr.FieldDefn("name", ogr.OFTString))
            feature = ogr.Feature(layer.GetLayerDefn()); feature.SetField("name", "probe")
            feature.SetGeometry(ogr.CreateGeometryFromWkt("POINT(-75 45)")); layer.CreateFeature(feature)
            feature = None; ds = None
            output = temp / f"frozen_{number}.gpkg"
            command = [str(exe), "--source", str(source), "--output", str(output), "--title", "Frozen stability probe", "--org", "Test Organization", "--nation", "USA", "--poc", "Test User", "--abstract", "Frozen executable stability validation", "--security", "UNCLASSIFIED", "--category", "location", "--profile", "military", "--quiet"]
            run = subprocess.run(command, capture_output=True, text=True, timeout=300)
            if run.returncode != 0 or not output.is_file():
                write(f"FAIL round {number + 1}: exit={run.returncode}\n{run.stdout}\n{run.stderr}"); return 1
            with sqlite3.connect(output) as conn:
                app_id = conn.execute("PRAGMA application_id").fetchone()[0]
                user_version = conn.execute("PRAGMA user_version").fetchone()[0]
            if (app_id, user_version) != (0x47504B47, 10400):
                write(f"FAIL round {number + 1}: header app_id=0x{app_id:08X}, user_version={user_version}"); return 1
            write(f"ROUND {number + 1}/12 OK (GPKG, user_version=10400)")
        write("VERDICT: PASS - frozen executable completed 12 conversions with OGC-standard headers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
