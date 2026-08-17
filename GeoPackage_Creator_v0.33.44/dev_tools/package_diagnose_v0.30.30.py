# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for diagnose_crash_v0.30.30.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a single dev_tools diagnostic script rather than a full release.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside diagnose_crash_v0.30.30.py:

    conda activate geopackage
    cd dev_tools
    python package_diagnose_v0.30.30.py

Produces:
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.30_<timestamp>\\
        diagnose_crash_v0.30.30.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.30_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "diagnose_crash_v0.30.30.py"
DIAGNOSTIC_VERSION = "0.30.30"


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
        "Follow-up to diagnose_crash_v0.30.29.py. v0.30.29 bisected the real,\n"
        "unmodified convert() (not a hand-rolled approximation) and found the\n"
        "first clean result in the whole series: removing MetadataHandler.\n"
        "validate_schema (real lxml schema validation) stops the crash (P30\n"
        "OK); removing either or both sqlite3 reopens does not (P28/P29/P31\n"
        "all still CRASH). That leaves two things unexplained: (1) the real\n"
        "pipeline already compiles each schema fresh and discards it\n"
        "immediately, the exact pattern v0.30.22/v0.30.23 proved safe within a\n"
        "single thread - so does this crash need a genuinely NEW OS thread's\n"
        "first-ever libxml2 touch specifically, independent of that thread\n"
        "doing its own GDAL write? and (2) v0.30.28's hand-rolled P26 used the\n"
        "real schema FILE but only ever validated a trivial '<x/>' document,\n"
        "never the real multi-hundred-line metadata the real pipeline actually\n"
        "validates - does real document content matter?\n"
        "\n"
        "Five probes, all through the real GeoPackageConverter.convert() (P37\n"
        "partially - see below), generate_reports=True, strict sequential\n"
        "hand-off (thread A join()-ed to completion before thread B is even\n"
        "created):\n"
        "  P36  Control - no patch at all. Expected CRASH (matches P27/17/18/19).\n"
        "       If P36 comes back OK, this harness itself is not faithfully\n"
        "       reproducing the crash and P37-P40 cannot be trusted either way.\n"
        "  P37  Thread A: real, complete convert(). Thread B: NO GDAL call at\n"
        "       all - only a real generate_package_metadata() + a real\n"
        "       validate_schema() call. Isolates whether thread B's own GDAL\n"
        "       write is necessary, or any new OS thread's first real lxml\n"
        "       touch is sufficient alone.\n"
        "  P38  validate_schema patched to do the real fresh schema compile,\n"
        "       then return immediately - never parses or validates a\n"
        "       document. Tests whether compilation alone is sufficient.\n"
        "  P39  validate_schema patched to do the real compile AND the real\n"
        "       document parse, but never calls schema.validate(doc). Only\n"
        "       meaningful if P38 is OK.\n"
        "  P40  validate_schema runs 100% real, but the document it validates\n"
        "       is swapped for a trivial '<x/>' - reproducing P26's untested\n"
        "       variable (real document content) inside the real pipeline.\n"
        "\n"
        "See the script's own module docstring for the full reasoning and the\n"
        "complete 'how to read this' table for every P36-P40 outcome combination.\n"
        "\n"
        "No code fix is proposed alongside this script - same discipline as\n"
        "every diagnostic before it in this series.\n"
        "\n"
        "Usage: place diagnose_crash_v0.30.30.py in the project's dev_tools\\\n"
        "folder (it resolves the project root as its own parent directory),\n"
        "then from an activated 'geopackage' conda environment:\n"
        "\n"
        "    python dev_tools\\diagnose_crash_v0.30.30.py\n"
        "\n"
        "Send back dev_tools\\logs\\diagnose_v0.30.30_<timestamp>.log.\n",
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
