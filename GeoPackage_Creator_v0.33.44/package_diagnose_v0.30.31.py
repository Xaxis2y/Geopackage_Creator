# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for diagnose_crash_v0.30.31.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a single dev_tools diagnostic script rather than a full release.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside diagnose_crash_v0.30.31.py:

    conda activate geopackage
    cd dev_tools
    python package_diagnose_v0.30.31.py

Produces:
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.31_<timestamp>\\
        diagnose_crash_v0.30.31.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.31_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "diagnose_crash_v0.30.31.py"
DIAGNOSTIC_VERSION = "0.30.31"


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
        "Follow-up to diagnose_crash_v0.30.30.py. All five of v0.30.30's\n"
        "probes crashed, which ruled out three of four open hypotheses in one\n"
        "run: thread B's own GDAL write is not necessary (P37 CRASH - a\n"
        "brand-new OS thread's first real lxml touch crashes with zero GDAL\n"
        "calls in that thread), the fault lives entirely inside\n"
        "_compile_schema_fresh() before any document is ever touched (P38\n"
        "CRASH), and real document content/size does not matter (P40 CRASH -\n"
        "even a trivial '<x/>' crashes through the real pipeline). That\n"
        "leaves exactly one untested difference between v0.30.28's hand-rolled\n"
        "P26 (OK) and the real, shipped _compile_schema_fresh() (CRASHES): the\n"
        "real code builds a brand-new, hardened etree.XMLParser(no_network=\n"
        "True, resolve_entities=False, huge_tree=False) on every call; P26\n"
        "used lxml's implicit default parser and never built one at all.\n"
        "\n"
        "Four probes, all shaped like v0.30.30's P38 (validate_schema patched\n"
        "to touch only what's under test, then return immediately - never\n"
        "reaching etree.fromstring() or .validate() on any document), through\n"
        "the real convert(), real thread, real lock, real per-call\n"
        "fresh-and-discard schema lifetime:\n"
        "  P41  Control - no patch at all. Expected CRASH (matches P36/27/17-19).\n"
        "       If P41 comes back OK, this harness itself is not faithfully\n"
        "       reproducing the crash and P42-P44 cannot be trusted either way.\n"
        "  P42  Schema-file parse uses NO explicit parser (lxml's implicit\n"
        "       default, exactly matching P26) instead of\n"
        "       _build_hardened_parser(). If OK, this is the answer.\n"
        "  P43  Same as P42, but with a freshly-constructed etree.XMLParser()\n"
        "       carrying none of the hardening options, instead of omitting\n"
        "       the parser argument entirely. Only meaningful vs. P42.\n"
        "  P44  Keeps the real hardened parser and the real cross-file\n"
        "       gco/gml import resolution, but never calls etree.XMLSchema()\n"
        "       at all - isolates parse from compile.\n"
        "\n"
        "See the script's own module docstring for the full reasoning and the\n"
        "complete 'how to read this' table for every P41-P44 outcome combination.\n"
        "\n"
        "No code fix is proposed alongside this script - same discipline as\n"
        "every diagnostic before it in this series.\n"
        "\n"
        "Usage: place diagnose_crash_v0.30.31.py in the project's dev_tools\\\n"
        "folder (it resolves the project root as its own parent directory),\n"
        "then from an activated 'geopackage' conda environment:\n"
        "\n"
        "    python dev_tools\\diagnose_crash_v0.30.31.py\n"
        "\n"
        "Send back dev_tools\\logs\\diagnose_v0.30.31_<timestamp>.log.\n",
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
