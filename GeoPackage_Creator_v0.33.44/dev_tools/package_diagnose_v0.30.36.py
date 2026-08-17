# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for diagnose_crash_v0.30.36.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a single dev_tools diagnostic script rather than a full release.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside diagnose_crash_v0.30.36.py:

    conda activate geopackage
    cd dev_tools
    python package_diagnose_v0.30.36.py

Produces:
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.36_<timestamp>\\
        diagnose_crash_v0.30.36.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.36_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "diagnose_crash_v0.30.36.py"
DIAGNOSTIC_VERSION = "0.30.36"


def main() -> int:
    here = Path(__file__).resolve().parent
    source = here / SCRIPT_NAME

    if not source.exists():
        print(f"ERROR: {SCRIPT_NAME} not found next to this packaging script.")
        print(f"Expected at: {source}")
        print("Place both files in the same dev_tools\\ folder and re-run.")
        return 1

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dist_root = here / "diagnostics_dist"
    stage_dir = dist_root / f"diagnose_crash_v{DIAGNOSTIC_VERSION}_{timestamp}"
    stage_dir.mkdir(parents=True, exist_ok=True)

    # 1. Copy the diagnostic script into the staging folder.
    dest_script = stage_dir / SCRIPT_NAME
    shutil.copy2(source, dest_script)
    print(f"Copied: {dest_script}")

    # 2. Write a small VERSION note (project convention: every packaged
    #    artifact carries a VERSION.txt describing what it is).
    version_txt = stage_dir / "VERSION.txt"
    version_txt.write_text(
        "GeoPackage Creator - crash diagnostic package\n"
        f"Diagnostic version : {DIAGNOSTIC_VERSION}\n"
        f"Packaged           : {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"Script             : {SCRIPT_NAME}\n"
        "\n"
        "Follow-up to diagnose_crash_v0.30.35.py. v0.30.35 came back clean:\n"
        "\n"
        "  CRASH  P54_control_no_patch\n"
        "  OK     P55_persistent_lxml_thread_five_rounds\n"
        "\n"
        "All 5 rounds completed with zero crashes, using one persistent lxml\n"
        "worker thread (created once, reused every round) while every round's\n"
        "GDAL work stayed on its own brand-new, disposable worker thread that\n"
        "never touched lxml itself. Real, if still preliminary, evidence for\n"
        "the mitigation shape: no thread ever does both GDAL and lxml itself;\n"
        "all lxml/schema-validation work funnels through one dedicated,\n"
        "persistent worker thread instead.\n"
        "\n"
        "What v0.30.35 did NOT test: its five rounds were strictly SEQUENTIAL -\n"
        "round N's GDAL thread was created, run, joined, AND had its validation\n"
        "dispatched and returned, all before round N+1's GDAL thread was even\n"
        "created. At no point were two GDAL threads alive at the same\n"
        "wall-clock time, and at no point did more than one thread dispatch to\n"
        "the persistent lxml worker concurrently. The real GUI does not\n"
        "necessarily serialize conversions one full round at a time - a user\n"
        "can plausibly have more than one conversion in flight together.\n"
        "\n"
        "Two probes:\n"
        "  P56  Control - the real, complete convert(), unpatched. Expected\n"
        "       CRASH (matches P54/P51/P48/P45/P41/P36/P27/P17-19).\n"
        "  P57  One batch of 4 GDAL-only worker threads started back-to-back\n"
        "       with no join() between the starts, so their real GDAL writes\n"
        "       genuinely overlap in wall-clock time (validate_schema\n"
        "       neutered process-wide, zero lxml in any of these 4 threads).\n"
        "       The ONE persistent lxml worker thread is created once, before\n"
        "       any of the 4 threads start. As soon as each thread finishes\n"
        "       its OWN GDAL work, it dispatches its own validation job to the\n"
        "       shared persistent worker - via a fresh, per-call response\n"
        "       queue so concurrent dispatches can never cross-talk - and\n"
        "       blocks on its own private response. The persistent worker\n"
        "       still processes jobs one at a time, serializing the actual\n"
        "       lxml calls even under concurrent contention. The log records\n"
        "       the OS thread identity the persistent worker actually ran\n"
        "       under, once per job, so the log itself is evidence a single\n"
        "       thread handled all 4 jobs (or flags this harness as broken if\n"
        "       it did not).\n"
        "\n"
        "This isolates exactly one new variable versus P55: concurrency of the\n"
        "GDAL threads and of the dispatches to the persistent worker.\n"
        "Repetition (multiple such batches back to back) is deliberately NOT\n"
        "combined with it here, so a failure's cause is unambiguous.\n"
        "\n"
        "The concurrent, per-call response-queue dispatch protocol itself was\n"
        "stress-tested standalone before delivery: 1600 concurrent dispatches\n"
        "(200 trials x 8 concurrent callers) against a mock worker, zero\n"
        "cross-talk, single confirmed worker thread throughout.\n"
        "\n"
        "See the script's own module docstring for the full reasoning and the\n"
        "complete 'how to read this' table for every P56/P57 outcome.\n"
        "\n"
        "No code fix to the shipped product is proposed alongside this script -\n"
        "same discipline as every diagnostic before it in this series. This\n"
        "tests whether a pattern is *safe* under one specific new condition\n"
        "(concurrency), which is a prerequisite for a fix, not a fix itself.\n"
        "\n"
        "Usage: place diagnose_crash_v0.30.36.py in the project's dev_tools\\\n"
        "folder (it resolves the project root as its own parent directory),\n"
        "then from an activated 'geopackage' conda environment:\n"
        "\n"
        "    python dev_tools\\diagnose_crash_v0.30.36.py\n"
        "\n"
        "Send back dev_tools\\logs\\diagnose_v0.30.36_<timestamp>.log.\n",
        encoding="utf-8",
    )
    print(f"Wrote:   {version_txt}")

    # 3. Zip the staging folder.
    zip_base = dist_root / f"diagnose_crash_v{DIAGNOSTIC_VERSION}_{timestamp}"
    zip_path = shutil.make_archive(str(zip_base), "zip", root_dir=stage_dir)
    print(f"Zipped:  {zip_path}")

    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
