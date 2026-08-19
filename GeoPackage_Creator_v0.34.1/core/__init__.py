# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
GeoPackage Creator Core Module

Pure Python GDAL/OGR-based core for creating OGC-compliant and DGIWG-compliant GeoPackages.

This module provides platform-independent functionality for converting spatial data
(File Geodatabases, Shapefiles, etc.) to GeoPackage format with full DGIWG support.

Key Components:
- config: Constants and configuration
- gdal_handler: GDAL/OGR I/O operations
- validators: Input/output validation and CRS checking
- metadata_handler: ISO 19115 metadata generation
- dgiwg_compliance: DGIWG standard enforcement
- converter: Main orchestrator

Usage:
    from core import GeoPackageConverter

    converter = GeoPackageConverter(profile='military')
    result = converter.convert(
        source_geodatabase='input.gdb',
        output_geopackage='output.gpkg',
        title='Dataset Title',
        security='CONFIDENTIAL'
    )

Environment Requirements:
- GDAL >= 3.6.0 (tested with 3.13.2)
- osgeo library (Python GDAL bindings)
- Python 3.8+

This module uses ONLY osgeo libraries, NOT arcpy or qgis.core, ensuring
environment independence (works with Conda, OSGeo4W, or standalone Python).
"""

__version__ = "0.34.1"
__author__ = "GeoPackage Creator Team"

from .config import (
    GPKG_VERSION,
    # COMPLIANCE-1: Export only the conformant DGIWG application_id constant.
    # GPKG_APPLICATION_ID (0x47504B47, "GPKG") is the raw GDAL marker; it is
    # NOT the DGIWG-compliant value and must not be used by callers.
    GPKG_APPLICATION_ID_DGIWG,
    DGIWG_SPATIAL_INDEX_REQUIRED,
    DGIWG_APPROVED_CRS,
    DGIWG_CRS_POLICY,
    DGIWG_CRS_VECTOR_2D,
    SECURITY_LEVELS,
    NATO_SECURITY_MARKINGS,
    TOPIC_CATEGORIES,
)
from .converter import GeoPackageConverter
from .dgiwg_compliance import DGIWGCompliance
from .gdal_handler import GDALHandler

__all__ = [
    "GeoPackageConverter",
    "DGIWGCompliance",
    "GDALHandler",
    "GPKG_VERSION",
    "GPKG_APPLICATION_ID_DGIWG",
    "DGIWG_SPATIAL_INDEX_REQUIRED",
    "DGIWG_APPROVED_CRS",
    "DGIWG_CRS_POLICY",
    "DGIWG_CRS_VECTOR_2D",
    "SECURITY_LEVELS",
    "NATO_SECURITY_MARKINGS",
    "TOPIC_CATEGORIES",
]
