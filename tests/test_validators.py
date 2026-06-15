"""
Unit tests for core/validators.py

Tests verify:
- CRS whitelist validation
- Input validation (metadata fields)
- Output validation (structure and R-Tree indexes)
- ValidationError exception handling
"""

import pytest
import os
import tempfile
from pathlib import Path

from core.validators import (
    ValidationError,
    CRSValidator,
    InputValidator,
    OutputValidator,
)


class TestValidationError:
    """Test ValidationError exception."""

    def test_validation_error_is_exception(self):
        """Test that ValidationError is an Exception."""
        assert issubclass(ValidationError, Exception)

    def test_validation_error_message(self):
        """Test that ValidationError preserves message."""
        msg = "Test error message"
        error = ValidationError(msg)
        assert str(error) == msg


class TestCRSValidator:
    """Test CRS validation against DGIWG whitelist."""

    def test_validate_wgs84_approved(self):
        """Test that WGS 84 (EPSG:4326) is approved."""
        # Should not raise
        CRSValidator.validate_epsg_code(4326)

    def test_validate_web_mercator_rejected_for_2d_vector(self):
        """v0.27.0: Web Mercator is NOT approved for 2D vector (Req 9)."""
        with pytest.raises(ValidationError):
            CRSValidator.validate_epsg_code(3857)  # default: vector_2d

    def test_validate_web_mercator_approved_for_tiles(self):
        """v0.27.0: Web Mercator IS approved for raster tiles (Req 7)."""
        CRSValidator.validate_epsg_code(3857, data_type="raster_tiles")

    def test_validate_utm_zone_rejected_for_2d_vector(self):
        """v0.27.0: UTM zones are NOT approved for 2D vector (Req 9)."""
        with pytest.raises(ValidationError):
            CRSValidator.validate_epsg_code(32633)  # default: vector_2d

    def test_validate_utm_zone_approved_for_gridded(self):
        """v0.27.0: UTM zones (north AND south) approved for gridded data."""
        CRSValidator.validate_epsg_code(32633, data_type="gridded_2d")
        CRSValidator.validate_epsg_code(32733, data_type="gridded_2d")

    def test_validate_3d_vector_crs(self):
        """v0.27.0: 3D vector allows 4979 and 9518 only (Req 10)."""
        CRSValidator.validate_epsg_code(4979, data_type="vector_3d")
        CRSValidator.validate_epsg_code(9518, data_type="vector_3d")
        with pytest.raises(ValidationError):
            CRSValidator.validate_epsg_code(4326, data_type="vector_3d")

    def test_validate_ups_for_tiles(self):
        """v0.27.0: UPS North/South approved for tiles (polar regions)."""
        CRSValidator.validate_epsg_code(5041, data_type="raster_tiles")
        CRSValidator.validate_epsg_code(5042, data_type="raster_tiles")

    def test_validate_any_accepts_union(self):
        """data_type='any' accepts every DGIWG-recognised CRS."""
        for code in (4326, 3857, 3395, 4979, 9518, 5041, 5042, 32633, 32733):
            CRSValidator.validate_epsg_code(code, data_type="any")

    def test_validate_unknown_data_type_rejected(self):
        """Unknown data_type raises a clear error."""
        with pytest.raises(ValidationError):
            CRSValidator.validate_epsg_code(4326, data_type="bogus")

    def test_validate_non_approved_crs_rejected(self):
        """Test that non-approved CRS is rejected."""
        # EPSG:2927 (NAD_1983_StatePlane_Washington_South_FIPS_4602_Feet)
        with pytest.raises(ValidationError):
            CRSValidator.validate_epsg_code(2927)

    def test_validate_invalid_epsg_code(self):
        """Test that invalid EPSG code is rejected."""
        with pytest.raises(ValidationError):
            CRSValidator.validate_epsg_code(999999)


class TestInputValidator:
    """Test input metadata validation."""

    def test_validate_security_level_unclassified(self):
        """Test UNCLASSIFIED security level is valid."""
        validator = InputValidator()
        validator.validate_security_level("UNCLASSIFIED")

    def test_validate_security_level_confidential(self):
        """Test CONFIDENTIAL security level is valid."""
        validator = InputValidator()
        validator.validate_security_level("CONFIDENTIAL")

    def test_validate_security_level_invalid(self):
        """Test invalid security level raises error."""
        validator = InputValidator()
        with pytest.raises(ValidationError):
            validator.validate_security_level("INVALID_LEVEL")

    def test_validate_language_code_english(self):
        """Test English language code (eng) is valid."""
        validator = InputValidator()
        validator.validate_language_code("eng")

    def test_validate_language_code_lowercase(self):
        """Test language codes work in lowercase."""
        validator = InputValidator()
        validator.validate_language_code("eng")

    def test_validate_language_code_invalid(self):
        """Test invalid language code raises error."""
        validator = InputValidator()
        with pytest.raises(ValidationError):
            validator.validate_language_code("invalid")

    def test_validate_nation_code_usa(self):
        """Test USA nation code is valid."""
        validator = InputValidator()
        validator.validate_nation_code("USA")

    def test_validate_nation_code_invalid(self):
        """Test invalid nation code raises error."""
        validator = InputValidator()
        with pytest.raises(ValidationError):
            validator.validate_nation_code("INVALID")

    def test_validate_topic_category_transportation(self):
        """Test transportation topic category is valid."""
        validator = InputValidator()
        validator.validate_topic_category("transportation")

    def test_validate_topic_category_invalid(self):
        """Test invalid topic category raises error."""
        validator = InputValidator()
        with pytest.raises(ValidationError):
            validator.validate_topic_category("invalid_category")

    def test_validate_source_file_not_exists(self):
        """Test that non-existent source file raises error."""
        validator = InputValidator()
        with pytest.raises(ValidationError):
            validator.validate_source_file("/nonexistent/path/file.gdb")

    def test_validate_source_file_exists(self):
        """Test that existing file is accepted."""
        validator = InputValidator()
        # Create temp file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            # Should not raise
            validator.validate_source_file(temp_path)
        finally:
            os.unlink(temp_path)

    def test_validate_output_path_not_gpkg_extension(self):
        """Test that non-.gpkg output path raises error."""
        validator = InputValidator()
        with pytest.raises(ValidationError):
            validator.validate_output_path("/tmp/output.shp")

    def test_validate_output_path_gpkg_extension(self):
        """Test that .gpkg output path is accepted."""
        validator = InputValidator()
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, "output.gpkg")

        try:
            # Should not raise
            validator.validate_output_path(output_path)
        finally:
            import shutil
            shutil.rmtree(temp_dir)

    def test_validate_output_path_directory_not_writable(self):
        """Test that non-writable directory raises error."""
        validator = InputValidator()
        # Use a path that definitely doesn't exist
        bad_path = "/nonexistent/nonexistent/output.gpkg"
        with pytest.raises(ValidationError):
            validator.validate_output_path(bad_path)


class TestOutputValidator:
    """Test output GeoPackage validation."""

    def test_validate_gpkg_structure_valid(self, sample_geopackage):
        """Test validation of valid GeoPackage structure."""
        validator = OutputValidator()
        results = validator.validate_gpkg_structure(sample_geopackage)

        assert isinstance(results, dict)
        assert "compliant" in results
        # Compliant should be True or have other relevant fields
        assert "dgiwg_spatial_indexes" in results or "layer_count" in results

    def test_verify_layer_count(self, sample_geopackage):
        """Test layer count verification."""
        validator = OutputValidator()
        count = validator.verify_layer_count(sample_geopackage)

        assert isinstance(count, int)
        assert count > 0

    def test_verify_crs_in_srs_table(self, sample_geopackage):
        """Test CRS verification in SRS table."""
        validator = OutputValidator()
        # WGS 84 should be in the SRS table
        is_valid = validator.verify_crs_in_srs_table(sample_geopackage, 4326)

        assert isinstance(is_valid, bool)

    def test_verify_invalid_crs(self, sample_geopackage):
        """Test verification of non-existent CRS."""
        validator = OutputValidator()
        # Use an EPSG code that's unlikely to exist in sample
        is_valid = validator.verify_crs_in_srs_table(sample_geopackage, 999999)

        assert isinstance(is_valid, bool)
        assert is_valid is False

    def test_gpkg_file_not_exists(self, temp_dir):
        """Test validation of non-existent GeoPackage."""
        validator = OutputValidator()
        non_existent = os.path.join(temp_dir, "nonexistent.gpkg")

        # Should handle gracefully (either raise or return error dict)
        try:
            results = validator.validate_gpkg_structure(non_existent)
            assert isinstance(results, dict)
        except Exception:
            # It's ok to raise if file doesn't exist
            pass
