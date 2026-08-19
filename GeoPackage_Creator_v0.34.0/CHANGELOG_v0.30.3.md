# GeoPackage Creator v0.30.3 — Changelog
**Release date:** 2026-06-18

Pure bug-fix release following a second-pass code review. No new features; no
behaviour changes for compliant inputs. All six fixes address resource leaks,
a performance regression, and stale version strings discovered after v0.30.2.

---

## Bug Fixes

### BUG-14 — `crs_converter.py`: `detect_crs` datasource handle leaked
**File:** `core/crs_converter.py` · `detect_crs()`

`ogr.Open()` was called but the returned `DataSource` was never explicitly
closed.  Python/GDAL eventually garbage-collects it, but the timing is
non-deterministic; on Windows the file handle may stay open long enough to
block a subsequent write to the same path.

**Fix:** moved `ds = None` before the `try` block and added a `finally:
ds = None` clause so the handle is always released whether the call succeeds
or raises.

---

### BUG-15 — `crs_converter.py`: bare `except:` in `validate_crs_support`
**File:** `core/crs_converter.py` · `validate_crs_support()`

A bare `except:` catches `BaseException`, including `KeyboardInterrupt`,
`SystemExit`, and memory errors that should propagate. This made it impossible
to interrupt the tool during a long CRS validation scan.

**Fix:** changed to `except Exception:`.

---

### BUG-16 — `crs_converter.py`: `_perform_conversion` has no transaction
**File:** `core/crs_converter.py` · `_perform_conversion()`

`gdal_handler.copy_layer_to_geopackage()` wraps all `CreateFeature()` calls in
a single `StartTransaction()`/`CommitTransaction()` for performance. The
parallel CRS-conversion path in `_perform_conversion()` had no such wrapping:
each feature was its own auto-committed SQLite transaction — typically 10–100×
slower for large layers.

**Fix:** added `output_layer.StartTransaction()` before the feature loop and
`output_layer.CommitTransaction()` after, with `RollbackTransaction()` in the
`except` handler.

---

### BUG-17 — `gdal_handler.py`: SRS objects stored without cloning
**File:** `core/gdal_handler.py` · `read_source_data()`

`layer.GetSpatialRef()` returns a reference into the `DataSource`'s internal
memory. When `read_source_data()` returns, the local `ds` variable goes out of
scope and Python eventually frees the underlying GDAL dataset. Any `srs` object
stored in `layers_info` then points at freed memory, which can cause silent
wrong values or crashes when those objects are accessed later.

**Fix:** added `srs = srs.Clone()` immediately after `GetSpatialRef()` so each
stored SRS is a fully independent copy that outlives the source DataSource.

---

### BUG-18 — `gdal_handler.py`: `validate_geopackage_output` datasource not closed
**File:** `core/gdal_handler.py` · `validate_geopackage_output()`

`ogr.Open(gpkg_path)` was called for read-back validation but `ds` was never
explicitly deleted, leaving the file handle open until garbage collection.
On Windows this prevents the caller from immediately moving or overwriting
the file.

**Fix:** added `ds = None` initialisation before the `try` block and a
`finally: ds = None` clause.

---

### BUG-19 — `report_generator.py` / `core/__init__.py`: version strings not bumped
**Files:** `core/report_generator.py`, `core/__init__.py`

Three version strings in `report_generator.py` (`"0.30.1"` in the module
docstring, the HTML page title, and the JSON `version` field) and
`__version__ = "0.30.1"` in `core/__init__.py` were hardcoded and were missed
during the v0.30.2 version bump.  Any generated report would claim to be
v0.30.1 regardless of the installed version.

**Fix:** updated all four occurrences to `"0.30.3"` and made both files
consistent with the rest of the codebase.

---

## Files changed

| File | Change |
|------|--------|
| `core/crs_converter.py` | BUG-14: `detect_crs` — `finally: ds = None` |
| `core/crs_converter.py` | BUG-15: `validate_crs_support` — `except Exception:` |
| `core/crs_converter.py` | BUG-16: `_perform_conversion` — per-layer transaction |
| `core/gdal_handler.py` | BUG-17: `read_source_data` — `srs.Clone()` |
| `core/gdal_handler.py` | BUG-18: `validate_geopackage_output` — `finally: ds = None` |
| `core/report_generator.py` | BUG-19: version strings → `0.30.3` |
| `core/__init__.py` | BUG-19: `__version__` → `"0.30.3"` |
| `core/config.py` | Version → `0.30.3` |
| `VERSION.txt` | Version → `0.30.3` |
| `geopackage_creator_gui.py` | Title/docstring → `v0.30.3` |
| `packaging/version_info.txt` | `filevers`/`prodvers` → `(0, 30, 3, 0)` |
| `CHANGELOG_v0.30.3.md` | This file |
