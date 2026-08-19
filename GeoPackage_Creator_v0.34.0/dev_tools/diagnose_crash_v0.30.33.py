# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.33 - follow-up to v0.30.32.

WHAT v0.30.32 FOUND
--------------------
    CRASH  P45_control_no_patch
    OK     P46_lxml_only_both_threads_no_gdal
    OK     P47_lxml_only_single_thread_repeated

P46 and P47 both came back clean. Per this project's own reading guide:
"P45 CRASH, P46 OK -> GDAL involvement (at least once, somewhere) is still
necessary; pure lxml-only across two threads is safe." That is now
confirmed. GDAL is NOT a coincidental witness - it is a real, necessary
ingredient, exactly as `diagnose_crash_v0.30.11.py`/`_v0.30.12.py`
concluded back at the start of this whole investigation. P47 (same
lxml-only work, single thread, no second OS thread at all) also came back
OK, consistent with `diagnose_crash_v0.30.22.py`'s "repeated fresh
compiles... fine every time" finding - nothing here contradicts that.

WHAT THIS LEAVES OPEN
-----------------------
So: two real OS threads, GDAL involved somewhere, a new thread's real
lxml touch - crashes (every control since P17). Two real OS threads, GDAL
involved (P26's minimal `gdal_write()`, real schema file, matching shape)
- does NOT crash. Parser choice, document content, and the `XMLSchema()`
compile step are all eliminated as explanations (v0.30.30/31). What is
still completely untested: WHICH thread needs to touch lxml, and whether
GDAL activity needs to be paired with lxml activity IN THE SAME THREAD,
or can be fully independent.

Every crash probe so far has had thread A run the real, complete
`convert()` - meaning thread A always did BOTH real GDAL work AND real
lxml work itself, in that order, before thread B's later touch. Nobody
has asked whether thread A's own lxml activity matters at all, or whether
"real GDAL happened somewhere in the process" and "a new thread's first
real lxml touch" are actually two fully independent conditions.

WHAT THIS SCRIPT DECIDES
-------------------------
  P48  Control. No patch at all - rerun of P45/P41/P36/P27. Expected
       CRASH. If P48 comes back OK, this harness is not faithfully
       reproducing the crash and P49/P50 cannot be trusted either way.

  P49  Thread A: the real, complete `convert()` - real source shapefile,
       real GDALHandler write, real `close_geopackage()`, real
       `_embed_metadata`/`_finalize_dgiwg_compliance` sqlite3 reopens,
       real output validation re-open - but `MetadataHandler.
       validate_schema` is patched to a no-op process-wide, so thread A's
       OWN lxml/libxml2 activity is exactly zero. Thread B: NO GDAL at
       all - one single, unambiguous real lxml touch, calling the
       ORIGINAL unpatched `validate_schema` directly (saved before the
       patch) on a trivial document (P40 already proved content does not
       matter). Tests whether thread A needs to touch lxml itself, or
       whether real GDAL activity anywhere plus a new thread's first real
       lxml touch is sufficient on its own.

  P50  The exact reverse of P49. Thread A: NO GDAL at all - one real lxml
       touch only. Thread B: the real, complete `convert()`, but with
       `validate_schema` neutered the same way, so thread B's own lxml
       activity is exactly zero. Tests whether a NEW thread's first real
       GDAL write - with zero lxml in that thread - crashes after an
       earlier thread's lxml-only activity, or whether the danger is
       specifically "GDAL first, then a new thread's lxml touch" and not
       the reverse.

  Reading the results:
      P48 OK                  -> this harness is not faithfully
                                  reproducing the crash; stop and compare
                                  it against P45 before trusting P49/P50.
      P48 CRASH, P49 CRASH     -> thread A's own lxml activity is NOT
                                  necessary. Real GDAL happening anywhere
                                  in the process, followed by ANY new
                                  thread's first real lxml touch, is
                                  sufficient - regardless of whether the
                                  GDAL-touching thread ever used lxml
                                  itself. This decouples the two roles:
                                  future probes can vary thread A's GDAL
                                  richness alone against this same cheap
                                  "thread B does one real lxml touch"
                                  pattern, without re-running a full
                                  second real convert() every time.
      P48 CRASH, P49 OK        -> thread A specifically needs to touch
                                  BOTH GDAL and lxml itself for the hazard
                                  to exist for a later thread. Pure GDAL
                                  with nothing else does not set it up.
      P49 CRASH, P50 OK        -> confirms DIRECTION matters: GDAL must
                                  happen first, and the new thread's touch
                                  must be an lxml touch specifically - a
                                  new thread's first GDAL write, after an
                                  earlier thread's lxml-only activity, is
                                  safe. Matches every crash observed so
                                  far firing specifically inside lxml,
                                  never inside a bare GDAL write.
      P49 CRASH, P50 CRASH     -> symmetric - it does not matter which
                                  thread does which library or in what
                                  order; any two-thread interleaving of
                                  GDAL and lxml activity crashes.

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.33.py

Writes dev_tools\\logs\\diagnose_v0.30.33_<timestamp>.log incrementally, so a
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
# P48 (control): real convert(), unmodified, through the same harness as
# every P-control before it.
# ---------------------------------------------------------------------------
P48_SCRIPT = r'''
import sys, tempfile, threading
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


def run_conversion(tag, tmp_root):
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
        generate_reports=True,
    )
    if not result.get("success"):
        raise RuntimeError(f"conversion {tag} reported failure: {result.get('error')}")
    return result


tmp_root = tempfile.mkdtemp()
errors = {}

def worker(i):
    try:
        run_conversion(f"P48_{i}", tmp_root)
        print(f"P48: thread {i} completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

print("P48: starting thread A, will wait for it to fully finish...", flush=True)
t_a = threading.Thread(target=worker, args=(0,))
t_a.start()
t_a.join(timeout=60)
if 0 in errors:
    print(f"P48: thread A errors: {errors}", flush=True)
    raise SystemExit(1)

print("P48: thread A finished cleanly. Starting thread B (a genuinely different, "
      "freshly-created OS thread) now...", flush=True)
t_b = threading.Thread(target=worker, args=(1,))
t_b.start()
t_b.join(timeout=60)
if errors:
    print(f"P48: errors: {errors}", flush=True)
    raise SystemExit(1)

print("P48 OK", flush=True)
'''


# ---------------------------------------------------------------------------
# P49: thread A does the real, complete convert() but with validate_schema
# neutered process-wide (real GDAL, zero real lxml in thread A). Thread B
# does NO GDAL at all - one real lxml touch via the saved original
# validate_schema, bypassing the patch.
# ---------------------------------------------------------------------------
P49_SCRIPT = r'''
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler

_ORIG_VALIDATE_SCHEMA = MetadataHandler.validate_schema

def _noop_validate_schema(self, metadata_xml_string):
    # Every validate_schema call made THROUGH convert() (thread A's own
    # real conversion) lands here and does zero real lxml work. Thread B
    # bypasses this entirely by calling _ORIG_VALIDATE_SCHEMA directly
    # (captured above, before this patch is applied).
    return True

MetadataHandler.validate_schema = _noop_validate_schema


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


def run_conversion_gdal_only(tag, tmp_root):
    """Real, complete convert() - real source shapefile, real GDALHandler
    write, real close_geopackage(), real _embed_metadata/
    _finalize_dgiwg_compliance sqlite3 reopens, real output validation
    re-open - everything the shipped pipeline does, EXCEPT validate_schema
    is neutered process-wide, so this thread's own lxml/libxml2 activity
    is exactly zero."""
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
        generate_reports=True,
    )
    if not result.get("success"):
        raise RuntimeError(f"conversion {tag} reported failure: {result.get('error')}")
    return result


def lxml_only_turn_real(tag):
    """NO GDAL, NO OGR, NO GeoPackageConverter at all - one single,
    unambiguous real lxml touch. Calls the ORIGINAL, unpatched
    validate_schema directly (saved above before the no-op patch), on a
    trivial document - P40 already proved document content does not
    matter, so there is no need to generate a full one here."""
    handler = MetadataHandler()
    _ORIG_VALIDATE_SCHEMA(handler, "<x/>")


tmp_root = tempfile.mkdtemp()
errors = {}

def worker_a(i):
    try:
        run_conversion_gdal_only(f"P49_{i}", tmp_root)
        print(f"P49: thread {i} (A, real GDAL, lxml neutered) completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

def worker_b(i):
    try:
        lxml_only_turn_real(f"P49_{i}")
        print(f"P49: thread {i} (B, real lxml touch, NO GDAL at all) completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

print("P49: starting thread A (real GDAL write, lxml neutered), will wait for it to fully finish...", flush=True)
t_a = threading.Thread(target=worker_a, args=(0,))
t_a.start()
t_a.join(timeout=60)
if 0 in errors:
    print(f"P49: thread A errors: {errors}", flush=True)
    raise SystemExit(1)

print("P49: thread A finished cleanly. Starting thread B (a genuinely different, "
      "freshly-created OS thread - one real lxml touch, no GDAL at all) now...", flush=True)
t_b = threading.Thread(target=worker_b, args=(1,))
t_b.start()
t_b.join(timeout=60)
if errors:
    print(f"P49: errors: {errors}", flush=True)
    raise SystemExit(1)

print("P49 OK", flush=True)
'''


# ---------------------------------------------------------------------------
# P50: the exact reverse of P49. Thread A: one real lxml touch, no GDAL.
# Thread B: the real, complete convert() with validate_schema neutered, so
# thread B's own lxml activity is exactly zero.
# ---------------------------------------------------------------------------
P50_SCRIPT = r'''
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler

_ORIG_VALIDATE_SCHEMA = MetadataHandler.validate_schema

def _noop_validate_schema(self, metadata_xml_string):
    # Every validate_schema call made THROUGH convert() (thread B's own
    # real conversion, this time) lands here and does zero real lxml work.
    return True

MetadataHandler.validate_schema = _noop_validate_schema


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


def run_conversion_gdal_only(tag, tmp_root):
    """Real, complete convert(), validate_schema neutered process-wide, so
    this thread's own lxml/libxml2 activity is exactly zero. Identical to
    P49's thread-A job - here it is thread B's job instead."""
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
        generate_reports=True,
    )
    if not result.get("success"):
        raise RuntimeError(f"conversion {tag} reported failure: {result.get('error')}")
    return result


def lxml_only_turn_real(tag):
    """NO GDAL, NO OGR, NO GeoPackageConverter at all - one single,
    unambiguous real lxml touch via the ORIGINAL unpatched
    validate_schema. Identical to P49's thread-B job - here it is thread
    A's job instead."""
    handler = MetadataHandler()
    _ORIG_VALIDATE_SCHEMA(handler, "<x/>")


tmp_root = tempfile.mkdtemp()
errors = {}

def worker_a(i):
    try:
        lxml_only_turn_real(f"P50_{i}")
        print(f"P50: thread {i} (A, real lxml touch, NO GDAL at all) completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

def worker_b(i):
    try:
        run_conversion_gdal_only(f"P50_{i}", tmp_root)
        print(f"P50: thread {i} (B, real GDAL, lxml neutered) completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

print("P50: starting thread A (real lxml touch, no GDAL at all), will wait for it to fully finish...", flush=True)
t_a = threading.Thread(target=worker_a, args=(0,))
t_a.start()
t_a.join(timeout=60)
if 0 in errors:
    print(f"P50: thread A errors: {errors}", flush=True)
    raise SystemExit(1)

print("P50: thread A finished cleanly. Starting thread B (a genuinely different, "
      "freshly-created OS thread - real GDAL write, lxml neutered) now...", flush=True)
t_b = threading.Thread(target=worker_b, args=(1,))
t_b.start()
t_b.join(timeout=60)
if errors:
    print(f"P50: errors: {errors}", flush=True)
    raise SystemExit(1)

print("P50 OK", flush=True)
'''


PROBES: list[tuple[str, str, str]] = [
    (
        "P48_control_no_patch",
        "Control: the real, complete convert() (all internal steps run for "
        "real), through this script's own harness. Expected CRASH, matching "
        "P45/P41/P36/P27/P17-19 - confirms this harness before trusting "
        "P49/P50.",
        P48_SCRIPT,
    ),
    (
        "P49_thread_a_gdal_only_thread_b_real_lxml",
        "Thread A: real, complete convert() but validate_schema neutered "
        "process-wide - real GDAL, zero real lxml in thread A. Thread B: NO "
        "GDAL at all - one real lxml touch via the saved original "
        "validate_schema. Tests whether thread A needs to touch lxml "
        "itself, or GDAL-anywhere plus a new thread's first real lxml "
        "touch is sufficient alone.",
        P49_SCRIPT,
    ),
    (
        "P50_thread_a_real_lxml_thread_b_gdal_only",
        "The exact reverse of P49. Thread A: one real lxml touch, no GDAL. "
        "Thread B: real, complete convert() with validate_schema neutered - "
        "zero real lxml in thread B. Tests whether a new thread's first "
        "real GDAL write, after an earlier thread's lxml-only activity, "
        "crashes - or whether the danger is specifically GDAL-then-lxml "
        "and not the reverse.",
        P50_SCRIPT,
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
    path = LOG_DIR / f"diagnose_v0.30.33_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS FOLLOW-UP (v0.30.33)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.32 confirmed GDAL is a real, necessary ingredient (P46/P47")
    log("  OK - no crash anywhere without it), reconfirming the project's")
    log("  original v0.30.11/12 finding. What has never been tested is WHICH")
    log("  thread needs to touch lxml, and whether GDAL activity needs to be")
    log("  paired with lxml activity in the SAME thread, or can be fully")
    log("  independent. Every crash so far has had thread A do both GDAL and")
    log("  lxml itself. This run separates the two roles.")

    results = {}
    for name, desc, code in PROBES:
        results[name] = run_probe(name, desc, code)

    header("SUMMARY")
    for name, ok in results.items():
        log(f"  {'OK   ' if ok else 'CRASH'}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P48 OK                  -> this harness is not faithfully")
    log("                             reproducing the crash - compare")
    log("                             against P45 before trusting P49/P50.")
    log("  P48 CRASH, P49 CRASH     -> thread A's own lxml activity is NOT")
    log("                             necessary; GDAL anywhere + a new")
    log("                             thread's first real lxml touch is")
    log("                             sufficient alone. Decouples the two")
    log("                             roles for future, cheaper probes.")
    log("  P48 CRASH, P49 OK        -> thread A needs to touch BOTH GDAL and")
    log("                             lxml itself for the hazard to exist.")
    log("  P49 CRASH, P50 OK        -> DIRECTION matters: GDAL first, then a")
    log("                             new thread's lxml touch - the reverse")
    log("                             (GDAL in the new thread) is safe.")
    log("  P49 CRASH, P50 CRASH     -> symmetric; any two-thread")
    log("                             interleaving of GDAL and lxml crashes,")
    log("                             regardless of which thread does which.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
