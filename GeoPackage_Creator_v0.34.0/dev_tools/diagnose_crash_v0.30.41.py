# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.41 - follow-up to
dev_tools/diagnose_crash_v0.30.40.py's P67 result.

WHAT P67 SHOWED
----------------
dev_tools/logs/diagnose_v0.30.40_20260817_115919.log, run on the target
machine on 2026-08-17:

    P64  hand-rolled worker, 5 rounds,  main-thread dispatch   -> OK
    P65  hand-rolled worker, 10 rounds, main-thread dispatch   -> OK
    P66  hand-rolled worker, 5 rounds,  round-thread dispatch  -> OK
    P67  REAL candidate_patch_v0.30.39 worker, 5 rounds,
         main-thread dispatch                                  -> CRASH

P67 is identical to P64 in every respect except one: the lxml side calls the
REAL candidate_patch_v0.30.39/core/metadata_handler.py's actual
validate_schema() / _ensure_lxml_worker_started() / shutdown_lxml_worker(),
instead of a hand-rolled stand-in. Its own log shows the crash happened fast
and needed neither repetition nor an explicit shutdown call: the last stdout
line is "P67: round 1 - starting a NEW GDAL-only worker thread..." - round
1's own "GDAL thread completed its FULL turn" print never appears, so the
crash happened during round 1's real GDAL write (the second round overall),
on a thread that never touched lxml at all (validate_schema is neutered on
every GDAL-only thread in this whole probe series).

WHY THIS DOES NOT FIT EITHER PRIOR FRAMING
---------------------------------------------
No single thread in P67 ever does both GDAL and lxml itself - the
documented P51/P52/P53 necessary condition ("one thread does a real GDAL
write AND a real lxml touch itself, in that order, before a later,
different, freshly-created thread's first lxml touch crashes") is not met
by anything in this probe. The GDAL-only threads never touch lxml; the REAL
persistent worker never touches GDAL. Worse, the thread that crashed was
doing a GDAL write, not an lxml touch - the mirror image of every earlier
finding in this series, where it was always the later thread's first LXML
touch that crashed.

It is also not simply "the real implementation is unconditionally fragile":
`_validate_schema_impl()` (core/metadata_handler.py:548) is documented in
its own docstring as "the v0.30.23 body of MetadataHandler.validate_schema(),
moved here unchanged" - the actual lxml-touching logic P67's worker thread
runs is provably identical to what P64's hand-rolled worker already runs
safely, repeatedly, including its own clean shutdown. Whatever P67 exposed
must live in the thread-lifecycle / dispatch machinery around that logic -
`_ensure_lxml_worker_started()`'s lazy, first-use thread creation, or the
cross-thread handoff where a MetadataHandler instance is constructed on the
calling thread but its `.schema` property is first read on the worker
thread - not in the validation logic itself.

Two concrete, cheap, single-variable differences between P67's shape and
everything that has run clean so far are now exposed:

  1. DISPATCH-THREAD IDENTITY. P67 dispatches from the main thread - a
     thread that itself never touches GDAL - exactly like P64/P65 (both
     OK). But P64/P65 use the hand-rolled worker; nothing has yet tested
     the REAL worker with a dispatch shape where the round's OWN thread
     dispatches its own validation (P66's shape, OK with the hand-rolled
     worker) - which is also, not coincidentally, what the real pipeline
     (validate_patch_v0.30.38.py's P61, 10/10 clean rounds) actually does.

  2. WORKER CREATION TIMING. P67's real worker thread is created lazily,
     on its VERY FIRST validate_schema() call - which happens only after
     round 0's GDAL-only thread has already done a real GDAL write and
     already terminated. P64/P65/P66's hand-rolled worker, by contrast, is
     always created up front, before the round loop starts and before any
     GDAL activity has happened anywhere in the process. Nothing has yet
     tested the REAL worker created that early.

WHAT THIS SCRIPT ISOLATES
----------------------------
Three probes, each a staged run against the REAL candidate_patch_v0.30.39
module (same staging discipline as v0.30.40's P67 and validate_patch_
shutdown_v0.30.39.py's P62/P63) - still cheap, monkey-patched GDAL-only
threads throughout, never the full expensive real pipeline:

  P67R  Control - an EXACT rerun of v0.30.40's P67, unchanged: 5 rounds,
        REAL worker, lazy start on round 0, main-thread dispatch. Expected
        CRASH, matching P67. This is not redundant: P67 has only ever been
        observed to crash once, and P68/P69 are only meaningful as a
        comparison if that crash is a reliably reproducible property of
        this exact shape, not a one-off race that might just as easily not
        have happened the first time either.

  P68   Same as P67R, except each round's OWN GDAL thread also dispatches
        its own validation to the REAL worker (P66's shape), instead of the
        main thread doing it afterward. Isolates dispatch-thread-identity
        alone, holding worker-creation timing (still lazy, still on round
        0) unchanged from P67R.

  P69   Same as P67R (main-thread dispatch unchanged), except the REAL
        worker is forced to start - via one throwaway validate_schema()
        call - BEFORE any GDAL-only thread ever runs in this process.
        Isolates worker-creation timing alone, holding dispatch shape
        (main-thread) unchanged from P67R.

READING THE RESULTS
---------------------
    P67R OK or FAIL       -> P67's crash is not reliably reproducible from
                              this exact shape alone, or the environment has
                              shifted since v0.30.40 ran - reconsider before
                              trusting a P68/P69 comparison built on it.
    P67R CRASH, P68 OK, P69 CRASH
                          -> dispatch-thread identity is the deciding
                             factor - the real implementation is only
                             dangerous when dispatched from a thread that
                             itself never does GDAL. Explains why P61's
                             real pipeline (round-thread-dispatch shape)
                             survived 10 rounds. Creation timing alone does
                             not matter.
    P67R CRASH, P68 CRASH, P69 OK
                          -> worker creation timing is the deciding factor -
                             pre-warming the worker before any GDAL activity
                             avoids the crash regardless of dispatch shape.
                             Concrete, simple, actionable: start the worker
                             eagerly at program/GUI startup. Dispatch-thread
                             identity alone does not matter.
    P67R CRASH, P68 OK, P69 OK
                          -> both single-variable changes independently
                             avoid the crash from P67R's exact combination -
                             the dangerous shape needs lazy-start-after-
                             first-GDAL AND non-GDAL-thread dispatch
                             together. Since the real pipeline already uses
                             P68's dispatch shape naturally, this would be
                             reassuring for the shipped GUI's actual call
                             pattern, but the interaction itself would still
                             be worth a closer look.
    P67R CRASH, P68 CRASH, P69 CRASH
                          -> both variables independently reproduce it -
                             the real worker/dispatch machinery is broadly
                             fragile regardless of dispatch shape or timing.
                             Points at something deeper inside
                             _ensure_lxml_worker_started() /
                             _lxml_worker_loop() / the cross-thread
                             MetadataHandler handoff that neither change
                             avoids.

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series. This is still bisection, not a fix.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Place this script in dev_tools/, alongside candidate_patch_v0.30.39/
(needed by all three probes here - already there from the previous
delivery):

    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.41.py

Writes dev_tools\\logs\\diagnose_v0.30.41_<timestamp>.log incrementally, so a
hard crash still leaves everything up to that point on disk. Send that file
back either way.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEV_TOOLS_DIR = Path(__file__).resolve().parent
LOG_DIR = DEV_TOOLS_DIR / "logs"
CANDIDATE_V39_METADATA_HANDLER = (
    DEV_TOOLS_DIR / "candidate_patch_v0.30.39" / "core" / "metadata_handler.py"
)
CANDIDATE_V39_EXPECTED_VERSION = '__version__ = "0.30.25"'

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


def stage_patched_copy() -> Path:
    """Copy the whole project into a fresh temp directory, then overwrite
    ONLY core/metadata_handler.py with candidate_patch_v0.30.39's file.

    All three probes in this script need this - unlike diagnose_crash_
    v0.30.40.py, where only P67 did - since all three exercise the REAL
    candidate module's actual worker/dispatch functions. Same pattern as
    v0.30.40's own stage_patched_copy() and validate_patch_shutdown_
    v0.30.39.py's: core/metadata_handler.py on the REAL project is never
    touched by this function or anything else in this script. Called once;
    all three probes run against the same staged copy, since staging only
    copies files to disk and nothing in this script's probes mutates them.

    Returns:
        Path to the staged copy's project root.
    """
    stage_root = Path(tempfile.mkdtemp()) / "patched_project"
    shutil.copytree(
        PROJECT_ROOT, stage_root,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    dest_metadata_handler = stage_root / "core" / "metadata_handler.py"
    shutil.copy2(CANDIDATE_V39_METADATA_HANDLER, dest_metadata_handler)
    log(f"  Staged a full project copy at {stage_root}")
    log(f"  Overwrote {dest_metadata_handler} with "
        f"{CANDIDATE_V39_METADATA_HANDLER}")

    staged_version_line = None
    for line in dest_metadata_handler.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            staged_version_line = line.strip()
            break
    log(f"  Staged core/metadata_handler.py reports: {staged_version_line}")
    if staged_version_line != CANDIDATE_V39_EXPECTED_VERSION:
        raise RuntimeError(
            f"STAGING FAILED: staged core/metadata_handler.py does not "
            f"report {CANDIDATE_V39_EXPECTED_VERSION} - the candidate patch "
            f"was not applied correctly. Aborting, since every probe's "
            f"result would be meaningless."
        )
    return stage_root


# ---------------------------------------------------------------------------
# Shared building blocks, textually identical across all three probes so any
# behavioral difference in the results traces back to the one thing each
# probe deliberately varies relative to P67R, not an incidental difference
# in the shapefile or conversion helpers themselves. Identical to v0.30.40's
# _COMMON_HELPERS.
# ---------------------------------------------------------------------------
_COMMON_HELPERS = r'''
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
    real GDAL, zero real lxml in this thread."""
    local_shp = make_shapefile(tag, tmp_root)
    out_path = str(Path(tmp_root) / f"out_{tag}.gpkg")
    converter = GeoPackageConverter(profile="military")
    result = converter.convert(
        source_geodatabase=local_shp,
        output_geopackage=out_path,
        title=f"P67 Follow-up Bisection {tag}",
        abstract="Isolates dispatch-thread identity and worker-creation timing behind diagnose_crash_v0.30.40.py's P67 crash",
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
# P67R (control): an EXACT rerun of v0.30.40's P67 - REAL worker, lazy start
# on round 0, main-thread dispatch, 5 rounds. Confirms the crash is reliably
# reproducible before trusting P68/P69 as a comparison against it.
# ---------------------------------------------------------------------------
P67R_SCRIPT = r'''
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler
from core import metadata_handler as _mh

ROUNDS = 5

_ORIG_VALIDATE_SCHEMA = MetadataHandler.validate_schema

def _noop_validate_schema(self, metadata_xml_string):
    return True

MetadataHandler.validate_schema = _noop_validate_schema

''' + _COMMON_HELPERS + r'''

def validate_via_real_worker(tag):
    """Uses the REAL module's real validate_schema (captured before the
    class-level monkeypatch above), which internally calls the REAL
    _ensure_lxml_worker_started() and dispatches through the REAL
    _LXML_JOBS queue to the REAL _lxml_worker_loop() - not a hand-rolled
    approximation. Called from the main thread, same as P67."""
    handler = MetadataHandler()
    try:
        _ORIG_VALIDATE_SCHEMA(handler, "<x/>")
    except ValueError as e:
        if "ISO 19115 schema validation failed" not in str(e):
            raise


tmp_root = tempfile.mkdtemp()
errors = {}

for round_i in range(ROUNDS):
    tag = f"P67R_r{round_i}"
    print(f"P67R: round {round_i} - starting a NEW GDAL-only worker thread...", flush=True)

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
        print(f"P67R: round {round_i} GDAL thread error: {gdal_error['e']}", flush=True)
        errors[round_i] = f"gdal: {gdal_error['e']}"
        break
    print(f"P67R: round {round_i} GDAL thread completed its FULL turn (patch=lxml neutered).",
          flush=True)

    print(f"P67R: round {round_i} - dispatching validation to the REAL persistent lxml "
          f"worker (candidate_patch_v0.30.39) from the MAIN thread...", flush=True)
    try:
        validate_via_real_worker(tag)
        print(f"P67R: round {round_i} validation completed via the REAL persistent lxml worker",
              flush=True)
    except Exception as e:
        print(f"P67R: round {round_i} validation error: {e}", flush=True)
        errors[round_i] = f"lxml: {e}"
        break

was_alive = _mh._LXML_WORKER_THREAD is not None and _mh._LXML_WORKER_THREAD.is_alive()
print(f"P67R: all {ROUNDS} rounds done, REAL worker thread alive: {was_alive} - "
      f"now calling the REAL shutdown_lxml_worker(timeout=5.0)...", flush=True)
stopped = _mh.shutdown_lxml_worker(timeout=5.0)
print(f"P67R: shutdown_lxml_worker(timeout=5.0) returned {stopped!r}", flush=True)

if errors:
    print(f"P67R: errors: {errors}", flush=True)
    raise SystemExit(1)

print(f"P67R OK - all {ROUNDS} rounds completed and the REAL persistent worker "
      f"stopped cleanly via the REAL shutdown_lxml_worker()", flush=True)
'''


# ---------------------------------------------------------------------------
# P68: same as P67R, except each round's OWN GDAL thread also dispatches its
# own validation to the REAL worker (P66's shape - and the real pipeline's
# actual shape), instead of the main thread doing it afterward. Isolates
# dispatch-thread identity alone; worker creation stays lazy, on round 0,
# same as P67R.
# ---------------------------------------------------------------------------
P68_SCRIPT = r'''
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler
from core import metadata_handler as _mh

ROUNDS = 5

_ORIG_VALIDATE_SCHEMA = MetadataHandler.validate_schema

def _noop_validate_schema(self, metadata_xml_string):
    return True

MetadataHandler.validate_schema = _noop_validate_schema

''' + _COMMON_HELPERS + r'''

def validate_via_real_worker(tag):
    """Called from EACH ROUND'S OWN thread here - a genuinely different,
    freshly-created OS thread each round, not the main thread - right after
    that same thread's own GDAL write. The actual lxml work still only ever
    happens on the REAL persistent worker thread; this thread only calls
    into validate_schema(), which puts a job on the REAL _LXML_JOBS queue
    and waits for its own response."""
    handler = MetadataHandler()
    try:
        _ORIG_VALIDATE_SCHEMA(handler, "<x/>")
    except ValueError as e:
        if "ISO 19115 schema validation failed" not in str(e):
            raise


tmp_root = tempfile.mkdtemp()
errors = {}

for round_i in range(ROUNDS):
    tag = f"P68_r{round_i}"
    print(f"P68: round {round_i} - starting a NEW thread that will do GDAL AND "
          f"dispatch its own validation to the REAL worker...", flush=True)

    round_error = {}
    def round_worker():
        try:
            run_conversion_gdal_only(tag, tmp_root)
            validate_via_real_worker(tag)
        except Exception as e:
            round_error["e"] = str(e)

    t = threading.Thread(target=round_worker)
    t.start()
    t.join(timeout=30)
    if "e" in round_error:
        print(f"P68: round {round_i} error: {round_error['e']}", flush=True)
        errors[round_i] = round_error["e"]
        break
    print(f"P68: round {round_i} completed - GDAL write and dispatch/response both done "
          f"on the same, single, freshly-created thread for this round, against the "
          f"REAL persistent worker.", flush=True)

was_alive = _mh._LXML_WORKER_THREAD is not None and _mh._LXML_WORKER_THREAD.is_alive()
print(f"P68: all {ROUNDS} rounds done, REAL worker thread alive: {was_alive} - "
      f"now calling the REAL shutdown_lxml_worker(timeout=5.0)...", flush=True)
stopped = _mh.shutdown_lxml_worker(timeout=5.0)
print(f"P68: shutdown_lxml_worker(timeout=5.0) returned {stopped!r}", flush=True)

if errors:
    print(f"P68: errors: {errors}", flush=True)
    raise SystemExit(1)

print(f"P68 OK - all {ROUNDS} rounds completed and the REAL persistent worker "
      f"stopped cleanly via the REAL shutdown_lxml_worker()", flush=True)
'''


# ---------------------------------------------------------------------------
# P69: same as P67R (main-thread dispatch unchanged), except the REAL
# worker is forced to start - via one throwaway validate_schema() call -
# BEFORE any GDAL-only thread ever runs in this process. Isolates worker
# creation timing alone; dispatch shape stays main-thread, same as P67R.
# ---------------------------------------------------------------------------
P69_SCRIPT = r'''
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler
from core import metadata_handler as _mh

ROUNDS = 5

_ORIG_VALIDATE_SCHEMA = MetadataHandler.validate_schema

def _noop_validate_schema(self, metadata_xml_string):
    return True

MetadataHandler.validate_schema = _noop_validate_schema

''' + _COMMON_HELPERS + r'''

def validate_via_real_worker(tag):
    handler = MetadataHandler()
    try:
        _ORIG_VALIDATE_SCHEMA(handler, "<x/>")
    except ValueError as e:
        if "ISO 19115 schema validation failed" not in str(e):
            raise


# Pre-warm the REAL persistent worker BEFORE any GDAL activity has happened
# anywhere in this process - this is the one thing that differs from P67R.
# P67R's worker is created lazily, on round 0's validation call, which
# happens only after round 0's GDAL-only thread has already done a real
# GDAL write and already terminated. This call forces that same lazy
# creation to happen right now instead, before any GDAL write has ever
# occurred in this process.
print("P69: pre-warming the REAL persistent worker BEFORE any GDAL activity "
      "in this process...", flush=True)
validate_via_real_worker("P69_prewarm")
was_alive_prewarm = _mh._LXML_WORKER_THREAD is not None and _mh._LXML_WORKER_THREAD.is_alive()
print(f"P69: pre-warm complete, REAL worker thread alive: {was_alive_prewarm}", flush=True)

tmp_root = tempfile.mkdtemp()
errors = {}

for round_i in range(ROUNDS):
    tag = f"P69_r{round_i}"
    print(f"P69: round {round_i} - starting a NEW GDAL-only worker thread...", flush=True)

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
        print(f"P69: round {round_i} GDAL thread error: {gdal_error['e']}", flush=True)
        errors[round_i] = f"gdal: {gdal_error['e']}"
        break
    print(f"P69: round {round_i} GDAL thread completed its FULL turn (patch=lxml neutered).",
          flush=True)

    print(f"P69: round {round_i} - dispatching validation to the REAL persistent lxml "
          f"worker (candidate_patch_v0.30.39) from the MAIN thread...", flush=True)
    try:
        validate_via_real_worker(tag)
        print(f"P69: round {round_i} validation completed via the REAL persistent lxml worker",
              flush=True)
    except Exception as e:
        print(f"P69: round {round_i} validation error: {e}", flush=True)
        errors[round_i] = f"lxml: {e}"
        break

was_alive = _mh._LXML_WORKER_THREAD is not None and _mh._LXML_WORKER_THREAD.is_alive()
print(f"P69: all {ROUNDS} rounds done, REAL worker thread alive: {was_alive} - "
      f"now calling the REAL shutdown_lxml_worker(timeout=5.0)...", flush=True)
stopped = _mh.shutdown_lxml_worker(timeout=5.0)
print(f"P69: shutdown_lxml_worker(timeout=5.0) returned {stopped!r}", flush=True)

if errors:
    print(f"P69: errors: {errors}", flush=True)
    raise SystemExit(1)

print(f"P69 OK - all {ROUNDS} rounds completed (worker pre-warmed before any GDAL "
      f"activity) and the REAL persistent worker stopped cleanly via the REAL "
      f"shutdown_lxml_worker()", flush=True)
'''


PROBES: "list[tuple[str, str, str, int]]" = [
    (
        "P67R_control_rerun",
        "Control: an EXACT rerun of diagnose_crash_v0.30.40.py's P67 - 5 "
        "rounds, REAL worker, lazy start on round 0, main-thread dispatch. "
        "Expected CRASH, matching P67 - confirms the crash is reliably "
        "reproducible from this exact shape before trusting P68/P69 as a "
        "comparison against it.",
        P67R_SCRIPT,
        120,
    ),
    (
        "P68_dispatch_from_round_thread_real",
        "Same as P67R, except each round's own GDAL thread also dispatches "
        "its own validation to the REAL worker (P66's shape, and the real "
        "pipeline's actual shape), instead of the main thread doing it "
        "afterward. Isolates dispatch-thread identity alone.",
        P68_SCRIPT,
        120,
    ),
    (
        "P69_prewarmed_worker_real",
        "Same as P67R (main-thread dispatch unchanged), except the REAL "
        "worker is forced to start, via one throwaway validate_schema() "
        "call, BEFORE any GDAL-only thread ever runs in this process. "
        "Isolates worker-creation timing alone.",
        P69_SCRIPT,
        120,
    ),
]


def run_probe(name: str, desc: str, code: str, root_for_probe: Path, timeout: int) -> str:
    """Runs one probe against *root_for_probe* and returns its tag: "OK",
    "FAIL", or "CRASH". All three probes in this script pass the SAME
    staged copy (see stage_patched_copy(), called once in main())."""
    header(name)
    log(f"  {desc}")

    f = Path(tempfile.mkdtemp()) / f"{name}.py"
    f.write_text(code, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(f), str(root_for_probe)],
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
    path = LOG_DIR / f"diagnose_v0.30.41_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - P67 FOLLOW-UP BISECTION (v0.30.41)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  Follows up on diagnose_crash_v0.30.40.py's P67: the REAL persistent")
    log("  lxml worker (candidate_patch_v0.30.39) crashed on round 1 of 5 - fast,")
    log("  with no repetition and no explicit shutdown call needed - in a shape")
    log("  that fits neither the original P51/P52/P53 framing (no single thread")
    log("  did GDAL then lxml itself) nor a simple 'real implementation is just")
    log("  unconditionally broken' theory (its actual lxml logic is documented as")
    log("  unchanged from the v0.30.23 body P64's hand-rolled worker already runs")
    log("  safely). This script isolates the two cheapest remaining candidate")
    log("  differences - which thread dispatches, and when the worker thread is")
    log("  created relative to the process's first GDAL write - one at a time,")
    log("  after first confirming P67's crash reproduces reliably. See this")
    log("  script's own module docstring for the full reasoning.")

    if not CANDIDATE_V39_METADATA_HANDLER.exists():
        header("SETUP ERROR")
        log(f"  {CANDIDATE_V39_METADATA_HANDLER} does not exist.")
        log(f"  All three probes in this script need it - unlike v0.30.40, there")
        log(f"  is nothing useful this script can run without it. Place")
        log(f"  candidate_patch_v0.30.39/ in dev_tools/, next to this script, and")
        log(f"  re-run.")
        _LOG_FH.close()
        print()
        print(f"Log written to: {path}")
        return 1

    tags = {}
    try:
        staged_root = stage_patched_copy()
    except RuntimeError as e:
        header("SETUP ERROR")
        log(f"  {e}")
        _LOG_FH.close()
        print()
        print(f"Log written to: {path}")
        return 1

    for name, desc, code, timeout in PROBES:
        tags[name] = run_probe(name, desc, code, staged_root, timeout)

    header("SUMMARY")
    for name, tag in tags.items():
        label = {"OK": "OK   ", "FAIL": "FAIL ", "CRASH": "CRASH"}[tag]
        log(f"  {label}  {name}")

    log("")
    log("  (for reference, from diagnose_v0.30.40_20260817_115919.log:)")
    log("  OK     P64_control_p55_rerun")
    log("  OK     P65_repetition_ten_rounds")
    log("  OK     P66_dispatch_from_round_thread")
    log("  CRASH  P67_real_module_implementation  (round 1 of 5, no repetition/shutdown needed)")

    log("")
    log("READING THE RESULTS:")
    log("  P67R OK or FAIL          -> P67's crash is not reliably reproducible")
    log("                              from this exact shape alone, or the")
    log("                              environment has shifted since v0.30.40 ran -")
    log("                              reconsider before trusting a P68/P69")
    log("                              comparison built on it.")
    log("  P67R CRASH, P68 OK, P69 CRASH")
    log("                           -> dispatch-thread identity is the deciding")
    log("                              factor - dangerous only when dispatched from")
    log("                              a thread that itself never does GDAL.")
    log("                              Explains why P61's real pipeline (round-")
    log("                              thread-dispatch shape) survived 10 rounds.")
    log("  P67R CRASH, P68 CRASH, P69 OK")
    log("                           -> worker creation timing is the deciding")
    log("                              factor - pre-warming before any GDAL")
    log("                              activity avoids the crash regardless of")
    log("                              dispatch shape. Concrete, actionable fix:")
    log("                              start the worker eagerly at startup.")
    log("  P67R CRASH, P68 OK, P69 OK")
    log("                           -> both changes independently avoid the crash -")
    log("                              the dangerous shape needs P67R's exact")
    log("                              combination together. Reassuring for the")
    log("                              real GUI's actual (P68-shaped) call pattern,")
    log("                              but the interaction itself still needs a")
    log("                              closer look.")
    log("  P67R CRASH, P68 CRASH, P69 CRASH")
    log("                           -> both variables independently reproduce it -")
    log("                              the real worker/dispatch machinery is")
    log("                              broadly fragile regardless of dispatch shape")
    log("                              or timing. Points at something deeper inside")
    log("                              _ensure_lxml_worker_started() /")
    log("                              _lxml_worker_loop() / the cross-thread")
    log("                              MetadataHandler handoff.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
