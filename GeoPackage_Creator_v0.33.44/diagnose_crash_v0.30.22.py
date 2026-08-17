# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.22 - follow-up to v0.30.21.

WHY THIS EXISTS
---------------
The 2026-08-14 run of `diagnose_crash_v0.30.21.py` on the real machine (GDAL
3.13.2, lxml 6.1.1, both loading a version-matched libxml2 2.14.6) produced a
sharp differential:

    P1 lxml alone                                    OK
    P2 GDAL alone                                     OK
    P3 import both, no work                           OK
    P4 GDAL write, THEN compile schema, THEN validate  OK
    P5 compile schema, THEN GDAL write, THEN parse     CRASH
    P6 compile schema, THEN GDAL write, THEN validate  CRASH
    P7 compile+discard, GDAL write, recompile+validate OK
    P8 same as P6 with GDAL's XML options disabled     CRASH (no effect)

The dividing line is exact: an lxml object (here, a compiled `XMLSchema`)
that is CREATED before a GDAL write and remains ALIVE (referenced by a
variable) past that write crashes when it is next touched or freed. An
object entirely on one side of a write - created after, or created before
but immediately dereferenced so CPython's refcounting frees it before the
write runs - is fine.

This matches the real bug precisely: `core/metadata_handler.py`'s
`_SHARED_SCHEMA` is compiled EXACTLY ONCE, lazily, on the first metadata
call, and then cached in a module-level global for the rest of the process.
Once compiled, it inevitably spans every GDAL write for the rest of the run.

WHAT THIS SCRIPT DECIDES
------------------------
One thing is still unknown, and it determines what the real fix has to look
like:

  (a) Is GDAL's libxml2 state disturbed ONCE (e.g. some lazy one-time
      global registration on its first XML-touching internal call)? If so,
      a schema compiled AFTER the first write should safely survive any
      NUMBER of further writes - the cheap fix is to defer `_SHARED_SCHEMA`'s
      first compile until after a warm-up write, and the existing
      process-wide cache can stay exactly as it is.

  (b) Or does EVERY SINGLE write disturb live libxml2 objects, regardless of
      when they were created? If so, no schema can ever be cached across
      more than one write - the fix has to recompile fresh, immediately
      before every validate() call, and let it die immediately after. That
      removes the performance win `_SHARED_SCHEMA` exists for, but it is the
      only pattern P7 proves is safe.

  P9  tests hypothesis (a): compile once after a warm-up write, then reuse
      that SAME schema object across four MORE writes.
  P10 tests hypothesis (b): recompile a fresh schema immediately before each
      of four writes' validate call, discarding it right after each use -
      the candidate real fix, exercised repeatedly rather than once.
  P11 is a direct, minimal reproduction of the real code's actual shape for
      the record: compile once (as `_SHARED_SCHEMA` does, before any write
      has necessarily happened yet), then validate after each of several
      writes with that same object. Expected to crash on the very first
      iteration, matching P6 - included so the log is self-documenting
      without needing last run's log alongside it.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
---------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.22.py

Writes dev_tools\\logs\\diagnose_v0.30.22_<timestamp>.log incrementally, so a
hard crash still leaves everything up to that point on disk. Send that file
back either way.
"""

from __future__ import annotations

import os
import subprocess
import sys
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


PREAMBLE = r'''
import sys, tempfile
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
XSD = root / "schemas" / "iso19139-gmd.xsd"

def gdal_write(tag="w"):
    from osgeo import ogr, osr
    tmp = Path(tempfile.mkdtemp()) / (tag + ".gpkg")
    drv = ogr.GetDriverByName("GPKG")
    ds = drv.CreateDataSource(str(tmp))
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    lyr = ds.CreateLayer("pts", srs=srs, geom_type=ogr.wkbPoint)
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetGeometry(ogr.CreateGeometryFromWkt("POINT (1 2)"))
    lyr.CreateFeature(f)
    f = None; ds = None
'''

PROBES: list[tuple[str, str, str]] = [
    (
        "P9_warmup_then_reuse_across_writes",
        "Hypothesis (a) - ONE-TIME global disturbance. write (warm-up), "
        "compile ONCE, then reuse that SAME schema across 4 MORE writes. "
        "If this survives, deferring _SHARED_SCHEMA's first compile past a "
        "warm-up write is sufficient and caching can stay as-is.",
        PREAMBLE + r'''
from lxml import etree
gdal_write("p9_warmup")
schema = etree.XMLSchema(etree.parse(str(XSD)))
print("P9: warm-up write + compile done, reusing across 4 more writes", flush=True)
for i in range(4):
    gdal_write(f"p9_{i}")
    schema.validate(etree.fromstring(b"<x/>"))
    print(f"P9: survived write #{i+1} after warm-up", flush=True)
print("P9 OK", flush=True)
''',
    ),
    (
        "P10_recompile_fresh_every_time",
        "Hypothesis (b) - EVERY write disturbs live objects. write, "
        "recompile a FRESH schema, validate, discard - repeated 4 times. "
        "This is the candidate real fix: never let any schema instance "
        "span more than the single write immediately before it.",
        PREAMBLE + r'''
from lxml import etree
for i in range(4):
    gdal_write(f"p10_{i}")
    schema = etree.XMLSchema(etree.parse(str(XSD)))
    schema.validate(etree.fromstring(b"<x/>"))
    del schema
    print(f"P10: fresh-compile-and-discard cycle #{i+1} survived", flush=True)
print("P10 OK", flush=True)
''',
    ),
    (
        "P11_real_code_shape_multi_write",
        "Direct reproduction of _SHARED_SCHEMA's actual shape: compile ONCE "
        "before any write (worst case - matches how the real cache can be "
        "populated mid-first-conversion), then validate after each of "
        "several writes with that same object. Expected to crash on the "
        "very first iteration, same as P6 - included for a self-contained "
        "log.",
        PREAMBLE + r'''
from lxml import etree
schema = etree.XMLSchema(etree.parse(str(XSD)))
print("P11: schema compiled before any write (matches _SHARED_SCHEMA worst case)", flush=True)
for i in range(3):
    gdal_write(f"p11_{i}")
    schema.validate(etree.fromstring(b"<x/>"))
    print(f"P11: survived write #{i+1}", flush=True)
print("P11 OK", flush=True)
''',
    ),
]


def run_probe(name: str, desc: str, code: str) -> bool:
    header(name)
    log(f"  {desc}")
    import tempfile

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
    path = LOG_DIR / f"diagnose_v0.30.22_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS FOLLOW-UP (v0.30.22)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.21 established: an lxml object created before a GDAL write")
    log("  and still alive after it crashes when next touched or freed. This")
    log("  run decides whether that disturbance happens ONCE per process (P9)")
    log("  or on EVERY write (P10), which determines the actual code fix.")

    results = {}
    for name, desc, code in PROBES:
        results[name] = run_probe(name, desc, code)

    header("SUMMARY")
    for name, ok in results.items():
        log(f"  {'OK   ' if ok else 'CRASH'}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P9 OK    -> one-time disturbance. Fix: defer _SHARED_SCHEMA's")
    log("              first compile past a warm-up GDAL write; keep caching.")
    log("  P9 CRASH -> every write disturbs it, even a schema born after a")
    log("              prior write is not safe across a SECOND write.")
    log("  P10 OK   -> recompiling fresh immediately before every validate,")
    log("              every time, is safe. This is the fallback fix if P9")
    log("              fails: drop the process-wide cache entirely.")
    log("  P10 CRASH-> even a freshly-recompiled, immediately-used, ")
    log("              immediately-discarded schema is not safe. That would")
    log("              point away from schema lifetime entirely and back")
    log("              toward the GDAL driver, DLL search order, or the")
    log("              specific data going into this schema/doc pair.")
    log("  P11      -> expected CRASH (documentation/regression check only,")
    log("              reproduces P6's exact shape for a self-contained log).")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
