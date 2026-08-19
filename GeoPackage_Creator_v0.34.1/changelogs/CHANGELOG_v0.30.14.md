# CHANGELOG - GeoPackage Creator v0.30.14

**Release date:** 2026-08-05
**Previous:** v0.30.13 (libxml2 ABI fail-fast guard, GDAL pin -> 3.13.2)
**Theme:** environment.yml now actually pins GDAL - closes a gap in v0.30.13's own remediation path

---

## Context

While building `run_prerelease_check_v0.30.13.py` - an automated gate that
verifies the v0.30.13 pre-release on a real Anaconda/Windows machine for the
first time - `environment.yml` was reviewed as part of confirming the
`conda env create -f environment.yml` remediation step that
`core/metadata_handler.py`'s `_verify_libxml2_abi()` error message tells
users to run when it detects a libxml2 ABI mismatch.

It does not fully do what that message assumes. Every other file that
documents the GDAL requirement has pinned it explicitly since v0.30.7:

- `DEPENDENCIES.txt`: "Install GDAL 3.13.2 EXACTLY. Do not install 'latest'."
- `requirements.txt`: "PIN THE VERSION... Required: GDAL == 3.13.2"
- `install_dependencies.bat` / `.ps1`, `QUICK_FIX_CONDA.txt`,
  `INSTALLATION_GUIDE.md`: all pass `gdal=3.13.2` explicitly.

`environment.yml` alone still read:

```yaml
  - gdal          # >= 3.6 required; 3.13.2 recommended (matches the tested build, v0.30.13)
```

A comment is not a pin. `conda env create -f environment.yml` lets conda's
solver resolve whatever the current `gdal` on conda-forge happens to be -
which, as of this release, is still 3.13.2 (verified against gdal.org and
conda-forge's own package page: 3.13.2 released 2026-07-22, current stable,
win-64 build updated 2026-07-26) - but nothing in the file guaranteed that
stays true after the next GDAL release.

## Why this matters specifically for v0.30.13

This is not a hypothetical concern about reproducibility in the abstract.
This exact codebase has been burned by exactly this failure mode once
already:

> "every install command in this file used to read `conda install
> -c conda-forge gdal` with no version. That silently moved the project from
> GDAL 3.13.1 to 3.13.2 between the v0.30.6 build and its release test. When
> the suite then crashed, the version change was the obvious suspect and it
> was wrong." - `DEPENDENCIES.txt`

And the v0.30.13 fix's own documented recovery path for the libxml2 ABI
mismatch is *specifically* "recreate the environment from this file":

> "Fix the environment (recommended - lets conda's solver pick a mutually
> consistent set, rather than layering another install on top of a drifted
> one): `conda env remove -n geopackage` / `conda env create -f
> environment.yml`" - `core/metadata_handler.py`, `_verify_libxml2_abi()`

An unpinned `gdal` line means that recovery path could not fully promise the
thing it is recommended for: landing back on the tested, reproducible build.

## FIX (environment.yml)

`gdal` is now `gdal=3.13.2`. `lxml` is deliberately left **unpinned** - the
whole point of `conda env create -f environment.yml` as the recommended fix
is letting conda's solver pick an lxml build that is mutually consistent
with the pinned GDAL in one solve, rather than pinning both and risking
forcing back together the exact mismatched pair the guard exists to catch.

## FIX (core/__init__.py)

`__version__` was still `"0.30.9"` - stale since v0.30.10, i.e. for four
releases before this one. `core/config.py`'s `TOOL_VERSION` was bumped every
time; this module-level stamp was not. Brought into agreement. Nothing in
this codebase reads `core.__version__` at runtime, so this has no
behavioural effect - it is a leftover drift worth closing while the file was
already open for this release, not a reason for this release on its own.

## Files changed

| file | change |
|---|---|
| `environment.yml` | `gdal` -> `gdal=3.13.2` (actually pinned; was a comment only); header and comments updated |
| `core/config.py` | `TOOL_VERSION` -> `0.30.14` |
| `core/__init__.py` | `__version__` `"0.30.9"` -> `"0.30.14"` (was 4 releases stale) |
| `VERSION.txt` | new v0.30.14 entry (prepended; all prior entries preserved verbatim) |
| `package_release_v0.30.14.py` | **new** - release packager, renamed from `package_release_v0.30.13.py` per this project's existing rename convention; `REQUIRED_FILES`/`CONTENT_CHECKS` updated to expect `CHANGELOG_v0.30.14.md` and the new `gdal=3.13.2` pin |

`package_release_v0.30.13.py` is left in place unchanged, matching how this
project has always kept prior `package_release_vX.Y.Z.py` /
`verify_concurrency_vX.Y.Z.py` scripts around after superseding them rather
than deleting them.

## Compatibility

No public API changed. No runtime behaviour changes for any environment
that already happened to have GDAL 3.13.2 installed - which is every
environment this project's own documentation told someone to build. The
only observable difference is that `conda env create -f environment.yml` on
a machine with no environment yet (or `run_prerelease_check_v0.30.13.bat
--recreate-env`) now resolves GDAL 3.13.2 deterministically instead of
"whatever conda-forge currently calls latest."

## Verification

Not independently re-run through the full `run_prerelease_check_v0.30.13.py`
gate after this change - that harness targets the v0.30.13 pre-release
specifically and was not re-pointed at v0.30.14 (its own `env_fingerprint`
stage reads `core.config.TOOL_VERSION` for informational display only, so it
still runs correctly and will simply report `0.30.14`; nothing in the gate
hard-asserts that value). The change here is narrow enough - one dependency
pin plus two version stamps - to review by inspection, but the concrete way
to confirm it does what this changelog claims is:

```
conda env remove -n geopackage
conda env create -f environment.yml
conda activate geopackage
python -c "from osgeo import gdal; print(gdal.__version__)"   -> should print 3.13.2
```
