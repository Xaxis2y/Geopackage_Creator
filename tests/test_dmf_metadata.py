"""
Tests for the DGIWG DMF metadata record (v0.27.0, validator Req 18).

These tests are GDAL-free: they validate the DMF XML structure that
core.metadata_handler.generate_dmf_metadata() produces against the same
rules the DGIWG GeoPackage Validator applies in its Req 18 check.
"""

import re
import uuid as uuid_mod
import xml.etree.ElementTree as ET

import pytest

from core.metadata_handler import MetadataHandler
from core.config import DMF_STANDARD_URI

NS = {
    "gmd": "http://www.isotc211.org/2005/gmd",
    "gco": "http://www.isotc211.org/2005/gco",
}

DMF_ALLOWED_CHILDREN = {
    "fileIdentifier", "language", "characterSet", "hierarchyLevel",
    "contact", "dateStamp", "identificationInfo", "referenceSystemInfo",
    "distributionInfo", "dataQualityInfo", "metadataConstraints",
    "spatialRepresentationInfo",
}


@pytest.fixture
def dmf_xml():
    handler = MetadataHandler()
    return handler.generate_dmf_metadata(
        title="Test Dataset",
        abstract="Test abstract",
        org="Test Organisation",
        nation="USA",
        security="NATO RESTRICTED",
        language="eng",
        ref_date="2026-06-11",
        releasability="NATO",
    )


class TestDMFStructure:
    def test_well_formed(self, dmf_xml):
        ET.fromstring(dmf_xml)

    def test_root_is_md_metadata(self, dmf_xml):
        root = ET.fromstring(dmf_xml)
        assert root.tag == f"{{{NS['gmd']}}}MD_Metadata"

    def test_only_dmf_allowed_children(self, dmf_xml):
        """Validator XSD uses xs:all - unknown children cause Req 18 FAIL."""
        root = ET.fromstring(dmf_xml)
        for child in root:
            local = child.tag.split("}")[-1]
            assert local in DMF_ALLOWED_CHILDREN, f"forbidden element: {local}"

    def test_mandatory_children_present(self, dmf_xml):
        root = ET.fromstring(dmf_xml)
        present = {c.tag.split("}")[-1] for c in root}
        for req in ("fileIdentifier", "language", "characterSet",
                    "hierarchyLevel", "contact", "dateStamp",
                    "identificationInfo"):
            assert req in present, f"missing mandatory element: {req}"


class TestDMFFieldRules:
    def test_file_identifier_is_uuid(self, dmf_xml):
        root = ET.fromstring(dmf_xml)
        fi = root.find("gmd:fileIdentifier/gco:CharacterString", NS)
        assert fi is not None and fi.text
        uuid_mod.UUID(fi.text)  # raises if not a UUID

    def test_language_is_iso639_2(self, dmf_xml):
        root = ET.fromstring(dmf_xml)
        lang = root.find("gmd:language/gmd:LanguageCode", NS)
        assert lang is not None
        assert re.match(r"^[a-z]{3}$", lang.get("codeListValue"))

    def test_charset_utf8(self, dmf_xml):
        root = ET.fromstring(dmf_xml)
        cs = root.find("gmd:characterSet/gmd:MD_CharacterSetCode", NS)
        assert cs is not None and cs.get("codeListValue") == "utf8"

    def test_hierarchy_level_dataset(self, dmf_xml):
        root = ET.fromstring(dmf_xml)
        hl = root.find("gmd:hierarchyLevel/gmd:MD_ScopeCode", NS)
        assert hl is not None and hl.get("codeListValue") == "dataset"

    def test_contact_org_and_role(self, dmf_xml):
        root = ET.fromstring(dmf_xml)
        org = root.find(".//gmd:organisationName/gco:CharacterString", NS)
        assert org is not None and org.text == "Test Organisation"
        role = root.find(".//gmd:CI_RoleCode", NS)
        assert role is not None and role.get("codeListValue")

    def test_datestamp_iso8601(self, dmf_xml):
        root = ET.fromstring(dmf_xml)
        ds = root.find("gmd:dateStamp/gco:Date", NS)
        assert ds is not None
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", ds.text)

    def test_releasability_written(self, dmf_xml):
        assert "Releasable to: NATO" in dmf_xml

    def test_nato_classification_mapped(self, dmf_xml):
        root = ET.fromstring(dmf_xml)
        cc = root.find(".//gmd:MD_ClassificationCode", NS)
        assert cc is not None and cc.get("codeListValue") == "restricted"


class TestDMFUri:
    def test_uri_recognised_by_validator(self):
        low = DMF_STANDARD_URI.lower()
        assert "dgiwg" in low and "dmf" in low

    def test_xml_escaping(self):
        handler = MetadataHandler()
        xml = handler.generate_dmf_metadata(
            title="A & B <Test>", abstract="x", org="O'Org & Co",
            nation="USA", security="UNCLASSIFIED", language="eng",
            ref_date="2026-06-11")
        ET.fromstring(xml)  # must stay well-formed
