# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
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
    # v0.34.5: DMF 2.0 MDSTD is mandatory (Annex B)
    "metadataStandardName", "metadataStandardVersion",
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


class TestDMFAnnexBMandatory:
    """v0.34.5: the record carries every mandatory Annex B element."""

    def test_mdstd_title_and_version(self, dmf_xml):
        root = ET.fromstring(dmf_xml)
        name = root.find("gmd:metadataStandardName", NS)
        ver = root.find("gmd:metadataStandardVersion/gco:CharacterString", NS)
        assert name is not None and "dmf" in "".join(name.itertext()).lower()
        assert ver is not None and ver.text == "2.0"

    def test_purpose_keywords_lineage_distribution(self, dmf_xml):
        root = ET.fromstring(dmf_xml)
        assert root.find(".//gmd:purpose/gco:CharacterString", NS).text
        assert root.find(".//gmd:descriptiveKeywords//gmd:keyword", NS) is not None
        assert root.find(".//gmd:lineage//gmd:statement/gco:CharacterString", NS).text
        assert root.find(
            ".//gmd:distributionFormat//gmd:name/gco:CharacterString", NS
        ).text == "GeoPackage"

    def test_resource_language_and_date(self, dmf_xml):
        root = ET.fromstring(dmf_xml)
        ident = root.find("gmd:identificationInfo/gmd:MD_DataIdentification", NS)
        assert ident.find("gmd:language/gmd:LanguageCode", NS) is not None
        assert ident.find("gmd:characterSet", NS) is not None
        assert ident.find(".//gmd:CI_Citation/gmd:date//gco:Date", NS).text == "2026-06-11"

    def test_extent_and_crs_when_supplied(self):
        xml = MetadataHandler().generate_dmf_metadata(
            title="T", abstract="A", org="O", nation="USA",
            security="UNCLASSIFIED", language="eng", ref_date="2026-06-11",
            bbox=(-10.0, 20.0, 30.5, 40.25), epsg_codes=[4326])
        root = ET.fromstring(xml)
        assert root.find(".//gmd:westBoundLongitude/gco:Decimal", NS).text.startswith("-10.")
        assert "EPSG/0/4326" in xml

    def test_layer_record_is_full_dmf(self):
        xml = MetadataHandler().generate_dmf_layer_metadata(
            layer_name="roads", org="O", nation="USA",
            security="UNCLASSIFIED", language="eng", ref_date="2026-06-11")
        root = ET.fromstring(xml)
        for tag in ("metadataStandardName", "metadataStandardVersion",
                    "distributionInfo", "dataQualityInfo"):
            assert root.find(f"gmd:{tag}", NS) is not None, tag
        assert root.find(".//gmd:title/gco:CharacterString", NS).text == "roads"

    def test_validates_against_bundled_validator_xsd(self, dmf_xml):
        """The bundled validator's DMF XSD must accept the generated record."""
        lxml_etree = pytest.importorskip("lxml.etree")
        import importlib, sys
        from pathlib import Path
        vdir = Path(__file__).resolve().parents[1] / "DGIWG_GeoPackage_Validator_v1.63"
        src = (vdir / "dgiwg_validator" / "net.py").read_text(encoding="utf-8")
        start = src.index('DMF_XSD_INLINE = """\\\n') + len('DMF_XSD_INLINE = """\\\n')
        xsd = src[start:src.index('"""', start)]
        schema = lxml_etree.XMLSchema(lxml_etree.fromstring(xsd.encode("utf-8")))
        doc = lxml_etree.fromstring(dmf_xml.encode("utf-8"))
        assert schema.validate(doc), schema.error_log
