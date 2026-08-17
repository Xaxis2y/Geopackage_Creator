# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Isolates WHY dev_tools/validate_patch_v0.30.38.py's P61 crashed, given that
its own log shows all 10 rounds of the exact originally-diagnosed pattern
completing cleanly first.

THE RESULT THIS SCRIPT FOLLOWS UP ON
-------------------------------------
dev_tools/logs/validate_patch_v0.30.38_20260817_105747.log, run on the target
machine on 2026-08-17:

    P60 (unpatched control)         -> CRASH, on round 0->1, exactly as every
                                        prior control (P17-P58) reproduces it.
    P61 (v0.30.24 candidate patch)  -> exit code 3221225477 too, BUT: the log
                                        shows "round 0" through "round 9" each
                                        printing "thread completed its FULL,
                                        real, unmodified conversion", and the
                                        probe's own closing line - "P61 OK -
                                        all 10 sequential rounds completed...
                                        zero crashes" - is present in the
                                        captured stdout. The crash only
                                        happens AFTER that line, once the
                                        subprocess's main() has returned and
                                        the interpreter is finalizing.

That is a different failure shape from every P17-P60 control, which all
crash mid-pattern (round 0 finishes, round 1's thread is where it dies).
P61's "setup" lines also confirm the staged copy's __version__ correctly
read "0.30.24" before the run proceeded, so this is not the patch failing to
apply. See dev_tools/CRASH_INVESTIGATION_STATUS_2026-08-17.md and candidate_
patch_v0.30.39/core/metadata_handler.py's own module docstring - the
"PERSISTENT LXML WORKER THREAD" and "PERSISTENT WORKER SHUTDOWN" sections -
for the full history this follows on from.

THE HYPOTHESIS THIS SCRIPT TESTS
-----------------------------------
candidate_patch_v0.30.38/core/metadata_handler.py starts its persistent lxml
worker thread with `daemon=True` and never stops it - no sentinel, no
`.join()`, no `atexit` hook anywhere in that file. When P61's subprocess
finishes its 10 rounds and lets Python exit normally, that thread is still
alive, parked in a blocking `queue.Queue.get()`, exactly when CPython
finalization and then Windows' own DLL-unload sequence for libxml2.dll and
the CRT run. A live thread that has previously touched libxml2 state, caught
by that teardown, is a plausible fit for the crash - but it is NOT yet
confirmed. This script isolates two variables, independently, against the
real target machine:

    P62  candidate_patch_v0.30.39/core/metadata_handler.py (identical to
         v0.30.38's candidate, plus ONLY an added shutdown_lxml_worker()
         that puts a stop sentinel and joins the thread - see that file's
         own "PERSISTENT WORKER SHUTDOWN" docstring section). The SAME
         10-round test as P61, then this probe explicitly calls
         shutdown_lxml_worker() before letting the interpreter exit
         normally. Expected OK if joining the thread before exit avoids the
         crash.

    P63  The ORIGINAL, UNMODIFIED v0.30.38 candidate (no shutdown
         mechanism at all - the exact file P61 already used) - the SAME
         10-round test, but instead of letting Python finalize normally,
         this probe calls os._exit(0) immediately after the 10th round,
         bypassing CPython's own finalization sequence (and any atexit
         hooks) entirely, while leaving the un-joined daemon thread exactly
         as v0.30.38 left it. Expected OK if the crash is specifically about
         CPython's own finalization touching a live daemon thread, rather
         than something that would happen at process exit regardless of how
         the process ends.

P60 is not re-run here: it was run minutes before this script was written,
on the same machine, and reproduced the documented mechanism exactly as it
always has (round 0 only) - see the log referenced above. If that log is no
longer fresh by the time this runs, or came from a different machine, re-run
dev_tools/diagnose_crash_v0.30.37.py's P58 (or dev_tools/validate_patch_
v0.30.38.py's P60) first and confirm CRASH before trusting P62/P63 either
way - the same caution validate_patch_v0.30.38.py itself gives for P61.

HOW TO READ THE RESULTS (this run's P62/P63, together with the existing
P60/P61 from validate_patch_v0.30.38_20260817_105747.log)
-------------------------------------------------------------------------------
    P62 OK, P63 OK      -> Both an explicit join AND simply skipping normal
                            Python finalization independently avoid the
                            crash. Strong support for "a live daemon thread
                            during CPython/CRT finalization" as the
                            mechanism. An explicit, joined shutdown
                            (shutdown_lxml_worker(), or equivalent) is the
                            correct direction for a production fix; os._exit
                            is informative but not a real fix by itself - it
                            also skips atexit hooks, stdio flushing, and any
                            other cleanup the application legitimately needs.
    P62 OK, P63 CRASH   -> Explicitly joining the thread fixes it; merely
                            skipping Python-level finalization does not.
                            Reinforces that a real, joined shutdown path -
                            not just "exit faster" - is what's needed.
    P62 CRASH           -> Joining the thread first is not sufficient by
                            itself. Check the "P62 setup" lines below first
                            (same discipline as every prior script in this
                            series), then this needs a different angle
                            before a fix is proposed.
    P63 OK, P62 CRASH   -> Unexpected - check the "P62 setup" lines below
                            before concluding anything. Would suggest
                            something specific to how shutdown_lxml_worker()
                            itself runs is implicated, rather than the
                            thread's mere presence at exit.

Neither result, on its own, changes what P61 already showed about the
ORIGINAL crash (10/10 clean rounds) - this script is only about the SECOND,
shutdown-time failure that run also happened to surface.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Place this script in dev_tools/, alongside candidate_patch_v0.30.38/
(already there) and candidate_patch_v0.30.39/ (new - contains
core/metadata_handler.py with shutdown_lxml_worker() added):

    conda activate geopackage
    python dev_tools\\validate_patch_shutdown_v0.30.39.py

Writes dev_tools\\logs\\validate_patch_shutdown_v0.30.39_<timestamp>.log
incrementally. Send that file back either way.
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

CANDIDATE_V38_METADATA_HANDLER = (
    DEV_TOOLS_DIR / "candidate_patch_v0.30.38" / "core" / "metadata_handler.py"
)
CANDIDATE_V38_EXPECTED_VERSION = '__version__ = "0.30.24"'

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


# ---------------------------------------------------------------------------
# Shared probe body: 10 sequential rounds, each a brand-new thread running
# one full, real, entirely unmodified conversion, joined before the next
# round's thread is created - identical to validate_patch_v0.30.38.py's
# PROBE_SCRIPT through the round loop. What happens AFTER the loop is what
# this script varies: `mode` (sys.argv[3]) selects "explicit_shutdown" (P62)
# or "os_exit" (P63).
# ---------------------------------------------------------------------------
PROBE_SCRIPT = r'''
import os, sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
tag = sys.argv[2]
mode = sys.argv[3]
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core import metadata_handler as _mh

ROUNDS = 10


def make_shapefile(round_tag, tmp_root):
    thread_dir = Path(tmp_root) / f"src_{round_tag}"
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


def run_conversion(round_tag, tmp_root):
    """The real, complete, entirely unmodified convert() - nothing
    monkey-patched, nothing neutered. This is exactly what the shipped GUI's
    do_conversion() calls."""
    local_shp = make_shapefile(round_tag, tmp_root)
    out_path = str(Path(tmp_root) / f"out_{round_tag}.gpkg")
    converter = GeoPackageConverter(profile="military")
    result = converter.convert(
        source_geodatabase=local_shp,
        output_geopackage=out_path,
        title=f"Shutdown Isolation {round_tag}",
        abstract="Isolates the shutdown-time crash seen in validate_patch_v0.30.38.py's P61",
        poc="Test User",
        org="Test Org",
        nation="USA",
        security="UNCLASSIFIED",
        generate_reports=True,
    )
    if not result.get("success"):
        raise RuntimeError(f"conversion {round_tag} reported failure: {result.get('error')}")
    return result


tmp_root = tempfile.mkdtemp()
errors = {}

def worker(i):
    try:
        run_conversion(f"{tag}_r{i}", tmp_root)
        print(f"{tag}: round {i} thread completed its FULL, real, "
              f"unmodified conversion", flush=True)
    except Exception as e:
        errors[i] = str(e)

for i in range(ROUNDS):
    print(f"{tag}: round {i} - starting a brand-new thread, will wait for "
          f"it to fully finish...", flush=True)
    t = threading.Thread(target=worker, args=(i,))
    t.start()
    t.join(timeout=60)
    if i in errors:
        print(f"{tag}: round {i} errors: {errors}", flush=True)
        raise SystemExit(1)

print(f"{tag} OK - all {ROUNDS} sequential rounds completed, each its own "
      f"brand-new thread running the real, unmodified convert(), zero "
      f"crashes", flush=True)

if mode == "explicit_shutdown":
    if not hasattr(_mh, "shutdown_lxml_worker"):
        print(f"{tag}: mode=explicit_shutdown requested but "
              f"core.metadata_handler has no shutdown_lxml_worker() - this "
              f"candidate does not implement it. Cannot run this probe.",
              flush=True)
        sys.exit(2)
    was_alive = (
        _mh._LXML_WORKER_THREAD is not None and _mh._LXML_WORKER_THREAD.is_alive()
    )
    print(f"{tag}: worker thread alive before shutdown call: {was_alive}", flush=True)
    stopped = _mh.shutdown_lxml_worker(timeout=5.0)
    print(f"{tag}: shutdown_lxml_worker(timeout=5.0) returned {stopped!r}", flush=True)
    print(f"{tag}: falling through to normal interpreter exit now "
          f"(no os._exit, no further action)", flush=True)
    # Normal fall-through: main() returns, Python finalizes as usual.
elif mode == "os_exit":
    print(f"{tag}: calling os._exit(0) now - bypassing normal Python "
          f"finalization entirely. Worker thread NOT explicitly stopped; "
          f"it is left exactly as it would be for a normal exit.",
          flush=True)
    sys.stdout.flush()
    os._exit(0)
else:
    raise SystemExit(f"{tag}: unknown mode {mode!r}")
'''


def stage_patched_copy(candidate_metadata_handler: Path, expected_version: str, label: str) -> Path:
    """Copy the whole project into a fresh temp directory, then overwrite
    ONLY core/metadata_handler.py with *candidate_metadata_handler*.

    Identical pattern to validate_patch_v0.30.38.py's stage_patched_copy(),
    generalized to accept which candidate file to stage so this script can
    reuse it for both P62 (v0.30.39 candidate) and P63 (v0.30.38 candidate).
    core/metadata_handler.py on the REAL project (PROJECT_ROOT) is never
    touched by this function or anything else in this script - it copies
    outward from PROJECT_ROOT into a disposable temp directory, and only the
    copy is modified.

    Returns:
        Path to the staged copy's project root.
    """
    stage_root = Path(tempfile.mkdtemp()) / "patched_project"
    shutil.copytree(
        PROJECT_ROOT, stage_root,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    dest_metadata_handler = stage_root / "core" / "metadata_handler.py"
    shutil.copy2(candidate_metadata_handler, dest_metadata_handler)
    log(f"  {label} setup: staged a full project copy at {stage_root}")
    log(f"  {label} setup: overwrote {dest_metadata_handler} with "
        f"{candidate_metadata_handler}")

    # Prove the substitution actually happened, in the log itself, rather
    # than trusting the copy silently succeeded - same discipline
    # validate_patch_v0.30.38.py's stage_patched_copy() uses.
    staged_version_line = None
    for line in dest_metadata_handler.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            staged_version_line = line.strip()
            break
    log(f"  {label} setup: staged core/metadata_handler.py reports: {staged_version_line}")
    if staged_version_line != expected_version:
        raise RuntimeError(
            f"{label} setup FAILED: staged core/metadata_handler.py does not "
            f"report {expected_version} - the candidate patch was not "
            f"applied correctly. Aborting before running {label}, since its "
            f"result would be meaningless."
        )
    return stage_root


def run_probe(name: str, root_for_probe: Path, mode: str, timeout: int = 180) -> str:
    """Runs the shared PROBE_SCRIPT against *root_for_probe* in *mode* and
    returns the result tag: "OK", "FAIL", or "CRASH"."""
    f = Path(tempfile.mkdtemp()) / f"{name}.py"
    f.write_text(PROBE_SCRIPT, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(f), str(root_for_probe), name, mode],
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
    path = LOG_DIR / f"validate_patch_shutdown_v0.30.39_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - SHUTDOWN-CRASH ISOLATION (v0.30.39)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  Follows up on dev_tools/logs/validate_patch_v0.30.38_20260817_105747.log's")
    log("  P61 result: 10/10 real conversion rounds completed with zero")
    log("  crashes, then the process crashed with the same access-violation")
    log("  code AFTER that, during interpreter shutdown. P62 tests whether")
    log("  explicitly stopping and joining the persistent lxml worker thread")
    log("  before exit avoids that crash. P63 tests whether bypassing normal")
    log("  Python finalization (os._exit) avoids it, with the SAME un-joined")
    log("  worker thread v0.30.38's candidate already leaves behind. See this")
    log("  script's own module docstring for the full reasoning and how to")
    log("  read the results together.")

    missing = []
    if not CANDIDATE_V39_METADATA_HANDLER.exists():
        missing.append(CANDIDATE_V39_METADATA_HANDLER)
    if not CANDIDATE_V38_METADATA_HANDLER.exists():
        missing.append(CANDIDATE_V38_METADATA_HANDLER)
    if missing:
        header("SETUP ERROR")
        log(f"  Expected to find:")
        for p in missing:
            log(f"    {p}")
        log(f"  One or more of these does not exist. Place candidate_patch_v0.30.38/")
        log(f"  and candidate_patch_v0.30.39/ (each containing core/metadata_handler.py)")
        log(f"  in dev_tools/, next to this script, and re-run.")
        _LOG_FH.close()
        print(f"\nSETUP ERROR - see {path}")
        return 1

    header("P62_v39_candidate_explicit_shutdown")
    log("  The same 10-round test as P61, against a temporary copy of the")
    log("  whole project with ONLY core/metadata_handler.py replaced by")
    log("  candidate_patch_v0.30.39 (v0.30.38's candidate + shutdown_lxml_")
    log("  worker()). After all 10 rounds complete, this probe explicitly")
    log("  calls shutdown_lxml_worker() before letting the interpreter exit")
    log("  normally. Expected OK if joining the thread before exit avoids")
    log("  the crash P61 hit.")
    try:
        v39_root = stage_patched_copy(
            CANDIDATE_V39_METADATA_HANDLER, CANDIDATE_V39_EXPECTED_VERSION, "P62"
        )
        p62 = run_probe("P62", v39_root, mode="explicit_shutdown")
    except RuntimeError as e:
        log(f"  {e}")
        p62 = "FAIL"

    header("P63_v38_candidate_os_exit")
    log("  The same 10-round test as P61, against a FRESH temporary copy of")
    log("  the whole project with core/metadata_handler.py replaced by the")
    log("  ORIGINAL, unmodified candidate_patch_v0.30.38 (the exact file P61")
    log("  already used - no shutdown mechanism). After all 10 rounds")
    log("  complete, this probe calls os._exit(0) immediately, bypassing")
    log("  normal Python finalization entirely, leaving the un-joined daemon")
    log("  worker thread exactly as v0.30.38's candidate always leaves it.")
    log("  Expected OK if simply skipping normal interpreter finalization -")
    log("  with no change to the thread's lifecycle at all - also avoids the")
    log("  crash P61 hit.")
    try:
        v38_root = stage_patched_copy(
            CANDIDATE_V38_METADATA_HANDLER, CANDIDATE_V38_EXPECTED_VERSION, "P63"
        )
        p63 = run_probe("P63", v38_root, mode="os_exit")
    except RuntimeError as e:
        log(f"  {e}")
        p63 = "FAIL"

    header("SUMMARY")
    label = {"OK": "OK   ", "FAIL": "FAIL ", "CRASH": "CRASH"}
    log(f"  {label[p62]}  P62_v39_candidate_explicit_shutdown")
    log(f"  {label[p63]}  P63_v38_candidate_os_exit")
    log("")
    log("  (for reference, from dev_tools/logs/validate_patch_v0.30.38_20260817_105747.log:)")
    log("  CRASH  P60_control_real_unpatched_project")
    log("  CRASH  P61_candidate_patch_applied  (10/10 rounds clean, crashed AFTER)")

    log("")
    log("HOW TO READ THIS:")
    log("  P62 OK, P63 OK    -> both an explicit join and skipping normal")
    log("                       Python finalization independently avoid the")
    log("                       crash - strong support for 'live daemon")
    log("                       thread during CPython/CRT finalization' as")
    log("                       the mechanism. An explicit, joined shutdown")
    log("                       is the right direction for a real fix.")
    log("  P62 OK, P63 CRASH -> joining the thread fixes it; skipping")
    log("                       finalization alone does not. Reinforces that")
    log("                       a real, joined shutdown path is what's")
    log("                       needed, not just a faster exit.")
    log("  P62 CRASH         -> joining the thread first is not sufficient")
    log("                       by itself - check the 'P62 setup' lines above")
    log("                       before concluding anything, then this needs a")
    log("                       different angle before a fix is proposed.")
    log("  P63 OK, P62 CRASH -> unexpected; check the 'P62 setup' lines")
    log("                       above - would suggest something about how")
    log("                       shutdown_lxml_worker() itself runs is")
    log("                       implicated, not just the thread's presence at")
    log("                       exit.")
    log("")
    log("  Neither result changes what P61 already showed about the ORIGINAL")
    log("  crash (10/10 clean rounds) - this script is only about the SECOND,")
    log("  shutdown-time failure that run also happened to surface.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
