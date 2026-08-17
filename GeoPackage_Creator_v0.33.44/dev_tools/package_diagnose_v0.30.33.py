# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for diagnose_crash_v0.30.33.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a single dev_tools diagnostic script rather than a full release.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside diagnose_crash_v0.30.33.py:

    conda activate geopackage
    cd dev_tools
    python package_diagnose_v0.30.33.py

Produces:
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.33_<timestamp>\\
        diagnose_crash_v0.30.33.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.33_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "diagnose_crash_v0.30.33.py"
DIAGNOSTIC_VERSION = "0.30.33"


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
        "Follow-up to diagnose_crash_v0.30.32.py. P46/P47 both came back OK,\n"
        "which confirms GDAL is a real, necessary ingredient in this crash -\n"
        "not a coincidental witness. Pure lxml-only activity, across two\n"
        "threads or repeated in one thread, is completely safe. Combined with\n"
        "everything already eliminated (parser choice, document content, the\n"
        "XMLSchema() compile step, thread B needing its own GDAL write), the\n"
        "one thing nobody has tested is WHICH thread needs to touch lxml, and\n"
        "whether GDAL activity needs to be paired with lxml activity in the\n"
        "SAME thread or can be fully independent. Every crash probe so far\n"
        "has had thread A do both GDAL and lxml itself.\n"
        "\n"
        "Three probes:\n"
        "  P48  Control - the real, complete convert(). Expected CRASH\n"
        "       (matches P45/41/36/27/17-19). If P48 comes back OK, this\n"
        "       harness itself is not faithfully reproducing the crash and\n"
        "       P49/P50 cannot be trusted either way.\n"
        "  P49  Thread A: real convert() but validate_schema neutered\n"
        "       process-wide - real GDAL, zero real lxml in thread A.\n"
        "       Thread B: no GDAL at all - one real lxml touch via the saved\n"
        "       original validate_schema. Tests whether thread A needs to\n"
        "       touch lxml itself, or GDAL-anywhere plus a new thread's\n"
        "       first real lxml touch is sufficient alone.\n"
        "  P50  The exact reverse of P49 - thread A does the lxml-only turn,\n"
        "       thread B does the real convert() with lxml neutered. Tests\n"
        "       whether direction/role matters.\n"
        "\n"
        "See the script's own module docstring for the full reasoning and the\n"
        "complete 'how to read this' table for every P48-P50 outcome combination.\n"
        "\n"
        "No code fix is proposed alongside this script - same discipline as\n"
        "every diagnostic before it in this series.\n"
        "\n"
        "Usage: place diagnose_crash_v0.30.33.py in the project's dev_tools\\\n"
        "folder (it resolves the project root as its own parent directory),\n"
        "then from an activated 'geopackage' conda environment:\n"
        "\n"
        "    python dev_tools\\diagnose_crash_v0.30.33.py\n"
        "\n"
        "Send back dev_tools\\logs\\diagnose_v0.30.33_<timestamp>.log.\n",
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
