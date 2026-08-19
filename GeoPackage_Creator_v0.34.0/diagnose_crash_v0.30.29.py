# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Crash diagnosis for GeoPackage Creator v0.30.29 - follow-up to v0.30.28.

WHAT v0.30.28 FOUND
--------------------
    OK   P25_sequential_handoff_minimal
    OK   P26_sequential_handoff_repetition_matched

Fixing the overlap-vs-handoff gap from v0.30.27 did not change the
conclusion: a hand-rolled minimal three-way combination (GDAL write + lxml
compile(s) + two sqlite3 reopens), run with the exact same strict
sequential hand-off the real crash shows, still does not crash - with
either one lxml compile or three. Per that script's own reading guide:
"the overlap/handoff distinction was not the missing piece either; bisect
convert() itself directly next, rather than building more free-standing
probes that keep approximating it." This script does that.

WHY HAND-ROLLING STOPS HERE
-----------------------------
Three rounds of hand-rolled reimplementation (P13-15, P20-22, P23-26) have
each approximated a piece of the real pipeline and each has come back clean
while the real `convert()` keeps crashing (P17/P18/P19). Every one of those
probes risks being unfaithful in some way I haven't thought to check - that
is exactly what happened with P23/P24's missing hand-off. Rather than build
a FOURTH hand-rolled approximation, this script uses the real, unmodified
`GeoPackageConverter.convert()` - proven to crash reliably three times now -
and removes ONE real internal step at a time via monkey-patching, so every
step that DOES run is still the actual shipped code, not a stand-in for it.

Candidates, in the order `convert()` actually calls them after the GDAL
write: `_embed_metadata()` (sqlite3 reopen #1), `_finalize_dgiwg_compliance()`
(sqlite3 reopen #2), and `MetadataHandler.validate_schema()` (every lxml
schema compile in the whole call, both the ones inside
`generate_package_metadata()`/`generate_layer_metadata()` and the extra
explicit one at converter.py:619 - patching this one method removes ALL
lxml schema-validation activity from the real pipeline in one shot, a
cleaner cut than trying to count exactly how many calls happen).

WHAT THIS SCRIPT DECIDES
-------------------------
Every probe uses the real `GeoPackageConverter.convert()`, `generate_reports
=True` (matching the shipped default and every prior crash), 2 threads,
STRICT sequential hand-off (thread A `join()`-ed to completion before
thread B is created - the pattern v0.30.28 confirmed is not itself the
missing piece, so it is kept, not reintroduced as a variable).

  P27  Control. No patch at all - the real, complete `convert()`, run
       through this script's own monkey-patch-capable harness (written
       fresh, not reusing P19's code verbatim) to confirm this harness
       reproduces the crash before trusting P28-P31's negative results.
       Expected CRASH, matching P17/P18/P19.

  P28  `GeoPackageConverter._embed_metadata` patched to a no-op returning
       0. Removes sqlite3 reopen #1 from the real pipeline; everything
       else (source reads, GDAL write, all metadata generation/validation,
       `_finalize_dgiwg_compliance`, output validation) still runs for
       real.

  P29  `GeoPackageConverter._finalize_dgiwg_compliance` patched to a no-op
       returning {}. Removes sqlite3 reopen #2 only.

  P30  `MetadataHandler.validate_schema` patched to a no-op returning True.
       Removes every lxml schema compile from the real pipeline - the
       metadata XML strings are still built (pure Python/string work), but
       libxml2 is never touched at all.

  P31  Both P28's and P29's patches together. Removes BOTH raw sqlite3
       reopens from the real pipeline, leaving GDAL + lxml (fully, at real
       multiplicity) as the only two libraries still touched.

  Reading the results:
      P27 OK                -> this harness itself is not faithfully
                                reproducing the crash; stop and compare it
                                against P19 line by line before trusting
                                P28-P31 either way.
      P27 CRASH, P28 OK      -> `_embed_metadata` (sqlite3 reopen #1) is
                                necessary.
      P27 CRASH, P29 OK      -> `_finalize_dgiwg_compliance` (sqlite3
                                reopen #2) is necessary.
      P27 CRASH, P30 OK      -> lxml schema validation is necessary - the
                                crash needs libxml2 touched at real
                                multiplicity inside the real call sequence,
                                even though P26's hand-rolled equivalent
                                (three compiles, sequential hand-off) did
                                not reproduce it alone.
      P27 CRASH, P31 OK      -> sqlite3 reopens (either one) are jointly
                                necessary; GDAL + lxml alone (real pipeline,
                                real multiplicity) is not sufficient.
      P27 CRASH, P28-P31 ALL CRASH
                            -> none of these three individually-removable
                                steps is the single necessary ingredient;
                                the hazard needs something structural this
                                script did not remove (the double source-
                                file `ogr.Open()`, `GDALHandler`'s own
                                write-lock/transaction machinery, or
                                `output_validator.validate_gpkg_structure`'s
                                own re-open) - narrow further by patching
                                those next, the same way.

No code fix is proposed alongside this script - same discipline as every
diagnostic before it in this series.

USAGE (Anaconda Prompt, `geopackage` env activated - never base)
------------------------------------------------------------------
    conda activate geopackage
    python dev_tools\\diagnose_crash_v0.30.29.py

Writes dev_tools\\logs\\diagnose_v0.30.29_<timestamp>.log incrementally, so a
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
# substituted per-probe; "none" applies no patch (the P27 control).
# ---------------------------------------------------------------------------
REAL_CONVERT_PREAMBLE = r'''
import sys, tempfile, threading
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from osgeo import ogr, osr
import core.converter as _conv_mod
from core import GeoPackageConverter
from core.metadata_handler import MetadataHandler

PATCH_STAGE = "{patch_stage}"

def _noop_embed_metadata(self, *a, **kw):
    return 0

def _noop_finalize_dgiwg_compliance(self, *a, **kw):
    return {{}}

def _noop_validate_schema(self, xml_str):
    return True

if PATCH_STAGE == "none":
    pass
elif PATCH_STAGE == "skip_embed_metadata":
    _conv_mod.GeoPackageConverter._embed_metadata = _noop_embed_metadata
elif PATCH_STAGE == "skip_finalize":
    _conv_mod.GeoPackageConverter._finalize_dgiwg_compliance = _noop_finalize_dgiwg_compliance
elif PATCH_STAGE == "skip_schema_validation":
    MetadataHandler.validate_schema = _noop_validate_schema
elif PATCH_STAGE == "skip_embed_and_finalize":
    _conv_mod.GeoPackageConverter._embed_metadata = _noop_embed_metadata
    _conv_mod.GeoPackageConverter._finalize_dgiwg_compliance = _noop_finalize_dgiwg_compliance
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
        "P27_control_no_patch",
        "Control: the real, complete convert() (all internal steps run for "
        "real), through this script's own harness. Expected CRASH, matching "
        "P17/P18/P19 - confirms this harness before trusting P28-P31.",
        _build_probe("P27", "none"),
    ),
    (
        "P28_skip_embed_metadata",
        "GeoPackageConverter._embed_metadata patched to a no-op. Removes "
        "sqlite3 reopen #1 (the gpkg_metadata CREATE+INSERT step) from the "
        "real pipeline; everything else still runs for real.",
        _build_probe("P28", "skip_embed_metadata"),
    ),
    (
        "P29_skip_finalize_dgiwg_compliance",
        "GeoPackageConverter._finalize_dgiwg_compliance patched to a no-op. "
        "Removes sqlite3 reopen #2 (application_id/WKT2/extension "
        "finalization) only.",
        _build_probe("P29", "skip_finalize"),
    ),
    (
        "P30_skip_schema_validation",
        "MetadataHandler.validate_schema patched to a no-op. Removes every "
        "lxml schema compile from the real pipeline - metadata XML strings "
        "are still built, but libxml2 is never touched.",
        _build_probe("P30", "skip_schema_validation"),
    ),
    (
        "P31_skip_embed_and_finalize",
        "Both P28's and P29's patches together. Removes BOTH raw sqlite3 "
        "reopens, leaving GDAL + lxml (at real multiplicity) as the only "
        "two libraries still touched by the real pipeline.",
        _build_probe("P31", "skip_embed_and_finalize"),
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
    path = LOG_DIR / f"diagnose_v0.30.29_{started:%Y%m%d_%H%M%S}.log"
    _LOG_FH = open(path, "w", encoding="utf-8", buffering=1)

    header("GeoPackage Creator - CRASH DIAGNOSIS FOLLOW-UP (v0.30.29)")
    log(f"  started : {started:%Y-%m-%d %H:%M:%S}")
    log(f"  log file: {path}")
    log("")
    log("  v0.30.28's P25/P26 (hand-rolled, sequential hand-off) still did not")
    log("  crash. Three rounds of hand-rolled reimplementation have now all")
    log("  come back clean while the real convert() keeps crashing. This run")
    log("  stops approximating and monkey-patches ONE real internal method at")
    log("  a time to a no-op, so every step that still runs is the actual")
    log("  shipped code, never a stand-in for it.")

    results = {}
    for name, desc, code in PROBES:
        results[name] = run_probe(name, desc, code)

    header("SUMMARY")
    for name, ok in results.items():
        log(f"  {'OK   ' if ok else 'CRASH'}  {name}")

    log("")
    log("HOW TO READ THIS:")
    log("  P27 OK                    -> this harness is not faithfully")
    log("                               reproducing the crash - compare")
    log("                               against P19 before trusting P28-P31.")
    log("  P27 CRASH, P28 OK          -> _embed_metadata (sqlite3 reopen #1)")
    log("                               is necessary.")
    log("  P27 CRASH, P29 OK          -> _finalize_dgiwg_compliance (sqlite3")
    log("                               reopen #2) is necessary.")
    log("  P27 CRASH, P30 OK          -> lxml schema validation is necessary")
    log("                               at real multiplicity/context.")
    log("  P27 CRASH, P31 OK          -> sqlite3 reopens (either) are jointly")
    log("                               necessary; GDAL+lxml alone is not.")
    log("  P27 CRASH, P28-31 ALL CRASH")
    log("                            -> none of these three is individually")
    log("                               necessary; narrow further next (the")
    log("                               double source ogr.Open(), GDALHandler's")
    log("                               own locking/transactions, or output")
    log("                               validation's own re-open).")

    _LOG_FH.close()
    print()
    print(f"Log written to: {path}")
    print("Please send this file back for review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
