# CHANGELOG - GeoPackage Creator v0.30.20

**Release date:** 2026-08-14
**Previous:** v0.30.19 (version-bookkeeping sweep + SPDX headers - see
`CHANGELOG_v0.30.19.md`)
**Theme:** Three real bugs fixed, plus a libxml2 version pin that was
believed to be the root-cause fix for the blocker open since v0.30.13 but has
since been DISPROVEN on the target machine. **The blocker remains OPEN.**

---

## Context

Every release since v0.30.13 has carried the same `DO NOT SHIP` verdict: the
libxml2 ABI fail-fast guard in `core/metadata_handler.py` fires on the target
machine (`LIBXML_COMPILED_VERSION (2, 14, 6)` vs `LIBXML_VERSION (2, 15, 3)`),
which blocks `MetadataHandler()` construction, which blocks every conversion.
The documented remediation - `conda env remove` followed by
`conda env create -f environment.yml` - never fixed it, and
`CHANGELOG_v0.30.19.md` speculated that the environment may simply never have
been genuinely recreated between test runs.

That speculation was wrong - but so was this release's replacement theory.
v0.30.20 proposed that the root cause was a missing `libxml2` pin in
`environment.yml`. Adding the pin genuinely fixed the *version mismatch* - the
tuples now agree - yet the access violation persists unchanged. The true root
cause is still unidentified. See the superseded-by-evidence note below and
`dev_tools/diagnose_crash_v0.30.21.py`.

## PARTIAL FIX (NOT THE ROOT CAUSE): environment.yml - `libxml2=2.14` pin

> **SUPERSEDED BY EVIDENCE — read this first.** A release check run on the
> real Windows/Anaconda machine on 2026-08-14 confirmed that this pin DOES
> make the version tuples agree (`LIBXML_COMPILED_VERSION == LIBXML_VERSION
> == (2, 14, 6)`) — **and the access violation still happens anyway**, in the
> same place (`core/metadata_handler.py:526`, `schema.validate()`), during
> `tests/test_converter.py` and `tests/test_concurrency.py`, and in the
> standalone interop probe (exit code `3221225477` = `0xC0000005`).
>
> Version agreement was therefore **necessary but not sufficient**. The
> section below explains why the pin is still correct and worth keeping, but
> it is NOT the fix, and the blocker is NOT closed. See
> `dev_tools/diagnose_crash_v0.30.21.py` for the follow-up investigation.



Three facts, each independently verifiable:

1. conda-forge's **global pinning file**
   (`conda-forge-pinning-feedstock/recipe/conda_build_config.yaml`) pins
   `libxml2: 2.14`. Every conda-forge `lxml` binary is compiled against that.
2. conda-forge nevertheless **publishes `libxml2` 2.15.x** (2.15.3, April
   2026) as an installable package.
3. The conda-forge **`lxml` recipe declares no `libxml2` version constraint
   and no `run_exports`**, so nothing propagates the 2.14 build-time
   assumption into the runtime solve.

Consequently nothing prevents conda's solver from installing libxml2 2.15.3 -
which `gdal` pulls in transitively - alongside an `lxml` compiled against
2.14.6. That did explain the observed version fingerprint, and pinning removed
it. It did not explain the crash.

(v0.30.13's claim that "exactly one libxml2 image is mapped into the process"
was never independently verified - it was inferred, not measured. Probe 0 of
`diagnose_crash_v0.30.21.py` measures it directly, because if there are in fact
TWO images, that alone accounts for the whole failure and always did.)

This also explains why recreating the environment never helped: a recreate
re-runs the *same unconstrained solve* and re-picks 2.15.x. The mismatch lives
in `libxml2`, a package `environment.yml` previously never mentioned at all.
The file pinned `gdal` and deliberately left `lxml` unpinned "so the solver
picks a mutually consistent pair" - but consistency between those two is
mediated by a third package that was left free.

`environment.yml` now pins `libxml2=2.14` explicitly, with a comment
explaining that the pin must move in lockstep with conda-forge's global pin if
that ever advances to 2.15.

**CONFIRMED INSUFFICIENT on the target machine (2026-08-14).** The pin does
what it claims - the two libxml2 version tuples now match exactly - so it is
retained: a version mismatch would be an independent defect on top of the real
one. But it does not stop the crash, so the v0.30.20 headline claim was wrong.

The leading remaining hypothesis is that conda's `lxml` and conda's `gdal` each
load their OWN libxml2 DLL. Two copies of the *same version* still keep
independent global state (interned-string dictionaries, the error-handler
table, the global parser context), so a document allocated by one copy and
validated against a schema owned by the other dereferences a pointer that is
meaningless in the other copy's heap - an access violation whose version tuples
look perfectly healthy. `dev_tools/diagnose_crash_v0.30.21.py` tests this
directly by counting the distinct libxml2 images mapped into one process.

## FIX: core/gdal_handler.py - TimeoutError no longer swallowed (real bug)

`create_geopackage()` raises `TimeoutError` when it cannot acquire the write
lock within `lock_timeout`. Its own trailing `except Exception as e:` then
caught that very exception and re-raised it as
`ValidationError(f"Error creating GeoPackage: {e}")` - `TimeoutError` is an
`OSError` subclass, so it was captured silently. A caller could not distinguish
"another thread holds the write lock, retry in a moment" from "this output path
is fundamentally broken."

A dedicated `except TimeoutError:` clause now releases the lock and re-raises
unchanged, ahead of the general handler.

`CHANGELOG_v0.30.19.md` listed the corresponding test
(`tests/test_critical_fixes.py::TestLockTimeout::
test_lock_timeout_prevents_indefinite_wait`) as "not yet root-caused (possibly
just flakiness from its tight 0.1s timeout)." It is not flaky: it failed 5 runs
out of 5, deterministically, and the 0.1s threshold was never the issue.

## FIX: tests/test_gdb_domains.py - invalid ISO 19115 topic category

`test_multiple_domain_types` passed `topic_category="utilities"` and then
asserted `result['success']`. `"utilities"` is not a member of the ISO 19115
`MD_TopicCategoryCode` codelist; the correct value is
`"utilitiesCommunication"`, which `core/config.py`'s `TOPIC_CATEGORIES` has
listed correctly all along. The validator was right and the test was wrong -
it fed in a value the validator is *required* to reject and then asserted
success. Corrected to `"utilitiesCommunication"`.

## HARDENING: GDAL binding-version compatibility (defensive, not a live bug)

The following two issues do **not** manifest on the pinned GDAL 3.13.2. They
are corrected so the tool degrades sanely if a user's environment resolves an
older GDAL, since `requirements.txt` still admits `GDAL >= 3.6.0` as a floor.

**Dataset handles tested for truth value (7 sites).** On GDAL >= 3.13,
`ogr.Open()` and `Driver.CreateDataSource()` return a `gdal.Dataset`, whose
`__bool__` unconditionally returns `True` - so `if not ds:` behaves correctly.
On GDAL <= 3.12 bindings the same calls return an `ogr.DataSource`, which
defines `__len__` (= `GetLayerCount()`) and **no** `__bool__`. Python then
falls back to `__len__`, making a **valid, successfully created, still-empty
GeoPackage evaluate falsy**. Under those bindings
`if not out_ds: raise ValidationError("Failed to create GeoPackage")` fires on
complete success, and `close_geopackage()`'s `if ds:` guard skips the entire
close path - leaking the GDAL handle *and* leaving the write lock held, which
is the exact failure mode the v0.30.7 notes describe. All seven sites now test
`is None` / `is not None`:

- `core/gdal_handler.py` (4): `_close_dataset_safely`, `read_source_data`,
  `create_geopackage`, `close_geopackage`, `validate_geopackage_output`
- `core/converter.py` (2), `core/crs_converter.py` (1), `core/validators.py` (1)

Note upstream fixed this same trap for `ogr.Layer` - which carries
`__nonzero__` with the comment *"To avoid `__len__` being called when testing
boolean value which can have side effects (#4758)"* - but never for
`ogr.DataSource`.

**`driver.ShortName` (1 site).** `core/gdal_handler.py:read_source_data` read
`driver.ShortName`. On GDAL 3.13.2 `ds.GetDriver()` returns a `gdal.Driver`,
which does expose `ShortName`, so this worked. On GDAL <= 3.12 the same call
returns an `ogr.Driver`, which has no such attribute (0 occurrences in the OGR
bindings vs 14 in the GDAL ones), raising `AttributeError` that the enclosing
handler reported as a misleading *"Error reading source data"*. Now uses
`driver.GetName()`, which is present on both.

## Files changed

| file | change |
|---|---|
| `environment.yml` | **the blocker fix** - pin `libxml2=2.14` |
| `core/gdal_handler.py` | real bug fix - `TimeoutError` propagates unwrapped; 4 truthiness sites; `ShortName` -> `GetName()` |
| `core/converter.py`, `core/crs_converter.py`, `core/validators.py` | dataset truthiness hardening (4 sites) |
| `tests/test_gdb_domains.py` | invalid ISO 19115 topic category corrected |
| `core/config.py` | `TOOL_VERSION` -> `0.30.20` |
| `core/__init__.py` | `__version__` -> `0.30.20` |
| `geopackage_creator_gui.py`, `packaging/app_main.py` | `APP_VERSION` -> `0.30.20` |
| `packaging/version_info.txt` | `filevers`/`prodvers`/`FileVersion`/`ProductVersion` -> `0.30.20` |
| `README.md` | version banner; release status rewritten to CANDIDATE |
| `VERSION.txt` | new v0.30.20 entry (prepended) |

## Compatibility

Public API unchanged. One deliberate behavioural change: `create_geopackage()`
now raises `TimeoutError` instead of `ValidationError` on lock-acquisition
timeout. Any caller catching `ValidationError` to handle contention must also
catch `TimeoutError` - in this tree only the test suite did so, and it
expected `TimeoutError` already. Everything else is comment-only or
version-string churn.

## Verification

### On the real Windows/Anaconda machine (2026-08-14) - AUTHORITATIVE

`dev_tools/run_release_check_v0.30.20.py`, conda env `geopackage`,
Python 3.11.15, Windows-10-10.0.26200, GDAL **3.13.2**, lxml **6.1.1**:

| stage | result |
|---|---|
| environment | PASS - conda env `geopackage` |
| libxml2_abi | **PASS - MATCH (2, 14, 6)** - the pin works |
| gdal | PASS - 3.13.2, GPKG driver present |
| metadata_ctor | PASS - `MetadataHandler()` constructs (first time since v0.30.13) |
| gdal_lxml_interop | **FAIL - NATIVE CRASH, exit 3221225477 (0xC0000005)** |
| version_strings | PASS - all agree at 0.30.20 |
| pytest_main | **FAIL - Windows fatal exception: access violation** |
| pytest_concurrency | **FAIL - Windows fatal exception: access violation** |

**VERDICT: DO NOT SHIP.**

Two genuine steps forward: the version tuples now match, and `MetadataHandler()`
constructs for the first time since v0.30.13 (the ABI guard no longer fires).
That is why the crash has *moved*: previously the guard stopped execution before
any libxml2 work happened; now execution proceeds to the real fault.

The crash site is precise and reproducible:

```
Windows fatal exception: access violation
  core/metadata_handler.py, line 526, in validate_schema     <- schema.validate(doc)
  core/metadata_handler.py, line 739, in generate_package_metadata
  core/converter.py,        line 588, in convert
  tests/test_converter.py,  line 143, in test_convert_with_valid_shapefile
```

`tests/test_concurrency.py` dies the same way with two worker threads inside
`converter.py:111`. The standalone interop probe - lxml XSD compile, one GDAL
vector write, one further lxml call, no project code at all - also crashes,
which reproduces v0.30.12's finding exactly and confirms this is not a defect
in this codebase's logic.

### In a Linux container (GDAL 3.8.4, lxml 2.14.6/2.14.6)

Full suite **304 passed, 1 skipped, 0 failed**. Notably the interop sequence
does NOT crash here. Probe 0 of the new diagnostic explains why this environment
is not a valid proxy: on Linux, lxml carries its own statically linked libxml2
while GDAL links the system `libxml2.so` - two independent copies that never
share state. The Windows conda build puts both DLLs in the same directory,
which is precisely the configuration under test.

This is why the three non-libxml2 fixes in this release (TimeoutError, ISO
topic category, GDAL binding compatibility) are trustworthy while the libxml2
conclusion was not: those are ordinary Python defects that reproduce anywhere.

### Still open

The blocker is NOT closed. Next step is
`dev_tools\diagnose_crash_v0.30.21.py`, which runs eight isolated probes -
each in its own subprocess so a crash names the exact fatal step - plus an
inventory of how many distinct libxml2 images are mapped into one process.

If that inventory reports **2**, the cause is settled: two copies of libxml2,
each with its own interned-string dictionary and error-handler table, cannot
safely exchange documents and schemas. Remedies in that case, roughly in order
of preference:

1. Install `lxml` from the SAME conda solve rather than pip, so both link one
   shared `libxml2.dll` (verify with the inventory probe, not by version).
2. Move XSD validation out of the conversion process entirely - run it in a
   subprocess, which is robust regardless of DLL topology.
3. Replace lxml validation with a pure-Python/`xmlschema` validator, removing
   the second libxml2 consumer.
4. Keep the existing fail-fast guard but widen it to detect image count rather
   than version, so users get a clear error instead of a crash.

Also still unverified: no real GDB→GPKG conversion has completed, no DGIWG
validator run on real output, and no GUI or frozen-`.exe` exercise.
