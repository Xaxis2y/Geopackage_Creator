#!/usr/bin/env python3
"""
Self-test for GeoPackage Creator.

Creates a tiny known-good source dataset, runs a full conversion, and verifies
the output. If this prints "SELF-TEST PASSED", the conversion engine works and
any hang you see in the GUI is environmental (input data or UI), not the core.

Run from the Anaconda Prompt (the Python that has GDAL/osgeo):

    python selftest_conversion.py
"""

import sys
import time
import sqlite3
import tempfile
from pathlib import Path


def make_sample_source(folder: Path) -> str:
    """Write a small GeoJSON source with 3 point features (EPSG:4326)."""
    geojson = """{
      "type": "FeatureCollection",
      "name": "test_points",
      "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4326"}},
      "features": [
        {"type":"Feature","properties":{"id":1,"name":"A"},"geometry":{"type":"Point","coordinates":[-75.7,45.4]}},
        {"type":"Feature","properties":{"id":2,"name":"B"},"geometry":{"type":"Point","coordinates":[-79.4,43.7]}},
        {"type":"Feature","properties":{"id":3,"name":"C"},"geometry":{"type":"Point","coordinates":[-123.1,49.3]}}
      ]
    }"""
    src = folder / "sample_source.geojson"
    src.write_text(geojson, encoding="utf-8")
    return str(src)


def main() -> int:
    print("=" * 70)
    print(" GeoPackage Creator - SELF TEST")
    print("=" * 70)

    # 1) Confirm GDAL is importable in THIS Python
    try:
        from osgeo import ogr  # noqa: F401
        print("[ok] osgeo (GDAL) is available")
    except ImportError:
        print("[FAIL] osgeo (GDAL) is NOT available to this Python.")
        print("       Run this from the Anaconda Prompt where the GUI works.")
        return 1

    try:
        from core.converter import GeoPackageConverter
    except Exception as e:
        print(f"[FAIL] Could not import the converter: {e}")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        source = make_sample_source(tmp)
        output = str(tmp / "selftest_output.gpkg")
        print(f"[..] Source: {source}")
        print(f"[..] Output: {output}")
        print("[..] Running conversion (a hang here means the ENGINE is stuck)...")

        start = time.time()
        converter = GeoPackageConverter(profile="default")
        result = converter.convert(
            source_geodatabase=source,
            output_geopackage=output,
            title="Self Test Dataset",
            abstract="Automated self-test of the conversion pipeline.",
            poc="Self Test",
            org="MCE",
            nation="CAN",
            generate_reports=False,
        )
        elapsed = time.time() - start
        print(f"[..] convert() returned in {elapsed:.2f}s")

        if not result.get("success"):
            print(f"[FAIL] Conversion reported failure: {result.get('error')}")
            return 1

        # Verify the output really exists and is a valid GeoPackage
        if not Path(output).exists():
            print("[FAIL] Output .gpkg was not created.")
            return 1

        try:
            conn = sqlite3.connect(output)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM gpkg_contents")
            n_contents = cur.fetchone()[0]
            cur.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='gpkg_metadata'"
            )
            has_metadata = cur.fetchone() is not None
            conn.close()
        except Exception as e:
            print(f"[FAIL] Output is not a readable GeoPackage: {e}")
            return 1

        print("-" * 70)
        print(f"  Layers converted : {result.get('layer_count')}")
        print(f"  Total features   : {result.get('total_features')}")
        print(f"  gpkg_contents    : {n_contents} row(s)")
        print(f"  metadata table   : {'present' if has_metadata else 'MISSING'}")
        print(f"  DGIWG compliant  : {result.get('dgiwg_compliant')}")
        print("-" * 70)

        ok = (
            result.get("layer_count", 0) >= 1
            and result.get("total_features", 0) == 3
            and n_contents >= 1
        )
        if ok:
            print("SELF-TEST PASSED - the conversion engine works correctly.")
            return 0
        print("[FAIL] Conversion ran but output did not match expectations.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
