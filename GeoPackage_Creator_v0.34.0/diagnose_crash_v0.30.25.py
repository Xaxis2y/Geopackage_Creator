# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.25 - follow-up to v0.30.24.

WHY THIS EXISTS
---------------
v0.30.24 (`diagnose_crash_v0.30.24.py`) tested whether the still-unresolved
`pytest_concurrency` crash needed genuinely fresh, never-before-used OS
threads touching GDAL/lxml for the first time. All four of its probes
(P12-P15) came back OK:

    OK   P12_single_thread_control
    OK   P13_three_threads_full_pipeline
    OK   P14_three_threads_gdal_only
    OK   P15_three_threads_lxml_only

Per that script's own reading guide, "P12 OK, P13 OK -> not reproduced
here; the real crash needs something this probe doesn't model yet."
Thread identity was ruled out. This script tests the next candidate.

THE UNTESTED VARIABLE THIS TIME
--------------------------------
Every probe from P1 through P15 - and `run_release_check_v0.30.23.py`'s own
`batch_conversion_cycle` - hand-reimplemented a MINIMAL stand-in for the real
pipeline: one GDAL write, then one schema compile+validate. That is not what
`test_concurrent_writes_different_files` actually runs. Reading
`core/converter.py`'s real `convert()` line by line, a single call (the
shipped default `generate_reports=True`, which the failing test never
overrides) does ALL of the following, every time:

  1. One GDAL vector write (GDALHandler: create -> copy_layer_to_geopackage
     with per-feature MakeValid()/transform -> close).
  2. THREE separate metadata XML documents per conversion, not one:
     generate_package_metadata() (which itself calls validate_schema()
     internally), generate_dmf_metadata() (no schema call), and one
     generate_layer_metadata() PER LAYER (each of which also calls
     validate_schema() internally) - PLUS converter.py:619 makes a FOURTH,
     fully separate, explicit validate_schema(package_xml) call on top of
     the one generate_package_metadata() already made. That is several
     fresh-compile-and-discard XSD cycles per conversion, not the single
     cycle every earlier probe modeled.
  3. A raw stdlib sqlite3.connect() re-open of the SAME file GDAL just
     closed, to embed metadata (_embed_metadata).
  4. A SECOND raw sqlite3 re-open to finalize DGIWG compliance
     (_finalize_dgiwg_compliance: application_id, WKT2, extension rows).
  5. Output re-validation (validate_gpkg_structure).
  6. HTML + JSON + PDF report generation (generate_reports=True is the
     shipped default AND what the failing test actually uses) - the PDF
     path pulls in reportlab, a dependency no probe before this one has
     ever touched.

None of P1-P15 ever combined ALL of this, concurrently, as the actual
shipped `GeoPackageConverter.convert()` method - every one of them was a
hand-written stand-in. This script stops reimplementing and calls the real,
unmodified production code path directly, from real fresh threads, outside
pytest.

WHAT THIS SCRIPT DECIDES
-------------------------
  P16  Single-thread control. THREE sequential real `GeoPackageConverter(
       profile='military').convert()` calls, one thread, `generate_reports=
       True` (the shipped default). Expected OK - `pytest_main` already
       proved single-threaded conversions with reports on pass (293 tests).
       Included so this log is self-contained before trusting P17-P18.

  P17  Direct reproduction. Three SEPARATE, freshly-created OS threads, each
       running ONE real `convert()` call end-to-end (own generated
       shapefile, own output path, `generate_reports=True`) - i.e. exactly
       `tests/test_concurrency.py::test_concurrent_writes_different_files`,
       reimplemented with zero pytest involvement. No manual lock is added
       here: `convert()` is already decorated with `@_serialize_conversions`
       in the shipped code, so this reproduces the real locking exactly,
       not an approximation of it.

  P18  Same as P17, but `generate_reports=False`. Isolates whether report
       generation (reportlab/PDF, extra file and lxml I/O) is a necessary
       ingredient, or whether the hazard lives in the write+metadata+
       sqlite3-finalize core that runs regardless of report settings.

  Reading the three together:
      P16 OK, P17 OK              -> not reproduced outside pytest either;
                                      pytest's own harness (capture threads,
                                      faulthandler, plugin machinery) is
                                      likely a necessary ingredient, not just
                                      an observer. Next step: drive this same
                                      real-convert-three-threads shape
                                      through `pytest.main()` in-process
                                      rather than pytest's own CLI runner.
      P16 OK, P17 CRASH, P18 OK   -> report generation is NOT the trigger.
                                      The hazard is in the core write +
                                      multi-schema-compile + dual-sqlite3-
                                      reopen sequence itself. Next: bisect
                                      inside that sequence (e.g. does it
                                      survive with only ONE metadata XML
                                      document generated per conversion
                                      instead of four).
      P16 OK, P17 CRASH, P18 CRASH -> report generation is ALSO sufficient
                                      on its own to reproduce, or the crash
                                      surface is large enough that removing
                                      one ingredient doesn't shrink it.
                                      Narrows less than the P18-OK case, but
                                      still confirms the real pipeline (not
                                      pytest) is where to keep looking.
      P16 CRASH                   -> this run's environment does not match
                                      the one every earlier stage passed on -
                                      stop and report before trusting P17/18.

No code fix is proposed alongside this script, matching this project's own
established discipline (see CHANGELOG_v0.30.20.md's correction and
diagnose_crash_v0.30.24.py's own docstring): a theory that looks solid
before a real-machine run has already been wrong twice on this crash. The
fix direction depends entirely on which outcome above this run shows.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.25.py

Writes dev_tools\\logs\\diagnose_v0.30.25_<timestamp>.log incrementally, so a
hard crash still leaves everything up to that point on disk. Send that file
back either way.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path(__file__).resolve().parent / "logs"

_LOG_FH = None


def log(msg: str = "") -> None:
    print(msg, flush=True)
    if _LOG_FH is not None:
        _LOG_FH.write(msg + "\n")
        _LOG_FH.flush()
        os.fsync(_LOG_FH.fileno())


def header(title: str) -> None:
    log("")
    log("=" * 78)
    log(f"  {title}")
    log("=" * 78)


# ---------------------------------------------------------------------------
# Shared preamble for every probe subprocess.
#
# Import order deliberately matches the real crash: under pytest, conftest.py
# (`from osgeo import ogr, osr`, to build fixtures) is imported during
# collection BEFORE test_concurrency.py's own `from core import
# GeoPackageConverter` - and both happen in pytest's single collection
# thread, before any worker thread is created. This preamble reproduces that
# exact order in a plain script's main thread, before spawning workers.
#
# make_shapefile() builds the same shape as tests/conftest.py's
# `sample_shapefile` fixture (5 WGS84 points, one string field) without
# depending on pytest. run_conversion() is
# `test_concurrent_writes_different_files.convert_file()`, unabridged: real
# GeoPackageConverter, real 'military' profile, real output path - the only
# difference is no pytest `results`/`errors` dict, replaced with a plain
# exception so the parent subprocess.run() exit code carries the outcome.
# ---------------------------------------------------------------------------
REAL_PREAMBLE = r'''
import sys, os, shutil, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter


def make_shapefile(tag, tmp_root):
    thread_dir = Path(tmp_root) / f"src_{tag}"
    thread_dir.mkdir(parents=True, exist_ok=True)
    shp_path = thread_dir / "points.shp"
    driver = ogr.GetDriverByName("ESRI Shapefile")
    ds = driver.CreateDataSource(str(thread_dir))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    layer = ds.CreateLayer("points", srs, ogr.wkbPoint)
    layer.CreateField(ogr.FieldDefn("name", ogr.OFTString))
    for i in range(5):
        f = ogr.Feature(layer.GetLayerDefn())
        f.SetField("name", f"Point_{i}")
        f.SetGeometry(ogr.CreateGeometryFromWkt(f"POINT({-120 + i} {40 + i})"))
        layer.CreateFeature(f)
        f = None
    ds = None
    return str(shp_path)


def run_conversion(tag, tmp_root, generate_reports=True):
    local_shp = make_shapefile(tag, tmp_root)
    out_path = str(Path(tmp_root) / f"out_{tag}.gpkg")
    converter = GeoPackageConverter(profile="military")
    result = converter.convert(
        source_geodatabase=local_shp,
        output_geopackage=out_path,
        title=f"Concurrent Test {tag}",
        abstract="Test concurrent writes",
        poc="Test User",
        org="Test Org",
        nation="USA",
        security="UNCLASSIFIED",
        generate_reports=generate_reports,
    )
    if not result.get("success"):
        raise RuntimeError(f"conversion {tag} reported failure: {result.get('error')}")
    return result
'''

PROBES: list[tuple[str, str, str]] = [
    (
        "P16_real_convert_single_thread_control",
        "Control: 3 real GeoPackageConverter.convert() calls (reports ON), "
        "one thread, sequential. pytest_main already proved this shape safe "
        "(293 tests) - included so this log is self-contained and confirms "
        "this run's environment before trusting P17-P18.",
        REAL_PREAMBLE + r'''
tmp_root = tempfile.mkdtemp()
for i in range(3):
    run_conversion(f"p16_{i}", tmp_root, generate_reports=True)
    print(f"P16: sequential real conversion #{i + 1} survived", flush=True)
print("P16 OK", flush=True)
''',
    ),
    (
        "P17_real_convert_three_threads_reports_on",
        "Direct reproduction: test_concurrent_writes_different_files, "
        "reimplemented with zero pytest involvement. 3 fresh OS threads, "
        "each runs ONE real convert() end to end (own shapefile, own output "
        "path, generate_reports=True, the shipped default). No manual lock "
        "added - convert() already carries @_serialize_conversions, so this "
        "exercises the REAL lock, not an approximation of it.",
        REAL_PREAMBLE + r'''
import threading
tmp_root = tempfile.mkdtemp()
errors = {}
def worker(i):
    try:
        run_conversion(f"p17_{i}", tmp_root, generate_reports=True)
        print(f"P17: thread {i} completed real convert() (reports ON)", flush=True)
    except Exception as e:
        errors[i] = str(e)
threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
for t in threads: t.start()
for t in threads: t.join(timeout=60)
if errors:
    print(f"P17: errors: {errors}", flush=True)
    raise SystemExit(1)
print("P17 OK", flush=True)
''',
    ),
    (
        "P18_real_convert_three_threads_reports_off",
        "Same as P17, but generate_reports=False. Isolates whether HTML/"
        "JSON/PDF report generation (reportlab, extra lxml/file I/O - "
        "untouched by every probe before this script) is a necessary "
        "ingredient, or whether the hazard lives in the write + multi-"
        "schema-compile + dual-sqlite3-reopen core that runs regardless.",
        REAL_PREAMBLE + r'''
import threading
tmp_root = tempfile.mkdtemp()
errors = {}
def worker(i):
    try:
        run_conversion(f"p18_{i}", tmp_root, generate_reports=False)
        print(f"P18: thread {i} completed real convert() (reports OFF)", flush=True)
    except Exception as e:
        errors[i] = str(e)
threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
for t in threads: t.start()
for t in threads: t.join(timeout=60)
if errors:
    print(f"P18: errors: {errors}", flush=True)
    raise SystemExit(1)
print("P18 OK", flush=True)
''',
    ),
]


def run_probe(name: str, desc: str, code: str) -> bool:
    header(name)
    log(f"  {desc}")

    f = Path(tempfile.mkdtemp()) / f"{name}.py"
    f.write_text(code, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(f), str(PROJECT_ROOT)],
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        log("  RESULT: TIMEOUT")
        return False

    for line in (proc.stdout or "").splitlines():
        log(f"    {line}")
    for line in (proc.stderr or "").splitlines():
        if "FutureWarning" in line or "warnings.warn" in line:
            continue
        log(f"    [stderr] {line}")

    rc = proc.returncode
    crashed = rc != 0
    tag = "CRASH" if rc in (3221225477, -11, -1073741819) else ("FAIL" if crashed else "OK")
    log(f"  exit code: {rc}   -> {tag}")
    return not crashed


def main() -> int:
    started = datetime.now()
    global _LOG_FH
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"diagnose_v0.30.25_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS FOLLOW-UP (v0.30.25)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.24 ruled out thread identity (P12-P15 all OK) while keeping")
    log("  each thread's workload minimal (1 write + 1 schema compile). This")
    log("  run stops hand-reimplementing the pipeline and calls the REAL,")
    log("  unmodified GeoPackageConverter.convert() - which does 1 write + up")
    log("  to 4 schema compiles + 2 raw sqlite3 reopens + HTML/JSON/PDF report")
    log("  generation per call - from real fresh threads, outside pytest.")

    results = {}
    for name, desc, code in PROBES:
        results[name] = run_probe(name, desc, code)

    header("SUMMARY")
    for name, ok in results.items():
        log(f"  {'OK   ' if ok else 'CRASH'}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P16 OK, P17 OK    -> not reproduced outside pytest either; pytest's")
    log("                       own harness is likely a necessary ingredient,")
    log("                       not just an observer.")
    log("  P16 OK, P17 CRASH, P18 OK")
    log("                    -> report generation is NOT the trigger; the")
    log("                       hazard is in the core write+metadata+sqlite3")
    log("                       sequence itself.")
    log("  P16 OK, P17 CRASH, P18 CRASH")
    log("                    -> report generation is also sufficient alone,")
    log("                       or the hazard is broad enough that removing")
    log("                       one ingredient does not shrink it.")
    log("  P16 CRASH         -> this run's environment does not match the one")
    log("                       every earlier stage passed on - stop and")
    log("                       report before trusting P17/P18.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
