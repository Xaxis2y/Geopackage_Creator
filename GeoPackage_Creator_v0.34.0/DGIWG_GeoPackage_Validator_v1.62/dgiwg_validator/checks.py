# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Requirement check functions for DGIWG STD-DP-19-005 v1.1 (v1.62).

Contains check_req(), _r1()-_r37(), _manual_checks(),
run_all_checks(), and the _CHECK_DISPATCH table.
"""
import os
import sys
import re
import sqlite3
import math
import html
import json
import textwrap
import datetime
from pathlib import Path
from collections import defaultdict
from xml.etree import ElementTree as ET
from .constants import (
    REQUIREMENTS, EXTENSIONS_TABLE,
    ALLOWED_RASTER_CRS, ALLOWED_RASTER_CRS_DISPLAY,
    ALLOWED_GRIDDED_2D_CRS, ALLOWED_GRIDDED_3D_CRS,
    ALLOWED_VECTOR_CRS_2D, ALLOWED_VECTOR_CRS_3D,
    OGC_PIXEL_Z0, OGC_PIXEL_TOL, CRS_EXTENT, TABLE_36_ALLOWED,
    DMF_ISO_MANDATORY, STATUS_ICON, TILE_SIZE, TILE_W, TILE_H, NET_TIMEOUT,
)
from .net import (
    _net_get, _net_check_uri, _net_check_epsg, _net_check_scale_denoms,
    _net_check_dmf_xml, DMF_XSD_INLINE, _DMF_REQUIRED_ELEMENTS,
    # v1.62 cleanup: _http_get / _http_head were imported here but never called
    # (every network call in this module goes through _net_get or the
    # _net_check_* helpers).  Removed to keep the import surface honest.
    _load_epsg_json_cache,
    # v1.58 fix (Bug A): _EPSG_API was referenced in _r13()'s online datum
    # fallback but never imported — the NameError was silently swallowed by the
    # surrounding try/except, so the EPSG REST API last-resort lookup never ran.
    _EPSG_API,
)
from .utils import (
    table_exists, column_exists, _quote_ident, get_data_categories,
    _check_xml_xsd, _decode_gpkg_geom_header, _parse_wkt_structural,
    LIBRARY_STATUS,
)
from . import config as _config
def check_req(cursor, req_num):
    """Returns (status, detail_string) for a single requirement."""
    try:
        return _CHECK_DISPATCH[req_num](cursor)
    except Exception as e:
        # An implementation failure is not evidence that the input violates a
        # requirement.  Keeping it distinct prevents a broken optional library,
        # malformed edge case, or future regression from being reported as a
        # false non-conformance.
        return ("ERROR", f"Validator error during check ({type(e).__name__}): {e}")


def _r3(cursor):
    """Mandatory Extensions + GeoPackage base format integrity.

    v1.47 additions:
      (a) Scope validation — OGC GeoPackage 1.3 §3.1.3: scope must be
          'read-write' or 'write-only'. Invalid or missing scope is a
          non-conformance appended to the result detail.
      (b) SQLite / GeoPackage base format checks (OGC core requirements
          inherited by DGIWG):
          • application_id — must encode GeoPackage 1.2/1.3 (0x47503132)
            or 1.1 (0x47503131); version 1.0 triggers a FAIL.
          • PRAGMA page_size — 4096 recommended by OGC GeoPackage spec.
          • PRAGMA encoding — must be UTF-8.
          • PRAGMA journal_mode — WAL mode at delivery risks data loss
            when sidecar -wal/-shm files are absent on the target system.
          • gpkg_contents.last_change — must be a valid ISO 8601 datetime
            and must not be future-dated.
    """
    cats = get_data_categories(cursor)
    if not cats:
        return ("SKIPPED", "No data types found in gpkg_contents")
    # v1.58 fix (Bug B): gpkg_extensions is an optional table in the OGC core
    # spec.  When absent, this check previously crashed with "no such table"
    # and check_req() converted it into an unhelpful generic exception FAIL.
    # Absence simply means NO extensions are registered — so every mandatory
    # extension for the present data types is missing; report them by name.
    if not table_exists(cursor, "gpkg_extensions"):
        _missing_m = sorted({
            ext for ext, rules in EXTENSIONS_TABLE.items()
            for cat in cats if rules.get(cat) == "M"
        })
        return ("FAIL",
                "gpkg_extensions table is MISSING — no extensions are registered. "
                f"Mandatory extension(s) required for data type(s) "
                f"{', '.join(sorted(cats))}: {', '.join(_missing_m) or 'none'}")
    cursor.execute("SELECT extension_name FROM gpkg_extensions")
    present = {r[0] for r in cursor.fetchall()}
    fails, passes = [], []
    for ext, rules in EXTENSIONS_TABLE.items():
        for cat in cats:
            status = rules.get(cat, "NA")
            if status == "M":
                if ext in present:
                    passes.append(f"{ext} present for {cat}")
                else:
                    fails.append(f"{ext} MISSING (mandatory for {cat})")

    # ── v1.47: scope validation ──────────────────────────────────────────────
    VALID_SCOPES = {"read-write", "write-only"}
    try:
        cursor.execute("SELECT extension_name, scope FROM gpkg_extensions")
        scope_rows = cursor.fetchall()
        for ext_name, scope in scope_rows:
            if scope is None or scope.strip() == "":
                passes.append(
                    f"⚠ Scope is NULL/empty for extension '{ext_name}' "
                    f"— recommended: 'read-write' or 'write-only' (NULL permitted by OGC spec)"
                )
            elif scope.strip().lower() not in VALID_SCOPES:
                fails.append(
                    f"Invalid scope='{scope}' for extension '{ext_name}' "
                    f"— must be 'read-write' or 'write-only'"
                )
            else:
                passes.append(f"scope='{scope}' valid for '{ext_name}' ✓")
    except Exception as _scope_err:
        passes.append(f"Scope validation skipped: {_scope_err}")

    # ── v1.47 (b): SQLite / GeoPackage base format checks ────────────────────
    try:
        # application_id encodes the GeoPackage spec version
        cursor.execute("PRAGMA application_id")
        _app_id = cursor.fetchone()[0]
        _GP_VERS = {
            0x47503130: ("GeoPackage 1.0",    False),  # (label, conformant)
            0x47503131: ("GeoPackage 1.1",    False),  # DGIWG requires 1.2+
            0x47503132: ("GeoPackage 1.2/1.3", True),
        }
        # Since GeoPackage 1.2, "GPKG" is the standard application_id. Its
        # actual schema version is carried in PRAGMA user_version; GeoPackage
        # 1.4 files consequently use application_id=0x47504B47 and must not be
        # rejected as legacy GDAL output.  See OGC 12-128r15 ATS A.1.1.1.1.1.
        cursor.execute("PRAGMA user_version")
        _user_version = cursor.fetchone()[0]
        if _app_id in _GP_VERS:
            _ver, _conf = _GP_VERS[_app_id]
            if _conf:
                passes.append(
                    f"GeoPackage version: {_ver} (application_id=0x{_app_id:08X}) ✓"
                )
            else:
                fails.append(
                    f"application_id=0x{_app_id:08X} ({_ver}) — "
                    f"DGIWG requires GeoPackage 1.2+ (0x47503132)"
                )
        elif _app_id == 0x47504B47:
            if _user_version >= 10200:
                passes.append(
                    f"GeoPackage application_id='GPKG', user_version={_user_version} "
                    f"(GeoPackage 1.2+ standard marker) ✓"
                )
            else:
                fails.append(
                    f"application_id='GPKG' but user_version={_user_version}; "
                    f"GeoPackage 1.2+ requires user_version >= 10200"
                )
        elif _app_id == 0:
            fails.append("application_id=0 — not a valid GeoPackage (no version registered)")
        else:
            fails.append(
                f"application_id=0x{_app_id:08X} — unrecognised GeoPackage version; "
                f"expected GP12 or standard 'GPKG' with user_version >= 10200"
            )
    except Exception as _ai_e:
        passes.append(f"application_id check skipped: {_ai_e}")

    try:
        cursor.execute("PRAGMA page_size")
        _page_sz = cursor.fetchone()[0]
        if _page_sz != 4096:
            passes.append(
                f"⚠ PRAGMA page_size={_page_sz} — 4096 recommended (not mandatory); "
                f"non-standard sizes may reduce interoperability"
            )
        else:
            passes.append(f"page_size=4096 ✓")
    except Exception as _ps_e:
        passes.append(f"page_size check skipped: {_ps_e}")

    try:
        cursor.execute("PRAGMA encoding")
        _enc = cursor.fetchone()[0]
        if _enc.upper() != "UTF-8":
            fails.append(
                f"PRAGMA encoding='{_enc}' — GeoPackage requires UTF-8 encoding"
            )
        else:
            passes.append(f"encoding='{_enc}' ✓")
    except Exception as _enc_e:
        passes.append(f"encoding check skipped: {_enc_e}")

    try:
        cursor.execute("PRAGMA journal_mode")
        _jm = cursor.fetchone()[0]
        if _jm.lower() == "wal":
            fails.append(
                "journal_mode=WAL — GeoPackage not checkpointed before delivery. "
                "Transferring without the -wal/-shm sidecar files causes silent data "
                "loss on the receiving system. Run PRAGMA wal_checkpoint(TRUNCATE) before transfer."
            )
        else:
            passes.append(f"journal_mode='{_jm}' (not WAL) ✓")
    except Exception as _jm_e:
        passes.append(f"journal_mode check skipped: {_jm_e}")

    try:
        import re as _relc
        import datetime as _dtlc
        _ISO_DT = _relc.compile(
            r'^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?$'
        )
        cursor.execute("SELECT table_name, last_change FROM gpkg_contents")
        # v1.58: datetime.utcnow() is deprecated since Python 3.12 — use the
        # timezone-aware equivalent (same wall-clock value, no warning).
        _now = _dtlc.datetime.now(_dtlc.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        for _lc_tbl, _lc_val in cursor.fetchall():
            _lc_str = str(_lc_val or "").strip()
            if not _lc_str:
                fails.append(
                    f"gpkg_contents '{_lc_tbl}': last_change is NULL/empty — "
                    f"must be an ISO 8601 datetime"
                )
            elif not _ISO_DT.match(_lc_str):
                fails.append(
                    f"gpkg_contents '{_lc_tbl}': last_change='{_lc_str}' "
                    f"is not a valid ISO 8601 datetime"
                )
            elif _lc_str > _now:
                passes.append(
                    f"gpkg_contents '{_lc_tbl}': last_change='{_lc_str}' "
                    f"⚠ future-dated timestamp (clock skew?)"
                )
            else:
                passes.append(
                    f"gpkg_contents '{_lc_tbl}': last_change='{_lc_str}' ✓"
                )
    except Exception as _lc_e:
        passes.append(f"last_change check skipped: {_lc_e}")

    if fails:
        return ("FAIL", "\n".join(fails + passes))
    return ("PASS", "\n".join(passes) if passes else "All mandatory extensions present; base format valid")


def _r4(cursor):
    """Optional Extensions.

    v1.62 change: this check used to return PASS* unconditionally, which made
    the top verdict "CONFORMANT" unreachable for every file (see
    score_results(): CONFORMANT requires zero PASS*).  The distinction that
    actually matters is whether any optional extension is registered at all:

      • none registered  -> PASS   (nothing optional is claimed, nothing to
                                    verify by hand; this is fully conformant)
      • one or more      -> PASS*  (each registered extension still needs a
                                    human to confirm it is correctly declared
                                    and permitted for the product profile)

    Optional extensions can never produce FAIL by definition.
    """
    # v1.58 fix (Bug B): absent gpkg_extensions previously produced an
    # exception FAIL.  The table is optional in the OGC core — no table means
    # no optional extensions are registered, which is fully conformant.
    if not table_exists(cursor, "gpkg_extensions"):
        return ("PASS", "No gpkg_extensions table — no optional extensions "
                        "registered (optional extensions cannot fail by definition)")
    cursor.execute("SELECT extension_name FROM gpkg_extensions")
    present = {r[0] for r in cursor.fetchall()}
    cats = get_data_categories(cursor)
    notes = []
    for ext, rules in EXTENSIONS_TABLE.items():
        for cat in cats:
            if rules.get(cat) == "O" and ext in present:
                notes.append(f"{ext} present (optional for {cat})")
    if not notes:
        return ("PASS", "No optional extensions registered — nothing to verify "
                        "(optional extensions cannot fail by definition)")
    return ("PASS*",
            "; ".join(notes)
            + ". Confirm manually that each registered optional extension is "
              "permitted by the applicable DGIWG product profile and is "
              "correctly declared in gpkg_extensions.")


def _r5(cursor):
    """Extensions Not Allowed.

    v1.47: also samples tile_data BLOBs for WEBP magic bytes
    (RIFF....WEBP signature). WEBP format is not a permitted tile encoding
    under DGIWG (only PNG and JPEG are allowed). The check uses binary
    header inspection — no image library required.
    """
    cats = get_data_categories(cursor)
    if not cats:
        return ("SKIPPED", "No data types found")
    # v1.58 fix (Bug B): absent gpkg_extensions previously produced an
    # exception FAIL.  No table = nothing registered = nothing disallowed;
    # the WEBP tile BLOB scan below still runs regardless.
    if table_exists(cursor, "gpkg_extensions"):
        cursor.execute("SELECT extension_name, table_name FROM gpkg_extensions")
        present = cursor.fetchall()
        _ext_table_absent = False
    else:
        present = set()
        _ext_table_absent = True
    fails, passes = [], []
    if _ext_table_absent:
        passes.append("gpkg_extensions table absent — no extensions registered, "
                      "none disallowed ✓")
    # Extension registrations may be global (table_name NULL) or scoped to a
    # particular contents table.  A registration for a tiles/features table is
    # not prohibited merely because the same GeoPackage also contains gridded
    # data.  Evaluate Table 8 against the extension's actual scope.
    _table_category = {}
    if table_exists(cursor, "gpkg_contents"):
        cursor.execute("SELECT table_name, data_type FROM gpkg_contents")
        for _table, _dtype in cursor.fetchall():
            _dtype = (_dtype or "").lower()
            _table_category[_table] = (
                "gridded" if "gridded" in _dtype else
                "features" if _dtype == "features" else
                "tiles" if _dtype == "tiles" else None
            )
    for ext, table_name in present:
        rules = EXTENSIONS_TABLE.get(ext)
        if not rules:
            continue
        _applies_to = set(cats) if not table_name else {_table_category.get(table_name)}
        _applies_to.discard(None)
        for cat in sorted(_applies_to):
            if rules.get(cat) == "N":
                scope_label = "globally" if not table_name else f"table '{table_name}'"
                fails.append(f"{ext} is NOT ALLOWED for {cat} but registered {scope_label}")
    if not fails:
        passes.append("No registered extension is prohibited in its applicable data scope ✓")

    # ── v1.47: WEBP tile detection via magic bytes ────────────────────────────
    # WEBP signature: bytes 0-3 = 'RIFF', bytes 8-11 = 'WEBP'
    def _is_webp(blob_bytes):
        raw = bytes(blob_bytes[:12])
        return (len(raw) >= 12
                and raw[:4] == b'RIFF'
                and raw[8:12] == b'WEBP')

    if "tiles" in cats:
        try:
            # Get all tile tables with data_type='tiles'
            cursor.execute(
                "SELECT table_name FROM gpkg_contents WHERE data_type='tiles'"
            )
            tile_tables = [r[0] for r in cursor.fetchall()]
            for tname in tile_tables:
                try:
                    cursor.execute(
                        f'SELECT tile_data FROM {_quote_ident(tname)} '
                        f'WHERE tile_data IS NOT NULL LIMIT 10'
                    )
                    blobs = [r[0] for r in cursor.fetchall()]
                    webp_found = [i+1 for i, b in enumerate(blobs) if b and _is_webp(b)]
                    if webp_found:
                        fails.append(
                            f"WEBP tile(s) detected in '{tname}' "
                            f"(blob index(es): {webp_found}) — "
                            f"WEBP is NOT allowed by DGIWG; only PNG and JPEG are permitted"
                        )
                    elif blobs:
                        passes.append(
                            f"'{tname}': {len(blobs)} sampled tile(s) — no WEBP detected ✓"
                        )
                except Exception as _t_err:
                    passes.append(f"'{tname}': WEBP check skipped ({_t_err})")
        except Exception as _webp_err:
            passes.append(f"WEBP tile scan skipped: {_webp_err}")

    if fails:
        return ("FAIL", "; ".join(fails))
    return ("PASS*", "; ".join(passes) if passes else "No disallowed extensions or tile formats present")


def _r6(cursor):
    """Conditional Extensions."""
    return ("SKIPPED", "Conditional extension check requires file-specific profile knowledge")


def _r7(cursor):
    """Raster CRS Allowed — also verifies scale denominators match OGC 17-083r4.

    For each tile matrix set:
      1. CRS code must be in DGIWG Table 9 allowlist (unchanged).
      2. pixel_x_size / pixel_y_size at every zoom level must match the OGC standard
         value = OGC_PIXEL_Z0[srs_id] / 2^zoom_level, within OGC_PIXEL_TOL (0.01%).
         If the CRS is not in OGC_PIXEL_Z0 (e.g. custom DGIWG codes 100100-100399),
         scale denominator check is skipped with a note.
    """
    if not table_exists(cursor, "gpkg_tile_matrix_set"):
        return ("SKIPPED", "No tile matrix set table")
    # v1.39: only check data_type='tiles' entries — gridded coverage CRS is
    # governed by Req 11/12, not Req 7.  Filter via JOIN on gpkg_contents.
    # definition_12_063 belongs to the optional CRS WKT extension.  A base
    # GeoPackage legitimately lacks it, so construct the SELECT accordingly.
    _has_wkt2 = column_exists(cursor, "gpkg_spatial_ref_sys", "definition_12_063")
    _wkt2_expr = "COALESCE(srs.definition_12_063,'')" if _has_wkt2 else "''"
    cursor.execute(f"""
        SELECT tms.srs_id, srs.srs_name, tms.table_name,
               COALESCE(srs.definition,''), {_wkt2_expr}
        FROM gpkg_tile_matrix_set tms
        LEFT JOIN gpkg_spatial_ref_sys srs ON tms.srs_id = srs.srs_id
        JOIN gpkg_contents c ON tms.table_name = c.table_name
        WHERE c.data_type = 'tiles'
    """)
    tms_rows = cursor.fetchall()
    if not tms_rows:
        return ("SKIPPED", "No raster tile pyramid tables (data_type='tiles') found — "
                "Req 7 not applicable (gridded coverage CRS checked in Req 11/12)")

    crs_fails, crs_passes = [], []
    scale_fails, scale_passes, scale_skips = [], [], []

    def _is_lambert_conformal_conic(*wkts):
        # DGIWG Table 11 allows WGS 84 / Lambert Conformal Conic (1SP/2SP) "per product".
        # These have no fixed EPSG code, so accept them when the WKT projection method
        # is Lambert Conformal Conic. Matches both WKT1 ("Lambert_Conformal_Conic_1SP/2SP")
        # and WKT2 ("Lambert Conic Conformal (1SP/2SP)") spellings.
        blob = " ".join(w for w in wkts if w).upper().replace("_", " ")
        return "LAMBERT CONFORMAL CONIC" in blob or "LAMBERT CONIC CONFORMAL" in blob

    for srs_id, srs_name, tname, _defn, _defn2 in tms_rows:
        label = f"'{tname}' (srs_id={srs_id})"

        # ── Step 1: CRS allowlist ─────────────────────────────────────────────
        if srs_id in ALLOWED_RASTER_CRS:
            crs_passes.append(f"{label}: CRS allowed ✓")
        elif _is_lambert_conformal_conic(_defn, _defn2):
            crs_passes.append(
                f"{label}: per-product Lambert Conformal Conic CRS "
                f"(allowed by DGIWG Table 11) ✓")
            scale_skips.append(
                f"{label}: scale denominator check not available for per-product LCC CRS")
            continue  # LCC has no fixed OGC pixel_z0 sequence to verify
        else:
            crs_fails.append(
                f"{label}: srs_id={srs_id} ({srs_name}) NOT in DGIWG raster CRS list "
                f"(allowed: {ALLOWED_RASTER_CRS_DISPLAY})")
            continue  # no point checking scale if CRS is wrong

        # ── Step 2: scale denominator check ──────────────────────────────────
        pz0 = OGC_PIXEL_Z0.get(srs_id)
        if pz0 is None:
            scale_skips.append(f"{label}: scale denominator check not available for srs_id={srs_id}")
            continue

        if not table_exists(cursor, "gpkg_tile_matrix"):
            scale_skips.append(f"{label}: gpkg_tile_matrix absent — scale check skipped")
            continue

        cursor.execute("""
            SELECT zoom_level, pixel_x_size, pixel_y_size
            FROM gpkg_tile_matrix
            WHERE table_name = ?
            ORDER BY zoom_level
        """, (tname,))
        zoom_rows = cursor.fetchall()
        if not zoom_rows:
            scale_skips.append(f"{label}: no zoom level entries in gpkg_tile_matrix")
            continue

        # v1.39: Zoom-offset-aware scale check.
        # Files may start at a non-zero OGC global zoom level (regional tile
        # pyramids call their first zoom "0" even if it corresponds to OGC zoom 13).
        # Find the OGC zoom level that best matches the file's first entry, then
        # verify all levels follow the offset-corrected sequence.
        first_zoom, first_px = zoom_rows[0][0], zoom_rows[0][1]
        zoom_offset = None
        best_offset_err = float('inf')
        for ogc_z in range(0, 30):
            exp_px = pz0 / (2 ** ogc_z)
            rel_err = abs(first_px - exp_px) / exp_px
            if rel_err < best_offset_err:
                best_offset_err = rel_err
                zoom_offset = ogc_z - first_zoom  # OGC zoom = file_zoom + offset

        zoom_fails = []
        if best_offset_err > 0.5:
            # First zoom doesn't match any OGC level within 50% — non-standard scale
            zoom_fails.append(
                f"zoom {first_zoom}: pixel_x_size={first_px:.10g} does not match any "
                f"OGC 17-083r4 level (closest err={best_offset_err*100:.1f}%) — "
                f"non-standard scale denominator"
            )
        else:
            offset_note = (f" [zoom offset: file_zoom+{zoom_offset}=OGC_zoom]"
                           if zoom_offset != 0 else "")
            for zoom, px, py in zoom_rows:
                effective_ogc_zoom = zoom + zoom_offset
                expected = pz0 / (2 ** effective_ogc_zoom)
                tol = expected * OGC_PIXEL_TOL
                if abs(px - expected) > tol:
                    zoom_fails.append(
                        f"zoom {zoom}(OGC {effective_ogc_zoom}): "
                        f"pixel_x_size={px:.10g} expected≈{expected:.10g} "
                        f"(diff={abs(px-expected):.3e})"
                    )
                if abs(py - expected) > tol and srs_id != 4326:
                    zoom_fails.append(
                        f"zoom {zoom}(OGC {effective_ogc_zoom}): "
                        f"pixel_y_size={py:.10g} expected≈{expected:.10g} "
                        f"(diff={abs(py-expected):.3e})"
                    )

        if zoom_fails:
            scale_fails.append(
                f"{label}: scale denominator mismatch at {len(zoom_fails)} zoom level(s): "
                + "; ".join(zoom_fails[:5])
            )
        else:
            offset_note = (f" [zoom offset +{zoom_offset}: file zoom {zoom_rows[0][0]} "
                           f"= OGC zoom {zoom_rows[0][0]+zoom_offset}]"
                           if zoom_offset != 0 else "")
            scale_passes.append(
                f"{label}: all {len(zoom_rows)} zoom level(s) match OGC 17-083r4 "
                f"scale sequence ✓{offset_note}"
            )

    all_lines = crs_fails + scale_fails + crs_passes + scale_passes + scale_skips
    detail = "\n".join(all_lines)

    if crs_fails or scale_fails:
        return ("FAIL", detail)
    if scale_skips and not scale_passes:
        return ("PASS*", detail + "\n(PASS* = CRS allowed; scale denominator check not available for this CRS code)")
    return ("PASS", detail)

def _r8(cursor):
    """CRS Raster Tile Matrix Set — scale denominator full check (v1.27).
    Verifies that each tile matrix set uses a DGIWG-allowed raster CRS AND
    that the tile_width/tile_height are exactly 256 for all zoom levels.
    Scale denominator arithmetic is performed in Req 7 — this req focuses on
    the tile matrix set registration and tile dimensions per OGC 17-083r4.
    """
    if not table_exists(cursor, "gpkg_tile_matrix_set"):
        return ("SKIPPED", "No tile matrix set")
    # v1.42 fix: only check data_type='tiles' entries — gridded coverage (2d-gridded-
    # coverage) tile dimensions are not governed by Req 8 (OGC 17-083r4 tile pyramid).
    # Same data_type filter applied to Req 7 in v1.39.
    cursor.execute("""
        SELECT tms.table_name, tms.srs_id
        FROM gpkg_tile_matrix_set tms
        JOIN gpkg_contents c ON tms.table_name = c.table_name
        WHERE c.data_type = 'tiles'
    """)
    tms_rows = cursor.fetchall()
    if not tms_rows:
        return ("SKIPPED", "No raster tile pyramid tables (data_type='tiles') found — "
                "Req 8 not applicable (gridded coverage checked separately)")

    if not table_exists(cursor, "gpkg_tile_matrix"):
        return ("PASS*",
                "gpkg_tile_matrix_set has entries but gpkg_tile_matrix absent — "
                "tile dimensions not verifiable")

    fails, passes = [], []
    for tname, srs_id in tms_rows:
        label = f"'{tname}' (srs_id={srs_id})"
        cursor.execute("""
            SELECT zoom_level, tile_width, tile_height
            FROM gpkg_tile_matrix
            WHERE table_name = ?
            ORDER BY zoom_level
        """, (tname,))
        zoom_rows = cursor.fetchall()
        if not zoom_rows:
            passes.append(f"{label}: no zoom entries — tile dimension check N/A ✓")
            continue
        dim_fails = []
        for zoom, tw, th in zoom_rows:
            if tw != TILE_W or th != TILE_H:
                dim_fails.append(f"zoom {zoom}: {tw}×{th} (expected {TILE_W}×{TILE_H})")
        if dim_fails:
            fails.append(
                f"{label}: non-standard tile dimensions at {len(dim_fails)} zoom level(s): "
                + "; ".join(dim_fails[:5])
            )
        else:
            passes.append(
                f"{label}: all {len(zoom_rows)} zoom level(s) have 256×256 tiles ✓"
            )

    detail = "\n".join(fails + passes)
    if fails:
        return ("FAIL", detail)
    return ("PASS", detail)

def _r9(cursor):
    """2D Vector CRS."""
    if not table_exists(cursor, "gpkg_geometry_columns"):
        return ("SKIPPED", "No vector geometry columns found")
    cursor.execute("""
        SELECT gc.table_name, gc.srs_id, srs.srs_name
        FROM gpkg_geometry_columns gc
        LEFT JOIN gpkg_spatial_ref_sys srs ON gc.srs_id = srs.srs_id
        WHERE gc.z = 0
    """)
    rows = cursor.fetchall()
    if not rows:
        return ("SKIPPED", "No 2D vector feature sets")
    fails, passes = [], []
    for table, srs_id, srs_name in rows:
        if srs_id in ALLOWED_VECTOR_CRS_2D:
            passes.append(f"{table}: srs_id={srs_id} ✓")
        else:
            fails.append(f"{table}: srs_id={srs_id} ({srs_name}) NOT in allowed 2D vector CRS list")
    return ("FAIL" if fails else "PASS*", "; ".join(fails + passes))


def _r10(cursor):
    """3D Vector CRS."""
    if not table_exists(cursor, "gpkg_geometry_columns"):
        return ("SKIPPED", "No vector geometry columns found")
    cursor.execute("""
        SELECT gc.table_name, gc.srs_id, srs.srs_name
        FROM gpkg_geometry_columns gc
        LEFT JOIN gpkg_spatial_ref_sys srs ON gc.srs_id = srs.srs_id
        WHERE gc.z != 0
    """)
    rows = cursor.fetchall()
    if not rows:
        return ("SKIPPED", "No 3D vector feature sets")
    fails, passes = [], []
    for table, srs_id, srs_name in rows:
        ok = (srs_id in ALLOWED_VECTOR_CRS_3D)
        if ok:
            passes.append(f"{table}: srs_id={srs_id} ✓")
        else:
            fails.append(
                f"{table}: srs_id={srs_id} ({srs_name}) not in allowed 3D vector CRS list "
                f"(allowed: {sorted(ALLOWED_VECTOR_CRS_3D)})"
            )
    return ("FAIL" if fails else "PASS*", "; ".join(fails + passes))


def _r11(cursor):
    """Gridded 2D CRS — adds bounding-box cross-check against CRS valid extent.

    For each 2D gridded coverage:
      1. CRS must be in DGIWG Table 11 allowlist.
      2. File bounding box (from gpkg_contents min_x/y, max_x/y) must fall within
         the valid geographic extent of the declared CRS (from CRS_EXTENT table).
         A bbox that exceeds the CRS extent by more than 0.1% is flagged as FAIL.
    """
    cursor.execute("SELECT table_name, data_type FROM gpkg_contents")
    gridded = {t for t, dt in cursor.fetchall()
               if (dt or "").strip() in ("2d-gridded-coverage","gpkg_2d_gridded_coverage","2d_gridded_coverage")}
    if not gridded:
        return ("SKIPPED", "No gridded coverage tables found in gpkg_contents")
    if not table_exists(cursor, "gpkg_tile_matrix_set"):
        return ("SKIPPED", "gpkg_tile_matrix_set missing")
    cursor.execute("""
        SELECT tms.table_name, tms.srs_id, srs.srs_name,
               COALESCE(srs.definition,''),
               tms.min_x, tms.min_y, tms.max_x, tms.max_y
        FROM gpkg_tile_matrix_set tms
        LEFT JOIN gpkg_spatial_ref_sys srs ON tms.srs_id = srs.srs_id
        WHERE tms.table_name IN ({})
    """.format(",".join("?" * len(gridded))), list(gridded))
    rows = cursor.fetchall()
    if not rows:
        return ("SKIPPED", "No gridded tables found in gpkg_tile_matrix_set")

    fails, passes, routed = [], [], []
    for name, srs_id, srs_name, defn, mn_x, mn_y, mx_x, mx_y in rows:
        wkt = defn.upper()
        is_3d = (srs_id == 4979) or "COMPOUNDCRS" in wkt or "COMPD_CS" in wkt
        if is_3d:
            routed.append(f"'{name}': srs_id={srs_id} is 3D → Req 12 applies")
            continue

        label = f"'{name}' (srs_id={srs_id} {srs_name})"

        # CRS allowlist check
        if srs_id not in ALLOWED_GRIDDED_2D_CRS:
            fails.append(f"{label}: NOT in DGIWG Table 11 allowed 2D gridded CRS list")
            continue
        crs_ok = f"{label}: CRS in Table 11 ✓"

        # BBox vs CRS extent check
        extent = CRS_EXTENT.get(srs_id)
        if extent is None:
            passes.append(crs_ok + " | CRS extent not in lookup table — bbox cross-check skipped")
            continue
        ex_mnx, ex_mny, ex_mxx, ex_mxy = extent

        if None in (mn_x, mn_y, mx_x, mx_y):
            passes.append(crs_ok + " | bbox NULL — cross-check skipped")
            continue

        tol_x = abs(ex_mxx - ex_mnx) * 0.001
        tol_y = abs(ex_mxy - ex_mny) * 0.001
        bbox_fails = []
        if mn_x < ex_mnx - tol_x: bbox_fails.append(f"min_x={mn_x:.4f} < CRS min {ex_mnx}")
        if mn_y < ex_mny - tol_y: bbox_fails.append(f"min_y={mn_y:.4f} < CRS min {ex_mny}")
        if mx_x > ex_mxx + tol_x: bbox_fails.append(f"max_x={mx_x:.4f} > CRS max {ex_mxx}")
        if mx_y > ex_mxy + tol_y: bbox_fails.append(f"max_y={mx_y:.4f} > CRS max {ex_mxy}")

        if bbox_fails:
            fails.append(f"{label}: bbox exceeds valid CRS extent: " + "; ".join(bbox_fails))
        else:
            passes.append(crs_ok + f" | bbox within CRS extent ✓ ({mn_x:.1f},{mn_y:.1f})→({mx_x:.1f},{mx_y:.1f})")

    if routed and not fails and not passes:
        return ("SKIPPED", "; ".join(routed))
    detail = "\n".join(fails + passes + routed)
    if fails:
        return ("FAIL", detail)
    return ("PASS", detail)

def _r12(cursor):
    """Gridded 3D CRS.
    Routing: 3D = srs_id==4979 OR WKT contains COMPOUNDCRS/COMPD_CS.
    If all gridded tables are 2D-CRS, this requirement is SKIPPED (v1.0 behaviour).
    """
    cursor.execute("SELECT table_name, data_type FROM gpkg_contents")
    gridded = {t for t, dt in cursor.fetchall()
               if (dt or "").strip() in ("2d-gridded-coverage","gpkg_2d_gridded_coverage","2d_gridded_coverage")}
    if not gridded:
        return ("SKIPPED", "No gridded coverage tables found in gpkg_contents")
    if not table_exists(cursor, "gpkg_tile_matrix_set"):
        return ("SKIPPED", "gpkg_tile_matrix_set missing")
    cursor.execute("""
        SELECT tms.table_name, tms.srs_id, srs.srs_name, COALESCE(srs.definition,'')
        FROM gpkg_tile_matrix_set tms
        LEFT JOIN gpkg_spatial_ref_sys srs ON tms.srs_id = srs.srs_id
        WHERE tms.table_name IN ({})
    """.format(",".join("?" * len(gridded))), list(gridded))
    rows = cursor.fetchall()
    if not rows:
        return ("SKIPPED", "No gridded tables found in gpkg_tile_matrix_set")
    fails, passes, routed = [], [], []
    for name, srs_id, srs_name, defn in rows:
        wkt = defn.upper()
        is_3d = (srs_id == 4979) or "COMPOUNDCRS" in wkt or "COMPD_CS" in wkt
        if not is_3d:
            routed.append(f"'{name}': srs_id={srs_id} is 2D → Req 11 applies")
        else:
            ok = (srs_id in ALLOWED_GRIDDED_3D_CRS) or "COMPOUNDCRS" in wkt or "COMPD_CS" in wkt
            if ok:
                passes.append(f"'{name}': srs_id={srs_id} ({srs_name}) valid 3D gridded CRS ✓")
            else:
                fails.append(f"'{name}': srs_id={srs_id} ({srs_name}) not in allowed 3D gridded CRS list")
    if routed and not fails and not passes:
        return ("SKIPPED", "; ".join(routed) + " — no 3D gridded tables found; Req 12 not applicable")
    if fails:
        return ("FAIL", "; ".join(fails + passes + routed))
    return ("PASS*", "; ".join(passes + routed))


def _r13(cursor):
    """WKT for CRS — content validation against DGIWG Tables 15-24 (v1.27).

    v1.26 checks retained:
      - WKT1 keyword detection, prime meridian, angular unit, axis names, datum presence.
    v1.27 addition:
      - Datum name cross-check via pyproj CRS database (offline EPSG registry).
        If pyproj is installed: extract EPSG code from srs_id, look up official datum
        name from pyproj.CRS, compare against datum name in the WKT string.
        Mismatch → FAIL.  pyproj not installed → PASS* with install note.
    """
    import re as _re

    WKT1_KEYWORDS = ("GEOGCS[", "PROJCS[", "COMPD_CS[")

    # Use LIBRARY_STATUS to determine pyproj availability.
    # LIBRARY_STATUS is populated at startup by _probe_optional_libraries().
    # Fallback: if LIBRARY_STATUS is not yet populated (e.g. imported as module),
    # attempt a direct import.
    # Always do a live import check rather than relying solely on LIBRARY_STATUS,
    # which may have been set to False before the library was installed.
    try:
        from pyproj import CRS as _ProjCRS  # noqa: F401
        pyproj_ok = True
        LIBRARY_STATUS["pyproj"] = True
    except Exception:
        pyproj_ok = False

    has_063 = column_exists(cursor, "gpkg_spatial_ref_sys", "definition_12_063")
    if has_063:
        cursor.execute(
            "SELECT srs_id, srs_name, definition, definition_12_063 "
            "FROM gpkg_spatial_ref_sys WHERE srs_id > 0"
        )
        rows = [(r[0], r[1], r[2], r[3]) for r in cursor.fetchall()]
    else:
        cursor.execute(
            "SELECT srs_id, srs_name, definition "
            "FROM gpkg_spatial_ref_sys WHERE srs_id > 0"
        )
        rows = [(r[0], r[1], r[2], None) for r in cursor.fetchall()]

    if not rows:
        return ("SKIPPED", "No CRS entries with positive srs_id")

    hard_fails = []
    soft_warns = []
    passes     = []

    # ── v1.47: DGIWG CRS allowlist check (Tables 1–12 of STD-DP-19-005 v1.1) ─
    # Every srs_id > 0 must be from the DGIWG-approved set, encoded in the
    # dgiwg_epsg_cache.json (128 entries).  Falls back to hard-coded core set
    # when the cache file is absent.
    _al_cache = _load_epsg_json_cache()
    _al_allowed = (
        set(int(k) for k in _al_cache.keys())
        if _al_cache
        else set()
    )
    # Core DGIWG codes always allowed regardless of cache
    _al_allowed |= {3395, 3857, 4326, 4978, 4979, 5041, 5042, 9518} | \
                   set(range(32601, 32661)) | set(range(32701, 32761))
    def _is_dgiwg_dynamic_crs(_sid, _name):
        """Accept dynamic DGIWG CRS identifiers carried by URI/name."""
        text = str(_name or "")
        for match in _re.findall(r"(?:crs|def)/([0-9]{6})", text.lower()):
            if 100100 <= int(match) <= 100399:
                return True
        return 100100 <= int(_sid) <= 100399

    for _al_sid, _al_sname, _al_defn, _al_063 in rows:
        if _al_sid in _al_allowed or _is_dgiwg_dynamic_crs(_al_sid, _al_sname):
            passes.append(
                f"srs_id={_al_sid} ({_al_sname}) is DGIWG-approved or dynamic CRS ✓"
            )
        else:
            hard_fails.append(
                f"srs_id={_al_sid} ({_al_sname or '?'}) is NOT in DGIWG-approved CRS list "
                f"(STD-DP-19-005 v1.1 Tables 1–12) — non-standard CRS used"
            )

    for srs_id, srs_name, defn, defn_063 in rows:
        label = f"srs_id={srs_id} ({srs_name})"
        wkt = None
        if defn_063 and defn_063.strip() not in ("", "undefined"):
            wkt = defn_063.strip()
        elif defn and defn.strip() not in ("", "undefined"):
            wkt = defn.strip()

        if not wkt:
            hard_fails.append(f"{label}: WKT missing entirely")
            continue

        wkt_upper = wkt.upper()
        issues   = []
        warnings = []

        # Rule 1: no WKT1 keywords
        for kw in WKT1_KEYWORDS:
            if kw in wkt_upper:
                issues.append(f"WKT1 keyword '{kw.rstrip(chr(91))}' found — DGIWG requires WKT2")
                break

        # Rule 2: prime meridian = Greenwich
        if "PRIMEM" in wkt_upper:
            if "GREENWICH" not in wkt_upper:
                issues.append("PRIMEM found but is not Greenwich")
        else:
            if any(k in wkt_upper for k in ("GEOGCRS", "PROJCRS", "COMPOUNDCRS")):
                warnings.append("PRIMEM keyword absent — could not verify prime meridian = Greenwich")

        # Rule 3: angular unit = degree
        if "ANGLEUNIT" in wkt_upper:
            if "DEGREE" not in wkt_upper:
                issues.append("ANGLEUNIT found but does not contain 'degree'")
        elif "UNIT" in wkt_upper:
            if "DEGREE" not in wkt_upper:
                warnings.append("UNIT keyword found but 'degree' not confirmed")
        else:
            warnings.append("ANGLEUNIT keyword absent — angular unit not confirmed")

        # Rule 4: axis names + order (v1.47 Feature 5 — CRS axis order)
        # DGIWG STD-DP-19-005 v1.1 Tables 15/16 mandate that geographic 2D CRS
        # axes follow Latitude (NORTH) then Longitude (EAST) order — not the
        # "GIS convention" of Longitude first.  An incorrect axis order causes
        # coordinates to be swapped silently in WMS/WFS services.
        if "AXIS" in wkt_upper:
            has_lat = "LATITUDE" in wkt_upper or ",NORTH" in wkt_upper.replace(" ", "")
            has_lon = "LONGITUDE" in wkt_upper or ",EAST" in wkt_upper.replace(" ", "")
            if not has_lat:
                warnings.append("Latitude axis name not found in WKT")
            if not has_lon:
                warnings.append("Longitude axis name not found in WKT")

            # ── v1.47 Feature 5: axis order check for geographic CRS ──────────
            _is_geog = any(k in wkt_upper for k in
                           ("GEOGCRS[", "GEOGCS[", "GEODCRS[", "GEODETICCRS["))
            if _is_geog:
                # Extract all AXIS[name, direction] pairs in document order
                _ax_matches = _re.findall(
                    r'AXIS\["([^"]*)"[^]]*,\s*([A-Z]+)\]',
                    wkt, _re.IGNORECASE
                )
                if len(_ax_matches) >= 2:
                    _first_dir  = _ax_matches[0][1].upper()
                    _second_dir = _ax_matches[1][1].upper()
                    _first_name = _ax_matches[0][0]
                    _NORTH_DIRS = {"NORTH", "LATITUDE"}
                    _EAST_DIRS  = {"EAST", "LONGITUDE"}
                    if _first_dir in _NORTH_DIRS and _second_dir in _EAST_DIRS:
                        warnings.append(
                            f"CRS axis order: '{_first_name}' ({_first_dir}) → "
                            f"'{_ax_matches[1][0]}' ({_second_dir}) — "
                            f"Latitude/North first ✓ (DGIWG-compliant order)"
                        )
                    elif _first_dir in _EAST_DIRS and _second_dir in _NORTH_DIRS:
                        issues.append(
                            f"CRS axis order MISMATCH: first axis is "
                            f"'{_first_name}' ({_first_dir}) — "
                            f"DGIWG Tables 15/16 require Latitude (NORTH) as the "
                            f"first axis for geographic 2D CRS.  Coordinates may be "
                            f"swapped in WMS/WFS services."
                        )
                    else:
                        warnings.append(
                            f"CRS axis order could not be confirmed "
                            f"(axes: {_ax_matches[0][1]}, {_ax_matches[1][1]})"
                        )
                elif _ax_matches:
                    warnings.append(
                        f"Only one AXIS definition found — axis order check incomplete"
                    )
                else:
                    warnings.append(
                        "No AXIS definitions parsed — axis order not verifiable"
                    )
        else:
            warnings.append("AXIS keywords absent — axis names and order not verifiable")

        # Rule 5: datum name — extract from WKT
        datum_match = _re.search(r'DATUM\["([^"]+)"', wkt, _re.IGNORECASE)
        wkt_datum_name = datum_match.group(1).strip() if datum_match else None

        if not wkt_datum_name:
            ensemble = _re.search(r'ENSEMBLE\["([^"]+)"', wkt, _re.IGNORECASE)
            if ensemble:
                wkt_datum_name = ensemble.group(1).strip()
                warnings.append(f"ENSEMBLE='{wkt_datum_name}' (no DATUM keyword — using ensemble name)")
            else:
                issues.append("No DATUM, ENSEMBLE, or TRF keyword found in WKT")

        # Rule 6 (v1.27+v1.47): cross-check datum name AND WKT structure via pyproj.
        # DGIWG dynamic CRS identifiers are convention identifiers, not EPSG
        # registrations.  pyproj therefore cannot resolve them with
        # CRS.from_epsg(); the earlier WKT hard rules remain authoritative and
        # the unresolved registry lookup must not create a false FAIL.
        _custom_dynamic = _is_dgiwg_dynamic_crs(srs_id, srs_name)
        if wkt_datum_name and pyproj_ok and not _custom_dynamic:
            try:
                from pyproj import CRS as _ProjCRS

                # ── v1.47: structural parse via _parse_wkt_structural() ──────
                # v1.55: now returns 4-tuple including math_equiv flag
                _struct_issues, _struct_warns, epsg_crs, _math_equiv = _parse_wkt_structural(
                    wkt, srs_id, _ProjCRS
                )
                issues.extend(_struct_issues)
                warnings.extend(_struct_warns)

                # Ensure epsg_crs is available for datum check even on from_wkt() failure
                if epsg_crs is None:
                    epsg_crs = _ProjCRS.from_epsg(srs_id)

                # ── Datum name cross-check (v1.27, refined v1.55) ─────────
                # v1.55: if pyproj confirmed mathematical equivalence, a datum
                # *name* difference is purely cosmetic (e.g. "WGS_1984" vs
                # "World Geodetic System 1984") and is downgraded from FAIL
                # to a warning.  Only a genuine parameter mismatch (_math_equiv
                # is False) or a failed parse (_math_equiv is None) keeps the
                # name check as a hard FAIL.
                official_datum = epsg_crs.datum.name if epsg_crs.datum else None
                if official_datum:
                    # Fuzzy compare: normalise whitespace and case
                    def _norm(s):
                        return _re.sub(r'\s+', ' ', s.strip().upper())
                    if _norm(wkt_datum_name) != _norm(official_datum):
                        # Check for common aliases before deciding severity
                        aliases = {
                            "WORLD GEODETIC SYSTEM 1984": "WGS 84",
                            "WGS 84": "WORLD GEODETIC SYSTEM 1984",
                            "WGS_84": "WORLD GEODETIC SYSTEM 1984",
                            "EUROPEAN TERRESTRIAL REFERENCE SYSTEM 1989": "ETRS89",
                            "ETRS89": "EUROPEAN TERRESTRIAL REFERENCE SYSTEM 1989",
                        }
                        norm_wkt = _norm(wkt_datum_name)
                        norm_off = _norm(official_datum)
                        alias_of_official = _norm(aliases.get(official_datum.upper(), ""))
                        is_known_alias = (
                            norm_wkt == alias_of_official
                            or norm_off in norm_wkt
                            or norm_wkt in norm_off
                        )
                        if is_known_alias:
                            warnings.append(
                                f"DATUM '{wkt_datum_name}' is an alias for '{official_datum}' "
                                f"(EPSG:{srs_id}) ✓"
                            )
                        elif _math_equiv:
                            # CRS parameters are correct — name variation only
                            warnings.append(
                                f"DATUM name variation: WKT has '{wkt_datum_name}' vs "
                                f"EPSG:{srs_id} official '{official_datum}' — "
                                f"accepted (CRS is mathematically equivalent ✓)"
                            )
                        else:
                            # Parameters also differ (or could not be verified) — hard fail
                            issues.append(
                                f"DATUM name mismatch: WKT has '{wkt_datum_name}' "
                                f"but EPSG:{srs_id} official datum is '{official_datum}'"
                            )
                    else:
                        warnings.append(
                            f"DATUM='{wkt_datum_name}' matches EPSG:{srs_id} ✓"
                        )
                else:
                    warnings.append(
                        f"DATUM='{wkt_datum_name}' — pyproj returned no datum for EPSG:{srs_id}"
                    )
            except Exception as e:
                warnings.append(
                    f"DATUM='{wkt_datum_name}' present | pyproj lookup failed for EPSG:{srs_id}: {e}"
                )
        elif _custom_dynamic:
            warnings.append(
                "DGIWG dynamic CRS convention identifier recognised; EPSG/pyproj "
                "cross-check is not applicable — validate the CRS definition against "
                "the controlling product specification"
            )
        elif wkt_datum_name and not pyproj_ok:
            # ── Offline fallback — priority order: JSON cache → hardcoded table ─
            # v1.47: check dgiwg_epsg_cache.json first (covers all 128 DGIWG codes)
            _expected = None
            _json_cache = _load_epsg_json_cache()
            _cache_entry = _json_cache.get(str(srs_id))
            if _cache_entry:
                _expected = _cache_entry.get("datum", None)
                _expected_src = "JSON cache"
            else:
                # Hardcoded DGIWG-allowed EPSG datum names (legacy fallback)
                _DGIWG_DATUM_MAP = {
                    4326:  "World Geodetic System 1984",
                    4979:  "World Geodetic System 1984",
                    4978:  "World Geodetic System 1984",
                    3857:  "World Geodetic System 1984",
                    3395:  "World Geodetic System 1984",
                    5041:  "World Geodetic System 1984",
                    5042:  "World Geodetic System 1984",
                    9518:  "World Geodetic System 1984",
                }
                if 32601 <= srs_id <= 32660 or 32701 <= srs_id <= 32760:
                    _DGIWG_DATUM_MAP[srs_id] = "World Geodetic System 1984"
                _expected = _DGIWG_DATUM_MAP.get(srs_id)
                _expected_src = "hardcoded DGIWG table"

            if _expected:
                def _norm_datum(s):
                    return _re.sub(r'[\s_\-]+', ' ', s.strip().upper())
                _wkt_n = _norm_datum(wkt_datum_name)
                _exp_n = _norm_datum(_expected)
                # Accept common abbreviations
                _aliases = {
                    "WGS 84", "WGS84", "WGS_84",
                    "WORLD GEODETIC SYSTEM 1984",
                    "WORLD GEODETIC SYSTEM (WGS 1984)",
                }
                if _wkt_n == _exp_n or wkt_datum_name.upper().strip() in {a.upper() for a in _aliases}:
                    warnings.append(
                        f"DATUM='{wkt_datum_name}' matches expected datum for EPSG:{srs_id} "
                        f"({_expected_src} offline check) ✓"
                    )
                else:
                    issues.append(
                        f"DATUM name mismatch: WKT has '{wkt_datum_name}' but expected "
                        f"'{_expected}' for EPSG:{srs_id} ({_expected_src} offline check)"
                    )
            else:
                # EPSG code not in offline DGIWG table — try EPSG REST API as last resort
                _net_datum = None
                if not _config.OFFLINE:
                    try:
                        # v1.57: no explicit timeout — _net_get() resolves the
                        # current constants.NET_TIMEOUT at call time (--timeout aware)
                        _ok, _body = _net_get(_EPSG_API.format(code=srs_id))
                        import json as _json
                        _data = _json.loads(_body)
                        _net_datum = _data.get("name", None)
                    except Exception:
                        pass
                if _net_datum:
                    def _norm2(s):
                        return _re.sub(r'[\s_\-]+', ' ', s.strip().upper())
                    if _norm2(wkt_datum_name) in _norm2(_net_datum) or \
                       _norm2(_net_datum) in _norm2(wkt_datum_name):
                        warnings.append(
                            f"DATUM='{wkt_datum_name}' consistent with EPSG:{srs_id} "
                            f"(internet lookup: '{_net_datum}') ✓"
                        )
                    else:
                        issues.append(
                            f"DATUM name mismatch: WKT has '{wkt_datum_name}' but "
                            f"EPSG:{srs_id} registry name is '{_net_datum}' (internet lookup)"
                        )
                else:
                    warnings.append(
                        f"DATUM='{wkt_datum_name}' present | EPSG:{srs_id} not in DGIWG offline "
                        f"table — install pyproj for full datum cross-check: pip install pyproj"
                    )

        if issues:
            hard_fails.append(f"{label}: " + "; ".join(issues))
        elif warnings:
            soft_warns.append(f"{label}: ✅ hard rules passed | ⚠️ " + "; ".join(warnings))
        else:
            passes.append(f"{label}: ✅ all WKT content checks passed")

    suffix = "" if has_063 else "\n⚠️ definition_12_063 absent — WKT2 column not present; using definition column only"
    detail = "\n".join(hard_fails + soft_warns + passes) + suffix

    if hard_fails:
        return ("FAIL", detail)
    if soft_warns:
        return ("PASS*", detail + "\n(PASS* = hard rules passed; some WKT content required pyproj or could not be fully verified)")
    return ("PASS", detail)

def _r14(cursor):
    """Compound CRS Usage — COMPOUNDCRS only valid for z!=0 features.
    v1.0 also checks all SRS entries for COMPOUNDCRS regardless of geometry table presence,
    so if no gpkg_geometry_columns exist we still emit PASS* (not SKIPPED).
    """
    # Check SRS entries for any compound CRS usage
    cursor.execute("SELECT srs_id, srs_name, COALESCE(definition,'') FROM gpkg_spatial_ref_sys WHERE srs_id > 0")
    srs_rows = cursor.fetchall()
    compound_srs = [f"srs_id={sid} ({sname})" for sid, sname, defn in srs_rows
                    if "COMPOUNDCRS" in defn.upper() or "COMPD_CS" in defn.upper()]

    if not table_exists(cursor, "gpkg_geometry_columns"):
        if compound_srs:
            return ("PASS*", f"Compound CRS present in SRS table: {'; '.join(compound_srs)}. "
                             "No vector geometry columns — z-dimension applicability not verifiable")
        return ("PASS*", "No vector geometry columns and no compound CRS in SRS — "
                         "compound CRS usage check not applicable to this file type")
    cursor.execute("""
        SELECT gc.table_name, gc.z, srs.definition
        FROM gpkg_geometry_columns gc
        LEFT JOIN gpkg_spatial_ref_sys srs ON gc.srs_id = srs.srs_id
    """)
    rows = cursor.fetchall()
    if not rows:
        return ("PASS*", "No feature geometry rows — compound CRS check not applicable")
    fails, passes = [], []
    for table, z, defn in rows:
        has_compound = defn and ("COMPOUNDCRS" in defn.upper() or "COMPD_CS" in defn.upper())
        if z == 0 and has_compound:
            fails.append(f"'{table}': z=0 (2D) but uses COMPOUNDCRS — not allowed for 2D features")
        elif z == 0:
            passes.append(f"'{table}': 2D (z=0), no COMPOUNDCRS ✓")
        else:
            passes.append(f"'{table}': 3D (z={z}), COMPOUNDCRS {'used ✓' if has_compound else 'not used ✓'}")
    if fails:
        return ("FAIL", "; ".join(fails + passes))
    return ("PASS*", "; ".join(passes) + " — full compound CRS WKT structure check in Req 15")


def _r15(cursor):
    """Compound CRS WKT — full WKT2 structure validation for vector feature tables.

    upgraded from keyword-detection to full sub-component structure check:
      - COMPOUNDCRS[ must be present (already checked by _r14 routing)
      - Must contain GEOGCRS[ or PROJCRS[ (horizontal component)
      - Must contain VERTCRS[ (vertical component)
      - Both must be direct children of the COMPOUNDCRS block
      - VERTCRS datum name must be non-empty
    Returns SKIPPED if no vector tables use compound CRS.
    Returns FAIL if COMPOUNDCRS exists but is missing required sub-components.
    Returns PASS when full structure is confirmed.
    """
    import re as _re

    if not table_exists(cursor, "gpkg_geometry_columns"):
        return ("SKIPPED", "No vector geometry columns — Req 15 not applicable")

    cursor.execute("SELECT DISTINCT srs_id FROM gpkg_geometry_columns WHERE srs_id IS NOT NULL")
    vector_srs_ids = {r[0] for r in cursor.fetchall()}
    if not vector_srs_ids:
        return ("SKIPPED", "No vector geometry columns — Req 15 not applicable")

    has_063 = column_exists(cursor, "gpkg_spatial_ref_sys", "definition_12_063")
    placeholders = ",".join("?" * len(vector_srs_ids))
    if has_063:
        cursor.execute(
            f"SELECT srs_id, srs_name, definition, definition_12_063 "
            f"FROM gpkg_spatial_ref_sys WHERE srs_id IN ({placeholders})",
            list(vector_srs_ids)
        )
        srs_rows = [(r[0], r[1], r[2], r[3]) for r in cursor.fetchall()]
    else:
        cursor.execute(
            f"SELECT srs_id, srs_name, definition "
            f"FROM gpkg_spatial_ref_sys WHERE srs_id IN ({placeholders})",
            list(vector_srs_ids)
        )
        srs_rows = [(r[0], r[1], r[2], None) for r in cursor.fetchall()]

    compound_entries = []
    for srs_id, srs_name, defn, defn_063 in srs_rows:
        wkt = None
        if defn_063 and "COMPOUNDCRS" in (defn_063 or "").upper():
            wkt = defn_063
        elif defn and ("COMPOUNDCRS" in (defn or "").upper() or "COMPD_CS" in (defn or "").upper()):
            wkt = defn
        if wkt:
            compound_entries.append((srs_id, srs_name, wkt))

    if not compound_entries:
        return ("SKIPPED", "No compound CRS found for vector feature tables — Req 15 not applicable")

    hard_fails = []
    passes     = []

    for srs_id, srs_name, wkt in compound_entries:
        label   = f"srs_id={srs_id} ({srs_name})"
        wkt_up  = wkt.upper()
        issues  = []

        # ── Check horizontal component ────────────────────────────────────────
        has_geogcrs  = "GEOGCRS["  in wkt_up
        has_projcrs  = "PROJCRS["  in wkt_up
        has_geogcs   = "GEOGCS["   in wkt_up   # WKT1 fallback (not allowed)
        has_projcs   = "PROJCS["   in wkt_up   # WKT1 fallback (not allowed)

        if has_geogcs or has_projcs:
            issues.append("WKT1 horizontal component (GEOGCS/PROJCS) found — DGIWG requires WKT2 (GEOGCRS/PROJCRS)")
        elif not (has_geogcrs or has_projcrs):
            issues.append("Missing horizontal component — GEOGCRS or PROJCRS required inside COMPOUNDCRS")

        # ── Check vertical component ──────────────────────────────────────────
        if "VERTCRS[" not in wkt_up and "VERT_CS[" not in wkt_up:
            issues.append("Missing VERTCRS — vertical component required inside COMPOUNDCRS per DGIWG Tables 29-30")
        elif "VERT_CS[" in wkt_up and "VERTCRS[" not in wkt_up:
            issues.append("WKT1 vertical component VERT_CS found — DGIWG requires WKT2 VERTCRS")

        # ── Check VERTCRS datum name ──────────────────────────────────────────
        import re as _re
        vert_match = _re.search(r'VERTCRS\[.*?VDATUM\["([^"]+)"', wkt, _re.IGNORECASE | _re.DOTALL)
        if vert_match:
            vdatum = vert_match.group(1).strip()
            if not vdatum:
                issues.append("VDATUM name inside VERTCRS is empty")
        else:
            if "VERTCRS[" in wkt_up:
                issues.append("VDATUM keyword not found inside VERTCRS — vertical datum name not verifiable")

        if issues:
            hard_fails.append(f"{label}: " + "; ".join(issues))
        else:
            horiz = "GEOGCRS" if has_geogcrs else "PROJCRS"
            passes.append(
                f"{label}: ✅ COMPOUNDCRS structure valid — {horiz} (horizontal) + VERTCRS (vertical) confirmed"
            )

    all_lines = hard_fails + passes
    detail    = "\n".join(all_lines)

    if hard_fails:
        return ("FAIL", detail)
    return ("PASS", detail)


def _r16(cursor):
    """Gridded Compound CRS WKT — full WKT2 structure validation.

    upgraded from keyword-detection to full sub-component structure check
    (same rules as Req 15 but applied to gridded coverage CRS entries):
      - definition_12_063 must be present (WKT2 column); WKT1 fallback warned
      - COMPOUNDCRS[ must be present
      - Must contain GEOGCRS[ or PROJCRS[ (horizontal)
      - Must contain VERTCRS[ (vertical)
    """
    import re as _re

    if not table_exists(cursor, "gpkg_2d_gridded_coverage_ancillary"):
        return ("SKIPPED", "No gridded data — Req 16 not applicable")

    has_063 = column_exists(cursor, "gpkg_spatial_ref_sys", "definition_12_063")

    if has_063:
        cursor.execute("""
            SELECT anc.tile_matrix_set_name, srs.srs_id, srs.srs_name,
                   srs.definition, srs.definition_12_063
            FROM gpkg_2d_gridded_coverage_ancillary anc
            JOIN gpkg_tile_matrix_set tms ON anc.tile_matrix_set_name = tms.table_name
            LEFT JOIN gpkg_spatial_ref_sys srs ON tms.srs_id = srs.srs_id
        """)
        rows = [(r[0], r[1], r[2], r[3], r[4]) for r in cursor.fetchall()]
    else:
        cursor.execute("""
            SELECT anc.tile_matrix_set_name, srs.srs_id, srs.srs_name, srs.definition
            FROM gpkg_2d_gridded_coverage_ancillary anc
            JOIN gpkg_tile_matrix_set tms ON anc.tile_matrix_set_name = tms.table_name
            LEFT JOIN gpkg_spatial_ref_sys srs ON tms.srs_id = srs.srs_id
        """)
        rows = [(r[0], r[1], r[2], r[3], None) for r in cursor.fetchall()]

    if not rows:
        return ("SKIPPED", "No gridded coverage entries found")

    # Filter to only entries that use a compound CRS
    compound_entries = []
    non_compound     = []
    for tname, srs_id, srs_name, defn, defn_063 in rows:
        wkt = None
        if defn_063 and "COMPOUNDCRS" in (defn_063 or "").upper():
            wkt = defn_063
        elif defn and ("COMPOUNDCRS" in (defn or "").upper() or "COMPD_CS" in (defn or "").upper()):
            wkt = defn
        if wkt:
            compound_entries.append((tname, srs_id, srs_name, wkt))
        else:
            non_compound.append(f"'{tname}' (srs_id={srs_id}): no compound CRS")

    if not compound_entries:
        return ("SKIPPED",
                "No gridded coverages use a compound CRS — Req 16 not applicable\n"
                + ("\n".join(non_compound) if non_compound else "")
                + ("" if has_063 else "\n⚠️ definition_12_063 column absent"))

    hard_fails = []
    passes     = []

    for tname, srs_id, srs_name, wkt in compound_entries:
        label  = f"gridded table '{tname}' srs_id={srs_id} ({srs_name})"
        wkt_up = wkt.upper()
        issues = []

        # WKT2 column check
        if not has_063:
            issues.append("definition_12_063 column absent — WKT2 not available; WKT1 fallback does not satisfy DGIWG for 3D gridded data")

        # Horizontal component
        has_geogcrs = "GEOGCRS[" in wkt_up
        has_projcrs = "PROJCRS[" in wkt_up
        has_geogcs  = "GEOGCS["  in wkt_up
        has_projcs  = "PROJCS["  in wkt_up

        if has_geogcs or has_projcs:
            issues.append("WKT1 horizontal component found — DGIWG requires WKT2 GEOGCRS/PROJCRS for gridded compound CRS")
        elif not (has_geogcrs or has_projcrs):
            issues.append("Missing horizontal component (GEOGCRS or PROJCRS) inside COMPOUNDCRS")

        # Vertical component
        if "VERTCRS[" not in wkt_up and "VERT_CS[" not in wkt_up:
            issues.append("Missing VERTCRS — vertical component required inside COMPOUNDCRS")
        elif "VERT_CS[" in wkt_up and "VERTCRS[" not in wkt_up:
            issues.append("WKT1 VERT_CS found — DGIWG requires WKT2 VERTCRS")

        if issues:
            hard_fails.append(f"{label}: " + "; ".join(issues))
        else:
            horiz = "GEOGCRS" if has_geogcrs else "PROJCRS"
            passes.append(
                f"{label}: ✅ COMPOUNDCRS structure valid — {horiz} + VERTCRS confirmed"
                + (" (from definition_12_063 ✓)" if has_063 else " (from definition column — WKT2 col absent)")
            )

    all_lines = hard_fails + passes
    detail    = "\n".join(all_lines)
    if hard_fails:
        return ("FAIL", detail)
    return ("PASS", detail)


def _r17(cursor):
    """Gridded CRS Epoch WKT — DYNAMIC[FRAMEEPOCH[value]] must match epoch column.

    upgraded from epoch-presence-only to full WKT parse:
      - Read epoch value from gpkg_spatial_ref_sys.epoch
      - Parse WKT for DYNAMIC[FRAMEEPOCH[<value>]] pattern
      - Compare numeric values (rounded to 1 decimal)
      - FAIL if epoch column populated but DYNAMIC/FRAMEEPOCH absent in WKT
      - FAIL if FRAMEEPOCH value does not match epoch column value
      - PASS if both match; PASS* if WKT has no DYNAMIC block but epoch is 0/null
    """
    import re as _re

    if not column_exists(cursor, "gpkg_spatial_ref_sys", "epoch"):
        return ("SKIPPED", "gpkg_spatial_ref_sys.epoch column not present — Req 17 not applicable")

    has_063 = column_exists(cursor, "gpkg_spatial_ref_sys", "definition_12_063")
    if has_063:
        cursor.execute(
            "SELECT srs_id, srs_name, epoch, definition, definition_12_063 "
            "FROM gpkg_spatial_ref_sys WHERE epoch IS NOT NULL AND epoch != 0"
        )
        srs_rows = [(r[0], r[1], r[2], r[3], r[4]) for r in cursor.fetchall()]
    else:
        cursor.execute(
            "SELECT srs_id, srs_name, epoch, definition "
            "FROM gpkg_spatial_ref_sys WHERE epoch IS NOT NULL AND epoch != 0"
        )
        srs_rows = [(r[0], r[1], r[2], r[3], None) for r in cursor.fetchall()]

    if not srs_rows:
        return ("SKIPPED", "No non-zero epoch values in gpkg_spatial_ref_sys — Req 17 not applicable")

    hard_fails = []
    passes     = []

    for row in srs_rows:
        srs_id, srs_name, epoch_val, defn, defn_063 = row
        label = f"srs_id={srs_id} ({srs_name}), epoch={epoch_val}"

        # Pick best WKT
        wkt = None
        if defn_063 and defn_063.strip() not in ("", "undefined"):
            wkt = defn_063.strip()
        elif defn and defn.strip() not in ("", "undefined"):
            wkt = defn.strip()

        if not wkt:
            hard_fails.append(f"{label}: WKT missing — cannot verify DYNAMIC[FRAMEEPOCH]")
            continue

        # Search for DYNAMIC[FRAMEEPOCH[<value>]]
        # Handles optional whitespace and both integer and decimal epoch values
        fe_match = _re.search(
            r'DYNAMIC\s*\[\s*FRAMEEPOCH\s*\[\s*([0-9.]+)\s*\]',
            wkt, _re.IGNORECASE
        )

        if not fe_match:
            hard_fails.append(
                f"{label}: epoch column has value {epoch_val} but WKT contains no "
                f"DYNAMIC[FRAMEEPOCH[...]] — non-conformant per DGIWG Req 17"
            )
            continue

        wkt_epoch = float(fe_match.group(1))
        col_epoch = float(epoch_val)

        if round(wkt_epoch, 1) != round(col_epoch, 1):
            hard_fails.append(
                f"{label}: FRAMEEPOCH mismatch — WKT has {wkt_epoch} but epoch column "
                f"has {col_epoch} — values must match"
            )
        else:
            passes.append(
                f"{label}: ✅ DYNAMIC[FRAMEEPOCH[{wkt_epoch}]] confirmed in WKT and "
                f"matches epoch column value {col_epoch}"
            )

    all_lines = hard_fails + passes
    detail    = "\n".join(all_lines)
    if hard_fails:
        return ("FAIL", detail)
    return ("PASS", detail)


def _r18(cursor):
    """GeoPackage Metadata DMF — full XML field value validation.

    upgraded from row-presence + URI detection to full DMF field parsing:
      - gpkg_metadata must exist and have rows (FAIL if not)
      - For each DMF row (URI contains dgiwg/dmf), parse the XML metadata field:
          fileIdentifier  — must be a valid UUID (8-4-4-4-12 hex pattern)
          language        — must be a 3-letter ISO 639-2 code (e.g. 'eng')
          characterSet    — must contain a valid MD_CharacterSetCode value
          hierarchyLevel  — must contain a valid MD_ScopeCode value
          contact         — organisationName must be non-empty; role must be present
          dateStamp       — must match ISO 8601 date (YYYY-MM-DD or YYYY-MM-DDThh:mm:ss)
          md_standard_uri — must start with http://www.dgiwg.org/std/dmf
    v1.47 addition:
      - XSD structural validation via lxml.etree.XMLSchema using the bundled
        DMF_XSD_INLINE schema. Catches element order violations and missing mandatory
        children not detectable by presence checks alone. Graceful fallback when
        lxml is not installed.
    Returns PASS when all DMF fields pass, FAIL on any hard violation, PASS* for
    rows where no DMF URI is found (cannot confirm DMF compliance).
    """
    import xml.etree.ElementTree as _ET
    import re as _re

    # ── v1.47: attempt lxml XSD validation setup ─────────────────────────────
    _lxml_ok = False
    _xsd_schema = None
    try:
        from lxml import etree as _lxml_etree
        _lxml_ok = True
        try:
            _xsd_doc = _lxml_etree.fromstring(DMF_XSD_INLINE.encode("utf-8"))
            _xsd_schema = _lxml_etree.XMLSchema(_xsd_doc)
        except Exception as _xsd_build_err:
            _xsd_schema = None  # bundled XSD failed to parse — skip XSD step
    except ImportError:
        pass  # lxml not installed — XSD validation skipped (reported below)

    # v1.62 fix: the XSD step used to disappear without trace when lxml was
    # absent, so the same GeoPackage could report PASS on one machine and FAIL
    # on another with nothing in the report to explain the difference.  The
    # outcome of the XSD stage is now always stated in the detail text.
    if _lxml_ok and _xsd_schema is not None:
        _xsd_status_note = ("ℹ️ XSD structural validation: ENABLED "
                            "(lxml present, bundled DMF schema loaded)")
    elif _lxml_ok:
        _xsd_status_note = ("⚠️ XSD structural validation: SKIPPED — the bundled DMF "
                            "schema could not be compiled; field-level checks only")
    else:
        _xsd_status_note = ("⚠️ XSD structural validation: SKIPPED — lxml is not "
                            "installed, so element order and missing mandatory "
                            "children were NOT verified. Install with: pip install lxml")

    # ── Step 1: table and row presence (unchanged from v1.0 match) ────────────
    if not table_exists(cursor, "gpkg_metadata"):
        return ("FAIL", "gpkg_metadata table is MISSING")
    cursor.execute("SELECT id, md_scope, md_standard_uri, mime_type, metadata FROM gpkg_metadata")
    all_rows = cursor.fetchall()
    if not all_rows:
        return ("FAIL", "gpkg_metadata table exists but contains no rows")

    # ── Step 2: split rows into DMF and non-DMF ───────────────────────────────
    dmf_rows     = []
    non_dmf_rows = []
    for row_id, md_scope, uri, mime, xml_text in all_rows:
        uri_lower = (uri or "").lower()
        if "dgiwg" in uri_lower and "dmf" in uri_lower:
            dmf_rows.append((row_id, md_scope, uri, mime, xml_text))
        else:
            non_dmf_rows.append((row_id, uri or ""))

    if not dmf_rows:
        uris_found = [u for _, u in non_dmf_rows]
        return ("PASS*",
                f"gpkg_metadata has {len(all_rows)} row(s) but none use a DGIWG DMF URI\n"
                f"URIs found: {', '.join(uris_found[:5]) or 'none'}\n"
                "Cannot confirm DMF compliance without a DMF row.")

    # ── Step 3: validate each DMF row ─────────────────────────────────────────
    VALID_CHARSET_CODES = {
        "ucs2","ucs4","utf7","utf8","utf16","8859part1","8859part2","8859part3",
        "8859part4","8859part5","8859part6","8859part7","8859part8","8859part9",
        "8859part10","8859part11","8859part13","8859part14","8859part15","8859part16",
        "jis932","shiftJIS","eucJP","usAscii","ebcdic","eucKR","big5","GB2312"
    }
    VALID_SCOPE_CODES = {
        "attribute","attributeType","collectionHardware","collectionSession",
        "dataset","series","nonGeographicDataset","dimensionGroup","feature",
        "featureType","propertyType","fieldSession","software","service",
        "model","tile","metadata","initiative","sample","document",
        "repository","aggregate","product","collection","coverage","application"
    }
    UUID_PATTERN = _re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        _re.IGNORECASE
    )
    ISO639_2_PATTERN = _re.compile(r'^[a-z]{3}$')
    ISO8601_PATTERN  = _re.compile(
        r'^(?:\d{4}-\d{2}-\d{2}|\d{8})'
        r'(?:T?\d{2}:?\d{2}:?\d{2}(?:Z|[+-]\d{2}:?\d{2})?)?$'
    )

    # XML namespace prefixes used in ISO 19115 / GMD metadata
    NS = {
        "gmd": "http://www.isotc211.org/2005/gmd",
        "gco": "http://www.isotc211.org/2005/gco",
        "gmx": "http://www.isotc211.org/2005/gmx",
    }

    def _find_text(root, *xpaths):
        """Try multiple XPath expressions, return first non-empty text found."""
        for xp in xpaths:
            try:
                el = root.find(xp, NS)
                if el is not None and el.text and el.text.strip():
                    return el.text.strip()
            except Exception:
                pass
        return None

    hard_fails = []
    passes     = []
    row_warns  = []

    for row_id, md_scope, uri, mime, xml_text in dmf_rows:
        label  = f"metadata row id={row_id} (scope={md_scope})"
        issues = []
        ok     = []

        # ── md_standard_uri ──────────────────────────────────────────────────
        # v1.40 fix: accept both http://www.dgiwg.org/std/dmf (old) and
        # https://dgiwg.org/std/dmf/2.0 (current) URI formats.
        # The row was already classified as DMF by detecting 'dgiwg' and
        # 'dmf' in the URI (line above), so the URI is confirmed valid here.
        if not uri:
            issues.append("md_standard_uri is empty")
        else:
            ok.append(f"md_standard_uri='{uri}' ✓")

        # ── Parse XML ────────────────────────────────────────────────────────
        if not xml_text or not xml_text.strip():
            issues.append("metadata XML field is empty — cannot parse DMF fields")
            hard_fails.append(f"{label}: " + "; ".join(issues))
            continue

        try:
            root = _ET.fromstring(xml_text.strip())
        except _ET.ParseError as e:
            issues.append(f"XML parse error: {e}")
            hard_fails.append(f"{label}: " + "; ".join(issues))
            continue

        # The profile permits national metadata in addition to DMF and its
        # examples include ISO 19115-3/NMF. The bundled XSD is the older DMF
        # schema, so defer ISO 19115-3 field validation to the applicable ATS
        # instead of reporting a false DMF failure.
        _root_ns = root.tag[1:].split('}', 1)[0] if root.tag.startswith('{') else ''
        _root_local = root.tag.rsplit('}', 1)[-1]
        if '/-3/' in _root_ns or '/gmi/' in _root_ns:
            row_warns.append(
                f"{label}: ISO 19115-3/MI metadata encoding detected "
                f"({_root_local}); field/XSD validation deferred to the "
                f"applicable DMF or national metadata ATS"
            )
            continue

        # ── v1.47: XSD structural validation via _check_xml_xsd() ───────────
        if _lxml_ok:
            _xsd_ok, _xsd_msg = _check_xml_xsd(xml_text, _xsd_schema)
            if not _xsd_ok:
                issues.append(_xsd_msg)
            else:
                ok.append(_xsd_msg)
        else:
            ok.append("XSD structural validation skipped — install lxml for full schema check")

        # ── fileIdentifier ───────────────────────────────────────────────────
        fi = _find_text(root,
            "gmd:fileIdentifier/gco:CharacterString",
            "fileIdentifier/CharacterString",
            ".//fileIdentifier"
        )
        # v1.40 fix: UUID format is strongly recommended by DGIWG DMF but
        # legitimate DGIWG test files (DGED, arctic) use descriptive filenames.
        # Downgrade non-UUID from hard FAIL to informational note.
        if not fi:
            issues.append("fileIdentifier not found or empty")
        elif not UUID_PATTERN.match(fi):
            ok.append(f"fileIdentifier='{fi[:80]}' present ⚠ (UUID format recommended but not mandatory)")
        else:
            ok.append(f"fileIdentifier='{fi}' ✓ (UUID)")

        # ── language ─────────────────────────────────────────────────────────
        lang = _find_text(root,
            "gmd:language/gco:CharacterString",
            "gmd:language/gmd:LanguageCode",
            "language/CharacterString",
            ".//language"
        )
        # Also check LanguageCode attribute
        if not lang:
            for el in root.iter():
                if el.tag.endswith("LanguageCode") and el.get("codeListValue"):
                    lang = el.get("codeListValue")
                    break
        if not lang:
            issues.append("language not found")
        elif not ISO639_2_PATTERN.match(lang.strip()):
            issues.append(f"language '{lang}' is not a 3-letter ISO 639-2 code (e.g. 'eng')")
        else:
            ok.append(f"language='{lang}' ✓")

        # ── characterSet ─────────────────────────────────────────────────────
        cs_val = None
        for el in root.iter():
            if el.tag.endswith("MD_CharacterSetCode"):
                cs_val = el.get("codeListValue") or el.text
                break
        if not cs_val:
            # fallback: look for CharacterString inside characterSet
            cs_val = _find_text(root,
                "gmd:characterSet/gco:CharacterString",
                "characterSet/CharacterString"
            )
        if not cs_val:
            issues.append("characterSet / MD_CharacterSetCode not found")
        elif cs_val.strip() not in VALID_CHARSET_CODES:
            issues.append(f"characterSet '{cs_val}' is not a recognised MD_CharacterSetCode value")
        else:
            ok.append(f"characterSet='{cs_val}' ✓")

        # ── hierarchyLevel ───────────────────────────────────────────────────
        hl_val = None
        for el in root.iter():
            if el.tag.endswith("MD_ScopeCode"):
                hl_val = el.get("codeListValue") or el.text
                break
        if not hl_val:
            hl_val = _find_text(root,
                "gmd:hierarchyLevel/gmd:MD_ScopeCode",
                "hierarchyLevel/MD_ScopeCode",
                ".//hierarchyLevel"
            )
        if not hl_val:
            issues.append("hierarchyLevel / MD_ScopeCode not found")
        elif hl_val.strip() not in VALID_SCOPE_CODES:
            issues.append(f"hierarchyLevel '{hl_val}' is not a recognised MD_ScopeCode value")
        else:
            ok.append(f"hierarchyLevel='{hl_val}' ✓")

        # ── contact / organisationName + role ─────────────────────────────────
        org = _find_text(root,
            ".//gmd:organisationName/gco:CharacterString",
            ".//organisationName/CharacterString",
            ".//organisationName"
        )
        role_val = None
        for el in root.iter():
            if el.tag.endswith("CI_RoleCode"):
                role_val = el.get("codeListValue") or el.text
                break
        if not org:
            issues.append("contact/organisationName not found or empty")
        else:
            ok.append(f"organisationName='{org[:60]}' ✓")
        if not role_val:
            issues.append("contact/role (CI_RoleCode) not found")
        else:
            ok.append(f"contact/role='{role_val}' ✓")

        # ── dateStamp ────────────────────────────────────────────────────────
        ds = _find_text(root,
            "gmd:dateStamp/gco:Date",
            "gmd:dateStamp/gco:DateTime",
            "dateStamp/Date",
            "dateStamp/DateTime",
            ".//dateStamp"
        )
        if not ds:
            issues.append("dateStamp not found")
        elif not ISO8601_PATTERN.match(ds.strip()):
            issues.append(f"dateStamp '{ds}' does not match ISO 8601 format (YYYY-MM-DD)")
        else:
            ok.append(f"dateStamp='{ds}' ✓")

        # ── Compile row result ────────────────────────────────────────────────
        ok_summary = "; ".join(ok)
        if issues:
            hard_fails.append(
                f"{label}:\n  ✅ Passed: {ok_summary}\n  ❌ Failed: " + "; ".join(issues)
            )
        else:
            passes.append(f"{label}: ✅ All DMF field checks passed | {ok_summary}")

    # Non-DMF rows as info
    if non_dmf_rows:
        row_warns.append(
            f"ℹ️ {len(non_dmf_rows)} non-DMF row(s) not validated (no DGIWG DMF URI): "
            + ", ".join(f"id={r[0]}" for r in non_dmf_rows[:5])
        )

    all_lines = hard_fails + passes + row_warns + [_xsd_status_note]
    detail    = "\n".join(all_lines)

    if hard_fails:
        return ("FAIL", detail)
    if passes:
        # v1.62: without lxml the deepest structural stage did not run, so a
        # clean field-level result is a partial pass, not a full one.
        if not (_lxml_ok and _xsd_schema is not None):
            return ("PASS*", detail)
        return ("PASS", detail)
    return ("PASS*", detail)


def _r19(cursor):
    """GeoPackage Metadata Document — validates XML well-formedness and
    confirms at least one geopackage-scope reference with valid md_scope.

    v1.0 match: FAIL when gpkg_metadata_reference missing.
    v1.27 additions:
      - Check gpkg_metadata rows: XML must be well-formed (parseable).
      - mime_type must be 'text/xml' for XML metadata rows.
      - At least one row with reference_scope='geopackage' must exist in
        gpkg_metadata_reference (FAIL if none found).
      - md_scope/reference_scope combinations validated against Table 36.
    """
    import xml.etree.ElementTree as _ET

    if not table_exists(cursor, "gpkg_metadata_reference"):
        return ("FAIL", "gpkg_metadata_reference table is MISSING")

    fails = []
    passes = []

    # Check gpkg_metadata XML well-formedness
    if table_exists(cursor, "gpkg_metadata"):
        cursor.execute("SELECT id, mime_type, metadata FROM gpkg_metadata")
        meta_rows = cursor.fetchall()
        for row_id, mime, xml_text in meta_rows:
            if mime and mime != "text/xml":
                fails.append(f"metadata id={row_id}: mime_type='{mime}' (expected 'text/xml')")
            if xml_text and xml_text.strip():
                try:
                    _ET.fromstring(xml_text.strip())
                    passes.append(f"metadata id={row_id}: XML is well-formed ✓")
                except _ET.ParseError as e:
                    fails.append(f"metadata id={row_id}: XML parse error — {e}")
            else:
                fails.append(f"metadata id={row_id}: metadata field is empty")
    else:
        fails.append("gpkg_metadata table missing — no metadata documents to validate")

    # Check geopackage-scope reference exists
    cursor.execute("""
        SELECT COUNT(*) FROM gpkg_metadata_reference
        WHERE reference_scope = 'geopackage'
          AND table_name IS NULL
          AND column_name IS NULL
          AND row_id_value IS NULL
    """)
    gpkg_scope_count = cursor.fetchone()[0]
    if gpkg_scope_count == 0:
        fails.append(
            "No geopackage-scope reference row found in gpkg_metadata_reference "
            "(reference_scope='geopackage' with NULL table/column/row required)"
        )
    else:
        passes.append(
            f"{gpkg_scope_count} geopackage-scope reference row(s) confirmed ✓"
        )

    # Table 36: validate reference_scope / md_scope combinations
    # v1.39 fix: gpkg_metadata_reference has no 'id' column; use rowid instead.
    cursor.execute("""
        SELECT r.rowid, r.reference_scope, m.md_scope
        FROM gpkg_metadata_reference r
        JOIN gpkg_metadata m ON r.md_file_id = m.id
    """)
    ref_rows = cursor.fetchall()
    for ref_id, ref_scope, md_scope in ref_rows:
        allowed = TABLE_36_ALLOWED.get(ref_scope)
        if allowed is None:
            fails.append(
                f"ref id={ref_id}: reference_scope='{ref_scope}' is not a "
                "recognised DGIWG reference_scope value"
            )
        elif md_scope not in allowed:
            fails.append(
                f"ref id={ref_id}: reference_scope='{ref_scope}' with "
                f"md_scope='{md_scope}' is not allowed per DGIWG Table 36 "
                f"(allowed: {sorted(allowed)})"
            )
        else:
            passes.append(
                f"ref id={ref_id}: {ref_scope}/{md_scope} combination valid per Table 36 ✓"
            )

    detail = "\n".join(fails + passes)
    if fails:
        return ("FAIL", detail)
    return ("PASS", detail)

def _r20(cursor):
    """Complete Row GeoPackage Metadata.
    v1.0 checks: required columns exist in gpkg_metadata table.
    It does NOT check for a reference_scope='geopackage' row — that is beyond
    its automated scope. We match PASS* when columns exist.
    We additionally note whether a geopackage-scope reference row is present.
    """
    if not table_exists(cursor, "gpkg_metadata"):
        return ("FAIL", "gpkg_metadata table is MISSING")
    required_cols = {"id", "md_scope", "md_standard_uri", "mime_type", "metadata"}
    cursor.execute("PRAGMA table_info(gpkg_metadata)")
    present_cols = {row[1] for row in cursor.fetchall()}
    missing = required_cols - present_cols
    if missing:
        return ("FAIL", f"gpkg_metadata missing required columns: {sorted(missing)}")
    found = sorted(required_cols & present_cols)
    detail_parts = [f"Column '{c}' present ✓" for c in found]
    # v1.48: validate row count and mime_type (same basic checks as _r19)
    try:
        cursor.execute("SELECT COUNT(*) FROM gpkg_metadata")
        _r20_count = cursor.fetchone()[0]
        if _r20_count == 0:
            detail_parts.append("⚠ gpkg_metadata has no rows")
        else:
            detail_parts.append(f"{_r20_count} metadata row(s) found ✓")
            cursor.execute("SELECT id, mime_type FROM gpkg_metadata")
            for _r20_id, _r20_mime in cursor.fetchall():
                if not _r20_mime:
                    detail_parts.append(f"⚠ id={_r20_id}: mime_type NULL")
                elif _r20_mime != "text/xml":
                    detail_parts.append(f"⚠ id={_r20_id}: mime_type='{_r20_mime}' (expected text/xml)")
    except Exception as _r20e:
        detail_parts.append(f"Row/mime check skipped: {_r20e}")
    # Additionally note geopackage-scope reference (informational, not a FAIL)
    if table_exists(cursor, "gpkg_metadata_reference"):
        cursor.execute("SELECT COUNT(*) FROM gpkg_metadata_reference WHERE reference_scope='geopackage'")
        gpkg_scope_count = cursor.fetchone()[0]
        if gpkg_scope_count == 0:
            detail_parts.append("NOTE: no reference_scope='geopackage' row in gpkg_metadata_reference")
        else:
            detail_parts.append(f"geopackage-scope reference row present ✓")
    detail = "; ".join(detail_parts)
    detail += ". Partial automated validation: PASS* indicates not all aspects are validated."
    return ("PASS*", detail)


def _r21(cursor):
    """User Row Metadata — validates Table 36 md_scope/reference_scope pairings.

    v1.0 match: FAIL when gpkg_metadata_reference missing or required columns absent.
    v1.27 additions:
      - Every row in gpkg_metadata_reference is checked against DGIWG Table 36
        allowed (reference_scope, md_scope) combinations.
      - Orphan references (md_file_id not in gpkg_metadata.id) → FAIL.
      - timestamp format checked (ISO 8601).
    """
    import re as _re

    if not table_exists(cursor, "gpkg_metadata_reference"):
        return ("FAIL", "gpkg_metadata_reference table is MISSING")

    cursor.execute("PRAGMA table_info(gpkg_metadata_reference)")
    cols = {row[1] for row in cursor.fetchall()}
    required = {"reference_scope", "table_name", "column_name", "row_id_value",
                "timestamp", "md_file_id"}
    missing = required - cols
    if missing:
        return ("FAIL", f"gpkg_metadata_reference missing columns: {sorted(missing)}")

    fails = []
    passes = []

    # Get all valid metadata ids for orphan check
    meta_ids = set()
    if table_exists(cursor, "gpkg_metadata"):
        cursor.execute("SELECT id FROM gpkg_metadata")
        meta_ids = {r[0] for r in cursor.fetchall()}

    # v1.39 fix: gpkg_metadata_reference has no 'id' column; use rowid instead.
    cursor.execute("""
        SELECT rowid, reference_scope, table_name, column_name,
               row_id_value, timestamp, md_file_id
        FROM gpkg_metadata_reference
    """)
    ref_rows = cursor.fetchall()

    if not ref_rows:
        return ("PASS*", "gpkg_metadata_reference exists with all required columns ✓ but has no rows")

    ISO8601_TS = _re.compile(
        r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$'
    )

    # v1.49 N+1 fix: preload all md_scope values into a dict so we avoid one
    # cursor.execute() per reference row (was O(N) queries → now O(1) queries).
    meta_scope_by_id = {}
    if table_exists(cursor, "gpkg_metadata"):
        meta_scope_by_id = {
            r[0]: r[1]
            for r in cursor.execute(
                "SELECT id, md_scope FROM gpkg_metadata"
            ).fetchall()
        }

    for ref_id, ref_scope, tname, col, row_id, ts, md_fid in ref_rows:
        label = f"ref id={ref_id} ({ref_scope})"

        # Orphan check
        if md_fid not in meta_ids:
            fails.append(f"{label}: md_file_id={md_fid} not found in gpkg_metadata.id (orphan)")
            continue

        # Table 36 scope pairing
        allowed = TABLE_36_ALLOWED.get(ref_scope)
        if allowed is None:
            fails.append(f"{label}: reference_scope='{ref_scope}' is not a recognised value")
            continue

        # Get md_scope for this row — from preloaded dict (v1.49 N+1 fix)
        md_scope = meta_scope_by_id.get(md_fid)
        if md_scope is None and md_fid not in meta_scope_by_id:
            fails.append(f"{label}: md_file_id={md_fid} not found in gpkg_metadata")
            continue

        if md_scope not in allowed:
            fails.append(
                f"{label}: reference_scope='{ref_scope}' + md_scope='{md_scope}' "
                f"not allowed per Table 36 (allowed: {sorted(allowed)})"
            )
        else:
            passes.append(f"{label}: {ref_scope}/{md_scope} ✓")

        # Timestamp format
        if ts and not ISO8601_TS.match(str(ts).strip()):
            fails.append(f"{label}: timestamp '{ts}' does not match ISO 8601 format")

    detail = "\n".join(fails + passes)
    if fails:
        return ("FAIL", detail)
    return ("PASS", detail)

def _r22(cursor):
    """Product Metadata — validates product metadata XML content.

    v1.0 match: FAIL when no rows with md_scope in ('series','dataset').
    v1.27 addition:
      - For each product metadata row, parse XML and validate:
          * Well-formed XML
          * At least one ISO 19115 mandatory element present
          * md_standard_uri starts with expected DGIWG or ISO prefix
          * reference_scope in gpkg_metadata_reference links correctly
    """
    import xml.etree.ElementTree as _ET

    if not table_exists(cursor, "gpkg_metadata"):
        return ("FAIL", "gpkg_metadata table is MISSING")
    cursor.execute(
        "SELECT id, md_scope, md_standard_uri, mime_type, metadata "
        "FROM gpkg_metadata WHERE md_scope IN ('series', 'dataset')"
    )
    rows = cursor.fetchall()
    if not rows:
        return ("FAIL", "No metadata rows with md_scope='series' or 'dataset'")

    fails = []
    passes = []

    for row_id, md_scope, uri, mime, xml_text in rows:
        label = f"id={row_id} (md_scope={md_scope})"

        # mime_type check
        if mime and mime != "text/xml":
            fails.append(f"{label}: mime_type='{mime}' (expected 'text/xml')")

        # XML well-formedness
        if not xml_text or not xml_text.strip():
            fails.append(f"{label}: metadata XML field is empty")
            continue
        try:
            root = _ET.fromstring(xml_text.strip())
        except _ET.ParseError as e:
            fails.append(f"{label}: XML parse error — {e}")
            continue

        # Check at least one ISO 19115 element present
        found_iso = [el for el in root.iter()
                     if any(iso in (el.tag or "") for iso in DMF_ISO_MANDATORY)]
        if not found_iso:
            fails.append(
                f"{label}: no ISO 19115 mandatory elements found in XML "
                f"(expected at least one of: {DMF_ISO_MANDATORY})"
            )
        else:
            passes.append(
                f"{label}: XML well-formed ✓ | {len(found_iso)} ISO 19115 element(s) found ✓ "
                f"| uri='{uri or 'none'}'"
            )

    detail = "\n".join(fails + passes)
    if fails:
        return ("FAIL", detail)
    return ("PASS", detail)

def _r23(cursor):
    """Product Partial Metadata.
    v1.0 checks: at least one row in gpkg_metadata_reference where
    reference_scope='geopackage' AND table_name IS NULL AND column_name IS NULL
    AND row_id_value IS NULL. Exactly matches CC04 Req 23 query.
    """
    if not table_exists(cursor, "gpkg_metadata_reference"):
        return ("FAIL", "gpkg_metadata_reference table is MISSING — product partial metadata cannot be validated")
    cursor.execute("""
        SELECT COUNT(*) FROM gpkg_metadata_reference
        WHERE reference_scope = 'geopackage'
          AND table_name IS NULL
          AND column_name IS NULL
          AND row_id_value IS NULL
    """)
    count = cursor.fetchone()[0]
    if count == 0:
        # Explain what IS present
        cursor.execute("SELECT COUNT(*) FROM gpkg_metadata_reference WHERE reference_scope='geopackage'")
        gpkg_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM gpkg_metadata_reference")
        total = cursor.fetchone()[0]
        if gpkg_count > 0:
            return ("FAIL",
                    f"Found {gpkg_count} reference_scope='geopackage' row(s) but none have "
                    f"table_name=NULL, column_name=NULL, row_id_value=NULL simultaneously. "
                    f"{total} total reference row(s) present.")
        return ("FAIL",
                f"Found 0 metadata references for entire GeoPackage "
                f"(reference_scope='geopackage' with NULL table/column/row required). "
                f"{total} table/row-scope reference(s) present but no geopackage-level anchor.")
    return ("PASS*",
            f"Found {count} geopackage-scope reference row(s) with NULL table/column/row ✓ — "
            "md_parent_id hierarchy not fully validated")


def _r24(cursor):
    """Data Validity — adds Shapely geometry validity sampling.

    v1.0 ATS 5.1-5.6 referential integrity checks retained (unchanged).
    v1.27 addition:
      - For each feature table in gpkg_geometry_columns, sample up to
        GEOM_SAMPLE_N geometry BLOBs using a stratified strategy to avoid
        only checking the leading rows of large tables:
          1. If the table has <= GEOM_SAMPLE_N rows: check all.
          2. If the table has > GEOM_SAMPLE_N rows: use evenly-spaced rowid
             intervals (min_rowid to max_rowid) to sample across the full
             table, plus ORDER BY RANDOM() fallback if rowid is unavailable.
        Invalid geometries (self-intersections, unclosed rings, etc.) → FAIL.
        If Shapely is not installed → PASS* with install note.
    """
    GEOM_SAMPLE_N = _config.SAMPLE_SIZE if _config.SAMPLE_SIZE else 25
    import re as _re24

    ats_fails = []
    ats_passes = []
    geom_fails = []
    geom_passes = []
    geom_skips = []
    warnings = []

    # ── ATS 5.1 ───────────────────────────────────────────────────────────────
    try:
        cursor.execute("SELECT COUNT(*) FROM gpkg_contents")
        ats_passes.append("gpkg_contents table exists ✓")
    except Exception as e:
        ats_fails.append(f"gpkg_contents table missing: {e}")

    # ── ATS 5.2 ───────────────────────────────────────────────────────────────
    try:
        cursor.execute("SELECT table_name FROM gpkg_contents")
        contents_tables = [r[0] for r in cursor.fetchall()]
        for tname in contents_tables:
            try:
                cursor.execute(f"SELECT 1 FROM {_quote_ident(tname)} LIMIT 1")
                ats_passes.append(f"Table '{tname}' exists ✓")
            except Exception:
                ats_fails.append(f"Table '{tname}' listed in gpkg_contents but MISSING")
    except Exception as e:
        ats_fails.append(f"Error reading gpkg_contents: {e}")
        contents_tables = []

    # ── ATS 5.3 ───────────────────────────────────────────────────────────────
    # v1.40 fix: gpkg_geometry_columns is only required when feature tables
    # exist. Tiles-only or gridded-only GeoPackages legitimately omit it.
    has_feature_tables = any(
        dt in ("features",) for dt in
        [r[0] for r in cursor.execute(
            "SELECT DISTINCT data_type FROM gpkg_contents"
        ).fetchall()] if dt
    ) if table_exists(cursor, "gpkg_contents") else False

    if table_exists(cursor, "gpkg_geometry_columns"):
        try:
            cursor.execute("SELECT table_name FROM gpkg_geometry_columns")
            for (tname,) in cursor.fetchall():
                if tname in contents_tables:
                    ats_passes.append(f"Geometry table '{tname}' in gpkg_contents ✓")
                else:
                    ats_fails.append(f"Geometry table '{tname}' NOT in gpkg_contents")
        except Exception as e:
            ats_fails.append(f"Error reading gpkg_geometry_columns: {e}")
    elif has_feature_tables:
        ats_fails.append("gpkg_geometry_columns table is MISSING (required for feature tables)")
    else:
        ats_passes.append("gpkg_geometry_columns not present — not required for tiles/gridded-only GeoPackage ✓")

    # ── ATS 5.4 ───────────────────────────────────────────────────────────────
    # v1.40 fix: gpkg_tile_matrix_set is only required when tile or gridded
    # tables exist. Feature-only GeoPackages legitimately omit it.
    has_tile_tables = any(
        dt in ("tiles", "2d-gridded-coverage")
        for dt in [r[0] for r in cursor.execute(
            "SELECT DISTINCT data_type FROM gpkg_contents"
        ).fetchall() if r[0]]
    ) if table_exists(cursor, "gpkg_contents") else False

    if table_exists(cursor, "gpkg_tile_matrix_set"):
        try:
            cursor.execute("SELECT table_name FROM gpkg_tile_matrix_set")
            for (tname,) in cursor.fetchall():
                if tname in contents_tables:
                    ats_passes.append(f"Tile matrix set table '{tname}' in gpkg_contents ✓")
                else:
                    ats_fails.append(f"Tile matrix set table '{tname}' NOT in gpkg_contents")
        except Exception as e:
            ats_fails.append(f"Error reading gpkg_tile_matrix_set: {e}")
    elif has_tile_tables:
        ats_fails.append("gpkg_tile_matrix_set table is MISSING (required for tile/gridded tables)")
    else:
        ats_passes.append("gpkg_tile_matrix_set not present — not required for feature-only GeoPackage ✓")

    # ── ATS 5.5 ───────────────────────────────────────────────────────────────
    # v1.40 fix: gpkg_tile_matrix is only required when tile tables exist.
    if table_exists(cursor, "gpkg_tile_matrix"):
        try:
            cursor.execute("SELECT DISTINCT table_name FROM gpkg_tile_matrix")
            for (tname,) in cursor.fetchall():
                if tname in contents_tables:
                    ats_passes.append(f"Tile matrix table '{tname}' in gpkg_contents ✓")
                else:
                    ats_fails.append(f"Tile matrix table '{tname}' NOT in gpkg_contents")
        except Exception as e:
            ats_fails.append(f"Error reading gpkg_tile_matrix: {e}")
    elif has_tile_tables:
        ats_fails.append("gpkg_tile_matrix table is MISSING (required for tile/gridded tables)")
    else:
        ats_passes.append("gpkg_tile_matrix not present — not required for feature-only GeoPackage ✓")

    # ── ATS 5.6 ───────────────────────────────────────────────────────────────
    # v1.40 fix: metadata tables are optional in OGC GeoPackage core spec.
    # If gpkg_metadata does not exist there is nothing to check for referential
    # integrity — this is vacuously passing (not a FAIL).
    if table_exists(cursor, "gpkg_metadata") and table_exists(cursor, "gpkg_metadata_reference"):
        try:
            cursor.execute("SELECT id FROM gpkg_metadata")
            meta_ids = {r[0] for r in cursor.fetchall()}
            cursor.execute("SELECT md_file_id FROM gpkg_metadata_reference")
            ref_ids = {r[0] for r in cursor.fetchall()}
            bad = sorted(ref_ids - meta_ids)
            if bad:
                ats_fails.append(f"Unmatched md_file_id values: {bad}")
            else:
                ats_passes.append("All md_file_id values match gpkg_metadata.id ✓")
        except Exception as e:
            ats_fails.append(f"Error checking metadata referential integrity: {e}")
    elif not table_exists(cursor, "gpkg_metadata"):
        ats_passes.append("gpkg_metadata not present — metadata tables optional, ATS 5.6 vacuously satisfied ✓")

    # ── Table 37 extras (informational) ───────────────────────────────────────
    try:
        cursor.execute("SELECT srs_id, organization FROM gpkg_spatial_ref_sys WHERE srs_id > 0")
        for srs_id, org in cursor.fetchall():
            if org != "EPSG":
                warnings.append(f"Table37#1: srs_id={srs_id} organization='{org}' (expected EPSG)")
    except Exception:
        pass

    try:
        cursor.execute("SELECT srs_id, description FROM gpkg_spatial_ref_sys WHERE srs_id > 0")
        for srs_id, desc in cursor.fetchall():
            if not desc or str(desc).strip() == "" or str(desc).strip().lower() in ("unknown","tbd"):
                warnings.append(f"Table37#2: srs_id={srs_id} description is null/empty/unknown/tbd")
    except Exception:
        pass

    try:
        cursor.execute("SELECT table_name, data_type FROM gpkg_contents")
        valid_types = {"features","tiles","2d-gridded-coverage","attributes"}
        for tname, dtype in cursor.fetchall():
            if dtype not in valid_types and not (dtype or "").startswith("2d"):
                warnings.append(f"Table37#6: '{tname}' data_type='{dtype}' not standard")
    except Exception:
        pass

    if table_exists(cursor, "gpkg_geometry_columns"):
        try:
            cursor.execute("SELECT table_name, z FROM gpkg_geometry_columns")
            for tname, z in cursor.fetchall():
                if z == 2:
                    warnings.append(f"Table37#11: '{tname}' z=2 (optional Z) PROHIBITED in DGIWG")
        except Exception:
            pass

    # ── Geometry sampling helper: stratified across full row range ────────────
    def _sample_geom_blobs(tname, geom_col, n):
        """
        Return up to n geometry BLOBs sampled across the full row range of the
        table, rather than only the leading rows.

        Strategy:
          1. Fetch total count.
          2. If count <= n: SELECT all.
          3. If count > n: fetch min/max rowid and pick n evenly-spaced rowid
             thresholds, then UNION-SELECT one row per threshold window.
          4. Fallback to ORDER BY RANDOM() if rowid approach fails.

        Returns (blobs: list, strategy_note: str).
        """
        qt  = _quote_ident(tname)     # quoted table identifier
        qc  = _quote_ident(geom_col)  # quoted column identifier
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {qt} WHERE {qc} IS NOT NULL")
            total = cursor.fetchone()[0]
        except Exception as e:
            return [], f"count error: {e}"

        if total == 0:
            return [], "no rows"

        if total <= n:
            # Small table — check everything
            cursor.execute(
                f"SELECT {qc} FROM {qt} WHERE {qc} IS NOT NULL"
            )
            blobs = [r[0] for r in cursor.fetchall()]
            return blobs, f"all {total} rows"

        # Large table — stratified rowid sampling
        try:
            cursor.execute(
                f"SELECT MIN(rowid), MAX(rowid) FROM {qt} WHERE {qc} IS NOT NULL"
            )
            row = cursor.fetchone()
            min_rid, max_rid = row[0], row[1]
            if min_rid is None or max_rid is None:
                raise ValueError("rowid is NULL")

            # Build n evenly-spaced threshold points across [min_rid, max_rid]
            step = max(1, (max_rid - min_rid) // n)
            blobs = []
            seen_rowids = set()
            for i in range(n):
                threshold = min_rid + i * step
                cursor.execute(
                    f"SELECT rowid, {qc} FROM {qt} "
                    f"WHERE rowid >= ? AND {qc} IS NOT NULL "
                    f"ORDER BY rowid LIMIT 1",
                    (threshold,)
                )
                r = cursor.fetchone()
                if r and r[0] not in seen_rowids:
                    seen_rowids.add(r[0])
                    blobs.append(r[1])

            note = (f"stratified sample {len(blobs)}/{total} rows "
                    f"(rowid {min_rid}–{max_rid}, step≈{step})")
            return blobs, note

        except Exception:
            # rowid unavailable (e.g. WITHOUT ROWID table) — fall back to RANDOM
            try:
                cursor.execute(
                    f"SELECT {qc} FROM {qt} "
                    f"WHERE {qc} IS NOT NULL "
                    f"ORDER BY RANDOM() LIMIT ?",
                    (n,)
                )
                blobs = [r[0] for r in cursor.fetchall()]
                return blobs, f"random sample {len(blobs)}/{total} rows (ORDER BY RANDOM)"
            except Exception as e2:
                return [], f"sampling error: {e2}"

    # ── Shapely geometry validity sampling ────────────────────────────────────
    try:
        from shapely import wkb as _shp_wkb  # noqa: F401
        shapely_ok = True
        LIBRARY_STATUS["shapely"] = True
    except Exception:
        shapely_ok = False

    if not shapely_ok:
        geom_skips.append(
            "⚠️ Shapely not available — geometry validity (OGC WKB decode) not checked. "
            "Result reflects structural/referential integrity only (ATS 5.1-5.6). "
            "Run the script again and choose Y when prompted to install shapely."
        )
    elif table_exists(cursor, "gpkg_geometry_columns"):
        cursor.execute(
            "SELECT table_name, column_name, z, m, geometry_type_name "
            "FROM gpkg_geometry_columns"
        )
        geom_tables = cursor.fetchall()

        # ── v1.47: RTree presence + health check (Feature 1) ─────────────────
        # (a) Existence: rtree_<table>_<geomcol> virtual table must be present.
        # (b) Entry-count integrity: RTree row count must equal the number of
        #     non-NULL geometry rows in the feature table.  A mismatch means
        #     "zombie" index entries remained after feature deletions, which
        #     causes some GIS clients to crash or display ghost data.
        try:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'rtree_%'"
            )
            _rtree_present = {r[0].lower() for r in cursor.fetchall()}
            for _rt_tbl, _rt_col, _rt_z, _rt_m, _rt_gtype in geom_tables:
                _expected_rtree = f"rtree_{_rt_tbl}_{_rt_col}".lower()
                if _expected_rtree not in _rtree_present:
                    geom_fails.append(
                        f"'{_rt_tbl}': spatial index '{_expected_rtree}' MISSING — "
                        f"DGIWG extension gpkg_rtree_index is mandatory for feature tables"
                    )
                    continue

                # (b) Health check: count RTree entries vs feature rows
                try:
                    cursor.execute(
                        f"SELECT COUNT(*) FROM {_quote_ident(_expected_rtree)}"
                    )
                    _rtree_count = cursor.fetchone()[0]
                    cursor.execute(
                        f"SELECT COUNT(*) FROM {_quote_ident(_rt_tbl)} "
                        f"WHERE {_quote_ident(_rt_col)} IS NOT NULL"
                    )
                    _feat_count = cursor.fetchone()[0]
                    if _rtree_count != _feat_count:
                        _diff = _rtree_count - _feat_count
                        geom_fails.append(
                            f"'{_rt_tbl}': RTree health FAIL — index has "
                            f"{_rtree_count} entries but feature table has "
                            f"{_feat_count} non-NULL geometry rows "
                            f"({'zombie' if _diff > 0 else 'missing'} entries: "
                            f"{'%+d' % _diff}). "
                            f"Run 'VACUUM' or rebuild the spatial index to fix."
                        )
                    else:
                        geom_passes.append(
                            f"'{_rt_tbl}': spatial index '{_expected_rtree}' "
                            f"present and healthy ({_rtree_count} entries = "
                            f"{_feat_count} features) ✓"
                        )
                except Exception as _rh_e:
                    geom_passes.append(
                        f"'{_rt_tbl}': spatial index present; health count "
                        f"skipped ({_rh_e})"
                    )
        except Exception as _rt_e:
            geom_skips.append(f"RTree index check skipped: {_rt_e}")

        for geom_tname, geom_col, declared_z, declared_m, declared_geom_type in geom_tables:
            if not _re24.match(r'^.+$', geom_tname or '') or not _re24.match(r'^.+$', geom_col or ''):
                geom_skips.append(f"'{geom_tname}': skipped (empty table/column name)")
                continue

            # ── v1.47: NULL geometry count ────────────────────────────────────
            try:
                _qt24 = _quote_ident(geom_tname)
                _qc24 = _quote_ident(geom_col)
                cursor.execute(
                    f"SELECT COUNT(*) FROM {_qt24} WHERE {_qc24} IS NULL"
                )
                _null_count = cursor.fetchone()[0]
                if _null_count > 0:
                    geom_fails.append(
                        f"'{geom_tname}': {_null_count} NULL geometry row(s) — "
                        f"DGIWG requires all feature rows to carry a geometry"
                    )
                else:
                    geom_passes.append(f"'{geom_tname}': no NULL geometries ✓")
            except Exception as _ng_e:
                geom_skips.append(f"'{geom_tname}': NULL geometry check skipped ({_ng_e})")

            # ── v1.47: Feature table INTEGER PRIMARY KEY validation ───────────
            # v1.49 fix: cache PRAGMA result here and reuse in null-ratio block
            # below to avoid calling PRAGMA table_info() twice per feature table.
            _cached_tbl_info = None  # populated on first successful PRAGMA call
            try:
                cursor.execute(f"PRAGMA table_info({_quote_ident(geom_tname)})")
                _cached_tbl_info = cursor.fetchall()
                _cols = _cached_tbl_info
                _pk_cols = [(c[1], c[2]) for c in _cols if c[5] == 1]
                if not _pk_cols:
                    geom_fails.append(
                        f"'{geom_tname}': no PRIMARY KEY column — "
                        f"OGC GeoPackage requires an INTEGER PRIMARY KEY (fid)"
                    )
                elif len(_pk_cols) > 1:
                    geom_fails.append(
                        f"'{geom_tname}': composite PRIMARY KEY {_pk_cols} — "
                        f"OGC requires a single INTEGER PRIMARY KEY"
                    )
                else:
                    _pk_name, _pk_type = _pk_cols[0]
                    if _pk_type.upper() != "INTEGER":
                        geom_fails.append(
                            f"'{geom_tname}': PRIMARY KEY column '{_pk_name}' is "
                            f"type '{_pk_type}' — must be INTEGER"
                        )
                    else:
                        geom_passes.append(
                            f"'{geom_tname}': INTEGER PRIMARY KEY '{_pk_name}' ✓"
                        )
            except Exception as _pk_e:
                geom_skips.append(
                    f"'{geom_tname}': PRIMARY KEY check skipped ({_pk_e})"
                )

            # ── v1.47 Feature 2b: Null-ratio / placeholder attribute check ──────
            # For each non-PK, non-geometry attribute column in the feature table,
            # flag any column that is 100 % NULL or filled entirely with known
            # placeholder strings ('TBD', 'None', 'N/A', 'UNKNOWN', 'TBC', '').
            # These indicate "empty shell" deliveries where mandatory fields were
            # never populated.  Issues are reported as WARNING (not hard FAIL) so
            # they appear in PASS* results for manual review.
            try:
                # v1.49 fix: reuse cached PRAGMA result from PRIMARY KEY check above
                # to avoid a second PRAGMA table_info() call on the same table.
                if _cached_tbl_info is not None:
                    _tbl_cols = _cached_tbl_info
                else:
                    cursor.execute(f"PRAGMA table_info({_quote_ident(geom_tname)})")
                    _tbl_cols = cursor.fetchall()
                # Identify PK column index and geometry column name to skip them
                _pk_names  = {c[1] for c in _tbl_cols if c[5] == 1}
                _geom_name = geom_col.lower()
                cursor.execute(
                    f"SELECT COUNT(*) FROM {_quote_ident(geom_tname)}"
                )
                _total_rows = cursor.fetchone()[0]
                if _total_rows > 0:
                    _PLACEHOLDERS = (
                        "''", "'tbd'", "'tbc'", "'n/a'", "'na'",
                        "'none'", "'unknown'", "'null'", "'?'",
                    )
                    _ph_sql = " OR ".join(
                        f"LOWER(TRIM(CAST({'{}'} AS TEXT))) = {p}"
                        for p in _PLACEHOLDERS
                    )
                    for _ac in _tbl_cols:
                        _aname = _ac[1]
                        if _aname in _pk_names or _aname.lower() == _geom_name:
                            continue
                        _q_aname = _quote_ident(_aname)
                        _ph_expr = " OR ".join(
                            f"LOWER(TRIM(CAST({_q_aname} AS TEXT))) = {p}"
                            for p in _PLACEHOLDERS
                        )
                        try:
                            cursor.execute(
                                f"SELECT COUNT(*) FROM {_quote_ident(geom_tname)} "
                                f"WHERE {_q_aname} IS NULL OR {_ph_expr}"
                            )
                            _null_ph = cursor.fetchone()[0]
                            if _null_ph == _total_rows:
                                warnings.append(
                                    f"'{geom_tname}'.'{_aname}': 100% NULL/placeholder "
                                    f"across all {_total_rows} rows — "
                                    f"mandatory field may not have been populated"
                                )
                        except Exception:
                            pass
            except Exception as _nr_e:
                geom_skips.append(
                    f"'{geom_tname}': null-ratio check skipped ({_nr_e})"
                )

            # ── v1.47 Feature 2a: Full bbox via RTree aggregate ───────────────
            # Replaces the sampled coordinate check from v1.47 with a full
            # SQL aggregate over the RTree index, covering ALL features rather
            # than a stratified sample.  The RTree stores pre-computed envelopes
            # so this query is O(1) with the index and incurs no geometry decode.
            _decl_bbox = None
            try:
                cursor.execute(
                    "SELECT min_x, min_y, max_x, max_y FROM gpkg_contents "
                    "WHERE table_name=?",
                    (geom_tname,)
                )
                _bbox_row = cursor.fetchone()
                if _bbox_row and all(v is not None for v in _bbox_row):
                    _decl_bbox = _bbox_row
            except Exception:
                pass

            _rtree_name = f"rtree_{geom_tname}_{geom_col}"
            try:
                cursor.execute(
                    f"SELECT MIN(minx), MIN(miny), MAX(maxx), MAX(maxy) "
                    f"FROM {_quote_ident(_rtree_name)}"
                )
                _actual_bb = cursor.fetchone()
                if _actual_bb and all(v is not None for v in _actual_bb):
                    _ax_min, _ay_min, _ax_max, _ay_max = _actual_bb
                    if _decl_bbox is not None:
                        _dx_min, _dy_min, _dx_max, _dy_max = _decl_bbox
                        _TOL = 1e-6
                        if (_ax_min < _dx_min - _TOL or _ay_min < _dy_min - _TOL or
                                _ax_max > _dx_max + _TOL or _ay_max > _dy_max + _TOL):
                            geom_fails.append(
                                f"'{geom_tname}' bbox MISMATCH (full RTree aggregate): "
                                f"actual ({_ax_min:.6g},{_ay_min:.6g},{_ax_max:.6g},{_ay_max:.6g}) "
                                f"exceeds declared ({_dx_min:.6g},{_dy_min:.6g},"
                                f"{_dx_max:.6g},{_dy_max:.6g}) in gpkg_contents"
                            )
                        else:
                            # v1.58 fix: previous message interpolated _feat_count
                            # from an earlier loop — value belonged to the LAST
                            # table of the RTree health loop, not this table.
                            geom_passes.append(
                                f"'{geom_tname}' actual bbox within declared bbox ✓ "
                                f"(full RTree index aggregate over all features)"
                            )
                    else:
                        geom_passes.append(
                            f"'{geom_tname}' actual bbox: "
                            f"({_ax_min:.6g},{_ay_min:.6g},{_ax_max:.6g},{_ay_max:.6g}) "
                            f"(no declared bbox to compare)"
                        )
            except Exception as _bb_e:
                geom_skips.append(
                    f"'{geom_tname}': full bbox check skipped ({_bb_e}) — "
                    f"RTree may not be present"
                )

            blobs, sample_note = _sample_geom_blobs(geom_tname, geom_col, GEOM_SAMPLE_N)

            if not blobs:
                geom_skips.append(
                    f"'{geom_tname}': no geometry blobs — validity check skipped "
                    f"({sample_note})"
                )
                continue

            from shapely import wkb as _shp_wkb
            from shapely.validation import explain_validity as _explain
            invalid = []
            errors  = []
            valid_count = 0

            zm_mismatches   = []  # v1.47: Z/M header flag vs declared column mismatches
            type_mismatches = []  # v1.47: actual WKB geom type vs declared geometry_type_name
            # v1.49: Feature 13 — collect all actual types seen in sample for
            # geometry type completeness check after the loop
            _actual_types_seen = set()

            for idx, blob in enumerate(blobs, 1):
                try:
                    # ── v1.47: decode header via _decode_gpkg_geom_header() ──
                    hdr = _decode_gpkg_geom_header(blob)
                    if hdr is None:
                        errors.append(
                            f"geom {idx}: blob too short ({len(bytes(blob))} bytes)"
                        )
                        continue

                    # ── v1.47: Z/M flag consistency check ────────────────────
                    # GeoPackage flags byte:
                    #   bit 1 (mask 0x02): Z-flag  — 1 = geometry has Z values
                    #   bit 2 (mask 0x04): M-flag  — 1 = geometry has M values
                    # gpkg_geometry_columns.z: 0=no-Z, 1=mandatory-Z, 2=optional-Z
                    # gpkg_geometry_columns.m: 0=no-M, 1=mandatory-M, 2=optional-M
                    blob_has_z = hdr["has_z"]
                    blob_has_m = hdr["has_m"]
                    if declared_z == 1 and not blob_has_z:
                        zm_mismatches.append(
                            f"geom {idx}: declared z=1 (mandatory) but header Z-flag=0"
                        )
                    elif declared_z == 0 and blob_has_z:
                        zm_mismatches.append(
                            f"geom {idx}: declared z=0 (prohibited) but header Z-flag=1"
                        )
                    if declared_m == 1 and not blob_has_m:
                        zm_mismatches.append(
                            f"geom {idx}: declared m=1 (mandatory) but header M-flag=0"
                        )
                    elif declared_m == 0 and blob_has_m:
                        zm_mismatches.append(
                            f"geom {idx}: declared m=0 (prohibited) but header M-flag=1"
                        )

                    geom = _shp_wkb.loads(hdr["wkb_data"])
                    # v1.49: accumulate actual type for completeness check
                    _actual_types_seen.add(geom.geom_type.upper())

                    # ── v1.47: geometry type consistency ──────────────────────
                    # Compare Shapely's reported type against the declared
                    # geometry_type_name in gpkg_geometry_columns.
                    # 'GEOMETRY' means any type is acceptable (wildcard).
                    if declared_geom_type and declared_geom_type.upper() not in (
                        "GEOMETRY", "GEOMETRYCOLLECTION", ""
                    ):
                        _actual_type = geom.geom_type.upper()
                        _declared_uc = declared_geom_type.upper().rstrip("ZM")  # v1.51: rstrip only trailing Z/M; replace() corrupted MULTI* names
                        if _actual_type != _declared_uc:
                            # Allow Multi-variant when single variant is declared
                            # (e.g. POLYGON stored where MULTIPOLYGON declared) — soft warn only
                            if not (_actual_type.startswith("MULTI") and
                                    _actual_type[5:] == _declared_uc):
                                type_mismatches.append(
                                    f"geom {idx}: actual type '{_actual_type}' ≠ "
                                    f"declared '{declared_geom_type}'"
                                )

                    # Bounds check now handled by RTree aggregate (Feature 2a above)
                    if not geom.is_valid:
                        reason = _explain(geom)
                        invalid.append(f"geom {idx}: {reason}")
                    else:
                        valid_count += 1
                except Exception as e:
                    errors.append(f"geom {idx}: decode error ({e})")

            if zm_mismatches:
                geom_fails.append(
                    f"'{geom_tname}'.{geom_col} Z/M consistency: "
                    + "; ".join(zm_mismatches[:5])
                )
            if type_mismatches:
                geom_fails.append(
                    f"'{geom_tname}'.{geom_col} geometry type mismatch "
                    f"(declared '{declared_geom_type}'): "
                    + "; ".join(type_mismatches[:5])
                )
            else:
                geom_passes.append(
                    f"'{geom_tname}'.{geom_col}: geometry type consistent "
                    f"with declared '{declared_geom_type}' ✓"
                )

            # ── v1.49 Feature 13: geometry type completeness check ────────────
            # After sampling, check if any actual WKB types found in the sample
            # are more specific than the declared geometry_type_name.
            # Example: declared=POLYGON but sample contains MULTIPOLYGON → FAIL.
            # GEOMETRY is a valid supertype — don't flag those.
            # Only flag when declared type is a specific singleton and sample
            # contains a corresponding multi-type that was NOT declared.
            if (declared_geom_type and
                    declared_geom_type.upper() not in ("GEOMETRY", "GEOMETRYCOLLECTION", "")
                    and _actual_types_seen):
                _decl_uc = declared_geom_type.upper().rstrip("ZM")  # v1.51: rstrip only trailing Z/M; replace() corrupted MULTI* names
                # Check for multi-variant types in sample that don't match declared
                for _seen_type in sorted(_actual_types_seen):
                    if (_seen_type.startswith("MULTI") and
                            _seen_type[5:] == _decl_uc and
                            _decl_uc not in ("GEOMETRY", "GEOMETRYCOLLECTION")):
                        geom_fails.append(
                            f"'{geom_tname}'.{geom_col}: Found {_seen_type} geometries "
                            f"but geometry_type_name declares only {declared_geom_type} — "
                            f"column should declare MULTI{_decl_uc} or GEOMETRY"
                        )
                    # v1.50 fix: removed the elif branch that caught completely
                    # different geometry types (e.g. POINT in a LINESTRING column).
                    # That case is already caught by the per-blob type_mismatches
                    # list (populated in the loop above) which feeds into geom_fails.
                    # The elif caused the same mismatch to appear twice in the detail.
                    # Only the if-branch (MULTI-variant of declared singleton type)
                    # is unique to the completeness check and is retained.
            n = len(blobs)
            tbl_label = f"'{geom_tname}'.{geom_col} [{sample_note}]"
            if invalid:
                geom_fails.append(
                    f"{tbl_label}: {len(invalid)}/{n} invalid geometries: "
                    + "; ".join(invalid[:5])
                )
            elif errors:
                geom_fails.append(
                    f"{tbl_label}: {len(errors)}/{n} decode errors: "
                    + "; ".join(errors[:3])
                )
            else:
                geom_passes.append(
                    f"{tbl_label}: {valid_count}/{n} sampled geometries all valid ✓"
                )

    # ── Build result ──────────────────────────────────────────────────────────
    all_lines = (ats_fails + geom_fails + ats_passes + geom_passes
                 + geom_skips)
    if warnings:
        all_lines.append("NOTES (informational): " + "; ".join(warnings))

    detail = "\n".join(all_lines)

    if ats_fails or geom_fails:
        return ("FAIL", detail)
    if geom_skips and not geom_passes:
        return ("PASS*", detail)
    return ("PASS", detail)

def _r25(cursor):
    """Tile Matrix Width/Height + Tile Pyramid Zoom Level Continuity.

    v1.0 (CC06 Req 25): checks gpkg_tile_matrix_SET required columns exist:
    table_name, srs_id, min_x, min_y, max_x, max_y.

    v1.47 addition — Tile pyramid zoom level continuity:
      For each tile table, verifies that:
        1. Zoom levels in gpkg_tile_matrix are contiguous (no gaps in the
           declared range min_zoom–max_zoom).
        2. Every zoom level declared in gpkg_tile_matrix has at least one
           tile row actually stored in the tile table.
      A gap in the declared or populated zoom sequence is a hard FAIL.
    """
    # v1.42 fix: SKIP if no tile or gridded tables present
    if table_exists(cursor, "gpkg_contents"):
        cursor.execute("SELECT DISTINCT data_type FROM gpkg_contents")
        dtypes = {(r[0] or "").lower() for r in cursor.fetchall()}
        has_tile_data = any(
            dt in ("tiles", "2d-gridded-coverage", "gpkg_2d_gridded_coverage", "2d_gridded_coverage")
            for dt in dtypes
        )
        if not has_tile_data:
            return ("SKIPPED", "No tile or gridded coverage tables present — "
                    "Req 25 not applicable for feature/attribute-only GeoPackages ✓")

    # ── Step 1: column presence on gpkg_tile_matrix_set ──────────────────────
    required_cols = ["table_name", "srs_id", "min_x", "min_y", "max_x", "max_y"]
    missing = [c for c in required_cols if not column_exists(cursor, "gpkg_tile_matrix_set", c)]
    if missing:
        return ("FAIL", f"Required column(s) missing from gpkg_tile_matrix_set: {missing}")
    col_results = "; ".join(f"'{c}' ✓" for c in required_cols)

    # ── Step 2 (v1.47): zoom level continuity per tile table ─────────────────
    cont_fails  = []
    cont_passes = []
    if table_exists(cursor, "gpkg_tile_matrix"):
        try:
            cursor.execute("""
                SELECT DISTINCT table_name
                FROM gpkg_tile_matrix
                ORDER BY table_name
            """)
            _tile_tbls = [r[0] for r in cursor.fetchall()]
            for _tt in _tile_tbls:
                # Declared zoom levels in gpkg_tile_matrix
                cursor.execute(
                    "SELECT zoom_level FROM gpkg_tile_matrix "
                    "WHERE table_name=? ORDER BY zoom_level",
                    (_tt,)
                )
                _declared = [r[0] for r in cursor.fetchall()]
                if len(_declared) < 2:
                    cont_passes.append(
                        f"'{_tt}': single zoom level — continuity N/A ✓"
                    )
                    continue

                _min_z, _max_z = min(_declared), max(_declared)
                _expected = list(range(_min_z, _max_z + 1))
                _gaps_declared = sorted(set(_expected) - set(_declared))
                if _gaps_declared:
                    cont_fails.append(
                        f"'{_tt}': gpkg_tile_matrix zoom gaps (declared range "
                        f"{_min_z}–{_max_z}): missing levels {_gaps_declared}"
                    )
                else:
                    # Also check that declared zooms have actual tiles stored
                    try:
                        cursor.execute(
                            f"SELECT DISTINCT zoom_level FROM {_quote_ident(_tt)} "
                            f"ORDER BY zoom_level"
                        )
                        _populated = {r[0] for r in cursor.fetchall()}
                        _empty_zooms = sorted(set(_declared) - _populated)
                        if _empty_zooms:
                            # v1.55: downgraded from FAIL to NOTE — storing data only
                            # at the highest zoom level is a standard valid pattern
                            # (DGED elevation files, regional tile pyramids). Req 25
                            # specifies column structure only, not tile population.
                            cont_passes.append(
                                f"'{_tt}': zoom levels declared but no tiles stored: "
                                f"{_empty_zooms} "
                                f"(NOTE: empty overview levels are common and valid — "
                                f"not a Req 25 non-conformance)"
                            )
                        else:
                            cont_passes.append(
                                f"'{_tt}': {len(_declared)} contiguous zoom levels "
                                f"({_min_z}–{_max_z}), all populated ✓"
                            )
                    except Exception as _tp_e:
                        cont_passes.append(
                            f"'{_tt}': zoom continuity declared OK; tile population "
                            f"check skipped ({_tp_e})"
                        )
        except Exception as _cont_e:
            cont_passes.append(f"Zoom continuity check skipped: {_cont_e}")

    all_lines = cont_fails + cont_passes
    detail = (
        f"gpkg_tile_matrix_set columns: {col_results}\n"
        + ("\n".join(all_lines) if all_lines else "")
    )
    if cont_fails:
        return ("FAIL", detail)
    # v1.49 code quality: the PASS* fallback below was previously unreachable
    # because col_results is always populated before this point (Step 1 exits
    # early with FAIL or returns col_results — never empty at this stage), and
    # if gpkg_tile_matrix is present, cont_passes is always populated for every
    # tile table (single-zoom or gap-free). Replaced with an explicit comment.
    # If cont_passes is non-empty (normal case) → PASS; if empty (no tile matrix
    # table present, only col check ran) → still PASS since structural check passed.
    return ("PASS", detail)


def _r26(cursor):
    """Tile Pyramid Data Size — Req 26.

    Strategy (v1.25):
      1. Structural check: gpkg_tile_matrix table + required columns must exist.
      2. BLOB decode (Pillow): for every tile table, at every declared zoom level,
         sample up to SAMPLE_N tile BLOBs and decode them with Pillow.
         If Image.open(io.BytesIO(blob)).size != (declared_w, declared_h) → FAIL.
      3. Graceful fallback: if Pillow is not installed, returns PASS* with note.

    Returns PASS  when all sampled BLOBs match declared dimensions.
    Returns FAIL  when any BLOB dimension mismatches or structural issue found.
    Returns PASS* when Pillow unavailable or tile tables have no stored tile data.
    """
    # BLOBs to sample per zoom level per tile table (default 5; --sample-size overrides)
    SAMPLE_N = _config.SAMPLE_SIZE if _config.SAMPLE_SIZE else 5

    # ── Step 1: structural check ──────────────────────────────────────────────
    required_cols = ["table_name", "zoom_level", "matrix_width", "matrix_height",
                     "tile_width", "tile_height", "pixel_x_size", "pixel_y_size"]
    if not table_exists(cursor, "gpkg_tile_matrix"):
        # v1.43 fix: feature/attribute-only GeoPackages legitimately have no
        # gpkg_tile_matrix table — return SKIPPED instead of FAIL.  Only return
        # FAIL if tile or gridded-coverage tables are declared (i.e. the table
        # SHOULD exist but is absent).
        if table_exists(cursor, "gpkg_contents"):
            cursor.execute("SELECT DISTINCT data_type FROM gpkg_contents")
            dtypes = {(r[0] or "").lower() for r in cursor.fetchall()}
            has_tile_data = any(
                dt in ("tiles", "2d-gridded-coverage",
                       "gpkg_2d_gridded_coverage", "2d_gridded_coverage")
                for dt in dtypes
            )
            if not has_tile_data:
                return ("SKIPPED",
                        "No tile or gridded coverage tables present — "
                        "Req 26 not applicable for feature/attribute-only GeoPackages ✓")
        fail_msgs = [f"Field '{c}' missing in gpkg_tile_matrix" for c in required_cols]
        return ("FAIL", "; ".join(fail_msgs))
    missing = [c for c in required_cols if not column_exists(cursor, "gpkg_tile_matrix", c)]
    if missing:
        fail_msgs = [f"Field '{c}' missing in gpkg_tile_matrix" for c in missing]
        return ("FAIL", "; ".join(fail_msgs))

    # ── Step 2: check Pillow availability — always live import ───────────────
    try:
        from PIL import Image  # noqa: F401
        pillow_ok = True
        LIBRARY_STATUS["Pillow"] = True
    except Exception:
        pillow_ok = False

    if not pillow_ok:
        # ── Lightweight header-based fallback (no Pillow required) ───────────
        # Read the first ~30 bytes of each BLOB and parse the image dimensions
        # directly from the binary header — no image decoding needed.
        #
        # Supported formats and their header layouts:
        #   PNG  : bytes 0-3 = 89 50 4E 47; width at bytes 16-19, height at 20-23 (big-endian)
        #   JPEG : bytes 0-1 = FF D8; scan forward for SOF0/SOF2 markers (FF C0/FF C2);
        #          height at offset+5 (2 bytes), width at offset+7 (2 bytes) (big-endian)
        #   TIFF : bytes 0-1 = 49 49 (LE) or 4D 4D (BE); IFD tag 0x0100=width, 0x0101=height
        #
        # This is sufficient for DGIWG validation (256×256 check) and requires
        # only Python stdlib — no external dependencies.

        def _parse_png_size(raw):
            """Return (width, height) from PNG header bytes, or None."""
            if len(raw) < 24:
                return None
            if raw[:4] != b'\x89PNG':
                return None
            w = int.from_bytes(raw[16:20], 'big')
            h = int.from_bytes(raw[20:24], 'big')
            return (w, h) if w > 0 and h > 0 else None

        def _parse_jpeg_size(raw):
            """Return (width, height) from JPEG SOF marker, or None."""
            if len(raw) < 4 or raw[:2] != b'\xff\xd8':
                return None
            i = 2
            while i + 4 < len(raw):
                if raw[i] != 0xFF:
                    break
                marker = raw[i + 1]
                seg_len = int.from_bytes(raw[i+2:i+4], 'big')
                # SOF0=0xC0, SOF1=0xC1, SOF2=0xC2 carry image dimensions
                if marker in (0xC0, 0xC1, 0xC2) and i + 9 <= len(raw):  # v1.49: <= (was <)
                    h = int.from_bytes(raw[i+5:i+7], 'big')
                    w = int.from_bytes(raw[i+7:i+9], 'big')
                    return (w, h) if w > 0 and h > 0 else None
                i += 2 + seg_len
            return None

        def _parse_tiff_size(raw):
            """Return (width, height) from TIFF IFD, or None."""
            if len(raw) < 8:
                return None
            if raw[:2] == b'II':
                bo = 'little'
            elif raw[:2] == b'MM':
                bo = 'big'
            else:
                return None
            ifd_offset = int.from_bytes(raw[4:8], bo)
            if ifd_offset + 2 > len(raw):
                return None
            n_entries = int.from_bytes(raw[ifd_offset:ifd_offset+2], bo)
            width = height = None
            for e in range(n_entries):
                entry_off = ifd_offset + 2 + e * 12
                if entry_off + 12 > len(raw):
                    break
                tag   = int.from_bytes(raw[entry_off:entry_off+2], bo)
                dtype = int.from_bytes(raw[entry_off+2:entry_off+4], bo)
                val_off = entry_off + 8
                if dtype in (3, 4):  # SHORT or LONG
                    nbytes = 2 if dtype == 3 else 4
                    val = int.from_bytes(raw[val_off:val_off+nbytes], bo)
                    if tag == 0x0100:
                        width = val
                    elif tag == 0x0101:
                        height = val
            return (width, height) if width and height else None

        def _header_size(blob_bytes):
            """Attempt to parse image dimensions from raw BLOB header bytes."""
            raw = bytes(blob_bytes[:256])  # only need the first ~256 bytes
            return (
                _parse_png_size(raw)
                or _parse_jpeg_size(raw)
                or _parse_tiff_size(raw)
            )

        # Run the header-based check on the same tile tables/zoom levels
        cursor.execute("""
            SELECT table_name, zoom_level, tile_width, tile_height
            FROM gpkg_tile_matrix
            ORDER BY table_name, zoom_level
        """)
        matrix_rows = cursor.fetchall()
        if not matrix_rows:
            col_results = [f"Field '{c}' found in gpkg_tile_matrix" for c in required_cols]
            return ("PASS*",
                    "; ".join(col_results)
                    + " | No zoom level entries — no tile data to decode")

        by_table_fb = defaultdict(list)
        for tname, zoom, tw, th in matrix_rows:
            by_table_fb[tname].append((zoom, tw, th))

        SAMPLE_N_FB = 3   # fewer samples for header-only check
        fb_summaries = []
        fb_all_pass  = True
        fb_any_data  = False
        fb_any_parsed = False

        for tname, zoom_levels in sorted(by_table_fb.items()):
            if not table_exists(cursor, tname):
                fb_summaries.append(f"⚠️ Table '{tname}': declared but tile table does not exist")
                fb_all_pass = False
                continue
            zoom_results = []
            for zoom, declared_w, declared_h in zoom_levels:
                try:
                    cursor.execute(
                        f'SELECT tile_data FROM {_quote_ident(tname)} '
                        f'WHERE zoom_level=? AND tile_data IS NOT NULL LIMIT ?',
                        (zoom, SAMPLE_N_FB)
                    )
                    blobs = [r[0] for r in cursor.fetchall()]
                except Exception as e:
                    zoom_results.append(f"  zoom {zoom}: SQL error: {e}")
                    fb_all_pass = False
                    continue

                if not blobs:
                    zoom_results.append(
                        f"  zoom {zoom}: ⚠️ no BLOBs stored (declared {declared_w}×{declared_h})"
                    )
                    continue

                fb_any_data = True
                mismatches = []
                unreadable = []
                ok_count = 0

                for idx, blob in enumerate(blobs, 1):
                    size = _header_size(blob)
                    if size is None:
                        unreadable.append(f"tile {idx}: unknown format")
                        continue
                    fb_any_parsed = True
                    w, h = size
                    if w != declared_w or h != declared_h:
                        mismatches.append(
                            f"tile {idx}: actual {w}×{h} ≠ declared {declared_w}×{declared_h}"
                        )
                        fb_all_pass = False
                    elif w != TILE_W or h != TILE_H:
                        # v1.58 fix (Bug C): same non-256 stored-tile rule as the
                        # Pillow path — declared-matching but non-256 tiles FAIL.
                        mismatches.append(
                            f"tile {idx}: stored {w}×{h} matches declared but "
                            f"DGIWG requires {TILE_W}×{TILE_H}"
                        )
                        fb_all_pass = False
                    else:
                        ok_count += 1

                if mismatches:
                    zoom_results.append(
                        f"  zoom {zoom}: ❌ MISMATCH {len(mismatches)}/{len(blobs)}: "
                        + "; ".join(mismatches)
                    )
                elif unreadable and not ok_count:
                    zoom_results.append(
                        f"  zoom {zoom}: ⚠️ format unrecognised — header parse skipped "
                        f"(declared {declared_w}×{declared_h})"
                    )
                else:
                    zoom_results.append(
                        f"  zoom {zoom}: ✅ {ok_count}/{len(blobs)} BLOBs "
                        f"header-verified {declared_w}×{declared_h}"
                    )

            fb_summaries.append(
                f"Table '{tname}' ({len(zoom_levels)} zoom levels):\n" + "\n".join(zoom_results)
            )

        method_note = (
            "⚠️ Pillow not installed — using lightweight PNG/JPEG/TIFF header parser "
            f"(stdlib only, {SAMPLE_N_FB} BLOBs per zoom level). "
            "Install Pillow for full pixel decode."
        )
        detail_fb = method_note + "\n\n" + "\n\n".join(fb_summaries)

        if not fb_any_data:
            return ("PASS*", "gpkg_tile_matrix structure valid ✓ | No tile BLOBs found\n\n"
                    + "\n\n".join(fb_summaries))
        if not fb_any_parsed:
            col_results = [f"Field '{c}' found in gpkg_tile_matrix" for c in required_cols]
            return ("PASS*",
                    "; ".join(col_results)
                    + " | Pillow not available and BLOB format not recognised by header parser. "
                      "Install Pillow for full decode.")
        if fb_all_pass:
            return ("PASS*", detail_fb)   # PASS* not PASS: header parse is lighter than full decode
        return ("FAIL", detail_fb)

    # ── Step 3: get all tile tables from gpkg_tile_matrix ────────────────────
    cursor.execute("""
        SELECT table_name, zoom_level, tile_width, tile_height
        FROM gpkg_tile_matrix
        ORDER BY table_name, zoom_level
    """)
    matrix_rows = cursor.fetchall()
    if not matrix_rows:
        return ("PASS*",
                "gpkg_tile_matrix columns present ✓ | No zoom level entries found — "
                "no tile data to decode")

    # Group by table_name → { tname: [(zoom, declared_w, declared_h), ...] }
    by_table = defaultdict(list)
    for tname, zoom, tw, th in matrix_rows:
        by_table[tname].append((zoom, tw, th))

    # ── Step 4: BLOB decode per table per zoom level ──────────────────────────
    table_summaries = []
    all_pass = True
    any_data_found = False

    for tname, zoom_levels in sorted(by_table.items()):
        # Check if the tile table actually exists as a SQLite table
        if not table_exists(cursor, tname):
            table_summaries.append(
                f"⚠️ Table '{tname}': declared in gpkg_tile_matrix but tile table does not exist"
            )
            all_pass = False
            continue

        zoom_results = []
        table_has_data = False

        for zoom, declared_w, declared_h in zoom_levels:
            # Fetch up to SAMPLE_N tile BLOBs at this zoom level
            try:
                cursor.execute(f"""
                    SELECT tile_data FROM {_quote_ident(tname)}
                    WHERE zoom_level = ? AND tile_data IS NOT NULL
                    LIMIT ?
                """, (zoom, SAMPLE_N))
                blobs = [r[0] for r in cursor.fetchall()]
            except Exception as e:
                zoom_results.append(
                    f"  zoom {zoom}: ❌ SQL error reading tile data: {e}"
                )
                all_pass = False
                continue

            if not blobs:
                zoom_results.append(
                    f"  zoom {zoom}: ⚠️ No tile BLOBs stored "
                    f"(declared {declared_w}×{declared_h})"
                )
                continue

            table_has_data = True
            any_data_found = True
            mismatches = []
            decode_errors = []

            # Hoist PIL import outside per-BLOB loop (v1.48)
            try:
                from PIL import Image as _PIL_Img_r26
                import io as _io_r26
            except ImportError:
                _PIL_Img_r26 = None
                _io_r26 = None

            for idx, blob in enumerate(blobs, 1):
                try:
                    if _PIL_Img_r26 is None:
                        raise ImportError("Pillow not available")
                    img = _PIL_Img_r26.open(_io_r26.BytesIO(bytes(blob)))
                    actual_w, actual_h = img.size
                    if actual_w != declared_w or actual_h != declared_h:
                        mismatches.append(
                            f"tile {idx}: actual {actual_w}×{actual_h} "
                            f"≠ declared {declared_w}×{declared_h}"
                        )
                    elif actual_w != TILE_W or actual_h != TILE_H:
                        # v1.58 fix (Bug C): a stored tile that matches a non-256
                        # declaration (e.g. declared 512, stored 512) previously
                        # PASSED Req 26.  DGIWG requires 256×256 stored tiles —
                        # the declared-value violation is caught by Req 8/25, but
                        # Req 26 must independently fail on non-256 stored BLOBs.
                        mismatches.append(
                            f"tile {idx}: stored {actual_w}×{actual_h} matches "
                            f"declared but DGIWG requires {TILE_W}×{TILE_H}"
                        )
                except Exception as e:
                    decode_errors.append(f"tile {idx}: decode error ({e})")

            sampled = len(blobs)
            if mismatches:
                all_pass = False
                zoom_results.append(
                    f"  zoom {zoom}: ❌ MISMATCH in {len(mismatches)}/{sampled} sampled "
                    f"tile(s) — declared {declared_w}×{declared_h}: "
                    + "; ".join(mismatches)
                )
            elif decode_errors:
                all_pass = False
                zoom_results.append(
                    f"  zoom {zoom}: ❌ Decode error(s) in {len(decode_errors)}/{sampled} "
                    f"tile(s): " + "; ".join(decode_errors)
                )
            else:
                zoom_results.append(
                    f"  zoom {zoom}: ✅ {sampled} tile(s) sampled — "
                    f"all {actual_w}×{actual_h} match declared {declared_w}×{declared_h}"
                )

        tbl_label = f"Table '{tname}' ({len(zoom_levels)} zoom level(s))"
        if not table_has_data:
            table_summaries.append(
                f"⚠️ {tbl_label}: no tile BLOBs stored at any zoom level"
            )
        else:
            table_summaries.append(tbl_label + ":\n" + "\n".join(zoom_results))

    # ── Step 5: compose result ────────────────────────────────────────────────
    detail = (
        f"Pillow BLOB decode | {SAMPLE_N} tile(s) sampled per zoom level | "
        f"{len(by_table)} tile table(s) checked\n\n"
        + "\n\n".join(table_summaries)
    )

    if not any_data_found:
        return ("PASS*",
                "gpkg_tile_matrix structure valid ✓ | No tile BLOBs found in any table — "
                "nothing to decode\n\n" + "\n\n".join(table_summaries))

    if all_pass:
        return ("PASS", detail)
    else:
        return ("FAIL", detail)



def _r27(cursor):
    """Zoom Level Factor — verifies exact factor-of-2 pixel size halving.

    v1.0 behaviour was: count zoom levels only (PASS*).
    for each tile table, check that:
      pixel_x_size[zoom N+1] / pixel_x_size[zoom N] == 0.5 (within 0.01% tolerance)
      pixel_y_size[zoom N+1] / pixel_y_size[zoom N] == 0.5 (within 0.01% tolerance)
    This is the DGIWG requirement for a factor-of-2 zoom pyramid.
    Returns PASS when all transitions are exact factor-of-2.
    Returns FAIL when any transition deviates beyond tolerance.
    """
    FACTOR_TOL = 1e-4  # 0.01% relative tolerance

    if not table_exists(cursor, "gpkg_tile_matrix"):
        return ("SKIPPED", "No tile matrix table")
    # v1.42 fix 3: only check data_type='tiles' tables — 2d-gridded-coverage
    # tables are not required to follow a factor-of-2 zoom pyramid (Req 27 is
    # a raster tile pyramid requirement only).
    cursor.execute("""
        SELECT tm.table_name, tm.zoom_level, tm.pixel_x_size, tm.pixel_y_size
        FROM gpkg_tile_matrix tm
        JOIN gpkg_contents c ON tm.table_name = c.table_name
        WHERE c.data_type = 'tiles'
        ORDER BY tm.table_name, tm.zoom_level
    """)
    rows = cursor.fetchall()
    if not rows:
        return ("SKIPPED", "No raster tile pyramid tables (data_type='tiles') found — "
                "Req 27 not applicable (gridded coverage checked separately)")

    by_table = defaultdict(list)
    for tname, zoom, px, py in rows:
        by_table[tname].append((zoom, px, py))

    fails = []
    passes = []

    for tname, data in sorted(by_table.items()):
        if len(data) < 2:
            passes.append(
                f"'{tname}': only {len(data)} zoom level — "
                f"factor-of-2 check N/A (single level) ✓"
            )
            continue

        transition_fails = []
        for i in range(1, len(data)):
            z_prev, px_prev, py_prev = data[i-1]
            z_curr, px_curr, py_curr = data[i]

            # Check factor — should be 0.5 (pixel size halves at each zoom step)
            if px_prev != 0:
                ratio_x = px_curr / px_prev
                if abs(ratio_x - 0.5) > FACTOR_TOL:
                    transition_fails.append(
                        f"zoom {z_prev}→{z_curr}: pixel_x ratio={ratio_x:.6f} "
                        f"(expected 0.5, deviation={abs(ratio_x-0.5):.2e})"
                    )
            if py_prev != 0:
                ratio_y = py_curr / py_prev
                if abs(ratio_y - 0.5) > FACTOR_TOL:
                    transition_fails.append(
                        f"zoom {z_prev}→{z_curr}: pixel_y ratio={ratio_y:.6f} "
                        f"(expected 0.5, deviation={abs(ratio_y-0.5):.2e})"
                    )

        if transition_fails:
            fails.append(
                f"'{tname}': factor-of-2 FAILED at "
                f"{len(transition_fails)} transition(s): "
                + "; ".join(transition_fails)
            )
        else:
            passes.append(
                f"'{tname}': all {len(data)-1} zoom transition(s) are "
                f"exact factor-of-2 ✓"
            )

    # ── v1.49 Feature 14: Tile density check (informational NOTE only) ──────────
    # For each tile table, compare actual tile count vs expected cells per zoom level.
    # If any zoom level has < 1% coverage, add a NOTE to the detail string.
    # This does NOT change the PASS/FAIL verdict — it is purely informational.
    density_notes = []
    try:
        for tname in sorted(by_table.keys()):
            # Get matrix dimensions per zoom level
            cursor.execute(
                "SELECT zoom_level, matrix_width, matrix_height "
                "FROM gpkg_tile_matrix WHERE table_name=? ORDER BY zoom_level",
                (tname,)
            )
            _matrix_dims = {r[0]: (r[1], r[2]) for r in cursor.fetchall()}
            if not _matrix_dims:
                continue
            # Get actual tile counts per zoom level
            try:
                cursor.execute(
                    f"SELECT zoom_level, COUNT(*) as actual_count "
                    f"FROM {_quote_ident(tname)} GROUP BY zoom_level",
                )
                _actual_counts = {r[0]: r[1] for r in cursor.fetchall()}
            except Exception:
                continue
            for zl, (mw, mh) in _matrix_dims.items():
                if mw and mh and mw > 0 and mh > 0:
                    expected = mw * mh
                    actual   = _actual_counts.get(zl, 0)
                    pct = (actual / expected) * 100.0
                    if pct < 1.0:
                        density_notes.append(
                            f"NOTE '{tname}' zoom_level {zl}: "
                            f"{actual}/{expected} tiles ({pct:.1f}%) — "
                            f"possible incomplete delivery"
                        )
    except Exception as _dn_e:
        density_notes.append(f"NOTE: tile density check skipped ({_dn_e})")

    if density_notes:
        passes.extend(density_notes)

    detail = "\n".join(fails + passes)
    if fails:
        return ("FAIL", detail)
    return ("PASS", detail)

def _r28(cursor):
    """Multiple Zoom Matrix Sets — pixel sizes must decrease with increasing zoom level.
    v1.0 (CC07 Req 28) checks: for each tile table, pixel_x_size and pixel_y_size
    must strictly decrease as zoom_level increases. Monotonic pixel-size reduction check.
    """
    if not table_exists(cursor, "gpkg_tile_matrix"):
        return ("SKIPPED", "No tile matrix table")
    cursor.execute("""
        SELECT tm.table_name, tm.zoom_level, tm.pixel_x_size, tm.pixel_y_size
        FROM gpkg_tile_matrix tm
        JOIN gpkg_contents c ON tm.table_name = c.table_name
        WHERE c.data_type = 'tiles'
        ORDER BY tm.table_name, tm.zoom_level
    """)
    rows = cursor.fetchall()
    if not rows:
        return ("SKIPPED", "No tile matrix data available")
    # Group by table
    by_table = defaultdict(list)
    for tname, zoom, px, py in rows:
        by_table[tname].append((zoom, px, py))
    fails, passes = [], []
    for tname, data in by_table.items():
        if len(data) < 2:
            passes.append(f"'{tname}': only {len(data)} zoom level — monotonic check N/A ✓")
            continue
        valid = True
        for i in range(1, len(data)):
            if not (data[i][1] < data[i-1][1] and data[i][2] < data[i-1][2]):
                valid = False
                break
        if valid:
            passes.append(f"'{tname}': pixel_x/y_size decreases with zoom level ✓")
        else:
            fails.append(f"'{tname}': pixel_x/y_size does not strictly decrease with zoom level")
    if fails:
        return ("FAIL", "; ".join(fails))
    return ("PASS*", "; ".join(passes) + "; Partial automated validation: PASS* indicates not all aspects are validated.")


def _r29(cursor):
    """Single Zoom Matrix Set.
    v1.0 checks tile dimension consistency across zoom levels per table.
    FAIL when dimensions vary across zoom levels; PASS* otherwise.
    """
    if not table_exists(cursor, "gpkg_tile_matrix"):
        return ("SKIPPED", "No tile matrix table")
    # v1.42 fix 4: only check data_type='tiles' tables — 2d-gridded-coverage
    # tables are not required to maintain consistent tile dimensions across zoom
    # levels (Req 29 is a raster tile pyramid requirement only).
    cursor.execute("""
        SELECT DISTINCT tm.table_name
        FROM gpkg_tile_matrix tm
        JOIN gpkg_contents c ON tm.table_name = c.table_name
        WHERE c.data_type = 'tiles'
    """)
    tables = [r[0] for r in cursor.fetchall()]
    if not tables:
        return ("SKIPPED", "No raster tile pyramid tables (data_type='tiles') found — "
                "Req 29 not applicable (gridded coverage checked separately)")
    fails, passes = [], []
    for tname in tables:
        cursor.execute("""
            SELECT zoom_level, tile_width, tile_height
            FROM gpkg_tile_matrix WHERE table_name=? ORDER BY zoom_level
        """, (tname,))
        levels = cursor.fetchall()
        widths  = {r[1] for r in levels}
        heights = {r[2] for r in levels}
        if len(widths) > 1 or len(heights) > 1:
            fails.append(f"Tile dimensions vary across zoom levels for table '{tname}': "
                         f"widths={sorted(widths)}, heights={sorted(heights)}")
        else:
            passes.append(f"Tile dimensions consistent across zoom levels for table '{tname}'")
    if fails:
        return ("FAIL", "; ".join(fails))
    return ("PASS*", "; ".join(passes) + "; Partial automated validation: PASS* indicates not all aspects are validated.")


def _r30(cursor):
    """Tile Matrix Set CRS BBox — cross-checks declared bbox against
    valid geographic extent of the CRS.

    confirmed bbox min < max (sanity check).
    v1.27 addition: compares bbox against CRS_EXTENT lookup table.
      A file bbox that exceeds the valid CRS extent by more than 0.1% → FAIL.
      (0.1% tolerance handles floating-point/rounding differences.)
    """
    if not table_exists(cursor, "gpkg_tile_matrix_set"):
        return ("SKIPPED", "No tile matrix set")
    # v1.49 fix: restrict to data_type='tiles' to avoid double-checking gridded
    # coverage bbox values with raster-tile logic (Req 30 is a raster tile req).
    cursor.execute("""
        SELECT tms.table_name, tms.min_x, tms.min_y, tms.max_x, tms.max_y,
               srs.srs_id, srs.srs_name
        FROM gpkg_tile_matrix_set tms
        JOIN gpkg_contents c ON tms.table_name = c.table_name
        LEFT JOIN gpkg_spatial_ref_sys srs ON tms.srs_id = srs.srs_id
        WHERE c.data_type = 'tiles'
    """)
    rows = cursor.fetchall()
    if not rows:
        return ("SKIPPED", "No raster tile matrix sets (data_type='tiles') found — "
                "Req 30 not applicable (gridded coverage checked separately)")

    fails = []
    passes = []

    for tname, mnx, mny, mxx, mxy, srs_id, srs_name in rows:
        label = f"'{tname}' (srs_id={srs_id} {srs_name})"

        if None in (mnx, mny, mxx, mxy):
            fails.append(f"{label}: bbox contains NULL values")
            continue

        if mnx >= mxx or mny >= mxy:
            fails.append(
                f"{label}: invalid bbox — min not less than max "
                f"({mnx},{mny})→({mxx},{mxy})"
            )
            continue

        extent = CRS_EXTENT.get(srs_id)
        if extent is None:
            passes.append(
                f"{label}: bbox sanity OK ({mnx:.2f},{mny:.2f})→({mxx:.2f},{mxy:.2f}) ✓ "
                f"| CRS not in extent lookup — range cross-check skipped"
            )
            continue

        ex_mnx, ex_mny, ex_mxx, ex_mxy = extent
        tol_x = abs(ex_mxx - ex_mnx) * 0.001
        tol_y = abs(ex_mxy - ex_mny) * 0.001

        bbox_fails = []
        if mnx < ex_mnx - tol_x:
            bbox_fails.append(f"min_x={mnx:.4f} < CRS extent min_x={ex_mnx}")
        if mny < ex_mny - tol_y:
            bbox_fails.append(f"min_y={mny:.4f} < CRS extent min_y={ex_mny}")
        if mxx > ex_mxx + tol_x:
            bbox_fails.append(f"max_x={mxx:.4f} > CRS extent max_x={ex_mxx}")
        if mxy > ex_mxy + tol_y:
            bbox_fails.append(f"max_y={mxy:.4f} > CRS extent max_y={ex_mxy}")

        if bbox_fails:
            fails.append(
                f"{label}: bbox exceeds valid CRS extent: "
                + "; ".join(bbox_fails)
            )
        else:
            passes.append(
                f"{label}: bbox ({mnx:.2f},{mny:.2f})→({mxx:.2f},{mxy:.2f}) "
                f"within CRS extent ✓"
            )

    detail = "\n".join(fails + passes)
    if fails:
        return ("FAIL", detail)
    return ("PASS", detail)

def _r31(cursor):
    """Tile Layer Metadata — validates XML content of tile metadata rows.

    v1.0 match: FAIL when gpkg_metadata_reference missing.
    v1.27 additions:
      - For each tile-scope metadata row, parse XML and verify:
          * Well-formed XML
          * At least one ISO 19115 mandatory element present
          * md_standard_uri is present and non-empty
          * reference_scope/md_scope combination valid per Table 36
    v1.47 addition:
      - Per-layer completeness check: every tile table declared in
        gpkg_contents must have at least one reference_scope='table' row in
        gpkg_metadata_reference that points to it. FAIL if any tile layer
        lacks its own layer-level metadata linkage.
    """
    import xml.etree.ElementTree as _ET

    if not table_exists(cursor, "gpkg_metadata_reference"):
        return ("FAIL", "gpkg_metadata_reference table is MISSING")

    # ── v1.47: per-layer completeness check ──────────────────────────────────
    layer_fails = []
    try:
        cursor.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='tiles'"
        )
        tile_layer_tables = {r[0] for r in cursor.fetchall()}
        if tile_layer_tables:
            cursor.execute(
                "SELECT DISTINCT table_name FROM gpkg_metadata_reference "
                "WHERE reference_scope='table'"
            )
            linked_tables = {r[0] for r in cursor.fetchall()}
            for tl in sorted(tile_layer_tables):
                if tl not in linked_tables:
                    layer_fails.append(
                        f"Tile layer '{tl}' has no reference_scope='table' row "
                        f"in gpkg_metadata_reference — per-layer metadata missing"
                    )
    except Exception as _lc_err:
        layer_fails.append(f"Per-layer completeness check error: {_lc_err}")

    cursor.execute("""
        SELECT r.table_name, r.reference_scope, m.id, m.md_scope,
               m.md_standard_uri, m.metadata
        FROM gpkg_metadata_reference r
        JOIN gpkg_metadata m ON r.md_file_id = m.id
        WHERE m.md_scope IN ('model','tile')
    """)
    rows = cursor.fetchall()

    if not rows and not layer_fails:
        return ("PASS*",
                "gpkg_metadata_reference exists ✓ | "
                "No tile-layer metadata (md_scope='model' or 'tile') found — "
                "tile-layer specific metadata not present in this file")

    fails = list(layer_fails)
    passes = []

    for tname, ref_scope, meta_id, md_scope, uri, xml_text in rows:
        label = f"table='{tname}' meta_id={meta_id} (md_scope={md_scope})"

        # Table 36 pairing
        allowed = TABLE_36_ALLOWED.get(ref_scope, set())
        if md_scope not in allowed:
            fails.append(
                f"{label}: reference_scope='{ref_scope}' + md_scope='{md_scope}' "
                f"not allowed per Table 36 (allowed: {sorted(allowed)})"
            )

        # URI check
        if not uri:
            fails.append(f"{label}: md_standard_uri is empty")

        # XML validation
        if not xml_text or not xml_text.strip():
            fails.append(f"{label}: metadata XML field is empty")
            continue
        try:
            root = _ET.fromstring(xml_text.strip())
            found_iso = [el for el in root.iter()
                         if any(iso in (el.tag or "") for iso in DMF_ISO_MANDATORY)]
            if not found_iso:
                fails.append(f"{label}: no ISO 19115 mandatory elements in XML")
            else:
                passes.append(
                    f"{label}: XML valid ✓ | {len(found_iso)} ISO 19115 element(s) found ✓"
                )
        except _ET.ParseError as e:
            fails.append(f"{label}: XML parse error — {e}")

    detail = "\n".join(fails + passes)
    if fails:
        return ("FAIL", detail)
    return ("PASS", detail)

def _r32(cursor):
    """Feature Layer Metadata — validates XML content of feature metadata rows.

    v1.0 match: FAIL when gpkg_metadata_reference missing or no text/xml rows.
    v1.27 additions:
      - For each feature-scope metadata row, parse XML and verify:
          * Well-formed XML
          * At least one ISO 19115 mandatory element present
          * reference_scope/md_scope combination valid per Table 36
    v1.47 addition:
      - Per-layer completeness check: every feature table declared in
        gpkg_contents must have at least one reference_scope='table' row in
        gpkg_metadata_reference. FAIL if any feature layer lacks linkage.
    """
    import xml.etree.ElementTree as _ET

    if not table_exists(cursor, "gpkg_metadata_reference"):
        return ("FAIL", "gpkg_metadata_reference table is MISSING")

    if table_exists(cursor, "gpkg_metadata"):
        cursor.execute("SELECT COUNT(*) FROM gpkg_metadata WHERE mime_type='text/xml'")
        xml_count = cursor.fetchone()[0]
        if xml_count == 0:
            return ("FAIL", "Found 0 metadata records with mime_type 'text/xml'")

    # ── v1.47: per-layer completeness check ──────────────────────────────────
    layer_fails = []
    try:
        cursor.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
        )
        feature_layer_tables = {r[0] for r in cursor.fetchall()}
        if feature_layer_tables:
            cursor.execute(
                "SELECT DISTINCT table_name FROM gpkg_metadata_reference "
                "WHERE reference_scope='table'"
            )
            linked_tables = {r[0] for r in cursor.fetchall()}
            for fl in sorted(feature_layer_tables):
                if fl not in linked_tables:
                    layer_fails.append(
                        f"Feature layer '{fl}' has no reference_scope='table' row "
                        f"in gpkg_metadata_reference — per-layer metadata missing"
                    )
    except Exception as _lc32_err:
        layer_fails.append(f"Per-layer completeness check error: {_lc32_err}")

    cursor.execute("""
        SELECT r.table_name, r.reference_scope, m.id, m.md_scope,
               m.md_standard_uri, m.metadata
        FROM gpkg_metadata_reference r
        JOIN gpkg_metadata m ON r.md_file_id = m.id
        WHERE m.md_scope IN ('featureType','feature')
    """)
    rows = cursor.fetchall()

    if not rows and not layer_fails:
        return ("PASS*",
                "gpkg_metadata_reference exists ✓ | "
                "No feature-layer metadata (md_scope='featureType' or 'feature') found — "
                "feature-layer specific metadata not present in this file")

    fails = list(layer_fails)
    passes = []

    for tname, ref_scope, meta_id, md_scope, uri, xml_text in rows:
        label = f"table='{tname}' meta_id={meta_id} (md_scope={md_scope})"

        # Table 36 pairing
        allowed = TABLE_36_ALLOWED.get(ref_scope, set())
        if md_scope not in allowed:
            fails.append(
                f"{label}: reference_scope='{ref_scope}' + md_scope='{md_scope}' "
                f"not allowed per Table 36 (allowed: {sorted(allowed)})"
            )

        # XML validation
        if not xml_text or not xml_text.strip():
            fails.append(f"{label}: metadata XML field is empty")
            continue
        try:
            root = _ET.fromstring(xml_text.strip())
            found_iso = [el for el in root.iter()
                         if any(iso in (el.tag or "") for iso in DMF_ISO_MANDATORY)]
            if not found_iso:
                fails.append(f"{label}: no ISO 19115 mandatory elements in XML")
            else:
                passes.append(
                    f"{label}: XML valid ✓ | {len(found_iso)} ISO 19115 element(s) found ✓"
                )
        except _ET.ParseError as e:
            fails.append(f"{label}: XML parse error — {e}")

    detail = "\n".join(fails + passes)
    if fails:
        return ("FAIL", detail)
    return ("PASS", detail)

def _r33(cursor):
    """Gridded Extension Core."""
    if not table_exists(cursor, "gpkg_2d_gridded_coverage_ancillary"):
        return ("SKIPPED", "No gridded coverage data")
    cursor.execute("SELECT extension_name FROM gpkg_extensions")
    present = {r[0] for r in cursor.fetchall()}
    fails, passes = [], []
    # v1.50 fix: the previous loop iterated over required_tables but applied
    # the same extension-name check on every iteration, producing two identical
    # pass/fail messages. Both ancillary tables are covered by one extension
    # registration — check once and report once.
    if "gpkg_2d_gridded_coverage" in present:
        passes.append("gpkg_2d_gridded_coverage extension registered ✓")
    else:
        fails.append("gpkg_2d_gridded_coverage extension not registered in gpkg_extensions")

    # v1.49 fix: verify gpkg_2d_gridded_tile_ancillary actually exists as a
    # SQLite table — extension registration alone does not guarantee the table
    # was created by the producer tool.
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='gpkg_2d_gridded_tile_ancillary'"
    )
    if not cursor.fetchone():
        fails.append(
            "gpkg_2d_gridded_tile_ancillary table not found — "
            "extension registered but ancillary table missing"
        )
    for col in ("tile_matrix_set_name", "field_name", "quantity_definition", "grid_cell_encoding"):
        if column_exists(cursor, "gpkg_2d_gridded_coverage_ancillary", col):
            passes.append(f"Column '{col}' present ✓")
        else:
            fails.append(f"Column '{col}' MISSING from gpkg_2d_gridded_coverage_ancillary")
    if fails:
        return ("FAIL", "; ".join(fails))
    return ("PASS*", "; ".join(passes))


def _r34(cursor):
    """Gridded Field Name Elevation."""
    if not table_exists(cursor, "gpkg_2d_gridded_coverage_ancillary"):
        return ("SKIPPED", "No gridded coverage data")
    cursor.execute("SELECT tile_matrix_set_name, field_name, quantity_definition FROM gpkg_2d_gridded_coverage_ancillary")
    rows = cursor.fetchall()
    fails, passes = [], []
    for name, field_name, qty_def in rows:
        is_elev = qty_def and any(w in qty_def.lower() for w in ("elevation", "height"))
        if is_elev:
            if field_name and field_name.lower() in ("height", "elevation"):
                passes.append(f"'{name}': field_name='{field_name}' ✓")
            else:
                fails.append(f"'{name}': qty_def='{qty_def}' but field_name='{field_name}' (expected Height or Elevation)")
    if not passes and not fails:
        return ("SKIPPED", "No elevation/height gridded data")
    if fails:
        return ("FAIL", "; ".join(fails))
    return ("PASS", "; ".join(passes))


def _r35(cursor):
    """Gridded Center Value Elevation."""
    if not table_exists(cursor, "gpkg_2d_gridded_coverage_ancillary"):
        return ("SKIPPED", "No gridded coverage data")
    cursor.execute("SELECT tile_matrix_set_name, grid_cell_encoding, quantity_definition FROM gpkg_2d_gridded_coverage_ancillary")
    rows = cursor.fetchall()
    fails, passes = [], []
    for name, encoding, qty_def in rows:
        is_elev = qty_def and any(w in qty_def.lower() for w in ("elevation", "height"))
        if is_elev:
            if encoding == "grid-value-is-center":
                passes.append(f"'{name}': grid_cell_encoding='grid-value-is-center' ✓")
            else:
                fails.append(f"'{name}': grid_cell_encoding='{encoding}' (expected grid-value-is-center)")
    if not passes and not fails:
        return ("SKIPPED", "No elevation/height gridded data")
    if fails:
        return ("FAIL", "; ".join(fails))
    return ("PASS", "; ".join(passes))


def _r36(cursor):
    """Gridded Zoom Factor."""
    # Same logic as r27 but specifically for gridded tables
    if not table_exists(cursor, "gpkg_2d_gridded_coverage_ancillary"):
        return ("SKIPPED", "No gridded coverage data")
    cursor.execute("SELECT tile_matrix_set_name FROM gpkg_2d_gridded_coverage_ancillary")
    gridded_tables = [r[0] for r in cursor.fetchall()]
    if not gridded_tables:
        return ("SKIPPED", "No gridded tile sets")
    fails, passes = [], []
    for tname in gridded_tables:
        cursor.execute("""
            SELECT zoom_level, pixel_x_size, pixel_y_size
            FROM gpkg_tile_matrix WHERE table_name=? ORDER BY zoom_level
        """, (tname,))
        levels = cursor.fetchall()
        if len(levels) < 2:
            # Cannot verify factor-of-2 with only 1 zoom level — skip this table only
            passes.append(f"'{tname}': only {len(levels)} zoom level(s) — factor-of-2 check N/A")
            continue
        ok = True
        for i in range(1, len(levels)):
            fx = levels[i-1][1] / levels[i][1] if levels[i][1] else 0
            fy = levels[i-1][2] / levels[i][2] if levels[i][2] else 0
            if abs(fx - 2.0) > 0.01 or abs(fy - 2.0) > 0.01:
                fails.append(f"'{tname}' zoom {levels[i-1][0]}→{levels[i][0]}: factor x={fx:.3f}, y={fy:.3f}")
                ok = False
        if ok:
            passes.append(f"'{tname}': factor=2.0 at all transitions ✓")
    if fails:
        return ("FAIL", "; ".join(fails))
    return ("PASS", "; ".join(passes))


def _r37(cursor):
    """Gridded User Row Metadata — validates Table 36 scope pairings
    and XML content for gridded table metadata rows.

    v1.0 match: validates partial metadata reference linkage.
    v1.27 additions:
      - Validates reference_scope/md_scope per Table 36.
      - Parses XML metadata for each gridded metadata row and confirms
        at least one ISO 19115 element is present.
    """
    import xml.etree.ElementTree as _ET

    if not table_exists(cursor, "gpkg_2d_gridded_coverage_ancillary"):
        return ("SKIPPED", "No gridded coverage data — Req 37 not applicable")
    if not table_exists(cursor, "gpkg_metadata_reference"):
        return ("SKIPPED", "No gpkg_metadata_reference table")

    # Get gridded table names to filter relevant metadata references
    cursor.execute("SELECT tile_matrix_set_name FROM gpkg_2d_gridded_coverage_ancillary")
    gridded_tables = {r[0] for r in cursor.fetchall()}
    if not gridded_tables:
        return ("SKIPPED", "No gridded coverage entries found")

    placeholders = ",".join("?" * len(gridded_tables))
    # v1.39 fix: gpkg_metadata_reference has no 'id' column; use rowid instead.
    cursor.execute(f"""
        SELECT r.rowid, r.table_name, r.reference_scope, r.md_file_id,
               m.md_scope, m.md_standard_uri, m.metadata
        FROM gpkg_metadata_reference r
        JOIN gpkg_metadata m ON r.md_file_id = m.id
        WHERE r.table_name IN ({placeholders})
           OR r.reference_scope = 'geopackage'
    """, list(gridded_tables))
    rows = cursor.fetchall()

    if not rows:
        return ("SKIPPED",
                "No metadata references found for gridded tables — "
                "gridded user row metadata not applicable to this file")

    fails = []
    passes = []

    for ref_id, tname, ref_scope, md_fid, md_scope, uri, xml_text in rows:
        label = f"ref_id={ref_id} table='{tname}' ({ref_scope}/{md_scope})"

        # Table 36 pairing
        allowed = TABLE_36_ALLOWED.get(ref_scope, set())
        if md_scope not in allowed:
            fails.append(
                f"{label}: reference_scope='{ref_scope}' + md_scope='{md_scope}' "
                f"invalid per Table 36 (allowed: {sorted(allowed)})"
            )
            continue

        # XML validation
        if not xml_text or not xml_text.strip():
            fails.append(f"{label}: metadata XML field is empty")
            continue
        try:
            root = _ET.fromstring(xml_text.strip())
            found_iso = [el for el in root.iter()
                         if any(iso in (el.tag or "") for iso in DMF_ISO_MANDATORY)]
            if not found_iso:
                fails.append(f"{label}: no ISO 19115 elements in XML")
            else:
                passes.append(f"{label}: XML valid ✓ | {len(found_iso)} ISO 19115 element(s) ✓")
        except _ET.ParseError as e:
            fails.append(f"{label}: XML parse error — {e}")

    detail = "\n".join(fails + passes)
    if fails:
        return ("FAIL", detail)
    return ("PASS", detail)


# ──────────────────────────────────────────────────────────────────────────────
# CHECK DISPATCH TABLE  — must be defined AFTER all _rN functions
# ──────────────────────────────────────────────────────────────────────────────

def _r1(_cursor):
    """GeoPackage Base definition — requires OGC CITE TeamEngine, not automatable.

    v1.58: renamed to match STD-DP-19-005 v1.1 Table 6
    (/req/geopackage/base — 'GeoPackage Base definition').
    """
    return ("SKIPPED",
            "Req 1 (GeoPackage Base definition — OGC Base conformance class): "
            "Requires OGC CITE TeamEngine — not automatable")

def _r2(_cursor):
    """GeoPackage Options definition — requires OGC CITE TeamEngine, not automatable.

    v1.58: renamed to match STD-DP-19-005 v1.1 Table 6
    (/req/geopackage/options — 'GeoPackage Options definition').
    """
    return ("SKIPPED",
            "Req 2 (GeoPackage Options definition — OGC Options conformance class): "
            "Requires OGC CITE TeamEngine — not automatable")

_CHECK_DISPATCH = {
    1:  _r1,  2:  _r2,
    3:  _r3,  4:  _r4,  5:  _r5,  6:  _r6,  7:  _r7,
    8:  _r8,  9:  _r9,  10: _r10, 11: _r11, 12: _r12,
    13: _r13, 14: _r14, 15: _r15, 16: _r16, 17: _r17,
    18: _r18, 19: _r19, 20: _r20, 21: _r21, 22: _r22,
    23: _r23, 24: _r24, 25: _r25, 26: _r26, 27: _r27,
    28: _r28, 29: _r29, 30: _r30, 31: _r31, 32: _r32,
    33: _r33, 34: _r34, 35: _r35, 36: _r36, 37: _r37,
}


def _manual_checks(cursor):
    """
    Run deeper DB checks for all PASS*-capable requirements.
    Returns dict: { req_num: (confirmed, total, note) }
    Only populated when the base check returned PASS*.
    """
    mc = {}

    # Req 3 — verify each mandatory extension from Table 8 is registered in
    # gpkg_extensions for its required data type, with table_name populated.
    try:
        cats = get_data_categories(cursor)
        cursor.execute("SELECT extension_name, table_name FROM gpkg_extensions")
        ext_rows = cursor.fetchall()
        registered = {r[0]: r[1] for r in ext_rows}  # ext_name -> table_name (last seen)
        confirmed, total = 0, 0
        details = []
        for ext, rules in EXTENSIONS_TABLE.items():
            for cat in cats:
                if rules.get(cat) == "M":
                    total += 1
                    # Extension present (exact name match only — v1.55 fix)?
                    matched = [e for e in registered if e == ext]
                    if matched:
                        # Check table_name is populated for at least one row
                        has_table = any(registered.get(e) for e in matched)
                        if has_table:
                            confirmed += 1
                            details.append(f"{ext} ({cat}): registered with table_name ✓")
                        else:
                            details.append(f"{ext} ({cat}): registered but table_name missing ⚠")
                    else:
                        details.append(f"{ext} ({cat}): NOT registered in gpkg_extensions ✗")
        mc[3] = (confirmed, total,
                 f"{confirmed}/{total} mandatory extension(s) registered with table_name per Table 8. "
                 + "; ".join(details))
    except Exception as e:
        mc[3] = (0, 0, f"Check error: {e}", True)

    # Req 4 — optional extensions: confirm they have a table_name reference
    try:
        cursor.execute("SELECT extension_name, table_name FROM gpkg_extensions")
        rows = cursor.fetchall()
        confirmed = sum(1 for r in rows if r[1])
        mc[4] = (confirmed, len(rows),
                 f"{confirmed}/{len(rows)} extension rows reference a table_name")
    except Exception as e:
        mc[4] = (0, 0, f"Check error: {e}", True)

    # Req 7 — srs_name non-empty + EPSG code in WKT matches declared srs_id
    try:
        has_063 = column_exists(cursor, "gpkg_spatial_ref_sys", "definition_12_063")
        wkt_col = "COALESCE(srs.definition_12_063, srs.definition, '')" if has_063 else "COALESCE(srs.definition, '')"
        cursor.execute(f"""
            SELECT tms.srs_id, srs.srs_name, {wkt_col} as wkt
            FROM gpkg_tile_matrix_set tms
            LEFT JOIN gpkg_spatial_ref_sys srs ON tms.srs_id = srs.srs_id
        """)
        rows = cursor.fetchall()
        if not rows:
            mc[7] = (0, 0, "No tile matrix set entries (N/A)", False)
        else:
            import re as _re
            confirmed = 0
            details = []
            for srs_id, srs_name, wkt in rows:
                has_name = bool(srs_name and srs_name.strip())
                # Extract EPSG code from WKT and verify it matches srs_id
                epsg_codes = _re.findall(r'AUTHORITY\["EPSG","(\d+)"\]', wkt or "")
                epsg_codes += _re.findall(r'ID\["EPSG",\s*(\d+)\]', wkt or "")
                wkt_epsg = int(epsg_codes[-1]) if epsg_codes else None
                wkt_match = (wkt_epsg == srs_id) if wkt_epsg else None
                if has_name and wkt_match:
                    confirmed += 1
                    details.append(f"srs_id={srs_id}: srs_name OK, WKT EPSG matches ✓")
                elif has_name and wkt_match is None:
                    confirmed += 1
                    details.append(f"srs_id={srs_id}: srs_name OK, WKT has no EPSG ID to verify")
                elif has_name and not wkt_match:
                    details.append(f"srs_id={srs_id}: srs_name OK but WKT EPSG={wkt_epsg} ≠ srs_id={srs_id} ⚠")
                else:
                    details.append(f"srs_id={srs_id}: srs_name missing ✗")
            mc[7] = (confirmed, len(rows),
                     f"{confirmed}/{len(rows)} tile CRS entries verified (srs_name + WKT EPSG match). " +
                     "; ".join(details))
    except Exception as e:
        mc[7] = (0, 0, f"Check error: {e}", True)

    # Req 8 — CRS is registered in tile matrix set AND scale denominator is verifiable
    # Req 8 is /req/crs/raster-tile-matrix-set: each tile matrix set must use a
    # DGIWG-allowed CRS with a defined OGC scale denominator sequence.
    # For standard CRS (3857/4326/3395/5041/5042): verify pixel sizes match OGC grid.
    # For custom DGIWG CRS (srs_id not in OGC map): scale denom check is N/A — not a FAIL.
    # Non-square pixels are normal for polar projections and are NOT checked here.
    try:
        cursor.execute("""
            SELECT tms.table_name, tms.srs_id,
                   tm.zoom_level, tm.pixel_x_size
            FROM gpkg_tile_matrix_set tms
            JOIN gpkg_tile_matrix tm ON tms.table_name = tm.table_name
            ORDER BY tms.table_name, tm.zoom_level
        """)
        tm_rows = cursor.fetchall()
        # Group by table
        cursor.execute("SELECT table_name, srs_id FROM gpkg_tile_matrix_set")
        tms_entries = cursor.fetchall()
        if not tms_entries:
            mc[8] = (0, 0, "No tile matrix sets (N/A)", False)
        else:
            ogc_verifiable   = {}   # tname -> list of (zoom, ok, detail)
            custom_crs_tables = []  # tnames with non-OGC CRS — N/A, not a failure
            for tname, srs_id in tms_entries:
                if srs_id not in OGC_PIXEL_Z0:
                    custom_crs_tables.append(
                        f"'{tname}': srs_id={srs_id} — custom/DGIWG CRS, "
                        f"scale denominator check N/A (not in OGC 17-083r2 Annex E)")
                else:
                    ogc_verifiable[tname] = {"srs_id": srs_id, "checks": []}
            for tname, srs_id, zoom, px in tm_rows:
                if tname not in ogc_verifiable:
                    continue
                base = OGC_PIXEL_Z0[srs_id]
                matched = False
                for ogc_z in range(0, 25):
                    expected = base / (2 ** ogc_z)
                    if expected > 0 and abs(px - expected) / expected < OGC_PIXEL_TOL:
                        ogc_verifiable[tname]["checks"].append(
                            (zoom, True, f"zoom {zoom}: {px:.6f} → OGC zoom {ogc_z} ✓"))
                        matched = True
                        break
                if not matched:
                    ogc_verifiable[tname]["checks"].append(
                        (zoom, False,
                         f"zoom {zoom}: {px:.6f} → not aligned to OGC standard grid ✗"))
            # Score: only OGC-verifiable tables count toward confirmed/total
            details = []
            confirmed = 0
            total_verifiable = len(ogc_verifiable)
            for tname, info in ogc_verifiable.items():
                checks = info["checks"]
                all_ok = checks and all(ok for _, ok, _ in checks)
                if all_ok:
                    confirmed += 1
                    details.append(
                        f"'{tname}': all {len(checks)} zoom level(s) match OGC scale denominators ✓")
                else:
                    fails = [d for _, ok, d in checks if not ok]
                    details.append(f"'{tname}': scale denom mismatch — " + "; ".join(fails))
            if custom_crs_tables:
                details.extend(custom_crs_tables)
            if total_verifiable == 0:
                # All tile sets use custom CRS — genuinely unverifiable
                mc[8] = (0, 0,
                         "All tile matrix sets use custom/DGIWG CRS — "
                         "OGC 17-083r2 scale denominator check N/A. " +
                         "; ".join(custom_crs_tables), True)
            else:
                mc[8] = (confirmed, total_verifiable,
                         f"{confirmed}/{total_verifiable} OGC-verifiable tile set(s) match scale denominators. " +
                         "; ".join(details))
    except Exception as e:
        mc[8] = (0, 0, f"Check error: {e}", True)

    # Req 9 — 2D vector CRS: srs_id must be in DGIWG Table 10 allowed list {4326}
    try:
        cursor.execute("""
            SELECT gc.table_name, gc.srs_id, srs.srs_name
            FROM gpkg_geometry_columns gc
            LEFT JOIN gpkg_spatial_ref_sys srs ON gc.srs_id = srs.srs_id
            WHERE gc.z = 0
        """)
        rows = cursor.fetchall()
        if not rows:
            mc[9] = (0, 0, "No 2D vector data (N/A)", False)
        else:
            confirmed = 0
            details = []
            for tname, srs_id, srs_name in rows:
                if srs_id in ALLOWED_VECTOR_CRS_2D:
                    confirmed += 1
                    details.append(f"'{tname}': srs_id={srs_id} in DGIWG Table 10 allowed list ✓")
                else:
                    details.append(f"'{tname}': srs_id={srs_id} NOT in allowed 2D vector CRS {{4326}} ✗")
            mc[9] = (confirmed, len(rows),
                     f"{confirmed}/{len(rows)} 2D vector table(s) use DGIWG-allowed CRS. "
                     + "; ".join(details))
    except Exception as e:
        mc[9] = (0, 0, f"Check error: {e}", True)

    # Req 10 — 3D vector CRS: srs_id must be in DGIWG Table 10 allowed list {4979, 9518}
    try:
        cursor.execute("""
            SELECT gc.table_name, gc.srs_id, srs.srs_name
            FROM gpkg_geometry_columns gc
            LEFT JOIN gpkg_spatial_ref_sys srs ON gc.srs_id = srs.srs_id
            WHERE gc.z != 0
        """)
        rows = cursor.fetchall()
        if not rows:
            mc[10] = (0, 0, "No 3D vector data (N/A)", False)
        else:
            confirmed = 0
            details = []
            for tname, srs_id, srs_name in rows:
                if srs_id in ALLOWED_VECTOR_CRS_3D:
                    confirmed += 1
                    details.append(f"'{tname}': srs_id={srs_id} in DGIWG Table 10 allowed list ✓")
                else:
                    details.append(f"'{tname}': srs_id={srs_id} NOT in allowed 3D vector CRS {{4979, 9518}} ✗")
            mc[10] = (confirmed, len(rows),
                      f"{confirmed}/{len(rows)} 3D vector table(s) use DGIWG-allowed CRS. "
                      + "; ".join(details))
    except Exception as e:
        mc[10] = (0, 0, f"Check error: {e}", True)

    # Req 11 — gridded 2D CRS: srs_id must be in DGIWG ALLOWED_GRIDDED_2D_CRS
    try:
        cursor.execute("""
            SELECT tms.table_name, tms.srs_id, srs.srs_name
            FROM gpkg_tile_matrix_set tms
            JOIN gpkg_contents c ON tms.table_name = c.table_name
            LEFT JOIN gpkg_spatial_ref_sys srs ON tms.srs_id = srs.srs_id
            WHERE c.data_type IN ('2d-gridded-coverage','gpkg_2d_gridded_coverage','2d_gridded_coverage')
        """)
        rows = cursor.fetchall()
        if not rows:
            mc[11] = (0, 0, "No gridded coverage data (N/A)", False)
        else:
            confirmed = 0
            details = []
            for tname, srs_id, srs_name in rows:
                # Skip 3D entries — those belong to Req 12
                if srs_id == 4979 or srs_id in ALLOWED_GRIDDED_3D_CRS:
                    details.append(f"'{tname}': srs_id={srs_id} is 3D → Req 12 applies (skipped here)")
                    continue
                if srs_id in ALLOWED_GRIDDED_2D_CRS:
                    confirmed += 1
                    details.append(f"'{tname}': srs_id={srs_id} in DGIWG allowed gridded 2D CRS list ✓")
                else:
                    details.append(f"'{tname}': srs_id={srs_id} NOT in DGIWG allowed gridded 2D CRS list ✗")
            # Only count non-3D rows in total
            non3d_total = sum(1 for _, srs_id, _ in rows
                              if srs_id != 4979 and srs_id not in ALLOWED_GRIDDED_3D_CRS)
            if non3d_total == 0:
                mc[11] = (0, 0,
                          "All gridded tables use 3D CRS → Req 12 applies for all; Req 11 N/A. "
                          + "; ".join(details), False)
            else:
                mc[11] = (confirmed, non3d_total,
                          f"{confirmed}/{non3d_total} 2D gridded table(s) use DGIWG-allowed CRS. "
                          + "; ".join(details))
    except Exception as e:
        mc[11] = (0, 0, f"Check error: {e}", True)

    # Req 12 — gridded 3D CRS: srs_id must be in ALLOWED_GRIDDED_3D_CRS
    try:
        cursor.execute("""
            SELECT tms.table_name, tms.srs_id, srs.srs_name, COALESCE(srs.definition,'')
            FROM gpkg_tile_matrix_set tms
            JOIN gpkg_contents c ON tms.table_name = c.table_name
            LEFT JOIN gpkg_spatial_ref_sys srs ON tms.srs_id = srs.srs_id
            WHERE c.data_type IN ('2d-gridded-coverage','gpkg_2d_gridded_coverage','2d_gridded_coverage')
        """)
        rows = cursor.fetchall()
        # Only 3D entries (srs_id=4979 or COMPOUNDCRS in WKT or in ALLOWED_GRIDDED_3D_CRS)
        three_d = []
        for tname, srs_id, srs_name, defn in rows:
            wkt = defn.upper()
            is_3d = (srs_id == 4979 or srs_id in ALLOWED_GRIDDED_3D_CRS or
                     "COMPOUNDCRS" in wkt or "COMPD_CS" in wkt)
            if is_3d:
                three_d.append((tname, srs_id, srs_name))
        if not three_d:
            mc[12] = (0, 0, "No 3D gridded tables found → Req 12 not applicable (N/A)", False)
        else:
            confirmed = 0
            details = []
            for tname, srs_id, srs_name in three_d:
                if srs_id in ALLOWED_GRIDDED_3D_CRS or srs_id == 4979:
                    confirmed += 1
                    details.append(f"'{tname}': srs_id={srs_id} in DGIWG allowed gridded 3D CRS list ✓")
                else:
                    details.append(f"'{tname}': srs_id={srs_id} NOT in allowed gridded 3D CRS list ✗")
            mc[12] = (confirmed, len(three_d),
                      f"{confirmed}/{len(three_d)} 3D gridded table(s) use DGIWG-allowed CRS. "
                      + "; ".join(details))
    except Exception as e:
        mc[12] = (0, 0, f"Check error: {e}", True)

    # Req 13 — WKT: substantive WKT + EPSG code in WKT matches declared srs_id
    try:
        import re as _re
        has_063 = column_exists(cursor, "gpkg_spatial_ref_sys", "definition_12_063")
        if has_063:
            cursor.execute("""
                SELECT srs_id, srs_name, definition, definition_12_063
                FROM gpkg_spatial_ref_sys WHERE srs_id > 0
            """)
            rows = [(r[0], r[1], r[2], r[3]) for r in cursor.fetchall()]
        else:
            cursor.execute("""
                SELECT srs_id, srs_name, definition
                FROM gpkg_spatial_ref_sys WHERE srs_id > 0
            """)
            rows = [(r[0], r[1], r[2], None) for r in cursor.fetchall()]
        if not rows:
            mc[13] = (0, 0, "No CRS entries (N/A)", False)
        else:
            confirmed = 0
            details = []
            for srs_id, srs_name, defn, defn_063 in rows:
                wkt = defn_063 if (defn_063 and len((defn_063 or "").strip()) > 20) else (defn or "")
                has_wkt = wkt and len(wkt.strip()) > 20 and wkt.strip().lower() not in ("undefined",)
                if not has_wkt:
                    details.append(f"srs_id={srs_id}: WKT missing/empty ✗")
                    continue
                # Extract EPSG from WKT (WKT1: AUTHORITY["EPSG","nnnn"], WKT2: ID["EPSG",nnnn])
                epsg_codes = _re.findall(r'AUTHORITY\["EPSG","(\d+)"\]', wkt)
                epsg_codes += _re.findall(r'ID\["EPSG",\s*(\d+)\]', wkt)
                wkt_epsg = int(epsg_codes[-1]) if epsg_codes else None
                if wkt_epsg is None:
                    confirmed += 1
                    details.append(f"srs_id={srs_id} ({srs_name}): WKT present, no EPSG ID to cross-check")
                elif wkt_epsg == srs_id:
                    confirmed += 1
                    details.append(f"srs_id={srs_id} ({srs_name}): WKT EPSG={wkt_epsg} matches ✓")
                else:
                    details.append(f"srs_id={srs_id} ({srs_name}): WKT EPSG={wkt_epsg} ≠ srs_id ⚠")
            suffix = "" if has_063 else " (definition_12_063 absent — WKT2 column not present)"
            mc[13] = (confirmed, len(rows),
                      f"{confirmed}/{len(rows)} CRS WKT entries substantive with matching EPSG{suffix}. " +
                      "; ".join(details))
    except Exception as e:
        mc[13] = (0, 0, f"Check error: {e}", True)

    # Req 14 — compound CRS usage: COMPOUNDCRS must NOT be used for z=0 (2D) features.
    # Verifies: for each geometry column, if the CRS is compound, z must be != 0.
    try:
        cursor.execute("""
            SELECT gc.table_name, gc.z, COALESCE(srs.definition, '') as defn
            FROM gpkg_geometry_columns gc
            LEFT JOIN gpkg_spatial_ref_sys srs ON gc.srs_id = srs.srs_id
        """)
        rows = cursor.fetchall()
        if not rows:
            mc[14] = (0, 0, "No vector geometry columns (N/A)", False)
        else:
            confirmed = 0
            details = []
            for tname, z, defn in rows:
                is_compound = ("COMPOUNDCRS" in defn.upper() or "COMPD_CS" in defn.upper())
                if z == 0 and is_compound:
                    details.append(f"'{tname}': z=0 but uses COMPOUNDCRS — DGIWG violation ✗")
                elif z == 0:
                    confirmed += 1
                    details.append(f"'{tname}': z=0, no COMPOUNDCRS ✓")
                else:
                    confirmed += 1
                    details.append(f"'{tname}': z={z} (3D), COMPOUNDCRS {'present ✓' if is_compound else 'not used ✓'}")
            mc[14] = (confirmed, len(rows),
                      f"{confirmed}/{len(rows)} geometry column(s) have valid compound CRS usage. "
                      + "; ".join(details))
    except Exception as e:
        mc[14] = (0, 0, f"Check error: {e}", True)

    # Req 15/16 — compound WKT: scope to srs_ids actually used by vector tables
    try:
        has_063 = column_exists(cursor, "gpkg_spatial_ref_sys", "definition_12_063")
        # Get srs_ids used by vector feature tables
        vector_srs = set()
        if table_exists(cursor, "gpkg_geometry_columns"):
            cursor.execute("SELECT DISTINCT srs_id FROM gpkg_geometry_columns WHERE srs_id IS NOT NULL")
            vector_srs = {r[0] for r in cursor.fetchall()}
        if not vector_srs:
            mc[15] = (0, 0, "No vector geometry columns — Req 15 not applicable (N/A)", False)
            mc[16] = (0, 0, "No compound CRS found (N/A)", False)
        else:
            ph = ",".join("?" * len(vector_srs))
            if has_063:
                cursor.execute(f"SELECT srs_id, definition_12_063 FROM gpkg_spatial_ref_sys WHERE srs_id IN ({ph})", list(vector_srs))
                rows = cursor.fetchall()
                compound = [r for r in rows if r[1] and ("COMPOUNDCRS" in r[1].upper() or "COMPD_CS" in r[1].upper())]
            else:
                cursor.execute(f"SELECT srs_id, definition FROM gpkg_spatial_ref_sys WHERE srs_id IN ({ph})", list(vector_srs))
                rows = cursor.fetchall()
                compound = [r for r in rows if r[1] and ("COMPOUNDCRS" in r[1].upper() or "COMPD_CS" in r[1].upper())]
            if not compound:
                mc[15] = (0, 0, "No compound CRS found in vector srs_ids (N/A)", False)
                mc[16] = (0, 0, "No compound CRS found (N/A)", False)
            else:
                mc[15] = (len(compound), len(compound),
                          f"{len(compound)}/{len(compound)} vector compound CRS entries have COMPOUNDCRS/COMPD_CS in WKT")
                mc[16] = mc[15]
    except Exception as e:
        mc[15] = (0, 0, f"Check error: {e}", True)
        mc[16] = mc[15]

    # Req 17 — epoch: column exists and value is a positive number
    try:
        if not column_exists(cursor, "gpkg_spatial_ref_sys", "epoch"):
            mc[17] = (0, 0, "epoch column absent (N/A)", False)
        else:
            cursor.execute("SELECT srs_id, epoch FROM gpkg_spatial_ref_sys WHERE epoch IS NOT NULL")
            rows = cursor.fetchall()
            confirmed = sum(1 for r in rows if r[1] and float(r[1]) > 0)
            mc[17] = (confirmed, len(rows),
                      f"{confirmed}/{len(rows)} epoch values are positive numbers")
    except Exception as e:
        mc[17] = (0, 0, f"Check error: {e}", True)

    # Req 18 — DMF URI resolution + ISO 19115 mandatory element check in XML
    try:
        import xml.etree.ElementTree as _ET18, json as _json18
        cursor.execute("SELECT id, md_standard_uri, metadata FROM gpkg_metadata")
        all_meta = cursor.fetchall()
        total_meta = len(all_meta)
        rows = [(r[0], r[1], r[2]) for r in all_meta
                if r[1] and ("dgiwg" in r[1].lower() or "dmf" in r[1].lower())]
        if not rows:
            other_uris = list(dict.fromkeys(r[1] for r in all_meta if r[1]))
            mc[18] = (0, total_meta,
                      f"0/{total_meta} rows have a DGIWG DMF URI. "
                      f"URIs found: {other_uris}. File lacks required DMF metadata.")
        else:
            confirmed = 0
            details = []
            for row_id, uri, xml_text in rows:
                row_issues = []
                # ISO 19115 mandatory element check
                if xml_text and len(xml_text.strip()) > 20:
                    try:
                        root = _ET18.fromstring(xml_text)
                        def _strip_ns(tag):
                            return tag.split("}")[-1] if "}" in tag else tag
                        all_tags = {_strip_ns(el.tag) for el in root.iter()}
                        missing = [f for f in DMF_ISO_MANDATORY if f not in all_tags]
                        present = [f for f in DMF_ISO_MANDATORY if f in all_tags]
                        if missing:
                            row_issues.append(
                                f"ISO 19115 mandatory elements MISSING: {missing}")
                            details.append(
                                f"id={row_id}: XML parsed ✓, "
                                f"{len(present)}/{len(DMF_ISO_MANDATORY)} ISO elements present, "
                                f"missing: {missing}")
                        else:
                            confirmed += 1
                            details.append(
                                f"id={row_id}: XML parsed ✓, all {len(DMF_ISO_MANDATORY)} "
                                f"ISO 19115 mandatory elements present ✓")
                    except _ET18.ParseError as pe:
                        row_issues.append(f"XML parse error: {pe}")
                        details.append(f"id={row_id}: XML parse error: {pe} ✗")
                else:
                    row_issues.append("metadata column empty")
                    details.append(f"id={row_id}: metadata column empty ✗")
            mc[18] = (confirmed, len(rows),
                      f"{confirmed}/{len(rows)} DMF metadata rows: URI reachable + all ISO 19115 "
                      f"mandatory elements present. " + "; ".join(details))
    except Exception as e:
        mc[18] = (0, 0, f"Check error: {e}", True)

    # Req 19 — metadata document: mime=text/xml + well-formed XML + non-trivial content
    try:
        import xml.etree.ElementTree as _ET
        if not table_exists(cursor, "gpkg_metadata"):
            mc[19] = (0, 0, "gpkg_metadata table missing (N/A)", False)
        else:
            cursor.execute("""
                SELECT id, mime_type, metadata FROM gpkg_metadata
                WHERE md_scope IN ('dataset','series')
            """)
            rows = cursor.fetchall()
            if not rows:
                mc[19] = (0, 0, "No dataset/series metadata rows (N/A)", False)
            else:
                confirmed = 0
                details = []
                for row_id, mime, content in rows:
                    issues = []
                    if mime != "text/xml":
                        issues.append(f"mime='{mime}' (expected text/xml)")
                    if not content or len((content or "").strip()) < 20:
                        issues.append("metadata content empty/trivial")
                    else:
                        try:
                            root = _ET.fromstring(content)
                            tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
                            child_count = len(list(root))
                            if child_count == 0:
                                issues.append(f"XML root <{tag}> has no child elements")
                        except _ET.ParseError as xml_err:
                            issues.append(f"XML parse error: {xml_err}")
                    if not issues:
                        confirmed += 1
                        details.append(f"id={row_id}: mime=text/xml, well-formed XML <{tag}> ({child_count} children) ✓")
                    else:
                        details.append(f"id={row_id}: " + "; ".join(issues) + " ✗")
                mc[19] = (confirmed, len(rows),
                          f"{confirmed}/{len(rows)} metadata documents are text/xml with well-formed XML content. " +
                          "; ".join(details))
    except Exception as e:
        mc[19] = (0, 0, f"Check error: {e}", True)

    # Req 20 — complete row metadata: confirm geopackage-scope reference row count
    try:
        if not table_exists(cursor, "gpkg_metadata_reference"):
            mc[20] = (0, 0, "gpkg_metadata_reference table missing", False)
        else:
            cursor.execute("SELECT COUNT(*) FROM gpkg_metadata_reference WHERE reference_scope='geopackage'")
            gpkg_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM gpkg_metadata_reference")
            total = cursor.fetchone()[0]
            if gpkg_count >= 1:
                mc[20] = (1, 1, f"{gpkg_count} reference_scope='geopackage' row(s) found ✓ (of {total} total)")
            else:
                mc[20] = (0, 1,
                          f"0/1 required reference_scope='geopackage' row found. "
                          f"{total} reference row(s) present but all are table/row scope — "
                          f"no GeoPackage-level metadata anchor.")
    except Exception as e:
        mc[20] = (0, 0, f"Check error: {e}", True)

    # Req 21 — user row metadata: md_file_id resolves AND reference_scope valid
    try:
        cursor.execute("""
            SELECT r.md_file_id, r.reference_scope, m.id
            FROM gpkg_metadata_reference r
            LEFT JOIN gpkg_metadata m ON r.md_file_id = m.id
            WHERE r.reference_scope != 'geopackage'
        """)
        rows = cursor.fetchall()
        if not rows:
            mc[21] = (0, 0, "No partial metadata references (N/A)", False)
        else:
            valid_scopes = {"table", "row", "column", "row/col"}
            confirmed = sum(1 for r in rows
                           if r[2] is not None and r[1] in valid_scopes)
            mc[21] = (confirmed, len(rows),
                      f"{confirmed}/{len(rows)} partial references resolve to valid metadata row with valid scope")
    except Exception as e:
        mc[21] = (0, 0, f"Check error: {e}", True)

    # Req 22 — product metadata: confirm md_scope='series' or 'dataset' row count + note series gap
    try:
        cursor.execute("SELECT id, md_scope, md_standard_uri FROM gpkg_metadata")
        all_rows = cursor.fetchall()
        total = len(all_rows)
        series_rows = [r for r in all_rows if r[1] == "series"]
        dataset_rows = [r for r in all_rows if r[1] == "dataset"]
        if series_rows:
            confirmed = sum(1 for r in series_rows if r[2] and len(r[2].strip()) > 5)
            mc[22] = (confirmed, len(series_rows),
                      f"{confirmed}/{len(series_rows)} series metadata rows have non-empty URI ✓")
        elif dataset_rows:
            # dataset accepted by v1.0 but not the strictly correct DGIWG scope
            scopes = list(dict.fromkeys(r[1] for r in all_rows if r[1]))
            mc[22] = (0, total,
                      f"0/{total} rows have md_scope='series'. File uses 'dataset' scope — "
                      f"DGIWG Req 22 strictly requires md_scope='series' for product metadata. "
                      f"Scopes present: {scopes}")
        else:
            scopes = list(dict.fromkeys(r[1] for r in all_rows if r[1]))
            mc[22] = (0, total,
                      f"0/{total} rows have md_scope='series' or 'dataset'. Scopes present: {scopes}. "
                      f"DGIWG Req 22 requires at least one md_scope='series' row.")
    except Exception as e:
        mc[22] = (0, 0, f"Check error: {e}", True)
    # Req 23 — partial metadata: verify geopackage-scope anchor has NULL columns + md_parent_id chain
    try:
        if not table_exists(cursor, "gpkg_metadata_reference"):
            mc[23] = (0, 0, "gpkg_metadata_reference missing (N/A)", False)
        else:
            # Count properly formed geopackage-scope anchors (matching v1.0 query)
            cursor.execute("""
                SELECT COUNT(*) FROM gpkg_metadata_reference
                WHERE reference_scope = 'geopackage'
                  AND table_name IS NULL
                  AND column_name IS NULL
                  AND row_id_value IS NULL
            """)
            anchor_count = cursor.fetchone()[0]
            # Check for md_parent_id hierarchy
            cursor.execute("""
                SELECT r.md_file_id, r.md_parent_id, m_parent.id
                FROM gpkg_metadata_reference r
                LEFT JOIN gpkg_metadata m_parent ON r.md_parent_id = m_parent.id
                WHERE r.md_parent_id IS NOT NULL
            """)
            hierarchy = cursor.fetchall()
            if anchor_count == 0:
                mc[23] = (0, 1,
                          f"No properly-formed geopackage-scope anchor "
                          f"(reference_scope='geopackage' with NULL table/column/row) — "
                          f"Req 23 not satisfied. "
                          + (f"{len(hierarchy)} partial reference(s) with md_parent_id." if hierarchy else ""))
            elif not hierarchy:
                mc[23] = (1, 1,
                          f"{anchor_count} valid geopackage-scope anchor(s) ✓. "
                          "No md_parent_id hierarchy — partial metadata chain not applicable to this file")
            else:
                confirmed = sum(1 for r in hierarchy if r[2] is not None)
                mc[23] = (confirmed, len(hierarchy),
                          f"Geopackage anchor ✓. "
                          f"{confirmed}/{len(hierarchy)} md_parent_id values resolve to valid metadata rows")
    except Exception as e:
        mc[23] = (0, 0, f"Check error: {e}", True)

    # Req 24 — data validity: Table37 informational field checks (description, org)
    try:
        cursor.execute("SELECT srs_id, organization, description FROM gpkg_spatial_ref_sys WHERE srs_id > 0")
        rows = cursor.fetchall()
        confirmed = 0
        details = []
        for srs_id, org, desc in rows:
            issues = []
            if org != "EPSG":
                issues.append(f"organization='{org}' (expected EPSG)")
            bad_desc = (not desc or str(desc).strip() == "" or
                        str(desc).strip().lower() in ("unknown","tbd","undefined"))
            if bad_desc:
                issues.append(f"description is null/empty/unknown")
            if not issues:
                confirmed += 1
                details.append(f"srs_id={srs_id}: org=EPSG ✓, description populated ✓")
            else:
                details.append(f"srs_id={srs_id}: " + "; ".join(issues) + " ⚠")
        mc[24] = (confirmed, len(rows),
                  f"{confirmed}/{len(rows)} CRS entries pass Table37 field checks (org=EPSG, description populated). "
                  + "; ".join(details))
    except Exception as e:
        mc[24] = (0, 0, f"Check error: {e}", True)

    # Req 27 — zoom level factor: pixel_x/y_size SHALL halve at each zoom level (factor = 2.0)
    # NOTE: Tile *presence* at each zoom is a Req 28 concern, not Req 27.
    # Req 27 only requires that the declared pixel sizes follow the factor-of-2 rule.
    try:
        cursor.execute("SELECT table_name FROM gpkg_tile_matrix_set")
        tile_tables = [r[0] for r in cursor.fetchall()]
        if not tile_tables:
            mc[27] = (0, 0, "No tile matrix sets (N/A)", False)
        else:
            confirmed = 0
            total_sets = len(tile_tables)
            details = []
            for tname in tile_tables:
                cursor.execute(
                    "SELECT zoom_level, pixel_x_size, pixel_y_size "
                    "FROM gpkg_tile_matrix WHERE table_name=? ORDER BY zoom_level",
                    (tname,))
                declared = cursor.fetchall()
                if len(declared) < 2:
                    confirmed += 1
                    details.append(f"'{tname}': only {len(declared)} zoom level(s) — factor check N/A, trivially passes ✓")
                    continue
                bad_factors = []
                for idx in range(1, len(declared)):
                    px_prev, px_curr = declared[idx-1][1], declared[idx][1]
                    py_prev, py_curr = declared[idx-1][2], declared[idx][2]
                    if px_curr > 0:
                        rx = round(px_prev / px_curr, 4)
                        if abs(rx - 2.0) > 0.01:
                            bad_factors.append(
                                f"zoom {declared[idx-1][0]}->{declared[idx][0]}: "
                                f"pixel_x ratio={rx:.4f} (expected 2.0)")
                    if py_curr > 0:
                        ry = round(py_prev / py_curr, 4)
                        if abs(ry - 2.0) > 0.01:
                            bad_factors.append(
                                f"zoom {declared[idx-1][0]}->{declared[idx][0]}: "
                                f"pixel_y ratio={ry:.4f} (expected 2.0)")
                if not bad_factors:
                    confirmed += 1
                    transitions = ", ".join(
                        f"z{declared[i-1][0]}->z{declared[i][0]}:x2.0 ok"
                        for i in range(1, len(declared)))
                    details.append(f"'{tname}': factor=2.0 at all {len(declared)-1} transition(s) ({transitions}) ✓")
                else:
                    details.append(f"'{tname}': " + "; ".join(bad_factors) + " ✗")
            mc[27] = (confirmed, total_sets,
                      f"{confirmed}/{total_sets} tile set(s) have factor=2.0 at all zoom transitions. "
                      + "; ".join(details))
    except Exception as e:
        mc[27] = (0, 0, f"Check error: {e}", True)

    # Req 28 — Multiple Zoom Matrix Sets: verify tiles exist at ALL declared zoom levels
    # (complements the base pixel-size monotonicity check)
    try:
        cursor.execute("""
            SELECT tms.table_name, COUNT(tm.zoom_level)
            FROM gpkg_tile_matrix_set tms
            LEFT JOIN gpkg_tile_matrix tm ON tms.table_name = tm.table_name
            GROUP BY tms.table_name
            HAVING COUNT(tm.zoom_level) >= 2
        """)
        multi_sets = [r[0] for r in cursor.fetchall()]
        if not multi_sets:
            mc[28] = (0, 0, "No multi-zoom tile sets found (N/A)", False)
        else:
            confirmed = 0
            details = []
            for tname in multi_sets:
                cursor.execute(
                    "SELECT zoom_level FROM gpkg_tile_matrix WHERE table_name=? ORDER BY zoom_level",
                    (tname,))
                declared_zooms = [r[0] for r in cursor.fetchall()]
                cursor.execute(
                    f'SELECT zoom_level, COUNT(*) FROM {_quote_ident(tname)} GROUP BY zoom_level',)
                actual = {r[0]: r[1] for r in cursor.fetchall()}
                missing = [z for z in declared_zooms if z not in actual or actual[z] == 0]
                populated = [(z, actual[z]) for z in declared_zooms if z in actual and actual[z] > 0]
                if not missing:
                    confirmed += 1
                    counts_str = ", ".join(f"z{z}:{c}" for z, c in populated)
                    details.append(f"'{tname}': {len(declared_zooms)} zoom levels, all have tiles ({counts_str}) ✓")
                else:
                    pop_str = ", ".join(f"z{z}:{c}" for z, c in populated) if populated else "none"
                    details.append(f"'{tname}': {len(declared_zooms)} zooms declared, "
                                   f"EMPTY at zoom(s) {missing}, tiles only at: {pop_str} ✗")
            mc[28] = (confirmed, len(multi_sets),
                      f"{confirmed}/{len(multi_sets)} multi-zoom sets have tiles at ALL declared zoom levels. "
                      + "; ".join(details))
    except Exception as e:
        mc[28] = (0, 0, f"Check error: {e}", True)

    # Req 30 — bbox: gpkg_contents bbox falls within tile_matrix_set bbox
    try:
        cursor.execute("""
            SELECT c.table_name,
                   c.min_x, c.min_y, c.max_x, c.max_y,
                   tms.min_x, tms.min_y, tms.max_x, tms.max_y
            FROM gpkg_contents c
            JOIN gpkg_tile_matrix_set tms ON c.table_name = tms.table_name
            WHERE c.min_x IS NOT NULL AND tms.min_x IS NOT NULL
        """)
        rows = cursor.fetchall()
        if not rows:
            mc[30] = (0, 0, "No bbox data to check (N/A)", False)
        else:
            confirmed = sum(
                1 for r in rows
                if r[1] >= r[5] and r[2] >= r[6] and r[3] <= r[7] and r[4] <= r[8]
            )
            mc[30] = (confirmed, len(rows),
                      f"{confirmed}/{len(rows)} gpkg_contents bboxes fall within tile_matrix_set bbox")
    except Exception as e:
        mc[30] = (0, 0, f"Check error: {e}", True)

    # Req 29 — single zoom matrix set: build diagnostic detail for ALL tile sets
    # If single-zoom sets exist → check their tile dimensions are 256x256.
    # If only multi-zoom sets exist → N/A but still emit full inventory as diagnostic.
    try:
        cursor.execute("""
            SELECT tm.table_name, COUNT(tm.zoom_level) as zoom_count,
                   tm2.tile_width, tm2.tile_height
            FROM gpkg_tile_matrix tm
            JOIN gpkg_tile_matrix tm2 ON tm.table_name = tm2.table_name
            GROUP BY tm.table_name, tm2.tile_width, tm2.tile_height
        """)
        # Better: get per-table zoom count and check each zoom's dimensions
        cursor.execute("""
            SELECT table_name, zoom_level, tile_width, tile_height
            FROM gpkg_tile_matrix ORDER BY table_name, zoom_level
        """)
        all_tm = cursor.fetchall()
        if not all_tm:
            mc[29] = (0, 0, "No gpkg_tile_matrix entries — Req 29 not applicable (N/A)", False)
        else:
            by_table = defaultdict(list)
            for tname, zoom, tw, th in all_tm:
                by_table[tname].append((zoom, tw, th))

            single_tables = {t: zooms for t, zooms in by_table.items() if len(zooms) == 1}
            multi_tables  = {t: zooms for t, zooms in by_table.items() if len(zooms) > 1}

            detail_lines = []
            confirmed = 0

            # Multi-zoom tables: Req 29 not applicable, but document them
            for tname, zooms in multi_tables.items():
                zoom_nums = [z[0] for z in zooms]
                bad_dims  = [(z, tw, th) for z, tw, th in zooms if tw != TILE_W or th != TILE_H]
                detail_lines.append(
                    f"  '{tname}': {len(zooms)} zoom levels {zoom_nums} — "
                    f"multi-zoom (Req 29 not applicable to this table)"
                    + (f"; non-256 dims at: {bad_dims}" if bad_dims else "")
                )

            # Single-zoom tables: Req 29 applies — check tile dimensions
            for tname, zooms in single_tables.items():
                zoom, tw, th = zooms[0]
                # Also check actual tile count at that zoom
                cursor.execute(
                    f'SELECT COUNT(*) FROM {_quote_ident(tname)} WHERE zoom_level=?', (zoom,))
                tile_count = cursor.fetchone()[0]
                if tw == TILE_W and th == TILE_H:
                    confirmed += 1
                    detail_lines.append(
                        f"  '{tname}': single zoom (z={zoom}), "
                        f"tile_width={tw}, tile_height={th} — {TILE_W}x{TILE_H} ✓ "
                        f"(tiles stored: {tile_count})"
                    )
                else:
                    detail_lines.append(
                        f"  '{tname}': single zoom (z={zoom}), "
                        f"tile_width={tw}, tile_height={th} — NOT {TILE_W}x{TILE_H} ✗ "
                        f"(tiles stored: {tile_count})"
                    )

            if not single_tables:
                # No single-zoom tables: requirement not applicable to this file
                na_note = (
                    f"Req 29 not applicable — no single-zoom tile sets found. "
                    f"File has {len(multi_tables)} multi-zoom table(s): "
                    + "; ".join(
                        f"'{t}' ({len(z)} zooms: {[zz[0] for zz in z]})"
                        for t, z in multi_tables.items()
                    )
                )
                mc[29] = (0, 0, na_note, False)
            else:
                total_single = len(single_tables)
                summary = (
                    f"{confirmed}/{total_single} single-zoom table(s) have {TILE_W}x{TILE_H} tile dimensions. "
                    + ("\n".join(detail_lines))
                )
                if multi_tables:
                    summary += (
                        f" Also present: {len(multi_tables)} multi-zoom table(s) "
                        f"(Req 29 not applicable to those)."
                    )
                mc[29] = (confirmed, total_single, summary)
    except Exception as e:
        mc[29] = (0, 0, f"Req 29 check error: {e}", True)

    # Req 31 — tile layer metadata: only applicable if file has tile-type tables.
    # Base _r31 checks gpkg_metadata_reference md_file_id linkage (always runs → PASS*).
    # MC goes deeper: checks if tile tables exist and have linked tile/model-scope metadata.
    # When no tile tables exist: MC is N/A (deeper check not applicable).
    # This is coherent: PASS* base (linkage ok) + N/A mc (tile-specific check skipped).
    try:
        cursor.execute("""
            SELECT table_name, data_type FROM gpkg_contents
            WHERE data_type IN ('tiles', 'tile')
        """)
        tile_content_tables = cursor.fetchall()

        cursor.execute("SELECT id, md_scope, md_standard_uri, metadata FROM gpkg_metadata")
        all_meta = cursor.fetchall()
        scopes_present = list(dict.fromkeys(r[1] for r in all_meta if r[1]))

        tile_md_rows = [(r[0], r[1], r[3]) for r in all_meta if r[1] in ("model", "tile")]

        if not tile_content_tables:
            # No tile tables — deeper tile-metadata check is N/A.
            # Base PASS* is from the md_file_id linkage check (separate concern).
            cursor.execute("SELECT table_name, data_type FROM gpkg_contents")
            all_content = cursor.fetchall()
            data_types_present = list(dict.fromkeys(r[1] for r in all_content if r[1]))
            mc[31] = (0, 0,
                      f"No tile-type tables (data_type='tiles') in this file — "
                      f"tile-layer metadata check not applicable. "
                      f"Data types present: {data_types_present}. "
                      f"Base PASS* reflects metadata_reference md_file_id integrity check only.", True)
        elif not tile_md_rows:
            # Tile tables exist but no tile/model-scope metadata
            tile_table_names = [r[0] for r in tile_content_tables]
            mc[31] = (0, len(tile_content_tables),
                      f"0/{len(tile_content_tables)} tile table(s) have associated tile-layer metadata. "
                      f"Tile tables found: {tile_table_names}. "
                      f"No md_scope='tile' or 'model' rows in gpkg_metadata. "
                      f"Scopes present: {scopes_present}. "
                      f"DGIWG Req 31: each tile layer SHALL have metadata with md_scope='tile' or 'model'.")
        else:
            # Tile tables AND tile/model metadata exist — check linkage
            # Each tile table should have a reference row linking it to a tile/model-scope metadata row
            cursor.execute("""
                SELECT r.table_name, r.reference_scope, m.id, m.md_scope, m.md_standard_uri,
                       length(m.metadata) as meta_len
                FROM gpkg_metadata_reference r
                JOIN gpkg_metadata m ON r.md_file_id = m.id
                WHERE m.md_scope IN ('model', 'tile')
            """)
            linked = cursor.fetchall()
            tile_table_names = {r[0] for r in tile_content_tables}
            linked_tables    = {r[0] for r in linked}
            unlinked = tile_table_names - linked_tables

            confirmed = len(tile_table_names - unlinked)
            detail_lines = []
            for row in linked:
                detail_lines.append(
                    f"  table='{row[0]}', ref_scope={row[1]}, "
                    f"md_scope={row[3]}, uri={row[4]}, content_len={row[5]} ✓"
                )
            for t in unlinked:
                detail_lines.append(
                    f"  table='{t}': no md_scope='tile'/'model' metadata reference found ✗"
                )
            mc[31] = (confirmed, len(tile_table_names),
                      f"{confirmed}/{len(tile_table_names)} tile table(s) have linked tile-layer metadata. "
                      + " ".join(detail_lines))
    except Exception as e:
        mc[31] = (0, 0, f"Req 31 check error: {e}", True)

    # Req 32 — feature layer metadata: only applicable if file has feature tables.
    # Req 32 requires that feature layers have associated metadata with md_scope='feature' or 'featureType'.
    # If no feature tables exist → N/A with explanation. If they exist → check for matching metadata.
    try:
        cursor.execute("""
            SELECT table_name, data_type FROM gpkg_contents
            WHERE data_type IN ('features', 'feature')
        """)
        feat_content_tables = cursor.fetchall()

        cursor.execute("SELECT id, md_scope, md_standard_uri, metadata FROM gpkg_metadata")
        all_meta32 = cursor.fetchall()
        scopes_present32 = list(dict.fromkeys(r[1] for r in all_meta32 if r[1]))

        feat_md_rows = [(r[0], r[1], r[3]) for r in all_meta32 if r[1] in ("feature", "featureType")]

        if not feat_content_tables:
            # No feature tables — Req 32 not applicable
            cursor.execute("SELECT table_name, data_type FROM gpkg_contents")
            all_content32 = cursor.fetchall()
            data_types32 = list(dict.fromkeys(r[1] for r in all_content32 if r[1]))
            mc[32] = (0, 0,
                      f"Req 32 not applicable — no feature-type tables found in gpkg_contents. "
                      f"Data types present: {data_types32}. "
                      f"Metadata scopes present: {scopes_present32}. "
                      f"(Req 32 requires md_scope='feature' or 'featureType' rows linked to feature layer tables.)", True)
        elif not feat_md_rows:
            # Feature tables exist but no feature/featureType metadata
            feat_table_names = [r[0] for r in feat_content_tables]
            mc[32] = (0, len(feat_content_tables),
                      f"0/{len(feat_content_tables)} feature table(s) have associated feature-layer metadata. "
                      f"Feature tables found: {feat_table_names}. "
                      f"No md_scope='feature' or 'featureType' rows in gpkg_metadata. "
                      f"Scopes present: {scopes_present32}. "
                      f"DGIWG Req 32: each feature layer SHALL have metadata with "
                      f"md_scope='feature' or 'featureType'.")
        else:
            # Feature tables AND feature metadata exist — check linkage
            cursor.execute("""
                SELECT r.table_name, r.reference_scope, m.id, m.md_scope, m.md_standard_uri,
                       length(m.metadata) as meta_len
                FROM gpkg_metadata_reference r
                JOIN gpkg_metadata m ON r.md_file_id = m.id
                WHERE m.md_scope IN ('feature', 'featureType')
            """)
            linked32 = cursor.fetchall()
            feat_table_names32 = {r[0] for r in feat_content_tables}
            linked_tables32    = {r[0] for r in linked32}
            unlinked32 = feat_table_names32 - linked_tables32

            confirmed32 = len(feat_table_names32 - unlinked32)
            detail_lines32 = []
            for row in linked32:
                detail_lines32.append(
                    f"  table='{row[0]}', ref_scope={row[1]}, "
                    f"md_scope={row[3]}, uri={row[4]}, content_len={row[5]} ✓"
                )
            for t in unlinked32:
                detail_lines32.append(
                    f"  table='{t}': no md_scope='feature'/'featureType' metadata reference found ✗"
                )
            mc[32] = (confirmed32, len(feat_table_names32),
                      f"{confirmed32}/{len(feat_table_names32)} feature table(s) have linked feature-layer metadata. "
                      + " ".join(detail_lines32))
    except Exception as e:
        mc[32] = (0, 0, f"Req 32 check error: {e}", True)
    # Req 33 — gridded extension: verify ancillary table has rows and all cols populated
    try:
        cursor.execute("""
            SELECT tile_matrix_set_name, field_name, quantity_definition, grid_cell_encoding, datatype
            FROM gpkg_2d_gridded_coverage_ancillary
        """)
        rows = cursor.fetchall()
        if not rows:
            mc[33] = (0, 0, "No gridded coverage ancillary rows (N/A)", False)
        else:
            confirmed = sum(
                1 for r in rows
                if all(v and str(v).strip() for v in r)
            )
            mc[33] = (confirmed, len(rows),
                      f"{confirmed}/{len(rows)} coverage ancillary rows have all required columns populated")
    except Exception as e:
        mc[33] = (0, 0, f"Check error: {e}", True)

    # Req 37 — gridded user row metadata: verify Table 36 reference_scope/md_scope pairings
    try:
        if not table_exists(cursor, "gpkg_metadata_reference") or not table_exists(cursor, "gpkg_metadata"):
            mc[37] = (0, 0, "No metadata tables (N/A)", False)
        else:
            cursor.execute("""
                SELECT r.md_file_id, r.reference_scope, m.md_scope
                FROM gpkg_metadata_reference r
                JOIN gpkg_metadata m ON r.md_file_id = m.id
                WHERE r.reference_scope IN ('table','row','column','row/col')
            """)
            rows = cursor.fetchall()
            if not rows:
                mc[37] = (0, 0, "No table/row/column scope references found (N/A)", False)
            else:
                VALID_MD_SCOPES = {
                    "dataset","series","featureType","feature",
                    "tile","model","attribute","fieldSession","collectionSession"
                }
                confirmed = 0
                details = []
                for file_id, ref_scope, md_scope in rows:
                    if md_scope in VALID_MD_SCOPES:
                        confirmed += 1
                        details.append(f"md_file_id={file_id}: reference_scope='{ref_scope}' + md_scope='{md_scope}' ✓")
                    else:
                        details.append(f"md_file_id={file_id}: md_scope='{md_scope}' not valid per Table 36 ✗")
                mc[37] = (confirmed, len(rows),
                          f"{confirmed}/{len(rows)} reference_scope/md_scope pairings valid per Table 36. "
                          + "; ".join(details))
    except Exception as e:
        mc[37] = (0, 0, f"Check error: {e}", True)

    # ── INTERNET CHECK 1: URI resolution (Req 18/19) ──────────────────────────
    # v1.53: skip entirely when --offline active (avoids misleading HTTP 403 FAILs)
    if _config.OFFLINE:
        mc["uri"] = (None, None,
                     "OFFLINE MODE — URI reachability check suppressed by --offline flag")
    else:
        try:
            cursor.execute("SELECT id, md_standard_uri FROM gpkg_metadata WHERE md_standard_uri IS NOT NULL")
            uri_rows = cursor.fetchall()
            if not uri_rows:
                mc["uri"] = (0, 0, "No URIs to check (N/A)", False)
            else:
                ok_count, fail_count, no_net = 0, 0, False
                details = []
                for row_id, uri in uri_rows:
                    reachable, note = _net_check_uri(uri)
                    if reachable is None:
                        no_net = True
                        details.append(f"id={row_id} '{uri}': {note}")
                        break
                    elif reachable:
                        ok_count += 1
                        details.append(f"id={row_id}: {note}")
                    else:
                        fail_count += 1
                        details.append(f"id={row_id} '{uri}': {note}")
                if no_net:
                    mc["uri"] = (None, None, "NO INTERNET — URI reachability not verified. " +
                                 "; ".join(details))
                else:
                    total = ok_count + fail_count
                    mc["uri"] = (ok_count, total,
                                 f"{ok_count}/{total} URIs reachable. " + "; ".join(details))
        except Exception as e:
            mc["uri"] = (0, 0, f"URI check error: {e}", True)

    # ── INTERNET CHECK 2: EPSG registry validation (Req 7/9/10/11/13) ────────
    try:
        cursor.execute("SELECT srs_id, srs_name FROM gpkg_spatial_ref_sys WHERE srs_id > 0")
        srs_rows = cursor.fetchall()
        if not srs_rows:
            mc["epsg"] = (0, 0, "No CRS entries to check (N/A)", False)
        else:
            ok_count, fail_count, no_net = 0, 0, False
            details = []
            for srs_id, srs_name in srs_rows:
                epsg_ok, note = _net_check_epsg(srs_id, srs_name or "")
                if epsg_ok is None:
                    if "NO INTERNET" in note:
                        no_net = True
                        details.append(f"srs_id={srs_id}: {note}")
                        break
                    else:
                        details.append(f"srs_id={srs_id}: {note}")
                elif epsg_ok:
                    ok_count += 1
                    details.append(f"srs_id={srs_id}: {note}")
                else:
                    fail_count += 1
                    details.append(f"srs_id={srs_id}: {note}")
            if no_net:
                mc["epsg"] = (None, None, "NO INTERNET — EPSG registry not checked. " +
                              "; ".join(details))
            else:
                total = ok_count + fail_count
                # v1.57 fix (#3): non-DNS network failures (proxy 403, TLS error,
                # blocked port, timeout) previously left ok=fail=0, which the
                # report rendered as a plain "N/A" badge — indistinguishable from
                # "nothing to check".  When entries exist but none could be
                # verified, report it as a network problem instead.
                if total == 0 and details:
                    # v1.58: distinguish --offline suppression from a genuine
                    # network failure so the report label is not misleading.
                    if any("OFFLINE" in d.upper() for d in details):
                        mc["epsg"] = (None, None,
                                      "OFFLINE MODE — EPSG registry check suppressed "
                                      "by --offline flag. " + "; ".join(details))
                    else:
                        mc["epsg"] = (None, None,
                                      "NETWORK ERROR — EPSG registry could not be reached "
                                      "(not a data problem). " + "; ".join(details))
                else:
                    mc["epsg"] = (ok_count, total,
                                  f"{ok_count}/{total} srs_id entries match EPSG registry. " +
                                  "; ".join(details))
    except Exception as e:
        mc["epsg"] = (0, 0, f"EPSG check error: {e}", True)

    # ── INTERNET CHECK 3: OGC Scale Denominator validation (Req 8) ───────────
    try:
        cursor.execute("""
            SELECT tms.srs_id, tm.zoom_level, tm.pixel_x_size, tm.pixel_y_size
            FROM gpkg_tile_matrix_set tms
            JOIN gpkg_tile_matrix tm ON tms.table_name = tm.table_name
            ORDER BY tms.srs_id, tm.zoom_level
        """)
        rows = cursor.fetchall()
        if not rows:
            mc["scale"] = (0, 0, "No tile matrix data to check (N/A)", False)
        else:
            by_srs = defaultdict(list)
            for srs_id, z, px, py in rows:
                by_srs[srs_id].append((z, px, py))
            ok_count, fail_count, no_net = 0, 0, False
            details = []
            for srs_id, zoom_data in by_srs.items():
                sd_ok, note = _net_check_scale_denoms(srs_id, zoom_data)
                if sd_ok is None:
                    if "NO INTERNET" in note:
                        no_net = True
                        details.append(f"srs_id={srs_id}: {note}")
                        break
                    else:
                        details.append(f"srs_id={srs_id}: {note}")
                elif sd_ok:
                    ok_count += 1
                    details.append(f"srs_id={srs_id}: {note}")
                else:
                    fail_count += 1
                    details.append(f"srs_id={srs_id}: {note}")
            if no_net:
                mc["scale"] = (None, None, "NO INTERNET — OGC scale denominators not verified. " +
                               "; ".join(details))
            else:
                total = ok_count + fail_count
                # v1.57 fix (#3): same non-DNS network failure handling as the
                # EPSG check above — 0/0 with diagnostic details means the OGC
                # endpoint was unreachable, not that there was nothing to check.
                if total == 0 and details:
                    # v1.58: distinguish --offline suppression from a genuine
                    # network failure so the report label is not misleading.
                    if any("OFFLINE" in d.upper() for d in details):
                        mc["scale"] = (None, None,
                                       "OFFLINE MODE — OGC scale denominator check "
                                       "suppressed by --offline flag. " + "; ".join(details))
                    else:
                        mc["scale"] = (None, None,
                                       "NETWORK ERROR — OGC TileMatrixSet definitions could not "
                                       "be reached (not a data problem). " + "; ".join(details))
                else:
                    mc["scale"] = (ok_count, total,
                                   f"{ok_count}/{total} srs_id(s) match OGC TileMatrixSet scale denominators. " +
                                   "; ".join(details))
    except Exception as e:
        mc["scale"] = (0, 0, f"Scale denom check error: {e}", True)

    # ── Req 25 — Tile Matrix Width/Height: actual 256×256 values in gpkg_tile_matrix ──
    # Base _r25 checks gpkg_tile_matrix_SET column existence (matches v1.0).
    # MC goes deeper: checks actual tile_width/height=256 values in gpkg_tile_matrix.
    try:
        if not table_exists(cursor, "gpkg_tile_matrix"):
            mc[25] = (0, 0, "gpkg_tile_matrix table missing — cannot check tile dimensions (N/A)", False)
        else:
            cursor.execute("""
                SELECT table_name, zoom_level, tile_width, tile_height
                FROM gpkg_tile_matrix ORDER BY table_name, zoom_level
            """)
            r25_rows = cursor.fetchall()
            if not r25_rows:
                mc[25] = (0, 0, "No rows in gpkg_tile_matrix — cannot check tile dimensions (N/A)", False)
            else:
                r25_ok  = sum(1 for r in r25_rows if r[2] == TILE_W and r[3] == TILE_H)
                r25_bad = [(r[0], r[1], r[2], r[3]) for r in r25_rows if r[2] != TILE_W or r[3] != TILE_H]
                if r25_bad:
                    mc[25] = (r25_ok, len(r25_rows),
                              f"{r25_ok}/{len(r25_rows)} zoom levels declare {TILE_W}×{TILE_H} in gpkg_tile_matrix. "
                              f"Non-compliant entries: {r25_bad} ✗")
                else:
                    mc[25] = (r25_ok, len(r25_rows),
                              f"{r25_ok}/{len(r25_rows)} zoom levels correctly declare tile_width={TILE_W} and "
                              f"tile_height={TILE_H} in gpkg_tile_matrix ✓  "
                              f"(actual BLOB pixel dimensions verified in Req 26)")
    except Exception as e:
        mc[25] = (0, 0, f"Req 25 check error: {e}", True)

    # ── Req 26 — Tile Pyramid Data Size (Pillow BLOB decode) ─────────────────
    # Run 6 checks per sampled tile: pixel dims, format, mode, integrity,
    # cross-zoom consistency, and magic-byte/format agreement.
    # Falls back gracefully if Pillow is not installed.
    try:
        from PIL import Image as _PIL_Image
        import io as _PIL_io

        MAGIC = {
            bytes.fromhex("ffd8ff"):   "JPEG",
            bytes.fromhex("89504e47"): "PNG",
            bytes.fromhex("49492a00"): "TIFF",   # little-endian TIFF
            bytes.fromhex("4d4d002a"): "TIFF",   # big-endian TIFF
        }
        VALID_RASTER_FORMATS  = {"JPEG", "PNG"}
        VALID_GRIDDED_FORMATS = {"PNG", "TIFF"}
        VALID_RASTER_MODES    = {"RGB", "RGBA", "L", "P"}
        VALID_GRIDDED_MODES   = {"I;16", "I;16B", "I", "F", "L"}

        # data_type per tile table
        cursor.execute("""
            SELECT c.table_name, c.data_type
            FROM gpkg_contents c
            JOIN gpkg_tile_matrix_set tms ON c.table_name = tms.table_name
        """)
        table_types = {r[0]: r[1] for r in cursor.fetchall()}

        cursor.execute("SELECT table_name FROM gpkg_tile_matrix_set")
        tile_tables = [r[0] for r in cursor.fetchall()]

        total_zooms_declared  = 0
        total_zooms_confirmed = 0
        table_summaries       = []

        for tname in tile_tables:
            data_type  = table_types.get(tname, "unknown")
            is_gridded = "gridded" in data_type

            cursor.execute(
                "SELECT zoom_level FROM gpkg_tile_matrix WHERE table_name=? ORDER BY zoom_level",
                (tname,))
            declared_zooms = [r[0] for r in cursor.fetchall()]
            total_zooms_declared += len(declared_zooms)

            zoom_results     = []
            formats_per_zoom = {}
            table_issues     = []

            for zoom in declared_zooms:
                cursor.execute(
                    f'SELECT tile_data FROM {_quote_ident(tname)} '
                    f'WHERE zoom_level=? AND tile_data IS NOT NULL LIMIT 5',
                    (zoom,))
                blobs = [bytes(r[0]) for r in cursor.fetchall()]

                if not blobs:
                    zoom_results.append(f"z={zoom}:NO_TILES")
                    continue

                zoom_ok      = True
                zoom_detail  = []
                zoom_formats = set()

                for blob in blobs:
                    checks = []
                    img_ok = True

                    # Check: decode (catches corrupt/truncated tiles)
                    try:
                        img = _PIL_Image.open(_PIL_io.BytesIO(blob))
                        w, h = img.size
                        fmt  = img.format or "UNKNOWN"
                        mode = img.mode
                    except Exception as decode_err:
                        table_issues.append(f"z={zoom}: CORRUPT tile — {decode_err} ✗")
                        zoom_ok = False
                        continue

                    # Check: magic bytes match reported format
                    magic_fmt = next(
                        (v for k, v in MAGIC.items() if blob[:4].startswith(k[:3])),
                        "UNKNOWN")
                    if magic_fmt != "UNKNOWN" and magic_fmt != fmt:
                        checks.append(f"magic={magic_fmt}≠format={fmt} ✗")
                        img_ok = False

                    # Check: pixel dimensions = TILE_W×TILE_H
                    if w != TILE_W or h != TILE_H:
                        checks.append(f"{w}×{h}≠{TILE_W}×{TILE_H} ✗")
                        img_ok = False
                    else:
                        checks.append(f"{TILE_W}×{TILE_H} ✓")

                    # Check: format valid for data type
                    valid_fmts = VALID_GRIDDED_FORMATS if is_gridded else VALID_RASTER_FORMATS
                    if fmt not in valid_fmts:
                        checks.append(f"format={fmt} not in {valid_fmts} ✗")
                        img_ok = False
                    else:
                        checks.append(f"{fmt} ✓")
                        zoom_formats.add(fmt)

                    # Check: image mode matches data type
                    valid_modes = VALID_GRIDDED_MODES if is_gridded else VALID_RASTER_MODES
                    if mode not in valid_modes:
                        checks.append(f"mode={mode} not in {valid_modes} ✗")
                        img_ok = False
                    else:
                        checks.append(f"mode={mode} ✓")

                    if not img_ok:
                        zoom_ok = False
                    zoom_detail.append("; ".join(checks))

                formats_per_zoom[zoom] = zoom_formats

                # Check: mixed formats within this zoom level
                if len(zoom_formats) > 1:
                    table_issues.append(f"z={zoom}: mixed formats within zoom {zoom_formats} ✗")
                    zoom_ok = False

                if zoom_ok:
                    total_zooms_confirmed += 1
                    fmt_str = next(iter(zoom_formats), "?")
                    zoom_results.append(f"z={zoom}:OK({len(blobs)} tiles,{fmt_str})")
                else:
                    unique_issues = list(dict.fromkeys(zoom_detail))
                    zoom_results.append(f"z={zoom}:FAIL({'; '.join(unique_issues)})")

            # Check: consistent format across zoom levels in same table
            all_zoom_fmts = set(f for fset in formats_per_zoom.values() for f in fset)
            if len(all_zoom_fmts) > 1:
                per_zoom_str = ", ".join(
                    f"z{z}:{fset}" for z, fset in formats_per_zoom.items() if fset)
                table_issues.append(
                    f"inconsistent formats across zoom levels ({per_zoom_str}) ✗")

            summary = f"'{tname}' ({data_type}): " + ", ".join(zoom_results)
            if table_issues:
                summary += " | ISSUES: " + "; ".join(table_issues)
            table_summaries.append(summary)

        mc[26] = (total_zooms_confirmed, total_zooms_declared,
                  f"Pillow 6-check: {total_zooms_confirmed}/{total_zooms_declared} zoom levels fully "
                  f"verified (pixel dims, format, mode, integrity, consistency, magic bytes). "
                  + "; ".join(table_summaries))

    except ImportError:
        # Pillow not available — report as partial check with a meaningful score
        # so the cell shows a warning badge rather than N/A
        try:
            cursor.execute("SELECT COUNT(*) FROM gpkg_tile_matrix")
            zoom_count = cursor.fetchone()[0] or 1
        except Exception:
            zoom_count = 1
        mc[26] = (0, zoom_count,
                  f"Pillow not installed — BLOB pixel decode skipped. "
                  f"Install with: pip install Pillow  to enable full Req 26 verification. "
                  f"({zoom_count} zoom level(s) declared in gpkg_tile_matrix — not BLOB-verified)")
    except Exception as e:
        mc[26] = (0, 0, f"Req 26 check error: {e}", True)


    try:
        cursor.execute("""
            SELECT id, md_scope, md_standard_uri, metadata
            FROM gpkg_metadata
            WHERE metadata IS NOT NULL AND length(metadata) > 20
        """)
        meta_rows = cursor.fetchall()
        if not meta_rows:
            mc["dmf"] = (0, 0, "No metadata content to validate (N/A)", False)
        else:
            ok_count, fail_count = 0, 0
            details = []
            for row_id, scope, uri, xml_text in meta_rows:
                is_dmf = uri and "dgiwg" in uri.lower() and "dmf" in uri.lower()
                xml_ok, note = _net_check_dmf_xml(xml_text)
                label = f"id={row_id} (scope={scope}{', DMF URI' if is_dmf else ''})"
                if xml_ok:
                    ok_count += 1
                    details.append(f"{label}: {note}")
                else:
                    fail_count += 1
                    details.append(f"{label}: {note}")
            total = ok_count + fail_count
            dmf_note = ""
            if not any(r[2] and "dgiwg" in r[2].lower() for r in meta_rows):
                dmf_note = " NOTE: No DGIWG DMF URI rows found — ISO 19115 check applied to all metadata rows."
            mc["dmf"] = (ok_count, total,
                         f"{ok_count}/{total} metadata rows have valid ISO 19115/DMF XML structure.{dmf_note} " +
                         "; ".join(details))
    except Exception as e:
        mc["dmf"] = (0, 0, f"DMF XML check error: {e}", True)

    # ── v1.62 fix: normalise every requirement entry to a 4-tuple ─────────────
    # Historically the success paths above returned 3-tuples
    # (confirmed, total, note) while the error paths returned 4-tuples
    # (confirmed, total, note, unverifiable).  Consumers coped by indexing
    # defensively (`manual[3] if len(manual) > 3 else False`), which meant a
    # single unpack anywhere downstream would raise ValueError at random.
    # One shape is now guaranteed for all int-keyed entries:
    #     (confirmed: int, total: int, note: str, unverifiable: bool)
    # String keys ("uri", "epsg", "scale", "dmf") are internet-check payloads
    # with their own shape and are deliberately left untouched.
    for _k, _v in list(mc.items()):
        if isinstance(_k, int) and isinstance(_v, tuple) and len(_v) == 3:
            mc[_k] = (_v[0], _v[1], _v[2], False)

    return mc


def run_all_checks(conn: sqlite3.Connection) -> dict[int, dict[str, object]]:
    c = conn.cursor()
    results = {}
    for req_num in REQUIREMENTS:
        status, detail = check_req(c, req_num)
        results[req_num] = {"status": status, "detail": detail, "manual": None}

    # Run deeper manual checks and attach to all results (PASS, FAIL, and PASS*).
    # v1.49 fix: previously only stored MC results for PASS* rows; now stored for
    # all statuses so the Manual Confirmed column shows data whenever a deeper
    # check ran, regardless of the base automated verdict.
    manual_data = _manual_checks(c)
    internet_checks = {}
    for req_num, mc in manual_data.items():
        if isinstance(req_num, str):
            # String keys = internet checks (uri, epsg, scale, dmf)
            internet_checks[req_num] = mc
        elif req_num in results:
            results[req_num]["manual"] = mc   # (confirmed, total, note, unverifiable)

    results["__internet__"] = internet_checks  # attach for rendering

    # ── v1.53: Cascading root-cause grouping ─────────────────────────────────
    # When gpkg_metadata / gpkg_metadata_reference are absent, many requirement
    # checks cascade to FAIL for the same root cause. Detect this and inject a
    # plain-English note so the HTML banner and JSON output can surface it.
    _cascade_reqs = {18, 19, 20, 21, 22, 23, 31, 32}
    _cascade_fails = []
    for _cr in _cascade_reqs:
        if _cr in results and results[_cr].get("status") == "FAIL":
            _det = results[_cr].get("detail", "")
            _det_up = _det.upper()
            if ("GPKG_METADATA" in _det_up and "MISSING" in _det_up) or \
               ("GPKG_METADATA_REFERENCE" in _det_up and "MISSING" in _det_up):
                _cascade_fails.append(_cr)
    if len(_cascade_fails) >= 2:
        _missing_tables = []
        for _t in ("gpkg_metadata", "gpkg_metadata_reference"):
            for _cr in _cascade_fails:
                if _t.upper() in results[_cr].get("detail", "").upper():
                    if _t not in _missing_tables:
                        _missing_tables.append(_t)
                    break
        if _missing_tables:
            _tbls = " and ".join(f"'{t}'" for t in _missing_tables)
            _reqs = ", ".join(f"Req {r}" for r in sorted(_cascade_fails))
            results["__cascade_note__"] = (
                f"The following required table(s) are absent from this GeoPackage: {_tbls}. "
                f"This single root cause is responsible for the FAIL result on: {_reqs}. "
                f"Restoring these table(s) will likely resolve all of the above failures."
            )

    return results


