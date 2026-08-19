# CHANGELOG - GeoPackage Creator v0.30.17

**Release date:** 2026-08-05
**Previous:** v0.30.16 (project root reorganized into subfolders)
**Theme:** DGIWG Validator updated to v1.58 (auto-detection only - no product
code behaviour changed)

---

## Note on how this changelog came to exist

This entry is being written on 2026-08-06, after the fact. `core/config.py`
and `core/__init__.py` were already stamped `0.30.17` and `VERSION.txt` already
had a `v0.30.17` entry at its head describing this work - but no
`CHANGELOG_v0.30.17.md` file existed in `changelogs/`, breaking this project's
own one-changelog-per-version convention (every prior version, back to
`CHANGELOG_v0.25.md`, has one). Reconstructed from `VERSION.txt`'s existing
v0.30.17 entry, the actual diffs in `core/validation_gate.py` and
`packaging/runtime_paths.py`, and `DGIWG_GeoPackage_Validator_v1.58/REVIEW_FINDINGS_v1.58.md`.
Nothing below is new work - it documents what v0.30.17 already did.

## Context

A newer build of the bundled DGIWG GeoPackage Validator became available:
`DGIWG_GeoPackage_Validator_v1.58`, superseding the `DGIWG_Validator_v1_55_updated`
folder this project had shipped since earlier releases. Per
`DGIWG_GeoPackage_Validator_v1.58/REVIEW_FINDINGS_v1.58.md` (full review dated
2026-08-05, all 12 validator modules, ~10,500 lines), v1.58 fixes 11 bugs in
the validator itself versus v1.57 - notably a `_EPSG_API` NameError that
silently disabled the Req 13 EPSG REST lookup, a false Req 26 PASS on
non-256px stored tiles, and stale Req 1/2/15 requirement identifiers predating
DGIWG STD-DP-19-005 v1.1's Table 6. That review's own verdict: "release-ready
as a pre-release", 40/40 synthetic functional-test assertions passed. The
validator is a separate bundled sub-project maintained on its own version
line (see its own `VERSION.txt` and `REVIEW_FINDINGS_v1.58.md`) - this
changelog covers only how GeoPackage Creator itself was updated to find and
prefer it.

## CHANGE (core/validation_gate.py)

`find_validator()`'s well-known-location search previously globbed only
`**/DGIWG_Validator_v1_5*` (the old naming convention). A second glob for
`**/DGIWG_GeoPackage_Validator_v1.*` was added alongside it, so a v1.58 (or
later v1.x) folder using the new naming convention is discovered the same way
the old `DGIWG_Validator_v1_5x` folders always were. Both patterns are
searched; whichever matching folder actually contains `dgiwg_validator/checks.py`
is used (unchanged verification logic).

## CHANGE (packaging/runtime_paths.py)

`bootstrap()`'s `DGIWG_VALIDATOR_PATH` auto-detection previously checked
`DGIWG_Validator_v1_55_updated` first. `_first_existing()`'s candidate order
was changed to try `DGIWG_GeoPackage_Validator_v1.58` first, then fall back to
`DGIWG_Validator_v1_55_updated`, then a glob for other `DGIWG_Validator_v1_5*`
/ `DGIWG_GeoPackage_Validator_v1.*` folders - so an installation that has both
an old and a new validator folder present prefers the newer one automatically,
without needing `DGIWG_VALIDATOR_PATH` set by hand.

## No functional code changes

Validator discovery and invocation logic (`sys.path.insert()` +
`from dgiwg_validator import checks`) is unchanged - only which folder gets
found first. A process that already had `DGIWG_GeoPackage_Validator_v1.58`
present starts using it automatically; nothing breaks for one that still only
has the older folder.

## Known gap introduced here, fixed in v0.30.18

`packaging/GeoPackageCreator.spec` - the PyInstaller build spec that controls
what actually ships inside the packaged `.exe` - was **not** updated as part
of this release. It continued to bundle `DGIWG_Validator_v1_55_updated` by
name (a folder that had already stopped existing in the project tree as of
v0.30.16's reorganization) instead of the new `DGIWG_GeoPackage_Validator_v1.58`
folder this release taught the *source* run to prefer. A `python -m PyInstaller`
build against this spec would have failed at the `Analysis()` step (bundling a
nonexistent source path), or - had the old folder still been physically
present on a given build machine's disk from before the rename - would have
silently shipped the superseded v1.55 validator inside the `.exe` while the
source/`python geopackage_creator.py` run used v1.58. Neither is a v0.30.17
code defect exactly - the runtime-path change here is correct - but the spec
should have been updated in the same release that changed the folder it
points at. See `CHANGELOG_v0.30.18.md` for the fix.

## Files changed

| file | change |
|---|---|
| `core/validation_gate.py` | `find_validator()` - added a second glob pattern for the `DGIWG_GeoPackage_Validator_v1.*` naming convention |
| `packaging/runtime_paths.py` | `bootstrap()` - `DGIWG_GeoPackage_Validator_v1.58` tried before `DGIWG_Validator_v1_55_updated` in the frozen-build auto-detect candidate list |
| `core/config.py` | `TOOL_VERSION` -> `0.30.17` |
| `core/__init__.py` | `__version__` -> `0.30.17` |
| `VERSION.txt` | v0.30.17 entry (already present - prepended at the time, prior to this changelog file being written) |

## Compatibility

No public API changed. No behavioural change to the conversion pipeline. Pure
validator-discovery preference change, additive (a new glob pattern; the old
one is still checked too).

## Verification

Not independently re-run through a full pre-release gate at the time (the
`dev_tools/` harness this project relies on for that did not exist in the
tree at the time this entry was reconstructed - see `CHANGELOG_v0.30.18.md`).
The two diffs are narrow and mechanical (a glob pattern added, a candidate
list reordered) and were reviewed by inspection against
`core/validation_gate.py`'s and `packaging/runtime_paths.py`'s existing,
already-tested discovery logic, which is otherwise unchanged.
