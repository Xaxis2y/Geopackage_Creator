# CHANGELOG - GeoPackage Creator v0.30.16

**Release date:** 2026-08-05
**Previous:** v0.30.15 (run_gdal_tests.py encoding fix + test_gdb_domains.py fix)
**Theme:** project root reorganized into docs/, changelogs/, dev_tools/, and archive/ - no product code behaviour changed

---

## Context

The project root had grown to roughly 74 loose files: 18 `CHANGELOG_*.md`
files, 8 `package_release_vX.py` scripts, several diagnostic/QA harnesses
and their generated logs, and two unrelated junk files (a stray
pip-install console log saved as `6.0`, and a stale full-project backup
zip named `zissfcWB` from the v0.30.2/v0.30.3 era), on top of the normal
`core/`, `tests/`, and documentation content. This release reorganizes the
root into subfolders. Two clarifying questions were asked and answered
before starting: (1) whether test/diagnostic scripts should also move
into subfolders despite the extra risk of updating their internal path
logic - answered yes, full reorganization; (2) whether old/superseded
files should be deleted or archived - answered archived, nothing deleted.

`core/`, `packaging/`, `schemas/`, `tests/`, `DGIWG_Validator_v1_55_updated/`,
`release_dist/`, and the product entry points
(`geopackage_creator.py`, `geopackage_creator_gui.py`) stay at the root,
unchanged.

## New layout

```
docs/          user-facing documentation (manuals, guides, install notes)
changelogs/    every CHANGELOG_vX.Y.Z.md, CODE_REVIEW_v0.30.6.md, TEST_GUIDE_v0.24.md
dev_tools/     diagnostic/QA harnesses, not part of the shipped tool
archive/       superseded files, kept for history - nothing deleted
```

`VERSION.txt` stays at the root as the single, prepend-only consolidated
history. `README.md` stays at the root as the project's front door.

## FIX (dev_tools/ path bootstrap)

Every script moved into `dev_tools/` is now one directory level below the
project root, so each one's path-bootstrap logic was reviewed line by
line and split into two variables instead of one:

- The script's own directory (`HERE` / `SCRIPT_DIR` / `ROOT`, depending on
  the file) - kept for the script's own log output, and for references to
  sibling scripts that moved into `dev_tools/` together with it
  (`diagnose_crash_v0.30.12.py`, `run_gdal_tests.py`,
  `verify_lxml_threadsafety_v0.30.10.py`, `verify_concurrency_v0.30.9.py`
  all reference each other this way inside
  `run_prerelease_check_v0.30.13.py`, and stayed correct unchanged).
- A new `PROJECT_ROOT` one level up - now used everywhere that needs to
  resolve against the actual project: `sys.path.insert(0, ...)` before
  `from core import ...`, `SCHEMA_DIR` (`diagnose_crash_v0.30.12.py`,
  `verify_lxml_threadsafety_v0.30.10.py`), the pytest `tests` argument
  (`run_prerelease_check_v0.30.13.py`, `release_test_v0.30.6.py`), and the
  subprocess-child template in `verify_concurrency_v0.30.9.py`.

`selftest_conversion.py` previously had no path bootstrap at all - it
worked only because it happened to always run from the project root,
where Python's implicit "script's own directory" sys.path entry was
enough. It now has an explicit `PROJECT_ROOT` bootstrap.

`run_prerelease_check_v0.30.13.py`'s `preconditions` stage previously
checked a single flat list of required files/directories relative to its
own directory. That list is now split three ways: files at the real
project root, sibling scripts in `dev_tools/`, and the changelog (now at
`changelogs/CHANGELOG_v0.30.13.md`).

`run_prerelease_check_v0.30.13.bat` and `run_tests_v0.30.10.bat` got the
equivalent fix for batch: a `SCRIPT_DIR` (this file's own folder) and a
derived `PROJECT_DIR`/`..\` reference (the actual project root, needed for
`environment.yml` and `tests`).

## FIX (hardcoded packager filename)

`run_prerelease_check_v0.30.13.py`'s `release_packaging_preflight` stage
previously ran `package_release_v0.30.13.py` by a hardcoded filename. That
file is archived in this release (see below), which would have made this
stage silently report "not found" from v0.30.16 onward, and would have
needed the same manual fix at every future release regardless. Replaced
with a new `_find_latest_package_release_script()` helper that globs
`package_release_v*.py` at the project root and picks the highest
`(major, minor, patch)` by filename. The same helper backs the
`preconditions` stage's check that *some* current packager exists. Verified
directly: it correctly resolves to `package_release_v0.30.16.py` in the
reorganized tree.

## FIX (user-facing path references in shipped code)

Two comments and one **user-facing** message in `core/config.py` and
`core/metadata_handler.py` referenced `CHANGELOG_v0.30.13.md` and
`diagnose_crash_v0.30.12.log` by their old root-level paths. The message
matters most: `_verify_libxml2_abi()`'s `RuntimeError` text - the message
a real user sees the moment the ABI guard fires - told them to go read
those two files. Updated to `changelogs/CHANGELOG_v0.30.13.md` and
`dev_tools/diagnose_crash_v0.30.12.log`. This is the only change in this
release that touches a file inside `core/`, and it is text-only: no
logic, no control flow, no behaviour changed. `_verify_libxml2_abi()`
still does exactly what it did in v0.30.13.

## Archive (nothing deleted)

Moved into `archive/`, not deleted, per this release's explicit
instruction:

- `6.0` - confirmed via inspection to be stray `pip install` console
  output, accidentally saved as a file. No code value.
- `zissfcWB` - a stale full-project backup zip dated 2026-06-18
  (v0.30.2/v0.30.3 era). No ongoing code value.
- `diagnose_crash_v0.30.11.py` - superseded by `_v0.30.12.py`, which
  re-ran and corrected its bisection conclusions.
- `package_release_v0.30.6.py` through `package_release_v0.30.15.py` (8
  files) - each superseded by the next; `package_release_v0.30.15.py`
  joins this list now that `package_release_v0.30.16.py` exists,
  matching the same reasoning applied to every packager before it.
- `release_dist/GeoPackage_Creator_v0.30.13.zip` and `_v0.30.14.zip` (plus
  their `RELEASE_INFO` files) - moved to `archive/release_dist_old/`, so
  `release_dist/` at the root now holds only the current build.

## Release packaging

`package_release_v0.30.15.py` renamed to `package_release_v0.30.16.py`
per this project's existing convention (old packagers kept in place,
now inside `archive/`). Changes beyond the version bump:

- `REQUIRED_FILES` / `CONTENT_CHECKS` updated for the files that moved -
  e.g. `CHANGELOG_v0.30.16.md` is checked at `changelogs/CHANGELOG_v0.30.16.md`,
  not the root.
- `EXCLUDE_DIRS` now also skips `archive/` and `dev_tools/`. `archive/` is
  explicitly historical/superseded material - never appropriate in a
  release archive. `dev_tools/` is this project's own crash-diagnosis and
  pre-release QA tooling, meant for maintainers verifying a build on a
  real Windows/Anaconda machine, not for an end user converting their own
  data - keeping the release zip "close to a release version" (this
  release's own stated goal) meant leaving it out. Both folders remain
  fully present in the project tree itself; only the *packaged zip*
  excludes them. Anyone who wants the QA harness specifically already has
  `dev_tools/release_dist/GeoPackage_Creator_v0.30.13_prerelease_check.zip`,
  built separately by `package_prerelease_check_v0.30.13.py`.

## Files changed

| file | change |
|---|---|
| `core/config.py` | `TOOL_VERSION` -> `0.30.16`; two comments updated to the new `changelogs/`/`dev_tools/` paths |
| `core/__init__.py` | `__version__` -> `0.30.16` |
| `core/metadata_handler.py` | `_verify_libxml2_abi()`'s user-facing RuntimeError text and one comment updated to the new paths - logic unchanged |
| `README.md` | folder-contents tree diagram rewritten for the new layout; direct doc-path mentions prefixed with `docs/`/`changelogs/` where the referring file (README.md) did not itself move |
| `diagnose_crash_v0.30.12.py`, `verify_concurrency_v0.30.9.py`, `verify_lxml_threadsafety_v0.30.10.py`, `run_gdal_tests.py`, `release_test_v0.30.6.py`, `selftest_conversion.py` | moved to `dev_tools/`; `PROJECT_ROOT` introduced and used for `sys.path`/`SCHEMA_DIR`/pytest-target references, per file as needed |
| `run_prerelease_check_v0.30.13.py` | moved to `dev_tools/`; preconditions check split by location; new `_find_latest_package_release_script()` replaces the hardcoded packager filename; pytest stage now targets `PROJECT_ROOT/tests` |
| `run_prerelease_check_v0.30.13.bat`, `run_tests_v0.30.10.bat` | moved to `dev_tools/`; `SCRIPT_DIR`/`PROJECT_DIR` split for `environment.yml`/`tests` references |
| `package_prerelease_check_v0.30.13.py` | moved to `dev_tools/`; no code change needed (already self-contained relative to its own directory) |
| `Anaconda_Start.bat` | two suggested commands in its printed help text updated to `dev_tools\...` |
| `package_release_v0.30.16.py` | **new** - renamed from `package_release_v0.30.15.py`; paths and `EXCLUDE_DIRS` updated for the new layout |
| (20 docs/changelog files) | moved into `docs/` or `changelogs/`, content unchanged |
| (10 files) | moved into `archive/`, content unchanged |

## Compatibility

No public API changed. No behavioural change to the shipped GUI/CLI/
conversion pipeline. The only functional code change anywhere in this
release is the dev-tooling path-bootstrap fix (necessary purely because
those scripts physically moved) and the packager-discovery helper
replacing a filename that would otherwise have gone stale. The one change
inside `core/` is a user-facing error message's *text*, not its trigger
condition or logic.

## Verification

`python -m py_compile` passed for every moved `.py` file, run from its
**new** location in `dev_tools/` (not the old root location), confirming
each one is still syntactically valid after the move. Because this
sandbox has no real GDAL - unchanged from every prior release built here -
minimal `osgeo`/`lxml` stand-in modules were used to exercise the actual
bootstrap chain end to end rather than guessing: `sys.path.insert(0,
str(PROJECT_ROOT))` followed by `from core import GeoPackageConverter`
succeeded from `dev_tools/`'s new location, and every `PROJECT_ROOT`,
`SCHEMA_DIR`, sibling-script path, and the `tests/`/`changelogs/`
references in `run_prerelease_check_v0.30.13.py`'s preconditions stage
were individually confirmed to resolve to the real, correct file or
directory - including `_find_latest_package_release_script()` correctly
returning `package_release_v0.30.16.py`. This confirms the path
arithmetic is correct; it does not exercise real GDAL/lxml behaviour,
which is unchanged from v0.30.15 regardless of this reorganization.
Recommended before trusting this build on the real machine: re-run
`dev_tools\run_prerelease_check_v0.30.13.bat` (`--recreate-env` is not
needed - the conda environment itself did not change) and confirm it
still reaches the same verdict as the last real run.
