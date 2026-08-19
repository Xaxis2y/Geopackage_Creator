# CHANGELOG - GeoPackage Creator v0.30.19

**Release date:** 2026-08-06
**Previous:** v0.30.18 (GUI visual redesign on ttkbootstrap - see
`CHANGELOG_v0.30.18.md`)
**Theme:** Version-bookkeeping sweep + SPDX/copyright headers. NOT a fix for
the open libxml2/GDAL ABI blocker - see "What is still open" below, which
carries forward unchanged from v0.30.18.

---

## Context

`dev_tools/run_release_check_v0.30.18.py` was run on the real Windows/
Anaconda machine three times on 2026-08-06 (10:50, 11:29, and once more
just before this release was packaged). All three runs returned the
IDENTICAL verdict: `DO NOT SHIP - 4 stage(s) failed: environment.
libxml2_abi, core.metadata_handler_construction, pytest.main, pytest.
concurrency`. The three release_check/pytest_main/pytest_concurrency log
files are byte-identical in size across runs, which is strong evidence the
`geopackage` conda environment was not actually recreated between them (see
"What is still open").

While confirming v0.30.18's own bookkeeping was complete, several more
drifted references and one real functional bug turned up - this release is
that cleanup pass, done before moving on to actually chasing the ABI
mismatch.

## FIX: core/report_generator.py (real, user-facing bug)

Every JSON/HTML/PDF conversion report this tool generates was hardcoding
`"0.30.9"` in four places: the module docstring, the JSON `'version'`
field, the PDF title (`"GeoPackage Creator - Conversion Report v0.30.9"`),
and the HTML `<h2>`/footer. This is not a stale comment - these strings
ship inside every report a user produces, so every report generated since
v0.30.10 has been mislabeled. Fixed to import `TOOL_VERSION` from
`core.config` and interpolate it in all four places, so this cannot drift
out of sync with the tool's actual version again. Verified end-to-end
(stubbed `osgeo`): a freshly generated JSON report's `'version'` field and
a freshly generated HTML report's `<h2>`/footer both now read `0.30.19`,
with zero occurrences of `0.30.9` in either output.

## FIX: packaging/app_main.py, packaging/version_info.txt (real bug)

The frozen `.exe`'s own `--version` output (`app_main.py`'s `APP_VERSION`)
was still `"0.30.9"`, and the Windows Explorer Properties/Details tab
metadata (`version_info.txt`'s `filevers`/`prodvers`/`FileVersion`/
`ProductVersion`) was still `0.30.6` - internally inconsistent with each
other even before this fix. A real build off the unfixed tree would have
shipped a `.exe` that reports the wrong version both ways a user might
check it.

## FIX: docs/USER_MANUAL.docx, packaging/GeoPackage_Creator_Windows_Packaging_Manual.docx

Both Word manuals had stale version banners predating v0.30.18
(`USER_MANUAL.docx`: "Version 0.26.0 | June 9, 2026" in both the title page
and, separately, the running page header - the header lives in a distinct
XML part, `header1.xml`, and was only caught by rendering to PDF and
visually inspecting after the title-page fix looked complete;
`Windows_Packaging_Manual.docx`: "Application version 0.28.0", three
occurrences of an installer filename with the same stale version, an
example `GDAL 3.13.1` that should read `3.13.2`, and a stale DGIWG
validator folder name - `DGIWG_Validator_v1_55_updated` instead of
`DGIWG_GeoPackage_Validator_v1.58` - in its troubleshooting table, the same
drift class already fixed in the `.spec` file back in v0.30.17/18). Both
manuals were fixed to v0.30.18 first, then bumped again to v0.30.19 as part
of this release, each time validated via the docx skill's XSD validator and
visually confirmed via a full page-by-page PDF render.

## FIX: stale version banners and broken file references (docs + scripts)

- `docs/USER_MANUAL.md`, `docs/GDAL_INSTALLATION.txt`: stale "current
  version" banners (`0.30.9`).
- `docs/QUICKSTART.md`: stale banner (`v0.26`) and a reference to a
  nonexistent file, `GeoPackage_Creator_User_Manual_v0.26.docx` - corrected
  to point at the real `docs/USER_MANUAL.docx`.
- `docs/QUICK_FIX_CONDA.txt`: a copy-paste example `cd` path referencing a
  folder name (`GeoPackage_Creator_v0.26.0`) that has never matched this
  machine's actual folder (`GeoPackage_Creator_v0.30.16`).
- `docs/GDAL_INSTALLATION.txt`: separately, a generic walkthrough path
  (`C:\Users\YourName\Documents\Google_AI\Geopackage_Creator\
  Geopackage_Creator_v0.26\Geopackage_Creator`) that did not match this
  project's structure on any axis (wrong root folder, doubled project name,
  stale version) - straightened out to a plausible generic example.
- `docs/GUI_USAGE_GUIDE.md`: pointed at `CHANGELOG_v0.26.2.md` as "the
  latest changes".
- `packaging/BUILD_WINDOWS.md`: stale installer filename version (twice).
- `START_HERE.bat`, `Anaconda_Start.bat`: stale banners (`v0.27.0` /
  `v0.30.9`). `Anaconda_Start.bat` also listed two dev_tools scripts,
  `release_test_v0.30.6.py` and `selftest_conversion.py`, that do not exist
  anywhere in this tree - replaced with the one QA script that actually
  exists, `dev_tools\run_release_check_v0.30.18.py`.
- `environment.yml`: same two nonexistent-script references (in comments),
  plus a reference to `run_prerelease_check_v0.30.13.bat --recreate-env`,
  also nonexistent - all three corrected to the real script.
- `packaging/build_windows.ps1`, `packaging/GeoPackageCreator.spec`: stale
  header-comment version only (the functional GDAL-pin and validator-path
  fixes were already done in v0.30.18).
- `core/crs_converter.py`, `core/raster_support.py`: stale module docstring
  headers (`v0.26`, `v0.30.9`).
- `core/validation_gate.py`: a docstring example path combining a stale
  project-folder version and the same old validator folder name pattern
  fixed elsewhere (`../GeoPackage_Creator_v0.26.0/DGIWG_Validator_v1_56_
  updated` -> `../GeoPackage_Creator_v0.30.16/DGIWG_GeoPackage_
  Validator_v1.58`).
- `README.md`: version banner; the "Folder Contents" narrative corrected -
  it claimed `release_dist/` "does not currently exist," which stopped
  being true once the v0.30.18 packager was actually run; the tree diagram
  now lists `release_dist/` and points at `package_release_v0.30.19.py` as
  the current packager; added a "Release status" line under `## Version`
  stating plainly that this build is not shippable and why, rather than
  leaving that fact only in `VERSION.txt`.

All of the above were flagged as "stale current-version claim" versus
"legitimate historical narrative" individually - changelog-style comments
explaining what changed in a specific past version (`# v0.30.7: ...`,
`*(new in v0.30.18)*`, per-test docstrings citing the version a regression
was fixed in) were deliberately left untouched; only banners and references
asserting something about *now* were changed.

## NOT DONE (flagged, not fixed - bigger than a version bump)

- `docs/GETTING_STARTED.md` describes an installable-package layout
  (`pip install -e .`, `from geopackage_creator.core import ...`,
  `setup.py`) from a much earlier project phase. No `setup.py` or
  `pyproject.toml` exist anywhere in this tree; the GUI is not mentioned at
  all; the CLI is described as unbuilt "Phase 2" work despite
  `geopackage_creator.py` being the project's actual, long-shipped CLI.
  This is not stale in one place, it is a different project shape
  throughout - needs a decision (rewrite vs. delete vs. mark deprecated),
  not a version-string edit.
- `docs/ROADMAP_RASTER.md`'s "target: v0.28" has already passed (current
  version 0.30.19) without raster conversion shipping - the roadmap target
  needs a product decision, not a mechanical bump.
- `packaging/GeoPackage_Creator_Windows_Packaging_Manual.docx` and
  `packaging/BUILD_WINDOWS.md` both document an Inno Setup installer step
  (`packaging\installer\GeoPackageCreator.iss`, `ISCC.exe packaging\
  installer\GeoPackageCreator.iss`) that does not exist anywhere in this
  tree - there is no `packaging/installer/` folder at all.
  `build_windows.ps1` itself correctly calls this step "(optional)"; the
  docs should probably say the same, or the file should be added.

## NEW: SPDX license headers (licensing, not a bugfix)

Every `.py`/`.bat`/`.ps1` source file under `core/`, `tests/`, `dev_tools/`,
`packaging/`, and the project root - 45 files - now opens with:

```
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
```

(`REM`-prefixed for the 6 `.bat` files), matching the convention already
established throughout `DGIWG_GeoPackage_Validator_v1.58/`. `release_dist/`
(generated), `__pycache__/`, and the validator subfolder itself (already
headered) were left alone; docs/config files were deliberately out of
scope for this pass. Placement was adjusted per file so nothing broke:

- After the shebang, for the 5 files that have one
  (`geopackage_creator.py`, `geopackage_creator_gui.py`,
  `dev_tools/run_release_check_v0.30.18.py`, `package_release_v0.30.16.py`,
  `package_release_v0.30.18.py`).
- After `GeoPackageCreator.spec`'s `# -*- coding: utf-8 -*-` declaration,
  which per PEP 263 must stay on line 1.
- Inside `build_windows.ps1`'s existing `<# ... #>` comment-based-help
  block, right after the opening `<#`, so `Get-Help` still finds
  `.SYNOPSIS`/`.DESCRIPTION`.
- After `@echo off` (not before it) in all 6 `.bat` files - inserting
  ahead of `@echo off` would have echoed the two header lines to the
  console before echo suppression took effect.

Verified by recompiling all 35 in-scope `.py` files and live-importing
every `core` submodule under a stubbed `osgeo` in one process - all import
cleanly, and `report_generator`'s fix (above) still stamps the correct
version afterward.

## Files changed

| file | change |
|---|---|
| `core/report_generator.py` | real bug fix - reads `TOOL_VERSION` instead of a hardcoded stale string, in 4 places |
| `packaging/app_main.py`, `packaging/version_info.txt` | real bug fix - frozen `.exe` version metadata was stale/internally inconsistent |
| `docs/USER_MANUAL.docx`, `packaging/GeoPackage_Creator_Windows_Packaging_Manual.docx` | stale version banners (title + running header for USER_MANUAL), stale example GDAL version, stale validator folder name |
| `docs/USER_MANUAL.md`, `docs/QUICKSTART.md`, `docs/GDAL_INSTALLATION.txt`, `docs/QUICK_FIX_CONDA.txt`, `docs/GUI_USAGE_GUIDE.md`, `packaging/BUILD_WINDOWS.md` | stale version banners / broken references |
| `START_HERE.bat`, `Anaconda_Start.bat`, `environment.yml` | stale banners; references to 3 nonexistent dev_tools scripts corrected |
| `packaging/build_windows.ps1`, `packaging/GeoPackageCreator.spec` | stale header-comment version only |
| `core/crs_converter.py`, `core/raster_support.py`, `core/validation_gate.py` | stale docstring headers / example paths |
| `README.md` | version banner; folder-contents narrative corrected (`release_dist/` now exists); new "Release status" line |
| 45 `.py`/`.bat`/`.ps1` files across `core/`, `tests/`, `dev_tools/`, `packaging/`, root | new SPDX + copyright header |
| `core/config.py` | `TOOL_VERSION` -> `0.30.19` |
| `core/__init__.py` | `__version__` -> `0.30.19` |
| `geopackage_creator_gui.py`, `packaging/app_main.py` | `APP_VERSION` -> `0.30.19`; docstring/class banners updated |
| `VERSION.txt` | new v0.30.19 entry (prepended; all prior entries preserved verbatim) |
| `package_release_v0.30.19.py` | **new** - current release packager (`package_release_v0.30.18.py` left in place, unchanged, per this project's established convention) |

## Compatibility

Public API (`core.GeoPackageConverter` and friends) unchanged. CLI and GUI
behavior unchanged - this release touches version strings, comments,
documentation, and license headers only, plus the one `report_generator.py`
fix (which changes report *labeling*, not report *content* or structure).
Nothing here affects the conda environment or its pins.

## What is still open (unchanged from v0.30.18 - re-confirmed three times)

`core/metadata_handler.py`'s libxml2 ABI fail-fast guard still fires on the
real target machine: `lxml LIBXML_COMPILED_VERSION (2, 14, 6)` vs
`LIBXML_VERSION` at runtime `(2, 15, 3)` - the exact mismatch
`CHANGELOG_v0.30.13.md` first documented. This blocks `MetadataHandler()`
construction, which blocks every conversion, which cascades into the test
suite: main suite `80 failed, 147 passed, 12 deselected, 66 errors`;
concurrency suite `6 failed, 6 passed` - traced failure-by-failure, every
one of those 86 failures/errors is the same root cause. One unrelated
failure, `tests/test_critical_fixes.py::TestLockTimeout::
test_lock_timeout_prevents_indefinite_wait`, is not yet root-caused
(possibly just flakiness from its tight 0.1s timeout).

The fact that three separate runs on 2026-08-06 produced byte-identical log
file sizes is itself evidence: it strongly suggests the `geopackage` conda
environment was never actually recreated between runs, only re-tested. The
documented fix has not yet been confirmed to fail after a genuine
`conda env remove -n geopackage && conda env create -f environment.yml` -
only after re-running the check against what may still be the original,
already-drifted environment.

**This release is a source snapshot for bookkeeping/handoff purposes, not a
verified, shippable build.** Before distributing `release_dist/
GeoPackage_Creator_v0.30.19.zip` to an end user:

1. `conda deactivate`
2. `conda env remove -n geopackage`
3. `conda env create -f environment.yml`
4. `conda activate geopackage`
5. `python -c "from lxml import etree; print(etree.LIBXML_COMPILED_VERSION, etree.LIBXML_VERSION)"`
   - if the two tuples still disagree after a genuine recreate, that is a
     more serious finding than anything in this changelog: it means
     conda-forge's current `gdal`/`lxml` builds for this platform are not
     mutually consistent, and `environment.yml`'s pin itself needs to
     change, not just be reapplied.
6. `dev_tools\run_release_check_v0.30.18.bat`, and read the resulting
   `VERDICT` line.

## Verification

`python -m py_compile` passed for every changed `.py` file (35 files in the
copyright-header scope, plus `report_generator.py`, `app_main.py`,
`crs_converter.py`, `raster_support.py`, `validation_gate.py`
individually). `version_info.txt` re-parsed as valid Python syntax after
editing (it is `exec()`'d by PyInstaller, not imported). Every `core`
submodule was live-imported in one process under a stubbed `osgeo`,
confirming no import-order or `from __future__` placement issue was
introduced by the header insertion. Both `.docx` manuals were validated
with the docx skill's XSD validator and visually confirmed via full
page-by-page PDF renders (9 pages each) after every edit pass. None of
this exercises real GDAL, real libxml2, or real Windows Tk rendering - see
"What is still open" above for what actually would.
