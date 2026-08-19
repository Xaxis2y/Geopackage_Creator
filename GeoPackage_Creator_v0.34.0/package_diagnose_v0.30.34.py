# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for diagnose_crash_v0.30.34.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a single dev_tools diagnostic script rather than a full release.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside diagnose_crash_v0.30.34.py:

    conda activate geopackage
    cd dev_tools
    python package_diagnose_v0.30.34.py

Produces:
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.34_<timestamp>\\
        diagnose_crash_v0.30.34.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.34_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "diagnose_crash_v0.30.34.py"
DIAGNOSTIC_VERSION = "0.30.34"


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
        "Bug-fix release for diagnose_crash_v0.30.33.py's OWN harness, not a\n"
        "new hypothesis. v0.30.33's P49/P50 both showed 'CRASH' in the\n"
        "SUMMARY block, but the detail lines above it showed exit code 1 with\n"
        "an ordinary ValueError ('ISO 19115 schema validation failed') - a\n"
        "trivial '<x/>' document correctly REJECTED by real schema\n"
        "validation, not a native crash. Two bugs caused this: (1)\n"
        "lxml_only_turn_real() called validate_schema directly and\n"
        "unwrapped, bypassing the tolerance every real call site in the\n"
        "shipped pipeline already has for this exact, expected exception; and\n"
        "(2) the SUMMARY block collapsed 'FAIL' (an ordinary exception) into\n"
        "the same 'CRASH' label as a genuine native fault, because\n"
        "run_probe() only ever returned a bare bool. P50 was worse than just\n"
        "mislabeled - thread A's expected rejection was treated as fatal, so\n"
        "thread B (the entire point of that probe) never even ran.\n"
        "\n"
        "Both bugs are fixed here. Neither changes any conclusion already\n"
        "drawn through v0.30.32 (every earlier probe exited either cleanly or\n"
        "with a genuine native fault code, never an ordinary exception, so\n"
        "none of them were mis-tagged) - this is purely a harness fix,\n"
        "verified against 4 behavioral test cases (expected ValueError, no\n"
        "exception, an unrelated ValueError, and an unrelated exception type)\n"
        "before being sent over.\n"
        "\n"
        "Three probes, matching v0.30.33's original intent exactly, under new\n"
        "numbers per this series' own convention for a corrected re-run (see\n"
        "v0.30.28's P25/P26 vs v0.30.27's P23/P24):\n"
        "  P51  Control - the real, complete convert(). Expected CRASH\n"
        "       (matches P48/45/41/36/27/17-19).\n"
        "  P52  Corrected P49 - thread A: real convert(), lxml neutered\n"
        "       process-wide (real GDAL, zero real lxml). Thread B: one real\n"
        "       lxml touch, no GDAL, now correctly tolerating the expected\n"
        "       schema-rejection ValueError.\n"
        "  P53  Corrected P50, the exact reverse of P52.\n"
        "\n"
        "See the script's own module docstring for the full reasoning and the\n"
        "complete 'how to read this' table for every P51-P53 outcome combination.\n"
        "\n"
        "No code fix to the shipped product is proposed alongside this script -\n"
        "same discipline as every diagnostic before it in this series. The two\n"
        "fixes described above are to this dev_tools harness only.\n"
        "\n"
        "Usage: place diagnose_crash_v0.30.34.py in the project's dev_tools\\\n"
        "folder (it resolves the project root as its own parent directory),\n"
        "then from an activated 'geopackage' conda environment:\n"
        "\n"
        "    python dev_tools\\diagnose_crash_v0.30.34.py\n"
        "\n"
        "Send back dev_tools\\logs\\diagnose_v0.30.34_<timestamp>.log.\n",
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
