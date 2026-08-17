# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
DGIWG Validator — Release Packaging Script (v1.58)
==================================================

Builds a clean pre-release folder and zip from the current project directory.

Usage (Anaconda Prompt, any environment — stdlib only):

    cd C:\\Users\\Son\\Documents\\DGIWG\\DGIWG_GeoPackage_Validator_v1.57
    python package_release.py

Output:
    dist\\DGIWG_GeoPackage_Validator_v<VERSION>\\        (staged folder)
    dist\\DGIWG_GeoPackage_Validator_v<VERSION>_pre.zip  (release archive)
    VERSION.txt generated inside the staged folder.

Included : dgiwg_validator/ package, versioned launcher, EPSG cache,
           user manual (.docx), run_local_tests.py
Excluded : __pycache__, old-version launchers, reports, local_test,
           logs, dist itself.
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
ZIP_PATH = os.path.join(DIST, f"{RELEASE_NAME}_pre.zip")
LAUNCHER_NAME = f"DGIWG_Validator_v{VERSION.replace('.', '_')}.py"

EXCLUDE_DIRS = {"__pycache__", "dist", "reports", "local_test", ".git"}
EXCLUDE_FILE_PATTERNS = [
    r"^local_test_log_.*\.txt$",
    r".*_DGIWG_Report.*\.(html|json)$",
    r"^DGIWG_GPKG_FINAL_REPORT\.(html|csv)$",
    r"^make_test_gpkgs\.py$",
    # old-version launchers — the staged folder keeps ONLY the current one
    r"^DGIWG_Validator_v\d+_\d+\.py$",
]


def _excluded(fname: str) -> bool:
    return any(re.match(p, fname) for p in EXCLUDE_FILE_PATTERNS)


def main() -> None:
    print(f"Packaging {RELEASE_NAME} (pre-release)")
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE, exist_ok=True)

    copied = 0
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
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
            f"Version   : {VERSION} (pre-release)\n"
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
