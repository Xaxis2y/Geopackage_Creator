# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Release check for GeoPackage Creator v0.30.20.

PURPOSE
-------
v0.30.20 pins `libxml2=2.14` in environment.yml, which is claimed to be the
root-cause fix for the libxml2/GDAL ABI mismatch that has blocked every
conversion since v0.30.13. That claim has NOT been verified on a real
Windows/Anaconda machine. This script verifies it, and everything downstream
of it, writing a detailed log for review.

It deliberately does NOT recreate the conda environment itself - destroying an
environment is the user's call. Run the recreate first (see USAGE), then this.

USAGE (Anaconda Prompt - NEVER the base environment)
----------------------------------------------------
    conda deactivate
    conda env remove -n geopackage
    conda env create -f environment.yml
    conda activate geopackage
    python dev_tools\\run_release_check_v0.30.20.py

Writes: dev_tools\\logs\\release_check_v0.30.20_<timestamp>.log
Prints a single VERDICT line at the end.

STAGES
------
  1. environment      - Python/platform, conda env name
  2. libxml2_abi      - THE headline check: compiled vs runtime libxml2
  3. gdal             - version, GPKG driver, pin agreement
  4. metadata_ctor    - MetadataHandler() construction (blocked pre-0.30.20)
  5. gdal_lxml_interop- the exact XSD-compile -> GDAL-write -> lxml sequence
                        that produced the 5/5 access violation in v0.30.12
  6. version_strings  - all version sources agree at 0.30.20
  7. pytest_main      - the main suite
  8. pytest_concurrency - the concurrency suite
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
EXPECTED_VERSION = "0.30.20"
EXPECTED_GDAL = "3.13.2"

_results: list[tuple[str, bool, str]] = []
_log_lines: list[str] = []

# v0.30.20a: the log file is opened at STARTUP and every line is flushed as it
# is written. The first version of this script buffered everything in memory
# and wrote the file as its last statement - which meant that if stage 5 (the
# GDAL/lxml interop probe) hard-crashed the process with a Windows access
# violation, the run produced NO log at all. That is the single most important
# outcome to capture, so it must survive the process dying abruptly.
_LOG_FH = None


def _open_log():
    global _LOG_FH
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"release_check_v{EXPECTED_VERSION}_{datetime.now():%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)
    return path


def log(msg: str = "") -> None:
    print(msg, flush=True)
    _log_lines.append(msg)
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
        record(
            "environment", False,
            "running in BASE environment - activate 'geopackage' instead",
        )
        return
    if not env_name:
        record("environment", False, "no conda environment active")
        return
    record("environment", True, f"conda env '{env_name}'")


# --------------------------------------------------------------------------
# 2. libxml2 ABI - the headline check
# --------------------------------------------------------------------------
def stage_libxml2_abi() -> None:
    header("STAGE 2: libxml2 ABI (THE v0.30.20 FIX)")
    try:
        from lxml import etree
    except Exception as exc:  # pragma: no cover
        record("libxml2_abi", False, f"cannot import lxml: {exc}")
        return

    compiled = etree.LIBXML_COMPILED_VERSION
    runtime = etree.LIBXML_VERSION
    log(f"  lxml version              : {etree.__version__}")
    log(f"  LIBXML_COMPILED_VERSION   : {compiled}   <- what this lxml expects")
    log(f"  LIBXML_VERSION (runtime)  : {runtime}   <- the libxml2 actually loaded")

    if compiled == runtime:
        record("libxml2_abi", True, f"MATCH {compiled} - blocker is CLOSED")
    else:
        log("")
        log("  The libxml2=2.14 pin did NOT resolve the mismatch.")
        log("  Check that environment.yml really was used to create this env,")
        log("  and report these two tuples - if conda-forge's global pin has")
        log("  moved to 2.15, environment.yml's pin must move with it.")
        record(
            "libxml2_abi", False,
            f"MISMATCH compiled={compiled} runtime={runtime}",
        )


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

    # Which binding generation is this? Decides the v0.30.20 hardening relevance.
    import os as _os
    import tempfile

    tmp = Path(tempfile.mkdtemp()) / "abi_probe.gpkg"
    ds = drv.CreateDataSource(str(tmp))
    kind = type(ds).__name__
    truthy = bool(ds)
    log(f"  CreateDataSource -> {kind}, bool()={truthy}, layers={ds.GetLayerCount()}")
    if not truthy:
        log("    NOTE: this binding returns a falsy empty dataset - the exact")
        log("    trap v0.30.20 hardened against (`if not ds` misfires).")
    ds = None
    try:
        _os.unlink(tmp)
    except OSError:
        pass

    if not ver.startswith(EXPECTED_GDAL):
        record("gdal", True, f"OK but version {ver} != pinned {EXPECTED_GDAL}")
        return
    record("gdal", True, f"{ver}, GPKG driver present")


# --------------------------------------------------------------------------
# 4. MetadataHandler construction
# --------------------------------------------------------------------------
def stage_metadata_ctor() -> None:
    header("STAGE 4: MetadataHandler() construction")
    log("  (blocked by the ABI guard in every release since v0.30.13)")
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
# 5. the crash sequence itself
# --------------------------------------------------------------------------
_INTEROP_PROBE = r'''
import sys, tempfile, os
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from lxml import etree
from osgeo import ogr, osr

print("PROBE: compiling XSD via lxml", flush=True)
etree.XMLSchema(etree.parse(str(root / "schemas" / "iso19139-gmd.xsd")))

tmp = Path(tempfile.mkdtemp()) / "interop.gpkg"
print("PROBE: real GDAL vector write", flush=True)
drv = ogr.GetDriverByName("GPKG")
ds = drv.CreateDataSource(str(tmp))
srs = osr.SpatialReference()
srs.ImportFromEPSG(4326)
layer = ds.CreateLayer("pts", srs=srs, geom_type=ogr.wkbPoint)
feat = ogr.Feature(layer.GetLayerDefn())
feat.SetGeometry(ogr.CreateGeometryFromWkt("POINT (1 2)"))
layer.CreateFeature(feat)
feat = None
ds = None

print("PROBE: further lxml call (this is where it used to fault)", flush=True)
etree.fromstring(b"<probe><ok/></probe>")
try:
    os.unlink(tmp)
except OSError:
    pass
print("PROBE: OK", flush=True)
'''


def stage_gdal_lxml_interop() -> None:
    header("STAGE 5: XSD-compile -> GDAL-write -> lxml (the v0.30.12 crash path)")
    log("  This is the exact sequence that produced a Windows access violation")
    log("  5 times out of 5 under a mismatched libxml2.")
    log("")
    log("  Run in a SUBPROCESS on purpose: under a live ABI mismatch this does")
    log("  not raise a Python exception, it kills the interpreter outright. In")
    log("  a subprocess that shows up as a negative/large exit code which this")
    log("  parent process can record, instead of taking the whole check down")
    log("  and losing the log.")

    import tempfile as _tf

    probe = Path(_tf.mkdtemp()) / "interop_probe.py"
    probe.write_text(_INTEROP_PROBE, encoding="utf-8")

    try:
        proc = subprocess.run(
            [sys.executable, str(probe), str(PROJECT_ROOT)],
            capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        record("gdal_lxml_interop", False, "probe timed out after 300s")
        return

    for line in (proc.stdout or "").splitlines():
        log(f"    {line}")
    for line in (proc.stderr or "").splitlines():
        log(f"    [stderr] {line}")
    log(f"  probe exit code: {proc.returncode}")

    if proc.returncode == 0:
        record("gdal_lxml_interop", True, "completed without crashing")
    elif proc.returncode < 0 or proc.returncode in (0xC0000005, 3221225477):
        record(
            "gdal_lxml_interop", False,
            f"NATIVE CRASH (exit {proc.returncode}) - ABI mismatch still live",
        )
    else:
        record("gdal_lxml_interop", False, f"probe failed, exit {proc.returncode}")


# --------------------------------------------------------------------------
# 6. version strings
# --------------------------------------------------------------------------
def stage_version_strings() -> None:
    header("STAGE 6: version strings")
    import re

    sources = {
        "core/config.py TOOL_VERSION": (r'TOOL_VERSION = "([\d.]+)"', "core/config.py"),
        "core/__init__.py __version__": (r'__version__ = "([\d.]+)"', "core/__init__.py"),
        "packaging/app_main.py": (r'APP_VERSION = "([\d.]+)"', "packaging/app_main.py"),
        "GUI APP_VERSION": (r'APP_VERSION = "([\d.]+)"', "geopackage_creator_gui.py"),
        "version_info FileVersion": (r"FileVersion', u'([\d.]+)'", "packaging/version_info.txt"),
        "README banner": (r"\*\*Version ([\d.]+)\*\*", "README.md"),
    }
    found = []
    for label, (pat, rel) in sources.items():
        path = PROJECT_ROOT / rel
        if not path.exists():
            log(f"  {label:30} FILE MISSING")
            found.append("MISSING")
            continue
        m = re.search(pat, path.read_text(encoding="utf-8", errors="replace"))
        val = m.group(1) if m else "NOT FOUND"
        log(f"  {label:30} {val}")
        found.append(val[:7])

    if len(set(found)) == 1 and found[0] == EXPECTED_VERSION:
        record("version_strings", True, f"all agree at {EXPECTED_VERSION}")
    else:
        record("version_strings", False, f"disagreement: {sorted(set(found))}")


# --------------------------------------------------------------------------
# 7 / 8. pytest
# --------------------------------------------------------------------------
def _run_pytest(stage: str, args: list[str]) -> None:
    header(f"STAGE: {stage}")
    cmd = [sys.executable, "-m", "pytest", *args, "-q", "--no-header", "-p", "no:cacheprovider"]
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
    stage_gdal_lxml_interop()
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
            "ALL STAGES PASSED - the libxml2 blocker is closed. Still do a real "
            "GDB->GPKG conversion + DGIWG validation before distributing."
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
        # Any uncaught failure still gets recorded, since the log handle is
        # already open and flushed line-by-line.
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
