# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for diagnose_crash_v0.30.40.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a dev_tools delivery - same convention as every package_diagnose_vX.py
before it. package_diagnose_v0.30.17.py through package_diagnose_v0.30.37.py
each bundled a single, self-sufficient diagnostic script with no other
dependencies. package_validate_patch_v0.30.38.py and package_validate_patch_
shutdown_v0.30.39.py additionally bundled a proposed candidate_patch_vX/
folder, because validating that proposed patch was their whole point.

v0.30.40 is a hybrid of those two shapes. It is a pure diagnostic - no NEW
code change is proposed here, same as v0.30.17-37 - but one of its four
probes (P67) needs the ALREADY-delivered candidate_patch_v0.30.39/core/
metadata_handler.py (from package_validate_patch_shutdown_v0.30.39.py) to
exercise the REAL persistent-worker implementation rather than a hand-rolled
stand-in. diagnose_crash_v0.30.40.py itself tolerates that folder being
missing - P67 is skipped with a warning, P64/P65/P66 still run - see that
script's own module docstring. This packaging script mirrors the same
tolerance: if candidate_patch_v0.30.39/ is sitting next to this script, it
is bundled too, so the zip is self-contained even if this is the only
delivery you have on hand; if it is not there, packaging still proceeds,
with a clear warning, since it should already be on your machine from the
previous delivery.

To be clear about what this script does NOT do: it does not copy any
candidate over the real, shipping core/metadata_handler.py anywhere, and it
does not modify candidate_patch_v0.30.39/ itself - only reads it. Nothing
outside dev_tools\\ is touched by this script.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside diagnose_crash_v0.30.40.py (and,
ideally, the already-delivered candidate_patch_v0.30.39\\):

    conda activate geopackage
    cd dev_tools
    python package_diagnose_v0.30.40.py

Produces:
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.40_<timestamp>\\
        diagnose_crash_v0.30.40.py
        candidate_patch_v0.30.39\\core\\metadata_handler.py   (if present)
        VERSION.txt
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.40_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "diagnose_crash_v0.30.40.py"
DIAGNOSTIC_VERSION = "0.30.40"
PATCH_DIR_NAME = "candidate_patch_v0.30.39"
PATCH_RELATIVE_PATH = Path(PATCH_DIR_NAME) / "core" / "metadata_handler.py"
EXPECTED_PATCH_VERSION_LINE = '__version__ = "0.30.25"'


def _verify_patch_version(patch_file: Path) -> str:
    """Read back the optional candidate's __version__ line and confirm it
    matches what diagnose_crash_v0.30.40.py's P67 probe expects. Raises
    RuntimeError on a MISMATCH - packaging a silently-wrong version would be
    worse than not bundling it at all - but a folder that is simply absent
    is handled separately in main() as a tolerated, warned-about case, not
    an error, matching diagnose_crash_v0.30.40.py's own graceful P67 skip."""
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
            "isn't the version diagnose_crash_v0.30.40.py's P67 probe "
            "expects - check which copy is sitting in "
            f"{PATCH_DIR_NAME}\\core\\ before re-running."
        )
    return version_line


def _build_version_txt(bundle_patch: bool, patch_version_line: str | None) -> str:
    """Builds the VERSION.txt contents as one string, kept as its own
    function so the bundle/no-bundle branching stays simple to read instead
    of being embedded inside a long write_text(...) call."""
    if bundle_patch:
        patch_status = f"Bundled ({patch_version_line})"
        unzip_layout = (
            "     dev_tools\\candidate_patch_v0.30.39\\core\\metadata_handler.py\n"
        )
    else:
        patch_status = "NOT bundled - was not found next to this packaging script"
        unzip_layout = (
            "   (candidate_patch_v0.30.39\\ was NOT bundled - it should already be\n"
            "    on your machine from the previous delivery; if it truly is not,\n"
            "    P67 will be skipped with a warning and P64/P65/P66 will still run)\n"
        )

    return (
        "GeoPackage Creator - crash diagnostic package\n"
        f"Diagnostic version : {DIAGNOSTIC_VERSION}\n"
        f"Packaged           : {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"Script             : {SCRIPT_NAME}\n"
        f"candidate_patch_v0.30.39 (needed by P67 only): {patch_status}\n"
        "\n"
        "WHAT THIS FOLLOWS UP ON\n"
        "------------------------\n"
        "dev_tools\\logs\\validate_patch_shutdown_v0.30.39_20260817_112111.log,\n"
        "run on the target machine on 2026-08-17:\n"
        "\n"
        "  CRASH  P62  v0.30.39 candidate, explicit shutdown_lxml_worker()\n"
        "              before a normal exit - crashed INSIDE that call\n"
        "              itself, per the log's print-statement ordering, not\n"
        "              after it and not during ordinary interpreter\n"
        "              finalization the way the earlier P61 crash did.\n"
        "  OK     P63  v0.30.38 candidate, unmodified, os._exit(0) instead\n"
        "              of a normal exit, worker thread never asked to stop.\n"
        "\n"
        "P62's persistent worker thread never performs a GDAL write itself -\n"
        "that is the entire point of the v0.30.24 mitigation this whole\n"
        "series has been validating - so its crash does not fit the\n"
        "documented P51/P52/P53 necessary condition ('one thread does GDAL\n"
        "then lxml itself'), and diagnose_crash_v0.30.34.py's P52 already\n"
        "showed a simpler 'lxml-only thread touches once then terminates,\n"
        "after a separate GDAL-only thread elsewhere' shape is safe.\n"
        "\n"
        "WHAT THIS SCRIPT ISOLATES\n"
        "----------------------------\n"
        "Four cheap, monkey-patched probes (never the full expensive real\n"
        "pipeline P62 used), each changing exactly ONE candidate difference\n"
        "relative to a fresh rerun of diagnose_crash_v0.30.35.py's P55\n"
        "(which came back clean, including its own persistent worker's\n"
        "clean sentinel-based stop):\n"
        "\n"
        "  P64  Control - P55's exact pattern rerun fresh today. Expected OK -\n"
        "       confirms nothing about the environment has shifted before\n"
        "       trusting P65-P67.\n"
        "  P65  Same as P64, ROUNDS=10 instead of 5 - isolates repetition\n"
        "       count alone.\n"
        "  P66  Same as P64 (5 rounds), except each round's OWN thread\n"
        "       dispatches its own validation to the persistent worker,\n"
        "       instead of the main thread doing it afterward - isolates\n"
        "       whether many different, transient dispatching threads\n"
        "       matters, versus one thread doing it repeatedly.\n"
        "  P67  Same as P64 (5 rounds, main-thread dispatch), except the\n"
        "       lxml side is the REAL candidate_patch_v0.30.39/core/\n"
        "       metadata_handler.py - its actual validate_schema()/\n"
        "       _ensure_lxml_worker_started() and its actual\n"
        "       shutdown_lxml_worker() - instead of a hand-rolled\n"
        "       equivalent. Needs candidate_patch_v0.30.39\\ to be present;\n"
        "       skipped with a warning if it is not.\n"
        "\n"
        "READING THE RESULTS - see diagnose_crash_v0.30.40.py's own module\n"
        "docstring for the complete table covering every combination, but in\n"
        "short: P64 itself CRASHing or FAILing means the environment has\n"
        "shifted and P65-P67 shouldn't be trusted yet; all four OK means none\n"
        "of these three candidate differences, changed alone, reproduces\n"
        "P62's crash cheaply; whichever of P65/P66/P67 crashes (with the\n"
        "others OK) points at repetition count, dispatching-thread identity,\n"
        "or the real implementation specifically, respectively; more than one\n"
        "crashing means more than one factor contributes together.\n"
        "\n"
        "No code fix is proposed alongside this script - same discipline as\n"
        "every diagnostic before it in this series. This is still bisection,\n"
        "not a fix.\n"
        "\n"
        "HOW TO RUN\n"
        "----------\n"
        "1. Unzip so you end up with, under dev_tools\\:\n"
        "     dev_tools\\diagnose_crash_v0.30.40.py\n"
        f"{unzip_layout}"
        "2. Anaconda Prompt:\n"
        "     conda activate geopackage\n"
        "     python dev_tools\\diagnose_crash_v0.30.40.py\n"
        "3. Send back dev_tools\\logs\\diagnose_v0.30.40_<timestamp>.log\n"
    )


def main() -> int:
    here = Path(__file__).resolve().parent
    source_script = here / SCRIPT_NAME
    source_patch = here / PATCH_RELATIVE_PATH

    if not source_script.exists():
        print(f"ERROR: {SCRIPT_NAME} not found next to this packaging script.")
        print(f"Expected at: {source_script}")
        print("Place both files in the same dev_tools\\ folder and re-run.")
        return 1

    bundle_patch = source_patch.exists()
    patch_version_line = None
    if bundle_patch:
        try:
            patch_version_line = _verify_patch_version(source_patch)
        except RuntimeError as e:
            print(f"ERROR: {e}")
            return 1
        print(f"Confirmed candidate version: {patch_version_line}")
    else:
        print(f"NOTE: {source_patch} not found - packaging WITHOUT it.")
        print("      diagnose_crash_v0.30.40.py's P67 probe will be skipped")
        print("      (with its own warning) wherever this package is unzipped")
        print("      and run, exactly as it would be right here right now.")
        print("      P64/P65/P66 do not need it and are unaffected.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dist_root = here / "diagnostics_dist"
    stage_dir = dist_root / f"diagnose_crash_v{DIAGNOSTIC_VERSION}_{timestamp}"
    stage_dir.mkdir(parents=True, exist_ok=True)

    # 1. Copy the diagnostic script into the staging folder.
    dest_script = stage_dir / SCRIPT_NAME
    shutil.copy2(source_script, dest_script)
    print(f"Copied: {dest_script}")

    # 2. Copy the whole candidate_patch_v0.30.39/ folder too, if present, so
    #    the staged bundle is self-contained - not just the one file P67
    #    reads - matching how package_validate_patch_v0.30.38.py and
    #    package_validate_patch_shutdown_v0.30.39.py both bundled their
    #    whole candidate folders rather than a single loose file.
    if bundle_patch:
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
        _build_version_txt(bundle_patch, patch_version_line), encoding="utf-8"
    )
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
