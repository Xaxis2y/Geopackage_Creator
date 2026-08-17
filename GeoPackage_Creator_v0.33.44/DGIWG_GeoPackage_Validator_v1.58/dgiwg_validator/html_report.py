# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Per-file HTML report rendering for the DGIWG validator (v1.58)."""
import os
import sys
import html
import json
import re
import datetime
from .constants import (
    REQUIREMENTS, STATUS_HTML_COLOR, STATUS_HTML_BG, STATUS_ICON,
    MANUAL_GUIDANCE, CONFIDENCE_COLOR, CONFIDENCE_BG, TILE_SIZE, LIKELY_CAUSE,
    REQ_ROLLUP_META, OGC_PIXEL_Z0, OGC_PIXEL_TOL,
)
from .forensics import _render_forensic_section
from .utils import score_results
def _summarise_mc(req_num, confirmed, total, note):
    """
    Return (summary_line, detail_text) for the Manual Confirmed cell.
    summary_line = short human-readable verdict sentence.
    detail_text  = the full diagnostic note, shown collapsed.
    """
    if total is None or total == 0:
        # Still return note as the summary so the cell shows diagnostic text, not silence
        return note, ""

    # ── Per-requirement summary templates ─────────────────────────────────────
    PASS_SUMMARY = {
        3:  f"All {total} mandatory extension(s) per Table 8; scopes valid ✓",
        4:  f"All {total} extension row(s) reference a table_name ✓",
        7:  f"All {total} tile CRS WKT EPSG codes match srs_id ✓",
        8:  f"All {total} OGC-verifiable tile matrix set(s) match scale denominators ✓",
        9:  f"All {total} 2D vector table(s) use DGIWG-allowed CRS (Table 10) ✓",
        10: f"All {total} 3D vector table(s) use DGIWG-allowed CRS (Table 10) ✓",
        11: f"All {total} 2D gridded table(s) use DGIWG-allowed CRS ✓",
        12: f"All {total} 3D gridded table(s) use DGIWG-allowed CRS ✓",
        13: f"All {total} CRS WKT entry(s) match EPSG codes ✓",
        14: f"All {total} geometry column(s) have valid compound CRS usage ✓",
        18: f"All {total} DMF metadata row(s) have correct URI and ISO 19115 elements ✓",
        19: f"All {total} metadata document(s) are well-formed XML ✓",
        20: f"geopackage-scope reference row found ✓",
        21: f"All {total} partial metadata reference(s) resolve correctly ✓",
        22: f"All {total} metadata row(s) have md_scope='series' ✓",
        24: f"All {total} CRS entry(s) pass Table 37 field checks ✓",
        25: f"All {total} declared zoom level(s) have tile_width/height=256 in metadata ✓",
        26: f"All {total} declared zoom level(s) Pillow-verified 256×256 (6 checks) ✓",
        27: f"All {total} tile set(s) have factor=2.0 at all zoom-level transitions ✓",
        28: f"All {total} multi-zoom set(s) have tiles at every declared zoom level ✓",
        29: f"All {total} single-zoom set(s) have 256x256 tile dimensions ✓",
        30: f"All {total} gpkg_contents bbox(es) fall within tile_matrix_set bbox ✓",
        31: f"All {total} tile table(s) have linked tile-layer metadata (md_scope='tile'/'model') ✓",
        32: f"All {total} feature table(s) have linked feature-layer metadata (md_scope='feature'/'featureType') ✓",
        15: f"All {total} compound CRS WKT entry(s) have correct GEOGCRS/PROJCRS + VERTCRS nesting ✓",
        16: f"All {total} gridded compound CRS WKT entry(s) in definition_12_063 have correct structure ✓",
        17: f"All {total} gridded CRS entry(s) have DYNAMIC[FRAMEEPOCH[…]] matching epoch column ✓",
        23: f"All {total} product-partial metadata row(s) have valid md_scope and XML content ✓",
        33: f"All {total} gridded coverage ancillary row(s) fully populated ✓",
        34: f"All {total} gridded elevation/height layer(s) have field_name='Height'/'Elevation' ✓",
        35: f"All {total} gridded elevation/height layer(s) have grid_cell_encoding='grid-value-is-center' ✓",
        36: f"All {total} gridded tile set(s) have factor=2.0 at all zoom-level transitions ✓",
        37: f"All {total} reference_scope/md_scope pairing(s) valid per Table 36 ✓",
    }
    FAIL_SUMMARY = {
        3:  f"0/{total} mandatory extension(s) registered with table_name — missing per Table 8",
        7:  f"CRS WKT EPSG mismatch in {total - confirmed} of {total} entry(s)",
        8:  f"{total - confirmed}/{total} OGC-verifiable tile set(s) have scale denominator mismatch",
        9:  f"0/{total} 2D vector table(s) use DGIWG-allowed CRS — srs_id not in Table 10 {{4326}}",
        10: f"0/{total} 3D vector table(s) use DGIWG-allowed CRS — srs_id not in Table 10 {{4979, 9518}}",
        11: f"0/{total} 2D gridded table(s) use DGIWG-allowed CRS",
        12: f"0/{total} 3D gridded table(s) use DGIWG-allowed CRS",
        14: f"0/{total} geometry column(s) have valid compound CRS usage — COMPOUNDCRS used with z=0",
        18: f"0/{total} metadata rows have a DGIWG DMF URI — file uses QGIS/GDAL metadata instead",
        19: f"{total - confirmed} metadata document(s) failed XML well-formedness check",
        20: f"No reference_scope='geopackage' row — only table/row-scope references present",
        22: f"0/{total} rows have md_scope='series' — all rows are md_scope='dataset'",
        24: f"{total - confirmed}/{total} CRS entries missing organisation=EPSG or empty description",
        25: f"{total - confirmed} zoom level(s) do not declare 256×256 in metadata",
        26: f"{total - confirmed}/{total} zoom levels failed Pillow check — see detail for which checks failed",
        27: f"{total - confirmed}/{total} tile set(s) have non-2.0 zoom factor ✗",
        28: f"0/{total} multi-zoom set(s) fully populated — all have empty declared zoom levels",
        15: f"0/{total} compound CRS WKT entry(s) have correct GEOGCRS/PROJCRS + VERTCRS structure",
        16: f"0/{total} gridded compound CRS WKT entry(s) have correct definition_12_063 structure",
        17: f"0/{total} gridded CRS entry(s) have DYNAMIC[FRAMEEPOCH[…]] matching epoch column",
        23: f"0/{total} product-partial metadata row(s) valid — md_scope or XML content incorrect",
        31: f"0/{total} metadata rows have md_scope='tile' or 'model' — only 'dataset' scope present",
        32: f"0/{total} metadata rows have md_scope='feature'/'featureType' — only 'dataset' scope present",
        33: f"0/{total} gridded coverage ancillary row(s) have all required columns populated",
        34: f"0/{total} gridded elevation/height layer(s) have correct field_name — expected Height or Elevation",
        35: f"0/{total} gridded elevation/height layer(s) have correct grid_cell_encoding — expected grid-value-is-center",
        36: f"0/{total} gridded tile set(s) have factor=2.0 at zoom transitions — non-2.0 ratios found",
        37: f"{total - confirmed}/{total} reference_scope/md_scope pairings invalid per Table 36",
    }
    PARTIAL_SUMMARY = {
        3:  f"{confirmed}/{total} mandatory extension(s) registered — {total-confirmed} missing table_name or not registered",
        7:  f"{confirmed}/{total} CRS WKT EPSG codes match — {total-confirmed} mismatch(es)",
        8:  f"{confirmed}/{total} OGC-verifiable tile set(s) match scale denominators — {total-confirmed} mismatch(es)",
        9:  f"{confirmed}/{total} 2D vector table(s) use DGIWG-allowed CRS — {total-confirmed} use disallowed CRS",
        10: f"{confirmed}/{total} 3D vector table(s) use DGIWG-allowed CRS — {total-confirmed} use disallowed CRS",
        11: f"{confirmed}/{total} 2D gridded table(s) use DGIWG-allowed CRS — {total-confirmed} do not",
        12: f"{confirmed}/{total} 3D gridded table(s) use DGIWG-allowed CRS — {total-confirmed} do not",
        13: f"{confirmed}/{total} CRS WKT entries match EPSG — {total-confirmed} mismatch(es)",
        14: f"{confirmed}/{total} geometry column(s) have valid compound CRS usage — {total-confirmed} violation(s)",
        18: f"{confirmed}/{total} DMF rows have correct URI and ISO 19115 elements",
        24: f"{confirmed}/{total} CRS entries pass Table 37 — remainder missing description or org≠EPSG",
        25: f"{confirmed}/{total} zoom levels declare 256×256 — {total-confirmed} do not",
        26: f"{confirmed}/{total} zoom levels Pillow-verified — {total-confirmed} have no tile data or format issues",
        27: f"{confirmed}/{total} tile set(s) have factor=2.0 — {total-confirmed} have non-2.0 transitions",
        15: f"{confirmed}/{total} compound CRS WKT entry(s) have correct structure — {total-confirmed} fail WKT2 nesting check",
        16: f"{confirmed}/{total} gridded compound CRS WKT entry(s) valid — {total-confirmed} fail definition_12_063 structure check",
        17: f"{confirmed}/{total} gridded CRS entry(s) have FRAMEEPOCH match — {total-confirmed} have mismatch or missing epoch",
        23: f"{confirmed}/{total} product-partial metadata row(s) valid — {total-confirmed} have scope or XML issues",
        28: f"{confirmed}/{total} multi-zoom sets fully populated — {total-confirmed} have empty zoom levels",
        29: f"{confirmed}/{total} single-zoom sets have valid tile dimensions",
        33: f"{confirmed}/{total} gridded coverage ancillary row(s) fully populated — {total-confirmed} missing column(s)",
        34: f"{confirmed}/{total} gridded elevation/height layer(s) have correct field_name",
        35: f"{confirmed}/{total} gridded elevation/height layer(s) have correct grid_cell_encoding",
        36: f"{confirmed}/{total} gridded tile set(s) have factor=2.0 — {total-confirmed} have non-2.0 transitions",
        37: f"{confirmed}/{total} pairings valid per Table 36",
    }

    if confirmed == total:
        summary = PASS_SUMMARY.get(req_num, f"{confirmed}/{total} checks passed ✓")
    elif confirmed == 0:
        summary = FAIL_SUMMARY.get(req_num, f"0/{total} checks passed — see detail")
    else:
        summary = PARTIAL_SUMMARY.get(req_num,
                  f"{confirmed}/{total} passed — {total-confirmed} issue(s) found")

    return summary, note



def _render_internet_checks_html(ic):
    """Render the internet checks dict as an HTML table."""
    LABELS = {
        "uri":   ("🔗 URI Reachability",          "Req 18/19 — md_standard_uri values are live and reachable"),
        "epsg":  ("🗺 EPSG Registry",              "Req 7/9/10/11/13 — srs_id names match official EPSG registry"),
        "scale": ("📐 OGC Scale Denominators",     "Req 8 — pixel sizes match OGC TileMatrixSet definitions"),
        "dmf":   ("📄 ISO 19115 / DMF XML",        "Req 18 — metadata XML has required ISO 19115 elements"),
    }
    if not ic:
        return '<p style="color:#666;font-style:italic;">No internet checks available.</p>'
    rows = []
    for key, (title, description) in LABELS.items():
        val = ic.get(key, (None, None, "Not run"))
        confirmed, total, note = val[0], val[1], val[2]
        if confirmed is None:
            # No internet, network error, or offline mode
            badge_color = "#7f8c8d"
            # v1.57 (#3): distinguish "network broken" from "offline/no internet"
            badge_text  = ("⚠ NETWORK ERROR"
                           if str(note).startswith("NETWORK ERROR")
                           else "⚠ NO INTERNET")
            conf_cell   = "—"
        elif total == 0:
            badge_color = "#7f8c8d"
            badge_text  = "N/A"
            conf_cell   = "—"
        elif confirmed == total:
            badge_color = "#27ae60"
            badge_text  = "✅ PASS"
            conf_cell   = f"{confirmed} / {total}"
        elif confirmed > 0:
            badge_color = "#f39c12"
            badge_text  = "⚠ PARTIAL"
            conf_cell   = f"{confirmed} / {total}"
        else:
            badge_color = "#e74c3c"
            badge_text  = "❌ FAIL"
            conf_cell   = f"0 / {total}"
        rows.append(
            f'<tr>'
            f'<td style="padding:8px 12px;font-weight:bold;white-space:nowrap;">{title}</td>'
            f'<td style="padding:8px 12px;color:#555;font-size:12px;">{description}</td>'
            f'<td style="padding:8px 12px;text-align:center;">'
            f'<span style="background:{badge_color};color:white;padding:3px 8px;'
            f'border-radius:4px;font-weight:bold;font-size:12px;">{badge_text}</span></td>'
            f'<td style="padding:8px 12px;text-align:center;font-weight:bold;">{conf_cell}</td>'
            f'<td style="padding:8px 12px;font-size:12px;color:#444;">{html.escape(str(note))}</td>'
            f'</tr>'
        )
    return (
        '<p style="font-size:13px;color:#555;margin-bottom:12px;">'
        'These checks require internet access. When offline, the reason is stated in the Details column.</p>'
        '<table><thead><tr>'
        '<th style="width:200px;">Check</th>'
        '<th style="width:280px;">Covers</th>'
        '<th style="width:120px;">Result</th>'
        '<th style="width:100px;">Confirmed</th>'
        '<th>Details</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def _build_likely_cause_cell(req_num: int, status: str, software: str) -> str:
    """
    Build the HTML cell content for the Likely Cause column.
    Returns a styled div for FAIL/PASS*, or a greyed dash for PASS/SKIPPED.
    """
    cause = _get_likely_cause(req_num, status, software)
    if not cause:
        return '<span style="color:#ccc;font-size:12px;">—</span>'
    if status == "FAIL":
        icon       = "🔴"
        bg_color   = "#fff5f5"
        border_col = "#e74c3c"
        label_col  = "#c0392b"
        label      = "Probable cause"
    else:  # PASS*
        icon       = "🔎"
        bg_color   = "#fffbf0"
        border_col = "#f39c12"
        label_col  = "#9a6500"
        label      = "What to verify"
    # Append tool attribution for FAIL rows
    tool_note = ""
    if status == "FAIL" and software != "UNKNOWN":
        tool_note = (
            f'<div style="font-size:10px;color:#999;margin-top:4px;">'
            f'Based on detected source: {software}</div>'
        )
    return (
        f'<div style="background:{bg_color};border-left:3px solid {border_col};'
        f'border-radius:4px;padding:6px 8px;font-size:11px;">'
        f'<div style="font-weight:bold;color:{label_col};margin-bottom:3px;">'
        f'{icon} {label}</div>'
        f'<div style="color:#444;line-height:1.5;">{cause}</div>'
        f'{tool_note}'
        f'</div>'
    )


def render_html(
    profile: dict[str, str],
    results: dict[int, dict[str, object]],
    output_path: str,
) -> None:
    counts, total, verdict, verdict_color = score_results(results)
    # Count how many PASS* were fully confirmed by manual check
    manual_confirmed = sum(
        1 for k, v in results.items()
        if k not in ("__internet__", "__forensic__", "__forensic_checks__", "__cascade_note__") and v["status"] == "PASS*" and v.get("manual") and v["manual"][0] == v["manual"][1] > 0
    )
    manual_partial = sum(
        1 for k, v in results.items()
        if k not in ("__internet__", "__forensic__", "__forensic_checks__", "__cascade_note__") and v["status"] == "PASS*" and v.get("manual") and 0 < v["manual"][0] < v["manual"][1]
    )

    rows_html = []
    # Extract detected software early so it's available in the row loop for likely-cause diagnosis
    _detected_sw = results.get("__forensic__", {}).get("software", "UNKNOWN")
    for req_num, (name, uri, compliance) in REQUIREMENTS.items():
        r = results[req_num]
        status = r["status"]
        detail = r["detail"]
        manual = r.get("manual")   # (confirmed, total, note) or None
        meta        = REQ_ROLLUP_META.get(req_num, {})
        conf        = meta.get("confidence", "Medium")
        conf_reason = meta.get("confidence_reason", "")
        auditor_chks = meta.get("auditor_checks", [])
        # SKIPPED = check did not run → confidence is always Low, no reason needed
        if status == "SKIPPED":
            conf        = "Low"
            conf_reason = ""
            auditor_chks = []
        # FAIL = requirement not met → confidence is always Low, no reason needed
        if status == "FAIL":
            conf        = "Low"
            conf_reason = ""
            auditor_chks = []
        icon = STATUS_ICON.get(status, status)
        color = STATUS_HTML_COLOR.get(status, "#333")
        bg    = STATUS_HTML_BG.get(status, "#fff")
        comp_badge = (
            f'<span style="background:#2c3e50;color:white;padding:2px 6px;'
            f'border-radius:3px;font-size:11px;">{compliance}</span>'
        )
        status_badge = (
            f'<span style="background:{color};color:white;padding:3px 8px;'
            f'border-radius:4px;font-weight:bold;font-size:12px;">{icon} {status}</span>'
        )
        # Confidence badge for this requirement
        conf_color = {"High": "#27ae60", "Medium": "#f39c12", "Low": "#e74c3c"}.get(conf, "#95a5a6")
        conf_badge = (
            f'<span style="background:{conf_color};color:white;padding:2px 7px;'
            f'border-radius:3px;font-size:11px;font-weight:bold;">{conf}</span>'
        )
        if conf_reason or auditor_chks:
            auditor_lines = "".join(
                f'<li style="margin:2px 0;">{c}</li>' for c in auditor_chks
            ) if auditor_chks else ""
            conf_detail = (
                f'<details style="margin-top:4px;">'
                f'<summary style="font-size:10px;color:#888;cursor:pointer;">What is checked</summary>'
                f'<div style="font-size:10px;color:#555;margin-top:3px;">'
                + (f'<ul style="margin:0;padding-left:14px;">{auditor_lines}</ul>' if auditor_lines else "")
                + (f'<div style="margin-top:3px;color:#777;font-style:italic;">{conf_reason}</div>' if conf_reason else "")
                + f'</div></details>'
            )
        else:
            conf_detail = ""
        confidence_cell = f'{conf_badge}{conf_detail}'
        # Build Manual Confirmed cell
        if status == "PASS*" and manual is not None:
            # MC tuple is (confirmed, total, note) or (confirmed, total, note, unverifiable)
            # unverifiable=True → MC N/A because check genuinely can't verify → force Low
            # unverifiable=False/absent → MC N/A because data type not in this file → keep static conf
            confirmed, total, mnote = manual[0], manual[1], manual[2]
            unverifiable = manual[3] if len(manual) > 3 else False
            mc_summary, mc_detail = _summarise_mc(req_num, confirmed, total, mnote)
            _mg = MANUAL_GUIDANCE.get(req_num)
            if _mg:
                _what, _how, _sql = _mg
                detail_html = (
                    f'<div style="background:#f0f7ff;border:1px solid #c3d9f7;'
                    f'border-radius:5px;padding:8px 10px;margin-top:6px;">'
                    f'<details>'
                    f'<summary style="font-size:11px;color:#2471a3;cursor:pointer;font-weight:bold;">'
                    f'&#128203; Manual Confirmation</summary>'
                    f'<div style="font-size:11px;color:#444;margin-top:6px;">'
                    f'<strong>What to check:</strong><br>{_what}<br><br>'
                    f'<strong>How (DB Browser):</strong><br>{_how}<br><br>'
                    f'<strong>SQL query:</strong><br>'
                    f'<code style="background:#e8f0fe;padding:3px 6px;border-radius:3px;'
                    f'display:block;margin-top:3px;word-break:break-all;font-size:10px;">{_sql}</code>'
                    f'</div></details></div>'
                )
            else:
                detail_html = ""
            if total is None or total == 0:
                # MC is N/A — only force Low when genuinely unverifiable
                if unverifiable:
                    conf        = "Low"
                    conf_reason = ""
                    auditor_chks = []
                    conf_color  = "#e74c3c"
                    conf_badge  = (
                        f'<span style="background:{conf_color};color:white;padding:2px 7px;'
                        f'border-radius:3px;font-size:11px;font-weight:bold;">Low</span>'
                    )
                    conf_detail = ""
                    confidence_cell = conf_badge
                # Show diagnostic explanation even when total==0 (N/A with reason)
                na_note = mnote if mnote else "Not applicable to this file"
                mc_badge = (
                    f'<span style="background:#7f8c8d;color:white;padding:3px 8px;'
                    f'border-radius:4px;font-size:12px;font-weight:bold;">N/A</span>'
                    f'<details style="margin-top:4px;">'
                    f'<summary style="font-size:10px;color:#888;cursor:pointer;">Why N/A — show detail</summary>'
                    f'<div style="font-size:10px;color:#555;margin-top:3px;word-break:break-word;">{na_note}</div>'
                    f'</details>'
                )
            elif confirmed == total:
                mc_badge = (
                    f'<span style="background:#27ae60;color:white;padding:3px 8px;'
                    f'border-radius:4px;font-weight:bold;font-size:12px;">'
                    f'✅ {confirmed} / {total}</span>'
                    f'<div style="font-size:11px;color:#2c7a3e;margin-top:4px;font-weight:bold;">{mc_summary}</div>'
                    f'{detail_html}'
                )
            elif confirmed > 0:
                mc_badge = (
                    f'<span style="background:#f39c12;color:white;padding:3px 8px;'
                    f'border-radius:4px;font-weight:bold;font-size:12px;">'
                    f'⚠️ {confirmed} / {total}</span>'
                    f'<div style="font-size:11px;color:#b7770d;margin-top:4px;font-weight:bold;">{mc_summary}</div>'
                    f'{detail_html}'
                )
            else:
                # MC confirmed == 0 → requirement partially checked but nothing verified → Low
                conf        = "Low"
                conf_reason = ""
                auditor_chks = []
                conf_color  = "#e74c3c"
                conf_badge  = (
                    f'<span style="background:{conf_color};color:white;padding:2px 7px;'
                    f'border-radius:3px;font-size:11px;font-weight:bold;">Low</span>'
                )
                conf_detail = ""
                confidence_cell = conf_badge
                mc_badge = (
                    f'<span style="background:#e74c3c;color:white;padding:3px 8px;'
                    f'border-radius:4px;font-weight:bold;font-size:12px;">'
                    f'❌ {confirmed} / {total}</span>'
                    f'<div style="font-size:11px;color:#c0392b;margin-top:4px;font-weight:bold;">{mc_summary}</div>'
                    f'{detail_html}'
                )
        elif status in ("FAIL", "SKIPPED"):
            _mg2 = MANUAL_GUIDANCE.get(req_num)
            if _mg2:
                _what2, _how2, _sql2 = _mg2
                mc_badge = (
                    f'<div style="background:#f0f7ff;border:1px solid #c3d9f7;'
                    f'border-radius:5px;padding:8px 10px;">'
                    f'<details>'
                    f'<summary style="font-size:11px;color:#2471a3;cursor:pointer;font-weight:bold;">'
                    f'&#128203; Manual Confirmation</summary>'
                    f'<div style="font-size:11px;color:#444;margin-top:6px;">'
                    f'<strong>What to check:</strong><br>{_what2}<br><br>'
                    f'<strong>How (DB Browser):</strong><br>{_how2}<br><br>'
                    f'<strong>SQL query:</strong><br>'
                    f'<code style="background:#e8f0fe;padding:3px 6px;border-radius:3px;'
                    f'display:block;margin-top:3px;word-break:break-all;font-size:10px;">{_sql2}</code>'
                    f'</div></details></div>'
                )
            else:
                mc_badge = f'<span style="color:#bbb;font-size:12px;">—</span>'
        elif status in ("PASS", "N/A"):
            mc_badge = f'<span style="color:#bbb;font-size:12px;">—</span>'
        else:
            mc_badge = f'<span style="color:#bbb;font-size:12px;">—</span>'

        # Split detail into main content and optional software hint
        _HINT_MARKER = "🔬 SOFTWARE AUDIT HINT"
        if _HINT_MARKER in detail:
            detail_main, hint_part = detail.split(_HINT_MARKER, 1)
            detail_main = html.escape(detail_main.strip()).replace("\n", "<br>")
            hint_part   = html.escape(hint_part.strip()).replace("\n", "<br>")
            sw_label    = hint_part.split("]", 1)[0].replace("[", "").strip() if hint_part.startswith("[") else ""
            hint_body   = hint_part.split("]", 1)[1].strip() if "]" in hint_part else hint_part
            hint_color  = {"QGIS/GDAL": "#1a6b3c", "ArcGIS": "#1a3a6b", "UNKNOWN": "#6b4a1a"}.get(sw_label, "#444")
            hint_bg     = {"QGIS/GDAL": "#eafaf1", "ArcGIS": "#eaf0fb", "UNKNOWN": "#fdf6e3"}.get(sw_label, "#f8f9fa")
            # Truncate main detail if long
            _TRUNC = 160
            if len(detail_main) > _TRUNC:
                detail_main_display = (
                    f'<details><summary style="cursor:pointer;font-size:12px;color:#444;">'
                    f'{detail_main[:_TRUNC]}… <span style="color:#888;font-size:10px;">(expand)</span>'
                    f'</summary><div style="margin-top:4px;">{detail_main}</div></details>'
                )
            else:
                detail_main_display = f'<div style="font-size:12px;color:#444;">{detail_main}</div>'
            detail_cell = (
                detail_main_display +
                f'<details style="margin-top:6px;">'
                f'<summary style="font-size:11px;font-weight:bold;color:{hint_color};cursor:pointer;">'
                f'🔬 Software Audit Hint [{sw_label}]</summary>'
                f'<div style="font-size:11px;color:{hint_color};background:{hint_bg};'
                f'border-left:3px solid {hint_color};padding:6px 8px;margin-top:4px;'
                f'border-radius:3px;">{hint_body}</div>'
                f'</details>'
            )
        else:
            _TRUNC = 160
            _detail_trunc = detail[:_TRUNC] if len(detail) > _TRUNC else detail
            detail_escaped = html.escape(detail).replace(chr(10), "<br>")
            detail_short   = html.escape(_detail_trunc).replace(chr(10), "<br>")
            if len(detail) > _TRUNC:
                detail_cell = (
                    f'<details><summary style="cursor:pointer;font-size:12px;color:#444;">'
                    f'{detail_short}… <span style="color:#888;font-size:10px;">(expand)</span>'
                    f'</summary><div style="font-size:12px;color:#444;margin-top:4px;">{detail_escaped}</div></details>'
                )
            else:
                detail_cell = f'<div style="font-size:12px;color:#444;">{detail_escaped}</div>'

        rows_html.append(f"""
        <tr style="background:{bg};">
            <td style="padding:8px;font-weight:bold;color:#2c3e50;">{req_num}</td>
            <td style="padding:8px;">{name}</td>
            <td style="padding:8px;font-family:monospace;font-size:11px;color:#555;">{uri}</td>
            <td style="padding:8px;text-align:center;">{comp_badge}</td>
            <td style="padding:8px;text-align:center;">{status_badge}</td>
            <td style="padding:8px;">{detail_cell}</td>
            <td style="padding:8px;vertical-align:top;">{_build_likely_cause_cell(req_num, status, _detected_sw)}</td>
            <td style="padding:8px;">{mc_badge}</td>
            <td style="padding:8px;vertical-align:top;">{confidence_cell}</td>
        </tr>""")

    summary_items = "".join([
        f'<div style="text-align:center;padding:12px 20px;background:white;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,0.1);">'
        f'<div style="font-size:28px;font-weight:bold;color:{STATUS_HTML_COLOR.get(k,"#333")};">{v}</div>'
        f'<div style="font-size:12px;color:#666;margin-top:4px;">{k}</div>'
        f'</div>'
        for k, v in counts.items() if v > 0
    ])

    # ── Summary bar chart ─────────────────────────────────────────────────────
    _bar_order  = [("PASS", "#27ae60"), ("FAIL", "#e74c3c"),
                   ("PASS*", "#f39c12"), ("SKIPPED", "#95a5a6")]
    _bar_total  = sum(counts.get(k, 0) for k, _ in _bar_order) or 1
    _bar_segs   = "".join(
        f'<div title="{k}: {counts.get(k,0)}" style="width:{100*counts.get(k,0)/_bar_total:.1f}%;'
        f'background:{c};height:100%;display:inline-block;vertical-align:top;"></div>'
        for k, c in _bar_order if counts.get(k, 0) > 0
    )
    _bar_legend = "&nbsp;&nbsp;".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;color:#555;">'
        f'<span style="width:10px;height:10px;background:{c};border-radius:2px;display:inline-block;"></span>'
        f'{k} {counts.get(k,0)}</span>'
        for k, c in _bar_order if counts.get(k, 0) > 0
    )
    summary_bar = (
        f'<div style="margin:10px 0 4px;">'
        f'<div style="height:14px;border-radius:7px;overflow:hidden;background:#eee;">{_bar_segs}</div>'
        f'<div style="margin-top:6px;text-align:center;">{_bar_legend}</div>'
        f'</div>'
    )

    profile_rows = "".join([
        f'<tr><td style="padding:7px 12px;font-weight:bold;color:#2c3e50;white-space:nowrap;">{html.escape(str(k))}</td>'
        f'<td style="padding:7px 12px;font-family:monospace;">{html.escape(str(v))}</td></tr>'
        for k, v in profile.items() if k not in ("generated_at",)
    ])

    # ── Forensic Software Banner ──────────────────────────────────────────────
    forensic = results.get("__forensic__", {})
    _sw       = forensic.get("software", "UNKNOWN")
    _sw_conf  = forensic.get("confidence", "Low")
    _sw_sigs  = forensic.get("signals", [])
    _sw_hints = forensic.get("hints", {})
    _sw_color = {"QGIS/GDAL": "#1a6b3c", "ArcGIS": "#1a3a6b", "UNKNOWN": "#7d5a00"}.get(_sw, "#555")
    _sw_bg    = {"QGIS/GDAL": "#eafaf1", "ArcGIS": "#eaf0fb", "UNKNOWN": "#fff8e1"}.get(_sw, "#f8f9fa")
    _sw_icon  = {"QGIS/GDAL": "🟢", "ArcGIS": "🔵", "UNKNOWN": "🟡"}.get(_sw, "⚪")
    _sw_conf_color = {"High": "#27ae60", "Medium": "#f39c12", "Low": "#e74c3c"}.get(_sw_conf, "#999")
    _sw_sigs_html = "".join(f'<li style="margin:2px 0;">{html.escape(str(s))}</li>' for s in _sw_sigs)
    _sw_req_hints_items = "".join(
        f'<li style="margin:3px 0;"><strong>Req {rn}:</strong> {html.escape(h[:120])}{"…" if len(h) > 120 else ""}</li>'
        for rn, h in sorted(_sw_hints.items())
    )
    if _sw_req_hints_items:
        _hints_block = (
            f'<details style="margin-top:6px;">'
            f'<summary style="font-size:12px;color:{_sw_color};cursor:pointer;font-weight:bold;">'
            f'&#x26A0;&#xFE0F; Requirement Audit Hints for {_sw} ({len(_sw_hints)}) &mdash; click to expand'
            f'</summary>'
            f'<ul style="font-size:11px;color:#555;margin:6px 0;padding-left:18px;">{_sw_req_hints_items}</ul>'
            f'</details>'
        )
    else:
        _hints_block = ""
    # v1.53: cascade root-cause banner (yellow advisory box when metadata tables absent)
    _cascade_raw = results.get("__cascade_note__")
    if _cascade_raw:
        _cascade_banner = (
            '<div style="background:#fef9e7;border:2px solid #f39c12;border-radius:6px;'
            'padding:14px 20px;margin:18px 0;font-size:14px;">'
            f'<strong>⚠️ Cascade Root-Cause Advisory</strong><br>{html.escape(_cascade_raw)}'
            '</div>'
        )
    else:
        _cascade_banner = ""

    forensic_banner = (
        f'<div style="background:{_sw_bg};border:1px solid {_sw_color};border-left:5px solid {_sw_color};'
        f'border-radius:6px;padding:14px 18px;margin:16px 0;">'
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
        f'<span style="font-size:20px;">{_sw_icon}</span>'
        f'<strong style="font-size:15px;color:{_sw_color};">Source Software Detected: {_sw}</strong>'
        f'<span style="background:{_sw_conf_color};color:white;padding:2px 8px;border-radius:4px;'
        f'font-size:11px;font-weight:bold;">{_sw_conf} Confidence</span>'
        f'</div>'
        f'<details>'
        f'<summary style="font-size:12px;color:{_sw_color};cursor:pointer;font-weight:bold;">'
        f'&#x1F50D; Detection Signals ({len(_sw_sigs)}) &mdash; click to expand'
        f'</summary>'
        f'<ul style="font-size:11px;color:#555;margin:6px 0;padding-left:18px;">{_sw_sigs_html}</ul>'
        f'</details>'
        f'{_hints_block}'
        f'</div>'
    )

    html_str = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DGIWG GeoPackage Compliance Report — {html.escape(profile['filename'])}</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 0; padding: 0; background: #f0f2f5; color: #2c3e50; }}
  .header {{ background: linear-gradient(135deg, #1a252f 0%, #2c3e50 50%, #34495e 100%);
             color: white; padding: 32px 40px; }}
  .header h1 {{ margin: 0 0 6px 0; font-size: 24px; font-weight: 700; }}
  .header p  {{ margin: 0; opacity: 0.7; font-size: 14px; }}
  .verdict-banner {{ padding: 16px 40px; font-size: 18px; font-weight: bold;
                     color: white; background: {verdict_color}; }}
  .content {{ padding: 24px 40px; }}
  .section-title {{ font-size: 18px; font-weight: bold; color: #2c3e50;
                    border-bottom: 3px solid #3498db; padding-bottom: 8px; margin: 28px 0 16px 0; }}
  .summary-grid {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 24px; }}
  table {{ width: 100%; border-collapse: collapse; background: white;
           box-shadow: 0 1px 6px rgba(0,0,0,0.08); border-radius: 8px; overflow: hidden; }}
  th {{ background: #2c3e50; color: white; padding: 11px 8px; text-align: left;
        font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
  tr:hover {{ filter: brightness(0.97); }}
  td {{ border-bottom: 1px solid #ecf0f1; vertical-align: top; }}
  .profile-table td:first-child {{ background: #f8f9fa; }}
  .legend {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 16px 0; font-size: 13px; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; }}
  .legend-dot {{ width: 14px; height: 14px; border-radius: 3px; }}
  .footer {{ text-align: center; padding: 20px; color: #95a5a6; font-size: 12px;
             border-top: 1px solid #ddd; margin-top: 32px; }}
</style>
</head>
<body>

<div class="header">
  <h1>🛡 DGIWG GeoPackage Compliance Report</h1>
  <p style="margin-top:6px;">File: {html.escape(profile['filename'])}</p>
</div>

<div class="verdict-banner">
  Overall Verdict: {verdict} &nbsp;|&nbsp;
  {counts['PASS']} PASS &nbsp;|&nbsp;
  {counts['FAIL']} FAIL &nbsp;|&nbsp;
  {counts['PASS*']} PASS* &nbsp;|&nbsp;
  {manual_confirmed} PASS* fully confirmed (manual check) &nbsp;|&nbsp;
  {counts['SKIPPED']} SKIPPED
</div>

<div class="content">

  <div class="section-title">📊 Summary</div>
  <div class="summary-grid">{summary_items}</div>
  {summary_bar}

  <div class="legend">
    <strong>Legend:</strong>
    <span class="legend-item"><span class="legend-dot" style="background:#27ae60;"></span> PASS — Fully checked, compliant</span>
    <span class="legend-item"><span class="legend-dot" style="background:#e74c3c;"></span> FAIL — Non-compliant or issue found</span>
    <span class="legend-item"><span class="legend-dot" style="background:#f39c12;"></span> PASS* — Partial automated check</span>
    <span class="legend-item"><span class="legend-dot" style="background:#7f8c8d;"></span> SKIPPED — Not applicable to this file</span>
    <span class="legend-item"><strong>Manual Confirmed</strong> = deeper DB check run on PASS* rows — e.g. "3 / 3" means all 3 items confirmed present in the database</span>
    <span class="legend-item"><strong>M</strong> = Mandatory &nbsp; <strong>C</strong> = Conditional</span>
  </div>

  <div class="section-title">📁 File Profile</div>
  <table class="profile-table" style="max-width:700px;">
    <thead><tr><th>Property</th><th>Value</th></tr></thead>
    <tbody>{profile_rows}</tbody>
  </table>

  {forensic_banner}

  {_cascade_banner}

  <div class="section-title">✅ Requirement Validation Results</div>
  <table>
    <thead>
      <tr>
        <th style="width:40px;">#</th>
        <th style="width:170px;">Requirement</th>
        <th style="width:170px;">Identifier</th>
        <th style="width:55px;">Type</th>
        <th style="width:100px;">Result</th>
        <th>Details</th>
        <th style="width:180px;">Likely Cause</th>
        <th style="width:155px;">Manual Confirmed</th>
        <th style="width:110px;">Confidence</th>
      </tr>
    </thead>
    <tbody>{"".join(rows_html)}</tbody>
  </table>

  <div class="section-title">🌐 Internet-Backed Verification Checks</div>
  {_render_internet_checks_html(results.get("__internet__", {}))}

  <div class="section-title">🔬 Forensic Deep-Dive — What the File Actually Contains</div>
  {_render_forensic_section(results.get("__forensic_checks__", {}))}

</div>

<div class="footer">
  DGIWG GeoPackage Compliance Report &nbsp;|&nbsp;
  Requirements 1–2 (OGC Base) require CITE TeamEngine and are not automated.
  PASS* indicates partial automated validation only.
  <div style="margin-top:8px;font-size:12px;font-weight:bold;color:#2c3e50 !important;letter-spacing:0.3px;">Created by MCpl Son E.S. &nbsp;|&nbsp; euisoo.son@forces.gc.ca</div>
  <div style="margin-top:2px;font-size:11px;color:#7f8c8d !important;">&copy; MCE/T&amp;E &mdash; Mapping and Charting Establishment / Geomatics Engineering Trials &amp; Evaluation Support Section (GETESS)</div>
</div>

</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_str)
    print(f"  HTML report written: {output_path}")



# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def _get_likely_cause(req_num: int, status: str, software: str) -> str:
    """
    Return the likely-cause diagnosis string for a given requirement, result
    status, and detected source software.

    Returns "" (empty) for PASS and SKIPPED — no diagnosis needed.
    For FAIL: returns the tool-specific cause (falls back to UNKNOWN text).
    For PASS*: returns the PASS*-specific note if defined, else UNKNOWN.
    """
    if status in ("PASS", "SKIPPED"):
        return ""
    entry = LIKELY_CAUSE.get(req_num)
    if not entry:
        return ""
    if status == "PASS*":
        return entry.get("PASS*", entry.get("UNKNOWN", ""))
    # FAIL — use tool-specific text, fall back to UNKNOWN
    return entry.get(software, entry.get("UNKNOWN", ""))


# ──────────────────────────────────────────────────────────────────────────────
# ROLLUP AGGREGATION
# ──────────────────────────────────────────────────────────────────────────────

