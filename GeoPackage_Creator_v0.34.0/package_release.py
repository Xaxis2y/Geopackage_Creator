# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
DGIWG Validator — Release Packaging Script (v1.62)
==================================================

Builds a clean release folder and zip from the current project directory.

Usage (Anaconda Prompt, any environment — stdlib only, no packages needed):

    conda activate dgiwg_test
    cd C:\\Users\\Son\\Documents\\DGIWG\\DGIWG_GeoPackage_Validator_v1.62
    python package_release.py

Output:
    dist\\DGIWG_GeoPackage_Validator_v<VERSION>\\       (staged folder)
    dist\\DGIWG_GeoPackage_Validator_v<VERSION>.zip     (release archive)
    VERSION.txt generated inside the staged folder.

Included : dgiwg_validator/ package, versioned launcher, EPSG cache,
           user manual (.docx), QUICKSTART.html, run_local_tests.py
Excluded : __pycache__, old-version launchers, superseded manuals, reports,
           local_test, logs, dist itself, any _superseded*/_to_delete* folder.

v1.62 changes:
  • archive name drops the "_pre" suffix — this is a full release
  • VERSION.txt says "(release)" instead of "(pre-release)"
  • a manifest check refuses to build if a required release asset is missing,
    so a zip can never ship without the manual or the quick-start page
  • superseded user-manual .docx files are excluded from the staged folder
  • bug fix: folders named "_superseded*" or "_to_delete*" — used to park
    files an update replaced, on machines where this script cannot delete
    them outright — are now excluded by prefix. Previously only exact names
    in EXCLUDE_DIRS were skipped, so a parking folder from an earlier update
    (whatever it happened to be named) got copied into the release and
    zipped straight into the archive, including any old release zip sitting
    inside it. If a past build looks 2x the expected size, this was why —
    rebuild with this version and check dist\\<name>.zip does not contain a
    "_superseded_..." entry.
"""
import os
import re
import sys
import shutil
import zipfile
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from dgiwg_validator import __version__ as VERSION  # single source of truth

RELEASE_NAME = f"DGIWG_GeoPackage_Validator_v{VERSION}"
DIST = os.path.join(HERE, "dist")
STAGE = os.path.join(DIST, RELEASE_NAME)
ZIP_PATH = os.path.join(DIST, f"{RELEASE_NAME}.zip")
LAUNCHER_NAME = f"DGIWG_Validator_v{VERSION.replace('.', '_')}.py"

EXCLUDE_DIRS = {"__pycache__", "dist", "reports", "local_test", ".git"}
# v1.62 fix: folders used to park superseded files during an in-place update
# (e.g. "_superseded_v158") are workspace housekeeping, never release content.
# They weren't excluded by name because the version suffix changes every
# release; matched by prefix instead so this can't recur next time regardless
# of what version number ends up in the folder name.
EXCLUDE_DIR_PREFIXES = ("_superseded", "_to_delete")
EXCLUDE_FILE_PATTERNS = [
    r"^local_test_log_.*\.txt$",
    r".*_DGIWG_Report.*\.(html|json)$",
    r"^DGIWG_GPKG_FINAL_REPORT\.(html|csv)$",
    r"^make_test_gpkgs\.py$",
    # old-version launchers — the staged folder keeps ONLY the current one
    r"^DGIWG_Validator_v\d+_\d+\.py$",
    # v1.62: superseded user manuals — only the current version ships
    r"^DGIWG_GeoPackage_Validator_User_Manual_v(?!%s\.docx$).*\.docx$"
    % VERSION.replace(".", r"\."),
    # v1.62: maintainer-only tooling and internal review notes — not shipped.
    # build_manual.js needs Node.js, which is not present on target machines,
    # and REVIEW_FINDINGS is an internal pre-release document.
    r"^build_manual\.js$",
    r"^REVIEW_FINDINGS_.*\.md$",
    r"^.*\.pdf$",
]

# v1.62: a release is not allowed to ship without these.  Missing any one of
# them aborts the build instead of producing a quietly incomplete zip.
REQUIRED_ASSETS = [
    LAUNCHER_NAME,
    "QUICKSTART.html",
    f"DGIWG_GeoPackage_Validator_User_Manual_v{VERSION}.docx",
    "run_local_tests.py",
    "dgiwg_epsg_cache.json",
    os.path.join("dgiwg_validator", "__init__.py"),
    os.path.join("dgiwg_validator", "__main__.py"),
    os.path.join("dgiwg_validator", "main.py"),
    os.path.join("dgiwg_validator", "checks.py"),
    os.path.join("dgiwg_validator", "config.py"),
    os.path.join("dgiwg_validator", "constants.py"),
    os.path.join("dgiwg_validator", "forensics.py"),
    os.path.join("dgiwg_validator", "html_report.py"),
    os.path.join("dgiwg_validator", "net.py"),
    os.path.join("dgiwg_validator", "rollup.py"),
    os.path.join("dgiwg_validator", "utils.py"),
]


def _excluded(fname: str) -> bool:
    return any(re.match(p, fname) for p in EXCLUDE_FILE_PATTERNS)


def _check_required_assets() -> list:
    """Return the list of REQUIRED_ASSETS that are absent from the source tree."""
    return [a for a in REQUIRED_ASSETS if not os.path.isfile(os.path.join(HERE, a))]


def main() -> None:
    print(f"Packaging {RELEASE_NAME} (release)")

    missing = _check_required_assets()
    if missing:
        print("  ABORT — required release asset(s) missing from the source folder:")
        for m in missing:
            print(f"    - {m}")
        print("  Nothing was written. Add the missing file(s) and re-run.")
        sys.exit(1)
    print(f"  manifest: all {len(REQUIRED_ASSETS)} required assets present")

    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE, exist_ok=True)

    copied = 0
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [
            d for d in dirs
            if d not in EXCLUDE_DIRS and not d.startswith(EXCLUDE_DIR_PREFIXES)
        ]
        rel_root = os.path.relpath(root, HERE)
        for f in files:
            if rel_root == "." and _excluded(f):
                continue
            src = os.path.join(root, f)
            dst_dir = os.path.join(STAGE, "" if rel_root == "." else rel_root)
            os.makedirs(dst_dir, exist_ok=True)
            shutil.copy2(src, os.path.join(dst_dir, f))
            copied += 1

    # Current-version launcher (copied explicitly since the pattern above
    # excludes ALL versioned launchers, old and new alike).
    src_launcher = os.path.join(HERE, LAUNCHER_NAME)
    if os.path.isfile(src_launcher):
        shutil.copy2(src_launcher, os.path.join(STAGE, LAUNCHER_NAME))
        copied += 1
        print(f"  launcher: {LAUNCHER_NAME}")
    else:
        print(f"  WARNING: launcher {LAUNCHER_NAME} not found — zip will have no launcher")

    # VERSION.txt
    with open(os.path.join(STAGE, "VERSION.txt"), "w", encoding="utf-8") as fh:
        fh.write(
            f"DGIWG GeoPackage Compliance Validator\n"
            f"Version   : {VERSION} (release)\n"
            f"Standard  : DGIWG STD-DP-19-005 v1.1\n"
            f"Packaged  : {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n"
            f"License   : GPL-2.0-or-later\n"
            f"Copyright : (c) 2026 Eui Soo SON\n"
        )
    copied += 1

    # Zip
    if os.path.isfile(ZIP_PATH):
        os.remove(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(STAGE):
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.join(RELEASE_NAME, os.path.relpath(full, STAGE))
                zf.write(full, arc)

    size_mb = os.path.getsize(ZIP_PATH) / 1_048_576
    print(f"  staged  : {STAGE}  ({copied} files)")
    print(f"  archive : {ZIP_PATH}  ({size_mb:.2f} MB)")
    print("Done.")


if __name__ == "__main__":
    main()


