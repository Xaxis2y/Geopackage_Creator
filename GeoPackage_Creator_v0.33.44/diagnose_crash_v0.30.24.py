# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.24 - follow-up to v0.30.23.

WHY THIS EXISTS
---------------
v0.30.23 removed the process-wide compiled-schema cache in
`core/metadata_handler.py` (see `CHANGELOG_v0.30.23.md`) after
`dev_tools/diagnose_crash_v0.30.21.py` / `_v0.30.22.py` proved a compiled
`etree.XMLSchema` that survives even one GDAL write crashes on the real
machine - and that recompiling fresh immediately before every use, then
discarding it, survives four repeated write/validate cycles (probe P10).

That fix was verified twice on the real target machine (2026-08-14,
`run_release_check_v0.30.23.py`):

    STAGE 5  schema_no_cache        PASS  (two `.schema` reads, distinct objects)
    STAGE 6  batch_conversion_cycle PASS  (8 real write+validate cycles, ONE thread,
                                           ONE reused MetadataHandler - no crash)
    STAGE    pytest_main            PASS  (293 tests, no crash)
    STAGE    pytest_concurrency     FAIL  (Windows access violation, still)

The `pytest_concurrency` crash trace is materially different from the one
v0.30.23 fixed:

    Thread 0x00000e30: core/converter.py:111 in wrapper   (inside
                        `with global_conversion_lock(): return func(...)`)
    Thread 0x00000958: core/converter.py:111 in wrapper   (same)
    Current thread    : <no Python frame>                  <- the actual fault
    Thread 0x00006c58 : test_concurrency.py:168, .join()   (pytest's main thread)

Nothing in this trace mentions `metadata_handler.py` at all - unlike the
crash v0.30.23 fixed, which faulted explicitly inside `validate_schema()`.
`core/converter.py:111` is literally the single line that acquires the
process-wide `_GLOBAL_CONVERSION_LOCK` and calls the real `convert()` body -
so this crash is happening WHILE conversions are correctly, fully serialized
by that lock. Only one of the three worker threads can be doing real
GDAL/lxml work at any instant; the fault is not a same-instant race between
two threads' native calls.

THE UNTESTED VARIABLE
----------------------
Every earlier diagnostic (P1 through P11, and the new `batch_conversion_cycle`
stage) ran its write/compile/validate cycles from a SINGLE OS thread - either
the probe subprocess's main thread directly, or a loop inside it. None of them
ever tested what happens when GDAL and/or lxml are first touched from a
BRAND NEW, freshly-created OS thread - which is exactly what
`test_concurrent_writes_different_files` does three times over: each of its
three worker threads is a thread that has NEVER called into GDAL or libxml2
before, doing so for the first and only time before it exits.

This matters because both libraries keep real per-thread state:

  - libxml2 (when built with threading support, which this build is - the
    ABI guard already reads `LIBXML_VERSION`) lazily allocates a
    "global state" structure the FIRST time each distinct OS thread calls
    into it, and registers that structure into an internal, mutex-protected
    registry keyed by thread. This registration is itself a mutation of
    shared libxml2 internals, separate from anything a compiled `XMLSchema`
    object does.
  - GDAL's GPKG driver writes through SQLite. Depending on how the specific
    conda-forge build was compiled (`SQLITE_THREADSAFE=0/1/2`), SQLite can
    assume single-thread AFFINITY for parts of its global state - not just
    mutual exclusion - in which case using it from a second, different
    thread later in the same process, even one at a time under a lock, is
    undefined behaviour distinct from true concurrent access.

Nothing already run rules either of these in or out, because nothing already
run used more than one OS thread.

WHAT THIS SCRIPT DECIDES
-------------------------
  P12  Control. Three FULL cycles (GDAL write + fresh-compile + validate),
       all from the SAME single thread, sequential. Expected OK - this is
       the same shape `batch_conversion_cycle` already proved safe, included
       here so this log is self-contained and confirms this run's
       environment matches that earlier PASS before trusting P13-P15.

  P13  Direct reproduction. Three SEPARATE, freshly-created OS threads, each
       running ONE full cycle (GDAL write + fresh-compile + validate),
       serialized by a `threading.RLock()` - the exact shape of
       `core/converter.py`'s `_serialize_conversions` wrapping the real
       `convert()`. If this crashes and P12 does not, the differential is
       thread identity, not object lifetime, and the v0.30.23 fix (which
       only ever addressed lifetime) cannot close this by itself.

  P14  Isolates GDAL. Same three-thread, lock-serialized shape as P13, but
       each thread does ONLY the GDAL write - lxml is never imported or
       touched anywhere in this probe. If this alone crashes, the hazard is
       GDAL/SQLite thread affinity, and lxml is not involved in this second
       bug at all.

  P15  Isolates lxml. Same three-thread, lock-serialized shape as P13, but
       each thread does ONLY the fresh-compile + validate - GDAL is never
       touched. If this alone crashes, the hazard is libxml2's own
       per-thread global-state registration, independent of GDAL entirely.

  Reading the four together:
      P12 OK, P13 OK              -> this diagnostic does not reproduce the
                                      pytest_concurrency crash; look elsewhere
                                      (timing, thread count, real shapefile
                                      I/O not modeled here).
      P12 OK, P13 CRASH,
        P14 OK,  P15 OK            -> the hazard only appears when GDAL AND
                                      lxml are BOTH touched, each from its
                                      own new thread, in the same process -
                                      points back to GDAL disturbing libxml2
                                      state, now shown to also depend on
                                      thread identity, not just call order.
      P12 OK, P13 CRASH,
        P14 CRASH                  -> GDAL/SQLite alone is thread-affinity
                                      unsafe; lxml is not the (or not the
                                      only) culprit.
      P12 OK, P13 CRASH,
        P15 CRASH                  -> libxml2 alone is thread-affinity
                                      unsafe; GDAL is not required to
                                      reproduce it.

No code fix is being proposed alongside this script. Per this project's own
established discipline (see CHANGELOG_v0.30.20.md's correction), a theory
that looks solid before a real-machine run has already been wrong once this
week - the fix direction depends entirely on which of the four outcomes
above this run actually shows.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.24.py

Writes dev_tools\\logs\\diagnose_v0.30.24_<timestamp>.log incrementally, so a
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
# Imports osgeo/lxml at MODULE level, in what will be that subprocess's own
# main thread, BEFORE any worker thread is created - this matches the real
# test exactly: `from core import GeoPackageConverter` (which pulls in
# `core.gdal_handler`'s module-level `gdal.UseExceptions(); ogr.UseExceptions()`
# and `core.metadata_handler`'s `from lxml import etree`) runs in pytest's
# collection thread, long before test_concurrent_writes_different_files
# spawns its three worker threads. Re-importing an already-imported module
# from a new thread is a cheap sys.modules lookup, not a re-init - so if a
# fresh OS thread's very first CALL into GDAL/libxml2 is itself the hazard,
# this preamble will still exercise exactly that, and nothing more.
# ---------------------------------------------------------------------------
PREAMBLE = r'''
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
XSD = root / "schemas" / "iso19139-gmd.xsd"

from osgeo import ogr, osr, gdal
gdal.UseExceptions()
ogr.UseExceptions()
from lxml import etree

def gdal_write(tag="w"):
    tmp = Path(tempfile.mkdtemp()) / (tag + ".gpkg")
    drv = ogr.GetDriverByName("GPKG")
    ds = drv.CreateDataSource(str(tmp))
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    lyr = ds.CreateLayer("pts", srs=srs, geom_type=ogr.wkbPoint)
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetGeometry(ogr.CreateGeometryFromWkt("POINT (1 2)"))
    lyr.CreateFeature(f)
    f = None; ds = None

def compile_and_validate(tag="v"):
    schema_doc = etree.parse(str(XSD))
    schema = etree.XMLSchema(schema_doc)
    schema.validate(etree.fromstring(b"<x/>"))
    del schema
'''

PROBES: list[tuple[str, str, str]] = [
    (
        "P12_single_thread_control",
        "Control: 3 full cycles (write+compile+validate), one thread, "
        "sequential. Same shape run_release_check_v0.30.23.py's "
        "batch_conversion_cycle already proved safe. Expected OK - confirms "
        "this run's environment before trusting P13-P15.",
        PREAMBLE + r'''
for i in range(3):
    gdal_write(f"p12_{i}")
    compile_and_validate(f"p12_{i}")
    print(f"P12: single-thread cycle #{i+1} survived", flush=True)
print("P12 OK", flush=True)
''',
    ),
    (
        "P13_three_threads_full_pipeline",
        "Direct reproduction: 3 SEPARATE new OS threads, each does ONE full "
        "cycle (write+compile+validate), serialized by a threading.RLock() - "
        "the exact shape of converter.py's _serialize_conversions. If this "
        "crashes where P12 did not, the differential is thread identity, "
        "not object lifetime.",
        PREAMBLE + r'''
import threading
lock = threading.RLock()
errors = {}
def worker(i):
    try:
        with lock:
            gdal_write(f"p13_{i}")
            compile_and_validate(f"p13_{i}")
        print(f"P13: thread {i} completed full cycle", flush=True)
    except Exception as e:
        errors[i] = str(e)
threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
for t in threads: t.start()
for t in threads: t.join(timeout=30)
if errors:
    print(f"P13: errors: {errors}", flush=True)
    raise SystemExit(1)
print("P13 OK", flush=True)
''',
    ),
    (
        "P14_three_threads_gdal_only",
        "Isolates GDAL: same 3-new-thread, lock-serialized shape as P13, "
        "but lxml is never imported or touched anywhere in this probe - "
        "each thread does only the GDAL write. Crashing alone here would "
        "point at GDAL/SQLite thread affinity, independent of lxml.",
        PREAMBLE + r'''
import threading
lock = threading.RLock()
errors = {}
def worker(i):
    try:
        with lock:
            gdal_write(f"p14_{i}")
        print(f"P14: thread {i} completed GDAL-only write", flush=True)
    except Exception as e:
        errors[i] = str(e)
threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
for t in threads: t.start()
for t in threads: t.join(timeout=30)
if errors:
    print(f"P14: errors: {errors}", flush=True)
    raise SystemExit(1)
print("P14 OK", flush=True)
''',
    ),
    (
        "P15_three_threads_lxml_only",
        "Isolates lxml: same 3-new-thread, lock-serialized shape as P13, "
        "but GDAL is never touched anywhere in this probe - each thread "
        "does only a fresh compile+validate. Crashing alone here would "
        "point at libxml2's own per-thread global-state registration, "
        "independent of GDAL.",
        PREAMBLE + r'''
import threading
lock = threading.RLock()
errors = {}
def worker(i):
    try:
        with lock:
            compile_and_validate(f"p15_{i}")
        print(f"P15: thread {i} completed lxml-only compile+validate", flush=True)
    except Exception as e:
        errors[i] = str(e)
threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
for t in threads: t.start()
for t in threads: t.join(timeout=30)
if errors:
    print(f"P15: errors: {errors}", flush=True)
    raise SystemExit(1)
print("P15 OK", flush=True)
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
            capture_output=True, text=True, timeout=300,
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
    path = LOG_DIR / f"diagnose_v0.30.24_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS FOLLOW-UP (v0.30.24)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.23 fixed the schema-LIFETIME crash (proven by")
    log("  batch_conversion_cycle: 8 sequential write+validate cycles, one")
    log("  thread, no crash). pytest_concurrency still crashes afterward, in")
    log("  a trace that never mentions metadata_handler.py. This run tests")
    log("  the one variable nothing before it ever varied: genuinely")
    log("  separate, freshly-created OS threads, each touching GDAL and/or")
    log("  lxml for the first time, serialized by a lock exactly like the")
    log("  real converter.py wrapper.")

    results = {}
    for name, desc, code in PROBES:
        results[name] = run_probe(name, desc, code)

    header("SUMMARY")
    for name, ok in results.items():
        log(f"  {'OK   ' if ok else 'CRASH'}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P12 OK, P13 OK    -> not reproduced here; the real crash needs")
    log("                       something this probe doesn't model yet.")
    log("  P12 OK, P13 CRASH,")
    log("    P14 OK, P15 OK  -> needs GDAL AND lxml, each from its own new")
    log("                       thread. GDAL-disturbs-libxml2, now shown to")
    log("                       also depend on thread identity.")
    log("  P12 OK, P13 CRASH, P14 CRASH")
    log("                    -> GDAL/SQLite alone is thread-affinity unsafe.")
    log("  P12 OK, P13 CRASH, P15 CRASH")
    log("                    -> libxml2 alone is thread-affinity unsafe.")
    log("  P12 CRASH         -> this run's environment does not match the")
    log("                       one batch_conversion_cycle passed on -")
    log("                       stop and report before trusting P13-P15.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
