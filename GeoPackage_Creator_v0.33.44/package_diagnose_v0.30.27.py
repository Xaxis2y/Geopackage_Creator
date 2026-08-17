# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for diagnose_crash_v0.30.27.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a single dev_tools diagnostic script rather than a full release.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside diagnose_crash_v0.30.27.py:

    conda activate geopackage
    cd dev_tools
    python package_diagnose_v0.30.27.py

Produces:
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.27_<timestamp>\\
        diagnose_crash_v0.30.27.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.27_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "diagnose_crash_v0.30.27.py"
DIAGNOSTIC_VERSION = "0.30.27"


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
        "Follow-up to diagnose_crash_v0.30.26.py, which found:\n"
        "sqlite3.threadsafety=3 (not the cause); the real convert() crashes\n"
        "with just 2 threads (P19); every PAIRWISE combination of GDAL,\n"
        "lxml, and sqlite3 survived in isolation (P20/P21/P22 all OK). Only\n"
        "the full three-way combination reproduces it. This version tests a\n"
        "minimal hand-rolled three-way combo (P23: one touch of each) and a\n"
        "repetition-matched variant (P24: three lxml compiles, matching the\n"
        "real pipeline's actual count) to find the true minimal repro. See\n"
        "the script's own module docstring for the full reasoning and how\n"
        "to read the results.\n"
        "\n"
        "Usage: place diagnose_crash_v0.30.27.py in the project's dev_tools\\\n"
        "folder (it resolves the project root as its own parent directory),\n"
        "then from an activated 'geopackage' conda environment:\n"
        "\n"
        "    python dev_tools\\diagnose_crash_v0.30.27.py\n"
        "\n"
        "Send back dev_tools\\logs\\diagnose_v0.30.27_<timestamp>.log.\n",
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
