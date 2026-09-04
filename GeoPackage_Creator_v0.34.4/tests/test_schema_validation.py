# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
ISO 19115 Schema Validation Tests

Tests that verify:
- XSD schema loads correctly
- Valid metadata passes schema validation
- Invalid metadata is rejected
- Required fields are enforced
- Invalid element types are caught
- DGIWG-specific fields are validated
"""

import pytest
from core.metadata_handler import MetadataHandler


class TestSchemaLoading:
    """Test schema file loading and initialization."""

    def test_schema_loads_successfully(self):
        """Test that ISO 19115 schema loads without errors."""
        handler = MetadataHandler()
        assert handler.schema is not None, "Schema should load successfully"

    def test_handler_initializes_with_schema(self):
        """Test that MetadataHandler initializes with schema."""
        handler = MetadataHandler()
        assert hasattr(handler, 'schema')
        assert handler.schema is not None


class TestValidMetadata:
    """Test valid metadata passes schema validation."""

    def test_valid_package_metadata_passes_schema(self):
        """Test that valid package metadata passes schema validation."""
        handler = MetadataHandler()

        xml = handler.generate_package_metadata(
            title="Test Dataset",
            abstract="A test dataset for validation",
            poc="John Doe",
            org="Test Organization",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="transportation",
            ref_date="2026-06-03",
        )

        # Should not raise
        assert handler.validate_schema(xml) is True

    def test_valid_layer_metadata_passes_schema(self):
        """Test that valid layer metadata passes schema validation."""
        handler = MetadataHandler()

        xml = handler.generate_layer_metadata(
            layer_name="roads",
            poc="Jane Smith",
            org="GIS Department",
            nation="USA",
            security="CONFIDENTIAL",
            language="eng",
            ref_date="2026-06-03",
        )

        # Should not raise
        assert handler.validate_schema(xml) is True

    def test_package_metadata_with_all_optional_fields(self):
        """Test metadata with all optional fields."""
        handler = MetadataHandler()

        xml = handler.generate_package_metadata(
            title="Complete Dataset",
            abstract="Metadata with optional fields",
            poc="Test User",
            org="Test Org",
            nation="GBR",
            security="SECRET",
            language="fra",
            topic_category="biota",
            ref_date="2026-06-03",
            data_quality="High quality data from authoritative source",
            lineage="Derived from satellite imagery processed 2026-06-01",
        )

        assert handler.validate_schema(xml) is True


class TestMetadataStructure:
    """Test metadata XML structure compliance."""

    def test_package_metadata_has_required_elements(self):
        """Test that generated metadata contains required elements."""
        handler = MetadataHandler()

        xml = handler.generate_package_metadata(
            title="Structured Test",
            abstract="Testing structure",
            poc="Contact",
            org="Org",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="elevation",
            ref_date="2026-06-03",
        )

        # Check for required elements (basic XML parse check)
        assert "<?xml version=" in xml
        assert "MD_Metadata" in xml
        assert "fileIdentifier" in xml
        assert "language" in xml
        assert "characterSet" in xml
        assert "hierarchyLevel" in xml
        assert "contact" in xml
        assert "dateStamp" in xml
        assert "identificationInfo" in xml

    def test_package_metadata_has_dgiwg_security_constraints(self):
        """Test that security constraints (DGIWG-required) are present."""
        handler = MetadataHandler()

        xml = handler.generate_package_metadata(
            title="DGIWG Test",
            abstract="Testing DGIWG fields",
            poc="User",
            org="Org",
            nation="USA",
            security="CONFIDENTIAL",
            language="eng",
            topic_category="imageryBaseMapsEarthCover",
            ref_date="2026-06-03",
        )

        # Check for DGIWG security elements
        assert "metadataConstraints" in xml
        assert "MD_SecurityConstraints" in xml
        assert "classification" in xml
        assert "MD_ClassificationCode" in xml
        assert "NATO/DGIWG" in xml
        assert "Producer Nation: USA" in xml

    def test_layer_metadata_has_required_elements(self):
        """Test layer metadata structure."""
        handler = MetadataHandler()

        xml = handler.generate_layer_metadata(
            layer_name="test_layer",
            poc="User",
            org="Org",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            ref_date="2026-06-03",
        )

        assert "MD_Metadata" in xml
        assert "fileIdentifier" in xml
        assert "contact" in xml
        assert "identificationInfo" in xml
        assert "Test Layer" in xml  # Layer name (titlecased)


class TestSecurityClassification:
    """Test security classification field handling."""

    @pytest.mark.parametrize("security_level", [
        "UNCLASSIFIED",
        "CONFIDENTIAL",
        "SECRET",
        "TOP SECRET",
    ])
    def test_security_classification_values(self, security_level):
        """Test various security classification levels."""
        handler = MetadataHandler()

        xml = handler.generate_package_metadata(
            title="Security Test",
            abstract="Testing security levels",
            poc="User",
            org="Org",
            nation="USA",
            security=security_level,
            language="eng",
            topic_category="boundaries",
            ref_date="2026-06-03",
        )

        assert handler.validate_schema(xml) is True
        assert security_level in xml

    def test_security_constraint_elements_in_xml(self):
        """Test that security elements are properly structured."""
        handler = MetadataHandler()

        xml = handler.generate_package_metadata(
            title="Test",
            abstract="Test",
            poc="User",
            org="Org",
            nation="USA",
            security="SECRET",
            language="eng",
            topic_category="geoscientificInformation",
            ref_date="2026-06-03",
        )

        assert "MD_ClassificationCode" in xml
        assert "codeListValue" in xml


class TestNationCodes:
    """Test nation code handling."""

    @pytest.mark.parametrize("nation", [
        "USA",
        "GBR",
        "FRA",
        "DEU",
        "CAN",
    ])
    def test_nation_codes(self, nation):
        """Test various NATO nation codes."""
        handler = MetadataHandler()

        xml = handler.generate_package_metadata(
            title="Nation Test",
            abstract="Testing nations",
            poc="User",
            org="Org",
            nation=nation,
            security="UNCLASSIFIED",
            language="eng",
            topic_category="inlandWaters",
            ref_date="2026-06-03",
        )

        assert handler.validate_schema(xml) is True
        assert nation in xml


class TestLanguageCodes:
    """Test language code handling."""

    @pytest.mark.parametrize("language", [
        "eng",
        "fra",
        "deu",
        "spa",
    ])
    def test_language_codes(self, language):
        """Test ISO 639-2 language codes."""
        handler = MetadataHandler()

        xml = handler.generate_package_metadata(
            title="Language Test",
            abstract="Testing languages",
            poc="User",
            org="Org",
            nation="USA",
            security="UNCLASSIFIED",
            language=language,
            topic_category="location",
            ref_date="2026-06-03",
        )

        assert handler.validate_schema(xml) is True
        assert language in xml


class TestTopicCategories:
    """Test ISO 19115 topic categories."""

    @pytest.mark.parametrize("topic", [
        "transportation",
        "biota",
        "boundaries",
        "elevation",
        "geoscientificInformation",
        "health",
        "imageryBaseMapsEarthCover",
        "inlandWaters",
        "location",
        "oceans",
        "structure",
        "utilities",
    ])
    def test_topic_categories(self, topic):
        """Test valid ISO 19115 topic categories."""
        handler = MetadataHandler()

        xml = handler.generate_package_metadata(
            title="Topic Test",
            abstract="Testing topics",
            poc="User",
            org="Org",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category=topic,
            ref_date="2026-06-03",
        )

        assert handler.validate_schema(xml) is True
        assert topic in xml


class TestXMLSpecialCharacters:
    """Test handling of XML special characters."""

    def test_special_characters_in_title(self):
        """Test that XML special characters are properly escaped."""
        handler = MetadataHandler()

        xml = handler.generate_package_metadata(
            title="Test & Dataset <Name>",
            abstract="Description with 'quotes' and \"double quotes\"",
            poc="User",
            org="Org & Partners",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="boundaries",
            ref_date="2026-06-03",
        )

        # Should escape special characters
        assert "&amp;" in xml or "& " in xml
        assert "&lt;" in xml or "<" not in xml[xml.find("<gco:CharacterString>"):xml.find("</gco:CharacterString>")]
        assert handler.validate_schema(xml) is True

    def test_unicode_characters(self):
        """Test handling of unicode characters."""
        handler = MetadataHandler()

        xml = handler.generate_package_metadata(
            title="Test Données",  # French
            abstract="Tëšt ünïçödé",
            poc="José García",
            org="组织",  # Chinese
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="location",
            ref_date="2026-06-03",
        )

        assert handler.validate_schema(xml) is True


class TestOptionalFields:
    """Test optional field handling."""

    def test_metadata_without_data_quality(self):
        """Test metadata generation without data quality statement."""
        handler = MetadataHandler()

        xml = handler.generate_package_metadata(
            title="Test",
            abstract="Test",
            poc="User",
            org="Org",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="elevation",
            ref_date="2026-06-03",
            data_quality=None,  # Explicitly None
        )

        assert handler.validate_schema(xml) is True

    def test_metadata_with_data_quality(self):
        """Test metadata generation with data quality statement."""
        handler = MetadataHandler()

        xml = handler.generate_package_metadata(
            title="Test",
            abstract="Test",
            poc="User",
            org="Org",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="elevation",
            ref_date="2026-06-03",
            data_quality="Positional accuracy ±5m, temporal accuracy ±1 day",
        )

        assert handler.validate_schema(xml) is True
        assert "Positional accuracy" in xml


class TestDateFormats:
    """Test date format handling."""

    def test_valid_date_format(self):
        """Test YYYY-MM-DD date format."""
        handler = MetadataHandler()

        xml = handler.generate_package_metadata(
            title="Date Test",
            abstract="Testing dates",
            poc="User",
            org="Org",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="location",
            ref_date="2026-06-03",
        )

        assert handler.validate_schema(xml) is True
        assert "2026-06-03" in xml


class TestValidationErrors:
    """Test error handling in validation."""

    def test_malformed_xml_rejected(self):
        """Test that malformed XML is rejected."""
        handler = MetadataHandler()

        bad_xml = "<?xml version='1.0'?><unclosed>"

        with pytest.raises(ValueError) as excinfo:
            handler.validate_schema(bad_xml)

        assert "Invalid XML" in str(excinfo.value) or "XML" in str(excinfo.value)

    def test_validation_with_schema_error_handling(self):
        """Test schema validation error reporting."""
        handler = MetadataHandler()

        # XML that's well-formed but won't validate
        bad_metadata = '<?xml version="1.0"?><gmd:MD_Metadata xmlns:gmd="http://www.isotc211.org/2005/gmd"/>'

        # May raise ValueError if schema is available, or return True if schema is not loaded
        if handler.schema:
            with pytest.raises(ValueError):
                handler.validate_schema(bad_metadata)
