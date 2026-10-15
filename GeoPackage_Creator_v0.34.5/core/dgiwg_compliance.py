# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
DGIWG Compliance Module

Enforces Defense Geospatial Information Working Group (DGIWG) standards
for GeoPackage creation. This module provides comprehensive validation
and compliance checking for DGIWG-126 Edition 1.1 requirements.

Key Responsibilities:
- Verify OGC GeoPackage table structure
- Validate R-Tree spatial indexes
- Check metadata compliance
- Verify extension registrations
- Validate SRS entries
"""

import sqlite3
import logging
from typing import Any, Dict, List, Tuple

from .config import (
    SECURITY_LEVELS,
    NATO_SECURITY_MARKINGS,
    TOPIC_CATEGORIES,
    KNOWN_LANGUAGE_CODES,
    KNOWN_NATION_CODES,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class DGIWGCompliance:
    """
    DGIWG compliance validator and enforcer.

    Checks that generated GeoPackages meet all DGIWG-126 requirements,
    including mandatory tables, extensions, and metadata.
    """

    # Required OGC GeoPackage tables
    REQUIRED_TABLES = [
        "gpkg_contents",
        "gpkg_spatial_ref_sys",
        "gpkg_geometry_columns",
        "gpkg_extensions",
    ]

    # Recommended DGIWG extension tables
    RECOMMENDED_TABLES = [
        "gpkg_metadata",
        "gpkg_metadata_reference",
        "gpkg_data_columns",
        "gpkg_data_column_constraints",
    ]

    # Required SRS entries
    REQUIRED_SRS = [
        -1,  # Undefined Cartesian
        0,   # Undefined Geographic
        4326,  # WGS 84
    ]

    @classmethod
    def validate_table_structure(cls, gpkg_path: str) -> Dict[str, bool]:
        """
        Validate that GeoPackage has all required OGC/DGIWG tables.

        Args:
            gpkg_path: Path to GeoPackage file

        Returns:
            Dict with validation results for each required table

        Raises:
            Exception: If database cannot be opened
        """
        results = {}
        conn = sqlite3.connect(gpkg_path)
        try:
            cursor = conn.cursor()

            # Check required tables
            for table in cls.REQUIRED_TABLES:
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                exists = cursor.fetchone() is not None
                results[f"required_{table}"] = exists

                if not exists:
                    logger.warning(f"Missing required table: {table}")

            # Check recommended tables
            for table in cls.RECOMMENDED_TABLES:
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                exists = cursor.fetchone() is not None
                results[f"recommended_{table}"] = exists

            return results

        except Exception as e:
            logger.error(f"Error validating table structure: {e}")
            raise
        finally:
            conn.close()

    @classmethod
    def validate_spatial_indexes(cls, gpkg_path: str) -> Tuple[bool, int]:
        """
        Validate presence of R-Tree spatial indexes (DGIWG-MANDATORY).

        Args:
            gpkg_path: Path to GeoPackage

        Returns:
            Tuple of (has_indexes: bool, index_count: int)

        Raises:
            Exception: If database error occurs
        """
        conn = sqlite3.connect(gpkg_path)
        try:
            cursor = conn.cursor()

            # Find all R-Tree spatial indexes
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'rtree%'"
            )
            rtree_tables = cursor.fetchall()

            has_indexes = len(rtree_tables) > 0
            logger.info(
                f"Spatial indexes found: {len(rtree_tables)} R-Tree table(s)"
            )
            return has_indexes, len(rtree_tables)

        except Exception as e:
            logger.error(f"Error validating spatial indexes: {e}")
            raise
        finally:
            conn.close()

    @classmethod
    def validate_srs_entries(cls, gpkg_path: str) -> Dict[int, bool]:
        """
        Validate that required SRS entries exist.

        Args:
            gpkg_path: Path to GeoPackage

        Returns:
            Dict with results for each required SRS ID

        Raises:
            Exception: If database error occurs
        """
        results = {}
        conn = sqlite3.connect(gpkg_path)
        try:
            cursor = conn.cursor()

            for srs_id in cls.REQUIRED_SRS:
                cursor.execute(
                    "SELECT srs_id FROM gpkg_spatial_ref_sys WHERE srs_id=?",
                    (srs_id,),
                )
                exists = cursor.fetchone() is not None
                results[srs_id] = exists

                if not exists:
                    logger.warning(f"Missing required SRS ID: {srs_id}")

            return results

        except Exception as e:
            logger.error(f"Error validating SRS entries: {e}")
            raise
        finally:
            conn.close()

    @classmethod
    def validate_metadata_tables(cls, gpkg_path: str) -> Dict[str, bool]:
        """
        Validate metadata tables and structure.

        Args:
            gpkg_path: Path to GeoPackage

        Returns:
            Dict with metadata validation results
        """
        results = {}
        conn = sqlite3.connect(gpkg_path)
        try:
            cursor = conn.cursor()

            # Check metadata table
            cursor.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='gpkg_metadata'"
            )
            has_metadata = cursor.fetchone()[0] > 0
            results["metadata_table_exists"] = has_metadata

            # Check metadata reference table
            cursor.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='gpkg_metadata_reference'"
            )
            has_metadata_ref = cursor.fetchone()[0] > 0
            results["metadata_reference_table_exists"] = has_metadata_ref

            # Count metadata records
            if has_metadata:
                cursor.execute("SELECT COUNT(*) FROM gpkg_metadata")
                count = cursor.fetchone()[0]
                results["metadata_record_count"] = count
                results["has_metadata_records"] = count > 0

                logger.info(f"Found {count} metadata record(s)")

            return results

        except Exception as e:
            logger.warning(f"Error validating metadata: {e}")
            return {"metadata_error": str(e)}
        finally:
            conn.close()

    @classmethod
    def validate_extensions(cls, gpkg_path: str) -> List[str]:
        """
        List registered extensions.

        Args:
            gpkg_path: Path to GeoPackage

        Returns:
            List of extension names

        Raises:
            Exception: If database error occurs
        """
        conn = sqlite3.connect(gpkg_path)
        try:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT DISTINCT extension_name FROM gpkg_extensions"
            )
            extensions = [row[0] for row in cursor.fetchall()]

            logger.info(f"Registered extensions: {extensions}")
            return extensions

        except Exception as e:
            logger.warning(f"Error reading extensions: {e}")
            return []
        finally:
            conn.close()

    @classmethod
    def full_compliance_check(cls, gpkg_path: str) -> Dict[str, Any]:
        """
        Perform complete DGIWG compliance check.

        Args:
            gpkg_path: Path to GeoPackage

        Returns:
            Comprehensive compliance report

        Raises:
            Exception: If critical validation fails
        """
        report = {
            "compliant": True,
            "errors": [],
            "warnings": [],
            "checks": {},
        }

        try:
            # Check 1: Table structure
            logger.info("Checking table structure...")
            table_results = cls.validate_table_structure(gpkg_path)
            report["checks"]["table_structure"] = table_results

            for table in cls.REQUIRED_TABLES:
                if not table_results.get(f"required_{table}", False):
                    report["errors"].append(f"Missing required table: {table}")
                    report["compliant"] = False

            # Check 2: Spatial indexes (DGIWG-MANDATORY)
            logger.info("Checking spatial indexes (DGIWG-MANDATORY)...")
            has_indexes, index_count = cls.validate_spatial_indexes(gpkg_path)
            report["checks"]["spatial_indexes"] = {
                "present": has_indexes,
                "count": index_count,
            }

            if not has_indexes:
                report["errors"].append(
                    "No R-Tree spatial indexes found (DGIWG-mandatory requirement)"
                )
                report["compliant"] = False

            # Check 3: SRS entries
            logger.info("Checking SRS entries...")
            srs_results = cls.validate_srs_entries(gpkg_path)
            report["checks"]["srs_entries"] = srs_results

            for srs_id, exists in srs_results.items():
                if not exists:
                    report["warnings"].append(f"Missing SRS ID: {srs_id}")

            # Check 4: Metadata
            logger.info("Checking metadata...")
            metadata_results = cls.validate_metadata_tables(gpkg_path)
            report["checks"]["metadata"] = metadata_results

            if not metadata_results.get("has_metadata_records", False):
                report["warnings"].append("No metadata records found")

            # Check 5: Extensions
            logger.info("Checking extensions...")
            extensions = cls.validate_extensions(gpkg_path)
            report["checks"]["extensions"] = extensions

            # Summary
            logger.info(f"Compliance check complete: {'✓ PASS' if report['compliant'] else '✗ FAIL'}")
            logger.info(f"  Errors: {len(report['errors'])}")
            logger.info(f"  Warnings: {len(report['warnings'])}")

            return report

        except Exception as e:
            report["compliant"] = False
            report["errors"].append(f"Compliance check failed: {e}")
            logger.error(f"Compliance check error: {e}")
            return report

    @staticmethod
    def validate_metadata_fields(
        title: str,
        abstract: str,
        security: str,
        language: str,
        topic_category: str,
        nation: str,
    ) -> Tuple[bool, List[str]]:
        """
        Validate metadata field values against standards.

        Args:
            title: Dataset title
            abstract: Dataset abstract
            security: Security classification
            language: ISO 639-2 language code
            topic_category: ISO 19115 topic category
            nation: ISO 3166-1 alpha-3 nation code

        Returns:
            Tuple of (valid: bool, errors: list of error messages)
        """
        errors = []

        # Validate security — accept both national levels and NATO markings
        # (mirrors InputValidator.validate_security_level added in v0.27.0)
        if security not in SECURITY_LEVELS and security not in NATO_SECURITY_MARKINGS:
            errors.append(f"Invalid security level: {security}")

        # Validate language
        if language.lower() not in KNOWN_LANGUAGE_CODES:
            errors.append(f"Invalid language code: {language}")

        # Validate topic category
        if topic_category not in TOPIC_CATEGORIES:
            errors.append(f"Invalid topic category: {topic_category}")

        # Validate nation
        if nation.upper() not in KNOWN_NATION_CODES:
            errors.append(f"Invalid nation code: {nation}")

        # Validate text fields
        if not title or len(title) < 5:
            errors.append("Title must be at least 5 characters")

        if not abstract or len(abstract) < 10:
            errors.append("Abstract must be at least 10 characters")

        return len(errors) == 0, errors
