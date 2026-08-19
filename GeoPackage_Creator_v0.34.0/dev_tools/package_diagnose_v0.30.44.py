# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for diagnose_crash_v0.30.44.py AND its required
companion candidate_patch_v0.30.39/core/metadata_handler.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a dev_tools delivery - same convention as every package_diagnose_vX.py
before it, including package_diagnose_v0.30.43.py immediately prior. All
four probes in diagnose_crash_v0.30.44.py exercise the REAL candidate
module (P75/P77/P78 through the real core package, P76 through an isolated
core_min/ package built at runtime from this same file), so
candidate_patch_v0.30.39/ is REQUIRED, not optional - packaging aborts if
it is missing or reports the wrong version.

To be clear about what this script does NOT do: it does not copy any
candidate over the real, shipping core/metadata_handler.py anywhere, and it
does not modify candidate_patch_v0.30.39/ itself - only reads it. Nothing
outside dev_tools\\ is touched by this script.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside diagnose_crash_v0.30.44.py and
candidate_patch_v0.30.39\\ (already there from an earlier delivery):

    conda activate geopackage
    cd dev_tools
    python package_diagnose_v0.30.44.py

Produces:
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.44_<timestamp>\\
        diagnose_crash_v0.30.44.py
        candidate_patch_v0.30.39\\core\\metadata_handler.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.44_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "diagnose_crash_v0.30.44.py"
DIAGNOSTIC_VERSION = "0.30.44"
PATCH_DIR_NAME = "candidate_patch_v0.30.39"
PATCH_RELATIVE_PATH = Path(PATCH_DIR_NAME) / "core" / "metadata_handler.py"
EXPECTED_PATCH_VERSION_LINE = '__version__ = "0.30.25"'


def _verify_patch_version(patch_file: Path) -> str:
    """Read back the candidate's __version__ line and confirm it matches
    what diagnose_crash_v0.30.44.py's probes expect. Raises RuntimeError on
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
            "isn't the version diagnose_crash_v0.30.44.py's probes expect - "
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
        "dev_tools\\logs\\diagnose_v0.30.43_20260817_124536.log, run on the\n"
        "target machine on 2026-08-17: P73 (real worker, patched loop that\n"
        "stringifies a failing validation's exception inside the worker\n"
        "before it crosses the queue) was OK, 5/5 rounds - direct\n"
        "confirmation that a live exception object crossing the worker-to-\n"
        "caller queue is a real crash mechanism, and fixable. P74\n"
        "(instrumented real pipeline, 10 rounds) CRASHED anyway - calls=30\n"
        "passed=30 failed=0, then dead inside shutdown_lxml_worker() itself\n"
        "(the log never reaches \"shutdown_lxml_worker(...) returned\").\n"
        "Since P73's mechanism needs a validation FAILURE to fire and none\n"
        "occurred, this confirms validate_patch_shutdown_v0.30.39.py's P62\n"
        "is a third, separate, still-unexplained crash mechanism - not\n"
        "another instance of the one P73 just closed.\n"
        "\n"
        "It is also worth being precise that this third mechanism is not\n"
        "unique to the EXPLICIT shutdown_lxml_worker() call path: candidate_\n"
        "patch_v0.30.39/core/metadata_handler.py's own \"PERSISTENT WORKER\n"
        "SHUTDOWN\" section records that validate_patch_v0.30.38.py's P61 -\n"
        "same real pipeline, same 10 rounds, but never calling any shutdown\n"
        "function at all (it did not exist yet on that candidate), just\n"
        "letting the process exit normally with the daemon worker still\n"
        "blocked - crashed too, after all 10 rounds completed, during\n"
        "ordinary interpreter finalization instead of inside a function\n"
        "call. Both \"join it explicitly\" and \"never touch it\" end in the\n"
        "same access violation once the worker thread has done real\n"
        "libxml2 work.\n"
        "\n"
        "WHAT THIS SCRIPT DOES\n"
        "-------------------------\n"
        "Four probes, narrowing this third mechanism along three\n"
        "independent axes:\n"
        "\n"
        "  P75  Never-used worker, immediate shutdown - zero jobs\n"
        "       dispatched, no lxml, no GDAL. Cheapest test of whether the\n"
        "       crash needs ANY real work at all.\n"
        "  P76  10 rounds of REAL schema generation and validation against\n"
        "       the REAL bundled XSD, but GDAL is never imported anywhere\n"
        "       in the process (candidate module loaded through an\n"
        "       isolated core_min/ package built at runtime, not the real\n"
        "       core package, since core/__init__.py unconditionally\n"
        "       imports osgeo as a side effect). Tests whether GDAL\n"
        "       involvement anywhere is a necessary ingredient for this\n"
        "       mechanism, the way it already is for the original one\n"
        "       (P46/P47).\n"
        "  P77  Identical to P74 (real pipeline, 10 rounds, zero-failure\n"
        "       instrumented) except it never calls shutdown_lxml_worker()\n"
        "       at all - re-tests P61's exact shape under the CURRENT\n"
        "       candidate for a clean comparison.\n"
        "  P78  Same as P77 but calls os._exit(0) instead of returning\n"
        "       normally, bypassing CPython's own interpreter finalization/\n"
        "       GC/atexit handling (not Windows' DLL_PROCESS_DETACH, which\n"
        "       still fires regardless of exit path) - tests whether the\n"
        "       crash is caused by code that runs during ordinary Python-\n"
        "       level shutdown specifically.\n"
        "\n"
        "Verified before this delivery, in this delivery's own sandbox,\n"
        "against the real candidate module and the project's real bundled\n"
        "XSD schema (this sandbox has a working lxml, though no GDAL): the\n"
        "P75-equivalent worker start/stop sequence and the P76 probe were\n"
        "both run for real end to end - not approximated - including via\n"
        "this script's own stage_gdal_free_copy() and run_probe()\n"
        "functions, called directly against a project layout mirroring the\n"
        "real one. All 10 P76 rounds passed, the schema resolved to the\n"
        "real bundled XSD (not the \"schema not found, skip validation\"\n"
        "path), and osgeo never entered sys.modules at any point. P77/P78\n"
        "need real GDAL and cannot be executed in that sandbox; their\n"
        "structure was AST-checked instead, and both reuse the same\n"
        "counting-wrapper approach diagnose_crash_v0.30.43.py's P74 already\n"
        "used successfully on the target machine.\n"
        "\n"
        "READING THE RESULTS - see diagnose_crash_v0.30.44.py's own module\n"
        "docstring for the complete table. In short: P75 CRASH means no\n"
        "real work is needed at all for this to be unsafe; P76 CRASH means\n"
        "GDAL is not a necessary ingredient for this mechanism the way it\n"
        "is for the original one; P77 CRASH (at ordinary interpreter exit)\n"
        "means this is the same hazard as P61/P74 just surfacing at a\n"
        "different point, while P77 OK would argue for removing the\n"
        "explicit shutdown call rather than continuing to develop it; P78\n"
        "OK narrows the cause to CPython's own finalization/GC/atexit\n"
        "layer specifically and opens an os._exit()-based mitigation angle,\n"
        "while P78 CRASH points at Windows' own DLL_PROCESS_DETACH-time\n"
        "native cleanup, which no amount of Python-level care can avoid.\n"
        "\n"
        "No code fix is proposed alongside this script - same discipline as\n"
        "every diagnostic before it in this series. This is still bisection\n"
        "and observation, not a fix.\n"
        "\n"
        "HOW TO RUN\n"
        "----------\n"
        "1. Unzip so you end up with, under dev_tools\\:\n"
        "     dev_tools\\diagnose_crash_v0.30.44.py\n"
        "     dev_tools\\candidate_patch_v0.30.39\\core\\metadata_handler.py\n"
        "2. Anaconda Prompt:\n"
        "     conda activate geopackage\n"
        "     python dev_tools\\diagnose_crash_v0.30.44.py\n"
        "3. Send back dev_tools\\logs\\diagnose_v0.30.44_<timestamp>.log\n"
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
        print("diagnose_crash_v0.30.44.py needs it, so there is nothing")
        print("useful to package without it.")
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
