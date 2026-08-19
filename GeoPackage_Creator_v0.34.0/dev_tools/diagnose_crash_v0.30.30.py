# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.30 - follow-up to v0.30.29.

WHAT v0.30.29 FOUND
--------------------
    CRASH  P27_control_no_patch
    CRASH  P28_skip_embed_metadata
    CRASH  P29_skip_finalize_dgiwg_compliance
    OK     P30_skip_schema_validation
    CRASH  P31_skip_embed_and_finalize

P30 is the first clean result in the ENTIRE series (P13 onward) that came
from bisecting the real, unmodified `convert()` rather than a hand-rolled
approximation of it. Removing `MetadataHandler.validate_schema` - and only
that - from the real pipeline stops the crash. Neither sqlite3 reopen
(`_embed_metadata`, `_finalize_dgiwg_compliance`), alone or together,
matters: P28/P29/P31 all still crash. `validate_schema` (i.e. real lxml
schema-validation activity, at its real per-conversion multiplicity of
three calls) is now a confirmed necessary ingredient, established the way
this series always intended to establish things - by removing one real
piece of shipped code at a time, not by building a smaller program that
merely resembles it.

OPEN QUESTIONS THIS LEAVES
----------------------------
Two things about P30's result do not fit the project's own prior "SCHEMA
LIFETIME VS GDAL WRITES" theory (see core/metadata_handler.py's module
docstring, v0.30.20-23) cleanly, and this script exists to chase both.

1. v0.30.23 already made every call to `validate_schema` compile a brand
   new schema, use it once, and let it go out of scope before returning -
   "compile fresh immediately before every use, discarded immediately
   after" - which `diagnose_crash_v0.30.22.py` proved safe across repeated
   write/validate cycles IN ONE THREAD. P27-P31 run exactly that same
   "shipped, already-fixed" code, and it still crashes - but only across a
   SEQUENTIAL THREAD HAND-OFF (thread A completes and is join()-ed, THEN a
   brand-new OS thread B starts). Nothing in the v0.30.20-23 diagnostics
   ever tested a genuinely different OS thread; every probe in that round
   ran everything on one thread. It is an open question whether this is
   really the same "schema outliving a write" hazard reappearing across a
   thread boundary, or a DIFFERENT hazard entirely - libxml2 keeps
   per-thread global state (`xmlGetGlobalState`), and on Windows a
   dynamically-loaded DLL's thread-local storage is not always initialized
   the same way for OS threads created after the DLL was already loaded as
   it is for the thread that first loaded it. If that is what is actually
   happening here, the necessary ingredient is "a new OS thread's first-
   ever libxml2 touch," full stop - with or without that same thread doing
   a GDAL write of its own first. No probe in this series has isolated
   that yet. P37 does.

2. `diagnose_crash_v0.30.28.py`'s P26 - real schema FILE
   (schemas/iso19139-gmd.xsd), sequential hand-off, three compile+validate
   calls per thread's turn (matching the real pipeline's own count) - came
   back OK. The one thing P26 did NOT match was WHAT it validated: three
   calls to `schema.validate(etree.fromstring(b"<x/>"))`, a single empty
   element, every time. `generate_package_metadata()` /
   `generate_layer_metadata()` build genuine multi-hundred-line, deeply
   namespaced ISO 19139/DGIWG documents (dataQualityInfo, security
   constraints, classification codes, and so on) and validate THOSE. P26
   never varied document content/size as a dimension at all. P40 does.

WHAT THIS SCRIPT DECIDES
-------------------------
Same discipline as v0.30.29: every probe runs the real, unmodified
`GeoPackageConverter.convert()` (`generate_reports=True`, profile
"military", strict sequential hand-off - thread A `join()`-ed to
completion before thread B is even created), and changes exactly one
thing via monkey-patching real methods, never a hand-rolled stand-in.

  P36  Control. No patch at all - rerun of P27 through this script's own
       harness (written fresh, not reusing P27's code verbatim). Expected
       CRASH. If P36 comes back OK, this harness is not faithfully
       reproducing the crash and P37-P40 cannot be trusted either way.

  P37  Thread A: the real, complete `convert()`, unmodified - identical to
       every prior control. Thread B does NOT call `convert()` and never
       touches GDAL at all: it only builds one real, full-sized package
       metadata document via the real `MetadataHandler.generate_package_
       metadata()` (pure Python/string work) and then calls the real,
       unmodified `validate_schema()` on it. Tests whether thread B's OWN
       GDAL write is a necessary co-ingredient, or whether ANY brand-new OS
       thread's first real lxml touch - after some OTHER thread has already
       used GDAL+lxml earlier in the process - is sufficient by itself.

  P38  `validate_schema` patched so it still does the real, fresh
       `self.schema` compile (real file, real cross-file gco/gml imports,
       real per-conversion multiplicity of three, under the real
       `_LXML_LOCK`) but returns immediately afterward - the compiled
       schema is discarded without ever parsing or validating any
       document. Tests whether schema COMPILATION alone, in the real
       pipeline's real timing/location/thread, is already sufficient.

  P39  `validate_schema` patched to do the real schema compile AND the
       real `etree.fromstring()` parse of the real metadata document, but
       returns immediately before calling `schema.validate(doc)`. Only
       meaningful to read if P38 is OK: isolates whether having a compiled
       schema and a parsed document alive together is enough, or whether
       the `.validate()` tree-walk call itself is the load-bearing step.

  P40  `validate_schema` patched to run 100% real (real compile, real
       parse, real `.validate()`, real error_log read) but the document it
       validates is swapped for a trivial `<x/>` in place of whatever real
       metadata string the caller passed - reproducing P26's one
       untested variable (real document content) inside the real
       pipeline's real call sites, real timing, and real threading for the
       first time.

  Reading the results:
      P36 OK                     -> this harness itself is not faithfully
                                     reproducing the crash; stop and compare
                                     it against P27 line by line before
                                     trusting P37-P40 either way.
      P36 CRASH, P37 CRASH        -> thread B's own GDAL write is NOT
                                     necessary. A brand-new OS thread's
                                     first-ever real lxml touch alone, with
                                     no GDAL call in that thread at all, is
                                     sufficient. Points squarely at
                                     libxml2/Windows thread-local-state
                                     initialization across OS threads, not
                                     at anything GDAL does. The right next
                                     step becomes finding a way to touch
                                     libxml2 once per new thread outside the
                                     hot path (a cheap warm-up call) or
                                     routing ALL lxml work through one
                                     dedicated long-lived thread process-
                                     wide, not further bisecting `convert()`.
      P36 CRASH, P37 OK           -> thread B's own GDAL write IS a
                                     necessary co-ingredient; "any new
                                     thread touching lxml" alone is not
                                     enough. Stays inside the existing
                                     GDAL+lxml interaction framing, now
                                     confirmed specifically cross-thread.
      P38 CRASH                   -> schema compilation alone (never even
                                     reaching a `.validate()` call) is
                                     already sufficient. Narrows the fault
                                     into `_compile_schema_fresh()` /
                                     `etree.XMLSchema()` itself.
      P38 OK, P39 CRASH           -> merely holding a compiled schema and a
                                     parsed document alive together is
                                     sufficient; the `.validate()` call
                                     itself is not required to trigger it.
      P38 OK, P39 OK              -> the `.validate()` tree-walk call
                                     itself is the necessary step, not
                                     compiling or parsing alone.
      P40 OK (while P36 crashes)  -> confirms real document content/size is
                                     the necessary ingredient - explains
                                     exactly why P26's hand-rolled `<x/>`
                                     reproduction was clean. The fix
                                     direction becomes something document-
                                     shaped (size, depth, or a specific
                                     construct in the generated XML), not
                                     purely a compile/thread/lifetime issue.
      P40 CRASH                   -> document content does not matter;
                                     P26 differed from the real pipeline for
                                     some other reason (most likely
                                     whatever P37 finds).

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.30.py

Writes dev_tools\\logs\\diagnose_v0.30.30_<timestamp>.log incrementally, so a
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
# Shared preamble for the symmetric probes (P36, P38, P39, P40): real project
# code only, plus one monkey-patch hook applied ONCE at module level (main
# thread), before any worker thread is created - matching every earlier
# probe's import-order discipline. `PATCH_STAGE` is substituted per-probe;
# "none" applies no patch (the P36 control).
# ---------------------------------------------------------------------------
REAL_CONVERT_PREAMBLE = r'''
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
import core.converter as _conv_mod
import core.metadata_handler as _mh_mod
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler
from lxml import etree

PATCH_STAGE = "{patch_stage}"

_ORIG_VALIDATE_SCHEMA = MetadataHandler.validate_schema

def _compile_only_validate_schema(self, metadata_xml_string):
    # Real fresh compile - real schema file, real cross-file gco/gml
    # imports, real per-conversion multiplicity, real lock - discarded
    # immediately without ever parsing or validating any document.
    with _mh_mod._LXML_LOCK:
        schema = self.schema  # real _compile_schema_fresh()
        del schema
    return True

def _compile_parse_no_validate_call_schema(self, metadata_xml_string):
    # Real compile AND real etree.fromstring() of the real document, but
    # deliberately never calls schema.validate(doc).
    try:
        xml_bytes = metadata_xml_string.encode("utf-8")
    except (AttributeError, UnicodeEncodeError) as e:
        raise ValueError(f"Invalid XML input: {{e}}")
    with _mh_mod._LXML_LOCK:
        schema = self.schema
        if not schema:
            return True
        doc = etree.fromstring(xml_bytes, _mh_mod._build_hardened_parser())
        del doc, schema
    return True

def _trivial_doc_validate_schema(self, metadata_xml_string):
    # 100% real validate_schema() - real compile, real parse, real
    # .validate(), real error_log read - only the document being validated
    # is swapped for a trivial one, matching P26's hand-rolled ingredient
    # but inside the real pipeline's real call sites/timing/threading.
    return _ORIG_VALIDATE_SCHEMA(self, "<x/>")

if PATCH_STAGE == "none":
    pass
elif PATCH_STAGE == "compile_only":
    MetadataHandler.validate_schema = _compile_only_validate_schema
elif PATCH_STAGE == "compile_parse_no_validate_call":
    MetadataHandler.validate_schema = _compile_parse_no_validate_call_schema
elif PATCH_STAGE == "trivial_doc":
    MetadataHandler.validate_schema = _trivial_doc_validate_schema
else:
    raise ValueError(f"unknown PATCH_STAGE: {{PATCH_STAGE}}")


def make_shapefile(tag, tmp_root):
    thread_dir = Path(tmp_root) / f"src_{{tag}}"
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
        f.SetField("name", f"Point_{{i}}")
        f.SetGeometry(ogr.CreateGeometryFromWkt(f"POINT({{-120 + i}} {{40 + i}})"))
        layer.CreateFeature(f)
        f = None
    ds = None
    return str(shp_path)


def run_conversion(tag, tmp_root):
    local_shp = make_shapefile(tag, tmp_root)
    out_path = str(Path(tmp_root) / f"out_{{tag}}.gpkg")
    converter = GeoPackageConverter(profile="military")
    result = converter.convert(
        source_geodatabase=local_shp,
        output_geopackage=out_path,
        title=f"Concurrent Test {{tag}}",
        abstract="Test concurrent writes",
        poc="Test User",
        org="Test Org",
        nation="USA",
        security="UNCLASSIFIED",
        generate_reports=True,
    )
    if not result.get("success"):
        raise RuntimeError(f"conversion {{tag}} reported failure: {{result.get('error')}}")
    return result
'''

SEQUENTIAL_HANDOFF_BODY = r'''
tmp_root = tempfile.mkdtemp()
errors = {{}}

def worker(i):
    try:
        run_conversion(f"{probe_name}_{{i}}", tmp_root)
        print(f"{probe_name}: thread {{i}} completed its FULL turn (patch={{PATCH_STAGE}})", flush=True)
    except Exception as e:
        errors[i] = str(e)

print("{probe_name}: starting thread A, will wait for it to fully finish...", flush=True)
t_a = threading.Thread(target=worker, args=(0,))
t_a.start()
t_a.join(timeout=60)
if 0 in errors:
    print(f"{probe_name}: thread A errors: {{errors}}", flush=True)
    raise SystemExit(1)

print("{probe_name}: thread A finished cleanly. Starting thread B (a genuinely "
      "different, freshly-created OS thread) now...", flush=True)
t_b = threading.Thread(target=worker, args=(1,))
t_b.start()
t_b.join(timeout=60)
if errors:
    print(f"{probe_name}: errors: {{errors}}", flush=True)
    raise SystemExit(1)

print("{probe_name} OK", flush=True)
'''


def _build_probe(probe_name: str, patch_stage: str) -> str:
    return (
        REAL_CONVERT_PREAMBLE.format(patch_stage=patch_stage)
        + SEQUENTIAL_HANDOFF_BODY.format(probe_name=probe_name)
    )


# ---------------------------------------------------------------------------
# P37 is asymmetric - thread A and thread B run genuinely different code -
# so it cannot reuse SEQUENTIAL_HANDOFF_BODY's identical-worker template.
# Written out in full rather than generalizing the template, matching this
# series' preference for an explicit bespoke probe over a cleverer but
# harder-to-audit abstraction.
# ---------------------------------------------------------------------------
P37_SCRIPT = r'''
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler


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


def run_conversion_full(tag, tmp_root):
    """Thread A's job: the real, complete, unmodified convert() - GDAL
    write plus all three real validate_schema() calls. Identical in shape
    to every P27/P36 control."""
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


def lxml_only_turn(tag):
    """Thread B's job: NO GeoPackageConverter, NO GDAL call of any kind at
    all - just the real MetadataHandler building one real, full-sized
    metadata document (pure Python/string work, no libxml2 involved) and
    then the real, unmodified validate_schema() validating it. `language`
    and `topic_category` values are taken from converter.py's own
    module-docstring usage example (line 30-31), not guessed. If this still
    crashes, thread B's own GDAL write is not a necessary ingredient - a
    brand-new OS thread's first-ever real lxml touch, on its own, after
    another thread has already used GDAL+lxml earlier in the process, is
    enough by itself."""
    handler = MetadataHandler()
    xml_str = handler.generate_package_metadata(
        title=f"Concurrent Test {tag}",
        abstract="Test concurrent writes, lxml-only thread",
        poc="Test User",
        org="Test Org",
        nation="USA",
        security="UNCLASSIFIED",
        language="eng",
        topic_category="transportation",
        ref_date="2026-08-14",
    )
    # generate_package_metadata() already calls validate_schema() on this
    # same string internally (metadata_handler.py:846) - this second,
    # explicit call is intentional: it keeps this probe's INTENT ("thread B
    # validates schema for real, more than once, same as the real
    # pipeline") legible in the code itself rather than relying on a side
    # effect three calls deep.
    handler.validate_schema(xml_str)


tmp_root = tempfile.mkdtemp()
errors = {}

def worker_a(i):
    try:
        run_conversion_full(f"P37_{i}", tmp_root)
        print(f"P37: thread {i} (A, full real convert()) completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

def worker_b(i):
    try:
        lxml_only_turn(f"P37_{i}")
        print(f"P37: thread {i} (B, lxml-only, NO GDAL call at all) completed its FULL turn", flush=True)
    except Exception as e:
        errors[i] = str(e)

print("P37: starting thread A (full real convert()), will wait for it to fully finish...", flush=True)
t_a = threading.Thread(target=worker_a, args=(0,))
t_a.start()
t_a.join(timeout=60)
if 0 in errors:
    print(f"P37: thread A errors: {errors}", flush=True)
    raise SystemExit(1)

print("P37: thread A finished cleanly. Starting thread B (a genuinely different, "
      "freshly-created OS thread, lxml-only - no GDAL call at all) now...", flush=True)
t_b = threading.Thread(target=worker_b, args=(1,))
t_b.start()
t_b.join(timeout=60)
if errors:
    print(f"P37: errors: {errors}", flush=True)
    raise SystemExit(1)

print("P37 OK", flush=True)
'''


PROBES: list[tuple[str, str, str]] = [
    (
        "P36_control_no_patch",
        "Control: the real, complete convert() (all internal steps run for "
        "real), through this script's own harness. Expected CRASH, matching "
        "P27/P17/P18/P19 - confirms this harness before trusting P37-P40.",
        _build_probe("P36", "none"),
    ),
    (
        "P37_thread_b_lxml_only_no_gdal",
        "Thread A: real, complete convert(). Thread B: NO GDAL call at all - "
        "only a real generate_package_metadata() + real validate_schema(). "
        "Tests whether thread B's own GDAL write is necessary, or whether "
        "any brand-new OS thread's first real lxml touch is sufficient "
        "alone.",
        P37_SCRIPT,
    ),
    (
        "P38_compile_only_no_parse_no_validate",
        "MetadataHandler.validate_schema patched to do the real fresh "
        "schema compile (real file, real imports, real multiplicity/lock) "
        "then return immediately - never parses or validates any document. "
        "Tests whether schema COMPILATION alone is already sufficient.",
        _build_probe("P38", "compile_only"),
    ),
    (
        "P39_compile_and_parse_no_validate_call",
        "MetadataHandler.validate_schema patched to do the real compile AND "
        "the real etree.fromstring() parse of the real document, but never "
        "calls schema.validate(doc). Only meaningful if P38 is OK: isolates "
        "whether the .validate() tree-walk call itself is required.",
        _build_probe("P39", "compile_parse_no_validate_call"),
    ),
    (
        "P40_real_schema_trivial_doc",
        "MetadataHandler.validate_schema runs 100% real (compile, parse, "
        "validate, error_log) but the document validated is swapped for a "
        "trivial '<x/>', reproducing P26's untested variable (real document "
        "content) inside the real pipeline's real call sites/timing/thread.",
        _build_probe("P40", "trivial_doc"),
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
    path = LOG_DIR / f"diagnose_v0.30.30_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS FOLLOW-UP (v0.30.30)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.29 isolated MetadataHandler.validate_schema (real lxml schema")
    log("  validation) as the first confirmed-necessary ingredient found by")
    log("  bisecting the real convert() rather than a hand-rolled stand-in for")
    log("  it (P30 OK; P28/P29/P31 all still CRASH). This run chases the two")
    log("  questions that result leaves open: (1) does thread B need its OWN")
    log("  GDAL write, or does any brand-new OS thread's first real lxml touch")
    log("  crash alone (P37); and (2) does it matter that the real pipeline")
    log("  validates full-sized real metadata documents where P26's hand-rolled")
    log("  probe only ever validated a trivial '<x/>' (P40) - plus a finer cut")
    log("  inside validate_schema itself between compiling, parsing, and the")
    log("  .validate() call (P38/P39).")

    results = {}
    for name, desc, code in PROBES:
        results[name] = run_probe(name, desc, code)

    header("SUMMARY")
    for name, ok in results.items():
        log(f"  {'OK   ' if ok else 'CRASH'}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P36 OK                     -> this harness is not faithfully")
    log("                                reproducing the crash - compare")
    log("                                against P27 before trusting P37-P40.")
    log("  P36 CRASH, P37 CRASH        -> thread B's own GDAL write is NOT")
    log("                                necessary; any new OS thread's first")
    log("                                real lxml touch is sufficient alone.")
    log("                                Points at libxml2/Windows thread-")
    log("                                local-state init, not at GDAL.")
    log("  P36 CRASH, P37 OK           -> thread B's own GDAL write IS a")
    log("                                necessary co-ingredient.")
    log("  P38 CRASH                   -> schema compilation alone (never")
    log("                                reaching .validate()) is sufficient.")
    log("  P38 OK, P39 CRASH            -> a compiled schema + a parsed doc")
    log("                                alive together is sufficient; the")
    log("                                .validate() call itself is not")
    log("                                required.")
    log("  P38 OK, P39 OK               -> the .validate() tree-walk call")
    log("                                itself is the necessary step.")
    log("  P40 OK (P36 crashes)        -> real document content/size is the")
    log("                                necessary ingredient - explains why")
    log("                                P26's trivial-doc reproduction was")
    log("                                clean.")
    log("  P40 CRASH                   -> document content does not matter;")
    log("                                P26 differed from the real pipeline")
    log("                                for some other reason (most likely")
    log("                                whatever P37 finds).")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
