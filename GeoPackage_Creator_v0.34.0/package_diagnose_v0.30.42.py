# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for diagnose_crash_v0.30.42.py AND its required
companion candidate_patch_v0.30.39/core/metadata_handler.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a dev_tools delivery - same convention as every package_diagnose_vX.py
before it. Same shape as package_diagnose_v0.30.41.py: every probe in
diagnose_crash_v0.30.42.py exercises the REAL candidate module, so
candidate_patch_v0.30.39/ is REQUIRED, not optional - packaging aborts if it
is missing or reports the wrong version.

To be clear about what this script does NOT do: it does not copy any
candidate over the real, shipping core/metadata_handler.py anywhere, and it
does not modify candidate_patch_v0.30.39/ itself - only reads it. Nothing
outside dev_tools\\ is touched by this script.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside diagnose_crash_v0.30.42.py and
candidate_patch_v0.30.39\\ (already there from an earlier delivery):

    conda activate geopackage
    cd dev_tools
    python package_diagnose_v0.30.42.py

Produces:
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.42_<timestamp>\\
        diagnose_crash_v0.30.42.py
        candidate_patch_v0.30.39\\core\\metadata_handler.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.42_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "diagnose_crash_v0.30.42.py"
DIAGNOSTIC_VERSION = "0.30.42"
PATCH_DIR_NAME = "candidate_patch_v0.30.39"
PATCH_RELATIVE_PATH = Path(PATCH_DIR_NAME) / "core" / "metadata_handler.py"
EXPECTED_PATCH_VERSION_LINE = '__version__ = "0.30.25"'


def _verify_patch_version(patch_file: Path) -> str:
    """Read back the candidate's __version__ line and confirm it matches
    what diagnose_crash_v0.30.42.py's probes expect. Raises RuntimeError on
    any mismatch - same discipline as every packaging script before it that
    bundles a required dependency."""
    version_line = None
    for line in patch_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            version_line = line.strip()
            break
    if version_line != EXPECTED_PATCH_VERSION_LINE:
        raise RuntimeError(
            f"PACKAGING ABORTED: {patch_file} reports "
            f"{version_line!r}, expected {EXPECTED_PATCH_VERSION_LINE!r}. "
            "Refusing to package a candidate_patch_v0.30.39 folder that "
            "isn't the version diagnose_crash_v0.30.42.py's probes expect - "
            f"check which copy is sitting in {PATCH_DIR_NAME}\\core\\ "
            "before re-running."
        )
    return version_line


def _build_version_txt(patch_version_line: str) -> str:
    """Builds the VERSION.txt contents as one string."""
    return (
        "GeoPackage Creator - crash diagnostic package\n"
        f"Diagnostic version : {DIAGNOSTIC_VERSION}\n"
        f"Packaged           : {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"Script             : {SCRIPT_NAME}\n"
        f"candidate_patch_v0.30.39 (required by every probe): Bundled ({patch_version_line})\n"
        "\n"
        "WHAT THIS FOLLOWS UP ON\n"
        "------------------------\n"
        "dev_tools\\logs\\diagnose_v0.30.41_20260817_121441.log, run on the\n"
        "target machine on 2026-08-17: P67R (control rerun), P68 (round-thread\n"
        "dispatch, matching the real pipeline's shape), and P69 (worker pre-\n"
        "warmed before any GDAL activity) ALL crashed - fast, P69 fastest of\n"
        "all (round 0). Neither dispatch-thread identity nor worker-creation\n"
        "timing explains why validate_patch_v0.30.38.py's P61 (the real,\n"
        "unmonkeypatched pipeline) survived 10/10 rounds using the same real\n"
        "worker.\n"
        "\n"
        "Reading core/converter.py and core/gdal_handler.py directly (not\n"
        "needed until now) surfaced a lock this whole series has never\n"
        "accounted for: GeoPackageConverter.convert() is wrapped in\n"
        "_serialize_conversions, which holds a process-wide threading.RLock()\n"
        "(global_conversion_lock()) across the ENTIRE conversion - GDAL write,\n"
        "metadata generation, AND the internal validate_schema() call - for\n"
        "its full duration. P61 dispatches validation from inside convert(),\n"
        "under this lock. Every bisection probe in this series so far,\n"
        "including this script's own predecessor, dispatches validation as a\n"
        "SEPARATE call made AFTER convert() has already returned and released\n"
        "it - an inadvertent confound present in every probe until now. A\n"
        "second, related, never-isolated variable: every monkeypatched probe\n"
        "validates a trivial, deliberately-FAILING document, never the kind\n"
        "of complete, schema-PASSING document generate_package_metadata()\n"
        "actually produces in production.\n"
        "\n"
        "WHAT THIS SCRIPT ISOLATES\n"
        "----------------------------\n"
        "Three probes, each a minimal, single-variable change from v0.30.41's\n"
        "P68 (real worker, round-thread dispatch, trivial doc, no lock -\n"
        "CRASH):\n"
        "\n"
        "  P70  Same as P68, except the round's own thread holds\n"
        "       global_conversion_lock() across both its GDAL write and its\n"
        "       validation dispatch. Document stays the trivial \"<x/>\".\n"
        "       Isolates the lock alone.\n"
        "  P71  Same as P68 (no lock), except the dispatched document is a\n"
        "       REAL, complete ISO 19115 package document built by\n"
        "       MetadataHandler.generate_package_metadata() itself - expected\n"
        "       to PASS validation, not raise ValueError. Isolates document\n"
        "       content/validation outcome alone, no lock.\n"
        "  P72  Combines both - lock held, real passing document - the most\n"
        "       production-faithful reconstruction of what P61 actually does.\n"
        "\n"
        "Both the lock-nesting control flow and the real-document generation\n"
        "path were verified standalone before this delivery: a pure-Python\n"
        "stand-in test confirmed the nested-RLock pattern (P70/P72 acquire the\n"
        "lock, then convert() re-acquires the SAME lock internally, reentrant,\n"
        "nested) has no deadlock; and the exact document this script builds\n"
        "was generated and validated for real, in this delivery's own\n"
        "sandbox, against the project's real bundled XSD schema - confirmed\n"
        "to return True, not raise, exactly as P71/P72 expect.\n"
        "\n"
        "READING THE RESULTS - see diagnose_crash_v0.30.42.py's own module\n"
        "docstring for the complete table, but in short: if P70 is OK and P71\n"
        "still crashes, the lock is the deciding factor and explains P61; if\n"
        "P71 is OK and P70 still crashes, document content/validation outcome\n"
        "is the deciding factor, not the lock; if both P70 and P71 crash but\n"
        "P72 (the combination) is OK, neither alone is sufficient and only the\n"
        "full combination matches P61's safety; if all three crash, neither\n"
        "factor explains P61's survival and it may have been a low-probability\n"
        "escape rather than a deterministic safe shape.\n"
        "\n"
        "No code fix is proposed alongside this script - same discipline as\n"
        "every diagnostic before it in this series. This is still bisection,\n"
        "not a fix.\n"
        "\n"
        "HOW TO RUN\n"
        "----------\n"
        "1. Unzip so you end up with, under dev_tools\\:\n"
        "     dev_tools\\diagnose_crash_v0.30.42.py\n"
        "     dev_tools\\candidate_patch_v0.30.39\\core\\metadata_handler.py\n"
        "2. Anaconda Prompt:\n"
        "     conda activate geopackage\n"
        "     python dev_tools\\diagnose_crash_v0.30.42.py\n"
        "3. Send back dev_tools\\logs\\diagnose_v0.30.42_<timestamp>.log\n"
    )


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
        print("Expected layout, all under dev_tools\\ alongside this script:")
        print(f"  {SCRIPT_NAME}")
        print(f"  {PATCH_RELATIVE_PATH}")
        print()
        print("candidate_patch_v0.30.39 is REQUIRED here - every probe in")
        print("diagnose_crash_v0.30.42.py needs it, so there is nothing useful")
        print("to package without it.")
        return 1

    try:
        patch_version_line = _verify_patch_version(source_patch)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1
    print(f"Confirmed candidate version: {patch_version_line}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dist_root = here / "diagnostics_dist"
    stage_dir = dist_root / f"diagnose_crash_v{DIAGNOSTIC_VERSION}_{timestamp}"
    stage_dir.mkdir(parents=True, exist_ok=True)

    # 1. Copy the diagnostic script into the staging folder.
    dest_script = stage_dir / SCRIPT_NAME
    shutil.copy2(source_script, dest_script)
    print(f"Copied: {dest_script}")

    # 2. Copy the whole candidate_patch_v0.30.39/ folder too, not just the
    #    one file the probes read, so the staged bundle is self-contained.
    dest_patch_dir = stage_dir / PATCH_DIR_NAME
    shutil.copytree(
        here / PATCH_DIR_NAME, dest_patch_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    print(f"Copied: {dest_patch_dir}")

    # 3. Write a VERSION note (project convention: every packaged artifact
    #    carries a VERSION.txt describing what it is).
    version_txt = stage_dir / "VERSION.txt"
    version_txt.write_text(_build_version_txt(patch_version_line), encoding="utf-8")
    print(f"Wrote:   {version_txt}")

    # 4. Zip the staging folder.
    zip_base = dist_root / f"diagnose_crash_v{DIAGNOSTIC_VERSION}_{timestamp}"
    zip_path = shutil.make_archive(str(zip_base), "zip", root_dir=stage_dir)
    print(f"Zipped:  {zip_path}")

    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
