# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for diagnose_crash_v0.30.29.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a single dev_tools diagnostic script rather than a full release.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside diagnose_crash_v0.30.29.py:

    conda activate geopackage
    cd dev_tools
    python package_diagnose_v0.30.29.py

Produces:
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.29_<timestamp>\\
        diagnose_crash_v0.30.29.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.29_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "diagnose_crash_v0.30.29.py"
DIAGNOSTIC_VERSION = "0.30.29"


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
        "Follow-up to diagnose_crash_v0.30.28.py. v0.30.28's P25/P26 reran the\n"
        "hand-rolled three-way (GDAL + lxml + sqlite3) combination with a\n"
        "STRICT sequential hand-off (thread A fully join()-ed before thread B\n"
        "is even created) and STILL came back OK. That was the third straight\n"
        "round (P13-15, P20-22, P23-26) where a hand-rolled approximation of\n"
        "the real pipeline failed to reproduce a crash that the real,\n"
        "unmodified convert() keeps reproducing (P17/P18/P19). So this version\n"
        "stops approximating: it runs the REAL GeoPackageConverter.convert(),\n"
        "unmodified, and monkey-patches ONE real internal method at a time to\n"
        "a no-op, so every step that still executes is the actual shipped\n"
        "code, never a stand-in for it.\n"
        "\n"
        "Five probes, all real convert(), generate_reports=True, 2 threads,\n"
        "same proven strict sequential hand-off as P25/P26:\n"
        "  P27  Control - no patch at all. Expected CRASH (matches P17/18/19).\n"
        "       If P27 comes back OK, this harness itself is not faithfully\n"
        "       reproducing the crash and P28-P31 cannot be trusted either way.\n"
        "  P28  _embed_metadata patched to a no-op (removes sqlite3 reopen #1).\n"
        "  P29  _finalize_dgiwg_compliance patched to a no-op (removes sqlite3\n"
        "       reopen #2).\n"
        "  P30  MetadataHandler.validate_schema patched to a no-op (removes\n"
        "       every lxml schema compile from the real pipeline).\n"
        "  P31  Both P28's and P29's patches together (GDAL + lxml only, at\n"
        "       real multiplicity, remain).\n"
        "\n"
        "See the script's own module docstring for the full reasoning and the\n"
        "complete 'how to read this' table for every P27-P31 outcome combination.\n"
        "\n"
        "No code fix is proposed alongside this script - same discipline as\n"
        "every diagnostic before it in this series.\n"
        "\n"
        "Usage: place diagnose_crash_v0.30.29.py in the project's dev_tools\\\n"
        "folder (it resolves the project root as its own parent directory),\n"
        "then from an activated 'geopackage' conda environment:\n"
        "\n"
        "    python dev_tools\\diagnose_crash_v0.30.29.py\n"
        "\n"
        "Send back dev_tools\\logs\\diagnose_v0.30.29_<timestamp>.log.\n",
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
