# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.35 - follow-up to v0.30.34.

WHAT v0.30.34 FOUND
--------------------
    CRASH  P51_control_no_patch
    OK     P52_thread_a_gdal_only_thread_b_real_lxml
    OK     P53_thread_a_real_lxml_thread_b_gdal_only

Both corrected probes came back clean this time - a real result, not a
harness bug. Per the project's own reading guide: "P51 CRASH, P52 OK ->
thread A needs to touch BOTH GDAL and lxml itself for the hazard to
exist." That is now confirmed, and P53 adds the mirror image: a new
thread's first real GDAL write, with zero lxml in that thread, is safe
too, no matter what an earlier thread did.

Read against every result gathered since v0.30.30, the necessary
condition is now pinned down precisely for the first time in this whole
series: ONE thread must do a real GDAL write followed by a real lxml
schema-file parse ITSELF, in that order, in that same thread (every
control, P17 through P51, does exactly this). Only THEN does a later,
different, freshly-created OS thread's first real lxml touch crash - and
that later thread needs nothing of its own except the lxml touch (P37),
with any parser (P42/P43), touching any document (P40), not even needing
to finish a full schema compile (P44). Split the GDAL and the lxml across
two threads that each do only one - in either order (P52, P53) - and nothing
crashes at all, not once.

WHAT THIS MEANS FOR A MITIGATION (STILL NOT A FIX - A TEST OF ONE)
----------------------------------------------------------------------
This is the first point in the whole investigation where the accumulated
evidence points at a concrete, testable mitigation *pattern*, not just
another bisection of the failure. If no thread is ever allowed to do both
GDAL and lxml itself - if every conversion's GDAL write happens on its own
worker thread (as today), but EVERY lxml/schema-validation call in the
whole process is routed to one single, persistent worker thread that is
created once and reused for the life of the program, never recreated -
then, by everything confirmed so far, no thread would ever do "GDAL then
lxml itself," and no new thread would ever be the one making its first
lxml touch right after such a thread. P52 already shows this is safe for
ONE round. It has never been tested across MANY rounds, which is what the
shipped GUI actually does over a real session - repeated conversions, each
presumably on its own new worker thread.

This script tests that specific pattern directly, repeated, before anyone
proposes changing the shipped code. It is still a diagnostic, not a fix -
no production code is touched here, and if this comes back clean it is
evidence FOR a mitigation shape, not a guarantee, and not yet an
implementation.

WHAT THIS SCRIPT DECIDES
-------------------------
  P54  Control. No patch at all. Expected CRASH, matching P51/P48/P45/P41/
       P36/P27/P17-19 - confirms this harness before trusting P55.

  P55  Five rounds. Each round: a brand-new OS thread runs the real,
       complete convert() with validate_schema neutered (real GDAL write,
       zero lxml in that thread - identical shape to P52/P53's GDAL-only
       job), joined to completion. Its metadata validation is then
       dispatched over a queue to ONE persistent lxml worker thread -
       created once, before round 0, and reused for every single round -
       which calls the real, original validate_schema and reports back.
       No thread in this probe ever does both GDAL and lxml itself. If
       all five rounds complete with zero crashes, that is real evidence
       the "one persistent, dedicated lxml thread" pattern holds up under
       repetition, not just once.

  Reading the results:
      P54 OK                  -> this harness is not faithfully
                                  reproducing the crash; stop and compare
                                  it against P51 before trusting P55.
      P54 CRASH, P55 OK (5/5)  -> the mitigation pattern survives repeated,
                                  realistic use. Worth prototyping for
                                  real, with the same discipline this
                                  series has used throughout - proven on
                                  this machine before it is trusted.
      P54 CRASH, P55 fails on some round N > 0
                               -> the pattern is not simply safe forever;
                                  something accumulates over repeated
                                  rounds that a single clean round (P52)
                                  did not reveal. Worth knowing exactly
                                  which round it broke on and how many
                                  rounds preceded it.
      P54 CRASH, P55 fails on round 0
                               -> would contradict P52 outright and needs
                                  reconciling before anything else.

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series. This tests whether a pattern is
*safe*, which is a prerequisite for a fix, not a fix itself.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.35.py

Writes dev_tools\\logs\\diagnose_v0.30.35_<timestamp>.log incrementally, so a
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
# P54 (control): real convert(), unmodified, through the same harness as
# every P-control before it.
# ---------------------------------------------------------------------------
P54_SCRIPT = r'''
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
        run_conversion(f"P54_{i}", tmp_root)
        print(f"P54: thread {i} completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

print("P54: starting thread A, will wait for it to fully finish...", flush=True)
t_a = threading.Thread(target=worker, args=(0,))
t_a.start()
t_a.join(timeout=60)
if 0 in errors:
    print(f"P54: thread A errors: {errors}", flush=True)
    raise SystemExit(1)

print("P54: thread A finished cleanly. Starting thread B (a genuinely different, "
      "freshly-created OS thread) now...", flush=True)
t_b = threading.Thread(target=worker, args=(1,))
t_b.start()
t_b.join(timeout=60)
if errors:
    print(f"P54: errors: {errors}", flush=True)
    raise SystemExit(1)

print("P54 OK", flush=True)
'''


# ---------------------------------------------------------------------------
# P55: five rounds of "new GDAL-only worker thread, then dispatch its
# metadata validation to ONE persistent lxml worker thread" - the candidate
# mitigation pattern, tested repeated rather than just once.
# ---------------------------------------------------------------------------
P55_SCRIPT = r'''
import queue
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler

ROUNDS = 5

_ORIG_VALIDATE_SCHEMA = MetadataHandler.validate_schema

def _noop_validate_schema(self, metadata_xml_string):
    # Every validate_schema call made THROUGH convert() lands here and does
    # zero real lxml work - each round's GDAL worker thread never touches
    # lxml itself. All real lxml work happens only on the one persistent
    # worker thread below, via _ORIG_VALIDATE_SCHEMA.
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
    """Real, complete convert(), validate_schema neutered process-wide -
    real GDAL, zero real lxml in this thread. Identical shape to P52/P53's
    GDAL-only job."""
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


# --- The candidate mitigation: ONE persistent lxml worker thread, created
# once, before round 0, and reused for every round's validation - never
# recreated, never doing any GDAL work of its own. ---
_lxml_jobs = queue.Queue()
_lxml_results = queue.Queue()
_LXML_STOP = object()

def _lxml_worker():
    while True:
        item = _lxml_jobs.get()
        if item is _LXML_STOP:
            _lxml_results.put(("stopped", None))
            return
        tag = item
        try:
            handler = MetadataHandler()
            try:
                _ORIG_VALIDATE_SCHEMA(handler, "<x/>")
            except ValueError as e:
                # Expected, harmless rejection of a trivial, intentionally
                # non-conformant document - see v0.30.34's fix. Any OTHER
                # exception still propagates below.
                if "ISO 19115 schema validation failed" not in str(e):
                    raise
            _lxml_results.put(("ok", tag))
        except Exception as e:
            _lxml_results.put(("error", f"{tag}: {e}"))

_lxml_thread = threading.Thread(target=_lxml_worker, daemon=True)
_lxml_thread.start()

def validate_via_persistent_thread(tag, timeout=20):
    _lxml_jobs.put(tag)
    try:
        status, payload = _lxml_results.get(timeout=timeout)
    except queue.Empty:
        raise RuntimeError(f"{tag}: persistent lxml worker did not respond within {timeout}s")
    if status == "error":
        raise RuntimeError(payload)
    return payload


tmp_root = tempfile.mkdtemp()
errors = {}

for round_i in range(ROUNDS):
    tag = f"P55_r{round_i}"
    print(f"P55: round {round_i} - starting a NEW GDAL-only worker thread...", flush=True)

    gdal_error = {}
    def gdal_worker():
        try:
            run_conversion_gdal_only(tag, tmp_root)
        except Exception as e:
            gdal_error["e"] = str(e)

    t = threading.Thread(target=gdal_worker)
    t.start()
    t.join(timeout=30)
    if "e" in gdal_error:
        print(f"P55: round {round_i} GDAL thread error: {gdal_error['e']}", flush=True)
        errors[round_i] = f"gdal: {gdal_error['e']}"
        break
    print(f"P55: round {round_i} GDAL thread completed its FULL turn (patch=lxml neutered).",
          flush=True)

    print(f"P55: round {round_i} - dispatching validation to the ONE persistent lxml "
          f"worker thread (created once before round 0, reused every round)...", flush=True)
    try:
        validate_via_persistent_thread(tag)
        print(f"P55: round {round_i} validation completed via the persistent lxml thread",
              flush=True)
    except Exception as e:
        print(f"P55: round {round_i} validation error: {e}", flush=True)
        errors[round_i] = f"lxml: {e}"
        break

_lxml_jobs.put(_LXML_STOP)
try:
    _lxml_results.get(timeout=15)
except queue.Empty:
    pass

if errors:
    print(f"P55: errors: {errors}", flush=True)
    raise SystemExit(1)

print(f"P55 OK - all {ROUNDS} rounds completed with zero crashes using one "
      f"persistent lxml worker thread reused throughout", flush=True)
'''


PROBES: list[tuple[str, str, str, int]] = [
    (
        "P54_control_no_patch",
        "Control: the real, complete convert() (all internal steps run for "
        "real), through this script's own harness. Expected CRASH, matching "
        "P51/P48/P45/P41/P36/P27/P17-19 - confirms this harness before "
        "trusting P55.",
        P54_SCRIPT,
        180,
    ),
    (
        "P55_persistent_lxml_thread_five_rounds",
        "Five rounds of: a brand-new GDAL-only worker thread (real convert(), "
        "lxml neutered), then dispatch its metadata validation over a queue "
        "to ONE persistent lxml worker thread created once before round 0 "
        "and reused every round. No thread ever does both GDAL and lxml "
        "itself. Tests whether this candidate mitigation pattern holds up "
        "under repetition, not just once (P52).",
        P55_SCRIPT,
        240,
    ),
]


def run_probe(name: str, desc: str, code: str, timeout: int) -> str:
    """Runs one probe and returns its tag: "OK", "FAIL", or "CRASH"."""
    header(name)
    log(f"  {desc}")

    f = Path(tempfile.mkdtemp()) / f"{name}.py"
    f.write_text(code, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(f), str(PROJECT_ROOT)],
            capture_output=True, text=True, timeout=timeout,
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
    path = LOG_DIR / f"diagnose_v0.30.35_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS FOLLOW-UP (v0.30.35)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.34 pinned down the necessary condition precisely: one thread")
    log("  must do a real GDAL write followed by a real lxml touch ITSELF, in")
    log("  that order, in that same thread - only then does a later, new")
    log("  thread's first real lxml touch crash. Split across two threads that")
    log("  each do only one (P52/P53), nothing crashes. This run tests whether")
    log("  routing ALL lxml work through one persistent, reused worker thread")
    log("  - never recreated, never doing GDAL itself - stays safe across")
    log("  repeated rounds, the way the shipped GUI is actually used over a")
    log("  session, not just once.")

    tags = {}
    for name, desc, code, timeout in PROBES:
        tags[name] = run_probe(name, desc, code, timeout)

    header("SUMMARY")
    for name, tag in tags.items():
        label = {"OK": "OK   ", "FAIL": "FAIL ", "CRASH": "CRASH"}[tag]
        log(f"  {label}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P54 OK                       -> this harness is not faithfully")
    log("                                  reproducing the crash - compare")
    log("                                  against P51 before trusting P55.")
    log("  P54 CRASH, P55 OK (5/5)       -> the mitigation pattern survives")
    log("                                  repeated, realistic use.")
    log("  P54 CRASH, P55 fails round N>0 -> something accumulates over")
    log("                                  repeated rounds that one clean")
    log("                                  round (P52) did not reveal.")
    log("  P54 CRASH, P55 fails round 0   -> would contradict P52 outright and")
    log("                                  needs reconciling before anything")
    log("                                  else.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
