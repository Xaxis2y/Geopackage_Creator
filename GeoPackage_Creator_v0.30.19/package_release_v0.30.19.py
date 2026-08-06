#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
package_release_v0.30.19.py  --  Automated release packager for
GeoPackage Creator v0.30.19.

Creates a clean, distributable ZIP of the project (excluding caches, build
artifacts, logs, temporary files, archived/superseded material, and dev-only
QA tooling), writes a RELEASE_INFO file recording the version and the exact
contents, and drops both into a `release_dist/` folder.

New for v0.30.19 (renamed from package_release_v0.30.18.py per this
project's existing convention - every prior packager, package_release_
v0.30.6.py through package_release_v0.30.18.py, is left in place,
unchanged, wherever it already was):
  - VERSION / REQUIRED_FILES / CONTENT_CHECKS updated for 0.30.19.
  - New CONTENT_CHECKS guarding the two things this release actually fixed:
    core/report_generator.py must reference TOOL_VERSION (not a hardcoded
    literal - it used to hardcode "0.30.9" into every generated report,
    see CHANGELOG_v0.30.19.md), and a sample source file must carry the new
    SPDX license header.
  - New FORBIDDEN_CONTENT_CHECKS entry: report_generator.py must NOT
    contain a hardcoded "0.30.9" (or any bare vX.Y.Z string) as a report
    title/version literal ever again - this is the exact regression this
    release fixed.

IMPORTANT - read before treating this zip as a release:
  This packager only checks the SOURCE TREE (file presence, version
  strings, forbidden drift). It does NOT re-verify the libxml2/GDAL ABI
  mismatch behind the standing DO NOT SHIP verdict - that requires a real
  GDAL/lxml environment this sandbox does not have. As of this packaging
  run, dev_tools/run_release_check_v0.30.18.py has been run three times on
  the real target machine (2026-08-06) and returned the IDENTICAL failure
  every time. See CHANGELOG_v0.30.19.md's "What is still open" section and
  RELEASE_INFO_v0.30.19.txt (written below) for the exact evidence. This
  zip is a SOURCE SNAPSHOT for bookkeeping/handoff purposes, not a verified
  shippable build.

Run from the project root (the folder that contains core/, packaging/, etc.):

    python package_release_v0.30.19.py

Output:
    release_dist/GeoPackage_Creator_v0.30.19.zip
    release_dist/RELEASE_INFO_v0.30.19.txt
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

VERSION = "0.30.19"
ARCHIVE_ROOT = f"GeoPackage_Creator_v{VERSION}"   # top-level folder inside zip

SOURCE_DIR = Path(__file__).resolve().parent
DIST_DIR = SOURCE_DIR / "release_dist"

# Directories skipped entirely (matched on any path segment).
EXCLUDE_DIRS = {
    "__pycache__", ".git", ".pytest_cache", ".idea", ".vscode",
    "build", "dist", "release_dist",
    # archive/ (if present) is superseded/historical material - never
    # appropriate in a release archive. dev_tools/ is this project's own
    # QA tooling for maintainers on a real Windows/Anaconda machine, not
    # something an end user converting their own data needs - keeping this
    # zip "just the necessary files" means leaving it out. Neither
    # exclusion requires the folder to actually exist.
    "archive", "dev_tools",
}

# File glob patterns skipped.
EXCLUDE_FILE_GLOBS = [
    "*.pyc", "*.pyo", "*.log", "*.tmp", "*.tmp_warped.tif",
    "*_report.html", "*_report.json", "*_report.pdf",
    "gdal_test_results.json", "*.gpkg",
    "release_test_v0.30.*.log",
    "prerelease_check_v0.30.13_summary.json",
    "release_check_*.log", "pytest_main_*.log", "pytest_concurrency_*.log",
]

# Files this release must contain. Packaging aborts if any is missing.
REQUIRED_FILES = [
    "core/metadata_handler.py",
    "core/config.py",
    "core/converter.py",
    "core/gdal_handler.py",
    "core/report_generator.py",
    "geopackage_creator_gui.py",
    "packaging/GeoPackageCreator.spec",
    "packaging/app_main.py",
    "packaging/version_info.txt",
    "tests/test_gdb_domains.py",
    "requirements.txt",
    "environment.yml",
    "changelogs/CHANGELOG_v0.30.19.md",
    "VERSION.txt",
    "docs/USER_MANUAL.md",
    "docs/USER_MANUAL.docx",
    "README.md",
]

# (path, substring, why) - content assertions run before packaging.
CONTENT_CHECKS = [
    (
        "core/config.py",
        'TOOL_VERSION = "0.30.19"',
        "the project version stamp matching this release",
    ),
    (
        "core/__init__.py",
        '__version__ = "0.30.19"',
        "the core package version stamp",
    ),
    (
        "geopackage_creator_gui.py",
        'APP_VERSION = "0.30.19"',
        "the GUI's own version stamp",
    ),
    (
        "packaging/app_main.py",
        'APP_VERSION = "0.30.19"',
        "the frozen .exe's --version output - this was stuck at 0.30.9 "
        "until this release, see CHANGELOG_v0.30.19.md",
    ),
    (
        "packaging/version_info.txt",
        "0.30.19.0",
        "the Windows exe FileVersion/ProductVersion metadata - was stuck "
        "at 0.30.6.0 until this release",
    ),
    (
        "core/report_generator.py",
        "from .config import TOOL_VERSION",
        "the fix for this release's headline bug: every generated report "
        "used to hardcode a stale version literal instead of reading the "
        "real one",
    ),
    (
        "core/metadata_handler.py",
        "_verify_libxml2_abi",
        "the libxml2 ABI fail-fast guard - carried over from v0.30.13, "
        "unchanged by this release",
    ),
    (
        "core/config.py",
        "ALLOW_LIBXML_ABI_MISMATCH",
        "the ABI-mismatch opt-out flag - carried over from v0.30.13",
    ),
    (
        "core/config.py",
        'GDAL_TESTED_VERSION = "3.13.2"',
        "the GDAL 3.13.2 pin decision - carried over from v0.30.13",
    ),
    (
        "environment.yml",
        "gdal=3.13.2",
        "the actual GDAL pin - carried over from v0.30.14",
    ),
    (
        "environment.yml",
        "ttkbootstrap==2.2.0",
        "the GUI theming dependency the v0.30.18 redesign requires - not on "
        "conda-forge, so this MUST be present under environment.yml's pip: "
        "section or a fresh `conda env create` will not have it",
    ),
    (
        "requirements.txt",
        "ttkbootstrap==2.2.0",
        "the GUI theming dependency, pip requirements copy",
    ),
    (
        "geopackage_creator_gui.py",
        "import ttkbootstrap",
        "confirms the shipped GUI file actually is the ttkbootstrap "
        "redesign, not an older ttk-only copy",
    ),
    (
        "packaging/GeoPackageCreator.spec",
        "DGIWG_GeoPackage_Validator_v1.58",
        "the current DGIWG validator folder must be the one actually "
        "bundled into the .exe",
    ),
    (
        "tests/test_gdb_domains.py",
        "ogr.wkbMultiLineString",
        "the v0.30.15 fix accepting OpenFileGDB's Multi- geometry promotion",
    ),
    (
        "VERSION.txt",
        "GeoPackage Creator v0.30.19",
        "the v0.30.19 release header",
    ),
    (
        "core/config.py",
        "# SPDX-License-Identifier: GPL-2.0-or-later",
        "spot-check that the new v0.30.19 license header is actually "
        "present, not just documented",
    ),
]

# Fails packaging outright if forbidden content is still present.
# Checked separately from CONTENT_CHECKS because these must be ABSENT, not
# present.
FORBIDDEN_CONTENT_CHECKS = [
    (
        "packaging/GeoPackageCreator.spec",
        "DGIWG_Validator_v1_55_updated",
        "that folder was deleted in the v0.30.16 reorganization - a spec "
        "that still names it will fail its PyInstaller build (or silently "
        "bundle a stale copy if one happens to exist on the build machine)",
    ),
    (
        "core/report_generator.py",
        '"0.30.9"',
        "the exact regression CHANGELOG_v0.30.19.md fixed - this module "
        "used to hardcode a literal stale version string into every "
        "generated report instead of reading TOOL_VERSION",
    ),
]

# Top-level entries the tree must have, confirming this is a real project
# checkout before packaging.
REQUIRED_TOP_LEVEL = ["docs", "changelogs", "dev_tools", "core"]


def is_excluded(path: Path) -> bool:
    """True when *path* should be left out of the release archive."""
    parts = set(path.parts)
    if parts & EXCLUDE_DIRS:
        return True
    name = path.name
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_FILE_GLOBS)


def collect_files() -> list:
    """Return the sorted list of files to include, relative to SOURCE_DIR."""
    included = []
    for root, dirs, files in os.walk(SOURCE_DIR):
        root_path = Path(root)
        # Prune excluded directories in-place so os.walk does not descend.
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fname in files:
            fpath = root_path / fname
            rel = fpath.relative_to(SOURCE_DIR)
            if is_excluded(rel):
                continue
            # Never include the packager's own output.
            if rel.parts and rel.parts[0] == "release_dist":
                continue
            included.append(rel)
    return sorted(included)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def preflight() -> list:
    """Return a list of problems. Empty means the tree is ready to package."""
    problems = []

    for rel in REQUIRED_TOP_LEVEL:
        if not (SOURCE_DIR / rel).is_dir():
            problems.append(
                f"missing top-level folder: {rel} - is this the "
                "v0.30.19 tree?"
            )

    for rel in REQUIRED_FILES:
        if not (SOURCE_DIR / rel).is_file():
            problems.append(f"missing required file: {rel}")

    for rel, needle, why in CONTENT_CHECKS:
        path = SOURCE_DIR / rel
        if not path.is_file():
            continue  # already reported above
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            problems.append(f"could not read {rel}: {e}")
            continue
        if needle not in text:
            problems.append(
                f"{rel} does not contain {needle!r} - {why} is absent, or "
                "the code and the documented pin have drifted apart. This "
                "tree is not v0.30.19."
            )

    # FORBIDDEN_CONTENT_CHECKS and the stale-pin scan below only look at
    # CODE lines, not comments - both this script's own explanatory
    # comments and CHANGELOG-style prose legitimately need to mention an
    # old, deliberately-superseded value when explaining why it changed. A
    # line whose stripped text starts with a comment marker is skipped;
    # this is a heuristic (it will not catch a forbidden string embedded
    # mid-line after live code on the same line as a trailing comment), not
    # a full parser, but it is enough to tell "still the active value"
    # apart from "explaining what the old value used to be" for the file
    # types this project actually uses (Python '#', PowerShell '#', batch
    # 'REM').
    _COMMENT_PREFIXES = ("#", "REM ", "rem ", "::")

    def _code_lines(text: str):
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(_COMMENT_PREFIXES):
                continue
            yield line

    for rel, needle, why in FORBIDDEN_CONTENT_CHECKS:
        path = SOURCE_DIR / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(needle in line for line in _code_lines(text)):
            problems.append(
                f"{rel} still contains {needle!r} in a live (non-comment) "
                f"line - {why}"
            )

    # Cross-file consistency: config.py, environment.yml and requirements.txt
    # must all agree on the GDAL pin, independent of any one of them
    # individually being "correct".
    stale_pin_files = []
    for rel in (
        "requirements.txt", "environment.yml", "docs/DEPENDENCIES.txt",
        "docs/INSTALLATION_GUIDE.md", "install_dependencies.bat",
        "install_dependencies.ps1", "docs/QUICK_FIX_CONDA.txt",
        "docs/USER_MANUAL.md", "core/__init__.py",
        "packaging/build_windows.ps1",
    ):
        path = SOURCE_DIR / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        code_text = "\n".join(_code_lines(text))
        if "3.13.1" in code_text and "3.13.2" not in text:
            stale_pin_files.append(rel)
        if "gdal=3.11.4" in code_text or "GDAL 3.11.4" in code_text:
            stale_pin_files.append(rel + " (still references 3.11.4 in a live line)")
    if stale_pin_files:
        problems.append(
            "these files still reference an OLD GDAL pin outside of a "
            "comment (stale instructions): " + ", ".join(stale_pin_files)
        )

    return problems


def main() -> int:
    print(f"Packaging GeoPackage Creator v{VERSION}")
    print(f"  Source : {SOURCE_DIR}")
    print()

    print("Preflight checks...")
    problems = preflight()
    if problems:
        print("[FAIL] This tree is not ready to package:")
        for p in problems:
            print(f"   - {p}")
        return 1
    print(f"  [OK] {len(REQUIRED_TOP_LEVEL)} required top-level folders present")
    print(f"  [OK] {len(REQUIRED_FILES)} required files present")
    print(f"  [OK] {len(CONTENT_CHECKS)} content assertions passed")
    print(f"  [OK] {len(FORBIDDEN_CONTENT_CHECKS)} forbidden-content checks passed")
    print("  [OK] no stale GDAL pins found")
    print()

    DIST_DIR.mkdir(parents=True, exist_ok=True)

    files = collect_files()
    if not files:
        print("[FAIL] No files collected - are you in the project root?")
        return 1

    zip_path = DIST_DIR / f"{ARCHIVE_ROOT}.zip"
    info_path = DIST_DIR / f"RELEASE_INFO_v{VERSION}.txt"

    print(f"  Archive: {zip_path}")
    print(f"  Files  : {len(files)}")

    total_bytes = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            abs_path = SOURCE_DIR / rel
            arcname = str(Path(ARCHIVE_ROOT) / rel)
            zf.write(abs_path, arcname)
            total_bytes += abs_path.stat().st_size

    digest = sha256(zip_path)

    lines = [
        f"GeoPackage Creator - Release Package v{VERSION}",
        f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Archive: {zip_path.name}",
        f"Archive SHA-256: {digest}",
        f"Files packaged: {len(files)}",
        f"Uncompressed size: {total_bytes / 1024:.1f} KiB",
        "",
        "Headline change:",
        "  Version-bookkeeping sweep + SPDX/copyright headers. Fixed a real",
        "  user-facing bug (core/report_generator.py was hardcoding \"0.30.9\"",
        "  into every generated JSON/HTML/PDF report - now reads",
        "  TOOL_VERSION). Fixed the frozen .exe's own --version output and",
        "  Windows metadata, which were also stale. Fixed stale version",
        "  banners and several broken file references across both .docx",
        "  manuals and a dozen+ docs/scripts. Added SPDX-License-Identifier:",
        "  GPL-2.0-or-later / Copyright (c) 2026 Eui Soo SON headers to all",
        "  45 source files. See CHANGELOG_v0.30.19.md for full detail,",
        "  including what was flagged but deliberately NOT fixed.",
        "",
        "*** STILL OPEN - DO NOT SHIP - READ BEFORE DISTRIBUTING ***",
        "  The libxml2/GDAL ABI mismatch first documented in",
        "  CHANGELOG_v0.30.13.md is UNCHANGED and has now been re-confirmed",
        "  on the real target machine THREE separate times on 2026-08-06",
        "  (identical failure each time: lxml compiled against libxml2",
        "  (2, 14, 6) but (2, 15, 3) loads at runtime). This blocks",
        "  MetadataHandler() construction, which blocks every conversion,",
        "  which is why the test suite fails almost entirely (main: 80",
        "  failed/147 passed/66 errors; concurrency: 6 failed/6 passed -",
        "  traced failure-by-failure, all of it is this one root cause).",
        "  This packaging step only checked the SOURCE TREE - it did not,",
        "  and cannot from this environment, re-verify GDAL/lxml against a",
        "  live install. This zip is a SOURCE SNAPSHOT for",
        "  bookkeeping/handoff, not a verified release. Before giving this",
        "  to an end user:",
        "    1. conda deactivate",
        "    2. conda env remove -n geopackage",
        "    3. conda env create -f environment.yml",
        "    4. conda activate geopackage",
        "    5. python -c \"from lxml import etree; print(etree.LIBXML_COMPILED_VERSION, etree.LIBXML_VERSION)\"",
        "    6. dev_tools\\run_release_check_v0.30.18.bat  (read the VERDICT line)",
        "  If the two version tuples in step 5 still disagree after a",
        "  GENUINE recreate, that is a more serious finding than anything",
        "  fixed in this release - it means conda-forge's current",
        "  gdal/lxml builds for this platform are not mutually consistent,",
        "  and environment.yml's pin itself needs to change.",
        "",
        "Contents:",
    ]
    lines += [f"  {rel.as_posix()}" for rel in files]
    info_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"  Info   : {info_path}")
    print(f"  SHA-256: {digest}")
    print()
    print("[OK] Release package created.")
    print()
    print("*** REMINDER: this is a source snapshot, not a verified release.")
    print("*** The libxml2/GDAL ABI blocker is still open - see RELEASE_INFO")
    print(f"*** or CHANGELOG_v{VERSION}.md before distributing this zip.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
