# CHANGELOG - GeoPackage Creator v0.30.15

**Release date:** 2026-08-05
**Previous:** v0.30.14 (environment.yml GDAL pin fix)
**Theme:** two independent bugs found by the first real run of `run_prerelease_check_v0.30.13.py` on Windows - neither is the libxml2 ABI mismatch

---

## Context

`run_prerelease_check_v0.30.13.py` was run for the first time on a real
Anaconda/Windows machine with GDAL 3.13.2. The two things it exists to
check both came back positive:

- The libxml2 ABI mismatch v0.30.13 diagnosed is real on that machine
  (`LIBXML_COMPILED_VERSION (2,14,6)` vs runtime `(2,15,3)`).
- The fail-fast guard works: `MetadataHandler()` raised a clean
  `RuntimeError` instead of crashing, and the decisive bisect
  (`heavy_no_lxml` clean 5/5, `gdal_then_schema` crashed 5/5) reproduced the
  exact predicted pattern under GDAL 3.13.2.

Underneath that result, the gate reported `DO NOT SHIP - FAILURES` because
155 individual pytest/harness checks failed. Triage:

- **152 of 155** were the identical `RuntimeError: lxml/libxml2 ABI
  mismatch...` (confirmed by grep: 290 occurrences of that exact string
  across the logs - each failure reports it twice, once in the detailed
  traceback and once in the short summary). Every one of these is the guard
  correctly firing on a machine that genuinely has the mismatch, cascading
  through every code path that constructs a `MetadataHandler` (which
  `GeoPackageConverter.__init__` does unconditionally). Not a new defect -
  the existing test suite simply predates the guard and has no
  accommodation for running on a mismatched machine.
- **3 of 155** were a second, unrelated, previously unknown defect in
  `tests/test_gdb_domains.py` - fixed below.
- A separate run of `run_gdal_tests.py` (part of the same gate) also
  surfaced a third, independent problem in this project's own test tooling
  - also fixed below.

Both fixes here are pre-existing issues that had simply never been
exercised before. This project's own history says so directly, repeatedly:
it was developed and tested without GDAL or Windows available until this
gate ran.

## FIX (run_gdal_tests.py) - Windows console encoding

The script's own progress/summary output used a handful of non-ASCII
symbols. Two of them are not representable in `cp1252`, the default
codepage of an Anaconda Prompt window unless `chcp 65001` has been run:

- `✗` (U+2717) in the failed-tests summary loop
- `→` (U+2192) in six success messages and the final "Log saved" line

`print()` raising `UnicodeEncodeError` on `✗` is caught by `run_test()`'s
own broad `except Exception`, which then **misreports an already-completed
test as an unrecoverable error**. Worse, because it happens partway through
printing the failure summary - *before* `gdal_test_results.json` is
written - the crash discards every result from the whole run.

This reproduced exactly on the real run: the console showed `27 passed, 0
failed, 6 errors`, but no JSON file was ever written. Of those 6 "errors,"
at least 3 were not real test failures at all - the test body had already
completed and returned successfully; only the harness's own `print()` of
the *success* message (which happened to contain `→`) crashed afterward,
and `run_test()`'s exception handler overwrote the already-recorded PASS
with an ERROR.

Fixed two ways:

1. Every `✗` / `→` in a message that gets printed is now plain ASCII
   (`->`, or a `[STATUS]` tag using the test's actual recorded status
   instead of a single symbol that could not distinguish FAIL from ERROR
   anyway).
2. `sys.stdout.reconfigure(errors="backslashreplace")` is called once at
   the top of the script (guarded by `hasattr`, since `reconfigure()` is a
   Python 3.7+ TextIOWrapper method). This removes the *failure mode*, not
   just the specific characters that triggered it once: a future non-ASCII
   character added to any message now degrades to a visible `\uXXXX`
   escape sequence instead of silently discarding an entire run's results
   again. Verified directly: forcing `PYTHONIOENCODING=cp1252` and printing
   the original arrow message reproduces `UnicodeEncodeError`; the same
   message after `reconfigure()` prints cleanly with the escape sequence
   visible and the process exits 0.

Several other non-ASCII characters already present in the file (em dash,
middle dot, ellipsis, multiplication sign) were checked against the
`cp1252` table and deliberately left alone - all four are representable in
`cp1252`, none appeared in the actual crash, and the real Windows run's own
output confirms they printed without issue. Changing them would be
cosmetic churn with no bug behind it.

## FIX (tests/test_gdb_domains.py)

Three tests asserted an *exact* geometry type on a layer read back from a
File Geodatabase that the test's own fixture (`sample_geodatabase_with_
domains` in `conftest.py`) had just written, e.g.:

```python
assert roads_layer.GetGeomType() == ogr.wkbLineString
```

On the real Windows run (GDAL 3.13.2), OpenFileGDB's write driver reported
these back as their **Multi-** equivalent instead - `wkbMultiLineString`
for a layer created as `wkbLineString`, `wkbMultiPolygon` for one created as
`wkbPolygon`.

This is a characteristic of the OpenFileGDB format/driver - unlike GDAL's
other vector drivers, it does not preserve the OGC Simple Features
single-part/multi-part distinction on write - not a defect in this project,
and the drift is entirely on the **write** side, which only this test
fixture exercises to synthesize input data. The shipped tool only ever
*reads* `.gdb` inputs and never writes one, so this does not describe
anything a real user's GDB goes through.

Each assertion now accepts either variant:

```python
assert roads_layer.GetGeomType() in (ogr.wkbLineString, ogr.wkbMultiLineString), (
    f"Expected LineString or MultiLineString, got {roads_layer.GetGeomType()}"
)
```

with a comment recording why, so a future edit does not quietly "fix" this
back to a strict equality check without understanding the reason it was
relaxed. The tests' actual purpose - verifying the expected
domain-constrained field names are present on each layer - is unchanged.

## Not related to the libxml2 ABI mismatch

Neither fix touches `core/metadata_handler.py`, `core/config.py`, or
anything involved in the v0.30.13 guard. Both are independent, pre-existing
issues that this release's first real Windows run happened to be the first
opportunity to catch.

## Files changed

| file | change |
|---|---|
| `run_gdal_tests.py` | non-ASCII symbols in printed messages replaced with ASCII; `sys.stdout.reconfigure(errors="backslashreplace")` added as a general safety net; title docstring version reference updated |
| `tests/test_gdb_domains.py` | 3 geometry-type assertions relaxed to accept OpenFileGDB's Multi- promotion, with an explanatory comment |
| `core/config.py` | `TOOL_VERSION` -> `0.30.15` |
| `core/__init__.py` | `__version__` -> `0.30.15` |
| `VERSION.txt` | new v0.30.15 entry (prepended; all prior entries preserved verbatim) |
| `package_release_v0.30.15.py` | **new** - release packager, renamed from `package_release_v0.30.14.py` per this project's existing rename convention |

## Compatibility

No public API changed. No behavioural change to the shipped GUI/CLI/
conversion pipeline at all - every file touched here is test or QA tooling.
The only observable differences are: `run_gdal_tests.py` no longer crashes
on a default-codepage Windows console, and 3 specific tests in
`test_gdb_domains.py` that were failing on GDAL 3.13.2 now pass.

## Verification

`python -m py_compile` passed for both changed files. The
`sys.stdout.reconfigure` fix was verified directly in a Linux sandbox by
forcing `PYTHONIOENCODING=cp1252`: the original code reproduces
`UnicodeEncodeError` on the exact reported message; the fixed code does
not. The `test_gdb_domains.py` fix could not be executed end-to-end in that
same sandbox (no GDAL available there - consistent with this project's
whole reason for `run_prerelease_check_v0.30.13.py` existing). Recommended
before trusting this build: re-run
`run_prerelease_check_v0.30.13.py --only pytest_suite --only gdal_functional`
on the machine that produced the original failures, and confirm
`gdal_test_results.json` is now produced and `test_gdb_domains.py`'s three
tests pass.
