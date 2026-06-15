"""Network/internet check helpers for the DGIWG validator (v1.56)."""
import os
import sys
import json
import re
import math
import urllib.request
import urllib.error
from .constants import NET_TIMEOUT
_OGC_TMS_MAP = {
    3857: "WebMercatorQuad",
    4326: "WorldCRS84Quad",
    3395: "WorldMercatorWGS84Quad",
    5041: "UPSNorthWGS84Quad",
    5042: "UPSSouthWGS84Quad",
}
_OGC_TMS_BASE = "https://schemas.opengis.net/tms/1.0/json/examples/{name}.json"
_EPSG_API     = "https://apps.epsg.org/api/v1/CoordRefSystem/{code}/"

# Network result caches — keyed by srs_id, uri, or tms_name.
# Populated on first call, reused for subsequent files in the same batch run.
# Avoids redundant HTTP requests when the same CRS / URI appears in multiple files.
_EPSG_CACHE: dict[int, tuple]   = {}   # srs_id  -> (ok, note)
_URI_CACHE:  dict[str, tuple]   = {}   # uri     -> (ok, note)
_TMS_CACHE:  dict[str, tuple]   = {}   # tms_name -> (ok, note)

# ── v1.47: Offline EPSG JSON cache ───────────────────────────────────────────
# Path to the bundled EPSG cache file (sits in the same folder as this script).
# Cache file lives alongside the .py script or .pyz zipapp launcher
_EPSG_JSON_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(sys.argv[0])),
    "dgiwg_epsg_cache.json"
)
_EPSG_JSON_CACHE: dict = {}   # loaded on first use via _load_epsg_json_cache()

def _load_epsg_json_cache() -> dict:
    """Load dgiwg_epsg_cache.json once and cache the result in _EPSG_JSON_CACHE.

    Returns the 'entries' dict keyed by str(srs_id), or {} if the file is missing
    or malformed.  Never raises — validation degrades gracefully without the cache.
    """
    global _EPSG_JSON_CACHE
    if _EPSG_JSON_CACHE:
        return _EPSG_JSON_CACHE
    try:
        with open(_EPSG_JSON_CACHE_PATH, encoding="utf-8") as _f:
            data = json.loads(_f.read())
        _EPSG_JSON_CACHE = data.get("entries", {})
    except Exception:
        _EPSG_JSON_CACHE = {}
    return _EPSG_JSON_CACHE

# ── v1.47: Bundled minimal ISO 19115/GMD XSD for DMF structural validation ───
# This is a simplified (not full ISO 19115) XSD that validates the required
# element structure of a DGIWG DMF metadata record.  It is used by _r18() when
# lxml is available.  The schema validates:
#   - Root element is MD_Metadata in the gmd namespace
#   - Required child elements are present in any order (xs:all)
#   - fileIdentifier, language, characterSet, hierarchyLevel, contact,
#     dateStamp, and identificationInfo are all mandatory children
# Limitations: does not validate code-list values or nested element content —
# those are handled by the existing ElementTree checks in _r18().
DMF_XSD_INLINE = """\
<?xml version="1.0" encoding="UTF-8"?>
<xs:schema
    xmlns:xs="http://www.w3.org/2001/XMLSchema"
    xmlns:gmd="http://www.isotc211.org/2005/gmd"
    xmlns:gco="http://www.isotc211.org/2005/gco"
    targetNamespace="http://www.isotc211.org/2005/gmd"
    elementFormDefault="qualified"
    attributeFormDefault="unqualified">

  <!-- Minimal gco import for CharacterString / Date / DateTime -->
  <xs:import namespace="http://www.isotc211.org/2005/gco"
             schemaLocation=""/>

  <!-- ── Root element ── -->
  <xs:element name="MD_Metadata" type="gmd:MD_Metadata_Type"/>

  <xs:complexType name="MD_Metadata_Type">
    <xs:all>
      <xs:element name="fileIdentifier"    minOccurs="1" type="xs:anyType"/>
      <xs:element name="language"          minOccurs="1" type="xs:anyType"/>
      <xs:element name="characterSet"      minOccurs="1" type="xs:anyType"/>
      <xs:element name="hierarchyLevel"    minOccurs="1" type="xs:anyType"/>
      <xs:element name="contact"           minOccurs="1" type="xs:anyType"/>
      <xs:element name="dateStamp"         minOccurs="1" type="xs:anyType"/>
      <xs:element name="identificationInfo" minOccurs="1" type="xs:anyType"/>
      <!-- Any other elements allowed -->
      <xs:element name="referenceSystemInfo"   minOccurs="0" type="xs:anyType"/>
      <xs:element name="distributionInfo"      minOccurs="0" type="xs:anyType"/>
      <xs:element name="dataQualityInfo"       minOccurs="0" type="xs:anyType"/>
      <xs:element name="metadataConstraints"   minOccurs="0" type="xs:anyType"/>
      <xs:element name="spatialRepresentationInfo" minOccurs="0" type="xs:anyType"/>
    </xs:all>
    <xs:anyAttribute namespace="##any" processContents="lax"/>
  </xs:complexType>

</xs:schema>
"""

# ISO 19115 element names required in DGIWG DMF metadata
_DMF_REQUIRED_ELEMENTS = [
    "fileIdentifier", "language", "characterSet",
    "hierarchyLevel", "contact", "dateStamp", "identificationInfo",
]

def _net_get(url, timeout=NET_TIMEOUT):
    """HTTP GET. Returns (status_int, text_body) or raises _NetError.

    Returns a synthetic _NetError immediately when --offline mode is active,
    avoiding any network I/O on air-gapped / 국방망 networks.
    """
    import builtins as _b
    if getattr(_b, "_DGIWG_OFFLINE", False):
        raise _NetError("OFFLINE MODE — internet checks disabled (--offline flag)", None)
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "DGIWG-Validator/1.0",
                          "Accept": "application/json, text/xml, */*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise _NetError(f"HTTP {e.code}", e.code)
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if "Name or service not known" in reason or "Temporary failure" in reason or "Name resolution" in reason:
            raise _NetError("NO INTERNET — DNS resolution failed", None)
        raise _NetError(f"URL error: {reason}", None)
    except Exception as e:
        raise _NetError(f"{type(e).__name__}: {e}", None)

class _NetError(Exception):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code  # None = no internet; int = HTTP error code

def _net_check_uri(uri, timeout=NET_TIMEOUT):
    """Returns (ok:bool, note:str). ok=True if reachable."""
    if uri in _URI_CACHE:
        return _URI_CACHE[uri]
    if not uri or not uri.startswith("http"):
        result = (False, f"Not a URL: '{uri}'")
        _URI_CACHE[uri] = result
        return result
    try:
        req = urllib.request.Request(
            uri, method="HEAD",
            headers={"User-Agent": "DGIWG-Validator/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            result = (True, f"HTTP {r.status} — reachable ✓")
            _URI_CACHE[uri] = result
            return result
    except urllib.error.HTTPError as e:
        if e.code in (405,):        # Method Not Allowed — server is up
            result = (True, f"HTTP {e.code} (HEAD not allowed, server reachable) ✓")
        else:
            result = (False, f"HTTP {e.code} — URI not reachable ✗")
        _URI_CACHE[uri] = result
        return result
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if "Temporary failure" in reason or "Name resolution" in reason or "Name or service" in reason:
            return None, "NO INTERNET — cannot verify URI"   # transient — don't cache
        result = (False, f"URI error: {reason} ✗")
        _URI_CACHE[uri] = result
        return result
    except Exception as e:
        result = (False, f"{type(e).__name__}: {e}")
        _URI_CACHE[uri] = result
        return result

def _normalize_name(s):
    """Normalize a CRS / EPSG name for loose comparison.

    v1.52: factored out from two near-duplicate sites inside
    ``_net_check_epsg()`` that previously used divergent rules (the offline
    JSON-cache branch stripped both spaces and underscores; the online
    registry branch stripped only spaces).  Consolidating here ensures the
    offline and online code paths apply identical normalization rules so
    the same (registry, file) name pair yields the same match verdict
    regardless of which branch runs.

    Rules:
      - lowercase
      - remove all space characters
      - remove all underscores

    Parameters
    ----------
    s : str or None
        Raw name.  ``None`` is coerced to ``""``.

    Returns
    -------
    str
        Normalized name suitable for substring / equality comparison.
    """
    if not s:
        return ""
    return s.lower().replace(" ", "").replace("_", "")


def _net_check_epsg(srs_id, srs_name, timeout=NET_TIMEOUT):
    """Query EPSG API and compare name. Returns (ok, note).

    v1.47: JSON cache consulted first when in offline mode, before the
    hardcoded DGIWG table — covers all UTM zones without pyproj.
    v1.52: name comparisons now delegate to _normalize_name() in both the
    offline JSON-cache and online-registry branches (previously inconsistent).
    """
    if srs_id in _EPSG_CACHE:
        return _EPSG_CACHE[srs_id]

    # v1.47: offline JSON cache first-pass (covers all 128 DGIWG EPSG codes)
    import builtins as _b_epsg
    if getattr(_b_epsg, "_DGIWG_OFFLINE", False):
        cache = _load_epsg_json_cache()
        entry = cache.get(str(srs_id))
        if entry:
            official_name  = entry.get("name", "")
            official_datum = entry.get("datum", "")
            deprecated     = entry.get("deprecated", False)
            if deprecated:
                result = (False, f"EPSG:{srs_id} is deprecated (JSON cache) ✗")
            else:
                # v1.52: shared _normalize_name() — see helper for rules.
                _off = _normalize_name(official_name)
                _src = _normalize_name(srs_name)
                if _off in _src or _src in _off:
                    result = (True,
                              f"EPSG:{srs_id} name consistent with JSON cache "
                              f"('{official_name}') — offline check ✓")
                else:
                    result = (True,
                              f"EPSG:{srs_id} JSON cache name='{official_name}' "
                              f"file='{srs_name}' (offline) — manual datum cross-check recommended")
            _EPSG_CACHE[srs_id] = result
            return result
        # Not in JSON cache — fall through to hardcoded table in _r13()
        return (None, f"EPSG:{srs_id} not in offline JSON cache — install pyproj for full check")

    try:
        _, body = _net_get(_EPSG_API.format(code=srs_id), timeout=timeout)
        data = json.loads(body)
        epsg_name = data.get("name", "")
        epsg_deprecated = data.get("deprecated", False)
        # v1.52: apply shared _normalize_name() on both sides so the online and
        # offline branches agree on what counts as an exact match.  Parenthetical
        # realization suffixes on the file-side name (e.g. "NAD83 (2011)") are
        # dropped via split("(")[0] BEFORE normalization, preserving prior
        # behaviour of treating "NAD83 (2011)" as equivalent to "NAD83".
        _epsg_norm = _normalize_name(epsg_name)
        _file_norm = _normalize_name(srs_name.split("(")[0].strip())
        match = (_epsg_norm == _file_norm)
        if epsg_deprecated:
            result = (False, f"EPSG:{srs_id} is deprecated in EPSG registry ✗")
        elif match:
            result = (True, f"EPSG:{srs_id} name matches registry ('{epsg_name}') ✓")
        # Partial match check — case-insensitive substring (kept intentionally
        # looser than _normalize_name; this catches legitimate partials like
        # "WGS 84 / UTM zone 19N" vs "UTM zone 19N").
        elif epsg_name.lower() in srs_name.lower() or srs_name.lower() in epsg_name.lower():
            result = (True, f"EPSG:{srs_id} partial name match: registry='{epsg_name}', file='{srs_name}' ✓")
        else:
            result = (False, f"EPSG:{srs_id} name mismatch: registry='{epsg_name}', file='{srs_name}' ✗")
        _EPSG_CACHE[srs_id] = result
        return result
    except _NetError as e:
        return None, str(e)   # transient — don't cache
    except (json.JSONDecodeError, KeyError) as e:
        return None, f"EPSG API response parse error: {e}"

def _net_check_scale_denoms(srs_id, zoom_pixel_sizes, tolerance=0.005, timeout=NET_TIMEOUT):
    """
    Compare pixel sizes from gpkg_tile_matrix against OGC TileMatrixSet definition.
    zoom_pixel_sizes: list of (zoom_level, pixel_x_size, pixel_y_size)
    Returns (ok, note).
    """
    tms_name = _OGC_TMS_MAP.get(srs_id)
    if not tms_name:
        return None, f"No OGC TileMatrixSet defined for srs_id={srs_id} — scale denom check N/A"
    # Cache the parsed ogc_levels dict by tms_name — the HTTP fetch only happens once
    # per TileMatrixSet per batch run; per-file pixel size comparison runs from the cache.
    if tms_name in _TMS_CACHE:
        ogc_levels = _TMS_CACHE[tms_name]
    else:
        try:
            _, body = _net_get(_OGC_TMS_BASE.format(name=tms_name), timeout=timeout)
            tms = json.loads(body)
            ogc_levels = {}
            for tm in tms.get("tileMatrix", []):
                sd = tm.get("scaleDenominator")
                if sd:
                    ogc_px = sd * 0.00028
                    try:
                        z = int(tm.get("identifier", tm.get("id", -1)))
                        ogc_levels[z] = ogc_px
                    except (ValueError, TypeError):
                        pass
            if not ogc_levels:
                return None, f"OGC TMS '{tms_name}' parsed but no tileMatrix entries found"
            _TMS_CACHE[tms_name] = ogc_levels
        except _NetError as e:
            return None, str(e)   # transient — don't cache
        except (json.JSONDecodeError, KeyError) as e:
            return None, f"OGC TMS response parse error: {e}"
    mismatches, matches, skipped = [], [], []
    for z, px, py in zoom_pixel_sizes:
        if z not in ogc_levels:
            skipped.append(f"zoom {z} not in OGC definition")
            continue
        ogc_px = ogc_levels[z]
        rel_err = abs(px - ogc_px) / ogc_px if ogc_px else float('inf')
        if rel_err > tolerance:
            mismatches.append(
                f"zoom {z}: file={px:.6f}, OGC={ogc_px:.6f} (err={rel_err*100:.2f}%)")
        else:
            matches.append(f"zoom {z}: {px:.6f} ≈ OGC {ogc_px:.6f} ✓")
    if mismatches:
        return False, (f"OGC '{tms_name}' scale mismatch: " +
                       "; ".join(mismatches) +
                       (f"; OK: {'; '.join(matches)}" if matches else ""))
    note = f"OGC '{tms_name}': all {len(matches)} zoom level(s) match scale denominators ✓"
    if skipped:
        note += f" ({len(skipped)} zoom(s) not in OGC definition: {'; '.join(skipped)})"
    return True, note

def _net_check_dmf_xml(xml_text):
    """
    Parse metadata XML and check for required ISO 19115 / DMF elements.
    Returns (ok, note).
    """
    if not xml_text or len(xml_text.strip()) < 20:
        return False, "metadata column is empty ✗"
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        return False, f"XML parse error: {e} ✗"
    # Collect all tag local-names (strip namespace URIs)
    all_tags = {el.tag.split("}")[-1] if "}" in el.tag else el.tag
                for el in root.iter()}
    found    = [e for e in _DMF_REQUIRED_ELEMENTS if e in all_tags]
    missing  = [e for e in _DMF_REQUIRED_ELEMENTS if e not in all_tags]
    root_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if missing:
        return False, (f"XML root=<{root_tag}>. "
                       f"Missing ISO 19115 elements: {missing}. "
                       f"Found: {found} ✗")
    return True, (f"XML root=<{root_tag}>. "
                  f"All required ISO 19115 elements present: {found} ✓")

# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS & LOOKUP TABLES
# ──────────────────────────────────────────────────────────────────────────────

def _http_get(url, timeout=NET_TIMEOUT):
    """Return (ok, content_or_reason).
    ok=True  → content is bytes
    ok=False → content is human-readable reason string
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DGIWG-Validator/1.01"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, r.read()
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} {e.reason}"
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if "Name or service not known" in reason or "Temporary failure" in reason                 or "No route to host" in reason or "Network is unreachable" in reason                 or "nodename nor servname" in reason:
            return False, "NO INTERNET"
        return False, f"Network error: {reason}"
    except Exception as e:
        return False, f"Error: {e}"

def _http_head(url, timeout=NET_TIMEOUT):
    """Return (ok, status_or_reason). Just checks reachability."""
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "DGIWG-Validator/1.01"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        # 4xx = URI exists but may require auth; still reachable
        if e.code < 500:
            return True, f"HTTP {e.code} (reachable)"
        return False, f"HTTP {e.code} {e.reason}"
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if "Name or service not known" in reason or "Temporary failure" in reason                 or "No route to host" in reason or "Network is unreachable" in reason                 or "nodename nor servname" in reason:
            return False, "NO INTERNET"
        return False, f"Network error: {reason}"
    except Exception as e:
        return False, f"Error: {e}"


