# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for validate_patch_shutdown_v0.30.39.py AND its two
companion candidate folders, candidate_patch_v0.30.38/core/metadata_handler.py
(P63 - the original, unmodified worker-thread patch) and candidate_patch_
v0.30.39/core/metadata_handler.py (P62 - that same patch plus
shutdown_lxml_worker()).

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), same
convention as package_validate_patch_v0.30.38.py and every package_diagnose_
vX.py before it in this series.

To be clear about what this script does NOT do: it does not copy either
candidate over the real, shipping core/metadata_handler.py anywhere. It only
copies the two candidate_patch_vX.30.3{8,9}/ folders (self-contained
proposals) and validate_patch_shutdown_v0.30.39.py (which tests them against
disposable temporary copies of the project - see that script's own module
docstring) into a dist/zip bundle for easy archiving. The real
core/metadata_handler.py is never referenced by this script at all.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside validate_patch_shutdown_v0.30.39.py,
candidate_patch_v0.30.38\\, and candidate_patch_v0.30.39\\:

    conda activate geopackage
    cd dev_tools
    python package_validate_patch_shutdown_v0.30.39.py

Produces:
    dev_tools\\diagnostics_dist\\validate_patch_shutdown_v0.30.39_<timestamp>\\
        validate_patch_shutdown_v0.30.39.py
        candidate_patch_v0.30.38\\core\\metadata_handler.py
        candidate_patch_v0.30.39\\core\\metadata_handler.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\validate_patch_shutdown_v0.30.39_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "validate_patch_shutdown_v0.30.39.py"
DELIVERY_VERSION = "0.30.39"

# (folder name, relative path to metadata_handler.py, expected __version__ line)
PATCH_DIRS = [
    (
        "candidate_patch_v0.30.38",
        Path("candidate_patch_v0.30.38") / "core" / "metadata_handler.py",
        '__version__ = "0.30.24"',
    ),
    (
        "candidate_patch_v0.30.39",
        Path("candidate_patch_v0.30.39") / "core" / "metadata_handler.py",
        '__version__ = "0.30.25"',
    ),
]


def _verify_patch_version(patch_file: Path, expected_version_line: str) -> str:
    """Read back a patch file's __version__ line and confirm it matches what
    this packaging script expects to be bundling. Raises RuntimeError on any
    mismatch rather than silently packaging the wrong file - the same
    discipline validate_patch_shutdown_v0.30.39.py itself uses when staging
    its own P62/P63 copies."""
    version_line = None
    for line in patch_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            version_line = line.strip()
            break
    if version_line != expected_version_line:
        raise RuntimeError(
            f"PACKAGING ABORTED: {patch_file} reports "
            f"{version_line!r}, expected {expected_version_line!r}. "
            "Refusing to package a patch file that isn't the version this "
            f"script expects - check what is sitting in {patch_file.parent} "
            "before re-running."
        )
    return version_line


def main() -> int:
    here = Path(__file__).resolve().parent
    source_script = here / SCRIPT_NAME

    missing = [source_script] if not source_script.exists() else []
    for _, rel_path, _ in PATCH_DIRS:
        p = here / rel_path
        if not p.exists():
            missing.append(p)
    if missing:
        print("ERROR: required file(s) not found next to this packaging script:")
        for p in missing:
            print(f"  - {p}")
        print()
        print("Expected layout, all under dev_tools\\ alongside this script:")
        print(f"  {SCRIPT_NAME}")
        for _, rel_path, _ in PATCH_DIRS:
            print(f"  {rel_path}")
        return 1

    version_lines = {}
    try:
        for dir_name, rel_path, expected in PATCH_DIRS:
            version_lines[dir_name] = _verify_patch_version(here / rel_path, expected)
            print(f"Confirmed {dir_name} version: {version_lines[dir_name]}")
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dist_root = here / "diagnostics_dist"
    stage_dir = dist_root / f"validate_patch_shutdown_v{DELIVERY_VERSION}_{timestamp}"
    stage_dir.mkdir(parents=True, exist_ok=True)

    # 1. Copy the isolation script into the staging folder.
    dest_script = stage_dir / SCRIPT_NAME
    shutil.copy2(source_script, dest_script)
    print(f"Copied: {dest_script}")

    # 2. Copy both whole candidate_patch_vX/ folders (not just the one file
    #    each) so the staged bundle is self-contained and matches exactly
    #    what validate_patch_shutdown_v0.30.39.py expects to find next to it.
    for dir_name, _, _ in PATCH_DIRS:
        dest_patch_dir = stage_dir / dir_name
        shutil.copytree(
            here / dir_name, dest_patch_dir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        print(f"Copied: {dest_patch_dir}")

    # 3. Write a VERSION note (project convention: every packaged artifact
    #    carries a VERSION.txt describing what it is).
    version_txt = stage_dir / "VERSION.txt"
    version_txt.write_text(
        "GeoPackage Creator - shutdown-crash isolation package\n"
        f"Delivery version   : {DELIVERY_VERSION}\n"
        f"Packaged           : {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"Isolation script   : {SCRIPT_NAME}\n"
        f"candidate_patch_v0.30.38 reports: {version_lines['candidate_patch_v0.30.38']}\n"
        f"candidate_patch_v0.30.39 reports: {version_lines['candidate_patch_v0.30.39']}\n"
        "\n"
        "WHAT THIS IS\n"
        "------------\n"
        "A follow-up to the validate_patch_v0.30.38 delivery. That delivery's\n"
        "P60/P61 run (dev_tools\\logs\\validate_patch_v0.30.38_20260817_105747.log)\n"
        "showed the ORIGINAL crash this whole series has chased appears fixed -\n"
        "P61 completed all 10 rounds of the exact reproducing pattern with zero\n"
        "crashes - but the process then crashed with the SAME access-violation\n"
        "code anyway, AFTER that work finished, during interpreter shutdown.\n"
        "That is a second, different failure from the one every P17-P60 control\n"
        "reproduces (which all crash mid-pattern, not after it).\n"
        "\n"
        "This package isolates why:\n"
        "\n"
        "  candidate_patch_v0.30.38\\core\\metadata_handler.py\n"
        "      UNCHANGED from the previous delivery - the original worker-\n"
        "      thread patch, no shutdown mechanism. Used by P63.\n"
        "\n"
        "  candidate_patch_v0.30.39\\core\\metadata_handler.py\n"
        "      The SAME patch, plus exactly one addition: shutdown_lxml_\n"
        "      worker(), which stops and joins the persistent worker thread\n"
        "      on request. Nothing about when or how the thread STARTS\n"
        "      changes. Used by P62.\n"
        "\n"
        "  validate_patch_shutdown_v0.30.39.py\n"
        "      Runs the SAME 10-round real-conversion test P61 already ran,\n"
        "      twice more:\n"
        "        P62  against candidate_patch_v0.30.39, then explicitly\n"
        "             calls shutdown_lxml_worker() before a normal exit.\n"
        "             Expected OK if joining the thread avoids the crash.\n"
        "        P63  against the ORIGINAL candidate_patch_v0.30.38\n"
        "             (unmodified), but calls os._exit(0) instead of a\n"
        "             normal exit, bypassing Python's own finalization\n"
        "             while leaving the un-joined daemon thread exactly as\n"
        "             it always is. Expected OK if skipping normal\n"
        "             finalization - with no other change - also avoids it.\n"
        "      core\\metadata_handler.py on disk is never modified by running\n"
        "      this script, either way. P60 is not re-run - see this script's\n"
        "      own module docstring for why, and what to do if that control\n"
        "      is no longer fresh.\n"
        "\n"
        "WHAT WAS VERIFIED WITHOUT GDAL/WINDOWS (this sandbox)\n"
        "---------------------------------------------------------\n"
        "This sandbox has no GDAL and cannot reproduce the native crash itself\n"
        "- that is exactly what P62/P63 are for, and why they must run on the\n"
        "real machine. What COULD be verified here, using the real lxml\n"
        "library against candidate_patch_v0.30.39\\core\\metadata_handler.py\n"
        "directly (copied byte-for-byte into a minimal test package, not a\n"
        "re-implementation):\n"
        "\n"
        "  - The worker thread does not start until first use, and shutdown_\n"
        "    lxml_worker() is a safe no-op when called before that.\n"
        "  - A real validate_schema() call starts the worker; shutdown_lxml_\n"
        "    worker() stops it and the underlying thread object is confirmed\n"
        "    no longer alive afterward.\n"
        "  - Calling shutdown_lxml_worker() a second time in a row is\n"
        "    idempotent - returns promptly, does not hang or error.\n"
        "  - After a shutdown, the next validate_schema() call transparently\n"
        "    starts a genuinely NEW thread object (confirmed by identity, not\n"
        "    just by is_alive()) and works correctly.\n"
        "  - 40 concurrent validate_schema() calls, made after a prior\n"
        "    shutdown/restart cycle, all return the correct result with\n"
        "    exactly one worker thread identity throughout, followed by a\n"
        "    clean final shutdown.\n"
        "\n"
        "This proves the shutdown/sentinel control flow itself is sound. It\n"
        "does NOT prove the native crash is avoided - only P62/P63, on your\n"
        "machine, can show that.\n"
        "\n"
        "NOTHING IS APPLIED TO YOUR REAL core\\metadata_handler.py\n"
        "------------------------------------------------------------\n"
        "This delivery only adds new files under dev_tools\\ - it does not\n"
        "modify core\\metadata_handler.py or any other file outside dev_tools\\.\n"
        "\n"
        "HOW TO RUN\n"
        "----------\n"
        "1. Unzip so you end up with, under dev_tools\\:\n"
        "     dev_tools\\validate_patch_shutdown_v0.30.39.py\n"
        "     dev_tools\\candidate_patch_v0.30.38\\core\\metadata_handler.py\n"
        "     dev_tools\\candidate_patch_v0.30.39\\core\\metadata_handler.py\n"
        "   (if you received these as loose files rather than this zip, they\n"
        "   should already be in place from delivery)\n"
        "2. Anaconda Prompt:\n"
        "     conda activate geopackage\n"
        "     python dev_tools\\validate_patch_shutdown_v0.30.39.py\n"
        "3. Send back dev_tools\\logs\\validate_patch_shutdown_v0.30.39_<timestamp>.log\n",
        encoding="utf-8",
    )
    print(f"Wrote:   {version_txt}")

    # 4. Zip the staging folder.
    zip_base = dist_root / f"validate_patch_shutdown_v{DELIVERY_VERSION}_{timestamp}"
    zip_path = shutil.make_archive(str(zip_base), "zip", root_dir=stage_dir)
    print(f"Zipped:  {zip_path}")

    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
