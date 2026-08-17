# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for diagnose_crash_v0.30.32.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a single dev_tools diagnostic script rather than a full release.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside diagnose_crash_v0.30.32.py:

    conda activate geopackage
    cd dev_tools
    python package_diagnose_v0.30.32.py

Produces:
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.32_<timestamp>\\
        diagnose_crash_v0.30.32.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.32_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "diagnose_crash_v0.30.32.py"
DIAGNOSTIC_VERSION = "0.30.32"


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
        "Follow-up to diagnose_crash_v0.30.31.py. All four of v0.30.31's\n"
        "probes crashed, which refutes the parser theory: dropping the custom\n"
        "hardened etree.XMLParser entirely (P42), or using a fresh but\n"
        "option-less one (P43), still crashed - matching P26's own parser\n"
        "usage exactly and it STILL wasn't the explanation. P44 added a real\n"
        "new fact: it never calls etree.XMLSchema() at all and still crashes,\n"
        "so parsing the schema file alone (real cross-file gco/gml imports,\n"
        "any parser) is already sufficient - the XMLSchema() compile step\n"
        "is not required.\n"
        "\n"
        "That leaves one thing nobody in this entire series has actually\n"
        "tested: whether GDAL needs to be involved AT ALL. Every probe so\n"
        "far - including this project's original v0.30.11/12\n"
        "'gdal_then_schema' finding that started this whole investigation -\n"
        "has kept at least one thread doing real GDAL work somewhere before\n"
        "the crash. Nobody has run two threads that only ever touch lxml,\n"
        "never GDAL, anywhere in the process.\n"
        "\n"
        "Three probes:\n"
        "  P45  Control - the real, complete convert(). Expected CRASH\n"
        "       (matches P41/36/27/17-19). If P45 comes back OK, this\n"
        "       harness itself is not faithfully reproducing the crash and\n"
        "       P46/P47 cannot be trusted either way.\n"
        "  P46  NEITHER thread touches GDAL/OGR/GeoPackageConverter at all -\n"
        "       both threads only build a real metadata document and\n"
        "       validate it. If this still crashes, GDAL was never a\n"
        "       required ingredient in this whole investigation - only ever\n"
        "       a coincidental witness.\n"
        "  P47  The same lxml-only work as P46, but both turns run in the\n"
        "       SAME thread - no second OS thread is ever created. Confirms\n"
        "       (or refutes) whether a genuinely new OS thread is what's\n"
        "       actually required.\n"
        "\n"
        "See the script's own module docstring for the full reasoning and the\n"
        "complete 'how to read this' table for every P45-P47 outcome combination.\n"
        "\n"
        "No code fix is proposed alongside this script - same discipline as\n"
        "every diagnostic before it in this series.\n"
        "\n"
        "Usage: place diagnose_crash_v0.30.32.py in the project's dev_tools\\\n"
        "folder (it resolves the project root as its own parent directory),\n"
        "then from an activated 'geopackage' conda environment:\n"
        "\n"
        "    python dev_tools\\diagnose_crash_v0.30.32.py\n"
        "\n"
        "Send back dev_tools\\logs\\diagnose_v0.30.32_<timestamp>.log.\n",
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
