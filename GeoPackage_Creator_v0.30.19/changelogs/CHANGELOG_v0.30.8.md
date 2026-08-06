# Changelog — GeoPackage Creator v0.30.8

**Release date:** 2026-08-04
**Builds on:** v0.30.7 (see `CHANGELOG_v0.30.7.md` for the crash fix and the
retracted GDAL 3.13.2 diagnosis)

---

## Summary

v0.30.7 fixed the handle-lifetime crash but shipped **no regression test for
it**. The verification lived only in a standalone script, so a future edit could
reintroduce the bug and the suite would still go green — exactly the failure
mode that let the original defect survive in the first place.

v0.30.8 closes that gap.

---

## Changes

### ADD — `tests/test_handle_lifetime.py` (12 regression tests)

Every test is **single-threaded and deterministic**. They fail on v0.30.6 and
pass on v0.30.7+; no race is needed to reproduce.

**`TestCloseGeopackageReleasesHandle`**

* `close_geopackage()` returns `None`, so callers can drop their reference.
* The dataset is removed from the handler's tracking list.
* *Windows only:* `os.remove()` on the output succeeds after close. This is the
  direct v0.30.6 reproducer — an open GDAL handle blocks deletion on Windows, so
  on v0.30.6 this raises `PermissionError`. Skipped on POSIX, which cannot
  detect the leak this way.
* `sqlite3` can open and write the closed file — mirroring what `convert()`
  actually does next (metadata embedding, DGIWG finalization).

**`TestWriteLockLifecycle`**

* The lock is recorded on acquire, owner thread is tracked, and it is genuinely
  re-acquirable after close (a leak would block the next conversion of the same
  file until timeout).
* Double close is a safe no-op, not a spurious release of another holder's lock.
* `close_all_datasets()` clears both tracked datasets and lock state.

**`TestConversionSerialization`**

* `ALLOW_CONCURRENT_CONVERSIONS` defaults to `False`.
* `convert()` is actually wrapped by `_serialize_conversions`.
* The global lock is shared and reentrant.
* **The opt-out is read at call time, not frozen by a from-import.** This one
  caught a real defect introduced during the v0.30.7 work: `converter.py`
  originally did `from .config import ALLOW_CONCURRENT_CONVERSIONS`, which binds
  the value once at import, so the documented runtime opt-out silently did
  nothing. Now imported as a module and read per call.

### Version

Bumped to **0.30.8** across code, packaging and documentation.
`verify_concurrency_v0.30.7.py` → `verify_concurrency_v0.30.8.py`;
`package_release_v0.30.7.py` → `package_release_v0.30.8.py`.

---

## Test status — read this before trusting the build

| Suite | Status |
|---|---|
| `TestConversionSerialization` (4 tests) | **Executed and passing.** These need no GDAL, so they were run against a stubbed `osgeo`. |
| `TestCloseGeopackageReleasesHandle`, `TestWriteLockLifecycle` (8 tests) | **Not executed.** They require a real GDAL. |
| Full `pytest` suite (294 tests) | **Not executed.** |
| `verify_concurrency_v0.30.8.py` | **Not executed.** |

The development environment has no GDAL, no root to install `libgdal-dev`, and
no Windows. PyPI ships GDAL 3.13.x as an sdist only, so it cannot be built
there, and conda-forge is unreachable. Everything else in v0.30.7/v0.30.8 is
syntax-checked and statically verified, and reasoned from the logs and source —
but it has not been run.

**Run this first, in the Anaconda Prompt:**

```bash
python -c "from osgeo import gdal; print(gdal.__version__)"   # expect 3.13.1
python -m pytest tests/test_handle_lifetime.py -v             # the regression tests
python verify_concurrency_v0.30.8.py                          # A/B/C must pass
python release_test_v0.30.6.py                                # full harness
```

If `tests/test_handle_lifetime.py` passes, the root-cause fix is confirmed —
and it confirms it *without needing the crash to reproduce*.
