# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.26 - follow-up to v0.30.25.

WHAT v0.30.25 FOUND
--------------------
    OK     P16_real_convert_single_thread_control   (3x real convert(), 1 thread)
    CRASH  P17_real_convert_three_threads_reports_on (3 fresh threads, reports ON)
    CRASH  P18_real_convert_three_threads_reports_off (3 fresh threads, reports OFF)

Per that script's own reading guide, P16 OK + P17 CRASH + P18 CRASH means:
report generation is NOT the trigger (P18 still crashes with it off), and the
hazard reproduces with the real, unmodified `GeoPackageConverter.convert()` -
no further reimplementation needed to prove it is real. In both crashing
runs, exactly ONE thread's "completed" line printed before the crash - the
lock correctly let only one thread inside `convert()` at a time, so this is
NOT a same-instant race. The shape is: thread A runs the full pipeline to
completion; thread B - a DIFFERENT OS thread - then acquires the lock and
crashes partway through running the SAME full pipeline again.

THE UNTESTED VARIABLE THIS TIME
--------------------------------
`diagnose_crash_v0.30.24.py`'s P13/P14/P15 already proved, in isolation,
that neither GDAL vector writes alone nor lxml schema compiles alone are
unsafe across fresh threads (both were OK, serialized by a lock, 3 threads
each doing ONE cycle). Neither of those probes - nor any probe before this
script - ever called Python's stdlib `sqlite3` module. The real `convert()`
does, twice per call: `_embed_metadata()` and `_finalize_dgiwg_compliance()`
each open their own `sqlite3.connect()` against the file GDAL just wrote and
closed. That is the one ingredient P12 through P18 never isolated.

This matters because CPython's `sqlite3.threadsafety` (accurate since
Python 3.11 - previously hardcoded and misleading) reports the ACTUAL
compiled threading mode of the linked SQLite library. If it reports 0
("single-thread"), the linked SQLite build documents itself as unsafe to
call from more than one OS thread FOR THE LIFETIME OF THE PROCESS - not just
concurrently, and no amount of external locking fixes that, because the
hazard is one thread's calls existing at all after another thread's calls,
not two threads calling at the same instant. That would explain this
crash's exact shape: fine within one thread (P16, batch_conversion_cycle),
fine across fresh threads that never touch sqlite3 (P13/P14/P15), broken the
first time a SECOND distinct thread touches sqlite3 in the same process
(P17/P18). GDAL links its OWN copy of SQLite for the GPKG driver, separate
from the stdlib `_sqlite3` extension - if either was compiled
`SQLITE_THREADSAFE=0`, or if one of them calls `sqlite3_config()` after the
other has already opened a connection (which SQLite's own docs say is only
safe before the first connection in the whole process), that is a
process-wide native hazard independent of any lock this project's Python
code holds.

WHAT THIS SCRIPT DECIDES
-------------------------
  STAGE 1  Informational, not a probe. Prints `sqlite3.threadsafety` and
           `sqlite3.sqlite_version` for the stdlib module, and whatever GDAL
           will report about its own linked SQLite. A 0 here would already
           be a strong lead on its own - the probes below confirm whether it
           actually bites in this project's calling pattern.

  P19  Tightened control. Same as v0.30.25's P17, but 2 threads instead of
       3 - the real, unmodified convert(), reports on. If the hazard only
       needs a SECOND distinct thread (not a third), this crashes too and
       gives a faster, cheaper repro to iterate on than 3 threads.

  P20  Purest isolation: sqlite3 ONLY. 2 fresh threads, each opens its own
       temp file via `sqlite3.connect()` TWICE in sequence (CREATE+INSERT,
       then a second connect() that does an UPDATE) - structurally
       mirroring `_embed_metadata()` then `_finalize_dgiwg_compliance()`'s
       two-reopen shape, but with NO GDAL import and NO lxml import
       anywhere in this probe at all. If this alone crashes, the hazard is
       purely stdlib sqlite3 used from more than one thread in this
       process - nothing about this project's GDAL or lxml usage is
       required to trigger it.

  P21  GDAL + sqlite3, no lxml. 2 fresh threads, each does a real GDAL
       vector write (like P14) then the same two sqlite3 reopens as P20
       against that same file - lxml/etree never imported in this probe.
       If this crashes but P20 does not, GDAL's own linked SQLite is
       specifically implicated, not stdlib sqlite3 in isolation.

  P22  lxml + sqlite3, no GDAL write. 2 fresh threads, each does a schema
       compile+validate (like P15) then the same two sqlite3 reopens
       against a plain (non-GDAL) file - no GDAL vector write anywhere in
       this probe. If this crashes but P20 does not, the combination of
       lxml's own libxml2 global state and sqlite3 is what matters, and a
       GDAL-written file is incidental.

  Reading the four together (P20/P21/P22 are only meaningful if P19
  confirms 2 threads reproduce it at all):
      P19 OK                       -> 2 threads is not enough; the hazard
                                       needs 3+ distinct threads. Re-run
                                       P20-P22 with 3 threads instead of 2
                                       before trusting their OK/CRASH either
                                       way.
      P20 CRASH                    -> stdlib sqlite3 alone, cross-thread,
                                       is sufficient. GDAL and lxml are
                                       incidental to THIS bug (they may
                                       still matter to trigger _embed_
                                       metadata/_finalize_dgiwg_compliance
                                       being reached at all in real usage,
                                       but the native fault itself does not
                                       need them).
      P20 OK, P21 CRASH            -> GDAL's linked SQLite + stdlib sqlite3
                                       reopening the SAME file is the
                                       hazard; lxml is not required.
      P20 OK, P22 CRASH            -> lxml + stdlib sqlite3 is the hazard;
                                       a GDAL-written file is not required.
      P20 OK, P21 OK, P22 OK       -> none of the two-way combinations
                                       reproduce it; the three-way
                                       combination (GDAL write + lxml
                                       compile + sqlite3 reopen, all in one
                                       thread's turn) is load-bearing and
                                       needs its own probe next.

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series. The fix depends entirely on which of
the above this run actually shows.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.26.py

Writes dev_tools\\logs\\diagnose_v0.30.26_<timestamp>.log incrementally, so a
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
# STAGE 1 - informational only, run in-process (not a subprocess probe).
# ---------------------------------------------------------------------------
def stage_sqlite_threading_info() -> None:
    header("STAGE 1: sqlite3 / GDAL threading-mode information (informational)")
    import sqlite3 as _sqlite3

    log(f"  python version            : {sys.version.split()[0]}")
    log(f"  sqlite3.sqlite_version    : {_sqlite3.sqlite_version}")
    log(f"  sqlite3.threadsafety      : {_sqlite3.threadsafety}")
    log("")
    if _sqlite3.threadsafety == 0:
        log("  ANALYSIS: 0 means this Python's stdlib sqlite3 module reports")
        log("  the linked SQLite library as compiled SINGLE-THREAD mode - its")
        log("  own documentation says it must not be called from more than one")
        log("  OS thread for the entire lifetime of the process, not just")
        log("  concurrently. If so, this alone would explain the P17/P18 shape")
        log("  in diagnose_crash_v0.30.25.py: safe within one thread, safe")
        log("  across fresh threads that never touch sqlite3, broken the first")
        log("  time a SECOND distinct thread calls into sqlite3 at all.")
    else:
        log(f"  ANALYSIS: {_sqlite3.threadsafety} indicates the stdlib sqlite3")
        log("  module itself claims some level of multi-thread safety. If the")
        log("  probes below still crash, the hazard is more likely GDAL's own,")
        log("  separately-linked copy of SQLite, or an interaction between the")
        log("  two libraries' SQLite instances sharing process-global state,")
        log("  rather than the stdlib module being unsafe on its own.")

    log("")
    try:
        from osgeo import gdal
        log(f"  GDAL version              : {gdal.__version__}")
        # GDAL does not expose a simple, stable API for "what SQLite version
        # is statically/dynamically linked into libgdal" - unlike the stdlib
        # sqlite3 module, there is no gdal.sqlite_version. Reporting this
        # accurately would require inspecting the GDAL build's dependency
        # manifest, which is out of scope for an in-process check. Left
        # unavailable rather than guessed.
        log("  GDAL's own linked SQLite version: not queryable via a stable")
        log("  GDAL Python API - not guessed here.")
    except Exception as exc:
        log(f"  [could not import osgeo.gdal: {exc}]")


# ---------------------------------------------------------------------------
# Preamble shared by every real-convert() probe (P19) - identical in spirit
# to diagnose_crash_v0.30.25.py's REAL_PREAMBLE.
# ---------------------------------------------------------------------------
REAL_CONVERT_PREAMBLE = r'''
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
'''

# ---------------------------------------------------------------------------
# Bisection preambles - deliberately minimal, hand-rolled (unlike the block
# above) BECAUSE the whole point of P20-P22 is removing ingredients one at a
# time. Each defines only what it needs; none imports both osgeo and lxml
# unless the probe specifically wants both.
# ---------------------------------------------------------------------------
SQLITE_ONLY_HELPERS = r'''
import sqlite3

def sqlite_double_reopen(tag, tmp_root):
    """Two separate connect/write/close cycles against the SAME file, no
    GDAL and no lxml anywhere in this probe - mirrors the shape of
    _embed_metadata() followed by _finalize_dgiwg_compliance(), which the
    real pipeline also runs as two separate sqlite3.connect() calls against
    one file, but with neither GDAL nor lxml involved here at all."""
    path = str(Path(tmp_root) / f"{tag}.db")

    conn1 = sqlite3.connect(path)
    try:
        cur = conn1.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS gpkg_metadata ("
            " id INTEGER PRIMARY KEY, md_scope TEXT, md_standard_uri TEXT,"
            " mime_type TEXT, metadata TEXT)"
        )
        cur.execute(
            "INSERT INTO gpkg_metadata (md_scope, md_standard_uri, mime_type, metadata)"
            " VALUES ('dataset', 'https://dgiwg.org/std/dmf/2.0', 'text/xml', '<x/>')"
        )
        conn1.commit()
    finally:
        conn1.close()

    conn2 = sqlite3.connect(path)
    try:
        cur = conn2.cursor()
        # Mirrors _finalize_dgiwg_compliance() setting the GP14 application_id
        # marker via a raw PRAGMA write against the same file a moment later.
        cur.execute("PRAGMA application_id = 1195922240")
        cur.execute("UPDATE gpkg_metadata SET mime_type = 'text/xml'")
        conn2.commit()
    finally:
        conn2.close()
'''

GDAL_WRITE_HELPER = r'''
from osgeo import ogr, osr

def gdal_write(tag, tmp_root):
    tmp = Path(tmp_root) / f"{tag}.gpkg"
    drv = ogr.GetDriverByName("GPKG")
    ds = drv.CreateDataSource(str(tmp))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    lyr = ds.CreateLayer("pts", srs=srs, geom_type=ogr.wkbPoint)
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetGeometry(ogr.CreateGeometryFromWkt("POINT (1 2)"))
    lyr.CreateFeature(f)
    f = None
    ds = None
    return str(tmp)
'''

LXML_COMPILE_HELPER = r'''
from lxml import etree

XSD = root / "schemas" / "iso19139-gmd.xsd"

def compile_and_validate(tag):
    schema_doc = etree.parse(str(XSD))
    schema = etree.XMLSchema(schema_doc)
    schema.validate(etree.fromstring(b"<x/>"))
    del schema
'''

BASE_IMPORTS = r'''
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
'''

PROBES: list[tuple[str, str, str]] = [
    (
        "P19_two_threads_real_convert",
        "Tightened control: v0.30.25's P17 (real, unmodified convert(), "
        "reports on), narrowed from 3 threads to 2. If a second distinct "
        "thread is all the hazard needs, this crashes too and gives a "
        "cheaper repro than 3 threads for everything below.",
        REAL_CONVERT_PREAMBLE + r'''
tmp_root = tempfile.mkdtemp()
errors = {}
def worker(i):
    try:
        run_conversion(f"p19_{i}", tmp_root)
        print(f"P19: thread {i} completed real convert()", flush=True)
    except Exception as e:
        errors[i] = str(e)
threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
for t in threads: t.start()
for t in threads: t.join(timeout=60)
if errors:
    print(f"P19: errors: {errors}", flush=True)
    raise SystemExit(1)
print("P19 OK", flush=True)
''',
    ),
    (
        "P20_two_threads_sqlite3_only",
        "Purest isolation: sqlite3 ONLY. 2 fresh threads, each does two "
        "sequential connect/write/close cycles against its own file - no "
        "GDAL import, no lxml import anywhere in this probe. If this alone "
        "crashes, stdlib sqlite3 used from more than one thread in this "
        "process is sufficient on its own.",
        BASE_IMPORTS + SQLITE_ONLY_HELPERS + r'''
tmp_root = tempfile.mkdtemp()
errors = {}
def worker(i):
    try:
        sqlite_double_reopen(f"p20_{i}", tmp_root)
        print(f"P20: thread {i} completed sqlite3-only double reopen", flush=True)
    except Exception as e:
        errors[i] = str(e)
threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
for t in threads: t.start()
for t in threads: t.join(timeout=30)
if errors:
    print(f"P20: errors: {errors}", flush=True)
    raise SystemExit(1)
print("P20 OK", flush=True)
''',
    ),
    (
        "P21_two_threads_gdal_plus_sqlite3_no_lxml",
        "GDAL + sqlite3, no lxml. 2 fresh threads, each does a real GDAL "
        "vector write then the same double sqlite3 reopen against that same "
        "file - lxml/etree never imported in this probe. If this crashes "
        "but P20 does not, GDAL's own linked SQLite is specifically "
        "implicated.",
        BASE_IMPORTS + GDAL_WRITE_HELPER + SQLITE_ONLY_HELPERS + r'''
tmp_root = tempfile.mkdtemp()
errors = {}
def worker(i):
    try:
        gdal_write(f"p21_{i}", tmp_root)
        sqlite_double_reopen(f"p21_{i}_meta", tmp_root)
        print(f"P21: thread {i} completed GDAL write + sqlite3 double reopen", flush=True)
    except Exception as e:
        errors[i] = str(e)
threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
for t in threads: t.start()
for t in threads: t.join(timeout=30)
if errors:
    print(f"P21: errors: {errors}", flush=True)
    raise SystemExit(1)
print("P21 OK", flush=True)
''',
    ),
    (
        "P22_two_threads_lxml_plus_sqlite3_no_gdal",
        "lxml + sqlite3, no GDAL write. 2 fresh threads, each does a schema "
        "compile+validate then the same double sqlite3 reopen against a "
        "plain (non-GDAL) file - no GDAL vector write anywhere in this "
        "probe. If this crashes but P20 does not, lxml's global state plus "
        "sqlite3 is the hazard; a GDAL-written file is not required.",
        BASE_IMPORTS + LXML_COMPILE_HELPER + SQLITE_ONLY_HELPERS + r'''
tmp_root = tempfile.mkdtemp()
errors = {}
def worker(i):
    try:
        compile_and_validate(f"p22_{i}")
        sqlite_double_reopen(f"p22_{i}_meta", tmp_root)
        print(f"P22: thread {i} completed lxml compile + sqlite3 double reopen", flush=True)
    except Exception as e:
        errors[i] = str(e)
threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
for t in threads: t.start()
for t in threads: t.join(timeout=30)
if errors:
    print(f"P22: errors: {errors}", flush=True)
    raise SystemExit(1)
print("P22 OK", flush=True)
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
    path = LOG_DIR / f"diagnose_v0.30.26_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS FOLLOW-UP (v0.30.26)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.25 found: P16 (1 thread) OK, P17/P18 (3 threads, reports")
    log("  on/off) both CRASH - report generation is not the trigger; the")
    log("  real convert() genuinely crashes the first time a SECOND distinct")
    log("  thread runs it after a first thread already completed one. No")
    log("  probe before this script has ever called stdlib sqlite3, which")
    log("  the real pipeline uses twice per conversion. This run checks the")
    log("  sqlite3 threading mode directly, then bisects GDAL / lxml /")
    log("  sqlite3 in pairs across 2 fresh threads to find which combination")
    log("  is load-bearing.")

    stage_sqlite_threading_info()

    results = {}
    for name, desc, code in PROBES:
        results[name] = run_probe(name, desc, code)

    header("SUMMARY")
    for name, ok in results.items():
        log(f"  {'OK   ' if ok else 'CRASH'}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P19 OK                  -> 2 threads is not enough; re-run P20-P22")
    log("                             with 3 threads before trusting them.")
    log("  P20 CRASH                -> stdlib sqlite3 alone, cross-thread, is")
    log("                             sufficient. GDAL/lxml are incidental.")
    log("  P20 OK, P21 CRASH        -> GDAL's linked SQLite + sqlite3 reopen")
    log("                             is the hazard; lxml not required.")
    log("  P20 OK, P22 CRASH        -> lxml + sqlite3 reopen is the hazard;")
    log("                             a GDAL-written file not required.")
    log("  P20 OK, P21 OK, P22 OK   -> only the full three-way combination")
    log("                             reproduces it; needs its own probe.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
