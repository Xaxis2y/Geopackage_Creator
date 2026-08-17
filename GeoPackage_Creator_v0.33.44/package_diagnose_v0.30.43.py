# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Packaging automation for diagnose_crash_v0.30.43.py AND its required
companion candidate_patch_v0.30.39/core/metadata_handler.py.

Mirrors this project's own DGIWG_GeoPackage_Validator_v1.58/package_release.py
pattern (copy into a dist folder + write a VERSION note + zip), scaled down
for a dev_tools delivery - same convention as every package_diagnose_vX.py
before it. Same shape as package_diagnose_v0.30.41.py/_v0.30.42.py: both
probes in diagnose_crash_v0.30.43.py exercise the REAL candidate module, so
candidate_patch_v0.30.39/ is REQUIRED, not optional - packaging aborts if it
is missing or reports the wrong version.

To be clear about what this script does NOT do: it does not copy any
candidate over the real, shipping core/metadata_handler.py anywhere, and it
does not modify candidate_patch_v0.30.39/ itself - only reads it. Nothing
outside dev_tools\\ is touched by this script.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
Run from inside dev_tools\\, alongside diagnose_crash_v0.30.43.py and
candidate_patch_v0.30.39\\ (already there from an earlier delivery):

    conda activate geopackage
    cd dev_tools
    python package_diagnose_v0.30.43.py

Produces:
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.43_<timestamp>\\
        diagnose_crash_v0.30.43.py
        candidate_patch_v0.30.39\\core\\metadata_handler.py
        VERSION.txt
    dev_tools\\diagnostics_dist\\diagnose_crash_v0.30.43_<timestamp>.zip
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_NAME = "diagnose_crash_v0.30.43.py"
DIAGNOSTIC_VERSION = "0.30.43"
PATCH_DIR_NAME = "candidate_patch_v0.30.39"
PATCH_RELATIVE_PATH = Path(PATCH_DIR_NAME) / "core" / "metadata_handler.py"
EXPECTED_PATCH_VERSION_LINE = '__version__ = "0.30.25"'


def _verify_patch_version(patch_file: Path) -> str:
    """Read back the candidate's __version__ line and confirm it matches
    what diagnose_crash_v0.30.43.py's probes expect. Raises RuntimeError on
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
            "isn't the version diagnose_crash_v0.30.43.py's probes expect - "
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
        "dev_tools\\logs\\diagnose_v0.30.42_20260817_122819.log, run on the\n"
        "target machine on 2026-08-17: P70 (lock held, trivial FAILING\n"
        "document) CRASHED; P71 (no lock, real PASSING document) and P72\n"
        "(lock held, real PASSING document) were both OK. The lock never\n"
        "mattered - what flips the outcome is entirely whether the dispatched\n"
        "document fails or passes validation.\n"
        "\n"
        "Re-reading core/metadata_handler.py with that in mind found the exact\n"
        "asymmetry: on a failing validation, _lxml_worker_loop() (the REAL\n"
        "persistent worker's body) catches the exception and does\n"
        "response_q.put((False, e)) - queuing the LIVE exception object, not\n"
        "just its message. validate_schema()'s dispatch code (line 1050) then\n"
        "does `raise payload` - re-raising that SAME exception, with its\n"
        "ORIGINAL traceback, on the DISPATCHING thread. That traceback pins\n"
        "references to the worker thread's local schema/doc variables - both\n"
        "real, compiled libxml2 objects - via the frames it holds onto, so\n"
        "their last reference can be dropped, and they can be deallocated, on\n"
        "a thread other than the one that created them. On a PASSING\n"
        "validation nothing is ever raised, so schema/doc clean up normally,\n"
        "locally, on the worker thread. Every hand-rolled worker this whole\n"
        "series has used has, by coincidence, always caught and stringified\n"
        "exceptions locally before ever queuing anything - consistent with\n"
        "why they have never crashed either.\n"
        "\n"
        "This does NOT, on its own, explain validate_patch_shutdown_v0.30.39.py's\n"
        "P62 - that crash happened inside an explicit shutdown_lxml_worker()\n"
        "call, after 10 rounds of the real pipeline that (so far as its own\n"
        "log shows) never reported a validation failure. Whether the real\n"
        "pipeline's real, generated metadata ever actually fails validation\n"
        "has never actually been measured - P62's own script only reported\n"
        "whether each round as a whole succeeded, not whether validation\n"
        "passed or failed within it.\n"
        "\n"
        "WHAT THIS SCRIPT DOES\n"
        "-------------------------\n"
        "Two probes:\n"
        "\n"
        "  P73  Direct mechanism test. Identical to P70 (real worker,\n"
        "       round-thread dispatch, trivial \"<x/>\" document - crashed 5/5\n"
        "       times across P67, P67R, P68, P69, P70), except\n"
        "       _lxml_worker_loop() is replaced with a version that converts\n"
        "       a failing validation's exception to a plain STRING inside\n"
        "       the worker thread, before it ever crosses the queue -\n"
        "       _validate_schema_impl() itself, the REAL lxml logic, is\n"
        "       completely untouched. If this alone avoids the crash, it is\n"
        "       direct confirmation of the mechanism above.\n"
        "  P74  Instrumented real pipeline. Runs the REAL, completely\n"
        "       unmonkeypatched pipeline for 10 rounds, matching P61/P62\n"
        "       exactly, with _validate_schema_impl() wrapped in a\n"
        "       transparent counting layer (calls the real implementation\n"
        "       unchanged, only observes) that counts every real validation\n"
        "       attempt and every failure. Prints the tally after every\n"
        "       round and a final summary BEFORE calling the REAL\n"
        "       shutdown_lxml_worker() one more time - both re-testing P62's\n"
        "       crash and showing, for the first time, whether the real\n"
        "       pipeline's real metadata ever actually fails validation.\n"
        "\n"
        "Both new mechanisms - the patched worker loop and the counting\n"
        "wrapper - were verified standalone before this delivery, directly\n"
        "against the real candidate module and the project's real bundled\n"
        "XSD schema, in this delivery's own sandbox: confirmed the patched\n"
        "loop's queued payload is a plain str (not a live exception object)\n"
        "on a failing document, and that shutdown_lxml_worker() still stops\n"
        "the patched-loop worker correctly; and confirmed the counting\n"
        "wrapper exactly tracks a real round-shaped sequence (generate_\n"
        "package_metadata()'s own internal self-check plus one explicit\n"
        "validate_schema() call) as 2 real dispatches, both passing, without\n"
        "altering behavior at all.\n"
        "\n"
        "READING THE RESULTS - see diagnose_crash_v0.30.43.py's own module\n"
        "docstring for the complete table, but in short: P73 OK directly\n"
        "confirms the cross-thread-exception mechanism; P73 CRASH means it is\n"
        "not the (or not the only) mechanism. For P74: zero validation\n"
        "failures across all real calls but it still crashes at shutdown\n"
        "confirms P62 is a SEPARATE mechanism (this hypothesis needs a\n"
        "failure to occur, and none did); zero failures and no crash this\n"
        "time means P62 may not be reliably reproducible and is worth a\n"
        "rerun; one or more failures anywhere means the real pipeline DOES\n"
        "sometimes hit the failing path, and this hypothesis could explain\n"
        "part or all of P62 after all.\n"
        "\n"
        "No code fix is proposed alongside this script - same discipline as\n"
        "every diagnostic before it in this series. This is still bisection\n"
        "and observation, not a fix.\n"
        "\n"
        "HOW TO RUN\n"
        "----------\n"
        "1. Unzip so you end up with, under dev_tools\\:\n"
        "     dev_tools\\diagnose_crash_v0.30.43.py\n"
        "     dev_tools\\candidate_patch_v0.30.39\\core\\metadata_handler.py\n"
        "2. Anaconda Prompt:\n"
        "     conda activate geopackage\n"
        "     python dev_tools\\diagnose_crash_v0.30.43.py\n"
        "3. Send back dev_tools\\logs\\diagnose_v0.30.43_<timestamp>.log\n"
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
        print("candidate_patch_v0.30.39 is REQUIRED here - both probes in")
        print("diagnose_crash_v0.30.43.py need it, so there is nothing useful")
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
