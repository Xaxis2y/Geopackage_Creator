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

GPKG_APPLICATION_ID_DGIWG = 0x47503132
"""DGIWG-required application_id marker ('GP12' in hex: 0x47503132).

The DGIWG GeoPackage Compliance Validator (STD-DP-19-005) requires the SQLite
header application_id to encode the GeoPackage version directly as 'GP12'
(0x47503132 = GeoPackage 1.2/1.3). GDAL/QGIS instead write the OGC 1.2+ marker
'GPKG' (0x47504B47) and put the version in user_version; the DGIWG validator
flags that as non-conformant (Req 3). GDAL and QGIS both still recognise the
'GP12' marker, so the converter rewrites application_id to this value during the
DGIWG finalization step while leaving user_version=10400 intact.
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

DGIWG_CRS_VECTOR_3D: Set[int] = {4979, 9518}
"""Allowed CRS for 3D vector feature layers (DGIWG Req 10).

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

TOOL_VERSION = "0.29.0"
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

# Options passed to GDAL when creating layers (DGIWG-mandatory)
GDAL_LAYER_OPTIONS = [
    "SPATIAL_INDEX=YES",  # R-Tree spatial index (DGIWG-MANDATORY)
    "GEOMETRY_NAME=geom",
    "OVERWRITE=YES",
]

# =====================
