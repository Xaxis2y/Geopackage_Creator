# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.31 - follow-up to v0.30.30.

WHAT v0.30.30 FOUND
--------------------
    CRASH  P36_control_no_patch
    CRASH  P37_thread_b_lxml_only_no_gdal
    CRASH  P38_compile_only_no_parse_no_validate
    CRASH  P39_compile_and_parse_no_validate_call
    CRASH  P40_real_schema_trivial_doc

All five crashed. Read together, this rules out three of the four open
hypotheses in one run:

  * P37 CRASH -> thread B's own GDAL write is NOT necessary. A brand-new
    OS thread's first real lxml touch, with zero GDAL calls in that
    thread, crashes just as reliably as the full pipeline. This points at
    libxml2/Windows thread-local-state initialization on a new OS thread,
    not at anything GDAL does.

  * P38 CRASH -> schema COMPILATION ALONE - `self.schema` accessed once,
    then discarded, never reaching `etree.fromstring()` or
    `schema.validate()` on any document - is already sufficient. The
    fault is now confirmed to live entirely inside `_compile_schema_
    fresh()`. P39 crashing too is consistent with this and adds no new
    information on its own.

  * P40 CRASH -> real document content/size does NOT matter. Validating a
    trivial `<x/>` through the real pipeline's real call sites still
    crashes. The "P26 was clean because it only ever validated a trivial
    document" theory from the v0.30.30 docstring is refuted.

WHAT THIS LEAVES OPEN
-----------------------
`diagnose_crash_v0.30.28.py`'s P26 - real schema FILE
(schemas/iso19139-gmd.xsd), sequential hand-off, three compile+validate
calls per thread's turn - came back OK. P40 just eliminated "the document
it validated was trivial" as the explanation. That leaves exactly one
unexamined difference between P26's hand-rolled `compile_and_validate()`
and the real, shipped `_compile_schema_fresh()`:

    P26 (v0.30.28, OK):
        schema_doc = etree.parse(str(XSD))
        schema = etree.XMLSchema(schema_doc)

    real _compile_schema_fresh() (shipped, CRASHES):
        schema_doc = etree.parse(str(_SCHEMA_SOURCE_PATH), _build_hardened_parser())
        schema = etree.XMLSchema(schema_doc)

P26 never constructs an `etree.XMLParser` at all - it lets lxml use its
own implicit, presumably-already-initialized-in-thread-A default parser.
The real code explicitly builds a brand-new, hardened `etree.XMLParser
(no_network=True, resolve_entities=False, huge_tree=False)` on every
single call (see `_build_hardened_parser()`'s own docstring: "Built per
call rather than cached"). Every other variable that could explain the
P26-vs-real gap - schema file, document content, GDAL involvement, thread
count/timing, call multiplicity - has now been tested and ruled out
(P40, P37, and the identical multiplicity used since v0.30.28). The
parser is the last one standing.

WHAT THIS SCRIPT DECIDES
-------------------------
Every probe here is shaped exactly like P38 - `validate_schema` patched to
touch only what's under test and return immediately, never reaching
`etree.fromstring()` or `.validate()` on any document - so each one
changes exactly one thing relative to P38's already-confirmed CRASH,
inside the real pipeline, real thread, real lock, real per-call
fresh-and-discard lifetime.

  P41  Control. No patch at all. Expected CRASH, matching P36/P27/P17-19 -
       confirms this harness before trusting P42-P44.

  P42  Schema-file parse uses NO explicit parser - `etree.parse(str(
       _SCHEMA_SOURCE_PATH))`, lxml's implicit default, exactly matching
       P26 - instead of `_build_hardened_parser()`. `etree.XMLSchema()`
       still compiles the result for real afterward, same as P38. If this
       comes back OK, the hardened-parser construction is confirmed as
       the trigger and precisely explains why P26 was clean.

  P43  Same as P42, but instead of omitting the parser argument, passes a
       freshly-constructed `etree.XMLParser()` with none of the hardening
       options set. Only meaningful to compare against P42: distinguishes
       "any freshly-constructed XMLParser object is unsafe here" (P43
       would still crash) from "specifically the no_network /
       resolve_entities=False / huge_tree=False options are unsafe here,
       not fresh construction itself" (P43 would be OK, matching P42).

  P44  Schema-file parse keeps the real hardened parser (unchanged from
       P38) and still resolves the schema's real cross-file gco/gml
       imports, but returns immediately after the parse - `etree.
       XMLSchema()` is never called at all. Isolates whether the PARSE
       step alone is already sufficient, or whether the `XMLSchema()`
       compile call specifically is required, as the v0.30.10 module
       docstring's own "compiling an XML Schema is the single least
       thread-safe thing in libxml2" already suspected.

  Reading the results:
      P41 OK                 -> this harness is not faithfully
                                 reproducing the crash; stop and compare
                                 it against P36 before trusting P42-P44.
      P41 CRASH, P42 CRASH    -> dropping the custom parser does NOT fix
                                 it. The hardened-vs-default parser
                                 distinction is not the explanation for
                                 P26; the real gap is still unidentified
                                 and needs a different angle next.
      P41 CRASH, P42 OK       -> CONFIRMED: the freshly-constructed
                                 hardened parser is the trigger. This
                                 precisely explains why P26 (no custom
                                 parser) was clean. Proceed to P43's
                                 result to learn whether it is fresh
                                 construction itself or specifically
                                 those three options.
      P42 OK, P43 CRASH       -> the non-default OPTIONS (no_network /
                                 resolve_entities=False / huge_tree=False)
                                 are what matter, not merely constructing
                                 a new parser object.
      P42 OK, P43 OK          -> ANY freshly-constructed XMLParser
                                 instance is unsafe the first time a new
                                 OS thread touches it here - even one
                                 with every option left at its default.
      P44 CRASH                -> the parse step alone (hardened parser,
                                 real cross-file import resolution) is
                                 already sufficient; XMLSchema() compile
                                 is not required to trigger it.
      P44 OK                   -> the XMLSchema() compile call
                                 specifically is required; parsing the
                                 file alone (even hardened) is safe.

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series. If P42 comes back OK, the shape of a
safe fix becomes visible (reuse one lazily-constructed parser instead of
building a fresh one per call, or warm up a throwaway parser once per
thread outside the hot path) - but that is a decision for after this
result, not before it.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.31.py

Writes dev_tools\\logs\\diagnose_v0.30.31_<timestamp>.log incrementally, so a
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
# Shared preamble: real project code only, plus one monkey-patch hook applied
# ONCE at module level (main thread), before any worker thread is created -
# matching every earlier probe's import-order discipline. `PATCH_STAGE` is
# substituted per-probe; "none" applies no patch (the P41 control). Every
# non-"none" patch is shaped exactly like v0.30.30's P38: touch only what is
# under test, then return True immediately, never reaching
# etree.fromstring() or .validate() on any document.
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


def _resolve_schema_path_if_needed():
    """Mirrors the path-resolution block at the top of the real
    _compile_schema_fresh() verbatim - this part was independently
    confirmed lxml-free and safe back in diagnose_crash_v0.30.21.py
    (probes P1-P3) and is not itself under test here."""
    if not _mh_mod._SCHEMA_PATH_RESOLVED:
        _mh_mod._SCHEMA_SOURCE_PATH = _mh_mod._locate_schema_file()
        _mh_mod._SCHEMA_PATH_RESOLVED = True
    return _mh_mod._SCHEMA_SOURCE_PATH is not None and not _mh_mod._SCHEMA_KNOWN_BROKEN


def _p42_default_parser_validate_schema(self, metadata_xml_string):
    # Same shape as P38 (compile, then return - never parses or validates
    # any document) but the schema-FILE parse uses NO explicit parser -
    # lxml's implicit default - instead of _build_hardened_parser(),
    # exactly matching P26's compile_and_validate().
    with _mh_mod._LXML_LOCK:
        if not _resolve_schema_path_if_needed():
            return True
        _mh_mod._verify_libxml2_abi()
        try:
            schema_doc = etree.parse(str(_mh_mod._SCHEMA_SOURCE_PATH))
            schema = etree.XMLSchema(schema_doc)
            del schema
        except Exception:
            _mh_mod._SCHEMA_KNOWN_BROKEN = True
    return True


def _p43_plain_xmlparser_validate_schema(self, metadata_xml_string):
    # Same as P42, but passes a freshly-constructed etree.XMLParser() with
    # none of the hardening options set, instead of omitting the parser
    # argument entirely. Only meaningful compared against P42's result.
    with _mh_mod._LXML_LOCK:
        if not _resolve_schema_path_if_needed():
            return True
        _mh_mod._verify_libxml2_abi()
        try:
            plain_parser = etree.XMLParser()
            schema_doc = etree.parse(str(_mh_mod._SCHEMA_SOURCE_PATH), plain_parser)
            schema = etree.XMLSchema(schema_doc)
            del schema
        except Exception:
            _mh_mod._SCHEMA_KNOWN_BROKEN = True
    return True


def _p44_parse_only_no_compile_validate_schema(self, metadata_xml_string):
    # Same shape as P38, but stops right after the schema-FILE PARSE (real
    # hardened parser, real cross-file gco/gml import resolution) - never
    # calls etree.XMLSchema() at all.
    with _mh_mod._LXML_LOCK:
        if not _resolve_schema_path_if_needed():
            return True
        _mh_mod._verify_libxml2_abi()
        try:
            schema_doc = etree.parse(
                str(_mh_mod._SCHEMA_SOURCE_PATH), _mh_mod._build_hardened_parser()
            )
            del schema_doc  # deliberately never calls etree.XMLSchema()
        except Exception:
            _mh_mod._SCHEMA_KNOWN_BROKEN = True
    return True


if PATCH_STAGE == "none":
    pass
elif PATCH_STAGE == "schema_parse_default_parser":
    MetadataHandler.validate_schema = _p42_default_parser_validate_schema
elif PATCH_STAGE == "schema_parse_plain_xmlparser":
    MetadataHandler.validate_schema = _p43_plain_xmlparser_validate_schema
elif PATCH_STAGE == "schema_parse_no_compile":
    MetadataHandler.validate_schema = _p44_parse_only_no_compile_validate_schema
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


PROBES: list[tuple[str, str, str]] = [
    (
        "P41_control_no_patch",
        "Control: the real, complete convert() (all internal steps run for "
        "real), through this script's own harness. Expected CRASH, matching "
        "P36/P27/P17-19 - confirms this harness before trusting P42-P44.",
        _build_probe("P41", "none"),
    ),
    (
        "P42_schema_parse_default_parser",
        "Schema-file parse uses NO explicit parser (lxml's implicit "
        "default, exactly matching P26) instead of _build_hardened_parser(). "
        "etree.XMLSchema() still compiles the result for real afterward, "
        "same as P38. Tests whether the custom parser is the P26-vs-real "
        "gap.",
        _build_probe("P42", "schema_parse_default_parser"),
    ),
    (
        "P43_schema_parse_plain_xmlparser",
        "Same as P42, but passes a freshly-constructed etree.XMLParser() "
        "with none of the hardening options set, instead of omitting the "
        "parser argument entirely. Only meaningful compared against P42.",
        _build_probe("P43", "schema_parse_plain_xmlparser"),
    ),
    (
        "P44_schema_parse_no_compile",
        "Schema-file parse keeps the real hardened parser (unchanged from "
        "P38) and resolves the real cross-file gco/gml imports, but "
        "returns immediately after the parse - etree.XMLSchema() is never "
        "called. Tests whether the parse alone is sufficient, or whether "
        "the compile call specifically is required.",
        _build_probe("P44", "schema_parse_no_compile"),
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
    path = LOG_DIR / f"diagnose_v0.30.31_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS FOLLOW-UP (v0.30.31)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.30 ruled out three of four open hypotheses in one run: thread")
    log("  B's own GDAL write is not necessary (P37 CRASH), the fault lives")
    log("  entirely inside _compile_schema_fresh() before any document is ever")
    log("  touched (P38 CRASH), and real document content/size does not matter")
    log("  (P40 CRASH). That leaves exactly one untested difference between")
    log("  P26 (hand-rolled, OK) and the real pipeline (CRASHES): the real code")
    log("  builds a brand-new, hardened etree.XMLParser on every call; P26 used")
    log("  lxml's implicit default parser and never built one at all. This run")
    log("  tests that, plus bisects the parse step from the compile step within")
    log("  _compile_schema_fresh() itself.")

    results = {}
    for name, desc, code in PROBES:
        results[name] = run_probe(name, desc, code)

    header("SUMMARY")
    for name, ok in results.items():
        log(f"  {'OK   ' if ok else 'CRASH'}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P41 OK                 -> this harness is not faithfully")
    log("                            reproducing the crash - compare against")
    log("                            P36 before trusting P42-P44.")
    log("  P41 CRASH, P42 CRASH    -> dropping the custom parser does NOT fix")
    log("                            it; the parser is not the P26-vs-real")
    log("                            explanation after all.")
    log("  P41 CRASH, P42 OK       -> CONFIRMED: the freshly-constructed")
    log("                            hardened parser is the trigger - exactly")
    log("                            explains why P26 was clean.")
    log("  P42 OK, P43 CRASH       -> the non-default OPTIONS matter, not")
    log("                            merely constructing a new parser object.")
    log("  P42 OK, P43 OK          -> ANY freshly-constructed XMLParser is")
    log("                            unsafe here, even with default options.")
    log("  P44 CRASH                -> the parse step alone is already")
    log("                            sufficient; XMLSchema() compile is not")
    log("                            required to trigger it.")
    log("  P44 OK                   -> the XMLSchema() compile call itself is")
    log("                            required; parsing alone (even hardened)")
    log("                            is safe.")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
