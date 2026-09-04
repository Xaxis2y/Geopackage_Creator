# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Entry-point logic for the DGIWG GeoPackage validator (v1.61).

process_file() validates a single GeoPackage and writes its report.
main() parses CLI args and drives batch or interactive mode.
"""
import os
import sys
import json
import textwrap
import tempfile
from pathlib import Path
from . import constants as _constants
from . import config as _config
from .constants import REQUIREMENTS, NET_TIMEOUT
from .constants import PASSSTAR_REASON_META
from .utils import (
    open_gpkg, collect_file_profile, _probe_optional_libraries,
    pick_files_dialog, score_results, coverage_gaps, advisory_reqs,
    LIBRARY_STATUS,
)
from .checks import run_all_checks
from .forensics import detect_source_software, run_forensic_checks
from .html_report import render_html
from .rollup import _write_rollup
def process_file(
    gpkg_path: str,
    reports_dir: str | None = None,
) -> tuple[str, dict, str] | None:
    """Run all checks on one GeoPackage, write per-file HTML report, return results.

    reports_dir — if supplied, HTML is written there instead of next to the .gpkg.
                  Used by batch/rollup runs so all per-file reports land in reports/.
    """
    stem    = Path(gpkg_path).stem
    gpkg_dir = os.path.dirname(os.path.abspath(gpkg_path))
    if reports_dir:
        out_dir = reports_dir
    else:
        out_dir = gpkg_dir
    # Fall back to a temp directory if target folder is read-only.
    # v1.57 fix (#11): previously fell back to the package directory itself,
    # which may also be read-only (e.g. site-packages) and clutters the
    # install with report files.
    test_path = os.path.join(out_dir, ".write_test")
    try:
        os.makedirs(out_dir, exist_ok=True)
        f = open(test_path, 'w')
        try:
            f.close()
        finally:
            try:
                os.remove(test_path)
            except OSError:
                pass
    except OSError:
        out_dir = os.path.join(tempfile.gettempdir(), "dgiwg_reports")
        os.makedirs(out_dir, exist_ok=True)
        print(f"  WARNING: target folder not writable — reports go to {out_dir}")
    html_out = os.path.join(out_dir, f"{stem}_DGIWG_Report.html")

    _quiet = _config.QUIET

    if not _quiet:
        print(f"\n{'='*60}")
        print(f"  DGIWG GeoPackage Compliance Report Generator")
        print(f"  File : {os.path.basename(gpkg_path)}")
        print(f"  Folder: {out_dir}")
        print(f"{'='*60}\n")

    if not _quiet:
        print("→ Opening GeoPackage …")
    try:
        conn = open_gpkg(gpkg_path)
    except ValueError as exc:
        print(f"  ERROR: {exc}")
        print("  File skipped — not a valid GeoPackage.")
        return None

    # v1.41 fix: structural validity gate — verify this is a real GeoPackage.
    # Empty SQLite stubs (zero tables) pass PRAGMA integrity_check but lack
    # gpkg_contents / gpkg_spatial_ref_sys, causing every requirement check to
    # raise "no such table" → caught by check_req() → false FAIL.  Reject early.
    _cur41 = conn.cursor()
    _missing_core = [
        t for t in ("gpkg_contents", "gpkg_spatial_ref_sys")
        if not _cur41.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)
        ).fetchone()
    ]
    if _missing_core:
        conn.close()
        print(
            f"  File skipped — not a valid GeoPackage "
            f"(missing core tables: {', '.join(_missing_core)})."
        )
        return None

    try:
        if not _quiet:
            print("→ Collecting file profile …")
        profile = collect_file_profile(conn, gpkg_path)

        if not _quiet:
            print("→ Detecting source software (forensic analysis) …")
        forensic = detect_source_software(conn)
        profile["source_software"] = (
            f"{forensic['software']} (confidence: {forensic['confidence']})"
        )
        software_tag = {
            "QGIS/GDAL": "_QGIS",
            "ArcGIS":    "_ARCGIS",
            "UNKNOWN":   "_UNKNOWN",
        }.get(forensic["software"], "_UNKNOWN")

        # Re-derive output filenames with software tag
        html_out = os.path.join(out_dir, f"{stem}{software_tag}_DGIWG_Report.html")
        report_filename = f"{stem}{software_tag}_DGIWG_Report.html"

        # Guard against filename collision when two .gpkg files from different
        # folders share the same basename (e.g. folder_a/map.gpkg, folder_b/map.gpkg).
        # Append _2, _3 … until the name is unique in out_dir.
        _collision = 2
        while os.path.exists(html_out):
            report_filename = f"{stem}{software_tag}_DGIWG_Report_{_collision}.html"
            html_out = os.path.join(out_dir, report_filename)
            _collision += 1
        if not _quiet:
            print(f"   Source software: {forensic['software']} ({forensic['confidence']} confidence) → tag: {software_tag}")

        if not _quiet:
            print("→ Running requirement checks (Req 1–37) …")
        results = run_all_checks(conn)

        if not _quiet:
            print("→ Running forensic deep-dive checks …")
        forensic_checks = run_forensic_checks(conn, forensic["software"])
        results["__forensic_checks__"] = forensic_checks

    finally:
        conn.close()   # guaranteed even if any check above throws

    # Attach forensic hints to result details for affected requirements
    for req_num, hint in forensic["hints"].items():
        if req_num in results:
            existing_detail = results[req_num]["detail"]
            results[req_num]["detail"] = f"{existing_detail}\n\n🔬 SOFTWARE AUDIT HINT [{forensic['software']}]: {hint}"

    # Store forensic data for rendering
    results["__forensic__"] = forensic

    counts, total, verdict, _ = score_results(results)
    _gaps = coverage_gaps(results)   # v1.61: [(req_num, reason), ...] — blocks CONFORMANT
    if _quiet:
        print(f"  {os.path.basename(gpkg_path):60s} {verdict:24s} "
              f"PASS={counts['PASS']} FAIL={counts['FAIL']} PASS*={counts['PASS*']} "
              f"SKIP={counts['SKIPPED']}")
    else:
        print(f"\n  Verdict : {verdict}")
        print(f"  PASS    : {counts['PASS']}")
        print(f"  FAIL    : {counts['FAIL']}")
        print(f"  PASS*   : {counts['PASS*']}")
        print(f"  SKIPPED : {counts['SKIPPED']}\n")

    # v1.61: surface exactly which requirements are keeping the verdict from
    # "CONFORMANT (automated scope)" and what would close each gap, so a
    # "CONFORMANT — REDUCED COVERAGE" verdict is actionable, not just a label.
    if _gaps:
        _gap_reqs = ", ".join(f"Req {n}" for n, _ in _gaps)
        print(f"  Coverage: incomplete on {_gap_reqs}")
        _remedies_seen = []
        for _n, _reason in _gaps:
            _remedy = PASSSTAR_REASON_META.get(_reason, {}).get("remedy")
            if _remedy and _remedy not in _remedies_seen:
                _remedies_seen.append(_remedy)
        for _r in _remedies_seen:
            print(f"            {_r}")
        print()

    if not _quiet:
        print("→ Generating HTML report …")
    render_html(profile, results, html_out)
    if not _quiet:
        print(f"   Saved → {html_out}")

    # ── v1.53: JSON always generated (--json flag retained for compat, now no-op) ──
    if True:  # v1.53: unconditional — JSON written for every report
        try:
            _json_path = os.path.splitext(html_out)[0] + ".json"
            _req_export = {}
            for _rk, _rv in results.items():
                if isinstance(_rk, int):
                    _req_tuple = REQUIREMENTS.get(_rk)
                    if _req_tuple:
                        _req_export[str(_rk)] = {
                            "name":       _req_tuple[0],
                            "identifier": _req_tuple[1],
                            "compliance": _req_tuple[2],
                            "status":     _rv.get("status", ""),
                            "reason":     _rv.get("reason"),
                            "detail":     (_rv.get("detail") or "")[:1000],
                        }
            # v1.58 fix: schema_version sourced from the package so it can
            # never drift from __init__.__version__ (same principle as the
            # v1.57 --version fix).
            from . import __version__ as _schema_ver
            # v1.61: coverage block makes the blocking/advisory PASS* split
            # (the reason the verdict landed where it did) machine-readable,
            # not just embedded in prose.
            _coverage = {
                "gaps":      [{"req": n, "reason": r} for n, r in coverage_gaps(results)],
                "advisory":  advisory_reqs(results),
            }
            _json_payload = {
                "schema_version": _schema_ver,
                "file":      os.path.basename(gpkg_path),
                "software":  profile.get("source_software", "UNKNOWN"),
                "verdict":   verdict,
                "counts":    counts,
                "coverage":  _coverage,
                "requirements": _req_export,
                "forensic":  forensic,
                "internet_checks": {
                    k: list(v) if isinstance(v, tuple) else v
                    for k, v in results.get("__internet__", {}).items()
                },
                "cascade_root_cause": results.get("__cascade_note__", None),
            }
            with open(_json_path, "w", encoding="utf-8") as _jf:
                json.dump(_json_payload, _jf, indent=2, ensure_ascii=False)
            if not _quiet:
                print(f"   JSON → {_json_path}")
        except Exception as _json_err:
            print(f"   JSON export failed: {_json_err}")

    if not _quiet:
        print(f"\n{'='*60}")
        print("  Done.")
        print(f"{'='*60}\n")

    # Return data needed for rollup aggregation
    return (os.path.basename(gpkg_path), results, report_filename)


def main() -> None:
    import argparse

    # v1.58: description version sourced from the package (no hardcoded drift)
    from . import __version__ as _desc_version
    parser = argparse.ArgumentParser(
        prog="dgiwg_validator",
        description=f"DGIWG GeoPackage Compliance Report Generator — STD-DP-19-005 v1.1 (script v{_desc_version})",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Use either the versioned launcher (DGIWG_Validator_v1_61.py) or
            the module form shown below.  (v1.59 fix: these examples used to
            invoke "dgiwg_validator.py", a filename that does not exist in the
            distribution.)

            Examples:
              # Interactive file picker (no arguments)
              python -m dgiwg_validator

              # Validate a single file
              python -m dgiwg_validator myfile.gpkg

              # Validate all .gpkg files in a folder (add --recursive for subfolders)
              python -m dgiwg_validator "C:\\Data\\Project_Alpha"
              python -m dgiwg_validator --recursive "C:\\Data\\Project_Alpha"

              # Explicit --file and --dir flags (identical to positional arguments)
              python -m dgiwg_validator --file map_data.gpkg
              python -m dgiwg_validator --dir "C:\\Data\\Project_Alpha"

              # Air-gapped machine — skip all EPSG/OGC internet checks
              python -m dgiwg_validator --offline myfile.gpkg

              # Skip the optional-library install prompts on locked-down systems
              python -m dgiwg_validator --no-install myfile.gpkg

              # Sample more geometry blobs per table for deeper Req 24 coverage
              python -m dgiwg_validator --sample-size 50 myfile.gpkg

              # Batch QA: one summary line per file, all reports in one folder
              python -m dgiwg_validator --quiet --output-dir "C:\\QA\\reports" "C:\\Data"

              # Stop at the first non-conformant file (exit code 1)
              python -m dgiwg_validator --fail-fast "C:\\Data"

              # Equivalent launcher form for any of the above
              python DGIWG_Validator_v1_61.py --offline myfile.gpkg
        """),
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        metavar="FILE_OR_FOLDER",
        help="GeoPackage file(s) or folder(s) containing .gpkg files. "
             "Omit to open the interactive file-picker dialog.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        default=False,
        help="Disable all internet checks (EPSG URI verification, OGC TMS validation). "
             "Useful on air-gapped / 국방망 networks. Affected checks return PASS* with "
             "an 'offline mode' note instead of querying external endpoints.",
    )
    parser.add_argument(
        "--no-install",
        action="store_true",
        default=False,
        dest="no_install",
        help="Skip the optional-library install prompts entirely. "
             "Libraries that are already installed will still be used; "
             "missing ones will produce PASS* results as normal.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        dest="sample_size",
        metavar="N",
        help="Number of geometry/tile BLOBs to sample per table for Req 24 and Req 26 "
             "(default: 25). Higher values give broader coverage at the cost of speed.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        dest="timeout",
        metavar="SECONDS",
        help=f"Network timeout in seconds for all HTTP checks — EPSG API, OGC TMS URI "
             f"verification, etc. (default: {NET_TIMEOUT}s). Increase on slow connections; "
             f"decrease to fail faster on unresponsive endpoints.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        dest="emit_json",
        help="Retained for backward compatibility — since v1.53 the JSON companion "
             "report ({stem}_DGIWG_Report.json) is ALWAYS written alongside each HTML "
             "file, so this flag has no additional effect. Contains verdict, counts, "
             "software, and per-requirement status/detail/compliance.",
    )
    parser.add_argument(
        "--dir",
        action="append",
        default=[],
        dest="dir_inputs",
        metavar="FOLDER",
        help="Explicit folder path containing .gpkg files to validate. "
             "All .gpkg files inside the folder are processed. "
             "Equivalent to supplying FOLDER as a positional argument. "
             "May be repeated to process multiple folders.",
    )
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        dest="file_inputs",
        metavar="FILE",
        help="Explicit path to a single .gpkg file to validate. "
             "Equivalent to supplying FILE as a positional argument. "
             "May be repeated to process multiple files.",
    )
    # v1.57 fix (#5): version string now sourced from the package itself so it
    # can never drift from __init__.__version__ again.
    from . import __version__ as _pkg_version
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_pkg_version}",
    )
    # v1.49: --output-dir flag — write all reports to this folder
    parser.add_argument(
        "--output-dir",
        default=None,
        dest="output_dir",
        metavar="FOLDER",
        help="Write all HTML/JSON/CSV reports to this folder instead of the "
             "default 'reports/' subfolder alongside each GeoPackage.",
    )
    # v1.49: --recursive flag — search folders recursively for .gpkg files
    parser.add_argument(
        "--recursive",
        action="store_true",
        default=False,
        dest="recursive",
        help="When a folder is given, use rglob('**/*.gpkg') instead of "
             "glob('*.gpkg') to find GeoPackages in nested subdirectories.",
    )
    # v1.49: --quiet flag — suppress per-file progress banners
    parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        dest="quiet",
        help="Suppress per-file progress banner output. Only final summary "
             "counts and errors are shown.",
    )
    # v1.49: --fail-fast flag — stop after first file with FAIL result
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        default=False,
        dest="fail_fast",
        help="Stop processing after the first file that has any FAIL result. "
             "Exits with code 1 after printing a clear message.",
    )

    args = parser.parse_args()

    # Merge --dir / --file explicit flags into the positional inputs list so that
    # all three input methods share a single processing path below.
    # Example: --dir "C:\Data\Project_Alpha"  is identical to passing the folder
    # as a positional argument.
    all_inputs = list(args.inputs) + list(args.dir_inputs) + list(args.file_inputs)

    # ── Push parsed flags into the runtime config ──────────────────────────────
    # v1.57 fix (#9): flags now live in dgiwg_validator.config instead of being
    # smuggled through attributes on the builtins module.
    if args.offline:
        _config.OFFLINE = True                   # checked by _net_get() at call time
        print("  [--offline] Internet checks disabled.")

    if args.emit_json:
        print("  [--json] Note: JSON companion reports are always written since v1.53.")

    if args.sample_size is not None:
        if args.sample_size < 1:
            parser.error("--sample-size must be at least 1")
        _config.SAMPLE_SIZE = args.sample_size
        print(f"  [--sample-size] Geometry/tile sample size set to {args.sample_size}.")

    if args.timeout is not None:
        if args.timeout < 1:
            parser.error("--timeout must be at least 1 second")
        # Patch constants module so all submodules pick up the new timeout
        _constants.NET_TIMEOUT = args.timeout
        print(f"  [--timeout] Network timeout set to {args.timeout}s.")

    _config.QUIET     = args.quiet
    _config.FAIL_FAST = args.fail_fast
    if args.quiet:
        print("  [--quiet] Per-file progress banners suppressed.")
    if args.fail_fast:
        print("  [--fail-fast] Will stop after first non-conformant file.")

    # ── Command-line mode (file paths or folders supplied) ─────────────────────
    if all_inputs:
        _probe_optional_libraries(
            interactive_mode=False,
            skip_install=args.no_install,
        )

        gpkg_paths = []
        for inp in all_inputs:
            if os.path.isdir(inp):
                # v1.49: --recursive uses rglob; default uses glob (top-level only)
                # v1.50 fix: filter out double-extension .gpkg.gpkg files (Bug #1)
                if args.recursive:
                    found = sorted(
                        p for p in Path(inp).rglob("*.gpkg")
                        if not p.name.endswith(".gpkg.gpkg")
                    )
                else:
                    found = sorted(
                        p for p in Path(inp).glob("*.gpkg")
                        if not p.name.endswith(".gpkg.gpkg")
                    )
                if not found:
                    print(f"WARNING: No .gpkg files found in folder: {inp}"
                          + (" (try --recursive for subdirectories)" if not args.recursive else ""))
                else:
                    print(f"  Folder '{inp}': found {len(found)} GeoPackage(s)"
                          + (" (recursive)" if args.recursive else ""))
                    gpkg_paths.extend(str(p) for p in found)
            elif os.path.isfile(inp):
                gpkg_paths.append(inp)
            else:
                print(f"ERROR: Not a file or folder: {inp}")

        if not gpkg_paths:
            print("No valid GeoPackage files to process.")
            return

        rollup_dir  = os.path.dirname(os.path.abspath(gpkg_paths[0]))
        # v1.49: --output-dir overrides the default reports/ subfolder
        if args.output_dir:
            reports_dir = os.path.abspath(args.output_dir)
            rollup_dir  = reports_dir
        else:
            reports_dir = os.path.join(rollup_dir, "reports")
        os.makedirs(reports_dir, exist_ok=True)

        n_total = len(gpkg_paths)
        all_results = []
        for i, gpkg_path in enumerate(gpkg_paths, 1):
            if not args.quiet:
                print(f"\n  ── File {i} of {n_total} ──")
            # v1.57 fix (Bug #1 hardening): isolate each file so an unexpected
            # exception in one file no longer aborts the entire batch run.
            try:
                result = process_file(gpkg_path, reports_dir=reports_dir)
            except Exception as exc:
                print(f"  ERROR: Unexpected failure while processing "
                      f"'{os.path.basename(gpkg_path)}' — file skipped: "
                      f"{type(exc).__name__}: {exc}")
                result = None
            if result:
                all_results.append(result)
                # v1.49: --fail-fast: stop after first file with any FAIL
                if args.fail_fast:
                    _fname, _res, _rpt = result
                    if any(
                        v.get("status") == "FAIL"
                        for k, v in _res.items()
                        if isinstance(k, int)
                    ):
                        print(
                            f"\nFAIL-FAST: stopping after first non-conformant "
                            f"file — {_fname}"
                        )
                        _write_rollup(all_results, rollup_dir,
                                      reports_dir=reports_dir)
                        sys.exit(1)

        if all_results:
            _write_rollup(all_results, rollup_dir, reports_dir=reports_dir)
        return

    # ── Interactive mode (no arguments — show file picker) ────────────────────
    print("\n" + "="*60)
    print("  DGIWG GeoPackage Compliance Report Generator")
    print("="*60)
    print("\n  No file specified — opening file picker …\n")

    _probe_optional_libraries(
        interactive_mode=True,
        skip_install=args.no_install,
    )

    gpkg_paths = pick_files_dialog()
    if not gpkg_paths:
        sys.exit(0)

    n_total = len(gpkg_paths)
    print(f"\n  {n_total} file(s) selected.\n")

    rollup_dir  = os.path.dirname(os.path.abspath(gpkg_paths[0]))
    reports_dir = os.path.join(rollup_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    all_results = []
    for i, gpkg_path in enumerate(gpkg_paths, 1):
        print(f"\n  ── File {i} of {n_total} ──")  # interactive always verbose
        if not os.path.isfile(gpkg_path):
            print(f"  ERROR: File not found: {gpkg_path} — skipping.")
            continue
        # v1.57 fix (Bug #1 hardening): isolate each file — see CLI loop above.
        try:
            result = process_file(gpkg_path, reports_dir=reports_dir)
        except Exception as exc:
            print(f"  ERROR: Unexpected failure while processing "
                  f"'{os.path.basename(gpkg_path)}' — file skipped: "
                  f"{type(exc).__name__}: {exc}")
            result = None
        if result:
            all_results.append(result)

    if all_results:
        _write_rollup(all_results, rollup_dir)

    print("\n  All files processed.")
    input("  Press Enter to close …")


