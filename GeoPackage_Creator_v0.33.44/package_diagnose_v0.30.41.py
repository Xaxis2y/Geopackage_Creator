# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for diagnose_crash_v0.30.41.py AND its required
companion candidate_patch_v0.30.39/core/metadata_handler.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a dev_tools delivery - same convention as every package_diagnose_vX.py
before it.

Unlike package_diagnose_v0.30.40.py - where candidate_patch_v0.30.39 was
needed by only one of four probes (P67), and packaging proceeded with a
warning if it was missing, since P64/P65/P66 still had value on their own -
EVERY probe in diagnose_crash_v0.30.41.py (P67R, P68, P69) exercises the
REAL candidate module. Without it, the script has nothing to run at all -
diagnose_crash_v0.30.41.py itself treats a missing candidate as a hard
SETUP ERROR, not a graceful partial run. This packaging script matches that:
candidate_patch_v0.30.39/ is REQUIRED here, not optional - packaging aborts
if it is missing or reports the wrong version, the same discipline
package_validate_patch_v0.30.38.py used for its own (also required) patch
bundle.

To be clear about what this script does NOT do: it does not copy any
candidate over the real, shipping core/metadata_handler.py anywhere, and it
does not modify candidate_patch_v0.30.39/ itself - only reads it. Nothing
outside dev_tools\\ is touched by this script.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside diagnose_crash_v0.30.41.py and
candidate_patch_v0.30.39\\ (already there from an earlier delivery):

    conda activate geopackage
    cd dev_tools
    python package_diagnose_v0.30.41.py

Produces:
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.41_<timestamp>\\
        diagnose_crash_v0.30.41.py
        candidate_patch_v0.30.39\\core\\metadata_handler.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.41_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "diagnose_crash_v0.30.41.py"
DIAGNOSTIC_VERSION = "0.30.41"
PATCH_DIR_NAME = "candidate_patch_v0.30.39"
PATCH_RELATIVE_PATH = Path(PATCH_DIR_NAME) / "core" / "metadata_handler.py"
EXPECTED_PATCH_VERSION_LINE = '__version__ = "0.30.25"'


def _verify_patch_version(patch_file: Path) -> str:
    """Read back the candidate's __version__ line and confirm it matches
    what diagnose_crash_v0.30.41.py's probes expect. Raises RuntimeError on
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
            "isn't the version diagnose_crash_v0.30.41.py's probes expect - "
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
        "dev_tools\\logs\\diagnose_v0.30.40_20260817_115919.log, run on the\n"
        "target machine on 2026-08-17:\n"
        "\n"
        "  OK     P64  hand-rolled worker, 5 rounds,  main-thread dispatch\n"
        "  OK     P65  hand-rolled worker, 10 rounds, main-thread dispatch\n"
        "  OK     P66  hand-rolled worker, 5 rounds,  round-thread dispatch\n"
        "  CRASH  P67  REAL candidate_patch_v0.30.39 worker, 5 rounds,\n"
        "              main-thread dispatch - crashed fast, on round 1 of 5,\n"
        "              with no repetition and no explicit shutdown call\n"
        "              needed.\n"
        "\n"
        "P67 is identical to P64 except the lxml side calls the REAL candidate\n"
        "module's actual validate_schema()/_ensure_lxml_worker_started()/\n"
        "shutdown_lxml_worker() instead of a hand-rolled stand-in. No single\n"
        "thread in P67 ever does both GDAL and lxml itself - the documented\n"
        "P51/P52/P53 necessary condition is not met - and the crashing thread\n"
        "was doing a GDAL write, not an lxml touch, the mirror image of every\n"
        "earlier finding in this series. The real module's own\n"
        "_validate_schema_impl() is documented as the v0.30.23 validate_\n"
        "schema() body 'moved here unchanged', so the actual lxml logic is\n"
        "provably identical to what P64's hand-rolled worker already runs\n"
        "safely - whatever P67 exposed lives in the thread-lifecycle/dispatch\n"
        "machinery around that logic, not the validation logic itself.\n"
        "\n"
        "WHAT THIS SCRIPT ISOLATES\n"
        "----------------------------\n"
        "Three probes, all staged against the REAL candidate module:\n"
        "\n"
        "  P67R  Control - an EXACT rerun of P67, unchanged. Expected CRASH,\n"
        "        matching P67 - confirms the crash is reliably reproducible\n"
        "        before trusting P68/P69 as a comparison against it.\n"
        "  P68   Same as P67R, except each round's own thread also dispatches\n"
        "        its own validation to the REAL worker, instead of the main\n"
        "        thread doing it afterward - isolates dispatch-thread\n"
        "        identity alone. This is also the real pipeline's actual\n"
        "        shape (validate_patch_v0.30.38.py's P61, 10/10 clean).\n"
        "  P69   Same as P67R (dispatch unchanged), except the REAL worker is\n"
        "        forced to start before any GDAL activity has happened\n"
        "        anywhere in the process, instead of lazily on round 0 -\n"
        "        isolates worker-creation timing alone.\n"
        "\n"
        "READING THE RESULTS - see diagnose_crash_v0.30.41.py's own module\n"
        "docstring for the complete table, but in short: if P67R itself does\n"
        "not crash, the original P67 crash was not reliably reproducible from\n"
        "this shape alone and the comparison needs rethinking; if P67R\n"
        "crashes and P68 does not (P69 does), dispatch-thread identity is the\n"
        "deciding factor and explains why the real pipeline survives 10\n"
        "rounds; if P67R crashes and P69 does not (P68 does), worker-creation\n"
        "timing is the deciding factor and points at a simple, concrete fix -\n"
        "start the worker eagerly at program startup; if both P68 and P69 are\n"
        "clean, the dangerous shape needs P67R's exact combination together;\n"
        "if both crash, the real worker/dispatch machinery is broadly\n"
        "fragile regardless of dispatch shape or timing.\n"
        "\n"
        "No code fix is proposed alongside this script - same discipline as\n"
        "every diagnostic before it in this series. This is still bisection,\n"
        "not a fix.\n"
        "\n"
        "HOW TO RUN\n"
        "----------\n"
        "1. Unzip so you end up with, under dev_tools\\:\n"
        "     dev_tools\\diagnose_crash_v0.30.41.py\n"
        "     dev_tools\\candidate_patch_v0.30.39\\core\\metadata_handler.py\n"
        "2. Anaconda Prompt:\n"
        "     conda activate geopackage\n"
        "     python dev_tools\\diagnose_crash_v0.30.41.py\n"
        "3. Send back dev_tools\\logs\\diagnose_v0.30.41_<timestamp>.log\n"
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
        print("Unlike package_diagnose_v0.30.40.py, candidate_patch_v0.30.39 is")
        print("REQUIRED here - every probe in diagnose_crash_v0.30.41.py needs it,")
        print("so there is nothing useful to package without it.")
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
    #    one file the probes read, so the staged bundle is self-contained -
    #    matching how every packaging script that bundles a candidate does.
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
