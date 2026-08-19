# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Configuration and Constants for GeoPackage Creator

This module defines all constants, standards, and approved values for creating
OGC-compliant and DGIWG-compliant GeoPackages.

CRITICAL: These constants enforce both OGC GeoPackage 1.4 and DGIWG standards.
Do not modify these without understanding the standards implications.
"""

from typing import Set, Dict

# ============================================================================
# OGC GeoPackage 1.4 Standard Constants
# ============================================================================

GPKG_VERSION = "1.4"
"""OGC GeoPackage specification version to use."""

GPKG_APPLICATION_ID = 0x47504B47
"""OGC magic bytes for GeoPackage format ('GPKG' in hex: 0x47504B47).

This value MUST be in the SQLite header for any tool to recognize the file
as a valid GeoPackage. It's set via PRAGMA application_id.
"""

GPKG_USER_VERSION = 10400
"""User version field encoding GeoPackage version (1.4.0 = 10400)."""

GPKG_APPLICATION_ID_DGIWG = GPKG_APPLICATION_ID
"""Conformant GeoPackage application id (``GPKG`` / 0x47504B47).

OGC GeoPackage 1.2 and later use the fixed ``GPKG`` application id and encode
their version in SQLite's ``user_version`` (10400 for GeoPackage 1.4.0).
The historic GP10/GP11 values apply only to GeoPackage 1.0/1.1; GP12/GP14 are
not valid GeoPackage application identifiers and cause GDAL interoperability
warnings.
"""

# ============================================================================
# DGIWG GeoPackage Profile Standards
# ============================================================================

DGIWG_SPATIAL_INDEX_REQUIRED = True
"""DGIWG-MANDATORY: All vector layers MUST have R-Tree spatial indexes.

Defense operations require spatial indexes for performance in disconnected
environments. Implementation: SPATIAL_INDEX=YES in layer creation options.
"""

# ----------------------------------------------------------------------------
# Per-data-type CRS policy (v0.27.0)
#
# DGIWG does NOT define one flat list of approved CRS. The DGIWG GeoPackage
# Profile (DGIWG 126 / STD-DP-19-005) defines DIFFERENT allowed CRS sets per
# data type, and the DGIWG GeoPackage Validator enforces them per requirement:
#   Req 7  - raster/tile CRS
#   Req 9  - 2D vector CRS (EPSG:4326 ONLY)
#   Req 10 - 3D vector CRS
#   Req 11/12 - gridded (elevation) coverage CRS
# ----------------------------------------------------------------------------

DGIWG_UTM_NORTH_ZONES: Set[int] = set(range(32601, 32661))
"""WGS 84 / UTM northern-hemisphere zones 1-60 (EPSG:32601-32660)."""

DGIWG_UTM_SOUTH_ZONES: Set[int] = set(range(32701, 32761))
"""WGS 84 / UTM southern-hemisphere zones 1-60 (EPSG:32701-32760)."""

DGIWG_CRS_VECTOR_2D: Set[int] = {4326}
"""Allowed CRS for 2D vector feature layers (DGIWG Req 9).

DGIWG mandates EPSG:4326 (WGS 84 geographic) for ALL 2D vector data.
Web Mercator and UTM are NOT permitted for 2D vector layers - they are
tile/gridded CRS only.
"""

DGIWG_CRS_VECTOR_3D: Set[int] = {4978, 4979, 9518}
"""Allowed CRS for 3D vector feature layers (DGIWG Req 10).

EPSG:4978 (WGS 84 geocentric / 3D Cartesian) — DGIWG STD-DP-19-005 Table 2.
EPSG:4979 (WGS 84 3D geographic) or EPSG:9518 (WGS 84 + EGM2008 height).
"""

DGIWG_CRS_RASTER_TILES: Set[int] = {3395, 3857, 4326, 4979, 5041, 5042}
"""Allowed CRS for raster tile pyramids (DGIWG Req 7, Table 9).

3395 World Mercator, 3857 Web Mercator, 4326/4979 WGS 84,
5041/5042 UPS North/South (polar regions).
"""

DGIWG_CRS_GRIDDED_2D: Set[int] = (
    {3395, 3857, 4326, 5041, 5042}
    | DGIWG_UTM_NORTH_ZONES
    | DGIWG_UTM_SOUTH_ZONES
)
"""Allowed CRS for 2D gridded (elevation) coverages (DGIWG Req 11)."""

DGIWG_CRS_GRIDDED_3D: Set[int] = {4979, 9518}
"""Allowed CRS for 3D gridded coverages (DGIWG Req 12)."""

DGIWG_CRS_POLICY: Dict[str, Set[int]] = {
    "vector_2d": DGIWG_CRS_VECTOR_2D,
    "vector_3d": DGIWG_CRS_VECTOR_3D,
    "raster_tiles": DGIWG_CRS_RASTER_TILES,
    "gridded_2d": DGIWG_CRS_GRIDDED_2D,
    "gridded_3d": DGIWG_CRS_GRIDDED_3D,
}
"""Map of data type -> allowed EPSG codes per the DGIWG GeoPackage Profile."""

DGIWG_APPROVED_CRS: Set[int] = (
    DGIWG_CRS_VECTOR_2D
    | DGIWG_CRS_VECTOR_3D
    | DGIWG_CRS_RASTER_TILES
    | DGIWG_CRS_GRIDDED_2D
    | DGIWG_CRS_GRIDDED_3D
)
"""Union of all DGIWG-recognised CRS across data types (back-compat).

NOTE (v0.27.0): membership here does NOT mean a CRS is valid for a given
layer - use DGIWG_CRS_POLICY[data_type] for that. This union is retained for
the SQLite finalization step (orphan-CRS cleanup / WKT2 writing), where any
DGIWG-recognised CRS row may legitimately remain in gpkg_spatial_ref_sys.
"""

# ============================================================================
# DGIWG Tile Matrix Specifications (for raster support in v1.2+)
# ============================================================================

DGIWG_TILE_MATRIX: Dict[str, int] = {
    "tile_width": 256,
    "tile_height": 256,
}
"""DGIWG-mandated tile dimensions for raster/imagery layers (Req 25).

These fixed dimensions ensure interoperability in defense systems.
Raster support foundations added in v0.27.0 (see core/raster_support.py);
use these values, not configurable.
"""

DGIWG_ZOOM_LEVEL_FACTOR = 2
"""DGIWG-mandated zoom level factor between adjacent tile matrix levels
(Req 27): each zoom level doubles resolution."""

# ============================================================================
# ISO 19115 / DGIWG Security Classifications
# ============================================================================

SECURITY_LEVELS = [
    "UNCLASSIFIED",
    "RESTRICTED",
    "CONFIDENTIAL",
    "SECRET",
    "TOP SECRET",
]
"""Valid security classification levels per ISO 19115 / DGIWG standards.

Used in metadata constraints to mark handling requirements. Choose the
HIGHEST classification that applies to ANY data in the GeoPackage.
"""

NATO_SECURITY_MARKINGS = [
    "NATO UNCLASSIFIED",
    "NATO RESTRICTED",
    "NATO CONFIDENTIAL",
    "NATO SECRET",
    "COSMIC TOP SECRET",
]
"""NATO security markings (C-M(2002)49) accepted in addition to the five
national classification levels (v0.27.0)."""

SECURITY_CODE_MAP = {
    "UNCLASSIFIED": "unclassified",
    "RESTRICTED": "restricted",
    "CONFIDENTIAL": "confidential",
    "SECRET": "secret",
    "TOP SECRET": "topSecret",
    # NATO markings map to the equivalent ISO 19115 MD_ClassificationCode
    "NATO UNCLASSIFIED": "unclassified",
    "NATO RESTRICTED": "restricted",
    "NATO CONFIDENTIAL": "confidential",
    "NATO SECRET": "secret",
    "COSMIC TOP SECRET": "topSecret",
}
"""Mapping of classification labels to code values for XML metadata."""

# ============================================================================
# ISO 19115 Topic Categories
# ============================================================================

TOPIC_CATEGORIES = [
    "farming",
    "biota",
    "boundaries",
    "climatologyMeteorologyAtmosphere",
    "economy",
    "elevation",
    "environment",
    "geoscientificInformation",
    "health",
    "imageryBaseMapsEarthCover",
    "intelligenceMilitary",
    "inlandWaters",
    "location",
    "oceans",
    "planningCadastre",
    "society",
    "structure",
    "transportation",
    "utilitiesCommunication",
]
"""ISO 19115 thematic categories describing dataset primary subject matter.

For defense data, common categories:
- intelligenceMilitary: tactical features, military installations
- transportation: roads, railways, bridges
- structure: buildings, facilities
- boundaries: administrative/political/operational
- elevation: terrain, DEMs, bathymetry
"""

# ============================================================================
# ISO 639-2 Language Codes (Bibliographic)
# ============================================================================

KNOWN_LANGUAGE_CODES = {
    "ara",  # Arabic
    "zho",  # Chinese
    "hrv",  # Croatian
    "ces",  # Czech
    "dan",  # Danish
    "nld",  # Dutch
    "eng",  # English
    "est",  # Estonian
    "fin",  # Finnish
    "fra",  # French
    "deu",  # German
    "ell",  # Greek
    "hun",  # Hungarian
    "isl",  # Icelandic
    "ita",  # Italian
    "jpn",  # Japanese
    "kor",  # Korean
    "lav",  # Latvian
    "lit",  # Lithuanian
    "mkd",  # Macedonian
    "msa",  # Malay
    "mlt",  # Maltese
    "nor",  # Norwegian
    "pol",  # Polish
    "por",  # Portuguese
    "ron",  # Romanian
    "rus",  # Russian
    "slk",  # Slovak
    "slv",  # Slovenian
    "spa",  # Spanish
    "swe",  # Swedish
    "tur",  # Turkish
}
"""Common ISO 639-2 bibliographic language codes used in metadata."""

# ============================================================================
# NATO / Partner Nation Codes (ISO 3166-1 Alpha-3)
# ============================================================================

KNOWN_NATION_CODES = {
    "ALB",  # Albania
    "AUS",  # Australia
    "AUT",  # Austria
    "BEL",  # Belgium
    "BGR",  # Bulgaria
    "CAN",  # Canada
    "CHE",  # Switzerland
    "CHL",  # Chile
    "COL",  # Colombia
    "HRV",  # Croatia
    "CZE",  # Czechia
    "DNK",  # Denmark
    "EST",  # Estonia
    "FIN",  # Finland
    "FRA",  # France
    "DEU",  # Germany
    "GRC",  # Greece
    "HUN",  # Hungary
    "ISL",  # Iceland
    "IRL",  # Ireland
    "ITA",  # Italy
    "JPN",  # Japan
    "KOR",  # South Korea
    "LVA",  # Latvia
    "LTU",  # Lithuania
    "LUX",  # Luxembourg
    "MKD",  # North Macedonia
    "MNE",  # Montenegro
    "NLD",  # Netherlands
    "NZL",  # New Zealand
    "NOR",  # Norway
    "POL",  # Poland
    "PRT",  # Portugal
    "ROU",  # Romania
    "SVK",  # Slovakia
    "SVN",  # Slovenia
    "ESP",  # Spain
    "SWE",  # Sweden
    "TUR",  # Turkey
    "UKR",  # Ukraine
    "GBR",  # United Kingdom
    "USA",  # United States
}
"""ISO 3166-1 Alpha-3 codes for NATO and partner nations.

Producer nation MUST be one of these codes per DGIWG-126 requirements.
"""

# ============================================================================
# DGIWG Metadata Standards
# ============================================================================

DMF_STANDARD_URI = "https://dgiwg.org/std/dmf/2.0"
"""DGIWG Metadata Foundation (DMF) 2.0 standard URI.

v0.27.0 fix: was the obsolete 'http://metadata.dgiwg.org/Schema/2014/DMF'.
The DGIWG GeoPackage Validator (Req 18) accepts the legacy
'http://www.dgiwg.org/std/dmf' and the current 'https://dgiwg.org/std/dmf/2.0'.
This URI is written to gpkg_metadata.md_standard_uri for the DMF record so
Req 18 can fully PASS (not just PASS*).
"""

METADATA_MIME_TYPE = "text/xml"
"""MIME type for ISO 19115 metadata stored in gpkg_metadata table.

v0.26 fix: changed from non-standard "application/xml+iso:19115" to the
standard "text/xml" expected by OGC GeoPackage validators.
"""

ISO_METADATA_STANDARD_URI = "http://www.isotc211.org/2005/gmd"
"""ISO 19115 metadata standard URI used in gpkg_metadata.md_standard_uri."""

# ============================================================================
# Conversion Profiles
# ============================================================================

CONVERSION_PROFILES = {
    "default": {
        "security_level": "UNCLASSIFIED",
        "language": "eng",
        "topic_category": "location",
        "spatial_index": True,
    },
    "military": {
        "security_level": "CONFIDENTIAL",
        "language": "eng",
        "topic_category": "intelligenceMilitary",
        "spatial_index": True,
    },
    "civilian": {
        "security_level": "UNCLASSIFIED",
        "language": "eng",
        "topic_category": "environment",
        "spatial_index": True,
    },
    "high_security": {
        "security_level": "SECRET",
        "language": "eng",
        "topic_category": "intelligenceMilitary",
        "spatial_index": True,
    },
}
"""Pre-configured conversion profiles with recommended settings."""

# ============================================================================
# Error Messages & Validation Constants
# ============================================================================

VALIDATION_MESSAGES = {
    "invalid_crs": "EPSG code {code} is not DGIWG-approved for this data type. "
    "2D vector layers must use WGS 84 (4326); 3D vector: 4979/9518; "
    "tiles/gridded: 3395, 3857, 4326, 5041/5042 UPS, UTM 32601-32660/32701-32760.",

    "invalid_security": "Security level '{level}' not valid. "
    "Must be one of: UNCLASSIFIED, RESTRICTED, CONFIDENTIAL, SECRET, TOP SECRET, "
    "or a NATO marking (NATO UNCLASSIFIED/RESTRICTED/CONFIDENTIAL/SECRET, COSMIC TOP SECRET).",

    "invalid_language": "Language code '{code}' not recognized. "
    "Must be ISO 639-2 bibliographic code (e.g., 'eng', 'fra', 'deu').",

    "invalid_nation": "Nation code '{code}' not in NATO/partner nation list. "
    "Must be ISO 3166-1 alpha-3 code (e.g., 'USA', 'GBR', 'CAN').",

    "missing_rtree": "DGIWG Compliance Error: No R-Tree spatial indexes found. "
    "Layer creation must use SPATIAL_INDEX=YES option.",
}

# ============================================================================
# Version & Metadata
# ============================================================================

TOOL_VERSION = "0.34.2"
GDAL_TESTED_VERSION = "3.13.2"   # the pinned, release-tested build (v0.30.13)
GDAL_MINIMUM_VERSION = "3.6.0"   # absolute floor; below this, unsupported

# v0.30.7: no GDAL version is currently known to be bad.
#
# An earlier draft of this release listed 3.13.2 here, on the strength of the
# access-violation crash first seen on 2026-08-04. That attribution did not
# survive checking. The crash is caused by a defect in THIS codebase - a
# GeoPackage left open by close_geopackage() while later steps reopen the same
# file through sqlite3 (see gdal_handler._flush_and_close_dataset). GDAL 3.13.2
# did not introduce it; the v0.30.6 fix to validators.py merely stopped masking
# it, by removing an early write-permission abort that had prevented the
# concurrent path from ever running to completion. GDAL 3.13.2's own release
# notes contain threading HARDENING, not a threading regression.
#
# v0.30.13 UPDATE - the pin moved FROM 3.13.1 TO 3.13.2, and this is worth
# being precise about, because a GDAL patch version has now been investigated
# TWICE in connection with an access violation in this project, and BOTH times
# GDAL's version turned out not to be the variable.
#
# The 2026-08-04/05 crash (changelogs/CHANGELOG_v0.30.13.md,
# dev_tools/diagnose_crash_v0.30.11.py / _v0.30.12.py) was bisected to a
# proven, deterministic, single-threaded
# repro - compile the bundled XSD via lxml, perform one GDAL vector write,
# make any further lxml call - that reproduced 5/5 with ZERO project code,
# under GDAL 3.13.1. The full project pipeline with lxml touched zero times
# (`heavy_no_lxml`) ran clean 5/5 under that SAME GDAL build. The fault is an
# ABI mismatch between the installed lxml build (compiled against libxml2
# 2.14.6) and the libxml2.dll conda actually resolves at runtime (2.15.3) -
# GDAL and lxml share that one DLL; it is not two competing copies.
#
# Moving to 3.13.2 is therefore a support decision, not a fix: it does not
# touch the lxml/libxml2 combination, and would not have prevented the crash
# on its own - the same fault is expected to reproduce under 3.13.2 too, until
# the environment's lxml and libxml2 are realigned (see environment.yml /
# ALLOW_LIBXML_ABI_MISMATCH below). metadata_handler._verify_libxml2_abi()
# (v0.30.13) refuses to compile the XSD under EITHER GDAL version while that
# mismatch persists, rather than let this file's version comment be the only
# thing standing between a user and a repeat of this investigation.
GDAL_KNOWN_BAD_VERSIONS = ()

# v0.30.7: serialize whole conversions process-wide (see gdal_handler and
# converter._serialize_conversions). OGR does not guarantee that two
# conversions may run concurrently in one process. Set True ONLY if you have
# verified your GDAL build and workload; the shipped GUI and CLI never run more
# than one conversion at a time, so the default costs them nothing.
ALLOW_CONCURRENT_CONVERSIONS = False

# v0.30.13: MetadataHandler refuses to compile the ISO 19139 XSD via lxml when
# etree.LIBXML_COMPILED_VERSION != etree.LIBXML_VERSION - see
# metadata_handler._verify_libxml2_abi() for the full evidence trail (that
# exact mismatch reproduced a Windows access violation 5/5 times in testing,
# with a clean pipeline run 5/5 times when lxml was removed from the picture
# entirely). Set True ONLY after you have independently verified your
# specific lxml/libxml2 combination is safe; the default protects against a
# confirmed crash, not a theoretical one.
ALLOW_LIBXML_ABI_MISMATCH = False

TOOL_NAME = "DGIWG GeoPackage Creator"

# ============================================================================
# GDAL Configuration
# ============================================================================

# Options passed to GDAL when creating GeoPackages
GDAL_GPKG_OPTIONS = [
    "VERSION=1.4",  # OGC GeoPackage 1.4 standard
    # DGIWG-mandatory: write the gpkg_crs_wkt extension, which adds the
    # definition_12_063 (WKT2) column to gpkg_spatial_ref_sys. Without this,
    # DGIWG Req 3 and Req 13 fail (WKT2 CRS definition missing).
    "CRS_WKT_EXTENSION=YES",
]

# Options passed to GDAL when creating individual layers inside a GeoPackage.
# SPATIAL_INDEX=YES is mandatory per DGIWG Req 3 (R-Tree spatial indexes).
# GEOMETRY_NAME=geom pins the geometry column name. GDAL already defaults to
# "geom", but pinning it makes the assumption explicit and guarantees that the
# R-Tree tables are named rtree_<table>_geom, which the DGIWG finalization step
# (_fix_bbox_from_rtree / _strip_z_from_2d_layers) relies on. (v0.30.6)
GDAL_LAYER_OPTIONS = [
    "SPATIAL_INDEX=YES",   # DGIWG-mandatory R-Tree spatial index
    "GEOMETRY_NAME=geom",  # explicit geometry column name (GDAL default)
]
