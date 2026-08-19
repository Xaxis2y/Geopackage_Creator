# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.32 - follow-up to v0.30.31.

WHAT v0.30.31 FOUND
--------------------
    CRASH  P41_control_no_patch
    CRASH  P42_schema_parse_default_parser
    CRASH  P43_schema_parse_plain_xmlparser
    CRASH  P44_schema_parse_no_compile

All four crashed. This is a clean NEGATIVE result on the parser theory:
P42 dropped `_build_hardened_parser()` entirely - no explicit parser
argument at all, lxml's implicit default, exactly matching
`diagnose_crash_v0.30.28.py`'s P26 - and it still crashed. P43 (a fresh
but option-less `etree.XMLParser()`) also crashed. So the parser
construction/options are NOT the P26-vs-real explanation after all; that
theory is refuted. P44 adds a real, clean new fact on its own: it never
calls `etree.XMLSchema()` at all - stops right after `etree.parse()` on
the schema file - and still crashes. So the fault does not even need the
schema COMPILE step; parsing the file (which resolves iso19139-gmd.xsd's
real `<xsd:import>`s into gco.xsd and gml.xsd) is already sufficient, with
any parser, hardened or not.

WHAT THIS LEAVES OPEN
-----------------------
Every difference between v0.30.28's hand-rolled P26 (OK) and the real
pipeline (CRASHES) that this series has been able to name is now tested
and eliminated: schema file (same in both since P26 was written), parser
choice (P42/P43), document content (P40), thread B's own GDAL write
(P37), and the `XMLSchema()` compile step itself (P44 - parse alone is
enough). One thing has never actually been isolated, because every probe
in this entire series - including P37, which removed thread B's GDAL but
still let thread A run the full real `convert()` - has kept AT LEAST ONE
thread doing real GDAL work somewhere in the process before the crashing
lxml touch. P26 did too (its `gdal_write()` helper). Nobody has yet asked
whether GDAL needs to be involved AT ALL. The entire "gdal_then_schema"
framing goes back to `diagnose_crash_v0.30.11.py`/`_v0.30.12.py` (see
core/metadata_handler.py's own module docstring, "LIBXML2 ABI FAIL-FAST
GUARD" section) - v0.30.20-23 built on it, this series inherited it - but
that comparison was `heavy_no_lxml` (lxml touched zero times) vs.
`gdal_then_schema` (one GDAL write, then lxml). It never included a third
arm: lxml touched twice, across two threads, with NO GDAL ANYWHERE in the
process. If that arm also crashes, GDAL was never a required ingredient -
only ever a coincidental witness in every probe run so far, this project's
included.

WHAT THIS SCRIPT DECIDES
-------------------------
  P45  Control. No patch at all - rerun of P41/P36/P27, through this
       script's own harness. Expected CRASH. If P45 comes back OK, this
       harness is not faithfully reproducing the crash and P46/P47 cannot
       be trusted either way.

  P46  NEITHER thread touches GDAL, OGR, or `GeoPackageConverter` at all.
       Both threads: construct a real `MetadataHandler`, build one real
       metadata document via real `generate_package_metadata()`, and
       validate it via real `validate_schema()` - nothing else. Same
       strict sequential hand-off (thread A `join()`-ed to completion
       before thread B is even created). Tests whether GDAL is involved
       in this crash AT ALL, or whether two sequential OS threads each
       doing one real schema parse is sufficient by itself.

  P47  The exact same lxml-only work as P46 (build + validate, twice) but
       both turns run in the SAME single thread - no second OS thread is
       ever created. Only meaningful to read once P46's result is known:
       isolates whether the crash needs a genuinely NEW OS thread
       specifically, or whether merely parsing this real schema file
       twice in a process - regardless of threading - is already enough.

  Reading the results:
      P45 OK                  -> this harness is not faithfully
                                  reproducing the crash; stop and compare
                                  it against P41 before trusting P46/P47.
      P45 CRASH, P46 CRASH     -> GDAL is NOT involved. This is a pure
                                  libxml2-across-two-OS-threads defect,
                                  independent of GDAL entirely - every
                                  "GDAL disturbs libxml2" theory since
                                  v0.30.10 was tracking a witness, not a
                                  cause. Proceed to P47 to learn whether
                                  it needs to be a new thread at all.
      P45 CRASH, P46 OK        -> GDAL involvement (at least once, in
                                  SOME thread, per every crash observed so
                                  far) is still a necessary co-ingredient;
                                  pure lxml-only across two threads, no
                                  GDAL anywhere, is safe. P47 is not very
                                  informative in this case.
      P46 CRASH, P47 OK        -> CONFIRMS the crash needs a genuinely new
                                  OS thread specifically - two real schema
                                  parses in the SAME thread are safe, only
                                  a second, different thread's first parse
                                  is not. Combined with a P46 CRASH, this
                                  means the whole hazard is "a new OS
                                  thread's first libxml2 touch, after any
                                  other thread has used libxml2 - GDAL not
                                  required," full stop.
      P46 CRASH, P47 CRASH     -> even single-threaded, two repeated real
                                  schema parses crash. This would
                                  contradict `diagnose_crash_v0.30.22.py`'s
                                  "compiled fresh immediately before every
                                  use, discarded immediately after,
                                  repeated 4x -> fine, every time" finding,
                                  and would need reconciling - most likely
                                  by checking whether that probe ever
                                  parsed the REAL schema file (with its
                                  real cross-file gco/gml imports) or a
                                  simpler stand-in.

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.32.py

Writes dev_tools\\logs\\diagnose_v0.30.32_<timestamp>.log incrementally, so a
hard crash still leaves everything up to that point on disk. Send that file
back either way.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
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
# P45 (control): real convert(), unmodified, through the same harness as
# every P-control before it.
# ---------------------------------------------------------------------------
P45_SCRIPT = r'''
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter


def make_shapefile(tag, tmp_root):
    thread_dir = Path(tmp_root) / f"src_{tag}"
    thread_dir.mkdir(parents=True, exist_ok=True)
    shp_path = thread_dir / "points.shp"
    driver = ogr.GetDriverByName("ESRI Shapefile")
    ds = driver.CreateDataSource(str(thread_dir))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    layer = ds.CreateLayer("points", srs, ogr.wkbPoint)
    layer.CreateField(ogr.FieldDefn("name", ogr.OFTString))
    for i in range(5):
        f = ogr.Feature(layer.GetLayerDefn())
        f.SetField("name", f"Point_{i}")
        f.SetGeometry(ogr.CreateGeometryFromWkt(f"POINT({-120 + i} {40 + i})"))
        layer.CreateFeature(f)
        f = None
    ds = None
    return str(shp_path)


def run_conversion(tag, tmp_root):
    local_shp = make_shapefile(tag, tmp_root)
    out_path = str(Path(tmp_root) / f"out_{tag}.gpkg")
    converter = GeoPackageConverter(profile="military")
    result = converter.convert(
        source_geodatabase=local_shp,
        output_geopackage=out_path,
        title=f"Concurrent Test {tag}",
        abstract="Test concurrent writes",
        poc="Test User",
        org="Test Org",
        nation="USA",
        security="UNCLASSIFIED",
        generate_reports=True,
    )
    if not result.get("success"):
        raise RuntimeError(f"conversion {tag} reported failure: {result.get('error')}")
    return result


tmp_root = tempfile.mkdtemp()
errors = {}

def worker(i):
    try:
        run_conversion(f"P45_{i}", tmp_root)
        print(f"P45: thread {i} completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

print("P45: starting thread A, will wait for it to fully finish...", flush=True)
t_a = threading.Thread(target=worker, args=(0,))
t_a.start()
t_a.join(timeout=60)
if 0 in errors:
    print(f"P45: thread A errors: {errors}", flush=True)
    raise SystemExit(1)

print("P45: thread A finished cleanly. Starting thread B (a genuinely different, "
      "freshly-created OS thread) now...", flush=True)
t_b = threading.Thread(target=worker, args=(1,))
t_b.start()
t_b.join(timeout=60)
if errors:
    print(f"P45: errors: {errors}", flush=True)
    raise SystemExit(1)

print("P45 OK", flush=True)
'''


# ---------------------------------------------------------------------------
# P46: NEITHER thread touches GDAL/OGR/GeoPackageConverter at all - pure
# lxml, two sequential OS threads, strict hand-off.
# ---------------------------------------------------------------------------
P46_SCRIPT = r'''
import sys, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from core.metadata_handler import MetadataHandler


def lxml_only_turn(tag):
    """NO GDAL, NO OGR, NO GeoPackageConverter anywhere in this probe -
    just the real MetadataHandler building one real, full-sized package
    metadata document (pure Python/string work) and validating it via the
    real, unmodified validate_schema(). language/topic_category values
    are taken from converter.py's own module-docstring usage example
    (line 30-31), not guessed - same values used in v0.30.30's P37."""
    handler = MetadataHandler()
    xml_str = handler.generate_package_metadata(
        title=f"Concurrent Test {tag}",
        abstract="Test concurrent writes, lxml-only, no GDAL anywhere",
        poc="Test User",
        org="Test Org",
        nation="USA",
        security="UNCLASSIFIED",
        language="eng",
        topic_category="transportation",
        ref_date="2026-08-14",
    )
    handler.validate_schema(xml_str)


errors = {}

def worker(i):
    try:
        lxml_only_turn(f"P46_{i}")
        print(f"P46: thread {i} (lxml-only, no GDAL anywhere) completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

print("P46: starting thread A (lxml-only, no GDAL), will wait for it to fully finish...", flush=True)
t_a = threading.Thread(target=worker, args=(0,))
t_a.start()
t_a.join(timeout=60)
if 0 in errors:
    print(f"P46: thread A errors: {errors}", flush=True)
    raise SystemExit(1)

print("P46: thread A finished cleanly. Starting thread B (a genuinely different, "
      "freshly-created OS thread, lxml-only - no GDAL anywhere in this whole "
      "probe) now...", flush=True)
t_b = threading.Thread(target=worker, args=(1,))
t_b.start()
t_b.join(timeout=60)
if errors:
    print(f"P46: errors: {errors}", flush=True)
    raise SystemExit(1)

print("P46 OK", flush=True)
'''


# ---------------------------------------------------------------------------
# P47: identical lxml-only work to P46, but both turns run in the SAME
# thread - no second OS thread is ever created. No `threading` import at
# all, deliberately, so there is no ambiguity about whether a new thread
# was involved.
# ---------------------------------------------------------------------------
P47_SCRIPT = r'''
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from core.metadata_handler import MetadataHandler


def lxml_only_turn(tag):
    handler = MetadataHandler()
    xml_str = handler.generate_package_metadata(
        title=f"Concurrent Test {tag}",
        abstract="Test concurrent writes, single-thread repeated parse",
        poc="Test User",
        org="Test Org",
        nation="USA",
        security="UNCLASSIFIED",
        language="eng",
        topic_category="transportation",
        ref_date="2026-08-14",
    )
    handler.validate_schema(xml_str)


print("P47: turn 0, main thread (no second OS thread will ever be created "
      "in this probe)...", flush=True)
lxml_only_turn("P47_0")
print("P47: turn 0 completed its FULL turn", flush=True)

print("P47: turn 1, the SAME thread as turn 0 - the only thing repeated is "
      "the real schema parse+validate, nothing about threading...", flush=True)
lxml_only_turn("P47_1")
print("P47: turn 1 completed its FULL turn", flush=True)

print("P47 OK", flush=True)
'''


PROBES: list[tuple[str, str, str]] = [
    (
        "P45_control_no_patch",
        "Control: the real, complete convert() (all internal steps run for "
        "real), through this script's own harness. Expected CRASH, matching "
        "P41/P36/P27/P17-19 - confirms this harness before trusting P46/P47.",
        P45_SCRIPT,
    ),
    (
        "P46_lxml_only_both_threads_no_gdal",
        "NEITHER thread touches GDAL/OGR/GeoPackageConverter at all - both "
        "threads only build a real metadata document and validate it. Tests "
        "whether GDAL is involved in this crash AT ALL, or two sequential "
        "OS threads each doing one real schema parse is sufficient alone.",
        P46_SCRIPT,
    ),
    (
        "P47_lxml_only_single_thread_repeated",
        "The exact same lxml-only work as P46 (build+validate, twice) but "
        "both turns run in the SAME thread - no second OS thread is ever "
        "created. Only meaningful once P46's result is known: isolates "
        "whether a genuinely new OS thread is required, or two real parses "
        "anywhere in the process is already enough.",
        P47_SCRIPT,
    ),
]


def run_probe(name: str, desc: str, code: str) -> bool:
    header(name)
    log(f"  {desc}")

    f = Path(tempfile.mkdtemp()) / f"{name}.py"
    f.write_text(code, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(f), str(PROJECT_ROOT)],
            capture_output=True, text=True, timeout=180,
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
    path = LOG_DIR / f"diagnose_v0.30.32_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS FOLLOW-UP (v0.30.32)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.31 refuted the parser theory (P42/P43 CRASH even with no")
    log("  custom parser, matching P26 exactly) and showed the fault does not")
    log("  even need the XMLSchema() compile call (P44 CRASH - parsing the")
    log("  schema file alone is enough). Every named difference between P26")
    log("  and the real pipeline is now eliminated except one nobody has")
    log("  actually tested: whether GDAL needs to be involved AT ALL. Every")
    log("  probe so far, including this project's original v0.30.11/12")
    log("  'gdal_then_schema' finding, has kept at least one thread doing real")
    log("  GDAL work somewhere before the crash. This run removes GDAL from")
    log("  the picture entirely.")

    results = {}
    for name, desc, code in PROBES:
        results[name] = run_probe(name, desc, code)

    header("SUMMARY")
    for name, ok in results.items():
        log(f"  {'OK   ' if ok else 'CRASH'}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P45 OK                  -> this harness is not faithfully")
    log("                             reproducing the crash - compare")
    log("                             against P41 before trusting P46/P47.")
    log("  P45 CRASH, P46 CRASH     -> GDAL is NOT involved. Pure libxml2-")
    log("                             across-two-OS-threads defect,")
    log("                             independent of GDAL entirely.")
    log("  P45 CRASH, P46 OK        -> GDAL involvement (at least once,")
    log("                             somewhere) is still necessary; pure")
    log("                             lxml-only across two threads is safe.")
    log("  P46 CRASH, P47 OK        -> confirms a genuinely NEW OS thread is")
    log("                             required - two real parses in the SAME")
    log("                             thread are safe.")
    log("  P46 CRASH, P47 CRASH     -> even single-threaded, two repeated")
    log("                             real schema parses crash - contradicts")
    log("                             v0.30.22's repeated-compile finding and")
    log("                             needs reconciling.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
