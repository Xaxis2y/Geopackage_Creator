# CHANGELOG - GeoPackage Creator v0.30.23

**Release date:** 2026-08-14
**Previous:** v0.30.20 (found the real crash was NOT the libxml2 version
mismatch it claimed to fix - see `CHANGELOG_v0.30.20.md`'s correction)
**Theme:** The actual root-cause fix for the crash open since v0.30.13:
`core/metadata_handler.py`'s process-wide compiled-schema cache is removed.

---

## Context - the full chain, so this fix's evidence is legible on its own

| release | claim | outcome |
|---|---|---|
| v0.30.13 | ABI guard: refuse to compile the XSD if lxml's compiled libxml2 differs from the runtime one | Correct diagnosis of a real defect, but blocked every conversion outright rather than fixing it |
| v0.30.20 | Pin `libxml2=2.14` in `environment.yml` - "the ABI mismatch IS the crash" | Tested on the real machine: the pin worked, both tuples read `(2,14,6)` - and the identical access violation still happened. **Wrong theory**, corrected in that changelog. |
| v0.30.21 | Diagnostic: 8 subprocess probes isolating what else it could be | Found the real differential: an `etree.XMLSchema` created **before** a GDAL write and still alive **after** it crashes on next use or on being freed - independent of libxml2 version agreement. |
| v0.30.22 | Diagnostic: does GDAL disturb libxml2 state once, or on every write? | **Every write.** A schema compiled safely after one write still crashes if a *second* write happens before it is used again (probe P9). Only compiling fresh immediately before use and discarding immediately after survived four repeated cycles (probe P10). |
| **v0.30.23** | **(this release)** Remove the cache; compile fresh every time | Applies P10's proven-safe pattern to the shipped code. |

Every one of those diagnostic runs happened on the real target machine
(Windows 10, GDAL 3.13.2, lxml 6.1.1, matched libxml2 2.14.6 both sides) -
none of this was inferred from the Linux container this assistant runs in,
which does not reproduce the crash at all (see `CHANGELOG_v0.30.20.md`'s
"Verification" section for why that environment is not a valid proxy).

## FIX: core/metadata_handler.py - the compiled-schema cache is removed

`_SHARED_SCHEMA`, live since v0.30.10, compiled the ISO 19139 XSD exactly
once and cached the compiled `etree.XMLSchema` object for the rest of the
process. Every `MetadataHandler` built afterward reused that same object,
across however many GDAL writes happened in between - which, per the
v0.30.22 finding, is unsafe on every single one of those writes, not just
the first.

Removed / replaced:

- **`_SHARED_SCHEMA`, `_SCHEMA_LOADED`** module globals - gone. Replaced by
  `_SCHEMA_PATH_RESOLVED` / `_SCHEMA_SOURCE_PATH` / `_SCHEMA_KNOWN_BROKEN`,
  which cache only the schema **file's filesystem location** (pure
  `Path.exists()` work, independently confirmed to touch no libxml2 state at
  all by `diagnose_crash_v0.30.21.py` probes P1-P3) and whether that file is
  permanently malformed - never a compiled object.
- **`_get_shared_schema()`** - replaced by `_compile_schema_fresh()`, which
  parses and compiles a brand-new `XMLSchema` on **every single call**, still
  gated by the existing `_verify_libxml2_abi()` check (kept - a version
  mismatch is still a real, independent defect worth catching, even though
  fixing it alone doesn't fix this crash).
- **`MetadataHandler.__init__`** no longer compiles or binds a schema at
  construction. It still calls `_verify_libxml2_abi()` on its own, so a
  version mismatch is still reported at construction time rather than
  silently deferred - it just no longer gates a compile, because no compile
  happens here anymore.
- **`MetadataHandler.schema`** is now a `@property`, not a stored attribute.
  Every access - `handler.schema` - compiles fresh. Existing code that reads
  `handler.schema` (including the test suite: `test_metadata_standalone.py`,
  `test_schema_validation.py`) keeps working unchanged, since a property read
  looks identical to an attribute read from the caller's side; it is simply
  no longer free to read repeatedly.
- **`validate_schema()`** now compiles the schema **inside** the same
  `_LXML_LOCK` critical section as the parse/validate/error-log-read that
  follow it, so the schema's entire lifetime - compile, use, drop - is
  contained in one call and can never span a GDAL write. Previously only
  parse/validate/error-log were inside the lock; the schema was fetched
  (from the cache) outside it.
- **`_load_iso19115_schema()`** (kept for backward compatibility) now
  delegates to `_compile_schema_fresh()` too.
- **`reset_schema_cache()`** now resets the file-location cache, not a
  compiled object (there is none to reset).

Nothing about the public API changed - `MetadataHandler()`,
`.generate_package_metadata()`, `.validate_schema()`, `.schema` all still
exist with the same signatures and the same return types.

## Performance note

Every `validate_schema()` call now re-parses and re-compiles the ISO 19139
XSD, where it previously reused a cached object. Measured in this session's
container: **~0.67ms per compile**. A single GeoPackage conversion touches
this at most a handful of times (once per `generate_package_metadata()` /
`generate_layer_metadata()` call), so the added cost per conversion is well
under 10ms - not measurable against a conversion that itself takes seconds.
This is the correct trade: the cache existed for a performance win measured
in single-digit milliseconds, and cost every conversion its correctness.

## Why this wasn't caught by a single earlier fix

The v0.30.10 thread-safety rewrite that introduced `_SHARED_SCHEMA` was
solving a real, different problem - two threads compiling a schema
concurrently corrupted the heap - and its fix (share one schema, serialize
access with a lock) was correct **for that problem**. It happened to also
create a schema that outlives GDAL writes across the life of the process,
which is a second, unrelated hazard that only a machine with the specific
DLL/heap behavior of Windows conda GDAL+lxml builds exposes. Single-threaded
testing, and testing on Linux (where lxml statically links its own libxml2
and never shares state with GDAL's copy - see `CHANGELOG_v0.30.20.md`), could
never have surfaced this independent of the thread-safety issue it was fixed
alongside.

## Files changed

| file | change |
|---|---|
| `core/metadata_handler.py` | **the fix** - compiled-schema cache removed; `schema` is now a property; module docstring gets a new "SCHEMA LIFETIME VS GDAL WRITES" section documenting the full v0.30.20-23 investigation |
| `dev_tools/run_release_check_v0.30.23.py` | **new** - adds a `schema_no_cache` regression guard and an 8-cycle real-batch-conversion stage exercising the actual `MetadataHandler` class, not just a synthetic probe |
| `core/config.py` | `TOOL_VERSION` -> `0.30.23` |
| `core/__init__.py` | `__version__` -> `0.30.23` |
| `geopackage_creator_gui.py`, `packaging/app_main.py` | `APP_VERSION` -> `0.30.23` |
| `packaging/version_info.txt` | `filevers`/`prodvers`/`FileVersion`/`ProductVersion` -> `0.30.23` |
| `README.md` | version banner |
| `VERSION.txt` | new v0.30.23 entry (prepended) |

## Compatibility

Public API unchanged. `MetadataHandler.schema` changes from a stored
attribute to a property - transparent to any caller doing `handler.schema`,
but code that specifically checked `'schema' in vars(handler)` or similar
introspection (none found anywhere in this tree) would need updating. No
other behavioral change.

## Verification

**In this session's Linux container** (GDAL 3.8.4, lxml 6.1.1, matched
libxml2 2.14.6 - does NOT reproduce the crash regardless, see above):

- Full suite: 304 passed, 1 skipped, 0 failed - identical to before this
  change, confirming no regression.
- Direct property test: `handler.schema` returns a **different object** on
  each of two consecutive accesses (proving the cache is actually gone, not
  just renamed), still exposes `.validate`, and a real
  `generate_package_metadata()` + `validate_schema()` round trip still
  returns `True` on valid output.
- Compile cost measured directly: 200 fresh compiles in 133.5ms (0.667ms
  each).
- `dev_tools/run_release_check_v0.30.23.py` run end-to-end: every stage
  passes except the two that are artifacts of this container (no conda
  environment; GDAL 3.8.4 instead of the pinned 3.13.2) - including the new
  8-cycle real-batch-conversion stage, which completed without error.

**NOT yet verified, and required before shipping:**

1. This fix has not been tested on the real Windows/Anaconda machine. Given
   v0.30.20's version-pin theory looked equally solid after container testing
   and then failed on the real machine, **do not treat this container's clean
   run as confirmation** - it is necessary but explicitly not sufficient,
   exactly as established by the last two releases.
2. Run `dev_tools\run_release_check_v0.30.23.py` there. The stage that
   matters most is `batch_conversion_cycle` (stage 6) - it runs 8 real
   GDAL-write + real-metadata-validate cycles through the actual shipped
   `MetadataHandler`, in a crash-safe subprocess, which is the most direct
   real-machine test of this exact fix available short of a full conversion.
3. No real GDB->GPKG conversion has completed on the target machine; no DGIWG
   validation of real output; no GUI or frozen-`.exe` exercise.

If `batch_conversion_cycle` and the two pytest stages all pass on the real
machine, this is very strong evidence the blocker open since v0.30.13 is
finally closed. A real conversion + DGIWG validation is still the last step
before distributing a build.
