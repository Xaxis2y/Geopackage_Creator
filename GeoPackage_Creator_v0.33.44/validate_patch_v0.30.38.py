# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Validates the candidate patch in candidate_patch_v0.30.38/core/metadata_handler.py
against the real crash, on THIS machine, end to end.

WHY THIS SCRIPT IS DIFFERENT FROM EVERY PRIOR diagnose_crash_vX.py
----------------------------------------------------------------------
Every diagnostic from v0.30.17 through v0.30.37 either ran the real,
UNMODIFIED pipeline (the controls) or monkey-patched real functions
(MetadataHandler.validate_schema, etc.) to isolate one variable at a time.
That was the right tool for bisecting a cause. It is the wrong tool for
validating a fix: monkey-patching a no-op or a mock IN PLACE of the fix
would prove the mock is safe, not that the actual patched code is.

This script does neither. It runs the real, complete, entirely unmodified
GeoPackageConverter.convert() - nothing monkey-patched, nothing neutered -
against TWO different copies of core/metadata_handler.py:

    P60  the real, currently-shipping file, exactly as it sits in core/
         today (unpatched). Expected to crash, same as every control this
         whole series has ever run (P17 through P58) - this is the same
         harness, so it must reproduce the same result before P61 means
         anything.

    P61  a temporary copy of the whole project with ONLY core/metadata_
         handler.py replaced by the candidate patch
         (candidate_patch_v0.30.38/core/metadata_handler.py). Nothing else
         differs. Expected to complete ALL rounds with zero crashes.

Both probes run the SAME test body: 10 sequential rounds, each round a
brand-new OS thread running one full, real conversion, joined to completion
before the next round's thread is even created - exactly the pattern in
the original bug report, and exactly what a user repeatedly clicking
"Convert to GeoPackage" in the shipped GUI produces over a session
(geopackage_creator_gui.py's start_conversion() refuses to start a second
conversion thread while one is in flight, so every real session is this
same strictly-sequential shape). 10 rounds is double dev_tools/diagnose_
crash_v0.30.35.py's P55 (5 rounds), which already validated this same
persistent-worker-thread pattern under monkey-patched conditions; this is
the same claim, at higher repetition, against the unmodified real code.

WHAT THIS DOES NOT TEST
--------------------------
This only exercises the strictly-sequential pattern, which is what P52/P55
(under monkey-patching) and the shipped GUI/CLI's own is_converting guard
and _GLOBAL_CONVERSION_LOCK (see core/gdal_handler.py) together make the
ONLY pattern the shipped product can currently produce. It does not repeat
diagnose_crash_v0.30.36.py/_v0.30.37.py's concurrent-attempt batches (P57/
P59) against this real patch - those were about robustness beyond today's
actual usage. A follow-up validation script can add that if useful; it is
not required to trust this result for the product as it ships today.

Reading the results:
    P60 OK                    -> this harness is not faithfully reproducing
                                  the crash on this machine right now; stop
                                  and compare against a fresh diagnose_
                                  crash_v0.30.37.py P58 run before trusting
                                  P61 either way.
    P60 CRASH, P61 OK (10/10) -> the candidate patch fixes the crash, under
                                  the real, unmodified convert(), at 2x the
                                  repetition already validated under
                                  monkey-patching. Strong evidence this is
                                  ready to move from core/metadata_handler.py's
                                  candidate copy into the real one.
    P60 CRASH, P61 crashes
    too                        -> the patch did not fix it, or the staged
                                  copy did not actually pick up the patched
                                  file - check the log's "P61 setup" lines
                                  before concluding anything about the fix
                                  itself.

No file under core/ is modified by running this script. P61 runs against a
disposable temporary copy of the whole project; core/metadata_handler.py on
disk is untouched either way.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Place this script in dev_tools/, alongside candidate_patch_v0.30.38/
(containing core/metadata_handler.py, the candidate patch):

    conda activate geopackage
    python dev_tools\\validate_patch_v0.30.38.py

Writes dev_tools\\logs\\validate_patch_v0.30.38_<timestamp>.log incrementally.
Send that file back either way.
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
CANDIDATE_PATCH_METADATA_HANDLER = (
    DEV_TOOLS_DIR / "candidate_patch_v0.30.38" / "core" / "metadata_handler.py"
)

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
# Shared probe body: N sequential rounds, each a brand-new thread running one
# full, real, entirely unmodified conversion, joined before the next round's
# thread is created. Identical for P60 and P61 - only which project ROOT
# directory is passed as sys.argv[1] differs (the real project for P60, a
# temporary patched copy for P61).
# ---------------------------------------------------------------------------
PROBE_SCRIPT = r'''
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
tag = sys.argv[2]
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter

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
        title=f"Patch Validation {round_tag}",
        abstract="Validates the persistent-lxml-worker-thread patch",
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
'''


def stage_patched_copy() -> Path:
    """Copy the whole project into a fresh temp directory, then overwrite
    ONLY core/metadata_handler.py with the candidate patch.

    core/metadata_handler.py on the REAL project (PROJECT_ROOT) is never
    touched by this function or by anything else in this script - it copies
    outward from PROJECT_ROOT into a disposable temp directory, and only
    the copy is modified.

    Returns:
        Path to the staged copy's project root (the directory containing
        its own core/, schemas/, etc.).
    """
    stage_root = Path(tempfile.mkdtemp()) / "patched_project"
    shutil.copytree(
        PROJECT_ROOT, stage_root,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    dest_metadata_handler = stage_root / "core" / "metadata_handler.py"
    shutil.copy2(CANDIDATE_PATCH_METADATA_HANDLER, dest_metadata_handler)
    log(f"  P61 setup: staged a full project copy at {stage_root}")
    log(f"  P61 setup: overwrote {dest_metadata_handler} with the candidate patch")

    # Prove the substitution actually happened, in the log itself, rather
    # than trusting the copy silently succeeded.
    staged_version_line = None
    for line in dest_metadata_handler.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            staged_version_line = line.strip()
            break
    log(f"  P61 setup: staged core/metadata_handler.py reports: {staged_version_line}")
    if staged_version_line != '__version__ = "0.30.24"':
        raise RuntimeError(
            "P61 setup FAILED: staged core/metadata_handler.py does not report "
            "__version__ = \"0.30.24\" - the candidate patch was not applied "
            "correctly. Aborting before running P61, since its result would "
            "be meaningless."
        )
    return stage_root


def run_probe(name: str, root_for_probe: Path, timeout: int = 180) -> str:
    """Runs the shared PROBE_SCRIPT against *root_for_probe* and returns the
    result tag: "OK", "FAIL", or "CRASH"."""
    f = Path(tempfile.mkdtemp()) / f"{name}.py"
    f.write_text(PROBE_SCRIPT, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(f), str(root_for_probe), name],
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
    path = LOG_DIR / f"validate_patch_v0.30.38_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CANDIDATE PATCH VALIDATION (v0.30.38)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  Validates candidate_patch_v0.30.38/core/metadata_handler.py -")
    log("  the persistent-lxml-worker-thread fix - against the real crash,")
    log("  end to end, through the REAL, entirely unmodified convert().")
    log("  No monkey-patching anywhere in this script. P60 runs the real")
    log("  project as it stands today (expected CRASH, same as every prior")
    log("  control). P61 runs the identical test against a temporary copy")
    log("  of the whole project with ONLY metadata_handler.py replaced by")
    log("  the candidate patch (expected OK, 10/10 rounds).")

    if not CANDIDATE_PATCH_METADATA_HANDLER.exists():
        header("SETUP ERROR")
        log(f"  Expected to find the candidate patch at:")
        log(f"    {CANDIDATE_PATCH_METADATA_HANDLER}")
        log(f"  That file does not exist. Place candidate_patch_v0.30.38/")
        log(f"  (containing core/metadata_handler.py) in dev_tools/, next to")
        log(f"  this script, and re-run.")
        _LOG_FH.close()
        print(f"\nSETUP ERROR - see {path}")
        return 1

    header("P60_control_real_unpatched_project")
    log("  10 sequential rounds (new thread each round, joined before the "
        "next starts) against the real project exactly as it sits in "
        "core/ today - unpatched. Expected CRASH, matching every prior "
        "control (P17 through P58).")
    p60 = run_probe("P60", PROJECT_ROOT)

    header("P61_candidate_patch_applied")
    log("  The SAME 10-round test, against a temporary copy of the whole "
        "project with ONLY core/metadata_handler.py replaced by the "
        "candidate patch. Expected OK - all 10 rounds clean.")
    try:
        patched_root = stage_patched_copy()
        p61 = run_probe("P61", patched_root)
    except RuntimeError as e:
        log(f"  {e}")
        p61 = "FAIL"

    header("SUMMARY")
    label = {"OK": "OK   ", "FAIL": "FAIL ", "CRASH": "CRASH"}
    log(f"  {label[p60]}  P60_control_real_unpatched_project")
    log(f"  {label[p61]}  P61_candidate_patch_applied")

    log("")
    log("HOW TO READ THIS:")
    log("  P60 OK                    -> this harness is not faithfully")
    log("                                reproducing the crash on this")
    log("                                machine right now - compare against")
    log("                                a fresh diagnose_crash_v0.30.37.py")
    log("                                P58 run before trusting P61 either")
    log("                                way.")
    log("  P60 CRASH, P61 OK (10/10) -> the candidate patch fixes the crash,")
    log("                                under the real, unmodified")
    log("                                convert(), at 2x the repetition")
    log("                                already validated under")
    log("                                monkey-patching.")
    log("  P60 CRASH, P61 crashes too -> the patch did not fix it, or the")
    log("                                staged copy did not actually pick")
    log("                                up the patched file - check the")
    log("                                'P61 setup' lines above before")
    log("                                concluding anything about the fix")
    log("                                itself.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
