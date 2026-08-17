# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.36 - follow-up to v0.30.35.

WHAT v0.30.35 FOUND
--------------------
    CRASH  P54_control_no_patch
    OK     P55_persistent_lxml_thread_five_rounds

P55 completed all 5 rounds cleanly - zero crashes, using one persistent
lxml worker thread (created once, reused every round) while every round's
GDAL work stayed on its own brand-new, disposable worker thread that never
touched lxml itself. Per the project's own reading guide: "P54 CRASH, P55
OK (5/5) -> the mitigation pattern survives repeated, realistic use."

That is real, if still preliminary, evidence for the mitigation shape: no
thread ever does both GDAL and lxml itself; all lxml/schema-validation
work funnels through one dedicated, persistent worker thread instead.

WHAT v0.30.35 DID NOT TEST
----------------------------
P55's five rounds were still strictly SEQUENTIAL - round N's GDAL thread
was created, run, joined, AND had its validation dispatched and returned,
all before round N+1's GDAL thread was even created. At no point were two
GDAL threads alive at the same wall-clock time, and at no point did more
than one thread dispatch to the persistent lxml worker concurrently.

That matters because the real GUI does not necessarily serialize
conversions one full round at a time - a user can plausibly have more than
one conversion in flight together (e.g. a batch of files), meaning
multiple GDAL worker threads genuinely overlapping in time, all eventually
needing to reach the same one persistent lxml thread together, not one at
a time with a full join() in between. P55 never exercised that.

This also matters for a second, separate reason: earlier in this
investigation, genuinely concurrent (overlapping, non-sequential) thread
races were already tried against the UNMITIGATED code and did NOT
reproduce the crash - only strict join()-then-new-thread hand-off did.
That is good reason to expect concurrency alone will not introduce a new
hazard here either, but it has never actually been tried against THIS
mitigation pattern specifically, with multiple producers contending for
the one persistent worker at once, so it is worth confirming rather than
assuming.

WHAT THIS SCRIPT DECIDES
-------------------------
  P56  Control. No patch at all. Expected CRASH, matching P54/P51/P48/P45/
       P41/P36/P27/P17-19 - confirms this harness before trusting P57.

  P57  One batch of 4 GDAL-only worker threads, started back-to-back with
       no join() between the starts, so their real GDAL writes genuinely
       overlap in wall-clock time (validate_schema neutered process-wide,
       identical shape to P55's per-round GDAL job - zero lxml in any of
       these 4 threads). The ONE persistent lxml worker thread is created
       once, before any of the 4 threads start. As soon as each of the 4
       threads finishes its OWN GDAL work, it - from within itself,
       concurrently with whichever siblings are still running - dispatches
       its own validation job to the shared persistent worker and blocks
       on its own private response (a fresh, per-call response queue, so
       concurrent dispatches can never cross-talk and pick up each other's
       result). The persistent worker still processes jobs one at a time,
       serializing the actual lxml calls even though up to 4 threads may
       be queued up waiting on it together. The log records the OS thread
       identity the persistent worker actually ran under, once per job
       processed, so the log itself - not just this script's own logic -
       is evidence that a single thread handled all 4 jobs.

       This isolates exactly one new variable versus P55: concurrency of
       the GDAL threads and of the dispatches to the persistent worker.
       Repetition (multiple such batches back to back) is deliberately
       NOT combined with it here - if this version's P57 needs a fix, it
       should be obvious which of the two independent variables (added in
       different versions) is responsible.

  Reading the results:
      P56 OK                   -> this harness is not faithfully
                                   reproducing the crash; stop and compare
                                   it against P54 before trusting P57.
      P56 CRASH, P57 OK         -> the mitigation pattern also survives
                                   genuine concurrency, not just sequential
                                   repetition. Combining concurrency with
                                   repeated rounds (multiple concurrent
                                   batches back to back) would be a
                                   reasonable next stress test before
                                   trusting this for real, sustained,
                                   multi-file GUI usage.
      P56 CRASH, P57 fails,
      log shows > 1 distinct
      persistent-worker thread
      ident                     -> a bug in THIS harness (the persistent
                                   worker was somehow recreated), not a
                                   product finding - the mitigation was
                                   never actually tested as designed.
      P56 CRASH, P57 fails,
      log shows exactly 1
      persistent-worker thread
      ident                     -> a genuine new finding: concurrent GDAL
                                   activity across multiple threads, or
                                   concurrent contention for the one
                                   persistent lxml worker, is itself
                                   enough to crash - even with the "no
                                   thread does both" rule still honored by
                                   every individual thread. Would mean the
                                   mitigation needs more than just "one
                                   dedicated lxml thread" to be safe.

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series. This tests whether a pattern is
*safe* under a specific, named new condition (concurrency), which is a
prerequisite for a fix, not a fix itself.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.36.py

Writes dev_tools\\logs\\diagnose_v0.30.36_<timestamp>.log incrementally, so a
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
# P56 (control): real convert(), unmodified, through the same harness as
# every P-control before it.
# ---------------------------------------------------------------------------
P56_SCRIPT = r'''
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
        run_conversion(f"P56_{i}", tmp_root)
        print(f"P56: thread {i} completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

print("P56: starting thread A, will wait for it to fully finish...", flush=True)
t_a = threading.Thread(target=worker, args=(0,))
t_a.start()
t_a.join(timeout=60)
if 0 in errors:
    print(f"P56: thread A errors: {errors}", flush=True)
    raise SystemExit(1)

print("P56: thread A finished cleanly. Starting thread B (a genuinely different, "
      "freshly-created OS thread) now...", flush=True)
t_b = threading.Thread(target=worker, args=(1,))
t_b.start()
t_b.join(timeout=60)
if errors:
    print(f"P56: errors: {errors}", flush=True)
    raise SystemExit(1)

print("P56 OK", flush=True)
'''


# ---------------------------------------------------------------------------
# P57: one batch of concurrent GDAL-only worker threads, all dispatching
# (potentially at the same time) to ONE persistent lxml worker thread -
# the mitigation pattern under genuine concurrency, not just repetition.
# ---------------------------------------------------------------------------
P57_SCRIPT = r'''
import queue
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler

CONCURRENT_WORKERS = 4

_ORIG_VALIDATE_SCHEMA = MetadataHandler.validate_schema

def _noop_validate_schema(self, metadata_xml_string):
    # Every validate_schema call made THROUGH convert() lands here and does
    # zero real lxml work - none of the 4 concurrent GDAL threads touch
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
    real GDAL, zero real lxml in this thread. Identical shape to P55's
    per-round GDAL job."""
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
# once, before any of the 4 GDAL threads start. Each dispatch gets its own
# private, single-use response queue, so concurrent dispatches from
# different threads can never pick up each other's result - only the
# actual lxml call itself is serialized, one job at a time, on this one
# thread. ---
_lxml_jobs = queue.Queue()
_LXML_STOP = object()
_lxml_worker_idents = []
_lxml_worker_idents_lock = threading.Lock()

def _lxml_worker():
    while True:
        item = _lxml_jobs.get()
        if item is _LXML_STOP:
            return
        tag, response_q = item
        with _lxml_worker_idents_lock:
            _lxml_worker_idents.append(threading.get_ident())
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
            response_q.put(("ok", tag))
        except Exception as e:
            response_q.put(("error", f"{tag}: {e}"))

_lxml_thread = threading.Thread(target=_lxml_worker, daemon=True)
_lxml_thread.start()

def validate_via_persistent_thread(tag, timeout=30):
    response_q = queue.Queue()
    _lxml_jobs.put((tag, response_q))
    try:
        status, payload = response_q.get(timeout=timeout)
    except queue.Empty:
        raise RuntimeError(f"{tag}: persistent lxml worker did not respond within {timeout}s")
    if status == "error":
        raise RuntimeError(payload)
    return payload


tmp_root = tempfile.mkdtemp()
errors = {}
errors_lock = threading.Lock()

def gdal_and_validate(i):
    tag = f"P57_w{i}"
    try:
        run_conversion_gdal_only(tag, tmp_root)
    except Exception as e:
        with errors_lock:
            errors[i] = f"gdal: {e}"
        return
    print(f"P57: worker {i} finished its own GDAL work, dispatching to the "
          f"persistent lxml thread now...", flush=True)
    try:
        validate_via_persistent_thread(tag)
        print(f"P57: worker {i} validation completed via the persistent lxml thread",
              flush=True)
    except Exception as e:
        with errors_lock:
            errors[i] = f"lxml: {e}"


print(f"P57: starting {CONCURRENT_WORKERS} GDAL-only worker threads CONCURRENTLY "
      f"(no join between starts - real GDAL writes will overlap in time)...", flush=True)
threads = []
for i in range(CONCURRENT_WORKERS):
    t = threading.Thread(target=gdal_and_validate, args=(i,))
    threads.append(t)
    t.start()
print(f"P57: all {CONCURRENT_WORKERS} threads started, now joining...", flush=True)
for t in threads:
    t.join(timeout=60)

alive = [i for i, t in enumerate(threads) if t.is_alive()]
if alive:
    errors["hang"] = f"threads still alive after join timeout: {alive}"

_lxml_jobs.put(_LXML_STOP)

distinct_idents = set(_lxml_worker_idents)
print(f"P57: persistent lxml worker processed {len(_lxml_worker_idents)} jobs "
      f"under {len(distinct_idents)} distinct OS thread ident(s): {distinct_idents}",
      flush=True)
if len(distinct_idents) != 1:
    errors["worker_idents"] = (
        f"expected exactly 1 persistent-worker thread ident, saw "
        f"{len(distinct_idents)}: {distinct_idents} - THIS SCRIPT'S OWN HARNESS "
        f"is broken (the persistent worker was somehow not singular), not a "
        f"product finding"
    )

if errors:
    print(f"P57: errors: {errors}", flush=True)
    raise SystemExit(1)

print(f"P57 OK - all {CONCURRENT_WORKERS} concurrent GDAL threads completed and "
      f"validated via the one persistent lxml worker thread (single confirmed "
      f"thread ident), zero crashes", flush=True)
'''


PROBES: list[tuple[str, str, str, int]] = [
    (
        "P56_control_no_patch",
        "Control: the real, complete convert() (all internal steps run for "
        "real), through this script's own harness. Expected CRASH, matching "
        "P54/P51/P48/P45/P41/P36/P27/P17-19 - confirms this harness before "
        "trusting P57.",
        P56_SCRIPT,
        180,
    ),
    (
        "P57_persistent_lxml_thread_concurrent_batch",
        "One batch of 4 GDAL-only worker threads started back-to-back (no "
        "join between starts, so their real GDAL writes overlap in time), "
        "each dispatching its own validation - possibly concurrently with "
        "siblings - to ONE persistent lxml worker thread created once "
        "before any of them start. No thread ever does both GDAL and lxml "
        "itself. Tests whether the mitigation pattern confirmed safe under "
        "repetition (P55) also holds under genuine concurrency.",
        P57_SCRIPT,
        180,
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
    path = LOG_DIR / f"diagnose_v0.30.36_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS FOLLOW-UP (v0.30.36)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.35 showed the persistent-lxml-worker-thread mitigation")
    log("  survives 5 SEQUENTIAL rounds with zero crashes. Every round there")
    log("  was still strictly one full round at a time - no two GDAL threads")
    log("  were ever alive together, and nothing ever contended for the")
    log("  persistent lxml thread concurrently. This run adds exactly that")
    log("  one new variable: 4 GDAL-only worker threads started together,")
    log("  genuinely overlapping in time, all eventually reaching the same")
    log("  one persistent lxml worker thread - which still processes them")
    log("  one at a time, but now with real contention instead of none.")

    tags = {}
    for name, desc, code, timeout in PROBES:
        tags[name] = run_probe(name, desc, code, timeout)

    header("SUMMARY")
    for name, tag in tags.items():
        label = {"OK": "OK   ", "FAIL": "FAIL ", "CRASH": "CRASH"}[tag]
        log(f"  {label}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P56 OK                        -> this harness is not faithfully")
    log("                                   reproducing the crash - compare")
    log("                                   against P54 before trusting P57.")
    log("  P56 CRASH, P57 OK              -> the mitigation pattern also")
    log("                                   survives genuine concurrency, not")
    log("                                   just sequential repetition.")
    log("  P56 CRASH, P57 fails, log shows")
    log("  > 1 distinct persistent-worker")
    log("  thread ident                   -> a bug in THIS harness, not a")
    log("                                   product finding - re-check before")
    log("                                   trusting the result either way.")
    log("  P56 CRASH, P57 fails, log shows")
    log("  exactly 1 persistent-worker")
    log("  thread ident                   -> a genuine new finding: mere")
    log("                                   concurrency/contention is itself")
    log("                                   enough to crash, even with 'no")
    log("                                   thread does both' still honored")
    log("                                   by every individual thread.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
