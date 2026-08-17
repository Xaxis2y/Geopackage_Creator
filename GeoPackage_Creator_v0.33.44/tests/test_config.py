# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Unit tests for core/config.py

Tests verify:
- All required constants are defined
- DGIWG standards constants are correct
- Conversion profiles are valid
- CRS whitelist has expected values
"""

import pytest
from core import config


class TestOGCConstants:
    """Test OGC GeoPackage 1.4 constants."""

    def test_gpkg_version(self):
        """Test GeoPackage version is 1.4."""
        assert config.GPKG_VERSION == "1.4"

    def test_gpkg_application_id(self):
        """Test GeoPackage application ID."""
        assert config.GPKG_APPLICATION_ID == 0x47504B47

    def test_gpkg_user_version(self):
        """Test GeoPackage user version for v1.4."""
        assert config.GPKG_USER_VERSION == 10400

    def test_gdal_gpkg_options(self):
        """Test GDAL GeoPackage creation options."""
        assert "VERSION=1.4" in config.GDAL_GPKG_OPTIONS

    def test_gdal_layer_options(self):
        """Test GDAL layer options include R-Tree spatial index."""
        assert "SPATIAL_INDEX=YES" in config.GDAL_LAYER_OPTIONS
        assert "GEOMETRY_NAME=geom" in config.GDAL_LAYER_OPTIONS


class TestDGIWGConstants:
    """Test DGIWG compliance constants."""

    def test_dgiwg_spatial_index_required(self):
        """Test that R-Tree spatial indexes are marked as required."""
        assert config.DGIWG_SPATIAL_INDEX_REQUIRED is True

    def test_dgiwg_approved_crs_count(self):
        """Test that DGIWG CRS whitelist has expected count."""
        # Should have WGS 84, Web Mercator, and 60 NATO UTM zones
        assert len(config.DGIWG_APPROVED_CRS) >= 62

    def test_dgiwg_approved_crs_includes_wgs84(self):
        """Test that WGS 84 (EPSG:4326) is in whitelist."""
        assert 4326 in config.DGIWG_APPROVED_CRS

    def test_dgiwg_approved_crs_includes_web_mercator(self):
        """Test that Web Mercator (EPSG:3857) is in whitelist."""
        assert 3857 in config.DGIWG_APPROVED_CRS

    def test_dgiwg_approved_crs_includes_utm_zones(self):
        """Test that NATO UTM zones (32601-32660) are in whitelist."""
        utm_zones = [code for code in config.DGIWG_APPROVED_CRS if 32601 <= code <= 32660]
        assert len(utm_zones) == 60  # 60 UTM zones

    def test_dmf_standard_uri(self):
        """v0.27.0: DMF URI must be one the DGIWG validator recognises."""
        assert config.DMF_STANDARD_URI == "https://dgiwg.org/std/dmf/2.0"
        low = config.DMF_STANDARD_URI.lower()
        assert "dgiwg" in low and "dmf" in low  # validator Req 18 row detection

    def test_crs_policy_per_data_type(self):
        """v0.27.0: per-data-type CRS policy matches the DGIWG profile."""
        assert config.DGIWG_CRS_POLICY["vector_2d"] == {4326}
        # v0.30.6: vector_3d includes EPSG:4978 (WGS 84 geocentric / 3D
        # Cartesian) alongside 4979 and 9518 per DGIWG STD-DP-19-005 Table 2.
        assert config.DGIWG_CRS_POLICY["vector_3d"] == {4978, 4979, 9518}
        assert config.DGIWG_CRS_POLICY["raster_tiles"] == {
            3395, 3857, 4326, 4979, 5041, 5042}
        assert 32601 in config.DGIWG_CRS_POLICY["gridded_2d"]
        assert 32760 in config.DGIWG_CRS_POLICY["gridded_2d"]  # southern UTM
        assert config.DGIWG_APPROVED_CRS == set().union(
            *config.DGIWG_CRS_POLICY.values())

    def test_nato_security_markings(self):
        """v0.27.0: NATO markings present and mapped to ISO codes."""
        assert "NATO RESTRICTED" in config.NATO_SECURITY_MARKINGS
        assert "COSMIC TOP SECRET" in config.NATO_SECURITY_MARKINGS
        for marking in config.NATO_SECURITY_MARKINGS:
            assert marking in config.SECURITY_CODE_MAP


class TestSecurityLevels:
    """Test security classification levels."""

    def test_security_levels_contains_required(self):
        """Test that all required security levels are present."""
        required_levels = [
            "UNCLASSIFIED",
            "RESTRICTED",
            "CONFIDENTIAL",
            "SECRET",
            "TOP SECRET",
        ]
        for level in required_levels:
            assert level in config.SECURITY_LEVELS

    def test_security_levels_count(self):
        """Test that security levels list has expected size."""
        assert len(config.SECURITY_LEVELS) >= 5


class TestTopicCategories:
    """Test ISO 19115 topic categories."""

    def test_topic_categories_count(self):
        """Test that 19 topic categories are defined."""
        assert len(config.TOPIC_CATEGORIES) == 19

    def test_topic_categories_includes_transportation(self):
        """Test that 'transportation' category exists."""
        assert "transportation" in config.TOPIC_CATEGORIES

    def test_topic_categories_includes_required(self):
        """Test that key ISO 19115 categories exist."""
        required_categories = [
            "transportation",
            "geoscientificInformation",
            "imageryBaseMapsEarthCover",
            "boundaries",
        ]
        for cat in required_categories:
            assert cat in config.TOPIC_CATEGORIES


class TestLanguageCodes:
    """Test ISO 639-2 language codes."""

    def test_language_codes_includes_english(self):
        """Test that 'eng' (English) is defined."""
        assert "eng" in config.KNOWN_LANGUAGE_CODES

    def test_language_codes_count(self):
        """Test that language codes are defined."""
        assert len(config.KNOWN_LANGUAGE_CODES) >= 32


class TestNationCodes:
    """Test ISO 3166-1 nation codes."""

    def test_nation_codes_includes_usa(self):
        """Test that USA is in nation codes."""
        assert "USA" in config.KNOWN_NATION_CODES

    def test_nation_codes_includes_nato_partners(self):
        """Test that key NATO nations are included."""
        nato_nations = ["USA", "GBR", "FRA", "DEU", "CAN"]
        for nation in nato_nations:
            assert nation in config.KNOWN_NATION_CODES

    def test_nation_codes_count(self):
        """Test that nation codes are defined."""
        assert len(config.KNOWN_NATION_CODES) >= 40


class TestConversionProfiles:
    """Test conversion profiles configuration."""

    def test_profiles_defined(self):
        """Test that conversion profiles dictionary exists."""
        assert hasattr(config, "CONVERSION_PROFILES")
        assert isinstance(config.CONVERSION_PROFILES, dict)

    def test_profile_default_exists(self):
        """Test that 'default' profile is defined."""
        assert "default" in config.CONVERSION_PROFILES

    def test_profile_military_exists(self):
        """Test that 'military' profile is defined."""
        assert "military" in config.CONVERSION_PROFILES

    def test_profile_civilian_exists(self):
        """Test that 'civilian' profile is defined."""
        assert "civilian" in config.CONVERSION_PROFILES

    def test_profile_high_security_exists(self):
        """Test that 'high_security' profile is defined."""
        assert "high_security" in config.CONVERSION_PROFILES

    def test_profile_has_required_fields(self):
        """Test that each profile has required configuration fields."""
        required_fields = [
            "security_level",
            "language",
            "topic_category",
        ]

        for profile_name, profile_config in config.CONVERSION_PROFILES.items():
            for field in required_fields:
                assert field in profile_config, f"Profile '{profile_name}' missing field '{field}'"

    def test_military_profile_is_high_security(self):
        """Test that military profile has security setting."""
        military = config.CONVERSION_PROFILES["military"]
        assert military["security_level"] == "CONFIDENTIAL"

    def test_high_security_profile_is_secret(self):
        """Test that high_security profile has elevated classification."""
        high_sec = config.CONVERSION_PROFILES["high_security"]
        assert high_sec["security_level"] in ["SECRET", "TOP SECRET"]


class TestMetadataConstants:
    """Test metadata-related constants."""

    def test_metadata_mime_type(self):
        """Test metadata MIME type is defined."""
        assert hasattr(config, "METADATA_MIME_TYPE")
        assert "xml" in config.METADATA_MIME_TYPE.lower()

    def test_security_code_map(self):
        """Test security level to code mapping."""
        assert hasattr(config, "SECURITY_CODE_MAP")
        assert isinstance(config.SECURITY_CODE_MAP, dict)

    def test_security_code_map_has_unclassified(self):
        """Test that UNCLASSIFIED maps to correct code."""
        code = config.SECURITY_CODE_MAP.get("UNCLASSIFIED")
        assert code is not None
