#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
package_release_v0.30.18.py  --  Automated release packager for
GeoPackage Creator v0.30.18.

Creates a clean, distributable ZIP of the project (excluding caches, build
artifacts, logs, temporary files, archived/superseded material, and dev-only
QA tooling), writes a RELEASE_INFO file recording the version and the exact
contents, and drops both into a `release_dist/` folder.

Renamed from package_release_v0.30.16.py per this project's existing
convention. Every prior packager (package_release_v0.30.6.py through
package_release_v0.30.16.py) is left in place, unchanged, wherever it
already was.

v0.30.18 deliverables verified present before packaging:
  - core/config.py TOOL_VERSION == "0.30.18".
  - core/metadata_handler.py still carries the libxml2 ABI fail-fast guard
    (_verify_libxml2_abi) from v0.30.13.
  - environment.yml still pins gdal=3.13.2, unchanged since v0.30.14, and
    now also installs ttkbootstrap==2.2.0 via its pip: section (v0.30.18).
  - packaging/GeoPackageCreator.spec bundles the CURRENT DGIWG validator
    folder (DGIWG_GeoPackage_Validator_v1.58) and does NOT still reference
    the deleted DGIWG_Validator_v1_55_updated folder - this exact drift
    broke the v0.30.17 release's build spec and is checked for explicitly
    below so it cannot silently recur.
  - CHANGELOG_v0.30.18.md (at changelogs/) and the VERSION.txt entry both
    exist.

WHAT CHANGED FROM package_release_v0.30.16.py (beyond the version bump):
  - REQUIRED_TOP_LEVEL no longer requires archive/. CHANGELOG_v0.30.16.md
    described archive/ (and release_dist/, and dev_tools/) as created by
    that release's reorganization; as of this snapshot only dev_tools/
    (rebuilt fresh in v0.30.18, see CHANGELOG_v0.30.18.md) actually exists.
    archive/ is not fabricated as an empty placeholder just to satisfy a
    check - if it does not exist, packaging should not pretend otherwise.
  - REQUIRED_FILES / CONTENT_CHECKS updated for v0.30.18: the changelog
    path, the version strings, and two new checks guarding the exact two
    bugs this release fixed (the DGIWG validator spec path, and the
    ttkbootstrap dependency being present in requirements.txt/
    environment.yml) so a future release cannot silently reintroduce
    either one.
  - The stale-GDAL-pin cross-file check now also covers
    packaging/build_windows.ps1, which was found still pinning gdal=3.11.4
    (unrelated to the 3.13.1/3.13.2 history, but the same class of drift)
    and fixed in v0.30.18.

Run from the project root (the folder that contains core/, packaging/, etc.):

    python package_release_v0.30.18.py

Output:
    release_dist/GeoPackage_Creator_v0.30.18.zip
    release_dist/RELEASE_INFO_v0.30.18.txt
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

VERSION = "0.30.18"
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
    # zip "close to a release version" means leaving it out. Neither
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
    "geopackage_creator_gui.py",
    "packaging/GeoPackageCreator.spec",
    "tests/test_gdb_domains.py",
    "requirements.txt",
    "environment.yml",
    "changelogs/CHANGELOG_v0.30.18.md",
    "VERSION.txt",
    "docs/USER_MANUAL.md",
    "README.md",
]

# (path, substring, why) - content assertions run before packaging.
CONTENT_CHECKS = [
    (
        "core/config.py",
        'TOOL_VERSION = "0.30.18"',
        "the project version stamp matching this release",
    ),
    (
        "core/__init__.py",
        '__version__ = "0.30.18"',
        "the core package version stamp",
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
        "confirms the shipped GUI file actually is the v0.30.18 redesign, "
        "not an older ttk-only copy",
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
        "GeoPackage Creator v0.30.18",
        "the v0.30.18 release header",
    ),
]

# Fails packaging outright if the OLD, deleted validator folder is still
# referenced anywhere the build spec would act on it - this exact drift
# (spec pointing at a folder that no longer exists) broke the v0.30.17
# release's PyInstaller build. Checked separately from CONTENT_CHECKS
# because this one must be ABSENT, not present.
FORBIDDEN_CONTENT_CHECKS = [
    (
        "packaging/GeoPackageCreator.spec",
        "DGIWG_Validator_v1_55_updated",
        "that folder was deleted in the v0.30.16 reorganization - a spec "
        "that still names it will fail its PyInstaller build (or silently "
        "bundle a stale copy if one happens to exist on the build machine)",
    ),
]

# Top-level entries the tree must have, confirming this is a real project
# checkout before packaging. archive/ deliberately NOT required here - see
# the module docstring's "WHAT CHANGED" note.
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
                "v0.30.18 tree?"
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
                "tree is not v0.30.18."
            )

    # FORBIDDEN_CONTENT_CHECKS and the stale-pin scan below only look at
    # CODE lines, not comments - both this script's own explanatory
    # comments (e.g. build_windows.ps1's "was gdal=3.11.4 through v0.30.17")
    # and CHANGELOG-style prose legitimately need to mention an old,
    # deliberately-superseded value when explaining why it changed. A line
    # whose stripped text starts with a comment marker is skipped; this is a
    # heuristic (it will not catch a forbidden string embedded mid-line
    # after live code on the same line as a trailing comment), not a full
    # parser, but it is enough to tell "still the active value" apart from
    # "explaining what the old value used to be" for the file types this
    # project actually uses (Python '#', PowerShell '#', batch 'REM').
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
        "  GUI visual redesign on ttkbootstrap (theme bootstrap-light) -",
        "  new header, tabbed/scrollable layout, styled buttons, segmented",
        "  CRS-mode selector, toggle-switch report checkboxes. No",
        "  conversion logic changed. Also fixes packaging/",
        "  GeoPackageCreator.spec's DGIWG validator bundle path (broken",
        "  since v0.30.17), packaging/build_windows.ps1's stale GDAL pin,",
        "  and version/changelog bookkeeping gaps found during a",
        "  release-readiness review. See CHANGELOG_v0.30.18.md.",
        "",
        "STILL OPEN - read before shipping:",
        "  The libxml2/GDAL ABI mismatch behind the last known real-machine",
        "  DO NOT SHIP verdict (CHANGELOG_v0.30.15.md) is not independently",
        "  re-verified by this packaging step - it only checks the source",
        "  tree, not a live GDAL/lxml pair. Run",
        "  dev_tools\\run_release_check_v0.30.18.bat on the real machine",
        "  first.",
        "",
        "Contents:",
    ]
    lines += [f"  {rel.as_posix()}" for rel in files]
    info_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"  Info   : {info_path}")
    print(f"  SHA-256: {digest}")
    print()
    print("[OK] Release package created.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
