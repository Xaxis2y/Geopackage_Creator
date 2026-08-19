# Changelog — GeoPackage Creator v0.30.7

**Release date:** 2026-08-04
**Supersedes:** v0.30.6 (packaged but never green — see below)

---

## Summary

v0.30.6 was packaged on 2026-08-04 at 10:17 while its own release-test harness
was crashing. This release fixes the crash and corrects the diagnosis that was
briefly attached to it.

The crash was **not** a GDAL 3.13.2 regression. It is a defect in this
codebase, present since well before v0.30.6, which the v0.30.6 fix to
`core/validators.py` stopped masking.

---

## The retracted diagnosis

The first analysis blamed GDAL 3.13.2, because two things were true at once:
the environment had drifted from GDAL 3.13.1 to 3.13.2, and the release test
started dying with `Windows fatal exception: access violation`. Correlation was
read as cause. Four pieces of evidence overturned it:

1. **The masking fix is timestamped.** `core/validators.py` was modified at
   **12:22:03 on 2026-07-24** — eight minutes *after* the 12:14 run, which is
   the only release test that ever ran to completion. Before that fix,
   `validate_output_path()` probed directory write access using a fixed
   filename (`.gpkg_creator_test`), so concurrent threads raced on one probe
   file and aborted early.

2. **The Jul 24 log shows mundane failures, not a crash.** The concurrency
   tests failed with `No write permission for directory: ...` and
   `[WinError 2] ... '.gpkg_creator_test'` — ordinary Python assertions. The
   threads died at the *validation* stage and never reached concurrent GDAL
   work at all. The concurrent path had therefore never run to completion on
   **any** GDAL version, 3.13.0 included.

3. **The v0.30.6 mitigation changed nothing.** Giving each thread a private
   copy of the *source* shapefile did not stop the crash, because the defect is
   on the **output** side. The 10:12 and 10:18 logs crash at different line
   numbers in the same test — before and after that mitigation — which proves
   it was irrelevant.

4. **GDAL 3.13.2's release notes contain threading _hardening_, not a
   regression** (`IVSIS3LikeFSHandler::Sync()` gained more robust locking). No
   published GPKG/OGR threading regression matches these symptoms.

`GDAL_KNOWN_BAD_VERSIONS` is consequently **empty**. The 3.13.1 pin is retained
for reproducibility, not because 3.13.2 is suspect.

---

## Root cause (FIXED)

`GDALHandler.close_geopackage()` ended with `del ds`. `ds` is a *parameter*, so
this unbound a local name and did nothing to the dataset. The caller's
reference stayed alive, so **the GeoPackage was never closed.**

In `GeoPackageConverter.convert()` that caller reference — `out_ds` — then
remained in scope for the entire remainder of the conversion, during which the
same `.gpkg` is reopened through `sqlite3` to embed ISO 19115 / DMF metadata and
apply DGIWG finalization. Two live handles on one file. Worse, the write lock
was released *before* the file was actually closed, so a second thread was free
to begin its own conversion against a GeoPackage that GDAL still had open and
buffered.

Single-threaded, this is silent corruption risk. Multi-threaded, it is an
access violation — which is what the harness hit the moment the validators fix
let three threads reach that code simultaneously for the first time.

---

## Changes

### FIX (CRITICAL) — `core/gdal_handler.py`, `core/converter.py`
`close_geopackage()` now flushes every layer, calls `FlushCache()`, calls
`Dataset.Close()` where the GDAL build provides it (≥ 3.7), and **returns
None** so the caller can drop its own reference. `converter.convert()` now
assigns that return value back over `out_ds`. The dataset is fully closed
*before* the write lock is released, so no second writer can open a file GDAL
still holds.

### FIX — `core/gdal_handler.py`: `close_all_datasets()`
Same `del ds` no-op inside a `for` loop, where it also rebound on every
iteration. Datasets are now flushed and explicitly closed via the shared
`_flush_and_close_dataset()` helper.

### FIX — `core/gdal_handler.py`: write-lock ownership
Four copies of a `try: lock.release() except RuntimeError: pass` block are
replaced by `_release_write_lock()`, which tracks the acquired lock object and
the owning thread id. Two real bugs were hidden by that swallowed exception:
releasing a lock the current thread never owned, and — when `acquire()` timed
out before `_active_output_path` was updated — releasing *another conversion's*
lock. Both are now logged rather than silently ignored.

### FIX — `core/gdal_handler.py`: `UseExceptions()` moved to import time
`gdal.UseExceptions()` / `ogr.UseExceptions()` were called in
`GDALHandler.__init__`. They mutate process-global binding state and swap the
installed CPL error handler, so every thread constructing a handler was racing
on that global while other threads were already executing inside GDAL. Now
applied exactly once, at module import.

### ADD — process-wide conversion serialization
`convert()` is wrapped by `_serialize_conversions`, which holds a module-level
lock for the whole conversion — GDAL write, sqlite3 metadata embedding, DGIWG
finalization and validation are one critical section. OGR gives no guarantee
that two such sequences may run concurrently in one process, and when the
guarantee is absent the failure mode is a native crash rather than an
exception. The shipped GUI and CLI never run more than one conversion at a
time, so this costs them nothing. Opt out with
`config.ALLOW_CONCURRENT_CONVERSIONS = True`.

### FIX — GDAL version pinning across all install paths
Every install command read `conda install -c conda-forge gdal` with no
version, which is how the environment drifted 3.13.1 → 3.13.2 unnoticed and
sent the investigation down the wrong path. Now pinned to `gdal=3.13.1` in
`requirements.txt`, `DEPENDENCIES.txt`, `INSTALLATION_GUIDE.md`,
`install_dependencies.bat`, `install_dependencies.ps1` and
`QUICK_FIX_CONDA.txt`; pip paths pinned to `GDAL==3.13.1`.

### ADD — `verify_concurrency_v0.30.8.py`
Standalone verification harness. TEST A proves the handle is really released
(single-threaded — this is the root-cause check and needs no threads). TEST B
proves lock acquire/release is balanced and owner-checked. TEST C runs the
serialized default. TEST D runs the *unserialized* path in a **subprocess**, so
a native access violation is reported rather than killing the run.

### Version
Bumped to **0.30.7** across code, packaging and documentation.

---

## Known state

* `tests/test_concurrency.py` still carries the v0.30.6 per-thread source-copy
  mitigation. It is harmless but addresses a non-issue; it can be simplified
  once v0.30.7 is confirmed green.
* The `test_gdb_domains.py` fixture errors (`OGR Error: Corrupt data`) and the
  `test_critical_fixes.py` / `test_validators.py` failures visible in the
  Jul 24 log are **unrelated** to this crash and remain open.
* **v0.30.7 has not been executed.** It was developed in a Linux sandbox with
  no GDAL and no Windows. Every change is syntax-checked and reasoned from the
  logs and source, but nothing here has been run. Run
  `verify_concurrency_v0.30.8.py` and then `release_test_v0.30.6.py` before
  trusting it.
