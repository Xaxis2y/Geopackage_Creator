# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.27 - follow-up to v0.30.26.

WHAT v0.30.26 FOUND
--------------------
    sqlite3.threadsafety      : 3   (stdlib sqlite3 itself claims full
                                      multi-thread safety - not the cause)
    GDAL version               : 3.13.2

    CRASH  P19_two_threads_real_convert            (real convert(), 2 threads)
    OK     P20_two_threads_sqlite3_only             (sqlite3 alone)
    OK     P21_two_threads_gdal_plus_sqlite3_no_lxml (GDAL + sqlite3, no lxml)
    OK     P22_two_threads_lxml_plus_sqlite3_no_gdal (lxml + sqlite3, no GDAL write)

Two threads is already enough (P19), which rules out "needs 3+ threads."
`sqlite3.threadsafety == 3` rules out the leading hypothesis from v0.30.26 -
this build's stdlib SQLite is not compiled single-thread. And critically:
EVERY pairwise combination of the three libraries survived in isolation.
Only the full real pipeline - GDAL write, THEN lxml compile(s), THEN two raw
sqlite3 reopens, all three together - crashes. Per v0.30.26's own reading
guide: "P20 OK, P21 OK, P22 OK -> only the full three-way combination
reproduces it; needs its own probe." This script is that probe.

THE UNTESTED VARIABLE THIS TIME
--------------------------------
Nothing before this script has combined all three libraries in one minimal,
hand-rolled probe - P19 proved the three-way combination crashes, but only
inside the full `GeoPackageConverter.convert()`, which also does CRS
validation, multiple metadata documents, transactions, and output
re-validation alongside the three libraries. Two questions remain open:

  1. Is bare co-presence of GDAL + lxml + sqlite3 (one touch each, in the
     real pipeline's order: write, then compile, then two reopens) already
     sufficient, with none of convert()'s surrounding complexity needed?

  2. Or does it specifically need MULTIPLE lxml compiles per turn, the way
     the real pipeline does (generate_package_metadata() compiles+validates
     internally, converter.py:619 makes a second explicit validate_schema()
     call on the same document, and generate_layer_metadata() compiles a
     third time for the one layer in the test fixture - three compiles per
     real convert() call, not one)?

WHAT THIS SCRIPT DECIDES
-------------------------
Both probes use the SAME proven building blocks as v0.30.26 (P20's
`sqlite_double_reopen`, P21's `gdal_write`, P22's `compile_and_validate` -
verbatim, not rewritten), combined instead of isolated, in the real
pipeline's own order: GDAL write+close, THEN lxml compile(s), THEN the two
sqlite3 reopens. Two fresh threads, second thread starts only after the
first's full turn completes (matches P19's proven-sufficient thread count).

  P23  Minimal three-way. GDAL write, ONE lxml compile+validate, two sqlite3
       reopens - one touch of each library, nothing extra. If this crashes,
       bare co-presence of the three libraries is the whole story; none of
       convert()'s surrounding complexity (multiple metadata docs, CRS
       validation, transactions) is required.

  P24  Repetition-matched three-way. Identical to P23, except THREE lxml
       compile+validate calls per turn instead of one - matching the real
       pipeline's actual count (package + explicit re-validate + one-layer).
       If P23 does NOT crash but this does, the repeated compiles are the
       load-bearing detail, not just co-presence.

  Reading the two together:
      P23 CRASH             -> bare co-presence (1 write, 1 compile, 2
                                reopens, real order) is sufficient. This is
                                the minimal reproduction - a genuine fix can
                                be designed and tested against THIS probe
                                instead of the full pipeline.
      P23 OK, P24 CRASH     -> compile MULTIPLICITY matters, not just
                                co-presence - echoes the original schema-
                                lifetime finding (v0.30.21/22), this time
                                across a thread handoff rather than within
                                one thread's repeated writes.
      P23 OK, P24 OK        -> neither reduced form reproduces it; something
                                else in convert() (CRS validation, the
                                transaction-wrapped feature copy, output
                                re-validation, or the exact real SQL in
                                _embed_metadata/_finalize_dgiwg_compliance
                                rather than this probe's approximation of
                                it) is also load-bearing. Next step would be
                                bisecting convert() itself by temporarily
                                short-circuiting one stage at a time, rather
                                than continuing to build free-standing
                                probes.

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.27.py

Writes dev_tools\\logs\\diagnose_v0.30.27_<timestamp>.log incrementally, so a
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
# Building blocks - verbatim from diagnose_crash_v0.30.26.py, where P20/P21/
# P22 already proved each one individually correct (P20 was even executed,
# not just compiled, during this script's own authoring). Combined here
# instead of isolated.
# ---------------------------------------------------------------------------
BASE_IMPORTS = r'''
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
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

SQLITE_ONLY_HELPERS = r'''
import sqlite3

def sqlite_double_reopen(tag, tmp_root):
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
        cur.execute("PRAGMA application_id = 1195922240")
        cur.execute("UPDATE gpkg_metadata SET mime_type = 'text/xml'")
        conn2.commit()
    finally:
        conn2.close()
'''

PROBES: list[tuple[str, str, str]] = [
    (
        "P23_two_threads_minimal_three_way",
        "Minimal three-way: GDAL write+close, ONE lxml compile+validate, two "
        "sqlite3 reopens - real pipeline's order, one touch of each library, "
        "nothing extra. 2 fresh threads. If this crashes, bare co-presence "
        "of the three libraries is the whole story.",
        BASE_IMPORTS + GDAL_WRITE_HELPER + LXML_COMPILE_HELPER + SQLITE_ONLY_HELPERS + r'''
tmp_root = tempfile.mkdtemp()
errors = {}
def worker(i):
    try:
        gdal_write(f"p23_{i}", tmp_root)
        compile_and_validate(f"p23_{i}")
        sqlite_double_reopen(f"p23_{i}_meta", tmp_root)
        print(f"P23: thread {i} completed write+compile+reopen (1 compile)", flush=True)
    except Exception as e:
        errors[i] = str(e)
threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
for t in threads: t.start()
for t in threads: t.join(timeout=30)
if errors:
    print(f"P23: errors: {errors}", flush=True)
    raise SystemExit(1)
print("P23 OK", flush=True)
''',
    ),
    (
        "P24_two_threads_repetition_matched_three_way",
        "Same as P23, but THREE lxml compile+validate calls per turn instead "
        "of one - matching the real pipeline's actual count (package + "
        "explicit re-validate + one-layer metadata). 2 fresh threads. If P23 "
        "did not crash but this does, compile repetition is the load-bearing "
        "detail.",
        BASE_IMPORTS + GDAL_WRITE_HELPER + LXML_COMPILE_HELPER + SQLITE_ONLY_HELPERS + r'''
tmp_root = tempfile.mkdtemp()
errors = {}
def worker(i):
    try:
        gdal_write(f"p24_{i}", tmp_root)
        compile_and_validate(f"p24_{i}_a")
        compile_and_validate(f"p24_{i}_b")
        compile_and_validate(f"p24_{i}_c")
        sqlite_double_reopen(f"p24_{i}_meta", tmp_root)
        print(f"P24: thread {i} completed write+compile+reopen (3 compiles)", flush=True)
    except Exception as e:
        errors[i] = str(e)
threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
for t in threads: t.start()
for t in threads: t.join(timeout=30)
if errors:
    print(f"P24: errors: {errors}", flush=True)
    raise SystemExit(1)
print("P24 OK", flush=True)
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
    path = LOG_DIR / f"diagnose_v0.30.27_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS FOLLOW-UP (v0.30.27)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.26 found: sqlite3.threadsafety=3 (not the cause). P19 (real")
    log("  convert(), 2 threads) CRASH. P20/P21/P22 (every PAIRWISE library")
    log("  combination) all OK. Only the full three-way combination - GDAL,")
    log("  lxml, and sqlite3 all touched in one thread's turn - reproduces")
    log("  it. This run tests whether a MINIMAL hand-rolled three-way combo")
    log("  (one touch of each, real pipeline's order) is already sufficient,")
    log("  or whether it specifically needs repeated lxml compiles the way")
    log("  the real pipeline does them.")

    results = {}
    for name, desc, code in PROBES:
        results[name] = run_probe(name, desc, code)

    header("SUMMARY")
    for name, ok in results.items():
        log(f"  {'OK   ' if ok else 'CRASH'}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P23 CRASH          -> bare co-presence (1 write, 1 compile, 2")
    log("                        reopens) is sufficient - minimal repro found.")
    log("  P23 OK, P24 CRASH  -> compile MULTIPLICITY matters, not just")
    log("                        co-presence.")
    log("  P23 OK, P24 OK     -> neither reduced form reproduces it; something")
    log("                        else in convert() is also load-bearing - next")
    log("                        step is bisecting convert() itself rather")
    log("                        than building more free-standing probes.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
