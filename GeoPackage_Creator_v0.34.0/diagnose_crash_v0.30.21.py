# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.21.

WHY THIS EXISTS
---------------
v0.30.20 pinned `libxml2=2.14` on the theory that the crash was caused by an
lxml/libxml2 ABI VERSION mismatch. The 2026-08-14 release-check run proved
that theory WRONG:

    LIBXML_COMPILED_VERSION : (2, 14, 6)
    LIBXML_VERSION          : (2, 14, 6)   <- now MATCHED
    ... and the access violation still happened, in the same place.

So version agreement was necessary but not sufficient. The remaining
candidates are structural, not numeric. This script tests them one at a time,
each in its OWN subprocess, so a crash identifies exactly which step is fatal
instead of taking the whole run down.

The leading hypothesis is TWO SEPARATE libxml2 DLLs mapped into one process
(one bundled next to lxml, one next to GDAL). Two copies of the SAME version
still keep independent global state - interned string dictionaries, the error
handler table, the global parser context. A document allocated by one copy and
then handed to a schema owned by the other dereferences a pointer that is
meaningless in the other copy's heap: an access violation whose version tuples
look perfectly healthy.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
---------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.21.py

Writes dev_tools\\logs\\diagnose_v0.30.21_<timestamp>.log incrementally, so a
hard crash still leaves everything up to that point on disk. Send that file
back.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path(__file__).resolve().parent / "logs"

_LOG_FH = None


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


# ---------------------------------------------------------------------------
# PROBE 0 - inventory: how many libxml2 images are mapped, and from where?
# ---------------------------------------------------------------------------
PROBE_INVENTORY = r'''
import sys, os
print("python :", sys.version.split()[0])

from lxml import etree
print("lxml   :", etree.__version__)
print("  LIBXML_COMPILED_VERSION:", etree.LIBXML_COMPILED_VERSION)
print("  LIBXML_VERSION         :", etree.LIBXML_VERSION)

from osgeo import gdal
print("gdal   :", gdal.__version__)

print()
print("--- every libxml2 image mapped into THIS process ---")
try:
    import psutil
    p = psutil.Process()
    seen = [m.path for m in p.memory_maps() if "xml2" in os.path.basename(m.path).lower()]
    if seen:
        for s in sorted(set(seen)):
            print("   ", s)
        print("   DISTINCT libxml2 IMAGES:", len(set(seen)))
    else:
        print("    (none reported)")
except ImportError:
    print("    (psutil not installed - using the OS module list instead)")
    if sys.platform != "win32":
        # Linux/macOS: read the memory map directly.
        try:
            with open("/proc/self/maps") as fh:
                paths = set()
                for line in fh:
                    parts = line.split()
                    if len(parts) >= 6 and "xml2" in os.path.basename(parts[-1]).lower():
                        paths.add(parts[-1])
            for p_ in sorted(paths):
                print("   ", p_)
            print("   DISTINCT libxml2 IMAGES:", len(paths))
        except OSError as exc:
            print("    could not read /proc/self/maps:", exc)
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.GetCurrentProcess()
        arr = (wintypes.HMODULE * 2048)()
        need = wintypes.DWORD()
        if psapi.EnumProcessModules(h, arr, ctypes.sizeof(arr), ctypes.byref(need)):
            n = need.value // ctypes.sizeof(wintypes.HMODULE)
            buf = ctypes.create_unicode_buffer(1024)
            found = []
            for i in range(n):
                if psapi.GetModuleFileNameExW(h, arr[i], buf, 1024):
                    if "xml2" in os.path.basename(buf.value).lower():
                        found.append(buf.value)
            for f in sorted(set(found)):
                print("   ", f)
            print("   DISTINCT libxml2 IMAGES:", len(set(found)))
'''

# ---------------------------------------------------------------------------
# The incremental probes. Each is a separate process.
# ---------------------------------------------------------------------------
PREAMBLE = r'''
import sys, tempfile, os
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
XSD = root / "schemas" / "iso19139-gmd.xsd"

def gdal_write(tag="w"):
    from osgeo import ogr, osr
    tmp = Path(tempfile.mkdtemp()) / (tag + ".gpkg")
    drv = ogr.GetDriverByName("GPKG")
    ds = drv.CreateDataSource(str(tmp))
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    lyr = ds.CreateLayer("pts", srs=srs, geom_type=ogr.wkbPoint)
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetGeometry(ogr.CreateGeometryFromWkt("POINT (1 2)"))
    lyr.CreateFeature(f)
    f = None; ds = None
    return tmp
'''

PROBES: list[tuple[str, str, str]] = [
    (
        "P1_lxml_only",
        "lxml alone: compile XSD + validate. GDAL never imported.",
        PREAMBLE + r'''
from lxml import etree
schema = etree.XMLSchema(etree.parse(str(XSD)))
schema.validate(etree.fromstring(b"<x/>"))
print("P1 OK", flush=True)
''',
    ),
    (
        "P2_gdal_only",
        "GDAL alone: a real vector write. lxml never imported.",
        PREAMBLE + r'''
gdal_write("p2")
print("P2 OK", flush=True)
''',
    ),
    (
        "P3_import_both_no_work",
        "Import BOTH modules, do nothing else. Does mere co-loading crash?",
        PREAMBLE + r'''
from lxml import etree
from osgeo import ogr, osr
print("P3 OK", flush=True)
''',
    ),
    (
        "P4_write_then_compile_then_validate",
        "GDAL write FIRST, then compile schema, then validate.",
        PREAMBLE + r'''
gdal_write("p4")
from lxml import etree
schema = etree.XMLSchema(etree.parse(str(XSD)))
schema.validate(etree.fromstring(b"<x/>"))
print("P4 OK", flush=True)
''',
    ),
    (
        "P5_compile_then_write_then_parse",
        "Compile schema, GDAL write, then only a PARSE (no validate).",
        PREAMBLE + r'''
from lxml import etree
schema = etree.XMLSchema(etree.parse(str(XSD)))
gdal_write("p5")
etree.fromstring(b"<x/>")
print("P5 OK", flush=True)
''',
    ),
    (
        "P6_compile_then_write_then_VALIDATE",
        "THE TOOL'S ACTUAL SEQUENCE: compile schema, GDAL write, then "
        "schema.validate() - metadata_handler.py:526.",
        PREAMBLE + r'''
from lxml import etree
schema = etree.XMLSchema(etree.parse(str(XSD)))
gdal_write("p6")
schema.validate(etree.fromstring(b"<x/>"))
print("P6 OK", flush=True)
''',
    ),
    (
        "P7_recompile_after_write",
        "Compile, GDAL write, then RE-COMPILE a fresh schema and validate. "
        "If P6 dies but P7 lives, the schema object simply cannot outlive a "
        "GDAL write - which is a fixable ordering bug.",
        PREAMBLE + r'''
from lxml import etree
etree.XMLSchema(etree.parse(str(XSD)))
gdal_write("p7")
schema2 = etree.XMLSchema(etree.parse(str(XSD)))
schema2.validate(etree.fromstring(b"<x/>"))
print("P7 OK", flush=True)
''',
    ),
    (
        "P8_gdal_dontusexml",
        "Same as P6 but with GDAL's own XML/XSD machinery disabled via "
        "CPLSetConfigOption, to see if GDAL's libxml2 use is the trigger.",
        PREAMBLE + r'''
from osgeo import gdal
gdal.SetConfigOption("GDAL_HTTP_UNSAFESSL", "YES")
gdal.SetConfigOption("CPL_DEBUG", "OFF")
from lxml import etree
schema = etree.XMLSchema(etree.parse(str(XSD)))
gdal_write("p8")
schema.validate(etree.fromstring(b"<x/>"))
print("P8 OK", flush=True)
''',
    ),
]


def run_probe(name: str, desc: str, code: str) -> bool:
    header(f"{name}")
    log(f"  {desc}")
    import tempfile

    f = Path(tempfile.mkdtemp()) / f"{name}.py"
    f.write_text(code, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(f), str(PROJECT_ROOT)],
            capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        log("  RESULT: TIMEOUT")
        return False

    for line in (proc.stdout or "").splitlines():
        log(f"    {line}")
    for line in (proc.stderr or "").splitlines():
        if "FutureWarning" in line or "warnings.warn" in line:
            continue
        log(f"    [stderr] {line}")

    rc = proc.returncode
    crashed = rc != 0
    tag = "CRASH" if rc in (3221225477, -11, -1073741819) else ("FAIL" if crashed else "OK")
    log(f"  exit code: {rc}   -> {tag}")
    return not crashed


def main() -> int:
    started = datetime.now()
    global _LOG_FH
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"diagnose_v0.30.21_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS (post v0.30.20)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.20's libxml2=2.14 pin MATCHED the version tuples and the")
    log("  crash still occurred. This run isolates what else it could be.")

    header("PROBE 0: libxml2 image inventory")
    log("  How many DISTINCT libxml2 binaries are mapped into one process?")
    log("  Two copies of the same VERSION still have separate global state.")
    import tempfile

    f = Path(tempfile.mkdtemp()) / "inventory.py"
    f.write_text(PROBE_INVENTORY, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(f)], capture_output=True, text=True, timeout=300)
    for line in ((proc.stdout or "") + (proc.stderr or "")).splitlines():
        if "FutureWarning" in line or "warnings.warn" in line:
            continue
        log(f"    {line}")

    results = {}
    for name, desc, code in PROBES:
        results[name] = run_probe(name, desc, code)

    header("SUMMARY")
    for name, ok in results.items():
        log(f"  {'OK   ' if ok else 'CRASH'}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P1 ok, P2 ok, P6 crash  -> the two libraries are individually fine;")
    log("                             the interaction is fatal.")
    log("  P5 ok  but P6 crash     -> only schema.VALIDATE is fatal after a")
    log("                             GDAL write, not lxml generally.")
    log("  P6 crash but P7 ok      -> a compiled schema cannot survive a GDAL")
    log("                             write. FIXABLE: recompile the XSD after")
    log("                             conversion, or validate before writing.")
    log("  P4 ok  but P6 crash     -> ordering matters; compile the schema")
    log("                             AFTER GDAL work instead of before.")
    log("  P3 crash                -> merely co-loading is fatal; the two")
    log("                             builds cannot share a process at all.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
