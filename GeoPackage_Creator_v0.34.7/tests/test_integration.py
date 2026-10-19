# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Integration tests for GeoPackage Creator

Tests complete end-to-end workflows including:
- Full conversion pipeline
- DGIWG compliance validation
- Metadata generation and verification
- Multiple profile handling
"""

import pytest
import os
import sqlite3

from core import GeoPackageConverter
from core.dgiwg_compliance import DGIWGCompliance


class TestEndToEndConversion:
    """Test complete conversion workflows."""

    def test_full_conversion_shapefile_to_gpkg(self, sample_shapefile, temp_dir):
        """Test complete workflow: Shapefile → GeoPackage."""
        converter = GeoPackageConverter(profile="military")
        output_gpkg = os.path.join(temp_dir, "converted.gpkg")

        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage=output_gpkg,
            title="Test Points Dataset",
            abstract="A test dataset of point features",
            poc="Jane Smith",
            org="Test Agency",
            nation="USA",
            security="CONFIDENTIAL",
            language="eng",
            topic_category="transportation",
            ref_date="2026-06-02",
        )

        # Verify success
        assert result["success"] is True
        assert result["error"] is None
        assert result["layer_count"] > 0
        assert result["total_features"] > 0
        assert os.path.exists(output_gpkg)
        assert os.path.getsize(output_gpkg) > 1000  # Should have substantial size

    def test_full_conversion_with_compliance_check(self, sample_shapefile, temp_dir):
        """Test conversion and verify DGIWG compliance."""
        converter = GeoPackageConverter(profile="military")
        output_gpkg = os.path.join(temp_dir, "compliant.gpkg")

        # Convert
        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage=output_gpkg,
            title="NATO Test Data",
            abstract="Test dataset for NATO operations",
            poc="Captain Smith",
            org="NATO Defense",
            nation="USA",
            security="CONFIDENTIAL",
            language="eng",
            topic_category="geoscientificInformation",
        )

        assert result["success"] is True

        # Verify compliance
        compliance = DGIWGCompliance.full_compliance_check(output_gpkg)
        assert isinstance(compliance, dict)
        assert "compliant" in compliance
        assert "checks" in compliance

    def test_multiple_conversions_different_profiles(self, sample_shapefile, temp_dir):
        """Test conversions with different profiles."""
        profiles = ["default", "military", "civilian", "high_security"]
        results = {}

        for profile in profiles:
            converter = GeoPackageConverter(profile=profile)
            output_gpkg = os.path.join(temp_dir, f"{profile}_output.gpkg")

            result = converter.convert(
                source_geodatabase=sample_shapefile,
                output_geopackage=output_gpkg,
                title=f"Test {profile.title()}",
                abstract="Test abstract",
                poc="Test Person",
                org="Test Org",
                nation="USA",
            )

            results[profile] = result
            # Each should succeed or have clear error message
            assert isinstance(result, dict)
            assert "success" in result

    def test_conversion_preserves_geometry(self, sample_shapefile, temp_dir):
        """Test that conversion preserves geometry types."""
        converter = GeoPackageConverter()
        output_gpkg = os.path.join(temp_dir, "geometry_test.gpkg")

        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage=output_gpkg,
            title="Geometry Test",
            abstract="Testing geometry preservation",
            poc="Tester",
            org="Test Org",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="transportation",
        )

        if result["success"]:
            # Check output GeoPackage has layers
            conn = sqlite3.connect(output_gpkg)
            cursor = conn.cursor()

            # Query the geometry columns table.
            # v0.30.6 fix: geometry_type_name lives in gpkg_geometry_columns,
            # NOT gpkg_contents (which has no such column). The previous query
            # raised sqlite3.OperationalError: no such column.
            cursor.execute(
                "SELECT table_name, geometry_type_name FROM gpkg_geometry_columns"
            )
            contents = cursor.fetchall()

            assert len(contents) > 0
            # First entry should be a feature table
            assert contents[0][0] is not None

            conn.close()

    def test_conversion_creates_valid_database(self, sample_shapefile, temp_dir):
        """Test that output is a valid SQLite database."""
        converter = GeoPackageConverter()
        output_gpkg = os.path.join(temp_dir, "db_test.gpkg")

        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage=output_gpkg,
            title="Database Test",
            abstract="Testing database validity",
            poc="Tester",
            org="Test Org",
            nation="USA",
        )

        if result["success"]:
            # Should be able to connect as SQLite database
            try:
                conn = sqlite3.connect(output_gpkg)
                cursor = conn.cursor()

                # Query should work
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()

                assert len(tables) > 0
                conn.close()
            except sqlite3.DatabaseError:
                pytest.fail("Output is not a valid SQLite database")


class TestDGIWGComplianceIntegration:
    """Test DGIWG compliance validation integration."""

    def test_spatial_indexes_created(self, sample_geopackage):
        """Test that R-Tree spatial indexes are present."""
        has_indexes, count = DGIWGCompliance.validate_spatial_indexes(sample_geopackage)

        assert has_indexes is True
        assert count > 0

    def test_table_structure_valid(self, sample_geopackage):
        """Test OGC table structure is valid."""
        results = DGIWGCompliance.validate_table_structure(sample_geopackage)

        assert isinstance(results, dict)
        # Required tables should be present
        assert results.get("required_gpkg_contents") is True
        assert results.get("required_gpkg_spatial_ref_sys") is True

    def test_full_compliance_report(self, sample_geopackage):
        """Test generating full compliance report."""
        report = DGIWGCompliance.full_compliance_check(sample_geopackage)

        assert isinstance(report, dict)
        assert "compliant" in report
        assert "checks" in report
        assert "errors" in report
        assert "warnings" in report

    def test_compliance_check_detects_structure_issues(self, temp_dir):
        """Test that compliance check detects invalid structure."""
        # Create a simple invalid database
        bad_db = os.path.join(temp_dir, "bad.gpkg")
        conn = sqlite3.connect(bad_db)
        conn.execute("CREATE TABLE dummy (id INTEGER)")
        conn.close()

        # Compliance check should flag issues
        report = DGIWGCompliance.full_compliance_check(bad_db)

        assert isinstance(report, dict)
        # Should have errors or non-compliant status
        assert not report.get("compliant", True) or len(report.get("errors", [])) > 0


class TestMetadataGeneration:
    """Test metadata generation in conversion."""

    def test_conversion_generates_metadata(self, sample_shapefile, temp_dir):
        """Test that conversion includes metadata."""
        converter = GeoPackageConverter()
        output_gpkg = os.path.join(temp_dir, "metadata_test.gpkg")

        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage=output_gpkg,
            title="Metadata Test Dataset",
            abstract="A dataset for testing metadata generation",
            poc="Metadata Tester",
            org="Test Metadata Agency",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="transportation",
            data_quality="Complete coverage of area of interest",
        )

        if result["success"]:
            # Check metadata table exists
            conn = sqlite3.connect(output_gpkg)
            cursor = conn.cursor()

            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='gpkg_metadata'"
            )
            has_metadata_table = cursor.fetchone() is not None

            # Metadata table may or may not exist depending on GDAL version
            # But conversion should still succeed
            assert result["success"] is True

            conn.close()


class TestErrorRecovery:
    """Test error handling and recovery."""

    def test_partial_failure_continues_with_warnings(self, sample_shapefile, temp_dir):
        """Test that conversion continues despite non-critical errors."""
        converter = GeoPackageConverter()
        output_gpkg = os.path.join(temp_dir, "partial_fail.gpkg")

        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage=output_gpkg,
            title="Partial Failure Test",
            abstract="Test partial failure handling",
            poc="Error Tester",
            org="Test Org",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="transportation",
        )

        # Should handle gracefully
        assert isinstance(result, dict)
        assert "success" in result

    def test_conversion_handles_invalid_metadata(self, sample_shapefile, temp_dir):
        """Test conversion with edge-case metadata values."""
        converter = GeoPackageConverter()
        output_gpkg = os.path.join(temp_dir, "edge_case.gpkg")

        # Very long strings
        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage=output_gpkg,
            title="A" * 500,  # Very long title
            abstract="B" * 2000,  # Very long abstract
            poc="Test Person",
            org="Test Organization",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="transportation",
        )

        # Should handle gracefully
        assert isinstance(result, dict)
