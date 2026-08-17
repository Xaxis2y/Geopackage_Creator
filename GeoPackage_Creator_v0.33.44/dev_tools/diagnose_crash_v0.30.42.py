# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.42 - follow-up to
dev_tools/diagnose_crash_v0.30.41.py's P67R/P68/P69 results.

WHAT v0.30.41 SHOWED
----------------------
dev_tools/logs/diagnose_v0.30.41_20260817_121441.log, run on the target
machine on 2026-08-17:

    P67R  control, exact rerun of P67                          -> CRASH (round 1, matches P67 exactly)
    P68   round's own thread dispatches itself (P61's shape)    -> CRASH (round 1)
    P69   worker pre-warmed before any GDAL activity            -> CRASH (round 0 - even faster)

Neither dispatch-thread identity nor worker-creation timing explains the
crash - both P68 and P69 still crashed, fast, using the REAL worker. That
leaves the central puzzle from v0.30.41 untouched: why did validate_patch_
v0.30.38.py's P61 - the real, unmonkeypatched pipeline, also using the real
worker - survive 10/10 rounds, when every monkeypatched version of
essentially the same shape crashes within 1-2 rounds?

THE NEW LEAD: A LOCK NONE OF P51-P69 HAS EVER HELD DURING DISPATCH
-----------------------------------------------------------------------
Reading core/converter.py and core/gdal_handler.py directly (not needed
until now) surfaced something this whole series has never accounted for.
`GeoPackageConverter.convert()` is wrapped in a decorator, `_serialize_
conversions` (core/converter.py:89), which acquires a process-wide
`threading.RLock()` - `_GLOBAL_CONVERSION_LOCK` in core/gdal_handler.py:74,
exposed via `global_conversion_lock()` - around the ENTIRE conversion: the
GDAL write, metadata generation, AND the internal `validate_schema()` call
at converter.py:619, for the FULL duration of `convert()`. Its own docstring
explains why: "a conversion is not just the GDAL dataset write - it
continues through sqlite3 metadata embedding, DGIWG finalization and
validation, all against the same file... when the guarantee [of no
concurrent access] is absent the failure mode is a native access violation
rather than an exception."

In P61, `validate_schema()` is called from INSIDE `convert()` (converter.py:
619), so its dispatch to the persistent worker happens while this lock is
held. But every bisection probe in this entire series - P51 through P69,
hand-rolled worker or real - dispatches validation as a SEPARATE call made
AFTER `run_conversion_gdal_only()`'s `convert()` call has already returned
and released this lock. That is an inadvertent confound present in every
probe so far: none of them have ever exercised the metadata dispatch under
the same lock production always holds it under at that point.

A second, related gap: every monkeypatched probe in this series validates a
deliberately trivial, always-FAILING "<x/>" document (tolerating the
resulting ValueError), never the kind of complete, schema-PASSING document
`MetadataHandler.generate_package_metadata()` actually produces in
production. This has never been isolated as its own variable either.

WHAT THIS SCRIPT ISOLATES
----------------------------
Three probes, all staged against the REAL candidate_patch_v0.30.39 module,
each a minimal, single-variable change from v0.30.41's P68 (real worker,
round-thread dispatch, trivial doc, no lock - CRASH):

  P70  Same as P68, except the round's own thread holds
       core.gdal_handler.global_conversion_lock() (the SAME RLock
       _serialize_conversions uses) across both its GDAL write and its
       validation dispatch - exactly mirroring what happens when
       validate_schema() is called from inside convert(), without changing
       anything else. Document stays the trivial "<x/>". Isolates the lock
       alone.

  P71  Same as P68 (no lock), except the dispatched document is a REAL,
       complete ISO 19115 package document built by MetadataHandler.
       generate_package_metadata() itself - using the exact same profile
       ("military") and field values run_conversion_gdal_only() already
       uses elsewhere in this series - expected to PASS validation (return
       True), not raise ValueError. Isolates document content / validation
       outcome alone, no lock.

  P72  Combines both changes together - lock held, real passing document -
       the most production-faithful reconstruction of what P61 actually
       does, short of running the full unmonkeypatched pipeline again.

READING THE RESULTS
---------------------
    P70 OK, P71 CRASH, P72 OK   -> the lock is the deciding factor; document
                                    content does not matter on its own. This
                                    explains P61 and points at a concrete
                                    fix: any validate_schema() call must be
                                    made while holding global_conversion_
                                    lock() (which convert() already does
                                    internally - the danger would be code
                                    paths that call validate_schema() or
                                    shutdown_lxml_worker() from outside any
                                    convert() call, exactly what P62's crash
                                    already showed for shutdown).
    P70 CRASH, P71 OK, P72 OK  -> document content/validation outcome is the
                                    deciding factor, not the lock. Real,
                                    passing documents are safe; trivial,
                                    failing ones are dangerous - independent
                                    of locking.
    P70 CRASH, P71 CRASH, P72 OK
                                 -> neither alone is sufficient - only the
                                    full combination (P61's actual shape)
                                    avoids the crash. Strong confirmation
                                    that P61's specific conditions matter,
                                    without fully isolating why.
    P70 CRASH, P71 CRASH, P72 CRASH
                                 -> neither factor, alone or combined,
                                    explains P61's survival. Would suggest
                                    P61's clean 10/10 run may itself have
                                    been a low-probability escape rather
                                    than a deterministic safe shape, and
                                    this investigation should shift toward
                                    treating the crash as probabilistic
                                    rather than cleanly triggerable.
    Any other combination       -> a more complex, non-monotonic
                                    interaction - worth a careful, separate
                                    follow-up rather than assuming either
                                    factor in isolation.

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series. This is still bisection, not a fix.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Place this script in dev_tools/, alongside candidate_patch_v0.30.39/
(needed by all three probes here - already there from an earlier delivery):

    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.42.py

Writes dev_tools\\logs\\diagnose_v0.30.42_<timestamp>.log incrementally, so a
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

    All three probes in this script need this, same as v0.30.41. Called
    once; all three probes run against the same staged copy, since staging
    only copies files to disk and nothing in this script's probes mutates
    them.

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
# Shared building blocks. make_shapefile/run_conversion_gdal_only are
# textually identical to v0.30.40/v0.30.41's - same shapefile, same
# convert() call, same "military" profile, same explicit security level, so
# the profile defaults this script's REAL_DOC_KWARGS below relies on
# (language "eng", topic_category "intelligenceMilitary" - see core/
# config.py's CONVERSION_PROFILES["military"]) are exactly what
# run_conversion_gdal_only's own convert() calls already resolve to
# elsewhere in this series.
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
    real GDAL, zero real lxml in this thread. Uses profile="military",
    same as every other probe in this series - security is passed
    explicitly (UNCLASSIFIED); language/topic_category are left to the
    profile's own defaults (eng / intelligenceMilitary), exactly like
    REAL_DOC_KWARGS below assumes."""
    local_shp = make_shapefile(tag, tmp_root)
    out_path = str(Path(tmp_root) / f"out_{tag}.gpkg")
    converter = GeoPackageConverter(profile="military")
    result = converter.convert(
        source_geodatabase=local_shp,
        output_geopackage=out_path,
        title=f"P67 Lock/Document Bisection {tag}",
        abstract="Isolates global_conversion_lock() and real-vs-trivial document content behind diagnose_crash_v0.30.41.py's P67R/P68/P69 crashes",
        poc="Test User",
        org="Test Org",
        nation="USA",
        security="UNCLASSIFIED",
        generate_reports=True,
    )
    if not result.get("success"):
        raise RuntimeError(f"conversion {tag} reported failure: {result.get('error')}")
    return result


def build_real_passing_xml(handler, tag):
    """A REAL, complete ISO 19115 package document, built by the project's
    own MetadataHandler.generate_package_metadata() - not a hand-written
    approximation - using the exact field values run_conversion_gdal_only()
    above already resolves to via the "military" profile. This function's
    own internal self-validation call (metadata_handler.py:1243) is a no-op
    under this script's class-level validate_schema monkeypatch, same as it
    is inside convert() - it does not touch lxml. Expected to PASS
    validation when later passed to _ORIG_VALIDATE_SCHEMA for real."""
    return handler.generate_package_metadata(
        title=f"P67 Lock/Document Bisection {tag}",
        abstract="Isolates global_conversion_lock() and real-vs-trivial document content behind diagnose_crash_v0.30.41.py's P67R/P68/P69 crashes",
        poc="Test User",
        org="Test Org",
        nation="USA",
        security="UNCLASSIFIED",
        language="eng",
        topic_category="intelligenceMilitary",
        ref_date=datetime.now().strftime("%Y-%m-%d"),
    )
'''


# ---------------------------------------------------------------------------
# P70: same as v0.30.41's P68 (real worker, round-thread dispatch, trivial
# "<x/>" document), except the round's own thread holds
# global_conversion_lock() across both its GDAL write and its validation
# dispatch - mirroring exactly what happens when validate_schema() is
# called from inside convert(). Isolates the lock alone.
# ---------------------------------------------------------------------------
P70_SCRIPT = r'''
import sys, tempfile, threading
from datetime import datetime
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler
from core import metadata_handler as _mh
from core.gdal_handler import global_conversion_lock

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


tmp_root = tempfile.mkdtemp()
errors = {}

for round_i in range(ROUNDS):
    tag = f"P70_r{round_i}"
    print(f"P70: round {round_i} - starting a NEW thread that will do GDAL AND "
          f"dispatch its own validation to the REAL worker, BOTH while holding "
          f"global_conversion_lock()...", flush=True)

    round_error = {}
    def round_worker():
        try:
            with global_conversion_lock():
                run_conversion_gdal_only(tag, tmp_root)
                validate_via_real_worker(tag)
        except Exception as e:
            round_error["e"] = str(e)

    t = threading.Thread(target=round_worker)
    t.start()
    t.join(timeout=30)
    if "e" in round_error:
        print(f"P70: round {round_i} error: {round_error['e']}", flush=True)
        errors[round_i] = round_error["e"]
        break
    print(f"P70: round {round_i} completed - GDAL write and validation dispatch both "
          f"done under global_conversion_lock(), on the same, single, freshly-created "
          f"thread for this round.", flush=True)

was_alive = _mh._LXML_WORKER_THREAD is not None and _mh._LXML_WORKER_THREAD.is_alive()
print(f"P70: all {ROUNDS} rounds done, REAL worker thread alive: {was_alive} - "
      f"now calling the REAL shutdown_lxml_worker(timeout=5.0)...", flush=True)
stopped = _mh.shutdown_lxml_worker(timeout=5.0)
print(f"P70: shutdown_lxml_worker(timeout=5.0) returned {stopped!r}", flush=True)

if errors:
    print(f"P70: errors: {errors}", flush=True)
    raise SystemExit(1)

print(f"P70 OK - all {ROUNDS} rounds completed (each under global_conversion_lock()) "
      f"and the REAL persistent worker stopped cleanly via the REAL "
      f"shutdown_lxml_worker()", flush=True)
'''


# ---------------------------------------------------------------------------
# P71: same as v0.30.41's P68 (real worker, round-thread dispatch, NO lock),
# except the dispatched document is a REAL, complete, schema-PASSING
# document from generate_package_metadata() instead of the trivial always-
# failing "<x/>". Isolates document content / validation outcome alone.
# ---------------------------------------------------------------------------
P71_SCRIPT = r'''
import sys, tempfile, threading
from datetime import datetime
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

def validate_via_real_worker_realdoc(tag):
    handler = MetadataHandler()
    xml_str = build_real_passing_xml(handler, tag)
    result = _ORIG_VALIDATE_SCHEMA(handler, xml_str)
    if result is not True:
        raise RuntimeError(
            f"{tag}: expected validate_schema() to return True for a real, "
            f"schema-conformant document, got {result!r} instead"
        )


tmp_root = tempfile.mkdtemp()
errors = {}

for round_i in range(ROUNDS):
    tag = f"P71_r{round_i}"
    print(f"P71: round {round_i} - starting a NEW thread that will do GDAL AND "
          f"dispatch its own validation to the REAL worker (no lock)...", flush=True)

    round_error = {}
    def round_worker():
        try:
            run_conversion_gdal_only(tag, tmp_root)
            validate_via_real_worker_realdoc(tag)
        except Exception as e:
            round_error["e"] = str(e)

    t = threading.Thread(target=round_worker)
    t.start()
    t.join(timeout=30)
    if "e" in round_error:
        print(f"P71: round {round_i} error: {round_error['e']}", flush=True)
        errors[round_i] = round_error["e"]
        break
    print(f"P71: round {round_i} completed - GDAL write and validation (REAL, PASSING "
          f"document) both done on the same, single, freshly-created thread for this "
          f"round, no lock held.", flush=True)

was_alive = _mh._LXML_WORKER_THREAD is not None and _mh._LXML_WORKER_THREAD.is_alive()
print(f"P71: all {ROUNDS} rounds done, REAL worker thread alive: {was_alive} - "
      f"now calling the REAL shutdown_lxml_worker(timeout=5.0)...", flush=True)
stopped = _mh.shutdown_lxml_worker(timeout=5.0)
print(f"P71: shutdown_lxml_worker(timeout=5.0) returned {stopped!r}", flush=True)

if errors:
    print(f"P71: errors: {errors}", flush=True)
    raise SystemExit(1)

print(f"P71 OK - all {ROUNDS} rounds completed (each validating a REAL, PASSING "
      f"document, no lock) and the REAL persistent worker stopped cleanly via the "
      f"REAL shutdown_lxml_worker()", flush=True)
'''


# ---------------------------------------------------------------------------
# P72: combines both changes - global_conversion_lock() held AND a REAL,
# schema-passing document - the most production-faithful reconstruction of
# what P61 actually does, short of rerunning the full unmonkeypatched
# pipeline again.
# ---------------------------------------------------------------------------
P72_SCRIPT = r'''
import sys, tempfile, threading
from datetime import datetime
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler
from core import metadata_handler as _mh
from core.gdal_handler import global_conversion_lock

ROUNDS = 5

_ORIG_VALIDATE_SCHEMA = MetadataHandler.validate_schema

def _noop_validate_schema(self, metadata_xml_string):
    return True

MetadataHandler.validate_schema = _noop_validate_schema

''' + _COMMON_HELPERS + r'''

def validate_via_real_worker_realdoc(tag):
    handler = MetadataHandler()
    xml_str = build_real_passing_xml(handler, tag)
    result = _ORIG_VALIDATE_SCHEMA(handler, xml_str)
    if result is not True:
        raise RuntimeError(
            f"{tag}: expected validate_schema() to return True for a real, "
            f"schema-conformant document, got {result!r} instead"
        )


tmp_root = tempfile.mkdtemp()
errors = {}

for round_i in range(ROUNDS):
    tag = f"P72_r{round_i}"
    print(f"P72: round {round_i} - starting a NEW thread that will do GDAL AND "
          f"dispatch its own validation (REAL, PASSING document) to the REAL "
          f"worker, BOTH while holding global_conversion_lock()...", flush=True)

    round_error = {}
    def round_worker():
        try:
            with global_conversion_lock():
                run_conversion_gdal_only(tag, tmp_root)
                validate_via_real_worker_realdoc(tag)
        except Exception as e:
            round_error["e"] = str(e)

    t = threading.Thread(target=round_worker)
    t.start()
    t.join(timeout=30)
    if "e" in round_error:
        print(f"P72: round {round_i} error: {round_error['e']}", flush=True)
        errors[round_i] = round_error["e"]
        break
    print(f"P72: round {round_i} completed - GDAL write and validation (REAL, PASSING "
          f"document) both done under global_conversion_lock(), on the same, single, "
          f"freshly-created thread for this round.", flush=True)

was_alive = _mh._LXML_WORKER_THREAD is not None and _mh._LXML_WORKER_THREAD.is_alive()
print(f"P72: all {ROUNDS} rounds done, REAL worker thread alive: {was_alive} - "
      f"now calling the REAL shutdown_lxml_worker(timeout=5.0)...", flush=True)
stopped = _mh.shutdown_lxml_worker(timeout=5.0)
print(f"P72: shutdown_lxml_worker(timeout=5.0) returned {stopped!r}", flush=True)

if errors:
    print(f"P72: errors: {errors}", flush=True)
    raise SystemExit(1)

print(f"P72 OK - all {ROUNDS} rounds completed (each under global_conversion_lock(), "
      f"each validating a REAL, PASSING document) and the REAL persistent worker "
      f"stopped cleanly via the REAL shutdown_lxml_worker()", flush=True)
'''


PROBES: "list[tuple[str, str, str, int]]" = [
    (
        "P70_lock_held_trivial_doc",
        "Same as v0.30.41's P68, except the round's own thread holds "
        "global_conversion_lock() across both its GDAL write and its "
        "validation dispatch - mirroring exactly what happens when "
        "validate_schema() is called from inside convert(). Document stays "
        "the trivial \"<x/>\". Isolates the lock alone.",
        P70_SCRIPT,
        120,
    ),
    (
        "P71_real_doc_no_lock",
        "Same as v0.30.41's P68 (no lock), except the dispatched document "
        "is a REAL, complete, schema-PASSING document from generate_"
        "package_metadata() instead of the trivial always-failing \"<x/>\". "
        "Isolates document content / validation outcome alone.",
        P71_SCRIPT,
        120,
    ),
    (
        "P72_lock_and_real_doc",
        "Combines both changes - lock held AND a real, passing document - "
        "the most production-faithful reconstruction of what P61 actually "
        "does.",
        P72_SCRIPT,
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
    path = LOG_DIR / f"diagnose_v0.30.42_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - LOCK / DOCUMENT-CONTENT BISECTION (v0.30.42)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  Follows up on diagnose_crash_v0.30.41.py's P67R/P68/P69, all three of")
    log("  which crashed regardless of dispatch-thread identity or worker-creation")
    log("  timing. Reading core/converter.py and core/gdal_handler.py directly")
    log("  surfaced a lock - global_conversion_lock(), an RLock that convert()")
    log("  always holds for its full duration via the _serialize_conversions")
    log("  decorator - that P61 (the only real-pipeline success using the real")
    log("  worker) dispatches validation under, and that every bisection probe in")
    log("  this series, this script's own prior probes included, has never held")
    log("  during its dispatch. This script isolates that lock, and a second")
    log("  never-isolated variable - real vs trivial document content - one at a")
    log("  time and combined. See this script's own module docstring for the full")
    log("  reasoning.")

    if not CANDIDATE_V39_METADATA_HANDLER.exists():
        header("SETUP ERROR")
        log(f"  {CANDIDATE_V39_METADATA_HANDLER} does not exist.")
        log(f"  All three probes in this script need it. Place")
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
    log("  (for reference, from diagnose_v0.30.41_20260817_121441.log:)")
    log("  CRASH  P67R_control_rerun                      (round 1)")
    log("  CRASH  P68_dispatch_from_round_thread_real      (round 1)")
    log("  CRASH  P69_prewarmed_worker_real                (round 0 - fastest yet)")
    log("  (for reference, from validate_patch_v0.30.38_20260817_105747.log:)")
    log("  OK     P61  real, unmonkeypatched pipeline, 10/10 rounds")

    log("")
    log("READING THE RESULTS:")
    log("  P70 OK, P71 CRASH, P72 OK")
    log("                           -> the lock is the deciding factor; document")
    log("                              content does not matter on its own. Explains")
    log("                              P61 and points at a concrete fix: any")
    log("                              validate_schema() call must be made while")
    log("                              holding global_conversion_lock().")
    log("  P70 CRASH, P71 OK, P72 OK")
    log("                           -> document content/validation outcome is the")
    log("                              deciding factor, not the lock.")
    log("  P70 CRASH, P71 CRASH, P72 OK")
    log("                           -> neither alone is sufficient - only the full")
    log("                              combination (P61's actual shape) avoids the")
    log("                              crash.")
    log("  P70 CRASH, P71 CRASH, P72 CRASH")
    log("                           -> neither factor, alone or combined, explains")
    log("                              P61's survival - P61's clean run may itself")
    log("                              have been a low-probability escape rather")
    log("                              than a deterministic safe shape.")
    log("  Any other combination   -> a more complex, non-monotonic interaction -")
    log("                              worth a careful, separate follow-up.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
