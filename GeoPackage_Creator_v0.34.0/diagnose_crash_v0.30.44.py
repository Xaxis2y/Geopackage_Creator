# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.44 - four probes localizing
dev_tools/validate_patch_shutdown_v0.30.39.py's still-unexplained P62
shutdown crash, now that diagnose_crash_v0.30.43.py's P73/P74 results are in.

WHAT v0.30.43 SHOWED
----------------------
dev_tools/logs/diagnose_v0.30.43_20260817_124536.log:

    P73  real worker, patched _lxml_worker_loop() that stringifies a
         failing validation's exception INSIDE the worker thread before it
         crosses the queue, trivial FAILING document      -> OK (5/5 rounds)
    P74  REAL, unmonkeypatched pipeline, 10 rounds, _validate_schema_impl()
         wrapped in a transparent counting layer           -> CRASH (inside
         shutdown_lxml_worker(), after "calls=30 passed=30 failed=0" -
         zero validation failures anywhere)

P73 is direct, positive confirmation of the mechanism its own docstring
proposed: a failing validation's exception, queued as a live object with
its original traceback (pinning the worker thread's `schema`/`doc` locals),
crossing the worker-to-caller queue and being re-raised on the dispatching
thread. Stringifying it inside the worker before it crosses avoids the
crash. That mechanism only ever fires when a validation FAILS.

P74 shows the real pipeline never failed a single validation across all 30
real calls in 10 rounds, and crashed anyway - inside `shutdown_lxml_worker()`
itself (the log never reaches "shutdown_lxml_worker(timeout=5.0) returned
...", unlike P73's run, which does). Since P73's mechanism requires a
failure and none occurred, this is exactly the outcome v0.30.43's own module
docstring called out in advance: P62 is a SEPARATE, still-unexplained third
mechanism, not another instance of the exception-crossing one.

THE THREE MECHANISMS NOW ON THE BOARD
----------------------------------------
1. The original one this whole series exists to fix: one OS thread
   performing a real GDAL write and a real lxml touch itself
   (`diagnose_crash_v0.30.34.py` probes P51/P52/P53). Closed by routing
   every lxml/schema call in the process to one persistent worker thread
   that never does GDAL work itself (`_ensure_lxml_worker_started()` /
   `_lxml_worker_loop()` below). Four independent clean results
   (P52/P55/P57/P59). Unaffected by anything in this script.
2. A live exception object crossing the worker-to-caller queue on a
   FAILING validation, carrying a traceback that pins libxml2-backed
   locals to the wrong thread. Just confirmed real by P73, and fixable by
   stringifying inside the worker before the queue.
3. Whatever crashes inside `shutdown_lxml_worker()` once the worker thread
   has done real work and is asked to stop and be joined - confirmed by
   P74 to be unrelated to mechanism 2. THIS is what this script probes.

It is also worth being precise, per `candidate_patch_v0.30.39/core/
metadata_handler.py`'s own "PERSISTENT WORKER SHUTDOWN" section, that
mechanism 3 is not unique to the EXPLICIT shutdown path either:
`validate_patch_v0.30.38.py`'s P61 - same real pipeline, same 10 rounds,
but never calling any shutdown function at all (it did not exist yet at
that candidate version), just letting the process exit normally with the
daemon worker thread still blocked - crashed too, after all 10 rounds
completed, during ordinary interpreter finalization instead of inside a
function call. Whatever this is, both "join it explicitly" and "never
touch it, let teardown handle it" end in the same access violation once
the worker thread has done real libxml2 work.

WHAT THIS SCRIPT DOES
-------------------------
Four probes, each changing exactly one thing relative to P74's shape
(10-round real pipeline, zero-failure instrumented) or relative to each
other, to localize mechanism 3 along three independent axes: how much real
work the worker needs to have done, whether GDAL needs to be involved
anywhere in the process at all, and whether the crash is specific to the
explicit `shutdown_lxml_worker()` call path or survives even bypassing
ordinary Python-level interpreter finalization.

  P75  Never-used worker, immediate shutdown. Starts the REAL persistent
       worker via the REAL `_ensure_lxml_worker_started()`, dispatches
       ZERO jobs to it - no validation, no GDAL, nothing - then
       immediately calls the REAL `shutdown_lxml_worker()`. Cheapest
       possible next data point: does the crash need ANY real work at
       all, or is merely creating and stopping this specific worker
       thread already unsafe regardless of payload?

  P76  Real lxml validation, GDAL NEVER imported anywhere in the process.
       Dispatches 10 rounds of REAL `generate_package_metadata()` +
       explicit `validate_schema()` calls (20 real worker dispatches, all
       passing, against the REAL bundled XSD) to the REAL persistent
       worker, then shuts it down - but imports the candidate
       metadata_handler.py from an ISOLATED `core_min/` package (built by
       `stage_gdal_free_copy()` below) instead of the real `core` package,
       specifically because `core/__init__.py` unconditionally does `from
       .converter import GeoPackageConverter`, which imports
       `gdal_handler.py`, which does `from osgeo import ogr, osr, gdal` at
       module level - so importing anything under the real `core/` package
       loads GDAL's native DLLs into the process as a side effect, even if
       no GDAL function is ever called. This is the only way to test
       "real lxml work happens, GDAL is never touched anywhere in this
       process" with a real prior. Extends P46/P47's finding (established
       for mechanism 1: pure lxml activity, GDAL never involved anywhere,
       never crashes) to mechanism 3 specifically - which has never been
       tested this way before, since every prior real-pipeline probe
       necessarily also ran real GDAL writes every round.

  P77  Ten real rounds, NO explicit shutdown call. Identical to P74 - real
       pipeline, 10 rounds, `_validate_schema_impl()` wrapped in the same
       transparent counting layer - except it never calls
       `shutdown_lxml_worker()` at all; the script just returns and lets
       the process exit normally with the daemon worker still blocked.
       Directly re-tests P61's exact shape, but under the CURRENT
       candidate (v0.30.39 / internal `__version__ = "0.30.25"`, which P61
       itself never ran against - P61 used the earlier v0.30.24 candidate,
       before `shutdown_lxml_worker()` existed) and with today's pass/fail
       instrumentation, for a clean, direct comparison against P74.

  P78  Same as P77 (10 real rounds, no explicit shutdown call), except
       immediately after the rounds finish the script calls `os._exit(0)`
       instead of returning normally. `os._exit()` skips CPython's own
       interpreter finalization: no garbage collection, no atexit hooks,
       none of `threading._shutdown()`'s handling of any thread still
       running. It does NOT skip Windows' own DLL_PROCESS_DETACH
       notification to every loaded DLL, which fires on any process exit
       path, including this one. So this probe isolates whether the
       crash is caused by code that runs during ORDINARY Python-level
       shutdown specifically, or survives even with that layer skipped.

READING THE RESULTS
---------------------
    P75 CRASH -> the crash needs NOTHING beyond creating and immediately
                 stopping this specific worker thread - no real lxml work,
                 no GDAL, no payload of any kind. Points hard at the
                 daemon-thread/queue/join mechanics themselves (or a
                 pre-existing environment issue), not at libxml2 or GDAL
                 state.
    P75 OK    -> some real work is a necessary ingredient; P76/P77/P78
                 narrow which kind.

    P76 CRASH -> GDAL is NOT a necessary ingredient for mechanism 3: real
                 lxml activity on a thread that is later stopped is
                 unsafe here on its own - materially different from
                 mechanism 1, where GDAL is a confirmed, necessary
                 ingredient (P46/P47).
    P76 OK    -> GDAL's presence/activity somewhere in the process is
                 still necessary, even for mechanism 3 - consistent with
                 the "a GDAL write disturbs live libxml2 state" throughline
                 CRASH_INVESTIGATION_STATUS_2026-08-17.md already names
                 across the other two mechanisms.

    P77 CRASH (at ordinary interpreter exit, no traceback, matching P61's
               own shape) -> confirms this is the same underlying hazard
               P61 and P74 both hit, just observed at two different
               trigger points - `shutdown_lxml_worker()` is not creating a
               NEW problem, only surfacing an existing one earlier, inside
               a catchable function call instead of during interpreter
               finalization.
    P77 OK    -> skipping the explicit stop-and-join avoids the crash
               entirely under otherwise identical conditions - a
               surprising, directly actionable result on its own (it
               would argue for NOT calling `shutdown_lxml_worker()` at
               all, the opposite of v0.30.39's original premise), and
               would mean P61 itself may not be reliably reproducible and
               is worth a second look.

    P78 OK (no crash even with the explicit shutdown skipped AND
            CPython's own finalization/GC/atexit bypassed via
            os._exit(0)) -> narrows the cause to something in CPython's
            OWN interpreter finalization / threading._shutdown() / GC
            layer specifically, since Windows' DLL_PROCESS_DETACH
            notification to every loaded DLL still ran regardless and did
            not, by itself, crash. Opens a real, much cheaper mitigation
            angle worth weighing alongside continuing to hunt the root
            cause: have the real GUI/CLI call os._exit() once all real
            work is verifiably complete, rather than relying on (or
            fighting with) ordinary interpreter shutdown.
    P78 CRASH (even with os._exit(0)) -> the hazard survives even without
            CPython's own finalization running, so it is either in
            Windows' DLL_PROCESS_DETACH-time native cleanup itself, or in
            whatever the abbreviated CRT _exit() path still triggers - no
            amount of doing less work in Python can avoid it, and "clean
            up more carefully in Python" stops being a viable direction on
            its own.

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series. This is still bisection and
observation, not a fix.

VERIFICATION BEFORE DELIVERY
-------------------------------
This sandbox has no GDAL/osgeo (P75/P77/P78's conversions cannot be
executed here) and is Linux, not the Windows target machine, so none of
these probes can be made to reproduce the actual access violation here
even where GDAL is not the blocker. What COULD be verified here, and was,
against the REAL candidate_patch_v0.30.39/core/metadata_handler.py and the
REAL bundled schemas/iso19139-gmd.xsd (this sandbox does have a working
lxml): the P75-equivalent sequence (start the real persistent worker,
dispatch zero jobs, call the real shutdown_lxml_worker()) runs clean and
returns True; the P76-equivalent sequence (import the candidate module
through an isolated core_min/ package built the same way
stage_gdal_free_copy() builds it below, run three rounds of real
generate_package_metadata() + validate_schema() calls, confirm
get_schema_source_path() resolves to the real schema file inside the
isolated layout rather than None) runs clean, every validation returns
True, and osgeo never enters sys.modules at any point. That confirms the
harness logic itself - the isolation mechanism, the schema path
assumption, the worker start/stop calls - is correct, independent of
whatever the target machine's result turns out to be.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Place this script in dev_tools/, alongside candidate_patch_v0.30.39/
(needed by P75/P76/P77/P78 - already there from an earlier delivery):

    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.44.py

Writes dev_tools\\logs\\diagnose_v0.30.44_<timestamp>.log incrementally, so
a hard crash still leaves everything up to that point on disk. Send that
file back either way.
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


def _read_version_line(path: Path) -> "str | None":
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.strip()
    return None


def stage_patched_copy() -> Path:
    """Copy the whole project into a fresh temp directory, then overwrite
    ONLY core/metadata_handler.py with candidate_patch_v0.30.39's file.
    P75, P77, and P78 all run against this same staged copy - the real
    `core` package, real GDAL, real everything except that one file."""
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

    staged_version_line = _read_version_line(dest_metadata_handler)
    log(f"  Staged core/metadata_handler.py reports: {staged_version_line}")
    if staged_version_line != CANDIDATE_V39_EXPECTED_VERSION:
        raise RuntimeError(
            f"STAGING FAILED: staged core/metadata_handler.py does not "
            f"report {CANDIDATE_V39_EXPECTED_VERSION} - the candidate patch "
            f"was not applied correctly. Aborting, since every probe's "
            f"result would be meaningless."
        )
    return stage_root


def stage_gdal_free_copy() -> Path:
    """Build an isolated, GDAL-free package for P76 only: a temp root
    containing ONLY core_min/ (a trivial empty __init__.py, the real
    core/config.py, and candidate_patch_v0.30.39's metadata_handler.py) and
    a real copy of schemas/ as core_min's SIBLING - preserving the exact
    relative layout `_locate_schema_file()` depends on
    (`Path(__file__).parent.parent / "schemas"`), so P76 compiles and
    validates against the REAL bundled XSD, not a stand-in that would
    silently take the "no schema found, skip validation" path instead.

    Deliberately does NOT copy core/__init__.py, converter.py, or
    gdal_handler.py - those are exactly what must never be importable here,
    since core/__init__.py unconditionally does `from .converter import
    GeoPackageConverter`, which imports `from osgeo import ogr, osr, gdal`
    at module level. The probe imports this as `from core_min import
    metadata_handler`, never `from core import ...`.
    """
    stage_root = Path(tempfile.mkdtemp()) / "gdal_free_project"
    core_min_dir = stage_root / "core_min"
    core_min_dir.mkdir(parents=True)
    (core_min_dir / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(PROJECT_ROOT / "core" / "config.py", core_min_dir / "config.py")
    shutil.copy2(CANDIDATE_V39_METADATA_HANDLER, core_min_dir / "metadata_handler.py")
    shutil.copytree(PROJECT_ROOT / "schemas", stage_root / "schemas")
    log(f"  Staged a GDAL-free package at {stage_root}")
    log(f"  core_min/ contains only __init__.py (empty), config.py, and "
        f"metadata_handler.py - no core/__init__.py, converter.py, or "
        f"gdal_handler.py anywhere on this probe's sys.path")

    staged_version_line = _read_version_line(core_min_dir / "metadata_handler.py")
    log(f"  Staged core_min/metadata_handler.py reports: {staged_version_line}")
    if staged_version_line != CANDIDATE_V39_EXPECTED_VERSION:
        raise RuntimeError(
            f"STAGING FAILED: staged core_min/metadata_handler.py does not "
            f"report {CANDIDATE_V39_EXPECTED_VERSION} - the candidate patch "
            f"was not applied correctly. Aborting, since P76's result would "
            f"be meaningless."
        )
    return stage_root


# ---------------------------------------------------------------------------
# P75: never-used worker, immediate shutdown. Cheapest possible next data
# point - does the crash need ANY real work at all?
# ---------------------------------------------------------------------------
P75_SCRIPT = r'''
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from core import metadata_handler as _mh

print("P75: starting the REAL persistent lxml worker via the REAL "
      "_ensure_lxml_worker_started() - zero jobs will ever be dispatched to "
      "it, no validate_schema() call, no GDAL write, nothing...", flush=True)
_mh._ensure_lxml_worker_started()

was_alive = _mh._LXML_WORKER_THREAD is not None and _mh._LXML_WORKER_THREAD.is_alive()
print(f"P75: worker thread alive: {was_alive} - now calling the REAL "
      f"shutdown_lxml_worker(timeout=5.0) immediately, having dispatched "
      f"zero jobs of any kind...", flush=True)
stopped = _mh.shutdown_lxml_worker(timeout=5.0)
print(f"P75: shutdown_lxml_worker(timeout=5.0) returned {stopped!r}", flush=True)

if not stopped:
    print("P75: worker did not report a clean stop", flush=True)
    raise SystemExit(1)

print("P75 OK - the persistent worker thread was created and stopped "
      "cleanly via the REAL shutdown_lxml_worker(), having done ZERO real "
      "work of any kind - no lxml, no GDAL", flush=True)
'''


# ---------------------------------------------------------------------------
# P76: real lxml validation, GDAL NEVER imported anywhere in the process.
# Imports the candidate module through an isolated core_min/ package (see
# stage_gdal_free_copy() above) instead of the real core package, since the
# real core/__init__.py unconditionally imports osgeo as a side effect of
# being imported at all.
# ---------------------------------------------------------------------------
P76_SCRIPT = r'''
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

# Deliberately "from core_min import metadata_handler", never "from core
# import ...": core/__init__.py unconditionally does `from .converter import
# GeoPackageConverter`, which imports gdal_handler.py, which does `from
# osgeo import ogr, osr, gdal` at module level - so importing anything under
# the real core/ package loads GDAL's native DLLs into this process as a
# side effect, regardless of whether any GDAL function is ever called. This
# probe's whole point is a process where that never happens. core_min/
# (built by stage_gdal_free_copy() in this script, before this subprocess
# was ever launched) contains only an empty __init__.py, the real
# config.py, and this file's own candidate_patch_v0.30.39
# metadata_handler.py - nothing that can reach osgeo.
from core_min import metadata_handler as _mh

assert "osgeo" not in sys.modules and "gdal" not in sys.modules, (
    "GDAL is already in sys.modules before this probe did anything - the "
    "isolation failed before the test even started and this run cannot be "
    "trusted"
)

_mh._ensure_lxml_worker_started()
handler = _mh.MetadataHandler()

ROUNDS = 10
for round_i in range(ROUNDS):
    print(f"P76: round {round_i} - generating REAL package metadata and "
          f"validating it against the REAL bundled XSD via the REAL "
          f"persistent worker (GDAL not imported anywhere in this "
          f"process)...", flush=True)
    xml_str = handler.generate_package_metadata(
        title=f"P76 GDAL-Free Isolation round {round_i}",
        abstract="Isolates whether GDAL needs to be involved anywhere in "
                 "the process for the persistent worker's shutdown to "
                 "crash, or whether real lxml activity alone is already "
                 "sufficient.",
        poc="Test User",
        org="Test Org",
        nation="USA",
        security="UNCLASSIFIED",
        language="eng",
        topic_category="boundaries",
        ref_date="2026-08-17",
    )
    # generate_package_metadata() already dispatched one real validate_
    # schema() call to the worker internally as its own self-check; this
    # is a second, explicit dispatch, matching the "2 real calls per round"
    # shape verified standalone before this script was sent.
    ok = handler.validate_schema(xml_str)
    print(f"P76: round {round_i} - explicit validate_schema() call "
          f"returned {ok!r}", flush=True)
    if ok is not True:
        print(f"P76: round {round_i} - unexpected non-True result, "
              f"aborting", flush=True)
        raise SystemExit(1)

assert "osgeo" not in sys.modules and "gdal" not in sys.modules, (
    "GDAL appeared in sys.modules during the rounds - the isolation broke "
    "partway through and this run cannot be trusted"
)

schema_source = _mh.get_schema_source_path()
print(f"P76: resolved schema source path: {schema_source}", flush=True)
if schema_source is None:
    print("P76: schema was never located - this run validated nothing "
          "against a real schema and cannot be trusted", flush=True)
    raise SystemExit(1)

was_alive = _mh._LXML_WORKER_THREAD is not None and _mh._LXML_WORKER_THREAD.is_alive()
print(f"P76: all {ROUNDS} rounds done, worker thread alive: {was_alive}, "
      f"GDAL confirmed never imported anywhere in this process (checked "
      f"via sys.modules before, during, and after) - now calling the REAL "
      f"shutdown_lxml_worker(timeout=5.0)...", flush=True)
stopped = _mh.shutdown_lxml_worker(timeout=5.0)
print(f"P76: shutdown_lxml_worker(timeout=5.0) returned {stopped!r}", flush=True)

if not stopped:
    print("P76: worker did not report a clean stop", flush=True)
    raise SystemExit(1)

print(f"P76 OK - all {ROUNDS} rounds of REAL schema generation and "
      f"validation completed (2 real worker dispatches per round, all "
      f"passing, all against the real bundled XSD at {schema_source}) and "
      f"the REAL persistent worker stopped cleanly via the REAL "
      f"shutdown_lxml_worker() - GDAL was never imported anywhere in this "
      f"process", flush=True)
'''


# ---------------------------------------------------------------------------
# P77: identical to v0.30.43's P74 (real pipeline, 10 rounds, zero-failure
# instrumented), except it never calls shutdown_lxml_worker() at all -
# directly re-testing P61's shape under the CURRENT candidate.
# ---------------------------------------------------------------------------
P77_SCRIPT = r'''
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core import metadata_handler as _mh

ROUNDS = 10

_stats = {"calls": 0, "passed": 0, "failed": 0, "failures": []}
_REAL_IMPL = _mh._validate_schema_impl

def _counting_validate_schema_impl(handler, xml_bytes):
    _stats["calls"] += 1
    try:
        result = _REAL_IMPL(handler, xml_bytes)
        _stats["passed"] += 1
        return result
    except Exception as e:
        _stats["failed"] += 1
        _stats["failures"].append(str(e)[:300])
        raise

_mh._validate_schema_impl = _counting_validate_schema_impl


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


def run_conversion_real(tag, tmp_root):
    """The REAL, completely unmonkeypatched convert() - real GDAL, real
    metadata generation, real validate_schema() dispatch, exactly as
    validate_patch_v0.30.38.py's P61 and diagnose_crash_v0.30.43.py's P74
    already ran it."""
    local_shp = make_shapefile(tag, tmp_root)
    out_path = str(Path(tmp_root) / f"out_{tag}.gpkg")
    converter = GeoPackageConverter(profile="military")
    result = converter.convert(
        source_geodatabase=local_shp,
        output_geopackage=out_path,
        title=f"P77 No-Explicit-Shutdown {tag}",
        abstract="Re-tests P61's exact shape (real pipeline, 10 rounds, "
                 "never calling shutdown_lxml_worker - the process just "
                 "exits normally) under the CURRENT candidate and today's "
                 "pass/fail instrumentation, for a clean comparison "
                 "against P74.",
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

for round_i in range(ROUNDS):
    print(f"P77: round {round_i} - starting a brand-new thread, will wait "
          f"for it to fully finish...", flush=True)

    round_error = {}
    def round_worker():
        try:
            run_conversion_real(f"P77_r{round_i}", tmp_root)
        except Exception as e:
            round_error["e"] = str(e)

    t = threading.Thread(target=round_worker)
    t.start()
    t.join(timeout=30)
    if "e" in round_error:
        print(f"P77: round {round_i} error: {round_error['e']}", flush=True)
        errors[round_i] = round_error["e"]
        break
    print(f"P77: round {round_i} thread completed its FULL, real, "
          f"unmodified conversion. Validation calls so far: "
          f"{_stats['calls']} (passed {_stats['passed']}, "
          f"failed {_stats['failed']})", flush=True)

print(f"P77: all {ROUNDS} rounds done.", flush=True)
print(f"P77: FINAL VALIDATION TALLY - calls={_stats['calls']} "
      f"passed={_stats['passed']} failed={_stats['failed']}", flush=True)
if _stats["failures"]:
    print(f"P77: failure messages (up to 300 chars each):", flush=True)
    for i, msg in enumerate(_stats["failures"]):
        print(f"P77:   failure {i}: {msg}", flush=True)
else:
    print(f"P77: zero validation failures across all {_stats['calls']} "
          f"real calls.", flush=True)

was_alive = _mh._LXML_WORKER_THREAD is not None and _mh._LXML_WORKER_THREAD.is_alive()
print(f"P77: worker thread alive: {was_alive} - deliberately NOT calling "
      f"shutdown_lxml_worker() at all (unlike P74) - returning from this "
      f"script now and letting the process exit normally, exactly as P61 "
      f"(v0.30.38, on the earlier v0.30.24 candidate) did.", flush=True)

if errors:
    print(f"P77: errors: {errors}", flush=True)
    raise SystemExit(1)

print(f"P77 OK - all {ROUNDS} rounds completed, {_stats['calls']} real "
      f"validation calls observed ({_stats['failed']} failed), worker "
      f"thread left alive and un-joined, exiting normally now", flush=True)
'''


# ---------------------------------------------------------------------------
# P78: same as P77 (10 real rounds, no explicit shutdown call), except the
# script calls os._exit(0) instead of returning normally - bypassing
# CPython's own interpreter finalization, GC, and atexit handling entirely.
# Windows' own DLL_PROCESS_DETACH notification to every loaded DLL still
# fires regardless of exit path; this probe does NOT and CANNOT skip that.
# ---------------------------------------------------------------------------
P78_SCRIPT = r'''
import sys, os, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core import metadata_handler as _mh

ROUNDS = 10

_stats = {"calls": 0, "passed": 0, "failed": 0, "failures": []}
_REAL_IMPL = _mh._validate_schema_impl

def _counting_validate_schema_impl(handler, xml_bytes):
    _stats["calls"] += 1
    try:
        result = _REAL_IMPL(handler, xml_bytes)
        _stats["passed"] += 1
        return result
    except Exception as e:
        _stats["failed"] += 1
        _stats["failures"].append(str(e)[:300])
        raise

_mh._validate_schema_impl = _counting_validate_schema_impl


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


def run_conversion_real(tag, tmp_root):
    local_shp = make_shapefile(tag, tmp_root)
    out_path = str(Path(tmp_root) / f"out_{tag}.gpkg")
    converter = GeoPackageConverter(profile="military")
    result = converter.convert(
        source_geodatabase=local_shp,
        output_geopackage=out_path,
        title=f"P78 os._exit Bypass {tag}",
        abstract="Same as P77 (no explicit shutdown_lxml_worker call) but "
                 "bypasses ordinary CPython interpreter finalization "
                 "entirely via os._exit(0), to test whether the crash is "
                 "caused by code that runs during normal Python-level "
                 "shutdown/GC/atexit, or survives even with that layer "
                 "skipped.",
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

for round_i in range(ROUNDS):
    print(f"P78: round {round_i} - starting a brand-new thread, will wait "
          f"for it to fully finish...", flush=True)

    round_error = {}
    def round_worker():
        try:
            run_conversion_real(f"P78_r{round_i}", tmp_root)
        except Exception as e:
            round_error["e"] = str(e)

    t = threading.Thread(target=round_worker)
    t.start()
    t.join(timeout=30)
    if "e" in round_error:
        print(f"P78: round {round_i} error: {round_error['e']}", flush=True)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
    print(f"P78: round {round_i} thread completed its FULL, real, "
          f"unmodified conversion. Validation calls so far: "
          f"{_stats['calls']} (passed {_stats['passed']}, "
          f"failed {_stats['failed']})", flush=True)

print(f"P78: all {ROUNDS} rounds done.", flush=True)
print(f"P78: FINAL VALIDATION TALLY - calls={_stats['calls']} "
      f"passed={_stats['passed']} failed={_stats['failed']}", flush=True)

was_alive = _mh._LXML_WORKER_THREAD is not None and _mh._LXML_WORKER_THREAD.is_alive()
print(f"P78: worker thread alive: {was_alive} - NOT calling "
      f"shutdown_lxml_worker(), and NOT returning normally either. Calling "
      f"os._exit(0) right now - this skips garbage collection, atexit "
      f"hooks, and CPython's own interpreter finalization sequence "
      f"entirely (it does NOT skip Windows' own DLL_PROCESS_DETACH "
      f"notification to every loaded DLL, which fires on any process exit "
      f"path). If a crash happens anyway, it happens at or below that "
      f"level, not in anything CPython's finalization does.", flush=True)
sys.stdout.flush()
sys.stderr.flush()

os._exit(0)
'''


PROBES: "list[tuple[str, str, str, int, str]]" = [
    (
        "P75_never_used_worker_immediate_shutdown",
        "Starts the REAL persistent worker, dispatches ZERO jobs (no "
        "validation, no GDAL), then immediately calls the REAL "
        "shutdown_lxml_worker(). Cheapest test of whether the crash needs "
        "ANY real work at all.",
        P75_SCRIPT,
        30,
        "patched",
    ),
    (
        "P76_lxml_only_no_gdal_ever",
        "10 rounds of REAL generate_package_metadata()+validate_schema() "
        "against the REAL bundled XSD via the REAL persistent worker, then "
        "shutdown - but GDAL is never imported anywhere in this process "
        "(candidate module loaded through an isolated core_min/ package, "
        "not the real core package). Tests whether GDAL involvement "
        "anywhere is a necessary ingredient for the shutdown crash.",
        P76_SCRIPT,
        90,
        "gdal_free",
    ),
    (
        "P77_ten_rounds_no_explicit_shutdown",
        "Identical to v0.30.43's P74 (real pipeline, 10 rounds, zero-"
        "failure instrumented) except it never calls "
        "shutdown_lxml_worker() at all - re-tests P61's exact shape under "
        "the CURRENT candidate.",
        P77_SCRIPT,
        180,
        "patched",
    ),
    (
        "P78_ten_rounds_os_exit_bypass",
        "Same as P77 but calls os._exit(0) instead of returning normally, "
        "bypassing CPython's own interpreter finalization/GC/atexit "
        "handling (not Windows' DLL_PROCESS_DETACH, which still fires "
        "regardless).",
        P78_SCRIPT,
        180,
        "patched",
    ),
]


def run_probe(name: str, desc: str, code: str, root_for_probe: Path, timeout: int) -> str:
    """Runs one probe against *root_for_probe* and returns its tag: "OK",
    "FAIL", or "CRASH"."""
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
    path = LOG_DIR / f"diagnose_v0.30.44_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - LOCALIZING THE SHUTDOWN CRASH (v0.30.44)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.43's P73 confirmed the cross-thread-exception mechanism is")
    log("  real (and fixable); its P74 showed that mechanism cannot explain")
    log("  P62 - zero validation failures across 30 real calls, yet it still")
    log("  crashed inside shutdown_lxml_worker(). This script runs four")
    log("  probes narrowing P62 along three axes: how much real work the")
    log("  worker needs (P75), whether GDAL needs to be involved anywhere in")
    log("  the process at all (P76), and whether the crash is specific to")
    log("  the explicit shutdown call or survives skipping it entirely (P77)")
    log("  and even bypassing ordinary CPython finalization (P78). See this")
    log("  script's own module docstring for the full reasoning and the")
    log("  complete reading-the-results table.")

    if not CANDIDATE_V39_METADATA_HANDLER.exists():
        header("SETUP ERROR")
        log(f"  {CANDIDATE_V39_METADATA_HANDLER} does not exist.")
        log(f"  P75/P76/P77/P78 all need it. Place candidate_patch_v0.30.39/")
        log(f"  in dev_tools/, next to this script, and re-run.")
        _LOG_FH.close()
        print()
        print(f"Log written to: {path}")
        return 1

    roots = {}
    try:
        roots["patched"] = stage_patched_copy()
        roots["gdal_free"] = stage_gdal_free_copy()
    except RuntimeError as e:
        header("SETUP ERROR")
        log(f"  {e}")
        _LOG_FH.close()
        print()
        print(f"Log written to: {path}")
        return 1

    tags = {}
    for name, desc, code, timeout, root_key in PROBES:
        tags[name] = run_probe(name, desc, code, roots[root_key], timeout)

    header("SUMMARY")
    for name, tag in tags.items():
        label = {"OK": "OK   ", "FAIL": "FAIL ", "CRASH": "CRASH"}[tag]
        log(f"  {label}  {name}")

    log("")
    log("  (for reference, from diagnose_v0.30.43_20260817_124536.log:)")
    log("  OK     P73_exception_stringified_in_worker")
    log("  CRASH  P74_instrumented_real_pipeline  (calls=30 passed=30")
    log("         failed=0, crashed INSIDE shutdown_lxml_worker() - the log")
    log("         never reaches \"shutdown_lxml_worker(...) returned\")")
    log("  (for reference, from validate_patch_shutdown_v0.30.39_20260817_112111.log:)")
    log("  CRASH  P62_v39_candidate_explicit_shutdown  (10/10 rounds clean,")
    log("         crashed INSIDE shutdown_lxml_worker(), on the EARLIER")
    log("         v0.30.24-based candidate build)")
    log("  (for reference, from validate_patch_v0.30.38_20260817_105747.log:)")
    log("  CRASH  P61  real, unmonkeypatched pipeline, 10/10 rounds clean,")
    log("         crashed during ORDINARY interpreter finalization - no")
    log("         shutdown_lxml_worker() call existed yet at that version")

    log("")
    log("READING THE RESULTS:")
    log("  P75 CRASH -> the crash needs NOTHING beyond creating and")
    log("               immediately stopping this specific worker thread -")
    log("               no real lxml work, no GDAL, no payload at all.")
    log("  P75 OK    -> some real work is a necessary ingredient; P76/P77/")
    log("               P78 narrow which kind.")
    log("")
    log("  P76 CRASH -> GDAL is NOT a necessary ingredient for this third")
    log("               mechanism - real lxml activity on a thread that is")
    log("               later stopped is unsafe here on its own.")
    log("  P76 OK    -> GDAL's presence/activity somewhere in the process")
    log("               is still necessary, even for this third mechanism.")
    log("")
    log("  P77 CRASH (at ordinary interpreter exit, matching P61) -> same")
    log("               underlying hazard as P61/P74, just observed at a")
    log("               different trigger point.")
    log("  P77 OK    -> skipping the explicit stop-and-join avoids the")
    log("               crash entirely - argues for NOT calling")
    log("               shutdown_lxml_worker() at all, and means P61 may")
    log("               not be reliably reproducible.")
    log("")
    log("  P78 OK (no crash even bypassing CPython's own finalization) ->")
    log("               narrows the cause to CPython's own finalization/")
    log("               GC/atexit layer specifically - opens \"call")
    log("               os._exit() once real work is done\" as a real,")
    log("               much cheaper mitigation angle.")
    log("  P78 CRASH (even with os._exit(0)) -> the hazard survives even")
    log("               without CPython's finalization running - points at")
    log("               Windows' own DLL_PROCESS_DETACH-time native")
    log("               cleanup, which no amount of Python-level care can")
    log("               avoid.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
