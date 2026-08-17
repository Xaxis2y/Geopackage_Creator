# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.40 - follow-up to
dev_tools/validate_patch_shutdown_v0.30.39.py's P62 result.

WHAT P62 SHOWED
----------------
dev_tools/logs/validate_patch_shutdown_v0.30.39_20260817_112111.log, run on
the target machine on 2026-08-17:

    P62 (v0.30.39 candidate, explicit shutdown_lxml_worker() before a
         normal exit)   -> CRASH (exit code 3221225477)
    P63 (v0.30.38 candidate, unmodified, os._exit(0) instead of a normal
         exit, worker thread never asked to stop)        -> OK (exit code 0)

P62's own log shows all 10 rounds of the real, unmodified conversion
pattern completing cleanly ("P62 OK - all 10 sequential rounds completed...
zero crashes"), followed by "P62: worker thread alive before shutdown call:
True" - and then NOTHING else from that subprocess's stdout. The very next
line this script's own PROBE_SCRIPT would have printed -
"P62: shutdown_lxml_worker(timeout=5.0) returned ..." - never appears.
Every print in that probe uses flush=True, exactly like every other print
in this whole series that DID reliably show up before a crash cut a
subprocess off - so its absence is the same kind of evidence this project
has relied on throughout: the crash happened INSIDE the
`shutdown_lxml_worker(timeout=5.0)` call itself, not afterward, and not
during ordinary interpreter finalization the way P61's crash did.

WHY THIS DOES NOT FIT THE ORIGINAL FRAMING
---------------------------------------------
`candidate_patch_v0.30.39/core/metadata_handler.py`'s persistent worker
thread never performs a GDAL write itself, by design - that is the entire
point of the v0.30.24 mitigation this whole series has been validating. So
P62's crash happened on the termination of a thread that, by the documented
P51/P52/P53 necessary condition ("ONE thread must perform a real GDAL write
AND a real lxml touch itself, in that order, in that same thread"), should
never have been part of the dangerous pattern at all.

It is also not simply "any lxml-only thread that touches lxml and then
terminates is dangerous, given GDAL happened elsewhere in the process" -
`diagnose_crash_v0.30.34.py`'s P52 already tested almost exactly that shape
(a GDAL-only thread A, joined/terminated, THEN a separate, freshly-created
thread B that makes ONE real lxml touch and then itself returns, ending
that thread) and came back OK, not CRASH. Whatever is different about P62
is not captured by P52 alone.

The most likely candidate differences, each changed exactly once relative
to `diagnose_crash_v0.30.35.py`'s P55 (five rounds of GDAL-only thread ->
dispatch to one persistent, hand-rolled lxml worker thread, reused
throughout, cleanly stopped via a sentinel at the end - which came back OK,
including that final clean stop):

  1. REPETITION. P55 dispatched 5 real lxml touches to the persistent
     thread before stopping it. P62's real pipeline, across 10 rounds with
     both package-level and layer-level metadata generated each round,
     dispatched roughly 2-4x that many before its shutdown call.

  2. WHICH THREAD DISPATCHES. In P55, `_lxml_jobs.put(...)` /
     `_lxml_results.get(...)` are always called from the SAME thread - the
     script's own main thread, after each round's GDAL-only thread has
     already been joined. In P62's real pipeline, `_LXML_JOBS.put(...)` is
     called from INSIDE `validate_schema()`, which runs on each round's OWN
     freshly-created conversion thread - ten different transient threads
     each touch the queue, not one thread doing it repeatedly.

  3. REAL IMPLEMENTATION VS. HAND-ROLLED. P55's persistent worker
     (`_lxml_worker()` in that script) is a small, standalone approximation
     written directly in the diagnostic, predating this project's real
     `_ensure_lxml_worker_started()` / `_lxml_worker_loop()` /
     `shutdown_lxml_worker()` functions (first written as real code in
     `candidate_patch_v0.30.38`/`_v0.30.39`). P62 exercises that real code
     for the first time under this kind of test. Something about the real
     implementation - the `_LXML_LOCK` acquisition inside
     `_validate_schema_impl()`, the `MetadataHandler` instance being
     constructed on a DIFFERENT thread than the one that later reads its
     `.schema` property, or something else not yet identified - could
     differ from the hand-rolled version in a way that matters.

WHAT THIS SCRIPT ISOLATES
----------------------------
Four probes, each changing exactly ONE of the three candidates above
relative to a fresh rerun of P55's own pattern - cheap, monkey-patched
GDAL-only threads throughout, never the full expensive real pipeline P62
used, so this can be run and re-run quickly before committing to another
expensive real-pipeline confirmation.

  P64  Control. P55's exact pattern rerun fresh today: 5 rounds, hand-rolled
       persistent worker, sentinel-based stop, main-thread dispatch.
       Expected OK, matching P55 - confirms nothing about the environment
       has shifted since v0.30.35 ran, before trusting P65-P67. (The base
       "two real threads, no mitigation" control is NOT re-run here - P60
       and P62 both already confirmed the underlying crash reproduces on
       this machine today, in `validate_patch_v0.30.38_20260817_105747.log`
       and `validate_patch_shutdown_v0.30.39_20260817_112111.log`.)

  P65  Same as P64, except ROUNDS=10 instead of 5 - isolates repetition
       count alone. Everything else (hand-rolled worker, main-thread
       dispatch) unchanged.

  P66  Same as P64 (5 rounds), except each round's OWN GDAL thread also
       performs its own dispatch to the persistent worker (queue put and
       response get), instead of the main thread doing it after joining
       that thread. Isolates whether it matters that many different,
       transient threads each touch the queue, versus one thread doing it
       repeatedly. The persistent worker itself still never does GDAL.

  P67  Same as P64 (5 rounds, main-thread dispatch), except the lxml side
       uses the REAL `candidate_patch_v0.30.39/core/metadata_handler.py`
       module directly - its actual `validate_schema()` (which internally
       calls the real `_ensure_lxml_worker_started()` and dispatches
       through the real `_LXML_JOBS`) and its actual `shutdown_lxml_worker()`
       - instead of this script's hand-rolled equivalent. GDAL-only threads
       still use the same class-level `validate_schema` no-op monkeypatch
       P52/P55/P64-P66 all use, so this probe changes only the
       implementation the lxml side runs, not repetition or dispatch-thread.

READING THE RESULTS
---------------------
    P64 CRASH (or FAIL)  -> something about the environment itself has
                             shifted since P55 ran clean - stop and
                             reconcile this before drawing any conclusion
                             from P65-P67.
    P64 OK, and all of P65/P66/P67 OK
                          -> none of these three candidate differences,
                             changed alone, reproduces P62's crash cheaply.
                             The real trigger may need more than one of
                             these changed together (a follow-up combining
                             them), or may be something this script has not
                             considered yet.
    P65 CRASH (P64/P66/P67 OK)
                          -> repetition count is the key variable. Worth
                             finding the approximate threshold.
    P66 CRASH (P64/P65/P67 OK)
                          -> which thread dispatches to the persistent
                             worker matters - many transient dispatching
                             threads is the dangerous shape, not just the
                             worker's own accumulated lxml activity.
    P67 CRASH (P64/P65/P66 OK)
                          -> something specific to the REAL
                             `_ensure_lxml_worker_started()` /
                             `_lxml_worker_loop()` / `shutdown_lxml_worker()`
                             implementation is implicated - worth a closer,
                             line-by-line comparison against this script's
                             hand-rolled equivalent for what differs.
    More than one of P65/P66/P67 CRASH
                          -> more than one factor contributes; note exactly
                             which combination and treat this as the
                             starting point for a follow-up probe that
                             varies them together.

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series. This is still bisection, not a fix.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Place this script in dev_tools/, alongside candidate_patch_v0.30.39/
(needed by P67 only - already there from the previous delivery):

    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.40.py

Writes dev_tools\\logs\\diagnose_v0.30.40_<timestamp>.log incrementally, so a
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

    Needed by P67 only, which is the one probe in this script that imports
    the REAL candidate module rather than a hand-rolled equivalent - P64,
    P65, and P66 run directly against PROJECT_ROOT and never call this.
    Same pattern as validate_patch_shutdown_v0.30.39.py's stage_patched_
    copy(): core/metadata_handler.py on the REAL project is never touched
    by this function or anything else in this script.

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
    log(f"  P67 setup: staged a full project copy at {stage_root}")
    log(f"  P67 setup: overwrote {dest_metadata_handler} with "
        f"{CANDIDATE_V39_METADATA_HANDLER}")

    staged_version_line = None
    for line in dest_metadata_handler.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            staged_version_line = line.strip()
            break
    log(f"  P67 setup: staged core/metadata_handler.py reports: {staged_version_line}")
    if staged_version_line != CANDIDATE_V39_EXPECTED_VERSION:
        raise RuntimeError(
            f"P67 setup FAILED: staged core/metadata_handler.py does not "
            f"report {CANDIDATE_V39_EXPECTED_VERSION} - the candidate patch "
            f"was not applied correctly. Aborting P67, since its result "
            f"would be meaningless."
        )
    return stage_root


# ---------------------------------------------------------------------------
# Shared building blocks, textually identical across all four probes so any
# behavioral difference in the results traces back to the one thing each
# probe deliberately varies, not an incidental difference in the shapefile
# or conversion helpers themselves.
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
        title=f"Shutdown Bisection {tag}",
        abstract="Isolates which variable reproduces validate_patch_shutdown_v0.30.39.py's P62 crash",
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
# P64 (control): P55's exact pattern, rerun fresh - 5 rounds, hand-rolled
# persistent lxml worker thread, sentinel-based clean stop at the end,
# always dispatched from the main thread.
# ---------------------------------------------------------------------------
P64_SCRIPT = r'''
import queue
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler

ROUNDS = 5

_ORIG_VALIDATE_SCHEMA = MetadataHandler.validate_schema

def _noop_validate_schema(self, metadata_xml_string):
    return True

MetadataHandler.validate_schema = _noop_validate_schema

''' + _COMMON_HELPERS + r'''

_lxml_jobs = queue.Queue()
_lxml_results = queue.Queue()
_LXML_STOP = object()

def _lxml_worker():
    while True:
        item = _lxml_jobs.get()
        if item is _LXML_STOP:
            _lxml_results.put(("stopped", None))
            return
        tag = item
        try:
            handler = MetadataHandler()
            try:
                _ORIG_VALIDATE_SCHEMA(handler, "<x/>")
            except ValueError as e:
                if "ISO 19115 schema validation failed" not in str(e):
                    raise
            _lxml_results.put(("ok", tag))
        except Exception as e:
            _lxml_results.put(("error", f"{tag}: {e}"))

_lxml_thread = threading.Thread(target=_lxml_worker, daemon=True)
_lxml_thread.start()

def validate_via_persistent_thread(tag, timeout=20):
    _lxml_jobs.put(tag)
    try:
        status, payload = _lxml_results.get(timeout=timeout)
    except queue.Empty:
        raise RuntimeError(f"{tag}: persistent lxml worker did not respond within {timeout}s")
    if status == "error":
        raise RuntimeError(payload)
    return payload


tmp_root = tempfile.mkdtemp()
errors = {}

for round_i in range(ROUNDS):
    tag = f"P64_r{round_i}"
    print(f"P64: round {round_i} - starting a NEW GDAL-only worker thread...", flush=True)

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
        print(f"P64: round {round_i} GDAL thread error: {gdal_error['e']}", flush=True)
        errors[round_i] = f"gdal: {gdal_error['e']}"
        break
    print(f"P64: round {round_i} GDAL thread completed its FULL turn (patch=lxml neutered).",
          flush=True)

    print(f"P64: round {round_i} - dispatching validation to the ONE persistent lxml "
          f"worker thread from the MAIN thread...", flush=True)
    try:
        validate_via_persistent_thread(tag)
        print(f"P64: round {round_i} validation completed via the persistent lxml thread",
              flush=True)
    except Exception as e:
        print(f"P64: round {round_i} validation error: {e}", flush=True)
        errors[round_i] = f"lxml: {e}"
        break

print(f"P64: all {ROUNDS} rounds done, worker alive: {_lxml_thread.is_alive()} - "
      f"now stopping the persistent worker via its sentinel...", flush=True)
_lxml_jobs.put(_LXML_STOP)
try:
    _lxml_results.get(timeout=15)
    print("P64: persistent worker acknowledged the stop sentinel and returned", flush=True)
except queue.Empty:
    print("P64: persistent worker did NOT acknowledge the stop sentinel within 15s", flush=True)

if errors:
    print(f"P64: errors: {errors}", flush=True)
    raise SystemExit(1)

print(f"P64 OK - all {ROUNDS} rounds completed and the persistent worker stopped cleanly",
      flush=True)
'''


# ---------------------------------------------------------------------------
# P65: identical to P64 except ROUNDS=10 - isolates repetition count alone.
# ---------------------------------------------------------------------------
P65_SCRIPT = P64_SCRIPT.replace("ROUNDS = 5", "ROUNDS = 10").replace("P64", "P65")


# ---------------------------------------------------------------------------
# P66: identical to P64 (5 rounds) except each round's OWN GDAL thread also
# performs its own dispatch to the persistent worker, instead of the main
# thread doing it after joining that thread. Isolates whether many
# different, transient dispatching threads (rather than one thread doing it
# repeatedly) matters. The persistent worker still never does GDAL itself.
# ---------------------------------------------------------------------------
P66_SCRIPT = r'''
import queue
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler

ROUNDS = 5

_ORIG_VALIDATE_SCHEMA = MetadataHandler.validate_schema

def _noop_validate_schema(self, metadata_xml_string):
    return True

MetadataHandler.validate_schema = _noop_validate_schema

''' + _COMMON_HELPERS + r'''

_lxml_jobs = queue.Queue()
_LXML_STOP = object()

def _lxml_worker():
    while True:
        item = _lxml_jobs.get()
        if item is _LXML_STOP:
            return
        tag, response_q = item
        try:
            handler = MetadataHandler()
            try:
                _ORIG_VALIDATE_SCHEMA(handler, "<x/>")
            except ValueError as e:
                if "ISO 19115 schema validation failed" not in str(e):
                    raise
            response_q.put(("ok", tag))
        except Exception as e:
            response_q.put(("error", f"{tag}: {e}"))

_lxml_thread = threading.Thread(target=_lxml_worker, daemon=True)
_lxml_thread.start()

def validate_via_persistent_thread(tag, timeout=20):
    """Called from the SAME thread that just did the GDAL write for this
    round - a genuinely different, freshly-created OS thread each round -
    not from the main thread. The actual lxml work still only ever happens
    on the one persistent worker thread above; this thread only puts a job
    on the queue and waits for its own response."""
    response_q = queue.Queue(maxsize=1)
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

for round_i in range(ROUNDS):
    tag = f"P66_r{round_i}"
    print(f"P66: round {round_i} - starting a NEW thread that will do GDAL AND "
          f"dispatch its own validation...", flush=True)

    round_error = {}
    def round_worker():
        try:
            run_conversion_gdal_only(tag, tmp_root)
            validate_via_persistent_thread(tag)
        except Exception as e:
            round_error["e"] = str(e)

    t = threading.Thread(target=round_worker)
    t.start()
    t.join(timeout=30)
    if "e" in round_error:
        print(f"P66: round {round_i} error: {round_error['e']}", flush=True)
        errors[round_i] = round_error["e"]
        break
    print(f"P66: round {round_i} completed - GDAL write and dispatch/response both done "
          f"on the same, single, freshly-created thread for this round.", flush=True)

print(f"P66: all {ROUNDS} rounds done, worker alive: {_lxml_thread.is_alive()} - "
      f"now stopping the persistent worker via its sentinel...", flush=True)
_lxml_jobs.put(_LXML_STOP)
_lxml_thread.join(timeout=15)
print(f"P66: persistent worker alive after join attempt: {_lxml_thread.is_alive()}", flush=True)

if errors:
    print(f"P66: errors: {errors}", flush=True)
    raise SystemExit(1)

print(f"P66 OK - all {ROUNDS} rounds completed and the persistent worker stopped cleanly",
      flush=True)
'''


# ---------------------------------------------------------------------------
# P67: identical to P64 (5 rounds, main-thread dispatch) except the lxml
# side is the REAL candidate_patch_v0.30.39 module - its actual
# validate_schema() (which internally starts and dispatches to the real
# persistent worker) and its actual shutdown_lxml_worker() - instead of a
# hand-rolled equivalent. GDAL-only threads still use the same class-level
# no-op monkeypatch as every other probe in this file.
# ---------------------------------------------------------------------------
P67_SCRIPT = r'''
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
    approximation. Called from the main thread, same as P64."""
    handler = MetadataHandler()
    try:
        _ORIG_VALIDATE_SCHEMA(handler, "<x/>")
    except ValueError as e:
        if "ISO 19115 schema validation failed" not in str(e):
            raise


tmp_root = tempfile.mkdtemp()
errors = {}

for round_i in range(ROUNDS):
    tag = f"P67_r{round_i}"
    print(f"P67: round {round_i} - starting a NEW GDAL-only worker thread...", flush=True)

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
        print(f"P67: round {round_i} GDAL thread error: {gdal_error['e']}", flush=True)
        errors[round_i] = f"gdal: {gdal_error['e']}"
        break
    print(f"P67: round {round_i} GDAL thread completed its FULL turn (patch=lxml neutered).",
          flush=True)

    print(f"P67: round {round_i} - dispatching validation to the REAL persistent lxml "
          f"worker (candidate_patch_v0.30.39) from the MAIN thread...", flush=True)
    try:
        validate_via_real_worker(tag)
        print(f"P67: round {round_i} validation completed via the REAL persistent lxml worker",
              flush=True)
    except Exception as e:
        print(f"P67: round {round_i} validation error: {e}", flush=True)
        errors[round_i] = f"lxml: {e}"
        break

was_alive = _mh._LXML_WORKER_THREAD is not None and _mh._LXML_WORKER_THREAD.is_alive()
print(f"P67: all {ROUNDS} rounds done, REAL worker thread alive: {was_alive} - "
      f"now calling the REAL shutdown_lxml_worker(timeout=5.0)...", flush=True)
stopped = _mh.shutdown_lxml_worker(timeout=5.0)
print(f"P67: shutdown_lxml_worker(timeout=5.0) returned {stopped!r}", flush=True)

if errors:
    print(f"P67: errors: {errors}", flush=True)
    raise SystemExit(1)

print(f"P67 OK - all {ROUNDS} rounds completed and the REAL persistent worker "
      f"stopped cleanly via the REAL shutdown_lxml_worker()", flush=True)
'''


# P64/P65/P66 run directly against PROJECT_ROOT - none of them import
# anything from candidate_patch_v0.30.39, so there is nothing to stage.
# P67 is handled separately in main() because it needs a staged temporary
# copy of the project with the candidate substituted in (see
# stage_patched_copy()) - it cannot run against PROJECT_ROOT directly, since
# the real, shipping core/metadata_handler.py does not have
# shutdown_lxml_worker() at all.
PROBES: "list[tuple[str, str, str, int]]" = [
    (
        "P64_control_p55_rerun",
        "Control: P55's exact pattern (diagnose_crash_v0.30.35.py) rerun "
        "fresh today - 5 rounds, hand-rolled persistent worker, main-thread "
        "dispatch, sentinel-based clean stop. Expected OK, matching P55 - "
        "confirms the environment before trusting P65-P67.",
        P64_SCRIPT,
        120,
    ),
    (
        "P65_repetition_ten_rounds",
        "Same as P64, except ROUNDS=10 instead of 5 - isolates repetition "
        "count alone against the persistent worker before it is stopped.",
        P65_SCRIPT,
        180,
    ),
    (
        "P66_dispatch_from_round_thread",
        "Same as P64 (5 rounds), except each round's own GDAL thread also "
        "dispatches its own validation to the persistent worker, instead of "
        "the main thread doing it afterward. The persistent worker still "
        "never does GDAL itself - only isolates whether many different, "
        "transient dispatching threads matters.",
        P66_SCRIPT,
        120,
    ),
]

P67_NAME = "P67_real_module_implementation"
P67_DESC = (
    "Same as P64 (5 rounds, main-thread dispatch), except the lxml side "
    "is the REAL candidate_patch_v0.30.39/core/metadata_handler.py - its "
    "actual validate_schema()/_ensure_lxml_worker_started() and its actual "
    "shutdown_lxml_worker() - instead of a hand-rolled equivalent. Runs "
    "against a staged temporary copy of the project with ONLY "
    "core/metadata_handler.py replaced by the candidate, same staging "
    "discipline as validate_patch_shutdown_v0.30.39.py's P62/P63."
)


def run_probe(name: str, desc: str, code: str, root_for_probe: Path, timeout: int) -> str:
    """Runs one probe against *root_for_probe* and returns its tag: "OK",
    "FAIL", or "CRASH". P64/P65/P66 pass PROJECT_ROOT; P67 passes a staged
    temporary copy (see stage_patched_copy())."""
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
    path = LOG_DIR / f"diagnose_v0.30.40_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - SHUTDOWN-CRASH BISECTION (v0.30.40)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  Follows up on validate_patch_shutdown_v0.30.39.py's P62: the real")
    log("  persistent lxml worker thread (never touches GDAL itself) crashed")
    log("  DURING its own explicit shutdown_lxml_worker() call, after 10/10")
    log("  real conversion rounds had already completed cleanly. That does not")
    log("  fit the original 'GDAL+lxml in the same thread' necessary condition,")
    log("  and diagnose_crash_v0.30.34.py's P52 already showed a simpler")
    log("  version of 'lxml-only thread touches once then terminates, after a")
    log("  separate GDAL-only thread' is safe. This script cheaply isolates")
    log("  three candidate differences from diagnose_crash_v0.30.35.py's P55")
    log("  (which came back clean, including its own persistent worker's clean")
    log("  stop) - repetition count, which thread dispatches, and real-vs-hand-")
    log("  rolled implementation - one at a time. See this script's own module")
    log("  docstring for the full reasoning.")

    if not CANDIDATE_V39_METADATA_HANDLER.exists():
        header("SETUP WARNING")
        log(f"  {CANDIDATE_V39_METADATA_HANDLER} does not exist.")
        log(f"  P67 needs it and will be skipped - P64/P65/P66 do not need it")
        log(f"  and will still run. Place candidate_patch_v0.30.39/ in dev_tools/,")
        log(f"  next to this script, for a complete run.")

    tags = {}
    for name, desc, code, timeout in PROBES:
        tags[name] = run_probe(name, desc, code, PROJECT_ROOT, timeout)

    if CANDIDATE_V39_METADATA_HANDLER.exists():
        try:
            staged_root = stage_patched_copy()
            tags[P67_NAME] = run_probe(P67_NAME, P67_DESC, P67_SCRIPT, staged_root, 120)
        except RuntimeError as e:
            header(P67_NAME)
            log(f"  {e}")
            tags[P67_NAME] = "FAIL"
    else:
        tags[P67_NAME] = "FAIL"

    header("SUMMARY")
    for name, tag in tags.items():
        label = {"OK": "OK   ", "FAIL": "FAIL ", "CRASH": "CRASH"}[tag]
        log(f"  {label}  {name}")

    log("")
    log("  (for reference, from validate_patch_shutdown_v0.30.39_20260817_112111.log:)")
    log("  CRASH  P62_v39_candidate_explicit_shutdown  (crashed INSIDE shutdown_lxml_worker())")
    log("  OK     P63_v38_candidate_os_exit")

    log("")
    log("READING THE RESULTS:")
    log("  P64 CRASH or FAIL        -> the environment itself has shifted since")
    log("                              P55 ran clean - reconcile this before")
    log("                              drawing any conclusion from P65-P67.")
    log("  P64 OK, P65/P66/P67 all OK")
    log("                           -> none of these three, changed alone,")
    log("                              reproduces P62's crash cheaply. May need")
    log("                              more than one changed together, or a")
    log("                              factor this script has not considered.")
    log("  P65 CRASH (others OK)    -> repetition count is the key variable.")
    log("  P66 CRASH (others OK)    -> which thread dispatches matters - many")
    log("                              transient dispatching threads is the")
    log("                              dangerous shape.")
    log("  P67 CRASH (others OK)    -> something specific to the REAL")
    log("                              persistent-worker implementation is")
    log("                              implicated - worth a close comparison")
    log("                              against this script's hand-rolled")
    log("                              equivalent for what differs.")
    log("  More than one of P65/P66/P67 CRASH")
    log("                           -> more than one factor contributes - note")
    log("                              exactly which combination.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
