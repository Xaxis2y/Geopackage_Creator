# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.43 - two follow-ups requested
together after dev_tools/diagnose_crash_v0.30.42.py's P70/P71/P72 results:
(1) a direct test of the new cross-thread-exception hypothesis those results
pointed at, and (2) an investigation into whether that same hypothesis can
also explain validate_patch_shutdown_v0.30.39.py's still-unexplained P62
shutdown crash.

WHAT v0.30.42 SHOWED
----------------------
dev_tools/logs/diagnose_v0.30.42_20260817_122819.log:

    P70  lock held, TRIVIAL FAILING document       -> CRASH (round 1)
    P71  no lock,    REAL PASSING document          -> OK (5/5 rounds)
    P72  lock held, REAL PASSING document           -> OK (5/5 rounds)

The lock made no difference either way - what flips the outcome is entirely
whether the dispatched document fails or passes validation.

THE MECHANISM: A LIVE EXCEPTION CROSSING A THREAD BOUNDARY
-----------------------------------------------------------------
Re-reading core/metadata_handler.py with that in mind: `_lxml_worker_loop()`
(the REAL persistent worker's body) does

    try:
        result = _validate_schema_impl(handler, xml_bytes)
        response_q.put((True, result))
    except Exception as e:
        response_q.put((False, e))                      # <- the LIVE object

and `validate_schema()`'s dispatch code (metadata_handler.py:1050) does

    if ok:
        return payload
    raise payload                                        # <- RE-raised here

On a FAILING validation, the exact exception object raised inside
`_validate_schema_impl()` - with its ORIGINAL traceback, which pins
references to that call's local variables (`schema`, a compiled
`etree.XMLSchema`; `doc`, a parsed `etree._Element` - both real,
libxml2-backed objects) via the frames the traceback holds onto - crosses
the queue and is re-raised on the DISPATCHING thread. When the caller's
local reference to that exception goes out of scope, the traceback (and
therefore `schema` and `doc`) can have their LAST reference dropped, and be
deallocated, on a thread other than the one that created them and did all
their prior libxml2 work - precisely the "compiled schema surviving to the
wrong place" hazard v0.30.23 already eliminated from the compiled-schema
cache, reappearing through a door nobody had looked at: an exception
crossing a queue. On a PASSING validation, nothing is ever raised, so
`schema`/`doc` go out of scope normally, locally, on the worker thread -
matching P71/P72 exactly. Every hand-rolled worker this whole series has
ever used (P55, P57, P59, P64-P66, and P70's own baseline) has, by
coincidence, always caught and stringified exceptions locally, on the same
thread, before ever queuing anything - consistent with why they have never
crashed either.

This does NOT, on its own, explain validate_patch_shutdown_v0.30.39.py's
P62: that crash happened inside an explicit `shutdown_lxml_worker()` call,
after 10 rounds of the REAL, unmonkeypatched pipeline, which (so far as its
own log shows) never reported a validation failure. If nothing ever failed,
nothing ever crossed the queue as a live exception, and this mechanism
would have nothing to do with P62. Whether that is actually true - whether
the real pipeline's real, generated metadata ever fails validation - has
never actually been measured; P62's own script did not report it either way
per round, only whether the round as a whole succeeded.

WHAT THIS SCRIPT DOES
-------------------------
Two probes, addressing each concern directly rather than continuing to
reason about the existing logs alone:

  P73  Direct mechanism test. Identical to P70 (real worker, round-thread
       dispatch, trivial "<x/>" document - CRASHED 5/5 times across P67,
       P67R, P68, P69, P70), except `_lxml_worker_loop()` is replaced with a
       version that converts a failing validation's exception to a plain
       STRING inside the worker thread, before it ever crosses the queue -
       `_validate_schema_impl()` itself, the REAL lxml-touching logic, is
       completely untouched. The dispatching side reconstructs a FRESH
       exception from that string, with a traceback rooted entirely on its
       own thread, instead of re-raising the original. If this alone avoids
       the crash, it is direct, positive confirmation of the mechanism
       above.

  P74  Instrumented real pipeline - addresses the P62 gap directly rather
       than continuing to reason about it. Runs the REAL, completely
       unmonkeypatched pipeline for 10 rounds (matching P61/P62 exactly:
       each round its own brand-new thread, real convert() end to end), with
       `_validate_schema_impl()` wrapped in a transparent counting layer
       (calls the real implementation unchanged, only observes) that counts
       every real validation attempt and every failure. Prints cumulative
       pass/fail counts after every round, so a mid-run crash still leaves
       the counts up to that point on disk, then prints the final tally
       BEFORE calling the REAL shutdown_lxml_worker() one more time - so
       this both re-tests P62's crash and, for the first time, shows
       whether the real pipeline's real metadata ever actually fails
       validation along the way.

READING THE RESULTS
---------------------
    P73 OK    -> direct confirmation: converting the exception to a string
                 before it crosses the worker-to-caller queue boundary
                 avoids the crash. The mechanism in this script's own module
                 docstring is very likely correct for the P67-family crashes.
    P73 CRASH -> the cross-thread exception object is not the (or not the
                 only) mechanism on the failing-validation path; something
                 else about that path is dangerous independent of whether
                 the exception itself crosses threads.

    P74: 0 validation failures across all 20 real calls (10 rounds x 2 -
         the internal generate_package_metadata() self-check and the
         explicit converter.py:619 check), AND it still crashes at shutdown
                 -> confirms P62 is a SEPARATE mechanism from P73's - the
                    cross-thread-exception hypothesis requires a failure to
                    occur, and none did, so it cannot be what crashed P62.
    P74: 0 validation failures, and it does NOT crash this time
                 -> P62 may not be reliably reproducible under identical
                    conditions - worth a second rerun before concluding
                    anything about reliability.
    P74: 1+ validation failures anywhere in the 20 calls
                 -> the real pipeline DOES sometimes hit the failing path -
                    this script's own hypothesis could explain part or all
                    of P62 after all. Check which round and which of the two
                    call sites failed, and whether it lines up with when the
                    crash happened.

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series. This is still bisection and
observation, not a fix.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Place this script in dev_tools/, alongside candidate_patch_v0.30.39/
(needed by both probes here - already there from an earlier delivery):

    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.43.py

Writes dev_tools\\logs\\diagnose_v0.30.43_<timestamp>.log incrementally, so a
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
    Both probes in this script need this. Called once; both probes run
    against the same staged copy."""
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
# P73: identical to v0.30.42's P70 shape, except _lxml_worker_loop() is
# replaced so a failing validation's exception is stringified INSIDE the
# worker thread before it crosses the queue. _validate_schema_impl() - the
# REAL lxml logic - is completely untouched.
# ---------------------------------------------------------------------------
P73_SCRIPT = r'''
import sys, tempfile, threading, queue
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler
from core import metadata_handler as _mh

ROUNDS = 5

MetadataHandler.validate_schema = lambda self, metadata_xml_string: True

# THE ONE CHANGE relative to P70: patch the REAL worker LOOP so a failing
# validation's exception is converted to a plain string INSIDE the worker
# thread, before crossing the queue - instead of the real _lxml_worker_
# loop()'s behavior of queuing the LIVE exception object (with its
# traceback, which pins this frame's local variables - schema, doc, both
# inside _validate_schema_impl(), left completely unmodified below) via
# response_q.put((False, e)).
def _patched_lxml_worker_loop():
    while True:
        job = _mh._LXML_JOBS.get()
        if job is _mh._LXML_WORKER_STOP:
            return
        handler, xml_bytes, response_q = job
        try:
            result = _mh._validate_schema_impl(handler, xml_bytes)  # REAL, unmodified
            response_q.put((True, result))
        except Exception as e:
            response_q.put((False, str(e)))  # <- stringified HERE, worker thread

_mh._lxml_worker_loop = _patched_lxml_worker_loop


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
    local_shp = make_shapefile(tag, tmp_root)
    out_path = str(Path(tmp_root) / f"out_{tag}.gpkg")
    converter = GeoPackageConverter(profile="military")
    result = converter.convert(
        source_geodatabase=local_shp,
        output_geopackage=out_path,
        title=f"P73 Exception-Crossing Isolation {tag}",
        abstract="Isolates whether the LIVE exception object crossing the worker-to-caller queue is what makes the failing-validation path dangerous",
        poc="Test User",
        org="Test Org",
        nation="USA",
        security="UNCLASSIFIED",
        generate_reports=True,
    )
    if not result.get("success"):
        raise RuntimeError(f"conversion {tag} reported failure: {result.get('error')}")
    return result


def validate_via_patched_worker(tag):
    """Mirrors the REAL validate_schema()'s own dispatch code exactly,
    except the final step: instead of `raise payload` (the real code's
    line 1050, re-raising the ORIGINAL exception crossing from the worker
    thread), this reconstructs a FRESH ValueError from the string message
    received - a brand new exception with a brand new traceback rooted
    entirely on THIS thread."""
    handler = MetadataHandler()
    xml_bytes = "<x/>".encode("utf-8")
    _mh._ensure_lxml_worker_started()
    response_q = queue.Queue(maxsize=1)
    _mh._LXML_JOBS.put((handler, xml_bytes, response_q))
    ok, payload = response_q.get(timeout=20)
    if ok:
        return payload
    if "ISO 19115 schema validation failed" not in payload:
        raise ValueError(payload)
    # tolerated, same as every other probe in this series


tmp_root = tempfile.mkdtemp()
errors = {}

for round_i in range(ROUNDS):
    tag = f"P73_r{round_i}"
    print(f"P73: round {round_i} - starting a NEW thread that will do GDAL AND "
          f"dispatch its own validation to the PATCHED-LOOP real worker (trivial "
          f"failing document, no lock)...", flush=True)

    round_error = {}
    def round_worker():
        try:
            run_conversion_gdal_only(tag, tmp_root)
            validate_via_patched_worker(tag)
        except Exception as e:
            round_error["e"] = str(e)

    t = threading.Thread(target=round_worker)
    t.start()
    t.join(timeout=30)
    if "e" in round_error:
        print(f"P73: round {round_i} error: {round_error['e']}", flush=True)
        errors[round_i] = round_error["e"]
        break
    print(f"P73: round {round_i} completed - GDAL write and validation (trivial "
          f"FAILING document, but exception stringified inside the worker thread "
          f"before crossing the queue) both done.", flush=True)

was_alive = _mh._LXML_WORKER_THREAD is not None and _mh._LXML_WORKER_THREAD.is_alive()
print(f"P73: all {ROUNDS} rounds done, worker thread alive: {was_alive} - "
      f"now calling the REAL shutdown_lxml_worker(timeout=5.0)...", flush=True)
stopped = _mh.shutdown_lxml_worker(timeout=5.0)
print(f"P73: shutdown_lxml_worker(timeout=5.0) returned {stopped!r}", flush=True)

if errors:
    print(f"P73: errors: {errors}", flush=True)
    raise SystemExit(1)

print(f"P73 OK - all {ROUNDS} rounds completed (trivial FAILING document each time, "
      f"exception always stringified on the worker thread before crossing the "
      f"queue) and the REAL persistent worker stopped cleanly via the REAL "
      f"shutdown_lxml_worker()", flush=True)
'''


# ---------------------------------------------------------------------------
# P74: the REAL, completely unmonkeypatched pipeline, 10 rounds, exactly
# matching P61/P62's own shape - but with _validate_schema_impl() wrapped in
# a transparent counting layer that observes every real validation call and
# every failure without changing behavior at all.
# ---------------------------------------------------------------------------
P74_SCRIPT = r'''
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core import metadata_handler as _mh

ROUNDS = 10

# Transparent counting wrapper around the REAL _validate_schema_impl() - the
# ONLY place in the process that ever actually touches lxml for validation
# (see that function's own docstring). Calls the real implementation
# unchanged and returns/raises exactly what it returns/raises; only counts.
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
    validate_patch_v0.30.38.py's P61 and validate_patch_shutdown_v0.30.39.py's
    P62 already ran it."""
    local_shp = make_shapefile(tag, tmp_root)
    out_path = str(Path(tmp_root) / f"out_{tag}.gpkg")
    converter = GeoPackageConverter(profile="military")
    result = converter.convert(
        source_geodatabase=local_shp,
        output_geopackage=out_path,
        title=f"P74 Instrumented Real Pipeline {tag}",
        abstract="Measures whether the real pipeline's real generated metadata ever actually fails validation, to check whether P73's mechanism could also explain P62's shutdown crash",
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
    print(f"P74: round {round_i} - starting a brand-new thread, will wait for it "
          f"to fully finish...", flush=True)

    round_error = {}
    def round_worker():
        try:
            run_conversion_real(f"P74_r{round_i}", tmp_root)
        except Exception as e:
            round_error["e"] = str(e)

    t = threading.Thread(target=round_worker)
    t.start()
    t.join(timeout=30)
    if "e" in round_error:
        print(f"P74: round {round_i} error: {round_error['e']}", flush=True)
        errors[round_i] = round_error["e"]
        break
    print(f"P74: round {round_i} thread completed its FULL, real, unmodified "
          f"conversion. Validation calls so far: {_stats['calls']} "
          f"(passed {_stats['passed']}, failed {_stats['failed']})", flush=True)

print(f"P74: all {ROUNDS} rounds done.", flush=True)
print(f"P74: FINAL VALIDATION TALLY - calls={_stats['calls']} "
      f"passed={_stats['passed']} failed={_stats['failed']}", flush=True)
if _stats["failures"]:
    print(f"P74: failure messages (up to 300 chars each):", flush=True)
    for i, msg in enumerate(_stats["failures"]):
        print(f"P74:   failure {i}: {msg}", flush=True)
else:
    print(f"P74: zero validation failures across all {_stats['calls']} real calls.",
          flush=True)

was_alive = _mh._LXML_WORKER_THREAD is not None and _mh._LXML_WORKER_THREAD.is_alive()
print(f"P74: worker thread alive before shutdown call: {was_alive} - now calling "
      f"the REAL shutdown_lxml_worker(timeout=5.0)...", flush=True)
stopped = _mh.shutdown_lxml_worker(timeout=5.0)
print(f"P74: shutdown_lxml_worker(timeout=5.0) returned {stopped!r}", flush=True)

if errors:
    print(f"P74: errors: {errors}", flush=True)
    raise SystemExit(1)

print(f"P74 OK - all {ROUNDS} rounds completed, {_stats['calls']} real validation "
      f"calls observed ({_stats['failed']} failed), and the REAL persistent worker "
      f"stopped cleanly via the REAL shutdown_lxml_worker()", flush=True)
'''


PROBES: "list[tuple[str, str, str, int]]" = [
    (
        "P73_exception_stringified_in_worker",
        "Identical to v0.30.42's P70, except _lxml_worker_loop() converts a "
        "failing validation's exception to a plain string INSIDE the worker "
        "thread before it crosses the queue - _validate_schema_impl() "
        "itself is untouched. Direct test of the cross-thread-exception "
        "hypothesis.",
        P73_SCRIPT,
        120,
    ),
    (
        "P74_instrumented_real_pipeline",
        "The REAL, unmonkeypatched pipeline, 10 rounds, matching P61/P62 "
        "exactly, with _validate_schema_impl() wrapped in a transparent "
        "counting layer. Measures whether real, generated metadata ever "
        "actually fails validation, to check whether P73's mechanism could "
        "also explain P62's shutdown crash.",
        P74_SCRIPT,
        180,
    ),
]


def run_probe(name: str, desc: str, code: str, root_for_probe: Path, timeout: int) -> str:
    """Runs one probe against *root_for_probe* and returns its tag: "OK",
    "FAIL", or "CRASH". Both probes in this script pass the SAME staged
    copy (see stage_patched_copy(), called once in main())."""
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
    path = LOG_DIR / f"diagnose_v0.30.43_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - EXCEPTION MECHANISM + P62 GAP (v0.30.43)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.42 showed the lock never mattered - what flips P70 (CRASH) to")
    log("  P71/P72 (OK) is entirely whether the dispatched document fails or")
    log("  passes validation. Re-reading the real worker's code found the exact")
    log("  asymmetry: on a failing validation, _lxml_worker_loop() queues the")
    log("  LIVE exception object, and validate_schema() re-raises that SAME")
    log("  object - with its original traceback, pinning the worker thread's")
    log("  schema/doc locals - on the dispatching thread. P73 tests that")
    log("  mechanism directly. P74 investigates whether it can also explain the")
    log("  still-unexplained P62 shutdown crash, by measuring - for the first")
    log("  time - whether the real pipeline's real, generated metadata ever")
    log("  actually fails validation. See this script's own module docstring")
    log("  for the full reasoning.")

    if not CANDIDATE_V39_METADATA_HANDLER.exists():
        header("SETUP ERROR")
        log(f"  {CANDIDATE_V39_METADATA_HANDLER} does not exist.")
        log(f"  Both probes in this script need it. Place")
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
    log("  (for reference, from diagnose_v0.30.42_20260817_122819.log:)")
    log("  CRASH  P70_lock_held_trivial_doc")
    log("  OK     P71_real_doc_no_lock")
    log("  OK     P72_lock_and_real_doc")
    log("  (for reference, from validate_patch_shutdown_v0.30.39_20260817_112111.log:)")
    log("  CRASH  P62_v39_candidate_explicit_shutdown  (10/10 rounds clean, crashed")
    log("         INSIDE shutdown_lxml_worker() - per-round validation pass/fail was")
    log("         never measured, only whether the round as a whole succeeded)")

    log("")
    log("READING THE RESULTS:")
    log("  P73 OK     -> direct confirmation: stringifying the exception before it")
    log("                crosses the queue avoids the crash. Strong support for the")
    log("                mechanism this script's own module docstring describes.")
    log("  P73 CRASH  -> the cross-thread exception object is not the (or not the")
    log("                only) mechanism on the failing-validation path.")
    log("")
    log("  P74: 0 failures across all real calls, still crashes at shutdown")
    log("                -> confirms P62 is a SEPARATE mechanism - this hypothesis")
    log("                   requires a failure, and none occurred.")
    log("  P74: 0 failures, does NOT crash this time")
    log("                -> P62 may not be reliably reproducible - worth a rerun.")
    log("  P74: 1+ failures anywhere")
    log("                -> the real pipeline DOES sometimes hit the failing path -")
    log("                   check which round/call, and whether it lines up with")
    log("                   the crash timing.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
