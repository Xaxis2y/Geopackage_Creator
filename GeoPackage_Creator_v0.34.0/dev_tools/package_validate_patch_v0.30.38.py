# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for validate_patch_v0.30.38.py AND its companion
candidate_patch_v0.30.38/core/metadata_handler.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a dev_tools delivery rather than a full release - same convention as
every package_diagnose_vX.py before it in this series.

This is the FIRST packaging script in the whole investigation that bundles a
proposed CODE CHANGE (candidate_patch_v0.30.38/core/metadata_handler.py)
alongside a diagnostic. Every package_diagnose_v0.30.17.py through
package_diagnose_v0.30.37.py packaged pure diagnostics only - nothing that
touched, or proposed touching, the shipped product's own code. See
VERSION.txt (written into the packaged output by this script) for the full
explanation of what changed and why.

To be clear about what this script does NOT do: it does not copy the
candidate patch over the real, shipping core/metadata_handler.py anywhere.
It only copies candidate_patch_v0.30.38/ (a self-contained proposal) and
validate_patch_v0.30.38.py (which tests that proposal against a disposable
temporary copy of the project - see that script's own module docstring) into
a dist/zip bundle for easy archiving. The real core/metadata_handler.py is
never referenced by this script at all.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside validate_patch_v0.30.38.py and
candidate_patch_v0.30.38\\:

    conda activate geopackage
    cd dev_tools
    python package_validate_patch_v0.30.38.py

Produces:
    dev_tools\\diagnostics_dist\\validate_patch_v0.30.38_<timestamp>\\
        validate_patch_v0.30.38.py
        candidate_patch_v0.30.38\\core\\metadata_handler.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\validate_patch_v0.30.38_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "validate_patch_v0.30.38.py"
PATCH_DIR_NAME = "candidate_patch_v0.30.38"
PATCH_RELATIVE_PATH = Path(PATCH_DIR_NAME) / "core" / "metadata_handler.py"
EXPECTED_PATCH_VERSION_LINE = '__version__ = "0.30.24"'
DELIVERY_VERSION = "0.30.38"


def _verify_patch_version(patch_file: Path) -> str:
    """Read back the patch file's __version__ line and confirm it matches
    what this packaging script expects to be bundling. Raises RuntimeError
    on any mismatch rather than silently packaging the wrong file - the
    same discipline validate_patch_v0.30.38.py itself uses when staging its
    own P61 copy."""
    version_line = None
    for line in patch_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            version_line = line.strip()
            break
    if version_line != EXPECTED_PATCH_VERSION_LINE:
        raise RuntimeError(
            f"PACKAGING ABORTED: {patch_file} reports "
            f"{version_line!r}, expected {EXPECTED_PATCH_VERSION_LINE!r}. "
            "Refusing to package a patch file that isn't the version this "
            "script expects - check which copy is sitting in "
            f"{PATCH_DIR_NAME}\\core\\ before re-running."
        )
    return version_line


def main() -> int:
    here = Path(__file__).resolve().parent
    source_script = here / SCRIPT_NAME
    source_patch = here / PATCH_RELATIVE_PATH

    missing = [p for p in (source_script, source_patch) if not p.exists()]
    if missing:
        print("ERROR: required file(s) not found next to this packaging script:")
        for p in missing:
            print(f"  - {p}")
        print()
        print(f"Expected layout, all under dev_tools\\ alongside this script:")
        print(f"  {SCRIPT_NAME}")
        print(f"  {PATCH_RELATIVE_PATH}")
        return 1

    try:
        patch_version_line = _verify_patch_version(source_patch)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1
    print(f"Confirmed patch version: {patch_version_line}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dist_root = here / "diagnostics_dist"
    stage_dir = dist_root / f"validate_patch_v{DELIVERY_VERSION}_{timestamp}"
    stage_dir.mkdir(parents=True, exist_ok=True)

    # 1. Copy the validation script into the staging folder.
    dest_script = stage_dir / SCRIPT_NAME
    shutil.copy2(source_script, dest_script)
    print(f"Copied: {dest_script}")

    # 2. Copy the whole candidate_patch_v0.30.38/ folder (not just the one
    #    file) so the staged bundle is self-contained and matches exactly
    #    what validate_patch_v0.30.38.py expects to find next to it.
    dest_patch_dir = stage_dir / PATCH_DIR_NAME
    shutil.copytree(
        here / PATCH_DIR_NAME, dest_patch_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    print(f"Copied: {dest_patch_dir}")

    # 3. Write a VERSION note (project convention: every packaged artifact
    #    carries a VERSION.txt describing what it is).
    version_txt = stage_dir / "VERSION.txt"
    version_txt.write_text(
        "GeoPackage Creator - candidate patch + validation package\n"
        f"Delivery version   : {DELIVERY_VERSION}\n"
        f"Packaged           : {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"Patch file         : {PATCH_RELATIVE_PATH.as_posix()}\n"
        f"Patch self-reports : {patch_version_line}\n"
        f"Validator          : {SCRIPT_NAME}\n"
        "\n"
        "WHAT THIS IS\n"
        "------------\n"
        "This is the FIRST delivery in this whole crash investigation that\n"
        "includes a proposed CHANGE to shipped code. Every earlier delivery\n"
        "(diagnose_crash_v0.30.17.py through diagnose_crash_v0.30.37.py) was\n"
        "a pure diagnostic - none of them touched, or proposed touching, a\n"
        "single line of the actual product. This one does, but carefully:\n"
        "\n"
        "  candidate_patch_v0.30.38\\core\\metadata_handler.py\n"
        "      A complete, standalone replacement for core\\metadata_handler.py\n"
        "      implementing the persistent-lxml-worker-thread pattern that\n"
        "      four independent diagnostic runs already validated under\n"
        "      monkey-patched conditions (v0.30.34's P52, v0.30.35's P55,\n"
        "      v0.30.36's P57, v0.30.37's P59). This file is NOT yet applied\n"
        "      anywhere - it sits in dev_tools\\ as a candidate. The real,\n"
        "      shipping core\\metadata_handler.py is completely untouched by\n"
        "      this delivery.\n"
        "\n"
        "  validate_patch_v0.30.38.py\n"
        "      Tests the candidate for real: runs the REAL, entirely\n"
        "      unmodified GeoPackageConverter.convert() - no monkey-patching\n"
        "      anywhere, unlike every earlier diagnose_crash_vX.py - through\n"
        "      10 sequential rounds (new thread each round, joined before the\n"
        "      next starts, matching exactly how the shipped GUI can ever\n"
        "      call it). It does this twice:\n"
        "        P60  against the real project exactly as it stands today\n"
        "             (unpatched). Expected CRASH, same as every control\n"
        "             this series has ever run.\n"
        "        P61  against a disposable temporary copy of the whole\n"
        "             project with ONLY core\\metadata_handler.py replaced by\n"
        "             the candidate patch. Expected OK, 10/10 rounds clean.\n"
        "      core\\metadata_handler.py on disk is never modified by running\n"
        "      this script, either way.\n"
        "\n"
        "WHY THE CANDIDATE PATCH SHOULD WORK\n"
        "------------------------------------\n"
        "The crash needs one OS thread to do a real GDAL write AND a real\n"
        "lxml schema-file touch itself, in that order, before a later,\n"
        "different, freshly-created thread's first lxml touch crashes. The\n"
        "patch removes the only way that precondition can occur: instead of\n"
        "each thread touching lxml directly inside MetadataHandler.\n"
        "validate_schema(), every call - from any thread - now dispatches its\n"
        "work to ONE persistent, lazily-started, dedicated worker thread that\n"
        "lives for the rest of the process and never does GDAL work itself.\n"
        "No thread ever does 'GDAL then lxml' itself again; the necessary\n"
        "condition for the crash can no longer occur.\n"
        "\n"
        "WHAT WAS VERIFIED WITHOUT GDAL/WINDOWS (this sandbox)\n"
        "---------------------------------------------------------\n"
        "This sandbox has no GDAL and cannot reproduce the native crash\n"
        "itself - that is exactly what validate_patch_v0.30.38.py's P60/P61\n"
        "are for, and why they must be run on the real machine. What COULD be\n"
        "verified here, using the real lxml library (available in this\n"
        "sandbox) against the project's real bundled XSD schemas and the\n"
        "project's own real, unmodified test suite:\n"
        "\n"
        "  - All 73 of this project's own real tests (tests\\test_metadata_\n"
        "    handler.py + tests\\test_schema_validation.py) pass against the\n"
        "    patched metadata_handler.py.\n"
        "  - The SAME 73 tests were also run, as a control, against the\n"
        "    unpatched original - also 73/73 passed. This confirms the test\n"
        "    harness isn't simply lenient; the patch is being held to the\n"
        "    exact same bar as the code it replaces.\n"
        "  - 20 additional custom checks confirming: the worker thread does\n"
        "    not start until the first validate_schema() call; exact\n"
        "    exception messages are preserved byte-for-byte for both\n"
        "    malformed-XML and schema-invalid-XML cases; the SAME worker\n"
        "    thread identity persists across errors and across multiple\n"
        "    MetadataHandler instances (never silently recreated); and 40\n"
        "    concurrent validate_schema() calls, mixing valid and invalid\n"
        "    cases, each get their own correct result with zero cross-talk\n"
        "    and exactly one worker thread throughout.\n"
        "\n"
        "WHAT STILL NEEDS YOUR MACHINE\n"
        "--------------------------------\n"
        "Everything above proves the patch's dispatch logic works correctly\n"
        "and preserves the exact existing behavioral contract. It does NOT\n"
        "prove the native crash is actually prevented - only a real GDAL\n"
        "write on Windows can trigger the original crash at all, so only\n"
        "your machine can confirm the fix. That is the entire purpose of\n"
        "validate_patch_v0.30.38.py's P60/P61 pair.\n"
        "\n"
        "NOTHING IS APPLIED TO YOUR REAL core\\metadata_handler.py\n"
        "------------------------------------------------------------\n"
        "This delivery only adds new files under dev_tools\\ - it does not\n"
        "modify core\\metadata_handler.py or any other file outside dev_tools\\.\n"
        "Promoting the candidate patch into the real, shipping\n"
        "core\\metadata_handler.py is a separate, deliberate step for later,\n"
        "only after you've run validate_patch_v0.30.38.py and confirmed P61\n"
        "passes 10/10 on your machine.\n"
        "\n"
        "HOW TO RUN\n"
        "----------\n"
        "1. Unzip so you end up with, under dev_tools\\:\n"
        "     dev_tools\\validate_patch_v0.30.38.py\n"
        "     dev_tools\\candidate_patch_v0.30.38\\core\\metadata_handler.py\n"
        "   (if you received these as loose files rather than this zip, they\n"
        "   should already be in place from delivery)\n"
        "2. Anaconda Prompt:\n"
        "     conda activate geopackage\n"
        "     python dev_tools\\validate_patch_v0.30.38.py\n"
        "3. Send back dev_tools\\logs\\validate_patch_v0.30.38_<timestamp>.log\n",
        encoding="utf-8",
    )
    print(f"Wrote:   {version_txt}")

    # 4. Zip the staging folder.
    zip_base = dist_root / f"validate_patch_v{DELIVERY_VERSION}_{timestamp}"
    zip_path = shutil.make_archive(str(zip_base), "zip", root_dir=stage_dir)
    print(f"Zipped:  {zip_path}")

    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
