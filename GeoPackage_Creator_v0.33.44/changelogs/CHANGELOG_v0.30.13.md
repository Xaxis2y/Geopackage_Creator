# CHANGELOG - GeoPackage Creator v0.30.13

**Release date:** 2026-08-05
**Previous:** v0.30.12 (diagnostics only, no release)
**Theme:** root cause confirmed, not just diagnosed - plus a fail-fast guard and a GDAL pin change

---

## Where v0.30.10 left off

v0.30.10 fixed a genuine thread-safety hole: `MetadataHandler.__init__` was
compiling the ISO 19139 XSD via lxml on every instantiation, unsynchronized.
That fix was correct and is kept. It did not stop the crash.

`pytest_main_v0.30.10.log` died inside
`test_convert_with_valid_shapefile` - a test that starts **no threads**. The
faulthandler dump contained exactly one thread. A single-threaded crash is
not a race, which meant the v0.30.10 diagnosis, while a real improvement,
was not the cause of this particular failure.

## The bisect

`diagnose_crash_v0.30.11.py` and `_v0.30.12.py` ran a series of
single-threaded experiments, each in its own subprocess - a Windows access
violation terminates the process rather than raising, so it cannot be
caught, only isolated and localized with numbered step markers.

Two results, each repeated 5 times, settle it:

**`heavy_no_lxml`** - the full `GeoPackageConverter` pipeline: `GDALHandler`
open/copy-layers/close, the sqlite3 metadata-embedding step, DGIWG
finalization, output validation - everything a real conversion does - with
the schema-compile cache pre-seeded to "no schema" and every metadata method
stubbed, so lxml performs **zero** parses or compiles anywhere in the
process.

Result: **clean, 5/5.**

**`gdal_then_schema`** - roughly 20 lines, zero project code: compile the
bundled XSD via `etree.XMLSchema()`, perform one GDAL vector write through
plain `osgeo` calls (`ogr.Open` + `gdal.VectorTranslate`), then make any
further lxml call.

Result: **crashed, 5/5**, an identical Windows access violation every time,
at the first lxml call after the write.

Same machine, same GDAL build. The only variable was whether lxml had
compiled a schema before a GDAL write happened in the same process. That is
dispositive: the fault requires lxml, requires a GDAL write, and requires
nothing specific to this project's pipeline beyond "a GDAL write happened."

## Root cause

The environment fingerprint explains why:

```
LIBXML_COMPILED_VERSION : (2, 14, 6)   <- what this lxml build expects
LIBXML_VERSION (runtime): (2, 15, 3)   <- the libxml2.dll actually loaded
```

Exactly **one** libxml2 image is mapped into the process - GDAL and lxml
share it; it is not two competing copies (confirmed with a corrected
module-enumeration routine - the v0.30.10/11 harness's `ctypes` call had no
`argtypes` set and silently returned nothing, which is why this took an
extra round to pin down).

lxml's compiled extension was built against libxml2 2.14.6's internal
structure layouts. The DLL conda resolves at runtime is 2.15.3. Windows does
not enforce ABI compatibility at load time the way a strict soname check
would - the mismatched DLL loads and runs right up until something
dereferences a structure whose layout changed, which a GDAL write reliably
provokes.

GDAL's own version was independently ruled out as the variable: this
reproduced under GDAL 3.13.1.

## Two things I got wrong along the way

Worth correcting in the open rather than quietly dropping:

**"Priming lxml first is a fix."** An earlier interim summary read: *"lxml_first
clean while gdal_then_lxml crashed -> priming lxml first is a fix."*
Backwards. `lxml_first` (prime lxml, then a GDAL write, then lxml again)
**crashed 5/5** with an identical traceback every time. `gdal_then_lxml`
(lxml used only *after* the write, never before) was the one that stayed
clean. Priming lxml before a GDAL write **causes** the fault; it does not
avoid it.

**"If gdal_only crashes, lxml is entirely innocent."** False on inspection.
`GeoPackageConverter.__init__` builds a `MetadataHandler`, whose `__init__`
compiles the real XSD via lxml - for real - before that experiment's
monkeypatch ever replaces the metadata-generation methods. `gdal_only`
never actually removed lxml from the picture. `heavy_no_lxml` is what it was
supposed to be and was not.

---

## FIX (core/metadata_handler.py) - module version v0.30.13

`MetadataHandler` now refuses to compile the XSD when
`etree.LIBXML_COMPILED_VERSION != etree.LIBXML_VERSION`.

`_verify_libxml2_abi()` runs immediately before the one operation proven to
trigger the fault, inside the same `_LXML_LOCK` introduced in v0.30.10, and
raises `RuntimeError` with the exact remediation steps unless
`config.ALLOW_LIBXML_ABI_MISMATCH` has been explicitly set `True`.

The check sits **outside** the existing `try/except` that downgrades
schema-load failures to a logged warning. A silent downgrade here - "schema
unavailable, validation skipped, continue anyway" - is exactly the failure
mode this guard exists to replace. A clear exception before any conversion
starts is a strictly better outcome than what every user of this tool got
until now: an opaque native crash minutes into a conversion, or during
interpreter shutdown, with no Python traceback at all.

Not cached independently of the existing schema-load cache: a tuple
comparison costs nothing, and caching a separate "already checked" flag would
let a caller who catches the `RuntimeError` and retries slip through
uninspected on the second attempt - defeating the guard on exactly the retry
path most likely to happen in practice.

## FIX (core/config.py)

New `ALLOW_LIBXML_ABI_MISMATCH` flag, default `False`, matching the existing
`ALLOW_CONCURRENT_CONVERSIONS` opt-out pattern: safe default, explicit
opt-in only after independently verifying the specific combination is safe.

`GDAL_TESTED_VERSION` moved to `"3.13.2"`. `GDAL_KNOWN_BAD_VERSIONS`'s
existing comment is extended, not rewritten, to record that a GDAL patch
version has now been investigated **twice** in this project in connection
with an access violation, and both times GDAL's version turned out not to be
the variable.

## GDAL pin moved: 3.13.1 -> 3.13.2

Updated project-wide: `core/config.py`, `requirements.txt`,
`environment.yml`, `DEPENDENCIES.txt`, `INSTALLATION_GUIDE.md`,
`install_dependencies.bat` / `.ps1`, `QUICK_FIX_CONDA.txt`,
`packaging/BUILD_WINDOWS.md`, `packaging/build_windows.ps1`,
`USER_MANUAL.md`, `core/__init__.py`.

Stated as plainly as possible: **this is a support decision, not a fix.** It
does not touch the lxml/libxml2 combination that is the actual confirmed
cause, and the crash is expected to reproduce under 3.13.2 exactly as it did
under 3.13.1 until the environment's lxml and libxml2 are realigned. The ABI
guard above protects both versions equally.

Historical changelogs (`CHANGELOG_v0.30.7.md`, `_v0.30.8.md`) and the older
`VERSION.txt` entries describing the *prior, unrelated* 3.13.1-vs-3.13.2
investigation (a stale-handle bug, fixed in v0.30.7) are deliberately left
untouched. They are accurate records of what was true at the time; rewriting
them would erase real project history and repeat exactly the mistake that
history warns about.

**Left open, flagged rather than guessed at:** `packaging/build_windows.ps1`'s
actual `conda create` command pins `gdal=3.11.4` - matching neither the old
3.13.1 pin nor the new 3.13.2 one, and predating this change. Only the
script's documentation header was updated here (to 3.13.2, for consistency
with the rest of the project). Changing the real EXE-build pin without
knowing why 3.11.4 was chosen felt like the wrong kind of confidence for a
packaging script that produces the shipped binary - worth a second look, not
a silent edit.

---

## Files changed

| file | change |
|---|---|
| `core/metadata_handler.py` | **module v0.30.13** - `_verify_libxml2_abi()`, wired into `_get_shared_schema()` outside the failure-swallowing `except` |
| `core/config.py` | `ALLOW_LIBXML_ABI_MISMATCH` (new), `GDAL_TESTED_VERSION` -> 3.13.2, `TOOL_VERSION` -> 0.30.13, extended historical comment |
| `core/__init__.py` | tested-GDAL-version docstring -> 3.13.2 |
| `requirements.txt` | GDAL pin -> 3.13.2, note on installing lxml+GDAL from one conda solve |
| `environment.yml` | recommended GDAL version comment -> 3.13.2 |
| `DEPENDENCIES.txt`, `INSTALLATION_GUIDE.md`, `install_dependencies.bat`, `install_dependencies.ps1`, `QUICK_FIX_CONDA.txt` | GDAL pin -> 3.13.2 throughout; ABI-mismatch verification step added where the callout already existed |
| `packaging/BUILD_WINDOWS.md`, `packaging/build_windows.ps1` | doc/header GDAL version -> 3.13.2 (actual build-env pin left as-is, flagged above) |
| `USER_MANUAL.md` | version table, install commands, verification steps -> 3.13.2; ABI-mismatch verification step added |
| `VERSION.txt` | new v0.30.13 entry (prepended; all prior entries preserved verbatim) |
| `package_release_v0.30.13.py` | **new** - release packager |

## Compatibility

No public API changed. A process whose lxml and libxml2 versions already
agree sees no behavior difference at all: the guard is one tuple comparison,
gated by the same `_SCHEMA_LOADED` check that already made schema
compilation a once-per-process cost in v0.30.10.

## Next step

```
conda activate geopackage
cd C:\Users\Son\Documents\Geopackage_Creator\GeoPackage_Creator_v0.30.9

python -c "from lxml import etree; print(etree.LIBXML_COMPILED_VERSION, etree.LIBXML_VERSION)"
```

If the two tuples differ, either recreate the environment
(`conda env create -f environment.yml`) or set
`core.config.ALLOW_LIBXML_ABI_MISMATCH = True` only after independently
verifying that specific combination is safe. Then re-run the full suite via
`run_tests_v0.30.10.bat` (still valid - the concurrency/main split is
unrelated to this fix) and confirm `MetadataHandler()` either constructs
normally or raises the new, clear `RuntimeError` instead of crashing.
