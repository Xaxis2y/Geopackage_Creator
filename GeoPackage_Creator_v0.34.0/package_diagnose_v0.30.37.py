# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for diagnose_crash_v0.30.37.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a single dev_tools diagnostic script rather than a full release.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside diagnose_crash_v0.30.37.py:

    conda activate geopackage
    cd dev_tools
    python package_diagnose_v0.30.37.py

Produces:
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.37_<timestamp>\\
        diagnose_crash_v0.30.37.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.37_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "diagnose_crash_v0.30.37.py"
DIAGNOSTIC_VERSION = "0.30.37"


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
        "Follow-up to diagnose_crash_v0.30.36.py. v0.30.36 came back clean:\n"
        "\n"
        "  CRASH  P56_control_no_patch\n"
        "  OK     P57_persistent_lxml_thread_concurrent_batch\n"
        "\n"
        "4 GDAL-only worker threads, started back-to-back with real GDAL\n"
        "writes genuinely overlapping in time, all dispatched to the one\n"
        "persistent lxml worker thread - zero crashes, and the log proved a\n"
        "single OS thread ident handled all 4 jobs. Combined with v0.30.35\n"
        "(5/5 sequential rounds clean), the mitigation pattern now has two\n"
        "SEPARATE clean confirmations: survives repeated sequential use, and\n"
        "survives one genuinely concurrent batch. Neither script combined the\n"
        "two - v0.30.35 was never concurrent, v0.30.36 was never repeated.\n"
        "\n"
        "That gap matters because a real session looks like neither in\n"
        "isolation - many batches of possibly-concurrent conversions over\n"
        "time, all sharing the same one persistent lxml thread for the life\n"
        "of the program. Interaction effects can surprise you even when each\n"
        "contributing dimension is independently safe.\n"
        "\n"
        "Two probes:\n"
        "  P58  Control - the real, complete convert(), unpatched. Expected\n"
        "       CRASH (matches P56/P54/P51/P48/P45/P41/P36/P27/P17-19).\n"
        "  P59  3 batches, run one after another (each batch, including all\n"
        "       its validation, fully finishes before the next batch starts -\n"
        "       P55's repeated dimension). WITHIN each batch, 4 GDAL-only\n"
        "       worker threads start back-to-back with no join between\n"
        "       starts, so their real GDAL writes genuinely overlap (P57's\n"
        "       concurrent dimension). All 12 total conversions (3 x 4) have\n"
        "       their validation dispatched - via the same per-call fresh\n"
        "       response-queue protocol as P57 - to the SAME ONE persistent\n"
        "       lxml worker thread, created once before batch 0 and never\n"
        "       recreated for the rest of the probe's life. The log records\n"
        "       the persistent worker's OS thread identity on every one of\n"
        "       the 12 jobs, proving whether it stayed the same single thread\n"
        "       across all three batches.\n"
        "\n"
        "If P59 completes all 3 batches (12/12 jobs) under one confirmed\n"
        "thread identity with zero crashes, that is the strongest evidence yet\n"
        "for the mitigation shape under realistic, sustained, multi-file GUI\n"
        "usage. A failure on batch 0 would contradict P57 outright (batch 0\n"
        "here is identical in shape); a failure on a later batch would point\n"
        "at an interaction effect that neither P55 nor P57 could reveal alone.\n"
        "\n"
        "Both new pieces of logic (repeated batches feeding one persistent\n"
        "thread; early-break-on-error between batches) were stress-tested\n"
        "standalone with mocks before delivery - 3 clean batches x 4 workers\n"
        "with zero cross-talk and a single confirmed thread identity, plus a\n"
        "fault-injection case confirming a batch-1 error correctly prevents\n"
        "batch 2 from ever starting.\n"
        "\n"
        "See the script's own module docstring for the full reasoning and the\n"
        "complete 'how to read this' table for every P58/P59 outcome.\n"
        "\n"
        "No code fix to the shipped product is proposed alongside this script -\n"
        "same discipline as every diagnostic before it in this series. This\n"
        "tests whether a pattern is *safe* when its two previously-isolated\n"
        "dimensions are combined, which is a prerequisite for a fix, not a fix\n"
        "itself.\n"
        "\n"
        "Usage: place diagnose_crash_v0.30.37.py in the project's dev_tools\\\n"
        "folder (it resolves the project root as its own parent directory),\n"
        "then from an activated 'geopackage' conda environment:\n"
        "\n"
        "    python dev_tools\\diagnose_crash_v0.30.37.py\n"
        "\n"
        "Send back dev_tools\\logs\\diagnose_v0.30.37_<timestamp>.log.\n",
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
