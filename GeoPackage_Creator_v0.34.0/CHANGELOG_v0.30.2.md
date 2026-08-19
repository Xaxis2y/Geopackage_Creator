# GeoPackage Creator v0.30.2 — Changelog
**Release date:** 2026-06-18

This release is a pure bug-fix drop. No new features; no behaviour changes for
compliant inputs. All six fixes address regressions discovered during a
full-file code and compliance review.

---

## Bug Fixes

### BUG-8 — `gdal_handler.py`: binary fields crash layer copy when `UseExceptions()` is active
**File:** `core/gdal_handler.py` · `copy_layer_to_geopackage()`

`field_names` was built from *all* source fields, but `ogr.OFTBinary` fields
were silently skipped during `CreateField`. With `ogr.UseExceptions()` active,
the subsequent `SetField(fname, …)` call on a field that does not exist in the
output layer definition raised `RuntimeError`, rolling back the entire layer
transaction. Any source dataset containing binary (blob) attribute columns
would produce an empty GeoPackage layer.

**Fix:** replaced the flat `field_names` list with a `copyable_fields` list of
`(source_field_index, field_name)` tuples that excludes `OFTBinary` fields from
both `CreateField` and the feature-copy loop.

---

### BUG-9 — `validation_gate.py`: `conformant` and `summary` never written on success path
**File:** `core/validation_gate.py` · `run_dgiwg_validation()`

After iterating all 37 requirements, `out["conformant"]` was never updated from
its initial `None`, and `out["summary"]` was never assigned. In `converter.py`,
`if not result["dgiwg_validation"].get("conformant"):` evaluated `not None` as
`True`, so **every** run that invoked `--run-dgiwg-validation` unconditionally
emitted a spurious *"DGIWG validator reports mandatory requirement FAILURE(s)"*
warning even when all requirements passed.

**Fix:** added `out["summary"] = summary` and `out["conformant"] = not mandatory_fail`
immediately before the final `return out`.

---

### BUG-10 — `converter.py`: `_finalize_dgiwg_compliance` called as unbound with wrong keyword
**File:** `core/converter.py` · `convert()` CRS side-file loop (line ≈ 525)

CRS-converted side files (Mode A/B/C) were post-processed with:
```python
GeoPackageConverter._finalize_dgiwg_compliance(side_file, dgiwg_reproject=False)
```
`_finalize_dgiwg_compliance` is an **instance method** with no `dgiwg_reproject`
parameter. Python passed `side_file` (a path string) as `self` and rejected the
unknown keyword argument with `TypeError`, meaning CRS-converted GeoPackages
never received their GP14 `application_id`, WKT2 definitions, or WAL checkpoint.

**Fix:** changed the call to `self._finalize_dgiwg_compliance(side_file)`.

---

### BUG-11 — `crs_converter.py`: Mode A returns `success=False` when CRS is already approved
**File:** `core/crs_converter.py` · `convert_crs_mode_a()`

When the source CRS was already DGIWG-approved, the early-return path left
`result['success']` at its default `False`. `converter.py` propagated this as a
CRS conversion failure in the result dict and in the HTML/JSON report, even
though no work needed to be done.

**Fix:** added `result['success'] = True` and `result['target_epsg'] = source_epsg`
to the no-op early-return branch.

---

### BUG-12 — `metadata_handler.py`: layer metadata omits mandatory `gmd:abstract`
**File:** `core/metadata_handler.py` · `generate_layer_metadata()`

ISO 19139 XSD declares `gmd:abstract` as mandatory (`minOccurs="1"`) inside
`gmd:MD_DataIdentification`. Layer metadata omitted it entirely. The XSD
validation step caught this but was non-fatal (logged as a warning), so the
generated XML was structurally non-compliant and would fail a strict OGC/DGIWG
metadata schema check.

**Fix:** added `<gmd:abstract>Feature layer: {layer_name}</gmd:abstract>` and
the companion `<gmd:language>` element to each layer metadata record.

---

### BUG-13 — `dgiwg_compliance.py`: SQLite connections not closed on exception
**File:** `core/dgiwg_compliance.py` · `validate_table_structure()`,
`validate_spatial_indexes()`, `validate_srs_entries()`,
`validate_metadata_tables()`, `validate_extensions()`

All five methods opened a `sqlite3.connect()` connection and called
`conn.close()` at the end of the `try` block. Any exception raised before
`conn.close()` would leave the file handle open, eventually causing
`OperationalError: database is locked` on subsequent access.

**Fix:** moved all five connection opens *outside* the `try` block and closed
them in a `finally` clause so the handle is always released.

---

## Files changed

| File | Change |
|------|--------|
| `core/gdal_handler.py` | BUG-8: binary-field-safe `copyable_fields` |
| `core/validation_gate.py` | BUG-9: assign `conformant` and `summary` |
| `core/converter.py` | BUG-10: fix unbound `_finalize_dgiwg_compliance` call |
| `core/crs_converter.py` | BUG-11: Mode A `success=True` on no-op path |
| `core/metadata_handler.py` | BUG-12: add mandatory `gmd:abstract` to layer metadata |
| `core/dgiwg_compliance.py` | BUG-13: `try/finally` connection cleanup in all 5 methods |
| `core/config.py` | Version → `0.30.2` |
| `VERSION.txt` | Version → `0.30.2` |
| `geopackage_creator_gui.py` | Title/docstring → `v0.30.2` |
| `packaging/version_info.txt` | `filevers`/`prodvers` → `(0, 30, 2, 0)` |
| `CHANGELOG_v0.30.2.md` | This file |
