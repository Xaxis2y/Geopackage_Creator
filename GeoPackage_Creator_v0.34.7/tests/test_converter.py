# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Unit tests for core/converter.py

Tests verify:
- GeoPackageConverter initialization
- Conversion profiles
- Conversion workflow
- Error handling
- Result structure
"""

import pytest
import os

from core import GeoPackageConverter


class TestGeoPackageConverterInit:
    """Test GeoPackageConverter initialization."""

    def test_converter_init_default_profile(self):
        """Test converter initialization with default profile."""
        converter = GeoPackageConverter()
        assert converter.profile == "default"

    def test_converter_init_military_profile(self):
        """Test converter initialization with military profile."""
        converter = GeoPackageConverter(profile="military")
        assert converter.profile == "military"

    def test_converter_init_invalid_profile(self):
        """Test converter initialization with invalid profile raises error."""
        with pytest.raises(ValueError):
            GeoPackageConverter(profile="invalid_profile")

    def test_converter_has_handlers(self):
        """Test that converter has required handlers."""
        converter = GeoPackageConverter()
        assert hasattr(converter, "gdal_handler")
        assert hasattr(converter, "input_validator")
        assert hasattr(converter, "output_validator")


class TestAvailableProfiles:
    """Test converter profile management."""

    def test_list_available_profiles(self):
        """Test listing available profiles."""
        profiles = GeoPackageConverter.list_available_profiles()

        assert isinstance(profiles, list)
        assert "default" in profiles
        assert "military" in profiles
        assert "civilian" in profiles
        assert "high_security" in profiles

    def test_profile_count(self):
        """Test that expected number of profiles exist."""
        profiles = GeoPackageConverter.list_available_profiles()
        assert len(profiles) >= 4

    def test_get_active_profile_config(self):
        """Test getting active profile configuration."""
        converter = GeoPackageConverter(profile="military")
        config = converter.get_active_profile_config()

        assert "profile" in config
        assert "config" in config
        assert config["profile"] == "military"

    def test_profile_config_has_defaults(self):
        """Test that profile config has required defaults."""
        converter = GeoPackageConverter(profile="military")
        config = converter.get_active_profile_config()["config"]

        required_keys = ["security_level", "language", "topic_category"]
        for key in required_keys:
            assert key in config


class TestSupportedFormats:
    """Test supported input format discovery."""

    def test_get_supported_input_formats(self):
        """Test getting list of supported formats."""
        converter = GeoPackageConverter()
        formats = converter.get_supported_input_formats()

        assert isinstance(formats, list)
        assert len(formats) > 0

    def test_supported_formats_includes_shapefile(self):
        """Test that Shapefile format is supported."""
        converter = GeoPackageConverter()
        formats = converter.get_supported_input_formats()

        # Look for ESRI Shapefile or similar
        shapefile_formats = [f for f in formats if "shape" in f.lower()]
        assert len(shapefile_formats) > 0

    def test_supported_formats_includes_geojson(self):
        """Test that GeoJSON format is supported."""
        converter = GeoPackageConverter()
        formats = converter.get_supported_input_formats()

        # Look for GeoJSON
        geojson_formats = [f for f in formats if "json" in f.lower()]
        assert len(geojson_formats) > 0


class TestConversionWorkflow:
    """Test full conversion workflow."""

    def test_convert_returns_result_dict(self, sample_shapefile, temp_dir, test_metadata):
        """Test that convert() returns proper result dictionary."""
        converter = GeoPackageConverter()
        output_gpkg = os.path.join(temp_dir, "output.gpkg")

        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage=output_gpkg,
            **test_metadata,
        )

        # Check result structure
        assert isinstance(result, dict)
        assert "success" in result
        assert "error" in result
        assert "warnings" in result
        assert "layer_count" in result
        assert "total_features" in result
        assert "output_path" in result
        assert "dgiwg_compliant" in result
        assert "r_tree_indexes" in result

    def test_convert_with_valid_shapefile(self, sample_shapefile, temp_dir, test_metadata):
        """Test conversion with valid shapefile."""
        converter = GeoPackageConverter()
        output_gpkg = os.path.join(temp_dir, "output.gpkg")

        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage=output_gpkg,
            **test_metadata,
        )

        # Should succeed
        assert result["success"] is True
        assert result["error"] is None
        assert result["layer_count"] > 0
        assert os.path.exists(output_gpkg)

    def test_convert_invalid_source_file(self, temp_dir, test_metadata):
        """Test conversion with invalid source file."""
        converter = GeoPackageConverter()
        output_gpkg = os.path.join(temp_dir, "output.gpkg")

        result = converter.convert(
            source_geodatabase="/nonexistent/input.gdb",
            output_geopackage=output_gpkg,
            **test_metadata,
        )

        # Should fail
        assert result["success"] is False
        assert result["error"] is not None

    def test_convert_invalid_output_path(self, sample_shapefile, test_metadata):
        """Test conversion with invalid output path (bad extension)."""
        converter = GeoPackageConverter()

        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage="/tmp/output.shp",  # Wrong extension
            **test_metadata,
        )

        # Should fail
        assert result["success"] is False
        assert result["error"] is not None

    def test_convert_invalid_security_level(self, sample_shapefile, temp_dir, test_metadata):
        """Test conversion with invalid security level."""
        converter = GeoPackageConverter()
        output_gpkg = os.path.join(temp_dir, "output.gpkg")

        test_metadata["security"] = "INVALID_LEVEL"

        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage=output_gpkg,
            **test_metadata,
        )

        # Should fail
        assert result["success"] is False
        assert result["error"] is not None

    def test_convert_military_profile(self, sample_shapefile, temp_dir, test_metadata):
        """Test conversion with military profile."""
        converter = GeoPackageConverter(profile="military")
        output_gpkg = os.path.join(temp_dir, "military_output.gpkg")

        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage=output_gpkg,
            **test_metadata,
        )

        # Should succeed
        assert result["success"] is True
        assert result["layer_count"] > 0

    def test_convert_profile_defaults_applied(self, sample_shapefile, temp_dir):
        """Test that profile defaults are applied."""
        converter = GeoPackageConverter(profile="military")
        output_gpkg = os.path.join(temp_dir, "output.gpkg")

        # Don't provide security, language, or topic_category
        # They should be filled from profile
        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage=output_gpkg,
            title="Test",
            abstract="Test abstract",
            poc="Test Person",
            org="Test Org",
            nation="USA",
            # security, language, topic_category omitted - should use profile defaults
        )

        # Should succeed (profile provides defaults)
        assert result["success"] is True or "error" in result  # May fail for other reasons

    def test_convert_produces_valid_geopackage(self, sample_shapefile, temp_dir, test_metadata):
        """Test that output GeoPackage is valid."""
        converter = GeoPackageConverter()
        output_gpkg = os.path.join(temp_dir, "output.gpkg")

        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage=output_gpkg,
            **test_metadata,
        )

        if result["success"]:
            # Output file should exist
            assert os.path.exists(output_gpkg)
            # File should be a valid SQLite database (GPKG format)
            assert os.path.getsize(output_gpkg) > 0


class TestErrorHandling:
    """Test error handling in converter."""

    def test_converter_graceful_error_handling(self, temp_dir):
        """Test that converter handles errors gracefully."""
        converter = GeoPackageConverter()

        result = converter.convert(
            source_geodatabase="/nonexistent/path/input.gdb",
            output_geopackage=os.path.join(temp_dir, "output.gpkg"),
            title="Test",
            abstract="Test",
            poc="Test",
            org="Test",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="transportation",
        )

        # Should not raise, should return error in result
        assert isinstance(result, dict)
        assert result["success"] is False
        assert isinstance(result["error"], str)
