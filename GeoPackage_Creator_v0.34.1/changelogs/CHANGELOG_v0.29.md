# CHANGELOG — GeoPackage Creator v0.29.0

**Release date:** 2026-06-15

## Summary

v0.29.0 fixes two software defects that made valid GeoPackages read as
*failures*. Neither defect ever reflected a problem with the data or the output
files. After this release, files that previously showed `success: false` /
`NON-CONFORMANT` are correctly reported as successful and **CONFORMANT** with no
re-conversion of the source.

## Fixes

### 1. Converter reported `success: false` on successful runs (cosmetic)

`core/converter.py` built the conversion report while `result["success"]` was
still its initial `False`; the flag was only flipped to `True` at the very end
of `convert()`, *after* the reports had already been written. Every
`*_report.json` / `*_report.html` therefore captured the stale `False`, even
though `validation.compliant` was `true` with no errors.

**Fix:** `result["success"] = True` is now set immediately before the
report-generation block. All substantive work (conversion, metadata,
finalization, CRS conversion, the DGIWG validation gate) is complete at that
point; only report writing — already wrapped in its own `try/except` — and
duration bookkeeping follow. The duplicate assignment at the end of `convert()`
was removed.

### 2. DGIWG Validator falsely failed Req 24 "Data Validity" (root cause of NON-CONFORMANT)

`DGIWG_Validator_v1_55_updated/dgiwg_validator/utils.py`
(`_decode_gpkg_geom_header`) derived Z/M dimensionality from the GeoPackage
binary header **flags byte**:

```python
"has_z": bool(flags & 0x02),   # WRONG
"has_m": bool(flags & 0x04),   # WRONG
```

Per OGC 12-128r15 §2.1.4 the flags byte contains **no Z/M flags**. Bits 1–3 are
the *envelope indicator* (0=none, 1=XY, 2=XYZ, 3=XYM, 4=XYZM). Any ordinary 2D
geometry carrying an XY envelope (indicator = 1, binary `001`) has bit 1 set, so
`flags & 0x02` was `True` and the validator declared a phantom Z value —
conflicting with the layer's declared `z=0` and producing a Req 24 FAIL on every
line/polygon layer (43 of 89 layers in the CanVec test sets). Point layers, which
use envelope indicator 0, escaped — exactly the pattern seen in the reports.

**Fix:** Z/M is now derived from the WKB geometry **type code** inside the WKB
payload, not the header byte:

- ISO WKB: `1000–1999` = Z, `2000–2999` = M, `3000–3999` = ZM
- EWKB: high bits `0x80000000` = Z, `0x40000000` = M

The Req 24 consumer in `checks.py` is unchanged (it already reads
`hdr["has_z"]` / `hdr["has_m"]`); only the source of those values was corrected.
Comments and the docstring were updated to document the real header layout.

### 3. Version unification

All version strings unified to `0.29.0`:

- `core/config.py` `TOOL_VERSION`
- `core/__init__.py` `__version__`
- `core/report_generator.py` report `version` field, module header, HTML footer
  (previously stamped a stale `0.26`)
- `geopackage_creator_gui.py` window title and headers
- `packaging/app_main.py` `APP_VERSION`
- `packaging/version_info.txt` `filevers` / `prodvers` / string fields

## Impact

No data was ever lost or malformed. Existing `*.gpkg` outputs remain valid and
now validate as CONFORMANT under the corrected validator; the Req 24 FAIL count
drops to 0.
