# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Release check for GeoPackage Creator v0.34.2.

PURPOSE
-------
This release replaces the process-wide compiled-schema cache in
`core/metadata_handler.py` (`_SHARED_SCHEMA`, live since v0.30.10) with a
fresh compile on every single access. That is a structural fix, not a
version pin - see the chain of evidence below - and it has NOT yet been
verified on a real Windows/Anaconda machine. This script verifies it.

THE FULL STORY, so this script's stages make sense:
  v0.30.13  ABI guard added: refuses to compile the XSD if lxml's compiled
            libxml2 differs from the one loaded at runtime. Correct as far
            as it went, but blocked every conversion outright.
  v0.30.20  Pinned `libxml2=2.14` in environment.yml, believing the version
            MISMATCH was the whole crash. Deployed and tested on the real
            machine: the pin worked (tuples now matched exactly) and the
            SAME access violation still happened. Necessary, not sufficient.
  v0.30.21  Isolated the real differential in 8 subprocess probes: an lxml
            object (a compiled XMLSchema) that is created before a GDAL
            write and stays alive past it crashes on next use or on being
            freed - regardless of whether the libxml2 versions match.
  v0.30.22  Narrowed further: does GDAL disturb libxml2 state ONCE (so a
            schema compiled after the first write is safe forever), or on
            EVERY write? Result: EVERY write (P9 crashed; a schema compiled
            AFTER one write did not survive a SECOND write). Only compiling
            fresh immediately before each use, and discarding immediately
            after, survived four repeated cycles (P10).
  v0.30.23  (this release) Applies P10's proven-safe pattern to the actual
            code: `_SHARED_SCHEMA` is removed. `MetadataHandler.schema` is
            now a property that compiles a brand-new `etree.XMLSchema` on
            every access; nothing stores the result anywhere that could
            outlive the statement using it.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\run_release_check_v0.30.23.py

Writes: dev_tools\\logs\\release_check_v0.30.23_<timestamp>.log, incrementally
- a hard crash still leaves everything up to that point on disk. Send that
file back either way.

STAGES
------
  1. environment          - Python/platform, conda env name
  2. libxml2_abi           - version tuples (necessary, proven NOT sufficient
                              alone - see stage 5)
  3. gdal                  - version, GPKG driver, pin agreement
  4. metadata_ctor         - MetadataHandler() construction
  5. schema_no_cache       - regression guard: confirms `.schema` returns a
                              DIFFERENT object on every access (the cache is
                              really gone, not just renamed)
  6. batch_conversion_cycle- THE decisive check: 8 simulated conversions in
                              one process - real GDAL write, then a REAL
                              MetadataHandler.generate_package_metadata() +
                              .validate_schema() call, repeated - run in a
                              crash-safe subprocess. This exercises the
                              actual shipped fix under the actual call
                              pattern, not a synthetic probe.
  7. version_strings       - all version sources agree at 0.30.23
  8. pytest_main           - the main suite
  9. pytest_concurrency    - the concurrency suite
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path(__file__).resolve().parent / "logs"
EXPECTED_VERSION = "0.34.2"
EXPECTED_GDAL = "3.13.2"
PYTEST_BASETEMP = PROJECT_ROOT / "dev_tools" / "logs" / "pytest_tmp"

_results: list[tuple[str, bool, str]] = []

# The log file is opened at STARTUP and every line is flushed+fsynced as it
# is written, so a hard crash in any stage still leaves the log on disk up
# to that point - see CHANGELOG_v0.30.20.md for why the first version of
# this family of scripts did not do this and lost a run's entire log.
_LOG_FH = None


def _open_log():
    global _LOG_FH
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"release_check_v{EXPECTED_VERSION}_{datetime.now():%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)
    return path


def log(msg: str = "") -> None:
    print(msg, flush=True)
    if _LOG_FH is not None:
        _LOG_FH.write(msg + "\n")
        _LOG_FH.flush()
        os.fsync(_LOG_FH.fileno())


def header(title: str) -> None:
    log("")
    log("=" * 78)
    log(f"  {title}")
    log("=" * 78)


def record(stage: str, ok: bool, detail: str = "") -> None:
    _results.append((stage, ok, detail))
    log(f"  [{'PASS' if ok else 'FAIL'}] {stage}" + (f" - {detail}" if detail else ""))


# --------------------------------------------------------------------------
# 1. environment
# --------------------------------------------------------------------------
def stage_environment() -> None:
    header("STAGE 1: environment")
    log(f"  python            : {sys.version.split()[0]} ({sys.executable})")
    log(f"  platform          : {platform.platform()}")
    log(f"  conda env         : {os.environ.get('CONDA_DEFAULT_ENV', '<none>')}")
    log(f"  project root      : {PROJECT_ROOT}")

    env_name = os.environ.get("CONDA_DEFAULT_ENV", "")
    if env_name == "base":
        record("environment", False, "running in BASE environment - activate 'geopackage' instead")
        return
    if not env_name:
        record("environment", False, "no conda environment active")
        return
    record("environment", True, f"conda env '{env_name}'")


# --------------------------------------------------------------------------
# 2. libxml2 ABI - necessary, proven not sufficient alone
# --------------------------------------------------------------------------
def stage_libxml2_abi() -> None:
    header("STAGE 2: libxml2 ABI (necessary, NOT sufficient alone - see stage 6)")
    try:
        from lxml import etree
    except Exception as exc:
        record("libxml2_abi", False, f"cannot import lxml: {exc}")
        return

    compiled = etree.LIBXML_COMPILED_VERSION
    runtime = etree.LIBXML_VERSION
    log(f"  lxml version              : {etree.__version__}")
    log(f"  LIBXML_COMPILED_VERSION   : {compiled}")
    log(f"  LIBXML_VERSION (runtime)  : {runtime}")

    if compiled == runtime:
        record("libxml2_abi", True, f"MATCH {compiled}")
    else:
        log("")
        log("  Version mismatch - environment.yml's libxml2=2.14 pin may not")
        log("  have taken effect. This alone does not explain the v0.30.20-22")
        log("  crash (that crash reproduced even with matched versions), but")
        log("  it is still a real defect worth fixing on its own.")
        record("libxml2_abi", False, f"MISMATCH compiled={compiled} runtime={runtime}")


# --------------------------------------------------------------------------
# 3. GDAL
# --------------------------------------------------------------------------
def stage_gdal() -> None:
    header("STAGE 3: GDAL")
    try:
        from osgeo import gdal, ogr
    except Exception as exc:
        record("gdal", False, f"cannot import osgeo: {exc}")
        return

    ver = gdal.__version__
    log(f"  GDAL version      : {ver} (pin expects {EXPECTED_GDAL})")

    drv = ogr.GetDriverByName("GPKG")
    log(f"  GPKG driver       : {'available' if drv is not None else 'MISSING'}")
    if drv is None:
        record("gdal", False, "GPKG driver not available")
        return

    record("gdal", ver.startswith(EXPECTED_GDAL), ver)


# --------------------------------------------------------------------------
# 4. MetadataHandler construction
# --------------------------------------------------------------------------
def stage_metadata_ctor() -> None:
    header("STAGE 4: MetadataHandler() construction")
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from core.metadata_handler import MetadataHandler

        handler = MetadataHandler()
        record("metadata_ctor", True, f"constructed {handler!r}"[:90])
    except Exception as exc:
        log("")
        log("  Traceback:")
        for line in traceback.format_exc().splitlines():
            log(f"    {line}")
        record("metadata_ctor", False, f"{type(exc).__name__}: {str(exc)[:100]}")


# --------------------------------------------------------------------------
# 5. schema is never cached (regression guard)
# --------------------------------------------------------------------------
def stage_schema_no_cache() -> None:
    header("STAGE 5: .schema is never cached (regression guard)")
    log("  Confirms two reads of `handler.schema` return DIFFERENT compiled")
    log("  objects. If this ever starts returning the SAME object twice, the")
    log("  v0.30.23 fix has been silently reverted (e.g. by a future 'perf")
    log("  cleanup' that reintroduces caching) - this stage exists to catch")
    log("  that before it ships.")
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from core.metadata_handler import MetadataHandler

        handler = MetadataHandler()
        s1 = handler.schema
        s2 = handler.schema
        if s1 is None:
            record("schema_no_cache", False, "handler.schema is None - no schema file found?")
            return
        distinct = s1 is not s2
        log(f"  id(first access) : {id(s1)}")
        log(f"  id(second access): {id(s2)}")
        record("schema_no_cache", distinct, "distinct objects" if distinct else "SAME OBJECT - caching regressed!")
    except Exception as exc:
        record("schema_no_cache", False, f"{type(exc).__name__}: {str(exc)[:100]}")


# --------------------------------------------------------------------------
# 6. THE decisive check - real batch-conversion-shaped cycle, crash-safe
# --------------------------------------------------------------------------
_BATCH_CYCLE_PROBE = r'''
import sys, tempfile
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from core.metadata_handler import MetadataHandler
from osgeo import ogr, osr

def gdal_write(tag):
    tmp = Path(tempfile.mkdtemp()) / (tag + ".gpkg")
    drv = ogr.GetDriverByName("GPKG")
    ds = drv.CreateDataSource(str(tmp))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    lyr = ds.CreateLayer("pts", srs=srs, geom_type=ogr.wkbPoint)
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetGeometry(ogr.CreateGeometryFromWkt("POINT (1 2)"))
    lyr.CreateFeature(f)
    f = None
    ds = None

# Simulates a batch of 8 conversions in one process: a real GDAL vector
# write, THEN a real generate_package_metadata() + validate_schema() call
# through the actual MetadataHandler class - not a synthetic lxml probe.
# This is exactly the shape diagnose_crash_v0.30.22.py's P9 proved a CACHED
# schema fails at (crashes even when compiled safely after a prior write,
# once a second write happens) and P10 proved a schema compiled fresh every
# time survives. One handler is reused across all 8 cycles, matching how the
# real CLI/GUI reuses one MetadataHandler across a session.
handler = MetadataHandler()
for i in range(8):
    print(f"CYCLE {i}: GDAL write", flush=True)
    gdal_write(f"cycle{i}")
    print(f"CYCLE {i}: generate_package_metadata", flush=True)
    xml = handler.generate_package_metadata(
        title="T", abstract="A", poc="P", org="O", nation="USA",
        security="UNCLASSIFIED", language="eng", topic_category="location",
        ref_date="2026-06-03",
    )
    print(f"CYCLE {i}: validate_schema", flush=True)
    ok = handler.validate_schema(xml)
    assert ok, f"cycle {i}: validate_schema returned False"
    print(f"CYCLE {i}: OK", flush=True)
print("ALL 8 CYCLES OK", flush=True)
'''


def stage_batch_conversion_cycle() -> None:
    header("STAGE 6: 8-cycle real batch conversion (THE decisive check)")
    log("  Real GDAL write + real MetadataHandler.generate_package_metadata()")
    log("  + real .validate_schema(), repeated 8 times with ONE reused handler -")
    log("  the actual shipped code, exercised the way the real tool calls it.")
    log("")
    log("  Run in a SUBPROCESS: if the fix did not work, this crashes the")
    log("  interpreter outright rather than raising a Python exception. A")
    log("  subprocess turns that into a negative/large exit code this parent")
    log("  process can record without losing the log.")

    import tempfile as _tf

    probe = Path(_tf.mkdtemp()) / "batch_cycle_probe.py"
    probe.write_text(_BATCH_CYCLE_PROBE, encoding="utf-8")

    try:
        proc = subprocess.run(
            [sys.executable, str(probe), str(PROJECT_ROOT)],
            capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        record("batch_conversion_cycle", False, "probe timed out after 300s")
        return

    for line in (proc.stdout or "").splitlines():
        log(f"    {line}")
    for line in (proc.stderr or "").splitlines():
        log(f"    [stderr] {line}")
    log(f"  probe exit code: {proc.returncode}")

    if proc.returncode == 0:
        record("batch_conversion_cycle", True, "all 8 cycles completed without crashing")
    elif proc.returncode < 0 or proc.returncode in (0xC0000005, 3221225477):
        record(
            "batch_conversion_cycle", False,
            f"NATIVE CRASH (exit {proc.returncode}) - the v0.30.23 fix did NOT hold",
        )
    else:
        record("batch_conversion_cycle", False, f"probe failed, exit {proc.returncode}")


# --------------------------------------------------------------------------
# 7. version strings
# --------------------------------------------------------------------------
def stage_version_strings() -> None:
    header("STAGE 7: version strings")
    import re

    sources = {
        "core/config.py TOOL_VERSION": (r'TOOL_VERSION = "(\d+\.\d+\.\d+)', "core/config.py"),
        "core/__init__.py __version__": (r'__version__ = "(\d+\.\d+\.\d+)', "core/__init__.py"),
        "packaging/app_main.py": (r'APP_VERSION = "(\d+\.\d+\.\d+)', "packaging/app_main.py"),
        "GUI APP_VERSION": (r'APP_VERSION = "(\d+\.\d+\.\d+)', "geopackage_creator_gui.py"),
        "version_info FileVersion": (r"FileVersion', u'(\d+\.\d+\.\d+)", "packaging/version_info.txt"),
        "README banner": (r"\*\*Version (\d+\.\d+\.\d+)\*\*", "README.md"),
        "metadata_handler.py __version__": (r'__version__ = "(\d+\.\d+\.\d+)', "core/metadata_handler.py"),
    }
    found = []
    for label, (pat, rel) in sources.items():
        path = PROJECT_ROOT / rel
        if not path.exists():
            log(f"  {label:34} FILE MISSING")
            found.append("MISSING")
            continue
        m = re.search(pat, path.read_text(encoding="utf-8", errors="replace"))
        val = m.group(1) if m else "NOT FOUND"
        log(f"  {label:34} {val}")
        found.append(val[:7])

    if len(set(found)) == 1 and found[0] == EXPECTED_VERSION:
        record("version_strings", True, f"all agree at {EXPECTED_VERSION}")
    else:
        record("version_strings", False, f"disagreement: {sorted(set(found))}")


# --------------------------------------------------------------------------
# 8 / 9. pytest
# --------------------------------------------------------------------------
def _run_pytest(stage: str, args: list[str]) -> None:
    header(f"STAGE: {stage}")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *args,
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        str(PYTEST_BASETEMP),
    ]
    log(f"  $ {' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=1800
        )
    except subprocess.TimeoutExpired:
        record(stage, False, "timed out after 30 min")
        return

    out = (proc.stdout or "") + (proc.stderr or "")
    for line in out.splitlines():
        log(f"    {line}")
    tail = [l for l in out.splitlines() if l.strip()][-1:] or ["<no output>"]
    log(f"  last line: {tail[0]}")
    record(stage, proc.returncode == 0, tail[0][:110])


def main() -> int:
    started = datetime.now()
    log_path = _open_log()
    header(f"GeoPackage Creator v{EXPECTED_VERSION} - RELEASE CHECK")
    log(f"  started: {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {log_path}")
    log("  (written incrementally - if this run dies mid-way, the log up to")
    log("   that point is still on disk and is exactly what to send back)")

    stage_environment()
    stage_libxml2_abi()
    stage_gdal()
    stage_metadata_ctor()
    stage_schema_no_cache()
    stage_batch_conversion_cycle()
    stage_version_strings()
    _run_pytest("pytest_main", ["tests/", "--ignore=tests/test_concurrency.py"])
    _run_pytest("pytest_concurrency", ["tests/test_concurrency.py"])

    header("SUMMARY")
    failed = [s for s, ok, _ in _results if not ok]
    for stage, ok, detail in _results:
        log(f"  {'PASS' if ok else 'FAIL'}  {stage:22} {detail}")

    log("")
    if failed:
        verdict = f"DO NOT SHIP - {len(failed)} stage(s) failed: {', '.join(failed)}"
    else:
        verdict = (
            "ALL STAGES PASSED - the schema-lifetime fix holds under a real "
            "8-cycle batch simulation. Still do a real GDB->GPKG conversion + "
            "DGIWG validation on actual customer-shaped data before distributing."
        )
    log(f"VERDICT: {verdict}")
    log(f"  finished in {(datetime.now() - started).total_seconds():.1f}s")

    print()
    print(f"Log written to: {log_path}")
    print("Please send this file back for review.")
    if _LOG_FH is not None:
        _LOG_FH.close()
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        _rc = main()
    except BaseException:
        try:
            log("")
            log("UNCAUGHT EXCEPTION - run aborted:")
            for _line in traceback.format_exc().splitlines():
                log(f"  {_line}")
            log("VERDICT: DO NOT SHIP - release check aborted")
        finally:
            if _LOG_FH is not None and not _LOG_FH.closed:
                _LOG_FH.close()
        raise
    sys.exit(_rc)
