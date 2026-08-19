# Changelog — GeoPackage Creator v0.30.9

**Release date:** 2026-08-04
**Builds on:** v0.30.7 (handle-lifetime crash fix) and v0.30.8 (regression tests)

---

## Summary

Triage of every failure in the last release-test run that completed
(2026-07-24 12:14): **12 failures + 17 errors.** Most were already fixed by
edits made *after* that log was written. Two were not, and one of those was a
live landmine.

---

## Triage of all 29 original failures

| Group | Count | Cause | Status |
|---|---|---|---|
| `CreateGeometryFromWkt` → `OGR Error: Corrupt data` | 6 failures + 17 errors | Malformed WKT in the tests — coordinates written without separating commas, e.g. `LINESTRING(0 0 1 1 2 0)` instead of `LINESTRING(0 0, 1 1, 2 0)`. GDAL ≥ 3.11 rejects what older builds tolerated. | **Already fixed** after the Jul 24 log — all WKT literals in `tests/` now carry commas. |
| `OutputValidator.verify_crs_in_srs_table` → `AttributeError` | 2 failures | Method referenced by tests but never implemented. | **Already fixed** — defined at `core/validators.py:484`. |
| `test_concurrency` write-permission races | 2 failures | Fixed-filename write probe (`.gpkg_creator_test`) raced across threads. | **Already fixed** — `validators.py` uses `tempfile.mkstemp` (changed 12:22, eight minutes after that run). |
| `TestLockTimeout` | 2 failures | See below — **still live**. | **Fixed in v0.30.9.** |

---

## Changes

### FIX — `tests/test_critical_fixes.py`: `NameError` in the lock-timeout test

`test_lock_timeout_prevents_indefinite_wait` ended with:

```python
# Cleanup
handler1.close_geopackage(ds1)
```

Neither `handler1` nor `ds1` exists in that test. They were leftovers from the
pre-v0.30.6 version, which created two handlers on the same thread. The v0.30.6
rewrite correctly replaced that setup with a background-thread lock holder — but
did not remove the trailing cleanup. The test therefore raised `NameError` and
**failed even though the timeout behaviour it checks was working correctly**.

Both `TestLockTimeout` failures in the Jul 24 log show a Windows
`PermissionError [WinError 32]` rather than this `NameError`, because that run
predates the v0.30.6 rewrite. Those two symptoms have separate causes; the
rewrite fixed the first, and v0.30.9 fixes the second.

### FIX (LANDMINE) — `core/gdal_handler_concurrency.py` reduced to a shim

A second, independent 395-line copy of `GDALHandler` was sitting in `core/`,
imported by nothing, carrying **both** v0.30.7 defects verbatim:

* `close_all_datasets()` with `del ds` on the loop variable (line 97)
* `close_geopackage(ds)` with `del ds` on the parameter, followed by an
  unconditional write-lock release in `finally` (line 345)

The second is the exact cause of the access violation that killed the v0.30.6
release test. It was not live — but it shipped inside the release archive under
a filename that reads like *the* concurrency implementation, so the obvious
"fix" for a future concurrency problem would have been to import it and
reintroduce the crash.

The file is now a forwarding shim that re-exports the maintained
`core.gdal_handler` implementation and emits a `DeprecationWarning` on import.
There is one canonical `GDALHandler`.

### FIX — `core/converter.py`: last `del ds` made explicit

`_strip_z_from_2d_layers()` closed its dataset with `del ds`. Unlike the two
fixed in v0.30.7, this one *worked* — `ds` was a genuine local holding the only
reference. It is now an explicit `_flush_and_close_dataset(ds)` anyway: this is
the last writer before DGIWG finalization reopens the same file through
`sqlite3`, so the flush should be deterministic rather than refcount-timed, and
the pattern should not read like the broken ones.

**There are now zero `del ds` statements in `core/` and `tests/`.**

### CHANGE — `tests/test_critical_fixes.py` uses the v0.30.7 close idiom

`ds = handler.close_geopackage(ds)`, with assertions that it returns `None`.
The v0.30.6 comment claiming the file "stays locked until the last Python
reference is dropped (GDAL closes on garbage collection)" was a description of
the bug, not of correct behaviour, and has been corrected.

### Version

Bumped to **0.30.9**. `verify_concurrency_v0.30.8.py` →
`verify_concurrency_v0.30.9.py`; packager likewise.

---

## Verification performed

* `pyflakes` across all of `core/` and `tests/` — **no undefined names remain**,
  confirming the `NameError` above was the only one of its kind.
* `del ds` sweep — zero remaining.
* Deprecation shim confirmed to re-export the canonical class
  (`m.GDALHandler is gdal_handler.GDALHandler` → `True`) and to warn on import.
* 22 static checks + the 4 GDAL-free serialization tests still pass.

## Still not executed

The 8 GDAL-dependent tests in `test_handle_lifetime.py`, the full 294-test
suite, and `verify_concurrency_v0.30.9.py` have **not been run** — no GDAL, no
root to install `libgdal-dev`, no Windows in the development environment.

The triage above is read from logs and source. In particular, the four
"already fixed" groups are inferred from current file contents, **not** from a
passing run. Confirm with:

```bash
python -m pytest tests/ -v
python verify_concurrency_v0.30.9.py
python release_test_v0.30.6.py
```
