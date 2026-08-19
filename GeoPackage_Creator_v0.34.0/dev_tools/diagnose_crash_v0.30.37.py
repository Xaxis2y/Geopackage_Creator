# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.37 - follow-up to v0.30.36.

WHAT v0.30.36 FOUND
--------------------
    CRASH  P56_control_no_patch
    OK     P57_persistent_lxml_thread_concurrent_batch

4 GDAL-only worker threads, started back-to-back with real GDAL writes
genuinely overlapping in time, all dispatched to the one persistent lxml
worker thread - and it came back clean. The log even proved it: "persistent
lxml worker processed 4 jobs under 1 distinct OS thread ident(s): {9204}" -
one real thread, contended by 4 concurrent callers, zero crashes. Per this
series' own reading guide: "P56 CRASH, P57 OK -> the mitigation pattern
also survives genuine concurrency, not just sequential repetition."

So the mitigation pattern now has two, SEPARATE, clean confirmations:
  - repeated SEQUENTIAL use survives (P55: 5/5 rounds, one at a time)
  - a single CONCURRENT batch survives (P57: 4/4 threads, genuinely
    overlapping, contending for the one persistent worker together)

WHAT NEITHER v0.30.35 NOR v0.30.36 TESTED
--------------------------------------------
Each prior script changed exactly one variable relative to the last clean
result, by design - that is why each result is easy to trust in isolation.
But neither combined them: P55 was repeated and NEVER concurrent; P57 was
concurrent and NEVER repeated (a single batch, then the probe ended).
v0.30.36's own module docstring flagged this directly: "Combining
concurrency with repeated rounds (multiple concurrent batches back to
back) would be a reasonable next stress test before trusting this for
real, sustained, multi-file GUI usage." That is what a real session
actually looks like - not one round, not one batch, but many batches of
possibly-concurrent conversions over time, all sharing the same one
persistent lxml thread for the life of the program.

Interaction effects are exactly the kind of thing that can surprise you
even when each contributing dimension is independently safe - this is
worth confirming rather than assuming it follows automatically from P55
and P57 separately.

WHAT THIS SCRIPT DECIDES
-------------------------
  P58  Control. No patch at all. Expected CRASH, matching P56/P54/P51/P48/
       P45/P41/P36/P27/P17-19 - confirms this harness before trusting P59.

  P59  3 batches, run one batch after another (each batch fully finished,
       including all validation, before the next batch starts - this is
       the "repeated" dimension, exactly like P55's rounds). WITHIN each
       batch, 4 GDAL-only worker threads start back-to-back with no join
       between starts, so their real GDAL writes genuinely overlap (this
       is the "concurrent" dimension, exactly like P57's single batch).
       Every one of the 12 total conversions (3 batches x 4 workers) has
       its validation dispatched - via the same per-call fresh response
       queue protocol as P57, so concurrent dispatches never cross-talk -
       to the SAME ONE persistent lxml worker thread, created once before
       batch 0 and never recreated for the rest of the probe's life,
       exactly matching how the real mitigation would work for the life
       of the actual running program. The log records the persistent
       worker's OS thread identity on every one of the 12 jobs, so the
       log itself proves whether it stayed the same single thread across
       all three batches, not just within one.

  Reading the results:
      P58 OK                        -> this harness is not faithfully
                                        reproducing the crash; stop and
                                        compare it against P56 before
                                        trusting P59.
      P58 CRASH, P59 OK (3/3 batches,
      12/12 jobs, 1 thread ident)    -> the mitigation pattern survives
                                        combined repetition AND
                                        concurrency together - the
                                        strongest evidence yet for real,
                                        sustained, multi-file GUI usage.
      P58 CRASH, P59 fails on
      batch M > 0                    -> an interaction effect: something
                                        accumulates specifically under
                                        REPEATED CONCURRENT load that
                                        neither pure repetition (P55) nor
                                        one concurrent batch (P57) revealed
                                        alone. Worth knowing which batch
                                        and how many prior conversions had
                                        already gone through the same
                                        persistent thread.
      P58 CRASH, P59 fails on
      batch 0                        -> would contradict P57 outright
                                        (batch 0 here is identical in
                                        shape to all of P57) and needs
                                        reconciling before anything else.
      Log shows > 1 distinct
      persistent-worker thread ident -> a bug in THIS harness (the
                                        persistent worker was somehow
                                        recreated or a second one spun
                                        up), not a product finding.

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series. This tests whether a pattern is
*safe* when its two previously-isolated dimensions are combined, which is
a prerequisite for a fix, not a fix itself.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.37.py

Writes dev_tools\\logs\\diagnose_v0.30.37_<timestamp>.log incrementally, so a
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
# P58 (control): real convert(), unmodified, through the same harness as
# every P-control before it.
# ---------------------------------------------------------------------------
P58_SCRIPT = r'''
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
        run_conversion(f"P58_{i}", tmp_root)
        print(f"P58: thread {i} completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

print("P58: starting thread A, will wait for it to fully finish...", flush=True)
t_a = threading.Thread(target=worker, args=(0,))
t_a.start()
t_a.join(timeout=60)
if 0 in errors:
    print(f"P58: thread A errors: {errors}", flush=True)
    raise SystemExit(1)

print("P58: thread A finished cleanly. Starting thread B (a genuinely different, "
      "freshly-created OS thread) now...", flush=True)
t_b = threading.Thread(target=worker, args=(1,))
t_b.start()
t_b.join(timeout=60)
if errors:
    print(f"P58: errors: {errors}", flush=True)
    raise SystemExit(1)

print("P58 OK", flush=True)
'''


# ---------------------------------------------------------------------------
# P59: 3 batches of 4 concurrent GDAL-only worker threads each - repetition
# (P55's dimension) AND concurrency (P57's dimension) combined for the
# first time, all funneled through ONE persistent lxml worker thread that
# lives for the entire probe.
# ---------------------------------------------------------------------------
P59_SCRIPT = r'''
import queue
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler

BATCHES = 3
CONCURRENT_WORKERS = 4

_ORIG_VALIDATE_SCHEMA = MetadataHandler.validate_schema

def _noop_validate_schema(self, metadata_xml_string):
    # Every validate_schema call made THROUGH convert() lands here and does
    # zero real lxml work - none of the 12 GDAL worker threads (3 batches x
    # 4 workers) touch lxml itself. All real lxml work happens only on the
    # one persistent worker thread below, via _ORIG_VALIDATE_SCHEMA.
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
    real GDAL, zero real lxml in this thread. Identical shape to P57's
    per-worker GDAL job."""
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
# once before batch 0, and never recreated for the rest of this probe's
# life - exactly matching how the real mitigation would run for the whole
# life of the actual program, not just one round or one batch. Each
# dispatch gets its own private, single-use response queue (P57's
# cross-talk-proof protocol, already stress-tested standalone with 1600
# concurrent dispatches before that version was sent). ---
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

def gdal_and_validate(tag):
    try:
        run_conversion_gdal_only(tag, tmp_root)
    except Exception as e:
        with errors_lock:
            errors[tag] = f"gdal: {e}"
        return
    try:
        validate_via_persistent_thread(tag)
    except Exception as e:
        with errors_lock:
            errors[tag] = f"lxml: {e}"


for batch_i in range(BATCHES):
    print(f"P59: batch {batch_i} - starting {CONCURRENT_WORKERS} GDAL-only worker "
          f"threads CONCURRENTLY (no join between starts)...", flush=True)
    threads = []
    for w in range(CONCURRENT_WORKERS):
        tag = f"P59_b{batch_i}_w{w}"
        t = threading.Thread(target=gdal_and_validate, args=(tag,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=60)

    alive = [i for i, t in enumerate(threads) if t.is_alive()]
    if alive:
        errors[f"batch{batch_i}_hang"] = f"threads still alive after join timeout: {alive}"

    if errors:
        print(f"P59: batch {batch_i} errors so far: {errors}", flush=True)
        break

    print(f"P59: batch {batch_i} completed cleanly - all {CONCURRENT_WORKERS} "
          f"workers validated via the persistent lxml thread", flush=True)

_lxml_jobs.put(_LXML_STOP)

distinct_idents = set(_lxml_worker_idents)
print(f"P59: persistent lxml worker processed {len(_lxml_worker_idents)} jobs across "
      f"{BATCHES} batches under {len(distinct_idents)} distinct OS thread ident(s): "
      f"{distinct_idents}", flush=True)
if len(distinct_idents) != 1:
    errors["worker_idents"] = (
        f"expected exactly 1 persistent-worker thread ident across all "
        f"{BATCHES} batches, saw {len(distinct_idents)}: {distinct_idents} - "
        f"THIS SCRIPT'S OWN HARNESS is broken (the persistent worker was "
        f"somehow not singular), not a product finding"
    )

if errors:
    print(f"P59: errors: {errors}", flush=True)
    raise SystemExit(1)

print(f"P59 OK - all {BATCHES} batches x {CONCURRENT_WORKERS} concurrent workers "
      f"({BATCHES * CONCURRENT_WORKERS} total conversions) completed and validated "
      f"via the SAME one persistent lxml worker thread (single confirmed thread "
      f"ident across the whole probe), zero crashes", flush=True)
'''


PROBES: list[tuple[str, str, str, int]] = [
    (
        "P58_control_no_patch",
        "Control: the real, complete convert() (all internal steps run for "
        "real), through this script's own harness. Expected CRASH, matching "
        "P56/P54/P51/P48/P45/P41/P36/P27/P17-19 - confirms this harness "
        "before trusting P59.",
        P58_SCRIPT,
        180,
    ),
    (
        "P59_persistent_lxml_thread_repeated_concurrent_batches",
        "3 batches of 4 concurrent GDAL-only worker threads each (12 total "
        "conversions) - repetition (P55) and concurrency (P57) combined for "
        "the first time. Every conversion's validation is dispatched to the "
        "SAME one persistent lxml worker thread, created once before batch "
        "0 and never recreated for the whole probe. Tests whether the "
        "mitigation pattern holds when both previously-isolated dimensions "
        "are combined, matching realistic sustained multi-file GUI usage.",
        P59_SCRIPT,
        300,
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
    path = LOG_DIR / f"diagnose_v0.30.37_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS FOLLOW-UP (v0.30.37)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.35 showed the persistent-lxml-worker-thread mitigation")
    log("  survives 5 sequential rounds. v0.30.36 showed it survives one")
    log("  batch of 4 genuinely concurrent threads. Neither combined the two.")
    log("  This run does: 3 batches of 4 concurrent GDAL-only threads each,")
    log("  all funneled through the SAME one persistent lxml thread for the")
    log("  whole probe - repetition and concurrency together, matching real")
    log("  sustained, multi-file GUI usage over a session.")

    tags = {}
    for name, desc, code, timeout in PROBES:
        tags[name] = run_probe(name, desc, code, timeout)

    header("SUMMARY")
    for name, tag in tags.items():
        label = {"OK": "OK   ", "FAIL": "FAIL ", "CRASH": "CRASH"}[tag]
        log(f"  {label}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P58 OK                         -> this harness is not faithfully")
    log("                                    reproducing the crash - compare")
    log("                                    against P56 before trusting P59.")
    log("  P58 CRASH, P59 OK (3/3 batches,")
    log("  12/12 jobs, 1 thread ident)     -> the mitigation pattern survives")
    log("                                    combined repetition AND")
    log("                                    concurrency - the strongest")
    log("                                    evidence yet for sustained,")
    log("                                    multi-file GUI usage.")
    log("  P58 CRASH, P59 fails on batch")
    log("  M > 0                           -> an interaction effect: something")
    log("                                    accumulates specifically under")
    log("                                    REPEATED CONCURRENT load that")
    log("                                    neither P55 nor P57 revealed alone.")
    log("  P58 CRASH, P59 fails on batch 0 -> would contradict P57 outright")
    log("                                    (identical in shape) and needs")
    log("                                    reconciling before anything else.")
    log("  log shows > 1 distinct thread")
    log("  ident                           -> a bug in THIS harness, not a")
    log("                                    product finding.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
