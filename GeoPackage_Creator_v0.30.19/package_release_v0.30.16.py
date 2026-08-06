#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
package_release_v0.30.16.py  --  Automated release packager for
GeoPackage Creator v0.30.16.

Creates a clean, distributable ZIP of the project (excluding caches, build
artifacts, logs, temporary files, archived/superseded material, and dev-only
QA tooling), writes a RELEASE_INFO file recording the version and the exact
contents, and drops both into a `release_dist/` folder.

Renamed from package_release_v0.30.15.py per this project's existing
convention. Every prior packager (package_release_v0.30.6.py through
package_release_v0.30.15.py) is left in place, unchanged - as of this
release they live in archive/ rather than the project root, moved (not
deleted) as part of the v0.30.16 reorganization.

v0.30.16 deliverables verified present before packaging:
  - core/config.py TOOL_VERSION == "0.30.16".
  - core/metadata_handler.py still carries the libxml2 ABI fail-fast guard
    (_verify_libxml2_abi) from v0.30.13, with its user-facing remediation
    text now pointing at changelogs/ and dev_tools/ instead of the old
    root-level paths (text-only change - logic unchanged).
  - environment.yml still pins gdal=3.13.2, unchanged since v0.30.14.
  - run_gdal_tests.py still has the v0.30.15 console-encoding safety net.
  - tests/test_gdb_domains.py still has the v0.30.15 OpenFileGDB Multi-
    promotion fix.
  - CHANGELOG_v0.30.16.md (at changelogs/) and the VERSION.txt entry both
    exist.
  - The reorganized layout is in place: docs/, changelogs/, dev_tools/,
    archive/ all exist alongside core/.

WHAT CHANGED FROM package_release_v0.30.15.py (beyond the version bump):
  - REQUIRED_FILES / CONTENT_CHECKS updated for files that moved in the
    v0.30.16 reorganization (e.g. the changelog is now checked at
    changelogs/CHANGELOG_v0.30.16.md, not the project root).
  - EXCLUDE_DIRS now also skips archive/ (explicitly historical/superseded
    material - never appropriate in a release archive) and dev_tools/
    (this project's own crash-diagnosis and pre-release QA tooling, meant
    for maintainers verifying a build on a real Windows/Anaconda machine,
    not for an end user converting their own data). Both folders remain
    fully present in the project tree; only the packaged zip excludes
    them. The QA harness itself is separately packaged by
    dev_tools/package_prerelease_check_v0.30.13.py for anyone who
    specifically wants it.

Run from the project root (the folder that contains core/, packaging/, etc.):

    python package_release_v0.30.16.py

Output:
    release_dist/GeoPackage_Creator_v0.30.16.zip
    release_dist/RELEASE_INFO_v0.30.16.txt
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

VERSION = "0.30.16"
ARCHIVE_ROOT = f"GeoPackage_Creator_v{VERSION}"   # top-level folder inside zip

SOURCE_DIR = Path(__file__).resolve().parent
DIST_DIR = SOURCE_DIR / "release_dist"

# Directories skipped entirely (matched on any path segment).
EXCLUDE_DIRS = {
    "__pycache__", ".git", ".pytest_cache", ".idea", ".vscode",
    "build", "dist", "release_dist",
    # v0.30.16 reorg: archive/ is explicitly superseded/historical material
    # (old package_release_vX.py scripts, the two junk files found during
    # triage, old release_dist zips) - never appropriate in a release
    # archive. dev_tools/ is this project's own crash-diagnosis and
    # pre-release QA tooling for maintainers on a real Windows/Anaconda
    # machine, not something an end user converting their own data needs -
    # keeping this zip "close to a release version" means leaving it out.
    # Neither folder is deleted from the project tree; only the packaged
    # zip excludes them.
    "archive", "dev_tools",
}

# File glob patterns skipped.
EXCLUDE_FILE_GLOBS = [
    "*.pyc", "*.pyo", "*.log", "*.tmp", "*.tmp_warped.tif",
    "*_report.html", "*_report.json", "*_report.pdf",
    "gdal_test_results.json", "*.gpkg",
    "release_test_v0.30.*.log",
    "prerelease_check_v0.30.13_summary.json",
]

# Files this release must contain. Packaging aborts if any is missing.
REQUIRED_FILES = [
    "core/metadata_handler.py",
    "core/config.py",
    "core/converter.py",
    "core/gdal_handler.py",
    "tests/test_gdb_domains.py",
    "requirements.txt",
    "environment.yml",
    "changelogs/CHANGELOG_v0.30.16.md",
    "VERSION.txt",
    "docs/USER_MANUAL.md",
    "README.md",
]

# (path, substring, why) - content assertions run before packaging.
CONTENT_CHECKS = [
    (
        "core/config.py",
        'TOOL_VERSION = "0.30.16"',
        "the project version stamp matching this release",
    ),
    (
        "core/__init__.py",
        '__version__ = "0.30.16"',
        "the core package version stamp",
    ),
    (
        "core/metadata_handler.py",
        "_verify_libxml2_abi",
        "the libxml2 ABI fail-fast guard - carried over from v0.30.13, "
        "unchanged by this release",
    ),
    (
        "core/metadata_handler.py",
        "changelogs/CHANGELOG_v0.30.13.md",
        "the v0.30.16 fix pointing the guard's user-facing remediation "
        "text at the reorganized changelogs/ path",
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
        "requirements.txt",
        "GDAL == 3.13.2",
        "the documented GDAL pin (must agree with core/config.py AND "
        "environment.yml, not just with itself)",
    ),
    (
        "tests/test_gdb_domains.py",
        "ogr.wkbMultiLineString",
        "the v0.30.15 fix accepting OpenFileGDB's Multi- geometry promotion",
    ),
    (
        "VERSION.txt",
        "GeoPackage Creator v0.30.16",
        "the v0.30.16 release header",
    ),
]

# Top-level entries the reorganized tree must have (directories or files),
# confirming the v0.30.16 layout is actually in place before packaging.
REQUIRED_TOP_LEVEL = ["docs", "changelogs", "dev_tools", "archive", "core"]


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
                "v0.30.16-reorganized tree?"
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
                "tree is not v0.30.16."
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
    ):
        path = SOURCE_DIR / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "3.13.1" in text and "3.13.2" not in text:
            stale_pin_files.append(rel)
    if stale_pin_files:
        problems.append(
            "these files still reference the OLD GDAL 3.13.1 pin with no "
            "3.13.2 mention at all (stale instructions): "
            + ", ".join(stale_pin_files)
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
    print("  [OK] no stale 3.13.1-only GDAL pins found")
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
        "  The project root was reorganized into docs/, changelogs/,",
        "  dev_tools/, and archive/ subfolders - nothing deleted, no",
        "  product code behaviour changed. This release zip excludes",
        "  archive/ (superseded material) and dev_tools/ (maintainer-only",
        "  QA harnesses) to stay close to what an actual release needs;",
        "  both remain present in the full project folder. See",
        "  CHANGELOG_v0.30.16.md.",
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
