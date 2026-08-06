# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Rollup aggregation + DGIWG_GPKG_FINAL_REPORT.html/.csv (v1.58)."""
import os
import sys
import html
import csv as _csv_mod
from .constants import REQUIREMENTS, REQ_ROLLUP_META, CONFIDENCE_COLOR, CONFIDENCE_BG
from .utils import score_results
from .html_report import _get_likely_cause
def aggregate_rollup(all_results):
    """
    all_results: list of (filename, results_dict, report_filename) tuples
    Returns:
      rollup   — per-req counts { req_num: { applicable, validator_disputes,
                                             auditor_disputes, passstar, manual_confirmed,
                                             fail_software: set of software tags that FAILed } }
      per_file — per-file manual counts [ { passstar, manual_confirmed } ]
    """
    # Requirements where an auditor should double-check even a passing automated result.
    # Selected on the basis that these reqs have known false-pass risk, involve cross-table
    # logic that a single-check approach can miss, or have real-world dispute history across
    # the 24-file test set (see REQ_ROLLUP_META confidence notes).
    AUDITOR_FLAGGED_REQS = {
        3,   # Mandatory extensions — extension list changes between DGIWG editions
        5,   # Disallowed extensions — gdal_nw false-negatives if table is absent
        11,  # Gridded 2D CRS bbox — 0.1% tolerance can mask borderline cases
        12,  # Gridded 3D CRS bbox — same tolerance risk as Req 11
        14,  # Compound CRS usage — z=0 detection relies on gpkg_geometry_columns
        22,  # Product metadata — XML structural check; semantic quality is manual
        24,  # Data validity — geometry sample may miss invalid geometries in tail
        25,  # Tile matrix 256×256 — column-presence only; actual BLOB decode is Req 26
        32,  # Feature layer metadata — XML structural check; semantic quality is manual
    }

    rollup = {req: {
        "applicable": 0, "validator_disputes": 0,
        "auditor_disputes": 0, "passstar": 0, "manual_confirmed": 0,
        "fail_software": set(),   # which software types produced FAIL for this req
        "has_passstar": False,    # any PASS* across all files for this req
    } for req in REQUIREMENTS}

    per_file = []

    for filename, results, *_ in all_results:
        file_passstar = 0
        file_manual   = 0
        sw = results.get("__forensic__", {}).get("software", "UNKNOWN")
        for req_num, r in results.items():
            if req_num in ("__internet__", "__forensic__", "__forensic_checks__", "__cascade_note__"):
                continue
            status = r["status"]
            if status == "SKIPPED":
                continue
            rollup[req_num]["applicable"] += 1
            if status == "FAIL":
                rollup[req_num]["validator_disputes"] += 1
                rollup[req_num]["fail_software"].add(sw)
            if status == "PASS*":
                rollup[req_num]["passstar"] += 1
                rollup[req_num]["has_passstar"] = True
                file_passstar += 1
                mc = r.get("manual")
                if mc and mc[1] > 0 and mc[0] == mc[1]:
                    rollup[req_num]["manual_confirmed"] += 1
                    file_manual += 1
            # Auditor disputes: count only FAIL or PASS* on auditor-flagged
            # requirements — a clean PASS does not need auditor attention
            if req_num in AUDITOR_FLAGGED_REQS and status in ("FAIL", "PASS*"):
                rollup[req_num]["auditor_disputes"] += 1
        per_file.append({
            "filename":         filename,
            "passstar":         file_passstar,
            "manual_confirmed": file_manual,
        })

    return rollup, per_file


# ──────────────────────────────────────────────────────────────────────────────
# ROLLUP HTML REPORT
# ──────────────────────────────────────────────────────────────────────────────

def render_rollup_html(
    all_results: list[tuple[str, dict, str]],
    output_path: str,
    reports_relpath: str = "reports",
) -> None:
    # reports_relpath — POSIX-style relative path from rollup HTML directory
    # to per-file reports directory. Default "reports" for the normal layout
    # (rollup one level above reports/). Pass "." when --output-dir places both
    # in the same folder. v1.50 fix for --output-dir broken links (Bug #2).
    _rep_prefix = reports_relpath.replace("\\", "/")
    rollup, per_file = aggregate_rollup(all_results)
    n_files = len(all_results)

    def dispute_str(disputes, applicable):
        if applicable == 0:
            return "Not applicable (all SKIPPED)"
        return f"{disputes} dispute{'s' if disputes != 1 else ''} out of {applicable} applicable GPKG{'s' if applicable != 1 else ''}"

    rows_html = []
    for req_num, (name, uri, compliance) in REQUIREMENTS.items():
        meta  = REQ_ROLLUP_META.get(req_num, {})
        r     = rollup[req_num]
        conf  = meta.get("confidence", "Medium")
        c_col = CONFIDENCE_COLOR[conf]
        c_bg  = CONFIDENCE_BG[conf]
        applicable    = r["applicable"]
        v_disp        = r["validator_disputes"]
        a_disp        = r["auditor_disputes"]
        ps_count      = r["passstar"]
        mc_count      = r["manual_confirmed"]

        # Colour the validator dispute cell
        if applicable == 0:
            v_bg, v_col = "#f4f4f4", "#95a5a6"
        elif v_disp == 0:
            v_bg, v_col = "#eafaf1", "#27ae60"
        else:
            frac = v_disp / applicable
            if frac >= 0.5:
                v_bg, v_col = "#fdedec", "#e74c3c"
            else:
                v_bg, v_col = "#fef9e7", "#e67e22"

        # Auditor disputes cell
        if applicable == 0:
            a_bg, a_col = "#f4f4f4", "#95a5a6"
        elif a_disp == 0:
            a_bg, a_col = "#eafaf1", "#27ae60"
        else:
            a_bg, a_col = "#fdebd0", "#e67e22"

        # ── Dynamic confidence override for rollup ────────────────────────────
        # 1. If ALL applicable files returned SKIPPED → check never ran → Low
        if applicable == 0:
            conf  = "Low"
        # 2. If there are PASS* results but 0 were manually confirmed → Low
        elif ps_count > 0 and mc_count == 0:
            conf  = "Low"
        # 3. If PASS* results exist but less than half confirmed → Medium (cap)
        elif ps_count > 0 and mc_count < ps_count and conf == "High":
            ratio = mc_count / ps_count
            if ratio < 0.5:
                conf = "Medium"
        c_col = CONFIDENCE_COLOR[conf]
        c_bg  = CONFIDENCE_BG[conf]
        # ─────────────────────────────────────────────────────────────────────

        auditor_bullets = "".join(
            f"<li>{c}</li>"
            for c in meta.get("auditor_checks", ["No additional cross-checks"])
        )

        # Auditor dispute summary line (used inside merged cell)
        if applicable == 0:
            auditor_summary = '<span style="color:#95a5a6;">N/A</span>'
        elif a_disp == 0:
            auditor_summary = '<span style="color:#27ae60;font-weight:bold;">No disputes</span>'
        else:
            auditor_summary = (
                f'<span style="color:#e67e22;font-weight:bold;">'
                f'{dispute_str(a_disp, applicable)}</span>'
            )

        # PASS* Manual Confirmed cell for requirement rollup
        if ps_count == 0:
            mc_req_cell = '<span style="color:#95a5a6;font-size:12px;">N/A (no PASS*)</span>'
            mc_req_bg   = "#f4f4f4"
        elif mc_count == ps_count:
            mc_req_cell = (f'<span style="background:#27ae60;color:white;padding:3px 8px;' 
                           f'border-radius:4px;font-weight:bold;font-size:13px;">' 
                           f'✅ {mc_count} / {ps_count}</span>')
            mc_req_bg   = "#eafaf1"
        elif mc_count > 0:
            mc_req_cell = (f'<span style="background:#f39c12;color:white;padding:3px 8px;' 
                           f'border-radius:4px;font-weight:bold;font-size:13px;">' 
                           f'⚠️ {mc_count} / {ps_count}</span>')
            mc_req_bg   = "#fef9e7"
        else:
            mc_req_cell = (f'<span style="background:#e74c3c;color:white;padding:3px 8px;' 
                           f'border-radius:4px;font-weight:bold;font-size:13px;">' 
                           f'❌ 0 / {ps_count}</span>')
            mc_req_bg   = "#fdedec"

        # ── Probable Cause cell ───────────────────────────────────────────────
        fail_sws    = r["fail_software"]       # set of software tags that FAILed
        has_passstar = r["has_passstar"]

        cause_blocks = []
        if v_disp > 0:
            # Show a cause block per software type that had FAILs
            for sw in sorted(fail_sws):
                cause_text = _get_likely_cause(req_num, "FAIL", sw)
                if cause_text:
                    sw_color = {"QGIS/GDAL": "#1a6b3c", "ArcGIS": "#1a3a6b"}.get(sw, "#6b4a1a")
                    sw_bg    = {"QGIS/GDAL": "#eafaf1", "ArcGIS": "#eaf0fb"}.get(sw, "#fdf6e3")
                    sw_icon  = {"QGIS/GDAL": "🟢", "ArcGIS": "🔵"}.get(sw, "🟡")
                    cause_blocks.append(
                        f'<div style="margin-bottom:5px;padding:5px 8px;background:#fff5f5;'
                        f'border-left:3px solid #e74c3c;border-radius:3px;">'
                        f'<div style="font-size:10px;font-weight:bold;color:#c0392b;margin-bottom:2px;">'
                        f'🔴 FAIL — {sw_icon} {sw}</div>'
                        f'<div style="font-size:11px;color:#555;">{html.escape(cause_text)}</div>'
                        f'</div>'
                    )
        if has_passstar:
            passstar_cause = _get_likely_cause(req_num, "PASS*", "UNKNOWN")
            if passstar_cause:
                cause_blocks.append(
                    f'<div style="padding:5px 8px;background:#fffbf0;'
                    f'border-left:3px solid #f39c12;border-radius:3px;">'
                    f'<div style="font-size:10px;font-weight:bold;color:#9a6500;margin-bottom:2px;">'
                    f'🔎 PASS* — verify manually</div>'
                    f'<div style="font-size:11px;color:#555;">{html.escape(passstar_cause)}</div>'
                    f'</div>'
                )
        if cause_blocks:
            probable_cause_cell = "".join(cause_blocks)
        elif applicable == 0:
            probable_cause_cell = '<span style="color:#ccc;font-size:12px;">—</span>'
        else:
            probable_cause_cell = '<span style="color:#27ae60;font-size:12px;font-weight:bold;">✅ No disputes</span>'

        rows_html.append(f"""
        <tr>
          <td style="padding:8px;font-weight:bold;white-space:nowrap;">{req_num}</td>
          <td style="padding:8px;">{name}
            <div style="font-size:11px;color:#888;margin-top:2px;">{uri}</div>
          </td>
          <td style="padding:8px;text-align:center;">
            <span style="background:#2c3e50;color:white;padding:2px 7px;border-radius:3px;font-size:11px;">{compliance}</span>
          </td>
          <td style="padding:8px;background:{v_bg};color:{v_col};font-weight:bold;font-size:13px;">
            {dispute_str(v_disp, applicable)}
          </td>
          <td style="padding:8px;vertical-align:top;">
            {probable_cause_cell}
            <details style="margin-top:6px;">
              <summary style="cursor:pointer;font-size:11px;font-weight:bold;color:#555;
                              list-style:none;display:flex;align-items:center;gap:4px;
                              user-select:none;">
                <span style="font-size:10px;">▶</span> 🔍 Auditor cross-checks
                &nbsp;{auditor_summary}
              </summary>
              <ul style="margin:5px 0 0 0;padding-left:16px;font-size:11px;color:#555;">
                {auditor_bullets}
              </ul>
            </details>
          </td>
          <td style="padding:8px;background:{mc_req_bg};vertical-align:top;">
            {mc_req_cell}
            <div style="font-size:10px;color:#888;margin-top:3px;">PASS* GPKGs: {ps_count}</div>
            <details style="margin-top:6px;">
              <summary style="cursor:pointer;font-size:11px;font-weight:bold;color:#555;
                              list-style:none;display:flex;align-items:center;gap:4px;
                              user-select:none;">
                <span style="font-size:10px;">▶</span> 📋 Manual Verification
              </summary>
              <div style="margin-top:5px;font-size:12px;color:#444;">
                {meta.get("manual_notes","—")}
              </div>
            </details>
          </td>
          <td style="padding:8px;text-align:center;background:{c_bg};">
            <span style="background:{c_col};color:white;padding:4px 10px;border-radius:4px;font-weight:bold;font-size:12px;">{conf}</span>
            <div style="font-size:10px;color:#666;margin-top:4px;">{meta.get("confidence_reason","")}</div>
          </td>
        </tr>""")

    # Per-file summary strip — include PASS*(Manual) from per_file data
    file_rows = ""
    for pf, (fname, results, report_fname) in zip(per_file, all_results):
        counts, _, verdict, vcol = score_results(results)
        mc    = pf["manual_confirmed"]
        ps    = pf["passstar"]
        # Get forensic software tag for this file
        _foren = results.get("__forensic__", {})
        _fsw   = _foren.get("software", "UNKNOWN")
        _fconf = _foren.get("confidence", "Low")
        _fsw_color = {"QGIS/GDAL": "#1a6b3c", "ArcGIS": "#1a3a6b", "UNKNOWN": "#7d5a00"}.get(_fsw, "#555")
        _fsw_bg    = {"QGIS/GDAL": "#eafaf1", "ArcGIS": "#eaf0fb", "UNKNOWN": "#fff8e1"}.get(_fsw, "#f8f9fa")
        _fsw_icon  = {"QGIS/GDAL": "🟢", "ArcGIS": "🔵", "UNKNOWN": "🟡"}.get(_fsw, "⚪")
        sw_cell = (
            f'<td style="padding:6px 10px;">'
            f'<span style="background:{_fsw_bg};color:{_fsw_color};border:1px solid {_fsw_color};'
            f'padding:2px 7px;border-radius:3px;font-size:11px;font-weight:bold;">'
            f'{_fsw_icon} {_fsw}</span>'
            f'<div style="font-size:10px;color:#999;margin-top:2px;">{_fconf} conf.</div>'
            f'</td>'
        )
        if ps == 0:
            mc_cell = '<td style="padding:6px 10px;color:#95a5a6;">N/A</td>'
        elif mc == ps:
            mc_cell = (f'<td style="padding:6px 10px;font-weight:bold;">' 
                       f'<span style="background:#27ae60;color:white;padding:2px 7px;border-radius:3px;">' 
                       f'✅ {mc} / {ps}</span></td>')
        elif mc > 0:
            mc_cell = (f'<td style="padding:6px 10px;font-weight:bold;">' 
                       f'<span style="background:#f39c12;color:white;padding:2px 7px;border-radius:3px;">' 
                       f'⚠️ {mc} / {ps}</span></td>')
        else:
            mc_cell = (f'<td style="padding:6px 10px;font-weight:bold;">' 
                       f'<span style="background:#e74c3c;color:white;padding:2px 7px;border-radius:3px;">' 
                       f'❌ 0 / {ps}</span></td>')
        report_link = f'./{_rep_prefix}/{report_fname}'
        fname_esc   = html.escape(fname)
        file_rows += (
            f'<tr><td style="padding:6px 10px;font-family:monospace;font-size:12px;">' +
            f'<a href="{report_link}" style="color:#2471a3;text-decoration:none;font-weight:bold;" ' +
            f'title="Open compliance report for {fname_esc}">{fname_esc}</a>' +
            f'<div style="font-size:10px;color:#aaa;margin-top:1px;">→ open report</div></td>'
            + sw_cell +
            f'<td style="padding:6px 10px;color:{vcol};font-weight:bold;">{verdict}</td>'
            f'<td style="padding:6px 10px;color:#27ae60;">{counts["PASS"]}</td>'
            f'<td style="padding:6px 10px;color:#e74c3c;">{counts["FAIL"]}</td>'
            f'<td style="padding:6px 10px;color:#f39c12;">{counts["PASS*"]}</td>'
            + mc_cell +
            f'<td style="padding:6px 10px;color:#95a5a6;">{counts["SKIPPED"]}</td></tr>'
        )

    # ── v1.49: Per-file drill-down matrix ────────────────────────────────────────
    # Rows = files, columns = Req 3–37, cells = coloured status badges.
    # Pure HTML table with inline CSS; no JavaScript required.
    # Skip Req 1 and 2 (always SKIPPED — not useful in the matrix view).
    _matrix_req_nums = [r for r in REQUIREMENTS if r >= 3]
    _matrix_hdr_cells = "".join(
        f'<th style="padding:4px 3px;font-size:10px;text-align:center;'
        f'background:#2c3e50;color:white;white-space:nowrap;"'
        f' title="{html.escape(REQUIREMENTS[r][0])}">{r}</th>'
        for r in _matrix_req_nums
    )
    _MATRIX_STATUS_BG  = {"PASS": "#27ae60", "FAIL": "#e74c3c",
                           "PASS*": "#f39c12", "SKIPPED": "#bdc3c7"}
    _MATRIX_STATUS_TXT = {"PASS": "P",  "FAIL": "F",
                          "PASS*": "P*", "SKIPPED": "—"}
    _matrix_body_rows = []
    for fname, fres, frpt in all_results:
        _counts_m, _, _verdict_m, _vcol_m = score_results(fres)
        _cells = ""
        for rn in _matrix_req_nums:
            _rv = fres.get(rn, {})
            _st = _rv.get("status", "SKIPPED") if _rv else "SKIPPED"
            _detail_snippet = html.escape(str(_rv.get("detail", ""))[:120]) if _rv else ""
            _bg = _MATRIX_STATUS_BG.get(_st, "#ecf0f1")
            _lbl = _MATRIX_STATUS_TXT.get(_st, _st[:2])
            _cells += (
                f'<td style="padding:3px;text-align:center;" '
                f'title="Req {rn}: {_st}&#10;{_detail_snippet}">'
                f'<span style="display:inline-block;width:22px;height:18px;'
                f'line-height:18px;font-size:9px;font-weight:bold;'
                f'background:{_bg};color:white;border-radius:3px;">'
                f'{_lbl}</span></td>'
            )
        _fname_short = html.escape(fname[:50])
        _flink = f'./{_rep_prefix}/{html.escape(frpt)}'
        _matrix_body_rows.append(
            f'<tr>'
            f'<td style="padding:4px 6px;font-family:monospace;font-size:11px;white-space:nowrap;">'
            f'<a href="{_flink}" style="color:#2471a3;text-decoration:none;">{_fname_short}</a>'
            f'</td>'
            + _cells +
            f'</tr>'
        )
    matrix_html = f"""
<div class="section-title">🔍 Per-File Requirement Matrix (Req 3–37)</div>
<div class="note" style="font-size:12px;">
  Each cell shows the automated verdict for that file × requirement combination.
  <strong style="color:#27ae60;">P</strong>=PASS &nbsp;
  <strong style="color:#e74c3c;">F</strong>=FAIL &nbsp;
  <strong style="color:#f39c12;">P*</strong>=PASS* (partial) &nbsp;
  <strong style="color:#7f8c8d;">—</strong>=SKIPPED.
  Hover over a cell for a brief detail snippet.
</div>
<div style="overflow-x:auto;">
<table style="width:auto;min-width:100%;font-size:11px;">
  <thead>
    <tr>
      <th style="padding:4px 6px;background:#2c3e50;color:white;font-size:11px;
                 text-align:left;white-space:nowrap;">File</th>
      {_matrix_hdr_cells}
    </tr>
  </thead>
  <tbody>
    {"".join(_matrix_body_rows)}
  </tbody>
</table>
</div>
"""

    html_str = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>DGIWG Integrated Validation Report — {html.escape(str(n_files))} GeoPackage(s)</title>
<style>
  body {{ font-family: Arial, sans-serif; margin:0; padding:0; background:#f0f2f5; color:#2c3e50; }}
  .header {{ background:linear-gradient(135deg,#1a252f,#2c3e50,#34495e); color:white; padding:32px 40px; }}
  .header h1 {{ margin:0 0 6px; font-size:24px; }}
  .header p  {{ margin:0; opacity:.7; font-size:14px; }}
  .content {{ padding:24px 40px; }}
  .section-title {{ font-size:18px;font-weight:bold;color:#2c3e50;
    border-bottom:3px solid #3498db;padding-bottom:8px;margin:28px 0 16px; }}
  table {{ width:100%;border-collapse:collapse;background:white;
    box-shadow:0 1px 6px rgba(0,0,0,.08);border-radius:8px;overflow:hidden; }}
  th {{ background:#2c3e50;color:white;padding:10px 8px;text-align:left;
    font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.5px; }}
  td {{ border-bottom:1px solid #ecf0f1;vertical-align:top; }}
  tr:hover {{ filter:brightness(.97); }}
  .note {{ background:#fef9e7;border-left:4px solid #f39c12;padding:12px 16px;
    margin:16px 0;border-radius:4px;font-size:13px; }}
  .footer {{ text-align:center;padding:20px;color:#95a5a6;font-size:12px;
    border-top:1px solid #ddd;margin-top:32px; }}
</style>
</head>
<body>
<div class="header">
  <h1>🛡 DGIWG GeoPackage — Integrated Validation Report</h1>
  <p style="margin-top:6px;">{n_files} GeoPackage(s) validated</p>
</div>

<div class="content">

<div class="note">
  <strong>How to read this table:</strong>
  <b>Validator Disputes</b> = how many GPKGs got FAIL from this script's automated checks.
  <b>Cross-Checks &amp; Diagnosis</b> = probable root cause for each FAIL/PASS* result (by source software),
  plus a collapsible auditor cross-check panel with known blind spots and caveats.
  <b>PASS* &amp; Manual Verification</b> = automated PASS* confirmation count, plus expandable manual inspection notes.
  <b>Confidence: High</b> = fully automated and confirmed; <b>Medium</b> = partial check or single known gap;
  <b>Low</b> = known validator bug or cannot be automated.
</div>

<div class="section-title">📁 Per-File Summary</div>
<table>
  <thead><tr>
    <th>File</th><th>Source Software</th><th>Verdict</th><th>PASS</th><th>FAIL</th><th>PASS*</th><th>PASS* (Manual Confirmed)</th><th>SKIPPED</th>
  </tr></thead>
  <tbody>{file_rows}</tbody>
</table>

{matrix_html}

<div class="section-title">📊 Requirement Rollup — DGIWG Validator (Req 3–37)</div>
<table>
  <thead><tr>
    <th style="width:38px;">Req</th>
    <th style="width:145px;">Requirement</th>
    <th style="width:40px;">Type</th>
    <th style="width:155px;">Validator Disputes</th>
    <th style="width:230px;">Cross-Checks &amp; Diagnosis</th>
    <th style="width:160px;">PASS* &amp; Manual Verification</th>
    <th style="width:115px;">Confidence Level</th>
  </tr></thead>
  <tbody>{"".join(rows_html)}</tbody>
</table>

<div class="section-title">📌 Legend</div>
<table>
  <thead><tr><th>Term</th><th>Definition</th></tr></thead>
  <tbody>
    <tr><td style="padding:8px;font-weight:bold;">Validator Disputes</td>
        <td style="padding:8px;">Number of GeoPackages where this script returned FAIL for this requirement, out of total applicable GPKGs (non-SKIPPED)</td></tr>
    <tr><td style="padding:8px;font-weight:bold;">Cross-Checks &amp; Diagnosis</td>
        <td style="padding:8px;">
          <strong>Probable Cause</strong> — the likely root cause for any FAIL or PASS* result,
          broken down by source software (QGIS/GDAL vs ArcGIS) where relevant.<br>
          <strong>▶ Auditor cross-checks</strong> (expandable) — known validator blind spots,
          misimplementations, or false-result risks for this requirement. Count shows how many
          applicable GPKGs were affected (FAIL or PASS* only).
        </td></tr>
    <tr><td style="padding:8px;font-weight:bold;">PASS* &amp; Manual Verification</td>
        <td style="padding:8px;">
          <strong>PASS* Manual Confirmed</strong> — how many of this requirement's PASS* results
          were subsequently confirmed by hands-on manual inspection.<br>
          <strong>▶ Manual Verification</strong> (expandable) — findings and notes from
          hands-on session analysis of the GeoPackage database.
        </td></tr>
    <tr><td style="padding:8px;font-weight:bold;color:#27ae60;">High Confidence</td>
        <td style="padding:8px;">Check fully implements the ATS requirement, no known bugs, result confirmed manually</td></tr>
    <tr><td style="padding:8px;font-weight:bold;color:#f39c12;">Medium Confidence</td>
        <td style="padding:8px;">Partial check (PASS*) or one known gap — result is likely correct but not fully verified</td></tr>
    <tr><td style="padding:8px;font-weight:bold;color:#e74c3c;">Low Confidence</td>
        <td style="padding:8px;">Known validator bug, logic error, or requirement cannot be automated — treat result with caution</td></tr>
    <tr><td style="padding:8px;font-weight:bold;">PASS*</td>
        <td style="padding:8px;"><strong>Partial automated validation</strong> — structural or presence checks passed but content not fully verified. Two distinct causes: (1) the check is technically possible but this script only does part of it (e.g. WKT presence without content validation); (2) the check cannot be fully automated at all (e.g. Req 6, 13 content, 15 WKT structure, 17 epoch WKT, 18 XML values). See the ⚠️ section above for the full list of non-automatable requirements.</td></tr>
    <tr><td style="padding:8px;font-weight:bold;">SKIPPED</td>
        <td style="padding:8px;">Requirement not applicable to this file (e.g. vector CRS check on a gridded-only file), OR the check was deliberately not automated because it requires external context (Req 6: product profile).</td></tr>
  </tbody>
</table>

</div>
<div class="footer">
  DGIWG GeoPackage — Integrated Validation Report &nbsp;|&nbsp;
  Req 1–2 (OGC Base) require OGC CITE TeamEngine and are not automated by this script.
  <div style="margin-top:8px;font-size:12px;font-weight:bold;color:#2c3e50 !important;letter-spacing:0.3px;">Created by MCpl Son E.S. &nbsp;|&nbsp; euisoo.son@forces.gc.ca</div>
  <div style="margin-top:2px;font-size:11px;color:#7f8c8d !important;">&copy; MCE/T&amp;E &mdash; Mapping and Charting Establishment / Geomatics Engineering Trials &amp; Evaluation Support Section (GETESS)</div>
</div>
</body></html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_str)
    print(f"  Rollup HTML written: {output_path}")



def _write_rollup(
    all_results: list[tuple[str, dict, str]],
    out_dir: str,
    reports_dir: str | None = None,
) -> None:
    """Write the rollup HTML and CSV summary reports.

    reports_dir — directory where per-file HTML reports were written.
                  When None (default), assumes reports/ is a subdirectory of
                  out_dir (standard layout). When supplied, the relative path
                  from out_dir to reports_dir is computed and passed to
                  render_rollup_html() so per-file links resolve. (v1.50 fix)
    """
   
    # Compute relative path from out_dir to reports_dir for HTML link resolution
    # (v1.50 fix: per-file report links in rollup HTML were broken when --output-dir used)
    if reports_dir is None:
        reports_dir = os.path.join(out_dir, "reports")

    try:
        reports_relpath = os.path.relpath(reports_dir, out_dir)
    except ValueError:
        # os.path.relpath raises ValueError on Windows when paths are on different drives
        reports_relpath = "reports"

    # ── Rollup HTML ───────────────────────────────────────────────────────────
    html_path = os.path.join(out_dir, "DGIWG_GPKG_FINAL_REPORT.html")
    render_rollup_html(all_results, html_path, reports_relpath=reports_relpath)

    # ── Rollup CSV ────────────────────────────────────────────────────────────
    import csv as _csv_mod
    csv_path = os.path.join(out_dir, "DGIWG_GPKG_FINAL_REPORT.csv")
    rollup, _ = aggregate_rollup(all_results)

    with open(csv_path, "w", newline="", encoding="utf-8") as _cf:
        _writer = _csv_mod.writer(_cf)
        _writer.writerow([
            "Req", "Requirement", "Compliance Type",
            "Applicable GPKGs", "Validator Disputes", "Auditor Disputes",
            "PASS* Count", "PASS* Manual Confirmed", "Dispute Rate %",
        ])
        for req_num, (name, _uri, compliance) in REQUIREMENTS.items():
            r          = rollup[req_num]
            applicable = r["applicable"]
            v_disp     = r["validator_disputes"]
            a_disp     = r["auditor_disputes"]
            ps_count   = r["passstar"]
            mc_count   = r["manual_confirmed"]
            rate       = "N/A" if applicable == 0 else round(v_disp / applicable * 100)
            _writer.writerow([
                req_num, name, compliance,
                applicable, v_disp, a_disp,
                ps_count, mc_count, rate,
            ])

    print(f"  Rollup CSV  written: {csv_path}")


if __name__ == '__main__':
    main()
