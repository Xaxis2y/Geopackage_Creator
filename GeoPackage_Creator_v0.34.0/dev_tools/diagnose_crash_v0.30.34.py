# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.34 - correcting a bug in
v0.30.33's own harness, not just refining it (same situation v0.30.28 was
in relative to v0.30.27's P23/P24 - see that script's own docstring).

WHAT v0.30.33 ACTUALLY SHOWED (AND WHY IT IS NOT A CLEAN ANSWER)
--------------------------------------------------------------------
    CRASH  P48_control_no_patch
    CRASH  P49_thread_a_gdal_only_thread_b_real_lxml   <- NOT a real crash
    CRASH  P50_thread_a_real_lxml_thread_b_gdal_only   <- NOT a real crash

The SUMMARY block printed "CRASH" for P49 and P50, but the per-probe detail
lines directly above it tell a different story:

    P49: errors: {1: "ISO 19115 schema validation failed:
      Line 1: Element 'x': No matching global declaration available for
      the validation root."}
    exit code: 1   -> FAIL

    P50: thread A errors: {0: "ISO 19115 schema validation failed: ..."}
    exit code: 1   -> FAIL

Exit code 1 is an ordinary Python `ValueError`, not a native access
violation - `"<x/>"` is not a valid `MD_Metadata` root element, so real
schema validation correctly REJECTS it, every time it gets far enough to
check. That rejection is expected and harmless - every real call site in
the shipped pipeline (`metadata_handler.py:846`/`:1105`,
`converter.py:619`) already wraps this exact call in
`except ValueError: log and continue`, which is exactly why v0.30.30's
P40 could validate the same trivial `"<x/>"` through the REAL call sites
without incident. P49/P50's `lxml_only_turn_real()` called
`_ORIG_VALIDATE_SCHEMA` directly and unwrapped, bypassing that tolerance -
a bug in this diagnostic script, not a finding about the product. P50 is
worse than inconclusive: thread A's expected `ValueError` was treated as
fatal by the orchestration code, so the script exited before thread B -
the entire point of P50 - ever ran at all.

There is a second, independent bug this exposed: `main()`'s SUMMARY block
only ever prints "OK" or "CRASH" because `run_probe()` returns a plain
bool. Every earlier script in this series only ever produced a genuine
`exit code 0` or a genuine native fault, so this never mattered before -
this is the first time a probe has hit an ordinary, non-crashing Python
exception, and the summary silently collapsed "FAIL" into "CRASH" when it
happened. Both bugs are fixed below. Neither one changes any conclusion
already drawn through v0.30.32 (P17 through P48's controls, and P36-P47)
- every one of those either exited 0 or exited with a genuine native fault
code, never an ordinary exception, so none of them were mis-tagged.

THE FIX
-------
1. `lxml_only_turn_real()` now catches exactly the expected "ISO 19115
   schema validation failed" `ValueError` and treats it as a normal,
   successful turn - mirroring what the real pipeline's own call sites
   already do. Any OTHER exception (a real bug, a crash-adjacent Python-
   level symptom, anything unexpected) still propagates and still fails
   the probe.
2. `run_probe()` now returns the actual tag ("OK" / "FAIL" / "CRASH"), and
   `main()`'s SUMMARY prints that tag directly instead of re-deriving a
   collapsed binary from it.

This script does not change what P49/P50 were trying to test - it reruns
the same two experiments, correctly this time, under new probe numbers
(P51 is a fresh control; P52/P53 are the corrected P49/P50), the same way
v0.30.28 gave its corrected P23/P24 the new numbers P25/P26 rather than
reusing the old ones.

WHAT THIS SCRIPT DECIDES
-------------------------
  P51  Control. No patch at all. Expected CRASH, matching P48/P45/P41/P36/
       P27/P17-19 - confirms this harness before trusting P52/P53.

  P52  Corrected P49. Thread A: real, complete convert() with
       validate_schema neutered process-wide - real GDAL, zero real lxml
       in thread A. Thread B: NO GDAL at all - one real lxml touch via the
       saved original validate_schema, now correctly tolerating the
       expected schema-rejection ValueError instead of mistaking it for a
       failure. Tests whether thread A needs to touch lxml itself, or
       GDAL-anywhere plus a new thread's first real lxml touch is
       sufficient alone.

  P53  Corrected P50, the exact reverse of P52. Thread A: one real lxml
       touch, no GDAL - this time actually surviving its expected
       ValueError so thread B gets to run at all. Thread B: real,
       complete convert() with validate_schema neutered - zero real lxml
       in thread B. Tests whether a new thread's first real GDAL write,
       after an earlier thread's lxml-only activity, crashes - or whether
       the danger is specifically GDAL-then-lxml and not the reverse.

  Reading the results (unchanged from v0.30.33's intent):
      P51 OK                  -> this harness is not faithfully
                                  reproducing the crash; stop and compare
                                  it against P48 before trusting P52/P53.
      P51 CRASH, P52 CRASH     -> thread A's own lxml activity is NOT
                                  necessary; GDAL anywhere + a new
                                  thread's first real lxml touch is
                                  sufficient alone. Decouples the two
                                  roles for future, cheaper probes.
      P51 CRASH, P52 OK        -> thread A needs to touch BOTH GDAL and
                                  lxml itself for the hazard to exist.
      P52 CRASH, P53 OK        -> DIRECTION matters: GDAL first, then a
                                  new thread's lxml touch - the reverse
                                  (GDAL in the new thread) is safe.
      P52 CRASH, P53 CRASH     -> symmetric; any two-thread interleaving
                                  of GDAL and lxml crashes, regardless of
                                  which thread does which.
      Any probe tagged FAIL (not OK, not CRASH) -> something unexpected
                                  happened that is neither a clean pass
                                  nor a native crash; read the printed
                                  error text before drawing any conclusion
                                  from it.

No code fix to the shipped product is proposed alongside this script -
same discipline as every diagnostic before it in this series. The two
fixes above are to this dev_tools harness only.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.34.py

Writes dev_tools\\logs\\diagnose_v0.30.34_<timestamp>.log incrementally, so a
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
# P51 (control): real convert(), unmodified, through the same harness as
# every P-control before it.
# ---------------------------------------------------------------------------
P51_SCRIPT = r'''
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
        run_conversion(f"P51_{i}", tmp_root)
        print(f"P51: thread {i} completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

print("P51: starting thread A, will wait for it to fully finish...", flush=True)
t_a = threading.Thread(target=worker, args=(0,))
t_a.start()
t_a.join(timeout=60)
if 0 in errors:
    print(f"P51: thread A errors: {errors}", flush=True)
    raise SystemExit(1)

print("P51: thread A finished cleanly. Starting thread B (a genuinely different, "
      "freshly-created OS thread) now...", flush=True)
t_b = threading.Thread(target=worker, args=(1,))
t_b.start()
t_b.join(timeout=60)
if errors:
    print(f"P51: errors: {errors}", flush=True)
    raise SystemExit(1)

print("P51 OK", flush=True)
'''


# ---------------------------------------------------------------------------
# P52 (corrected P49): thread A does the real, complete convert() but with
# validate_schema neutered process-wide (real GDAL, zero real lxml in
# thread A). Thread B does NO GDAL at all - one real lxml touch via the
# saved original validate_schema, now correctly tolerating the expected
# "schema validation failed" ValueError instead of mistaking it for a
# probe failure.
# ---------------------------------------------------------------------------
P52_SCRIPT = r'''
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
    matter to the crash, so there is no need to generate a full one here.

    v0.30.34 FIX: "<x/>" is not a valid MD_Metadata root, so real schema
    validation correctly raises ValueError("ISO 19115 schema validation
    failed...") every time it gets far enough to check - that is expected
    and harmless, exactly what the real pipeline's own call sites
    (metadata_handler.py:846/1105, converter.py:619) already tolerate by
    catching ValueError and continuing. v0.30.33 called this unwrapped and
    mistook that expected rejection for a probe failure. Any OTHER
    exception still propagates - this only tolerates the one specific,
    expected message.
    """
    handler = MetadataHandler()
    try:
        _ORIG_VALIDATE_SCHEMA(handler, "<x/>")
    except ValueError as e:
        if "ISO 19115 schema validation failed" not in str(e):
            raise


tmp_root = tempfile.mkdtemp()
errors = {}

def worker_a(i):
    try:
        run_conversion_gdal_only(f"P52_{i}", tmp_root)
        print(f"P52: thread {i} (A, real GDAL, lxml neutered) completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

def worker_b(i):
    try:
        lxml_only_turn_real(f"P52_{i}")
        print(f"P52: thread {i} (B, real lxml touch, NO GDAL at all) completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

print("P52: starting thread A (real GDAL write, lxml neutered), will wait for it to fully finish...", flush=True)
t_a = threading.Thread(target=worker_a, args=(0,))
t_a.start()
t_a.join(timeout=60)
if 0 in errors:
    print(f"P52: thread A errors: {errors}", flush=True)
    raise SystemExit(1)

print("P52: thread A finished cleanly. Starting thread B (a genuinely different, "
      "freshly-created OS thread - one real lxml touch, no GDAL at all) now...", flush=True)
t_b = threading.Thread(target=worker_b, args=(1,))
t_b.start()
t_b.join(timeout=60)
if errors:
    print(f"P52: errors: {errors}", flush=True)
    raise SystemExit(1)

print("P52 OK", flush=True)
'''


# ---------------------------------------------------------------------------
# P53 (corrected P50): the exact reverse of P52. Thread A: one real lxml
# touch, no GDAL - now correctly tolerating the expected ValueError so
# thread B actually gets to run this time. Thread B: the real, complete
# convert() with validate_schema neutered, so thread B's own lxml activity
# is exactly zero.
# ---------------------------------------------------------------------------
P53_SCRIPT = r'''
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
    P52's thread-A job - here it is thread B's job instead."""
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
    validate_schema. Identical to P52's thread-B job - here it is thread
    A's job instead.

    v0.30.34 FIX: same as P52 - tolerates the one expected, harmless
    "ISO 19115 schema validation failed" ValueError from validating a
    trivial, intentionally-non-conformant document. v0.30.33's P50 did not
    do this, so thread A's expected rejection was treated as fatal and
    thread B - the entire point of this probe - never ran at all.
    """
    handler = MetadataHandler()
    try:
        _ORIG_VALIDATE_SCHEMA(handler, "<x/>")
    except ValueError as e:
        if "ISO 19115 schema validation failed" not in str(e):
            raise


tmp_root = tempfile.mkdtemp()
errors = {}

def worker_a(i):
    try:
        lxml_only_turn_real(f"P53_{i}")
        print(f"P53: thread {i} (A, real lxml touch, NO GDAL at all) completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

def worker_b(i):
    try:
        run_conversion_gdal_only(f"P53_{i}", tmp_root)
        print(f"P53: thread {i} (B, real GDAL, lxml neutered) completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

print("P53: starting thread A (real lxml touch, no GDAL at all), will wait for it to fully finish...", flush=True)
t_a = threading.Thread(target=worker_a, args=(0,))
t_a.start()
t_a.join(timeout=60)
if 0 in errors:
    print(f"P53: thread A errors: {errors}", flush=True)
    raise SystemExit(1)

print("P53: thread A finished cleanly. Starting thread B (a genuinely different, "
      "freshly-created OS thread - real GDAL write, lxml neutered) now...", flush=True)
t_b = threading.Thread(target=worker_b, args=(1,))
t_b.start()
t_b.join(timeout=60)
if errors:
    print(f"P53: errors: {errors}", flush=True)
    raise SystemExit(1)

print("P53 OK", flush=True)
'''


PROBES: list[tuple[str, str, str]] = [
    (
        "P51_control_no_patch",
        "Control: the real, complete convert() (all internal steps run for "
        "real), through this script's own harness. Expected CRASH, matching "
        "P48/P45/P41/P36/P27/P17-19 - confirms this harness before trusting "
        "P52/P53.",
        P51_SCRIPT,
    ),
    (
        "P52_thread_a_gdal_only_thread_b_real_lxml",
        "Corrected P49. Thread A: real, complete convert() but "
        "validate_schema neutered process-wide - real GDAL, zero real lxml "
        "in thread A. Thread B: NO GDAL at all - one real lxml touch, now "
        "correctly tolerating the expected schema-rejection ValueError. "
        "Tests whether thread A needs to touch lxml itself, or GDAL-"
        "anywhere plus a new thread's first real lxml touch is sufficient "
        "alone.",
        P52_SCRIPT,
    ),
    (
        "P53_thread_a_real_lxml_thread_b_gdal_only",
        "Corrected P50, the exact reverse of P52. Thread A: one real lxml "
        "touch, no GDAL - now actually surviving its expected ValueError so "
        "thread B gets to run. Thread B: real, complete convert() with "
        "validate_schema neutered - zero real lxml in thread B. Tests "
        "whether a new thread's first real GDAL write, after an earlier "
        "thread's lxml-only activity, crashes.",
        P53_SCRIPT,
    ),
]


def run_probe(name: str, desc: str, code: str) -> str:
    """Runs one probe and returns its tag: "OK", "FAIL", or "CRASH".

    v0.30.34 FIX: previously returned a bare bool, which forced main()'s
    SUMMARY block to collapse "FAIL" (an ordinary, non-crashing Python
    exception) into the same bucket as "CRASH" (a native access
    violation). Returning the real tag lets the summary report exactly
    what happened.
    """
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
        return "FAIL"

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
    return tag


def main() -> int:
    started = datetime.now()
    global _LOG_FH
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"diagnose_v0.30.34_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS FOLLOW-UP (v0.30.34)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.33's P49/P50 both hit a bug in THIS diagnostic script, not a")
    log("  finding about the product: validating the trivial '<x/>' document")
    log("  directly (bypassing the real pipeline's own ValueError tolerance)")
    log("  raised an ordinary, expected, non-crashing exception that a second")
    log("  bug in this script's own SUMMARY block then mis-reported as CRASH.")
    log("  P50 never even reached thread B. Both bugs are fixed below and")
    log("  P49/P50's intent is rerun cleanly as P52/P53.")

    tags = {}
    for name, desc, code in PROBES:
        tags[name] = run_probe(name, desc, code)

    header("SUMMARY")
    for name, tag in tags.items():
        label = {"OK": "OK   ", "FAIL": "FAIL ", "CRASH": "CRASH"}[tag]
        log(f"  {label}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P51 OK                  -> this harness is not faithfully")
    log("                             reproducing the crash - compare")
    log("                             against P48 before trusting P52/P53.")
    log("  P51 CRASH, P52 CRASH     -> thread A's own lxml activity is NOT")
    log("                             necessary; GDAL anywhere + a new")
    log("                             thread's first real lxml touch is")
    log("                             sufficient alone.")
    log("  P51 CRASH, P52 OK        -> thread A needs to touch BOTH GDAL and")
    log("                             lxml itself for the hazard to exist.")
    log("  P52 CRASH, P53 OK        -> DIRECTION matters: GDAL first, then a")
    log("                             new thread's lxml touch - the reverse")
    log("                             (GDAL in the new thread) is safe.")
    log("  P52 CRASH, P53 CRASH     -> symmetric; any two-thread")
    log("                             interleaving of GDAL and lxml crashes,")
    log("                             regardless of which thread does which.")
    log("  Any probe tagged FAIL     -> something unexpected happened that is")
    log("                             neither a clean pass nor a native")
    log("                             crash; read the printed error text")
    log("                             before drawing any conclusion from it.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
