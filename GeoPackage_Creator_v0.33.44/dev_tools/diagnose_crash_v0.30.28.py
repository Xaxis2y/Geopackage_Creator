# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.28 - follow-up to v0.30.27.

CORRECTING A GAP IN v0.30.27, NOT JUST REFINING IT
-----------------------------------------------------
v0.30.27's P23/P24 both came back OK - the minimal and repetition-matched
three-way combinations (GDAL write + lxml compile(s) + two sqlite3 reopens)
did not crash. Read at face value that pointed away from "bare co-presence"
and toward something else in `convert()` being load-bearing. But re-reading
P23/P24's own code turned up a real methodological gap, not a refinement:

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=30)

Both threads are started together with no lock between them - this runs
them CONCURRENTLY, with real overlap. That is a DIFFERENT experiment than
what actually crashes. `test_concurrent_writes_different_files` running
under the real `convert()` is wrapped in `@_serialize_conversions` (`with
global_conversion_lock(): return func(...)`), and every crash log so far
(v0.30.25's P17/P18, v0.30.26's P19) shows exactly ONE thread's "completed"
line before the fault - meaning thread A ran its ENTIRE turn to completion,
released the lock, and only THEN did thread B - a different OS thread -
start and crash partway through. That is sequential hand-off between two
threads, never simultaneous. P20 through P24 (v0.30.26 and v0.30.27) never
reproduced that shape; they let both threads race freely. Given the crash
needs the SECOND thread to begin only after the first is entirely done, a
probe that lets them overlap is not a smaller-but-equivalent version of the
real scenario - it is testing something else, and its four OK results
(P20-P24) do not actually rule out what they were built to test.

This script reruns the same minimal and repetition-matched three-way
combinations from P23/P24, changed in exactly one way: thread A is started
and FULLY JOINED before thread B is even created, guaranteeing zero overlap
by construction (not by a lock, which would still leave open the question
of whether contention timing mattered - `join()` removes the question
entirely). Nothing else about the probes changes: same `gdal_write`, same
`compile_and_validate`, same `sqlite_double_reopen` helpers as P20-P24,
verbatim.

WHAT THIS SCRIPT DECIDES
-------------------------
  P25  Minimal, sequential hand-off. Thread A: one GDAL write, one lxml
       compile+validate, two sqlite3 reopens - start, then join() to
       completion. Only then does thread B run the identical sequence.
       If this crashes, bare co-presence of the three libraries WAS the
       whole story after all - P23 gave a false negative purely because it
       let the threads overlap instead of hand off.

  P26  Same, repetition-matched: THREE lxml compile+validate calls per
       thread's turn instead of one (matching the real pipeline's actual
       count), same strict start-then-join-then-start hand-off. If P25 does
       not crash but this does, repetition specifically matters, not just
       co-presence - and it only shows up under true hand-off, which is why
       P24 (same repetition count, but concurrent) missed it too.

  Reading the two together:
      P25 CRASH             -> minimal repro found, and it confirms the
                                overlap-vs-handoff distinction was the whole
                                reason P23/P24 looked clean. A fix can be
                                designed and tested against THIS probe.
      P25 OK, P26 CRASH      -> repetition matters, and only under hand-off.
      P25 OK, P26 OK         -> the overlap/handoff distinction was not the
                                missing piece either; something else in the
                                real convert() (the extra source-file re-open
                                for CRS validation, output_validator's own
                                re-open, or the real, larger SQL in
                                _embed_metadata/_finalize_dgiwg_compliance)
                                is load-bearing. At that point the right move
                                is bisecting convert() itself directly -
                                e.g. temporarily stubbing out one stage at a
                                time in a scratch copy - rather than
                                continuing to build free-standing probes
                                that keep approximating it.

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.28.py

Writes dev_tools\\logs\\diagnose_v0.30.28_<timestamp>.log incrementally, so a
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
# Building blocks - verbatim from diagnose_crash_v0.30.26.py / _v0.30.27.py.
# Only the orchestration below changes (strict sequential hand-off instead
# of concurrent start-both/join-both).
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

# ---------------------------------------------------------------------------
# Strict sequential hand-off orchestration: thread A is started and joined
# to completion BEFORE thread B is even constructed. This guarantees zero
# overlap by construction - not by a lock, which would leave open whether
# contention timing mattered.
# ---------------------------------------------------------------------------
SEQUENTIAL_HANDOFF_TEMPLATE = r'''
tmp_root = tempfile.mkdtemp()
errors = {{}}

def worker(i):
    try:
        {body}
        print(f"{probe_name}: thread {{i}} completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

print("{probe_name}: starting thread A, will wait for it to fully finish...", flush=True)
t_a = threading.Thread(target=worker, args=(0,))
t_a.start()
t_a.join(timeout=30)
if 0 in errors:
    print(f"{probe_name}: thread A errors: {{errors}}", flush=True)
    raise SystemExit(1)

print("{probe_name}: thread A finished cleanly. Starting thread B (a genuinely "
      "different, freshly-created OS thread) now...", flush=True)
t_b = threading.Thread(target=worker, args=(1,))
t_b.start()
t_b.join(timeout=30)
if errors:
    print(f"{probe_name}: errors: {{errors}}", flush=True)
    raise SystemExit(1)

print("{probe_name} OK", flush=True)
'''

_P25_BODY = (
    'gdal_write(f"p25_{i}", tmp_root)\n'
    '        compile_and_validate(f"p25_{i}")\n'
    '        sqlite_double_reopen(f"p25_{i}_meta", tmp_root)'
)

_P26_BODY = (
    'gdal_write(f"p26_{i}", tmp_root)\n'
    '        compile_and_validate(f"p26_{i}_a")\n'
    '        compile_and_validate(f"p26_{i}_b")\n'
    '        compile_and_validate(f"p26_{i}_c")\n'
    '        sqlite_double_reopen(f"p26_{i}_meta", tmp_root)'
)

PROBES: list[tuple[str, str, str]] = [
    (
        "P25_sequential_handoff_minimal",
        "Minimal three-way, STRICT sequential hand-off (not concurrent, "
        "unlike P23): thread A runs one GDAL write + one lxml compile + two "
        "sqlite3 reopens to completion and is join()-ed BEFORE thread B is "
        "even created. If this crashes, P23's overlap (instead of hand-off) "
        "is confirmed as the reason it looked clean.",
        BASE_IMPORTS + GDAL_WRITE_HELPER + LXML_COMPILE_HELPER + SQLITE_ONLY_HELPERS
        + SEQUENTIAL_HANDOFF_TEMPLATE.format(probe_name="P25", body=_P25_BODY),
    ),
    (
        "P26_sequential_handoff_repetition_matched",
        "Same as P25, but THREE lxml compile+validate calls per thread's "
        "turn instead of one - matching the real pipeline's actual count. "
        "Same strict sequential hand-off as P25.",
        BASE_IMPORTS + GDAL_WRITE_HELPER + LXML_COMPILE_HELPER + SQLITE_ONLY_HELPERS
        + SEQUENTIAL_HANDOFF_TEMPLATE.format(probe_name="P26", body=_P26_BODY),
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
    path = LOG_DIR / f"diagnose_v0.30.28_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS FOLLOW-UP (v0.30.28)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.27's P23/P24 let both threads run CONCURRENTLY and both came")
    log("  back OK - but every real crash (P17/P18/P19) shows thread A running")
    log("  to completion BEFORE thread B starts, never simultaneous access.")
    log("  P23/P24 tested a different, more permissive scenario than the one")
    log("  that actually crashes. This run reruns the same two combinations")
    log("  with thread A explicitly join()-ed to completion before thread B")
    log("  is even created, removing any doubt about overlap.")

    results = {}
    for name, desc, code in PROBES:
        results[name] = run_probe(name, desc, code)

    header("SUMMARY")
    for name, ok in results.items():
        log(f"  {'OK   ' if ok else 'CRASH'}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P25 CRASH          -> minimal repro found; P23's concurrency (not")
    log("                        hand-off) explains why it looked clean.")
    log("  P25 OK, P26 CRASH  -> repetition matters, and only under hand-off.")
    log("  P25 OK, P26 OK     -> the overlap/handoff distinction was not the")
    log("                        missing piece either; bisect convert() itself")
    log("                        directly next, rather than building more")
    log("                        free-standing probes.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
