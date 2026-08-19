# CHANGELOG - GeoPackage Creator v0.30.18

**Release date:** 2026-08-06
**Previous:** v0.30.17 (DGIWG Validator updated to v1.58 - see
`CHANGELOG_v0.30.17.md`, itself reconstructed today - see that file's own
note on why)
**Theme:** GUI visual redesign (ttkbootstrap) + a pass through the specific
release-readiness gaps identified while reviewing whether this project could
ship

---

## Context

This release starts from a release-readiness review of the v0.30.16/v0.30.17
snapshot, which found several problems before any GUI work began:

1. `core/config.py`/`core/__init__.py`/`VERSION.txt` were already at v0.30.17
   with no `CHANGELOG_v0.30.17.md` - fixed by reconstructing that changelog
   (see its own note on how).
2. `CHANGELOG_v0.30.16.md` describes moving QA scripts into a new
   `dev_tools/` folder and superseded files into `archive/` - neither folder,
   nor any of the named scripts (`run_prerelease_check_v0.30.13.py`,
   `verify_concurrency_*.py`, `run_gdal_tests.py`, `diagnose_crash_*.py`,
   `selftest_conversion.py`), actually exist anywhere in the tree. Whatever
   happened, the described reorganization and the actual disk contents had
   diverged.
3. The last real-machine run this project has any record of
   (`CHANGELOG_v0.30.15.md`'s context section) ended in `DO NOT SHIP -
   FAILURES`: a libxml2/GDAL ABI mismatch (`LIBXML_COMPILED_VERSION (2, 14,
   6)` vs runtime `(2, 15, 3)`) that makes `MetadataHandler()` - and so every
   conversion - raise `RuntimeError` by design (the v0.30.13 fail-fast
   guard). Nothing in v0.30.16 or v0.30.17 touched this, and with the QA
   harness gone (point 2), there was no longer any way to even re-check it.
4. `packaging/GeoPackageCreator.spec` still bundled the old
   `DGIWG_Validator_v1_55_updated` folder by name - a folder that stopped
   existing as of the v0.30.16 reorganization, replaced by
   `DGIWG_GeoPackage_Validator_v1.58` (v0.30.17). A PyInstaller build against
   this spec would have failed outright, or (worse, if the old folder
   happened to still be present on a given build machine from before the
   rename) silently shipped the superseded validator inside the `.exe`.
5. `packaging/build_windows.ps1` created its build conda env with
   `gdal=3.11.4` - matching neither the `3.13.1` nor `3.13.2` pin used
   everywhere else in the project. Flagged as an open item in
   `CHANGELOG_v0.30.13.md` ("left open, flagged rather than guessed at")
   and never revisited since.
6. `README.md`'s version banner still read "Version 0.27.0", and its folder
   diagram described the v0.30.16 reorg's `dev_tools/`/`archive/`/
   `release_dist/` layout - the same divergence as point 2, just visible to
   a human reader instead of a script.

Points 1, 2, 4, 5, 6 are fixed in this release (see below). Point 3 - the
actual libxml2/GDAL ABI mismatch - is a real-machine environment problem
that cannot be fixed from this sandbox; `dev_tools/run_release_check_v0.30.18.py`
(new, see below) is what re-checks it. See "What is still open" at the
bottom of this changelog.

Separately, and the part actually requested: the GUI's visual design
(plain `ttk`/`clam`, default gray buttons) was reworked.

## NEW: GUI visual redesign (geopackage_creator_gui.py)

Switched from bare `tkinter.ttk` to `ttkbootstrap` (theme `bootstrap-light`).
Every business-logic method is byte-for-byte unchanged from v0.30.9
(`validate_inputs`, `start_conversion`, `do_conversion`, `convert_in_console`,
`view_results`, `open_json_report`, the thread-marshaling `log`/`_ui`
helpers) - only widget construction and layout changed:

- New header banner (title, subtitle, version badge on a solid primary-color
  bar).
- The six stacked sections are now split across two `Notebook` tabs ("Files
  & Metadata", "CRS & Reports") instead of one long vertical stack, each tab
  wrapped in a `ttk.ScrolledFrame` so content is never unreachably clipped
  regardless of window size or DPI scaling (verified at 1040x900 default and
  at a deliberately undersized 950x620 - see Verification).
- CRS Conversion Mode is now a segmented `outline-toolbutton` radio group
  instead of four plain radio dots.
- The three report-format checkboxes are now `round-toggle` switches.
- Buttons are explicitly styled by role: `Convert to GeoPackage` (primary,
  solid), `Convert in Console Window` (info, outline), `Clear Log`/`Exit`
  (secondary, outline), `View Results` (success, outline, disabled until a
  result exists - unchanged behaviour).
- A status line ("Ready" / "Converting..." / "Completed" / "Failed" /
  "Error") was added next to the progress bar, updated through the same
  `self._ui(...)` main-thread marshaling every other cross-thread UI update
  already uses.
- The Abstract field and both report/log Toplevel dialogs (`view_results`,
  `open_json_report`) now use `ttkbootstrap`'s `Text`/`ScrolledText` so they
  pick up the theme instead of rendering as plain unstyled tk widgets.

Window default size grew from 1000x900 to 1040x900 (the tab/scroll
restructuring needed a little more width for comfortable padding).

## FIX (packaging/GeoPackageCreator.spec)

- `app_datas`: bundled folder changed from `DGIWG_Validator_v1_55_updated`
  (does not exist) to `DGIWG_GeoPackage_Validator_v1.58` (see "Context" point
  4 above).
- `hiddenimports`: removed `"DGIWG_Validator_v1_55_updated"` and
  `*collect_submodules("DGIWG_Validator_v1_55_updated")`. This was never
  actually a valid top-level importable package name even before the
  rename - the real package is `dgiwg_validator` (lowercase), loaded at
  RUNTIME via `sys.path.insert()` against the bundled data folder
  (`core/validation_gate.py`'s `find_validator()` /
  `packaging/runtime_paths.py`'s `bootstrap()`), which PyInstaller's static
  analysis cannot see and does not need to. Left in place, `collect_submodules()`
  importing a name that no longer resolves to anything would have hard-failed
  the build outright the next time anyone actually ran PyInstaller against
  this spec.
- `hiddenimports`/`datas`: added `ttkbootstrap` + `collect_submodules("ttkbootstrap")`
  + `collect_data_files("ttkbootstrap")` (the GUI's new dependency - code via
  hiddenimports, its non-.py assets such as localization files via datas,
  the same pattern already used for `osgeo`/`pyproj`).

## FIX (packaging/build_windows.ps1, packaging/build_windows.bat)

- `build_windows.ps1`'s `conda create` now pins `gdal=3.13.2` (was
  `gdal=3.11.4` - see "Context" point 5). Also installs
  `ttkbootstrap==2.2.0` via pip into the build env (needed for
  `PyInstaller.Analysis()` to find `import ttkbootstrap` from
  `geopackage_creator_gui.py`).
- `build_windows.bat`'s header comment updated to match (`v0.30.9` ->
  `v0.30.18`, `GDAL 3.11.4` -> `GDAL 3.13.2`) - it does not itself invoke
  conda, so this is documentation-only.

## FIX (version/changelog bookkeeping)

- `CHANGELOG_v0.30.17.md` written (reconstructed - see its own note on how
  and why).
- `TOOL_VERSION` (`core/config.py`) and `__version__` (`core/__init__.py`)
  bumped `0.30.17` -> `0.30.18`.
- `README.md`: version banner `0.27.0` -> `0.30.18`; folder-contents diagram
  rewritten to match what is actually on disk (see "Context" point 6);
  requirements list now mentions `ttkbootstrap`; the "Version" section's
  stale "predates several releases" caveat removed now that the number
  itself is current.

## NEW (dev_tools/run_release_check_v0.30.18.py, .bat)

Fresh replacement for the missing QA harness (see "Context" point 2) - not a
byte-for-byte restoration (the original scripts' exact source is not
recoverable from the changelogs describing them). Five stages, each
independently PASS/FAIL/SKIP recorded and written to a timestamped log:
environment fingerprint (Python/GDAL/lxml/ttkbootstrap versions, and
explicitly the libxml2 `LIBXML_COMPILED_VERSION` vs `LIBXML_VERSION`
comparison), `core` import + actually constructing a `MetadataHandler()` (the
real fail-fast-guard behaviour, not just an import check), DGIWG validator
discovery, a GUI construction smoke test (new - covers the ttkbootstrap
redesign), and the full pytest suite split into `not concurrency`/
`concurrency` subprocesses exactly as `pytest.ini`'s own comments describe
(so a native access-violation crash in one cannot discard the other's
results). Ends with an explicit `DO NOT SHIP - FAILURES` / `INCOMPLETE` /
`ALL STAGES PASSED` verdict and a matching exit code (1 / 2 / 0).

## Files changed

| file | change |
|---|---|
| `geopackage_creator_gui.py` | visual redesign on `ttkbootstrap` (see above) - business logic unchanged |
| `packaging/GeoPackageCreator.spec` | DGIWG validator bundle path fixed (v1.58); broken hiddenimports removed; ttkbootstrap added |
| `packaging/build_windows.ps1` | GDAL pin `3.11.4` -> `3.13.2`; installs ttkbootstrap into the build env |
| `packaging/build_windows.bat` | header comment version/GDAL references updated |
| `requirements.txt` | `ttkbootstrap==2.2.0` added, with a note on why it's pip-only |
| `environment.yml` | `pip` + `pip: [ttkbootstrap==2.2.0]` section added (not on conda-forge) |
| `install_dependencies.bat`, `install_dependencies.ps1` | new step installs `ttkbootstrap==2.2.0`; step numbering updated |
| `docs/DEPENDENCIES.txt` | `ttkbootstrap` added to the package list, with a pip-only explainer section |
| `README.md` | version banner, folder-contents diagram, requirements list, Version section |
| `core/config.py` | `TOOL_VERSION` -> `0.30.18` |
| `core/__init__.py` | `__version__` -> `0.30.18` |
| `VERSION.txt` | new v0.30.18 entry (prepended; all prior entries preserved verbatim) |
| `changelogs/CHANGELOG_v0.30.17.md` | **new** - reconstructed retroactively |
| `dev_tools/run_release_check_v0.30.18.py`, `.bat` | **new** - replacement pre-release QA gate |

## Compatibility

Public API (`core.GeoPackageConverter` and friends) unchanged. CLI
(`geopackage_creator.py`) unchanged. GUI behaviour (what each button does,
what gets validated, what a conversion produces) unchanged - only its
appearance and layout changed. Anyone scripting against `core/` directly is
unaffected. Anyone with an existing `geopackage` conda env needs to add
`ttkbootstrap==2.2.0` (via pip) before the GUI will launch - the CLI does not
need it.

## What is still open

This release does NOT resolve the libxml2/GDAL ABI mismatch itself (Context
point 3) - that is a specific machine's environment, not something fixable
from source. It also does not independently re-verify that mismatch is even
still present on your machine; the last data point on file is the v0.30.15
context section, which is not current. Before trusting this build:

1. `conda env create -f environment.yml` (or `conda env remove -n geopackage`
   then recreate, if the env already exists and might have drifted).
2. `conda activate geopackage`
3. `python dev_tools\run_release_check_v0.30.18.py` (or the `.bat` wrapper)
4. Send back `dev_tools\release_check_<timestamp>.log` and the two
   `pytest_*.log` files it produces alongside it.

## Verification

`python -m py_compile` passed for every changed `.py` file. Because this
sandbox has no real GDAL, Tk, or Windows - unchanged from every prior release
built here - verification here used the same substitution technique this
project's own history already established (stub `osgeo`/`lxml` modules,
"minimal osgeo/lxml stand-in modules... to exercise the actual bootstrap
chain end to end", `CHANGELOG_v0.30.16.md`):

- The redesigned GUI was constructed for real (stubbed `osgeo`, real
  `ttkbootstrap` 2.2.0, real `tkinter` via an extracted Ubuntu package under
  Xvfb) and screenshotted at its default 1040x900 size and at a shrunk
  950x620 to confirm the tab/scroll restructuring degrades gracefully
  instead of clipping fields unreachably. No bootstyle-grammar warnings were
  raised by any of the strings used (`@primary`, `round-toggle`,
  `primary-outline-toolbutton`, `success-striped`, `secondary-outline`, etc.)
  - `ttkbootstrap`'s tokenizer fails loudly on an unrecognized token, so a
    clean run is a real signal, not just an absence of a crash.
- `dev_tools/run_release_check_v0.30.18.py` itself was run end-to-end
  against the same stubs (symlinked project subtree + a minimal on-disk
  `osgeo` stub package, since this script spawns real subprocesses that
  need the stub to be importable fresh, not just monkeypatched into one
  already-running process). All five stages executed, recorded PASS/FAIL
  correctly, wrote their log files, and produced the right exit code - the
  pytest stages reported FAIL in this sandbox (expected: the stub GDAL
  returns `None` from calls real conversion code needs), which is the
  correct behaviour for an environment that cannot really run GDAL, not a
  bug in the harness.
- `ttkbootstrap==2.2.0` is confirmed NOT to exist on conda-forge
  (`anaconda.org/conda-forge/ttkbootstrap` returns 404; a general web search
  turned up no conda-forge package either) - this is why it is pip-only in
  every dependency file touched above, rather than a guess.

None of this exercises real GDAL, real libxml2, or real Windows Tk
rendering. Recommended before trusting this build: the four steps under
"What is still open" above, on the real machine.
