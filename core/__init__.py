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
- GDAL >= 3.6.0
- osgeo library (Python GDAL bindings)
- Python 3.8+

This module uses ONLY osgeo libraries, NOT arcpy or qgis.core, ensuring
environment independence (works with Conda, OSGeo4W, or standalone Python).
"""

__version__ = "0.29.0"
__author__ = "GeoPackage Creator Team"

from .config import (
    GPKG_VERSION,
    GPKG_APPLICATION_ID,
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
    "GPKG_APPLICATION_ID",
    "DGIWG_SPATIAL_INDEX_REQUIRED",
    "DGIWG_APPROVED_CRS",
    "DGIWG_CRS_POLICY",
    "DGIWG_CRS_VECTOR_2D",
    "SECURITY_LEVELS",
    "NATO_SECURITY_MARKINGS",
    "TOPIC_CATEGORIES",
]
