# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Standalone test suite for ISO 19115 metadata handler.
Does not require GDAL or conftest.py - tests only metadata generation and validation.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import core modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from core.metadata_handler import MetadataHandler


class TestMetadataHandlerBasic:
    """Basic metadata generation tests."""

    @pytest.fixture
    def handler(self):
        """Create a MetadataHandler instance."""
        return MetadataHandler()

    def test_handler_init(self, handler):
        """Test MetadataHandler initialization."""
        assert handler is not None
        assert handler.namespace_map is not None
        assert "gmd" in handler.namespace_map
        assert "gco" in handler.namespace_map

    def test_schema_loading(self, handler):
        """Test that ISO 19115 schema is loaded."""
        # Schema might be None if file not found, but handler should not crash
        assert handler.schema is None or hasattr(handler.schema, 'validate')

    def test_package_metadata_generation(self, handler):
        """Test basic package-level metadata generation."""
        xml = handler.generate_package_metadata(
            title="Test Dataset",
            abstract="Test abstract",
            poc="John Doe",
            org="Test Organization",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="geoscientificInformation",
            ref_date="2026-06-03"
        )

        assert xml is not None
        assert isinstance(xml, str)
        assert "<?xml version" in xml
        assert "<gmd:MD_Metadata" in xml
        assert "Test Dataset" in xml
        assert "Test abstract" in xml

    def test_layer_metadata_generation(self, handler):
        """Test basic layer-level metadata generation."""
        xml = handler.generate_layer_metadata(
            layer_name="test_layer",
            poc="Jane Doe",
            org="Defense Org",
            nation="CAN",
            security="CONFIDENTIAL",
            language="fra",
            ref_date="2026-06-03"
        )

        assert xml is not None
        assert isinstance(xml, str)
        assert "<?xml version" in xml
        assert "<gmd:MD_Metadata" in xml
        assert "Test Layer" in xml  # layer_name is title-cased


class TestSchemaValidation:
    """ISO 19115 XSD schema validation tests."""

    @pytest.fixture
    def handler(self):
        """Create a MetadataHandler instance."""
        return MetadataHandler()

    def test_validate_valid_package_metadata(self, handler):
        """Test validation of valid package metadata."""
        if handler.schema is None:
            pytest.skip("Schema not loaded")

        xml = handler.generate_package_metadata(
            title="Valid Dataset",
            abstract="Valid abstract",
            poc="John Doe",
            org="Test Org",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="geoscientificInformation",
            ref_date="2026-06-03"
        )

        # Should not raise exception
        result = handler.validate_schema(xml)
        assert result is True

    def test_validate_valid_layer_metadata(self, handler):
        """Test validation of valid layer metadata."""
        if handler.schema is None:
            pytest.skip("Schema not loaded")

        xml = handler.generate_layer_metadata(
            layer_name="valid_layer",
            poc="Jane Doe",
            org="Defense Org",
            nation="CAN",
            security="CONFIDENTIAL",
            language="fra",
            ref_date="2026-06-03"
        )

        result = handler.validate_schema(xml)
        assert result is True

    def test_validate_with_data_quality(self, handler):
        """Test validation with optional data quality field."""
        if handler.schema is None:
            pytest.skip("Schema not loaded")

        xml = handler.generate_package_metadata(
            title="Dataset with Quality",
            abstract="Testing data quality",
            poc="John Doe",
            org="Test Org",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="geoscientificInformation",
            ref_date="2026-06-03",
            data_quality="Validated against source"
        )

        result = handler.validate_schema(xml)
        assert result is True

    def test_invalid_xml_syntax(self, handler):
        """Test validation of malformed XML."""
        if handler.schema is None:
            pytest.skip("Schema not loaded")

        invalid_xml = "<invalid>Not well-formed</not>"

        with pytest.raises(ValueError) as exc_info:
            handler.validate_schema(invalid_xml)

        assert "Invalid XML syntax" in str(exc_info.value) or "schema validation" in str(exc_info.value).lower()


class TestXMLWellFormedness:
    """Test XML well-formedness of generated metadata."""

    @pytest.fixture
    def handler(self):
        """Create a MetadataHandler instance."""
        return MetadataHandler()

    def test_package_metadata_well_formed(self, handler):
        """Test that package metadata XML is well-formed."""
        import xml.etree.ElementTree as ET

        xml = handler.generate_package_metadata(
            title="Test Dataset",
            abstract="Test abstract",
            poc="John Doe",
            org="Test Organization",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="geoscientificInformation",
            ref_date="2026-06-03"
        )

        # Should parse without error
        root = ET.fromstring(xml)
        assert root is not None
        assert root.tag.endswith("MD_Metadata")

    def test_layer_metadata_well_formed(self, handler):
        """Test that layer metadata XML is well-formed."""
        import xml.etree.ElementTree as ET

        xml = handler.generate_layer_metadata(
            layer_name="test_layer",
            poc="Jane Doe",
            org="Defense Org",
            nation="CAN",
            security="CONFIDENTIAL",
            language="fra",
            ref_date="2026-06-03"
        )

        # Should parse without error
        root = ET.fromstring(xml)
        assert root is not None
        assert root.tag.endswith("MD_Metadata")

    def test_namespace_preservation(self, handler):
        """Test that XML namespaces are properly preserved."""
        xml = handler.generate_package_metadata(
            title="Test Dataset",
            abstract="Test abstract",
            poc="John Doe",
            org="Test Organization",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="geoscientificInformation",
            ref_date="2026-06-03"
        )

        # Check that namespaces are declared
        assert 'xmlns:gmd="http://www.isotc211.org/2005/gmd"' in xml
        assert 'xmlns:gco="http://www.isotc211.org/2005/gco"' in xml


class TestSecurityClassifications:
    """Test support for various security classifications."""

    @pytest.fixture
    def handler(self):
        """Create a MetadataHandler instance."""
        return MetadataHandler()

    @pytest.mark.parametrize("security_level", [
        "UNCLASSIFIED",
        "CONFIDENTIAL",
        "SECRET",
        "TOP SECRET",
    ])
    def test_security_levels(self, handler, security_level):
        """Test support for various NATO/DGIWG security classifications."""
        xml = handler.generate_package_metadata(
            title="Test Dataset",
            abstract="Test abstract",
            poc="John Doe",
            org="Test Organization",
            nation="USA",
            security=security_level,
            language="eng",
            topic_category="geoscientificInformation",
            ref_date="2026-06-03"
        )

        assert xml is not None
        # Security level should appear in metadata
        assert security_level in xml or security_level.replace(" ", "_") in xml or "classified" in xml.lower()


class TestLanguageSupport:
    """Test support for multiple languages."""

    @pytest.fixture
    def handler(self):
        """Create a MetadataHandler instance."""
        return MetadataHandler()

    @pytest.mark.parametrize("language_code", [
        "eng",  # English
        "fra",  # French
        "deu",  # German
        "spa",  # Spanish
    ])
    def test_language_codes(self, handler, language_code):
        """Test support for various ISO 639-2 language codes."""
        xml = handler.generate_package_metadata(
            title="Test Dataset",
            abstract="Test abstract",
            poc="John Doe",
            org="Test Organization",
            nation="USA",
            security="UNCLASSIFIED",
            language=language_code,
            topic_category="geoscientificInformation",
            ref_date="2026-06-03"
        )

        assert xml is not None
        assert language_code in xml


class TestSpecialCharacters:
    """Test handling of special characters in metadata fields."""

    @pytest.fixture
    def handler(self):
        """Create a MetadataHandler instance."""
        return MetadataHandler()

    def test_special_characters_in_title(self, handler):
        """Test handling of special XML characters in title."""
        xml = handler.generate_package_metadata(
            title="Dataset <with> & special \"chars\"",
            abstract="Test abstract",
            poc="John Doe",
            org="Test Organization",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="geoscientificInformation",
            ref_date="2026-06-03"
        )

        assert xml is not None
        # Should still be well-formed
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)
        assert root is not None

    def test_special_characters_in_abstract(self, handler):
        """Test handling of special characters in abstract."""
        xml = handler.generate_package_metadata(
            title="Test Dataset",
            abstract="This dataset includes 'quotes' & <xml> tags",
            poc="John Doe",
            org="Test Organization",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="geoscientificInformation",
            ref_date="2026-06-03"
        )

        assert xml is not None
        # Should be well-formed despite special characters
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)
        assert root is not None


class TestUUIDGeneration:
    """Test UUID generation in metadata."""

    @pytest.fixture
    def handler(self):
        """Create a MetadataHandler instance."""
        return MetadataHandler()

    def test_unique_file_identifiers(self, handler):
        """Test that fileIdentifier is unique per generation."""
        xml1 = handler.generate_package_metadata(
            title="Test Dataset",
            abstract="Test abstract",
            poc="John Doe",
            org="Test Organization",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="geoscientificInformation",
            ref_date="2026-06-03"
        )

        xml2 = handler.generate_package_metadata(
            title="Test Dataset",
            abstract="Test abstract",
            poc="John Doe",
            org="Test Organization",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="geoscientificInformation",
            ref_date="2026-06-03"
        )

        # Extract UUIDs
        import re
        uuid_pattern = r"<gco:CharacterString>([a-f0-9\-]{36})</gco:CharacterString>"
        uuids1 = re.findall(uuid_pattern, xml1)
        uuids2 = re.findall(uuid_pattern, xml2)

        # Should have at least one UUID (fileIdentifier)
        assert len(uuids1) > 0
        assert len(uuids2) > 0

        # First UUID (fileIdentifier) should be different
        assert uuids1[0] != uuids2[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
