# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Utility helpers for the DGIWG validator (v1.58).

Library probing, SQLite/GeoPackage helpers, file profile collection,
result scoring, and the interactive file-picker dialog.
"""
import os
import sys
import re
import sqlite3
import subprocess
import tempfile
import datetime
import math
import urllib.request
import urllib.error
from pathlib import Path
from collections import defaultdict
from xml.etree import ElementTree as ET
from .constants import NET_TIMEOUT, STATUS_ICON, TILE_SIZE, TILE_W, TILE_H
LIBRARY_STATUS: dict = {}

def _try_import(pkg_name: str) -> bool:
    """Return True if the package can be imported successfully.

    Handles special cases where the pip package name differs from the
    import name (e.g. Pillow is installed as 'Pillow' but imported as 'PIL').

    Catches ImportError AND OSError/Exception broadly — some packages on Windows
    raise OSError at import time when required system DLLs are absent.
    """
    import importlib
    # Explicit import-name overrides (pip name → actual import name)
    _IMPORT_NAME_MAP = {
        "pillow": "PIL",
        "PIL":    "PIL",
        "scikit-learn": "sklearn",
    }
    actual = _IMPORT_NAME_MAP.get(pkg_name, _IMPORT_NAME_MAP.get(
        pkg_name.lower(), pkg_name.replace("-", "_")
    ))
    try:
        importlib.import_module(actual)
        return True
    except ImportError:
        return False
    except Exception:
        # Catches OSError (missing system DLLs e.g. weasyprint/GTK on Windows),
        # AttributeError, and any other failure that can occur at import time.
        return False


def _pip_install(pkg_name: str) -> tuple:
    """
    Attempt to install pkg_name via pip.
    Returns (success: bool, output: str).

    Platform behaviour:
      - Linux/Mac: passes --break-system-packages (needed on Debian/Ubuntu
        where the system Python is managed by apt).
      - Windows: omits --break-system-packages (flag is unrecognised and
        causes pip to exit with an error on Windows Python installs).

    Already-installed packages: pip returns exit code 0 with
    "Requirement already satisfied" — treated as success.
    """
    is_windows = sys.platform.startswith("win")

    base_cmd = [pkg_name]
    flags = [] if is_windows else ["--break-system-packages"]

    pip_cmds = [
        [sys.executable, "-m", "pip", "install"] + base_cmd + flags,
        (["pip3", "install"] + base_cmd + flags) if not is_windows else None,
        (["pip",  "install"] + base_cmd + flags) if not is_windows else None,
    ]
    pip_cmds = [c for c in pip_cmds if c]  # drop None entries

    last_out = ""
    for cmd in pip_cmds:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=120
            )
            last_out = (result.stdout + result.stderr).strip()
            if result.returncode == 0:
                return True, last_out
            # On Windows, pip may return non-zero for --break-system-packages
            # even though install succeeded — check output for success signal
            if "Successfully installed" in last_out or \
               "already satisfied" in last_out.lower():
                return True, last_out
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            last_out = str(e)
            continue
    return False, last_out

def _check_and_offer_install(import_name: str, pip_name: str, description: str,
                              interactive_mode: bool = False) -> bool:
    """
    Check whether import_name is importable. If not, prompt the user to
    install pip_name. Return True if the library is available (either already
    installed or successfully installed after the prompt).

    Behaviour:
      - If already installed → return True immediately, no prompt.
      - CLI mode (interactive_mode=False): print a Y/N prompt to stdout.
      - Interactive mode (interactive_mode=True): show a tkinter messagebox.
      - If user declines OR install fails → return False (fallback will be used).
    """
    if _try_import(import_name):
        return True  # already available

    pkg_label = f"{pip_name} ({description})"

    # ── CLI prompt ────────────────────────────────────────────────────────────
    if not interactive_mode:
        print()
        print(f"  ┌─ Optional library missing ─────────────────────────────┐")
        print(f"  │  {pkg_label:<54} │")
        print(f"  │  This library improves validation accuracy.            │")
        print(f"  │  Install it now? (Y to install / N to skip)            │")
        print(f"  └────────────────────────────────────────────────────────┘")
        try:
            answer = input("  Install now? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in ("y", "yes", ""):
            print(f"  Skipped. {pip_name} checks will use structural fallback.\n")
            return False
        print(f"  Installing {pip_name} …")
        ok, out = _pip_install(pip_name)
        if ok:
            print(f"  ✅ {pip_name} installed successfully.")
            # Clear any cached ImportError so Python re-scans sys.path.
            # Use the actual import name (not lowercased) — PIL ≠ pil.
            for mod_key in list(sys.modules.keys()):
                if mod_key == import_name or mod_key.startswith(import_name + "."):
                    del sys.modules[mod_key]
            if _try_import(import_name):
                print(f"  ✅ {import_name} imported OK — full checks enabled.\n")
                return True
            else:
                print(f"  ⚠  pip reported success but import still failed.")
                print(f"     You may need to restart the script.")
                print(f"     Falling back to structural check for {pip_name}.\n")
                return False
        else:
            print(f"  ❌ Install failed. Output:")
            for line in out.splitlines()[-6:]:
                print(f"     {line}")
            print(f"  Falling back to structural check for {pip_name}.\n")
            return False

    # ── Tkinter / interactive prompt ──────────────────────────────────────────
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        # No tkinter — fall through to a non-interactive skip
        return False

    root = tk.Tk()
    root.withdraw()
    msg = (
        f"Optional library missing: {pkg_label}\n\n"
        f"This library improves validation accuracy.\n\n"
        f"Install it now using pip?\n"
        f"(Clicking 'No' will use the structural fallback for this check.)"
    )
    answer = messagebox.askyesno("Install Optional Library?", msg)
    root.destroy()

    if not answer:
        return False

    # Show progress window
    prog_root = tk.Tk()
    prog_root.title(f"Installing {pip_name}…")
    prog_root.geometry("420x120")
    prog_root.resizable(False, False)
    tk.Label(prog_root, text=f"Installing {pkg_label}…",
             font=("Arial", 11), wraplength=390, pady=20).pack()
    status_var = tk.StringVar(value="Please wait…")
    tk.Label(prog_root, textvariable=status_var, font=("Arial", 9),
             fg="#555").pack()
    prog_root.update()

    ok, out = _pip_install(pip_name)
    prog_root.destroy()

    if ok and _try_import(import_name):
        try:
            import tkinter as _tk2
            from tkinter import messagebox as _mb2
            r2 = _tk2.Tk(); r2.withdraw()
            _mb2.showinfo("Install Successful",
                          f"✅ {pip_name} installed and imported successfully.\n"
                          f"Full checks for this requirement are now enabled.")
            r2.destroy()
        except Exception:
            pass
        return True
    else:
        try:
            import tkinter as _tk2
            from tkinter import messagebox as _mb2
            r2 = _tk2.Tk(); r2.withdraw()
            is_windows = sys.platform.startswith("win")
            manual_cmd = (f"  pip install {pip_name}" if is_windows
                          else f"  pip install {pip_name} --break-system-packages")
            _mb2.showwarning("Install Failed",
                             f"❌ Could not install {pip_name}.\n\n"
                             f"The structural fallback check will be used instead.\n\n"
                             f"To install manually:\n{manual_cmd}")
            r2.destroy()
        except Exception:
            pass
        return False


def _probe_optional_libraries(
    interactive_mode: bool = False,
    skip_install: bool = False,
) -> None:
    """
    Called once at startup. Checks pyproj, shapely, and Pillow.
    Populates LIBRARY_STATUS with the result for each.

    Args:
        interactive_mode: True in GUI/Tkinter flow (uses dialog boxes);
                          False in CLI flow (prints Y/N prompts to stdout).
        skip_install:     When True (--no-install flag), suppress all install
                          prompts. Libraries already present are still used;
                          missing ones silently become PASS* fallbacks.
    """
    libs = [
        ("pyproj",     "pyproj",      "Req 13 — datum name EPSG cross-check (offline)"),
        ("shapely",    "shapely",     "Req 24 — OGC geometry validity (WKB decode)"),
        ("PIL",        "Pillow",      "Req 26 — tile BLOB pixel dimension decode"),
    ]
    any_missing = any(not _try_import(imp) for imp, _, _ in libs)

    if any_missing:
        if not interactive_mode:
            print()
            print("  ─── Optional library check ───────────────────────────────")
        if skip_install and any_missing:
            print("  [--no-install] Install prompts suppressed.")

    for import_name, pip_name, desc in libs:
        if _try_import(import_name):
            LIBRARY_STATUS[pip_name] = True
            if not interactive_mode and any_missing:
                print(f"  ✅ {pip_name:<10} already installed")
        else:
            if skip_install:
                LIBRARY_STATUS[pip_name] = False
                if not interactive_mode:
                    print(f"  ⚠  {pip_name:<10} not available — structural fallback will be used")
            else:
                result = _check_and_offer_install(
                    import_name, pip_name, desc, interactive_mode=interactive_mode
                )
                LIBRARY_STATUS[pip_name] = result
                if not interactive_mode and not result:
                    print(f"  ⚠  {pip_name:<10} not available — structural fallback will be used")

    if any_missing and not interactive_mode:
        print("  ──────────────────────────────────────────────────────────")
        print()


# ──────────────────────────────────────────────────────────────────────────────
# INTERNET CHECK HELPERS
# ──────────────────────────────────────────────────────────────────────────────

# Default network timeout in seconds for all HTTP checks (Req 7, 20, 21, 35–37).
# Override at runtime via --timeout N on the command line.
# Set lower on slow networks; increase if EPSG lookups time out.
def open_gpkg(path: str) -> sqlite3.Connection:
    """Open a GeoPackage as a SQLite connection.

    Raises:
        ValueError  — if the file is not a valid SQLite database, is
                      encrypted/locked, or fails SQLite's own integrity check.
    """
    try:
        # Open read-only via URI to prevent any accidental writes and avoid
        # SQLite creating a WAL journal file alongside the GeoPackage.
        uri = "file:{}?mode=ro".format(
            urllib.request.pathname2url(os.path.abspath(path))
        )
        conn = sqlite3.connect(uri, uri=True)
        conn.text_factory = lambda b: b.decode("utf-8", errors="replace") \
            if isinstance(b, (bytes, bytearray)) else b
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"Cannot open '{os.path.basename(path)}' as SQLite: {exc}") from exc

    # Quick structural sanity check — catches truncated / encrypted / non-SQLite files
    # before any requirement check tries to query tables.
    try:
        row = conn.execute("PRAGMA integrity_check(1)").fetchone()
        if row is None or row[0] != "ok":
            conn.close()
            raise ValueError(
                f"SQLite integrity_check failed for '{os.path.basename(path)}': "
                f"{row[0] if row else 'no result'}"
            )
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise ValueError(
            f"'{os.path.basename(path)}' is not a valid SQLite/GeoPackage file: {exc}"
        ) from exc

    return conn


def table_exists(cursor, name):
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cursor.fetchone() is not None


def column_exists(cursor, table, col):
    try:
        cursor.execute(f'PRAGMA table_info("{table}")')
        return any(r[1] == col for r in cursor.fetchall())
    except Exception:
        return False


def _quote_ident(name: str) -> str:
    """
    Return a safely double-quoted SQLite identifier.

    SQLite allows any characters in identifiers when double-quoted.
    The only character that needs escaping inside double-quoted identifiers
    is the double-quote itself, which is escaped by doubling it ("").

    This replaces the old _sql_safe() regex guard (which only allowed
    ASCII letters, digits, and underscores) with a proper quoting strategy
    that handles spaces, hyphens, Korean/Unicode characters, and other
    valid-but-unusual table/column names that GeoPackage producers may use.

    Usage:
        qi = _quote_ident(tname)
        cursor.execute(f"SELECT 1 FROM {qi}")
    """
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def get_data_categories(cursor):
    """Return set of: 'features', 'tiles', 'gridded' present in the file.

    Queries ``gpkg_contents.data_type`` and buckets distinct values into the
    three DGIWG-relevant categories.  If ``gpkg_contents`` is missing or the
    database is locked/corrupt, a ``sqlite3.Error`` is caught and a warning
    is printed — callers receive an empty set but at least have visibility
    that category detection failed rather than silently assuming the file
    contains no data.  Non-sqlite errors intentionally propagate so real
    bugs surface during development.
    """
    cats = set()
    try:
        cursor.execute("SELECT DISTINCT data_type FROM gpkg_contents")
        for (dt,) in cursor.fetchall():
            dt = (dt or "").lower()
            if "gridded" in dt or "coverage" in dt:
                cats.add("gridded")
            elif dt == "features":
                cats.add("features")
            elif dt == "tiles":
                cats.add("tiles")
    except sqlite3.Error as _cat_err:
        # v1.52: narrowed from bare Exception — surface DB-level failures so
        # downstream requirement checks do not proceed on a misleading empty set.
        print(f"  [warn] get_data_categories: {_cat_err} — returning empty category set")
    return cats


# ──────────────────────────────────────────────────────────────────────────────
# STANDALONE HELPER FUNCTIONS (called by individual requirement checks)
# ──────────────────────────────────────────────────────────────────────────────

def _check_xml_xsd(xml_text, xsd_schema):
    """Validate XML text against a pre-compiled ``lxml.etree.XMLSchema``.

    This is where the script feeds the metadata BLOB into the ``lxml`` schema
    validator.  It encapsulates the XSD validation path used by Req 18 so that
    the logic is testable in isolation and the call site in ``_r18()`` remains
    concise.

    Parameters
    ----------
    xml_text : str
        Raw XML string — the ``metadata`` field from ``gpkg_metadata``.
    xsd_schema : lxml.etree.XMLSchema or None
        A compiled schema object returned by ``lxml.etree.XMLSchema()``.
        When *None* (lxml not installed or XSD compilation failed) the
        function returns gracefully with ``(True, "XSD validation skipped …")``.

    Returns
    -------
    tuple[bool, str]
        ``(is_valid, message)`` where *message* summarises the outcome.
        On XSD failure the first five error lines are concatenated into
        *message*.  ``is_valid`` is always ``True`` when the check is
        skipped so that callers can safely append *message* to their
        ``ok`` list rather than their ``issues`` list.
    """
    if xsd_schema is None:
        return (True, "XSD validation skipped — no schema provided")
    try:
        from lxml import etree as _lxml_etree
        _lxml_root = _lxml_etree.fromstring(xml_text.strip().encode("utf-8"))
        valid = xsd_schema.validate(_lxml_root)
        if valid:
            return (True, "XSD structural validation ✓")
        msgs = [f"line {e.line}: {e.message}" for e in xsd_schema.error_log]
        return (False, "XSD structural validation FAILED — " + "; ".join(msgs[:5]))
    except Exception as exc:
        return (True, f"XSD validation skipped: {exc}")


def _decode_gpkg_geom_header(blob):
    """Decode the GeoPackage binary geometry header from a geometry BLOB.

    This is the new bitwise logic that reads the 4th byte of the geometry BLOB
    to check for Z and M consistency.  It implements the header layout defined
    in OGC 12-128r15 §2.1.4 and is called by ``_r24()`` for every sampled
    geometry BLOB.

    Header layout::

        bytes 0–1  : magic  (``GP``)
        byte  2    : version
        byte  3    : flags
        bytes 4–7  : srs_id  (int32, little-endian)
        bytes 8–N  : optional envelope  (0 / 32 / 48 / 64 bytes)

    Flags byte bit layout (byte 3)::

        bits 1–3  (mask 0x0E) : envelope indicator
                                  0 = no envelope
                                  1 = XY   (32 bytes)
                                  2 = XYZ  (48 bytes)
                                  3 = XYM  (48 bytes)
                                  4 = XYZM (64 bytes)
        bit  1    (mask 0x02) : Z-flag — 1 = geometry carries Z values
        bit  2    (mask 0x04) : M-flag — 1 = geometry carries M values

    Parameters
    ----------
    blob : bytes-like
        Raw geometry BLOB as returned by SQLite.

    Returns
    -------
    dict or None
        On success, a dict with keys:

        * ``flags``          – raw flags byte (int)
        * ``envelope_code``  – envelope indicator value (0–4)
        * ``header_size``    – total header length in bytes
        * ``has_z``          – True when the Z-flag is set
        * ``has_m``          – True when the M-flag is set
        * ``wkb_data``       – bytes slice beginning at the WKB payload

        Returns *None* when the blob contains fewer than 8 bytes and
        therefore cannot hold a valid GeoPackage geometry header.
    """
    raw = bytes(blob)
    if len(raw) < 8:
        return None
    flags         = raw[3]
    envelope_code = (flags >> 1) & 0x07
    envelope_size = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(envelope_code, 32)
    header_size   = 8 + envelope_size
    return {
        "flags":         flags,
        "envelope_code": envelope_code,
        "header_size":   header_size,
        "has_z":         bool(flags & 0x02),
        "has_m":         bool(flags & 0x04),
        "wkb_data":      raw[header_size:],
    }


def _parse_wkt_structural(wkt, srs_id, pyproj_crs_class):
    """Parse a WKT2 CRS string and cross-check its structure against EPSG via pyproj.

    This uses ``pyproj`` to ensure the internal math of the CRS matches the
    DGIWG-mandated EPSG codes.  It performs three structural checks:

    1. **CRS type consistency** — ``type_name`` of the parsed WKT CRS must
       match the ``type_name`` of the EPSG CRS loaded for *srs_id*
       (e.g., "Geographic 2D CRS", "Projected CRS").
    2. **Axis count** — axis count of the WKT CRS must equal that of the
       EPSG reference CRS (catches 2-D WKT being registered as a 3-D code).
    3. **AUTHORITY/ID binding** — the authority code embedded in the WKT
       must equal *srs_id* (catches copy-paste errors in the definition).

    Parameters
    ----------
    wkt : str
        WKT2 CRS definition string from ``gpkg_spatial_ref_sys``.
    srs_id : int
        EPSG code declared in ``gpkg_spatial_ref_sys.srs_id``.
    pyproj_crs_class
        The ``pyproj.CRS`` class passed in by the caller.  Accepting the
        class as a parameter keeps this function importable and testable
        without requiring pyproj to be installed at module level.

    Returns
    -------
    tuple[list, list, object]
        ``(issues, warnings, epsg_crs)`` where:

        * *issues*   – hard failures (should propagate to FAIL);
        * *warnings* – informational notes (propagate to PASS*);
        * *epsg_crs* – the ``pyproj.CRS`` object loaded from *srs_id*, or
          ``None`` when ``from_wkt()`` raised an exception before
          ``from_epsg()`` could be called.  The caller uses *epsg_crs*
          for the subsequent datum name cross-check; when it is ``None``
          the caller must call ``pyproj_crs_class.from_epsg(srs_id)``
          directly.
    """
    issues     = []
    warnings   = []
    epsg_crs   = None
    math_equiv = None   # True / False / None (None = check could not run)
    try:
        wkt_parsed_crs = pyproj_crs_class.from_wkt(wkt)
        epsg_crs       = pyproj_crs_class.from_epsg(srs_id)

        # Check 1: CRS type consistency
        wkt_type  = wkt_parsed_crs.type_name.lower()
        epsg_type = epsg_crs.type_name.lower()
        if wkt_type != epsg_type:
            issues.append(
                f"WKT CRS type '{wkt_type}' does not match EPSG:{srs_id} "
                f"expected type '{epsg_type}' — WKT may encode a different CRS"
            )
        else:
            warnings.append(f"WKT CRS type='{wkt_type}' matches EPSG:{srs_id} ✓")

        # Check 2: Axis count consistency
        wkt_axes  = wkt_parsed_crs.axis_info
        epsg_axes = epsg_crs.axis_info
        if len(wkt_axes) != len(epsg_axes):
            issues.append(
                f"WKT axis count ({len(wkt_axes)}) ≠ EPSG:{srs_id} "
                f"expected ({len(epsg_axes)}) — dimension mismatch"
            )

        # Check 3: AUTHORITY/ID code binding
        try:
            auth_list = wkt_parsed_crs.to_authority()
            if auth_list:
                auth_name, auth_code = auth_list
                if str(auth_code) != str(srs_id):
                    issues.append(
                        f"WKT AUTHORITY/ID code {auth_code} ≠ declared srs_id={srs_id}"
                    )
                else:
                    warnings.append(
                        f"WKT AUTHORITY/ID={auth_name}:{auth_code} matches srs_id ✓"
                    )
        except Exception:
            warnings.append("WKT carries no AUTHORITY/ID — cannot verify code binding")

        # ── Check 4 (v1.55): Mathematical / logical equivalence ───────────────
        # Compares actual CRS parameters (datum ellipsoid, prime meridian,
        # projection math) instead of names or string formatting.
        # "WGS 84", "WGS_1984", "World Geodetic System 1984" all pass here if
        # the semi-major axis and inverse flattening match EPSG:{srs_id}.
        try:
            if wkt_parsed_crs.equals(epsg_crs):
                math_equiv = True
                warnings.append(
                    f"WKT CRS is mathematically equivalent to EPSG:{srs_id} ✓ "
                    f"(name/format variations are acceptable)"
                )
            elif wkt_parsed_crs.equals(epsg_crs, ignore_axis_order=True):
                # Parameters match but axis order is wrong — already caught by
                # Check 1/axis-order rule; record equiv=True so datum name
                # variations are not double-penalised.
                math_equiv = True
                issues.append(
                    f"WKT CRS parameters match EPSG:{srs_id} but axis order "
                    f"differs — DGIWG Tables 15/16 require Latitude (NORTH) first"
                )
            else:
                math_equiv = False
                issues.append(
                    f"WKT CRS is NOT mathematically equivalent to EPSG:{srs_id} "
                    f"— datum, ellipsoid, or projection parameters mismatch"
                )
        except Exception as _eq_err:
            math_equiv = None
            warnings.append(
                f"CRS mathematical equivalence check could not be completed: {_eq_err}"
            )

    except Exception as _wkt_parse_err:
        issues.append(
            f"pyproj.CRS.from_wkt() failed — WKT may be malformed or WKT1: "
            f"{_wkt_parse_err}"
        )

    return issues, warnings, epsg_crs, math_equiv


# ──────────────────────────────────────────────────────────────────────────────
# INDIVIDUAL REQUIREMENT CHECKS
# ──────────────────────────────────────────────────────────────────────────────

# v1.58 fix: dead duplicate of checks.check_req() removed.  It referenced
# _CHECK_DISPATCH, which is defined only in checks.py — calling this copy
# raised NameError (masked as a FAIL result).  The live implementation is
# dgiwg_validator.checks.check_req().


def collect_file_profile(conn: sqlite3.Connection, gpkg_path: str) -> dict[str, str]:
    c = conn.cursor()
    profile = {}
    profile["filename"] = os.path.basename(gpkg_path)
    profile["filesize"] = f"{os.path.getsize(gpkg_path) / 1_048_576:.1f} MB"
    profile["generated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Data types
    try:
        c.execute("SELECT DISTINCT data_type FROM gpkg_contents")
        profile["data_types"] = ", ".join(r[0] for r in c.fetchall()) or "—"
    except Exception:
        profile["data_types"] = "Unknown"

    # Table names
    try:
        c.execute("SELECT table_name FROM gpkg_contents")
        profile["table_names"] = ", ".join(r[0] for r in c.fetchall()) or "—"
    except Exception:
        profile["table_names"] = "Unknown"

    # CRS
    try:
        c.execute("SELECT srs_id, srs_name, organization FROM gpkg_tile_matrix_set tms JOIN gpkg_spatial_ref_sys srs ON tms.srs_id=srs.srs_id LIMIT 1")
        row = c.fetchone()
        if row:
            profile["crs"] = f"EPSG:{row[0]} — {row[1]}"
        else:
            profile["crs"] = "—"
    except Exception:
        profile["crs"] = "—"

    # Zoom levels
    try:
        c.execute("SELECT MIN(zoom_level), MAX(zoom_level), COUNT(*) FROM gpkg_tile_matrix")
        row = c.fetchone()
        if row and row[0] is not None:
            profile["zoom_levels"] = f"{row[0]}–{row[1]} ({row[2]} levels)"
        else:
            profile["zoom_levels"] = "—"
    except Exception:
        profile["zoom_levels"] = "—"

    # Tile count
    try:
        c.execute("SELECT table_name FROM gpkg_contents WHERE data_type LIKE '%gridded%' OR data_type='tiles' LIMIT 1")
        row = c.fetchone()
        if row:
            c.execute(f'SELECT COUNT(*) FROM {_quote_ident(row[0])}')
            profile["tile_count"] = str(c.fetchone()[0])
        else:
            profile["tile_count"] = "—"
    except Exception:
        profile["tile_count"] = "—"

    # Tile size
    try:
        c.execute("SELECT tile_width, tile_height FROM gpkg_tile_matrix LIMIT 1")
        row = c.fetchone()
        profile["tile_size"] = f"{row[0]}×{row[1]}" if row else "—"
    except Exception:
        profile["tile_size"] = "—"

    # Zoom factor
    try:
        c.execute("SELECT zoom_level, pixel_x_size FROM gpkg_tile_matrix ORDER BY zoom_level LIMIT 2")
        rows = c.fetchall()
        if len(rows) == 2 and rows[1][1]:
            factor = rows[0][1] / rows[1][1]
            profile["zoom_factor"] = f"{factor:.2f}"
        else:
            profile["zoom_factor"] = "—"
    except Exception:
        profile["zoom_factor"] = "—"

    # Extensions
    try:
        c.execute("SELECT DISTINCT extension_name FROM gpkg_extensions")
        profile["extensions"] = ", ".join(r[0] for r in c.fetchall()) or "None"
    except Exception:
        profile["extensions"] = "—"

    # Metadata URI
    try:
        c.execute("SELECT md_standard_uri FROM gpkg_metadata LIMIT 1")
        row = c.fetchone()
        profile["metadata_uri"] = row[0] if row else "—"
    except Exception:
        profile["metadata_uri"] = "—"

    # Gridded field info
    try:
        c.execute("SELECT field_name, quantity_definition, grid_cell_encoding FROM gpkg_2d_gridded_coverage_ancillary LIMIT 1")
        row = c.fetchone()
        if row:
            profile["gridded_field"] = row[0] or "—"
            profile["quantity_definition"] = row[1] or "—"
            profile["grid_cell_encoding"] = row[2] or "—"
        else:
            profile["gridded_field"] = "—"
            profile["quantity_definition"] = "—"
            profile["grid_cell_encoding"] = "—"
    except Exception:
        profile["gridded_field"] = "—"
        profile["quantity_definition"] = "—"
        profile["grid_cell_encoding"] = "—"

    return profile


# ──────────────────────────────────────────────────────────────────────────────
# FORENSIC SOURCE SOFTWARE DETECTION
# Identifies the likely authoring tool (QGIS/GDAL, ArcGIS, or UNKNOWN) by
# inspecting structural fingerprints in the GeoPackage schema.
# Returns a dict:
#   {
#     "software":  "QGIS/GDAL" | "ArcGIS" | "UNKNOWN",
#     "confidence": "High" | "Medium" | "Low",
#     "signals":   [list of detected evidence strings],
#     "hints":     {req_num: hint_string, ...}   # audit hints per requirement
#   }
# ──────────────────────────────────────────────────────────────────────────────

def score_results(
    results: dict[int, dict[str, object]],
) -> tuple[dict[str, int], int, str, str]:
    counts = {"PASS": 0, "FAIL": 0, "PASS*": 0, "SKIPPED": 0, "N/A": 0, "WARNING": 0}
    for k, v in results.items():
        if k in ("__internet__", "__forensic__", "__forensic_checks__", "__cascade_note__"):
            continue
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    # v1.50 fix: derive total from counts, not len(results).
    # len(results) includes 3 extra string keys (__internet__, __forensic__,
    # __forensic_checks__) excluded from counts but counted in len() = 40 not 37.
    total = sum(counts.values())
    fail = counts["FAIL"]
    warn = counts["PASS*"]
    passed = counts["PASS"]
    if fail == 0 and warn == 0:
        verdict = "CONFORMANT"
        verdict_color = "#27ae60"
    elif fail == 0:
        verdict = "LIKELY CONFORMANT (partial checks)"
        verdict_color = "#f39c12"
    else:
        verdict = "NON-CONFORMANT"
        verdict_color = "#e74c3c"
    return counts, total, verdict, verdict_color


# ──────────────────────────────────────────────────────────────────────────────
# HTML REPORT
# ──────────────────────────────────────────────────────────────────────────────

def pick_files_dialog() -> list[str]:
    """
    Show a small tkinter launcher window with two buttons:
      • Select Files   — standard multi-file picker (Ctrl/Shift+click)
      • Select Folder  — folder picker that finds all .gpkg files inside

    Returns a sorted list of .gpkg paths, or [] if the user cancels.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError:
        print("  ⚠  tkinter is not available on this system.")
        print("     Install it or pass a file/folder path as a command-line argument:")
        print("     python DGIWG_Report_Generator.py your_file.gpkg")
        print("     python DGIWG_Report_Generator.py C:\\data\\gpkg_folder\\")
        return []

    selected_paths = []   # filled by the button callbacks

    root = tk.Tk()
    root.title("DGIWG Report Generator")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    # ── Header ────────────────────────────────────────────────────────────────────────────
    header = tk.Frame(root, bg="#2c3e50", pady=14, padx=20)
    header.pack(fill="x")
    tk.Label(header, text="🛡  DGIWG GeoPackage Compliance Report Generator",
             bg="#2c3e50", fg="white",
             font=("Arial", 13, "bold")).pack(anchor="w")
    tk.Label(header, text="STD-DP-19-005 v1.1  —  Select files or a folder to validate",
             bg="#2c3e50", fg="#aab7c4",
             font=("Arial", 9)).pack(anchor="w", pady=(2, 0))

    # ── Body ──────────────────────────────────────────────────────────────────────────────
    body = tk.Frame(root, bg="#f0f2f5", padx=24, pady=20)
    body.pack(fill="both", expand=True)

    tk.Label(body, text="How do you want to select your GeoPackage(s)?",
             bg="#f0f2f5", font=("Arial", 10)).pack(anchor="w", pady=(0, 12))

    btn_frame = tk.Frame(body, bg="#f0f2f5")
    btn_frame.pack(fill="x")

    def choose_files():
        paths = filedialog.askopenfilenames(
            parent=root,
            title="Select one or more GeoPackage files",
            filetypes=[("GeoPackage files", "*.gpkg"), ("All files", "*.*")],
        )
        if paths:
            selected_paths.extend(paths)
            root.quit()

    def choose_folder():
        folder = filedialog.askdirectory(
            parent=root,
            title="Select folder containing GeoPackage files",
            mustexist=True,
        )
        if folder:
            # v1.50 fix: exclude double-extension .gpkg.gpkg files (Bug #1)
            found = sorted(
                p for p in Path(folder).glob("*.gpkg")
                if not p.name.endswith(".gpkg.gpkg")
            )
            if not found:
                messagebox.showwarning(
                    "No GeoPackages found",
                    f"No .gpkg files were found in:\n{folder}",
                    parent=root,
                )
                return
            selected_paths.extend(str(p) for p in found)
            root.quit()

    # File button
    f_btn = tk.Button(
        btn_frame,
        text="📄  Select Files",
        command=choose_files,
        bg="#3498db", fg="white", activebackground="#2980b9", activeforeground="white",
        font=("Arial", 10, "bold"), relief="flat",
        padx=18, pady=10, cursor="hand2",
    )
    f_btn.pack(side="left", padx=(0, 12))

    tk.Label(btn_frame,
             text="Pick individual files.\nCtrl+click or Shift+click\nfor multiple.",
             bg="#f0f2f5", fg="#555", font=("Arial", 8),
             justify="left").pack(side="left", padx=(0, 30))

    # Folder button
    d_btn = tk.Button(
        btn_frame,
        text="📁  Select Folder",
        command=choose_folder,
        bg="#27ae60", fg="white", activebackground="#219a52", activeforeground="white",
        font=("Arial", 10, "bold"), relief="flat",
        padx=18, pady=10, cursor="hand2",
    )
    d_btn.pack(side="left", padx=(0, 12))

    tk.Label(btn_frame,
             text="Pick a folder and ALL\n.gpkg files inside will\nbe validated at once.",
             bg="#f0f2f5", fg="#555", font=("Arial", 8),
             justify="left").pack(side="left")

    # ── Cancel / footer ────────────────────────────────────────────────────────────────────────
    footer = tk.Frame(root, bg="#e8ecef", pady=8, padx=24)
    footer.pack(fill="x")
    tk.Button(
        footer, text="Cancel", command=root.destroy,
        bg="#e8ecef", fg="#666", relief="flat",
        font=("Arial", 9), cursor="hand2",
    ).pack(side="right")

    root.update_idletasks()
    root.mainloop()
    try:
        root.destroy()
    except Exception:
        pass

    return sorted(set(selected_paths))
