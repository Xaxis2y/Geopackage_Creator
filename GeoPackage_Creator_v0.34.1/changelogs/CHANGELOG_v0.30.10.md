# CHANGELOG - GeoPackage Creator v0.30.10

**Release date:** 2026-08-04
**Previous:** v0.30.9
**Theme:** the v0.30.9 access violation was libxml2, not GDAL

---

## The crash

`python -m pytest tests/ -v` on v0.30.9 died at test 4 of 305:

```
tests/test_concurrency.py::TestConcurrentWrites::test_concurrent_writes_different_files
Windows fatal exception: access violation

Current thread 0x00008674 (most recent call first):
  core\metadata_handler.py, line 125 in validate_schema
  core\metadata_handler.py, line 335 in generate_package_metadata
  core\converter.py,        line 586 in convert
  core\converter.py,        line 110 in wrapper
  tests\test_concurrency.py, line 128 in convert_file
```

The other 301 tests produced no result. A native crash is not a test failure -
it terminates the process.

## Reading the dump

Three facts in that thread dump narrow the cause to one file.

1. **The other two worker threads were at `converter.py:109`.** That is
   `with global_conversion_lock():` inside `_serialize_conversions`. They had
   not entered `convert()`. The v0.30.7 serialization was doing exactly its
   job.

2. **The faulting thread had already finished with GDAL.** `converter.py:586`
   is well past `converter.py:574`, where the GeoPackage is closed and the
   write lock released. No dataset was open, and no other thread held one.

3. **The faulting frame is pure lxml.** `metadata_handler.py:125` was
   `etree.fromstring(metadata_xml_string.encode('utf-8'))`.

Only one thread was in GDAL, and it had left. This was never a GDAL crash.

## Root cause

`MetadataHandler.__init__` compiled the ISO 19139 XSD on **every**
instantiation:

```python
schema_doc = etree.parse(str(schema_path))
schema = etree.XMLSchema(schema_doc)      # <- once per handler
```

`GeoPackageConverter.__init__` (converter.py:217) constructs a
`MetadataHandler`. The test constructs the converter **inside each worker
thread** (test_concurrency.py:127) - before `convert()` is called, and
therefore outside the lock that serializes everything else. Three threads
compiled an XML Schema simultaneously.

Compiling an XML Schema is the least thread-safe operation in libxml2.
`xmlSchemaParse()` interns strings into shared dictionaries, installs the
global structured-error handler, and resolves imports through shared caches.
Two of those running at once corrupts the heap.

Heap corruption does not fault where the damage is done. It faults at the next
allocation from the same arena - which here was the `etree.fromstring()` a few
hundred microseconds later, in whichever thread reached it first. That is
precisely the shape of the reported traceback, and it explains why the visible
frame looked innocent.

The window was small, which is why v0.30.6 through v0.30.9 shipped with it
open and only tripped over it intermittently.

---

## FIX (core/metadata_handler.py) - module version v0.30.10

Three changes, all in one file. No behaviour visible to callers changed.

### 1. The compiled XSD is now a process-wide singleton

`_get_shared_schema()` compiles the schema once, under `_LXML_LOCK`, with
double-checked locking. Every `MetadataHandler` binds that same object. The
second and third callers never enter `etree.XMLSchema()` at all, so the race
is closed rather than narrowed.

A failed load is cached too. If the XSD is missing or invalid the answer is
`None` for the life of the process, instead of a fresh filesystem walk and a
fresh warning per handler.

Side effect: constructing a converter no longer parses a 13 KB XSD. The suite
builds hundreds of handlers.

### 2. All libxml2 access is serialized on `_LXML_LOCK`

`validate_schema()` holds one acquisition across parse, validate, and the
`error_log` read.

`schema.error_log` is mutable state living **on the shared schema object**.
Even if libxml2 never faulted, two threads validating at once would interleave
their error lists and report each other's failures. Holding the lock across
all three steps means the errors raised describe the document just validated.

`lxml_lock()` is exported so anything else in the process that reaches into
lxml can serialize against this module rather than racing it.

The stdlib `xml.etree.ElementTree.fromstring()` well-formedness checks are
deliberately left unlocked. Those run on expat, build an independent parser per
call, and share nothing with libxml2.

### 3. Parsing is hardened

`_build_hardened_parser()` returns a fresh `etree.XMLParser` per call with:

| option | effect |
|---|---|
| `no_network=True` | never fetch a DTD or schema over the wire |
| `resolve_entities=False` | closes XXE (`file://` disclosure) and billion-laughs |
| `huge_tree=False` | keeps libxml2's depth and size guards armed |

This removes lxml's implicit thread-local default parser from the picture -
one less piece of shared mutable state - and, for a tool that validates
metadata for defense customers, closes two XML attack classes as a side effect.

A fresh parser per call rather than a cached one is intentional: an
`XMLParser` carries its own error log and its in-progress tree, so a shared
one would be another hazard of exactly the kind this release removes.

### Cost

Validating a ~4 KB metadata document is on the order of a millisecond; a
conversion is seconds to minutes. The lock is uncontended in the shipped GUI
and CLI, which never run two conversions at once, and is noise even under the
3-thread test.

### Also fixed

`validate_schema()` no longer double-wraps its own error. A schema failure
previously came back as
`"Schema validation error: ISO 19115 schema validation failed: ..."` because
the `ValueError` it raised was caught by its own `except Exception`. The
message is now raised once.

---

## FIX (pytest.ini, tests/test_concurrency.py) - the suite survives a crash

Registered a `concurrency` marker and tagged `tests/test_concurrency.py` with
it. Every test in that module drives native code from more than one thread.

The tests are **not** deselected by default - `pytest tests/` still runs all
305. Silently skipping tests is how a crash-prone path stops being tested at
all. The marker exists so the run can be split:

```
pytest tests/ -v -m "not concurrency"   > pytest_main_v0.30.10.log 2>&1
pytest tests/ -v -m concurrency         > pytest_concurrency_v0.30.10.log 2>&1
```

A native crash in pass 2 can no longer discard pass 1's results.

`tests/test_critical_fixes.py` is deliberately left unmarked. Its background
thread only acquires a Python `RLock`; it makes no native calls.

---

## NEW (run_tests_v0.30.10.bat)

Runs the two passes above, reports both exit codes, and decodes them:

| exit code | meaning |
|---|---|
| 0 | all passed |
| 1 | normal pytest failure |
| 5 | no tests collected |
| -1073741819 | `0xC0000005` access violation - native crash |
| -1073740940 | `0xC0000374` heap corruption - same root cause |

---

## NEW (verify_lxml_threadsafety_v0.30.10.py)

A harness that tests the diagnosis above rather than asserting it.

An access violation cannot be caught with `try/except`, so **every phase runs
in its own subprocess** and the driver records the exit code. Racy phases run
`--attempts` times (default 5), because a race that did not fire once has not
been disproved.

| phase | what it does | expected |
|---|---|---|
| `env` | lxml build, libxml2 runtime-vs-compiled versions, pip-vs-conda provenance, GDAL version, every libxml2 DLL mapped into the process | info |
| `old_unlocked` | the v0.30.9 pattern, lxml only, no GDAL | **crashes** |
| `old_unlocked_gdal` | same, with GDAL's libxml2 also mapped | **crashes** |
| `new_locked` | the v0.30.10 pattern standalone | clean |
| `real_module` | the shipped `core.metadata_handler` under threads | clean |
| `real_module_gdal` | same, with GDAL loaded | clean |
| `converter` | end-to-end 3-thread conversion - the test that died | clean |

The `env` phase also rules out the one competing explanation: **two libxml2
images mapped into one process**. A pip lxml wheel statically bundles its own
libxml2, and if GDAL came from conda-forge the process ends up with two
allocators managing one set of `xmlDoc` structures - which produces this same
access violation for a completely different reason. The phase enumerates
loaded modules and flags it, and checks `LIBXML_COMPILED_VERSION` against the
runtime `LIBXML_VERSION`.

```
conda activate geopackage
python verify_lxml_threadsafety_v0.30.10.py
```

Writes `verify_lxml_v0.30.10.log`.

---

## Files changed

| file | change |
|---|---|
| `core/metadata_handler.py` | **rewritten** - shared schema singleton, `_LXML_LOCK`, hardened parser, `lxml_lock()`, `reset_schema_cache()`, `get_schema_source_path()` |
| `pytest.ini` | registered the `concurrency` marker |
| `tests/test_concurrency.py` | added `pytestmark = pytest.mark.concurrency` |
| `run_tests_v0.30.10.bat` | **new** - split test runner |
| `verify_lxml_threadsafety_v0.30.10.py` | **new** - subprocess-isolated verification harness |
| `package_release_v0.30.10.py` | **new** - release packager |
| `VERSION.txt` | v0.30.10 entry |

## Compatibility

No public API changed. `MetadataHandler.schema`, `validate_schema()`,
`generate_package_metadata()`, `generate_dmf_metadata()` and
`generate_layer_metadata()` keep their signatures and their return values.
`_load_iso19115_schema()` is retained and now delegates to the shared cache.

`handler.schema` is now the *same object* on every handler in the process. No
test mutates it, and lxml `XMLSchema` objects are immutable after
construction, so this is invisible - but a test that wanted a private schema
would need `reset_schema_cache()`.

## Next step

```
conda activate geopackage
cd C:\Users\Son\Documents\Geopackage_Creator\GeoPackage_Creator_v0.30.9

python verify_lxml_threadsafety_v0.30.10.py
run_tests_v0.30.10.bat
```

Send back `verify_lxml_v0.30.10.log`, `pytest_main_v0.30.10.log` and
`pytest_concurrency_v0.30.10.log`.
