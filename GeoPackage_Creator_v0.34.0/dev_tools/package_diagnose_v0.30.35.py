# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for diagnose_crash_v0.30.35.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a single dev_tools diagnostic script rather than a full release.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside diagnose_crash_v0.30.35.py:

    conda activate geopackage
    cd dev_tools
    python package_diagnose_v0.30.35.py

Produces:
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.35_<timestamp>\\
        diagnose_crash_v0.30.35.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.35_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "diagnose_crash_v0.30.35.py"
DIAGNOSTIC_VERSION = "0.30.35"


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
        "Follow-up to diagnose_crash_v0.30.34.py. v0.30.34 came back clean on\n"
        "both corrected probes:\n"
        "\n"
        "  CRASH  P51_control_no_patch\n"
        "  OK     P52_thread_a_gdal_only_thread_b_real_lxml\n"
        "  OK     P53_thread_a_real_lxml_thread_b_gdal_only\n"
        "\n"
        "Per this series' own reading guide, 'P51 CRASH, P52 OK' means thread A\n"
        "needs to touch BOTH GDAL and lxml itself for the hazard to exist - now\n"
        "confirmed. P53 adds the mirror image: a new thread's first real GDAL\n"
        "write, with zero lxml in that thread, is safe too, regardless of what\n"
        "an earlier thread did. Read against every result gathered since\n"
        "v0.30.30, the necessary condition is pinned down precisely for the\n"
        "first time in this whole series: ONE thread must do a real GDAL write\n"
        "followed by a real lxml schema-file touch ITSELF, in that order, in\n"
        "that same thread. Only THEN does a later, different, freshly-created\n"
        "OS thread's first real lxml touch crash. Split GDAL and lxml across\n"
        "two threads that each do only one, in either order, and nothing\n"
        "crashes at all.\n"
        "\n"
        "That is the first point in the investigation where the evidence points\n"
        "at a concrete, testable MITIGATION PATTERN, not just another\n"
        "bisection: if every conversion's GDAL write stays on its own worker\n"
        "thread (as today), but EVERY lxml/schema-validation call in the whole\n"
        "process is routed to one single, persistent worker thread - created\n"
        "once and reused for the life of the program, never recreated - then no\n"
        "thread would ever do 'GDAL then lxml itself', and no new thread would\n"
        "ever be the one making its first lxml touch right after such a thread.\n"
        "P52 already shows this is safe for ONE round. It has never been tested\n"
        "across MANY rounds, which is what the shipped GUI actually does over a\n"
        "real session.\n"
        "\n"
        "Two probes:\n"
        "  P54  Control - the real, complete convert(), unpatched. Expected\n"
        "       CRASH (matches P51/P48/P45/P41/P36/P27/P17-19).\n"
        "  P55  Five rounds. Each round: a brand-new OS thread runs the real,\n"
        "       complete convert() with validate_schema neutered (real GDAL,\n"
        "       zero lxml in that thread - identical shape to P52/P53's\n"
        "       GDAL-only job), joined to completion. Its metadata validation\n"
        "       is then dispatched over a queue to ONE persistent lxml worker\n"
        "       thread - created once, before round 0, and reused for every\n"
        "       round - which calls the real, original validate_schema. No\n"
        "       thread in this probe ever does both GDAL and lxml itself.\n"
        "\n"
        "If P55 completes all 5 rounds with zero crashes, that is real evidence\n"
        "the 'one persistent, dedicated lxml thread' pattern holds up under\n"
        "repetition, not just once. If it fails partway through, the round\n"
        "number it failed on matters - round 0 failing would contradict P52\n"
        "outright; a later round failing would mean something accumulates over\n"
        "repeated use that a single clean round did not reveal.\n"
        "\n"
        "See the script's own module docstring for the full reasoning and the\n"
        "complete 'how to read this' table for every P54/P55 outcome.\n"
        "\n"
        "No code fix to the shipped product is proposed alongside this script -\n"
        "same discipline as every diagnostic before it in this series. This\n"
        "tests whether a pattern is *safe*, which is a prerequisite for a fix,\n"
        "not a fix itself.\n"
        "\n"
        "Usage: place diagnose_crash_v0.30.35.py in the project's dev_tools\\\n"
        "folder (it resolves the project root as its own parent directory),\n"
        "then from an activated 'geopackage' conda environment:\n"
        "\n"
        "    python dev_tools\\diagnose_crash_v0.30.35.py\n"
        "\n"
        "Send back dev_tools\\logs\\diagnose_v0.30.35_<timestamp>.log.\n",
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
