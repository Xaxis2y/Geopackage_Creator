"""
Validation module for GeoPackage Creator

Handles all input validation, CRS whitelist checking, and output verification
to ensure OGC/DGIWG compliance.

Key Validators:
- InputValidator: Validates user inputs and source data
- CRSValidator: Checks against DGIWG-approved CRS whitelist
- OutputValidator: Verifies OGC/DGIWG compliance of generated GeoPackages
"""

import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from osgeo import ogr, osr

from .config import (
    DGIWG_APPROVED_CRS,
    DGIWG_CRS_POLICY,
    DGIWG_SPATIAL_INDEX_REQUIRED,
    SECURITY_LEVELS,
    NATO_SECURITY_MARKINGS,
    TOPIC_CATEGORIES,
    KNOWN_LANGUAGE_CODES,
    KNOWN_NATION_CODES,
    VALIDATION_MESSAGES,
)


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


class CRSValidator:
    """Validates coordinate reference systems against DGIWG requirements."""

    @staticmethod
    def validate_epsg_code(epsg_code: int, data_type: str = "vector_2d") -> bool:
        """
        Validate that EPSG code is DGIWG-approved for the given data type.

        v0.27.0: DGIWG defines allowed CRS PER DATA TYPE (Req 7/9/10/11/12),
        not as one flat list. 2D vector layers must be EPSG:4326.

        Args:
            epsg_code: EPSG code (e.g., 4326 for WGS 84)
            data_type: One of 'vector_2d', 'vector_3d', 'raster_tiles',
                'gridded_2d', 'gridded_3d', or 'any' (union, back-compat)

        Returns:
            True if valid, raises ValidationError otherwise

        Raises:
            ValidationError: If EPSG code not approved for the data type
        """
        allowed = (
            DGIWG_APPROVED_CRS if data_type == "any"
            else DGIWG_CRS_POLICY.get(data_type)
        )
        if allowed is None:
            raise ValidationError(
                f"Unknown DGIWG data type '{data_type}'. "
                f"Valid types: {sorted(DGIWG_CRS_POLICY)} or 'any'"
            )
        if epsg_code not in allowed:
            raise ValidationError(
                VALIDATION_MESSAGES["invalid_crs"].format(code=epsg_code)
            )
        return True

    @staticmethod
    def validate_crs_dgiwg(
        srs: osr.SpatialReference, data_type: str = "vector_2d"
    ) -> bool:
        """
        Validate CRS is DGIWG-approved for the given data type.

        v0.27.0: enforces the per-data-type CRS policy of the DGIWG
        GeoPackage Profile. For 2D vector layers (the tool's current output)
        only EPSG:4326 is approved (Req 9).

        Args:
            srs: OGR SpatialReference object
            data_type: 'vector_2d' (default), 'vector_3d', 'raster_tiles',
                'gridded_2d', 'gridded_3d', or 'any'

        Returns:
            True if valid, raises ValidationError otherwise

        Raises:
            ValidationError: If CRS not DGIWG-approved or cannot be determined
        """
        if not srs:
            raise ValidationError(
                "Layer has no spatial reference system. "
                "DGIWG requires explicit CRS definition."
            )

        # Try to get EPSG code
        epsg_code = srs.GetAttrValue("AUTHORITY", 1)

        if not epsg_code:
            # Try proj4 as fallback
            proj4 = srs.ExportToProj4()
            raise ValidationError(
                f"Cannot determine EPSG code for CRS. "
                f"DGIWG requires explicit EPSG code. "
                f"Found: {proj4}"
            )

        try:
            epsg_int = int(epsg_code)
        except ValueError:
            raise ValidationError(f"Invalid EPSG code: {epsg_code}")

        # Validate against the per-data-type policy (v0.27.0)
        allowed = (
            DGIWG_APPROVED_CRS if data_type == "any"
            else DGIWG_CRS_POLICY.get(data_type, DGIWG_APPROVED_CRS)
        )
        if epsg_int not in allowed:
            raise ValidationError(
                f"CRS EPSG:{epsg_int} is not DGIWG-approved for data type "
                f"'{data_type}'. Allowed: {sorted(allowed)[:8]}"
                f"{'...' if len(allowed) > 8 else ''} "
                f"(2D vector data MUST use EPSG:4326 per DGIWG Req 9)"
            )

        return True

    @staticmethod
    def get_crs_from_layer(layer: ogr.Layer) -> Optional[int]:
        """
        Extract EPSG code from an OGR layer's spatial reference.

        Args:
            layer: OGR Layer object

        Returns:
            EPSG code as integer, or None if cannot be determined

        Raises:
            ValidationError: If CRS cannot be determined
        """
        if not layer:
            raise ValidationError("Layer is None")

        srs = layer.GetSpatialRef()
        if not srs:
            raise ValidationError("Layer has no spatial reference system")

        # Try to get EPSG code
        epsg_code = srs.GetAttrValue("AUTHORITY", 1)
        if not epsg_code:
            raise ValidationError(
                f"Cannot determine EPSG code for CRS: {srs.ExportToProj4()}"
            )

        return int(epsg_code)


class InputValidator:
    """Validates user inputs and source data."""

    @staticmethod
    def validate_security_level(level: str) -> bool:
        """Validate security classification.

        v0.27.0: NATO markings (NATO RESTRICTED, COSMIC TOP SECRET, ...)
        are accepted in addition to the five national levels.
        """
        if level not in SECURITY_LEVELS and level not in NATO_SECURITY_MARKINGS:
            raise ValidationError(
                VALIDATION_MESSAGES["invalid_security"].format(level=level)
            )
        return True

    @staticmethod
    def validate_language_code(code: str) -> bool:
        """Validate ISO 639-2 language code."""
        if code.lower() not in KNOWN_LANGUAGE_CODES:
            raise ValidationError(
                VALIDATION_MESSAGES["invalid_language"].format(code=code)
            )
        return True

    @staticmethod
    def validate_nation_code(code: str) -> bool:
        """Validate ISO 3166-1 alpha-3 nation code."""
        if code.upper() not in KNOWN_NATION_CODES:
            raise ValidationError(
                VALIDATION_MESSAGES["invalid_nation"].format(code=code)
            )
        return True

    @staticmethod
    def validate_topic_category(category: str) -> bool:
        """Validate ISO 19115 topic category."""
        if category not in TOPIC_CATEGORIES:
            raise ValidationError(
                f"Topic category '{category}' not valid. "
                f"Must be one of: {', '.join(TOPIC_CATEGORIES)}"
            )
        return True

    @staticmethod
    def validate_source_file(file_path: str) -> bool:
        """
        Validate that source file exists and is readable by GDAL.

        Args:
            file_path: Path to source geodatabase or file

        Returns:
            True if valid

        Raises:
            ValidationError: If file doesn't exist or can't be read
        """
        path = Path(file_path)

        if not path.exists():
            raise ValidationError(f"Source file not found: {file_path}")

        if not path.is_file() and not path.is_dir():
            raise ValidationError(f"Path is neither file nor directory: {file_path}")

        # Try to open with GDAL to verify readability
        try:
            ds = ogr.Open(file_path)
            if not ds:
                raise ValidationError(
                    f"GDAL cannot open file: {file_path}. "
                    f"Check format and permissions."
                )
        except Exception as e:
            raise ValidationError(f"Error reading source file: {e}")

        return True

    @staticmethod
    def validate_output_path(file_path: str) -> bool:
        """
        Validate that output path is writable.

        Args:
            file_path: Path for output GeoPackage

        Returns:
            True if valid

        Raises:
            ValidationError: If path is invalid or not writable
        """
        path = Path(file_path)

        # Check extension
        if path.suffix.lower() != ".gpkg":
            raise ValidationError(
                f"Output file must have .gpkg extension, got: {path.suffix}"
            )

        # Check parent directory exists
        parent = path.parent
        if not parent.exists():
            raise ValidationError(
                f"Output directory does not exist: {parent}. "
                f"Please create it first."
            )

        if not parent.is_dir():
            raise ValidationError(f"Output path parent is not a directory: {parent}")

        # Check write permission
        try:
            # Try to write a test file
            test_file = parent / ".gpkg_creator_test"
            test_file.write_text("test")
            test_file.unlink()
        except PermissionError:
            raise ValidationError(
                f"No write permission for directory: {parent}"
            )
        except Exception as e:
            raise ValidationError(f"Cannot write to output directory: {e}")

        return True


class OutputValidator:
    """Validates OGC/DGIWG compliance of generated GeoPackages."""

    @staticmethod
    def validate_gpkg_structure(gpkg_path: str) -> Dict[str, bool]:
        """
        Comprehensive validation of GeoPackage structure and compliance.

        Checks:
        1. SQLite format with GPKG magic bytes
        2. Openable by GDAL
        3. Required OGC tables exist
        4. DGIWG R-Tree spatial indexes present (MANDATORY)
        5. Metadata tables exist

        Args:
            gpkg_path: Path to GeoPackage file

        Returns:
            Dict with validation results: {check_name: bool}

        Raises:
            ValidationError: If critical checks fail
        """
        results = {}
        errors = []

        # Check 1: SQLite format
        try:
            with open(gpkg_path, "rb") as f:
                header = f.read(16)
                results["sqlite_format"] = header.startswith(b"SQLite format 3")
                if not results["sqlite_format"]:
                    errors.append("File is not SQLite format")
        except Exception as e:
            results["sqlite_format"] = False
            errors.append(f"Cannot read file header: {e}")

        # Check 2: GDAL can open it
        try:
            ds = ogr.Open(gpkg_path)
            results["gdal_readable"] = ds is not None
            if not results["gdal_readable"]:
                errors.append("GDAL cannot open file as GeoPackage")
        except Exception as e:
            results["gdal_readable"] = False
            errors.append(f"GDAL error: {e}")

        # Check 3: Required OGC tables
        required_tables = [
            "gpkg_contents",
            "gpkg_spatial_ref_sys",
            "gpkg_geometry_columns",
            "gpkg_extensions",
        ]

        try:
            conn = sqlite3.connect(gpkg_path)
            cursor = conn.cursor()

            for table in required_tables:
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                exists = cursor.fetchone() is not None
                results[f"table_{table}"] = exists
                if not exists:
                    errors.append(f"Missing required table: {table}")

            # Check 4: DGIWG-MANDATORY R-Tree spatial indexes
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'rtree%'"
            )
            rtree_tables = cursor.fetchall()
            results["dgiwg_spatial_indexes"] = len(rtree_tables) > 0

            if not results["dgiwg_spatial_indexes"]:
                errors.append(
                    "DGIWG Compliance Error: No R-Tree spatial indexes found. "
                    "Layers must be created with SPATIAL_INDEX=YES option."
                )

            # Check 5: Metadata tables
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'gpkg_metadata%'"
            )
            metadata_tables = cursor.fetchone() is not None
            results["metadata_tables"] = metadata_tables

            conn.close()

        except Exception as e:
            errors.append(f"Error checking tables: {e}")
            results["tables_checked"] = False

        # Overall compliance
        critical_checks = [
            results.get("sqlite_format", False),
            results.get("gdal_readable", False),
            results.get("dgiwg_spatial_indexes", False),
        ]

        results["compliant"] = all(critical_checks)
        results["errors"] = errors

        if errors and DGIWG_SPATIAL_INDEX_REQUIRED:
            raise ValidationError(
                f"GeoPackage validation failed: {'; '.join(errors)}"
            )

        return results

    @staticmethod
    def verify_layer_count(gpkg_path: str) -> int:
        """
        Count vector layers in GeoPackage.

        Args:
            gpkg_path: Path to GeoPackage

        Returns:
            Number of layers
        """
        try:
            ds = ogr.Open(gpkg_path)
            if not ds:
                raise ValidationError("Cannot open GeoPackage with GDAL")

            layer_count = ds.GetLayerCount()
            return layer_count
        except Exception as e:
            raise ValidationError(f"Error counting layers: {e}")

    @staticmethod
    def verify_crs_in_srs_table(gpkg_path: str, expected_epsg: int) -> bool:
        """
        Verify that expected CRS is recorded in gpkg_spatial_ref_sys.

        Args:
            gpkg_path: Path to GeoPackage
            expected_epsg: Expected EPSG code

        Returns:
            True if CRS found in table
        """
        try:
            conn = sqlite3.connect(gpkg_path)
            cursor = conn.cursor()

            cursor.execute(
                "SELECT srs_id FROM gpkg_spatial_ref_sys WHERE srs_id=?",
                (expected_epsg,),
            )
            found = cursor.fetchone() is not None
            conn.close()

            return found
        except Exception as e:
            raise ValidationError(f"Error checking SRS table: {e}")
