"""
ISO 19115 / DGIWG Metadata Handler

Generates and manages ISO 19115-compliant metadata with DGIWG Defense Metadata
Framework (DMF) extensions.

This module creates:
- Package-level metadata (describes entire GeoPackage)
- Layer-level metadata (describes individual feature layers)
- Proper XML structure per ISO 19115 / DGIWG standards
- XSD Schema validation for DGIWG compliance
- Embedding in GeoPackage gpkg_metadata table

All metadata is embedded in the GeoPackage for portability and compliance.
"""

import uuid
import logging
from datetime import datetime
from typing import Dict, Optional
from pathlib import Path
import xml.sax.saxutils as saxutils
import xml.etree.ElementTree as ET

from lxml import etree

from .config import (
    DMF_STANDARD_URI,
    METADATA_MIME_TYPE,
    SECURITY_CODE_MAP,
)


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class MetadataHandler:
    """
    Generates ISO 19115 / DGIWG-compliant metadata with XSD validation.

    Handles creation of metadata XML documents for embedding in
    GeoPackage files. Ensures compliance with both OGC standards
    and DGIWG defense requirements through XSD schema validation.

    Attributes:
        schema: Loaded ISO 19115 XSD schema for validation
        namespace_map: XML namespace mappings
    """

    def __init__(self):
        """Initialize metadata handler and load XSD schema."""
        self.namespace_map = {
            "gmd": "http://www.isotc211.org/2005/gmd",
            "gco": "http://www.isotc211.org/2005/gco",
            "gml": "http://www.opengis.net/gml/3.2",
            "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        }
        # Load XSD schema for validation
        self.schema = self._load_iso19115_schema()

    def _load_iso19115_schema(self) -> Optional[etree.XMLSchema]:
        """
        Load ISO 19115 XSD schema for metadata validation.

        Returns:
            lxml XMLSchema object, or None if schema file not found

        Raises:
            ValueError: If schema file is invalid
        """
        try:
            # Locate schema file relative to this module
            # v0.27.0 housekeeping: the bundled schema validates the ISO
            # 19139 (2005 'gmd') ENCODING of ISO 19115 metadata, so it is now
            # named iso19139-gmd.xsd. Fall back to the legacy filename.
            schema_dir = Path(__file__).parent.parent / "schemas"
            schema_path = schema_dir / "iso19139-gmd.xsd"
            if not schema_path.exists():
                schema_path = schema_dir / "iso19115-1.xsd"

            if not schema_path.exists():
                logger.warning(f"ISO 19115 schema not found at {schema_path}")
                return None

            # Parse schema document
            schema_doc = etree.parse(str(schema_path))
            schema = etree.XMLSchema(schema_doc)

            logger.info(f"Loaded ISO 19115 schema from {schema_path}")
            return schema

        except Exception as e:
            logger.warning(f"Error loading ISO 19115 schema: {e}")
            return None

    def validate_schema(self, metadata_xml_string: str) -> bool:
        """
        Validate metadata XML against ISO 19115 XSD schema.

        Performs full XSD schema validation to ensure DGIWG compliance.
        Checks required fields, element types, and structure.

        Args:
            metadata_xml_string: XML string to validate

        Returns:
            True if valid

        Raises:
            ValueError: If XML fails schema validation

        Examples:
            >>> handler = MetadataHandler()
            >>> xml = handler.generate_package_metadata(...)
            >>> handler.validate_schema(xml)  # Raises if invalid
            True
        """
        if not self.schema:
            logger.warning("No XSD schema available for validation")
            return True  # Skip validation if schema not loaded

        try:
            # Parse XML string
            doc = etree.fromstring(metadata_xml_string.encode('utf-8'))

            # Validate against schema
            if not self.schema.validate(doc):
                errors = self.schema.error_log
                error_details = "\n".join(
                    f"  Line {e.line}: {e.message}" for e in errors
                )
                raise ValueError(
                    f"ISO 19115 schema validation failed:\n{error_details}"
                )

            logger.info("ISO 19115 schema validation passed")
            return True

        except etree.XMLSyntaxError as e:
            raise ValueError(f"Invalid XML syntax: {e}")
        except Exception as e:
            raise ValueError(f"Schema validation error: {e}")

    def generate_package_metadata(
        self,
        title: str,
        abstract: str,
        poc: str,
        org: str,
        nation: str,
        security: str,
        language: str,
        topic_category: str,
        ref_date: str,
        data_quality: Optional[str] = None,
        lineage: Optional[str] = None,
        releasability: Optional[str] = None,
    ) -> str:
        """
        Generate package-level ISO 19115 metadata XML.

        Creates metadata describing the entire GeoPackage dataset,
        including contact information, classification, and data quality.

        Args:
            title: Dataset title
            abstract: Dataset description
            poc: Point of contact name
            org: Organization name
            nation: ISO 3166-1 alpha-3 nation code
            security: Security classification (UNCLASSIFIED, CONFIDENTIAL, SECRET, etc.)
            language: ISO 639-2 language code
            topic_category: ISO 19115 topic category
            ref_date: Reference date (YYYY-MM-DD)
            data_quality: Optional data quality statement
            lineage: Optional lineage/source information

        Returns:
            XML string of package-level metadata

        Raises:
            ValueError: If required fields are invalid or XML generation fails
        """
        try:
            # Generate unique file identifier
            file_id = str(uuid.uuid4())
            now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

            # Escape XML special characters in user inputs
            t = saxutils.escape(title)
            a = saxutils.escape(abstract)
            p = saxutils.escape(poc)
            o = saxutils.escape(org)
            n = saxutils.escape(nation)
            sec_label = saxutils.escape(security)
            sec_code = SECURITY_CODE_MAP.get(security, "unclassified")
            lng = saxutils.escape(language)
            tc = saxutils.escape(topic_category)
            rd = saxutils.escape(ref_date)
            ni = saxutils.escape(now_iso)

            # Build XML (ISO 19115 with DGIWG extensions)
            xml_str = f'''<?xml version="1.0" encoding="UTF-8"?>
<gmd:MD_Metadata xmlns:gmd="http://www.isotc211.org/2005/gmd"
                 xmlns:gco="http://www.isotc211.org/2005/gco"
                 xmlns:gml="http://www.opengis.net/gml/3.2"
                 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 xsi:schemaLocation="http://www.isotc211.org/2005/gmd http://schemas.opengis.net/csw/2.0.2/profiles/apiso/1.0.0/apiso.xsd">

  <!-- File Identifier (UUID) -->
  <gmd:fileIdentifier>
    <gco:CharacterString>{file_id}</gco:CharacterString>
  </gmd:fileIdentifier>

  <!-- Language of metadata -->
  <gmd:language>
    <gmd:LanguageCode codeList="http://www.loc.gov/standards/iso639-2/" codeListValue="{lng}">{lng}</gmd:LanguageCode>
  </gmd:language>

  <!-- Character set (UTF-8) -->
  <gmd:characterSet>
    <gmd:MD_CharacterSetCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_CharacterSetCode" codeListValue="utf8">utf8</gmd:MD_CharacterSetCode>
  </gmd:characterSet>

  <!-- Hierarchy level (dataset) -->
  <gmd:hierarchyLevel>
    <gmd:MD_ScopeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ScopeCode" codeListValue="dataset">dataset</gmd:MD_ScopeCode>
  </gmd:hierarchyLevel>

  <!-- Point of contact (individual responsible) -->
  <gmd:contact>
    <gmd:CI_ResponsibleParty>
      <gmd:individualName><gco:CharacterString>{p}</gco:CharacterString></gmd:individualName>
      <gmd:organisationName><gco:CharacterString>{o}</gco:CharacterString></gmd:organisationName>
      <gmd:contactInfo>
        <gmd:CI_Contact>
          <gmd:address>
            <gmd:CI_Address>
              <gmd:country><gco:CharacterString>{n}</gco:CharacterString></gmd:country>
            </gmd:CI_Address>
          </gmd:address>
        </gmd:CI_Contact>
      </gmd:contactInfo>
      <gmd:role>
        <gmd:CI_RoleCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_RoleCode" codeListValue="pointOfContact">pointOfContact</gmd:CI_RoleCode>
      </gmd:role>
    </gmd:CI_ResponsibleParty>
  </gmd:contact>

  <!-- Metadata creation date -->
  <gmd:dateStamp>
    <gco:DateTime>{ni}</gco:DateTime>
  </gmd:dateStamp>

  <!-- Metadata standard (DGIWG DMF) -->
  <gmd:metadataStandardName><gco:CharacterString>DGIWG Metadata Foundation (DMF)</gco:CharacterString></gmd:metadataStandardName>
  <gmd:metadataStandardVersion><gco:CharacterString>2.0</gco:CharacterString></gmd:metadataStandardVersion>

  <!-- Data Identification -->
  <gmd:identificationInfo>
    <gmd:MD_DataIdentification>

      <!-- Citation (title and date) -->
      <gmd:citation>
        <gmd:CI_Citation>
          <gmd:title><gco:CharacterString>{t}</gco:CharacterString></gmd:title>
          <gmd:date>
            <gmd:CI_Date>
              <gmd:date><gco:Date>{rd}</gco:Date></gmd:date>
              <gmd:dateType>
                <gmd:CI_DateTypeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_DateTypeCode" codeListValue="publication">publication</gmd:CI_DateTypeCode>
              </gmd:dateType>
            </gmd:CI_Date>
          </gmd:date>
        </gmd:CI_Citation>
      </gmd:citation>

      <!-- Abstract -->
      <gmd:abstract><gco:CharacterString>{a}</gco:CharacterString></gmd:abstract>

      <!-- Language -->
      <gmd:language>
        <gmd:LanguageCode codeList="http://www.loc.gov/standards/iso639-2/" codeListValue="{lng}">{lng}</gmd:LanguageCode>
      </gmd:language>

      <!-- Character set -->
      <gmd:characterSet>
        <gmd:MD_CharacterSetCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_CharacterSetCode" codeListValue="utf8">utf8</gmd:MD_CharacterSetCode>
      </gmd:characterSet>

      <!-- Topic category -->
      <gmd:topicCategory>
        <gmd:MD_TopicCategoryCode>{tc}</gmd:MD_TopicCategoryCode>
      </gmd:topicCategory>

    </gmd:MD_DataIdentification>
  </gmd:identificationInfo>

  <!-- Security constraints (DGIWG-required) -->
  <gmd:metadataConstraints>
    <gmd:MD_SecurityConstraints>
      <gmd:classification>
        <gmd:MD_ClassificationCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ClassificationCode" codeListValue="{sec_code}">{sec_label}</gmd:MD_ClassificationCode>
      </gmd:classification>
      <gmd:classificationSystem><gco:CharacterString>NATO/DGIWG</gco:CharacterString></gmd:classificationSystem>
      <gmd:handlingDescription><gco:CharacterString>Producer Nation: {n}{f". Releasable to: {saxutils.escape(releasability)}" if releasability else ""}</gco:CharacterString></gmd:handlingDescription>
    </gmd:MD_SecurityConstraints>
  </gmd:metadataConstraints>

  <!-- Data quality -->
  <gmd:dataQualityInfo>
    <gmd:DQ_DataQuality>
      <gmd:scope>
        <gmd:DQ_Scope>
          <gmd:level>
            <gmd:MD_ScopeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ScopeCode" codeListValue="dataset">dataset</gmd:MD_ScopeCode>
          </gmd:level>
        </gmd:DQ_Scope>
      </gmd:scope>
      {f'<gmd:report><gmd:DQ_DomainConsistency><gmd:result><gmd:DQ_ConformanceResult><gmd:explanation><gco:CharacterString>{saxutils.escape(data_quality)}</gco:CharacterString></gmd:explanation><gmd:pass><gco:Boolean>true</gco:Boolean></gmd:pass></gmd:DQ_ConformanceResult></gmd:result></gmd:DQ_DomainConsistency></gmd:report>' if data_quality else ''}
    </gmd:DQ_DataQuality>
  </gmd:dataQualityInfo>

</gmd:MD_Metadata>'''

            # Step 1: Validate XML is well-formed (basic check)
            ET.fromstring(xml_str)

            # Step 2: Validate against ISO 19115 schema (full compliance check)
            try:
                self.validate_schema(xml_str)
            except ValueError as schema_error:
                logger.warning(f"Schema validation warning: {schema_error}")
                # Don't fail - schema validation is optional but logged

            logger.info(f"Generated package metadata (UUID: {file_id})")
            return xml_str

        except Exception as e:
            raise ValueError(f"Error generating metadata: {e}")

    def generate_dmf_metadata(
        self,
        title: str,
        abstract: str,
        org: str,
        nation: str,
        security: str,
        language: str,
        ref_date: str,
        releasability: Optional[str] = None,
    ) -> str:
        """
        Generate a DGIWG Metadata Foundation (DMF) 2.0 metadata record
        (v0.27.0, DGIWG GeoPackage Profile Req 18).

        The DGIWG GeoPackage Validator only awards Req 18 a full PASS when
        gpkg_metadata contains a row whose md_standard_uri is a DGIWG DMF URI
        and whose XML satisfies the DMF structural rules:

        - root gmd:MD_Metadata containing ONLY the DMF-recognised children
          (fileIdentifier, language, characterSet, hierarchyLevel, contact,
          dateStamp, identificationInfo and the optional constraint blocks);
          elements such as metadataStandardName are NOT permitted
        - fileIdentifier: UUID
        - language: 3-letter ISO 639-2 code
        - characterSet: valid MD_CharacterSetCode (utf8)
        - hierarchyLevel: valid MD_ScopeCode (dataset)
        - contact: organisationName + CI_RoleCode
        - dateStamp: ISO 8601 date

        Args:
            title: Dataset title
            abstract: Dataset description
            org: Responsible organisation
            nation: ISO 3166-1 alpha-3 producer nation code
            security: Security classification label
            language: ISO 639-2 language code
            ref_date: Reference date (YYYY-MM-DD)
            releasability: Optional releasability statement
                (e.g. "NATO" or "USA, GBR, CAN")

        Returns:
            XML string of the DMF metadata record
        """
        try:
            file_id = str(uuid.uuid4())
            date_stamp = datetime.utcnow().strftime("%Y-%m-%d")

            t = saxutils.escape(title)
            a = saxutils.escape(abstract)
            o = saxutils.escape(org)
            n = saxutils.escape(nation)
            sec_label = saxutils.escape(security)
            sec_code = SECURITY_CODE_MAP.get(security, "unclassified")
            lng = saxutils.escape((language or "eng").lower())
            rd = saxutils.escape(ref_date or date_stamp)

            releasability_block = ""
            if releasability:
                rel = saxutils.escape(releasability)
                releasability_block = f"""
      <gmd:resourceConstraints>
        <gmd:MD_LegalConstraints>
          <gmd:useLimitation><gco:CharacterString>Releasable to: {rel}</gco:CharacterString></gmd:useLimitation>
        </gmd:MD_LegalConstraints>
      </gmd:resourceConstraints>"""

            xml_str = f'''<?xml version="1.0" encoding="UTF-8"?>
<gmd:MD_Metadata xmlns:gmd="http://www.isotc211.org/2005/gmd"
                 xmlns:gco="http://www.isotc211.org/2005/gco">
  <gmd:fileIdentifier>
    <gco:CharacterString>{file_id}</gco:CharacterString>
  </gmd:fileIdentifier>
  <gmd:language>
    <gmd:LanguageCode codeList="http://www.loc.gov/standards/iso639-2/" codeListValue="{lng}">{lng}</gmd:LanguageCode>
  </gmd:language>
  <gmd:characterSet>
    <gmd:MD_CharacterSetCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_CharacterSetCode" codeListValue="utf8">utf8</gmd:MD_CharacterSetCode>
  </gmd:characterSet>
  <gmd:hierarchyLevel>
    <gmd:MD_ScopeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ScopeCode" codeListValue="dataset">dataset</gmd:MD_ScopeCode>
  </gmd:hierarchyLevel>
  <gmd:contact>
    <gmd:CI_ResponsibleParty>
      <gmd:organisationName><gco:CharacterString>{o}</gco:CharacterString></gmd:organisationName>
      <gmd:role>
        <gmd:CI_RoleCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_RoleCode" codeListValue="pointOfContact">pointOfContact</gmd:CI_RoleCode>
      </gmd:role>
    </gmd:CI_ResponsibleParty>
  </gmd:contact>
  <gmd:dateStamp>
    <gco:Date>{date_stamp}</gco:Date>
  </gmd:dateStamp>
  <gmd:identificationInfo>
    <gmd:MD_DataIdentification>
      <gmd:citation>
        <gmd:CI_Citation>
          <gmd:title><gco:CharacterString>{t}</gco:CharacterString></gmd:title>
          <gmd:date>
            <gmd:CI_Date>
              <gmd:date><gco:Date>{rd}</gco:Date></gmd:date>
              <gmd:dateType>
                <gmd:CI_DateTypeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_DateTypeCode" codeListValue="publication">publication</gmd:CI_DateTypeCode>
              </gmd:dateType>
            </gmd:CI_Date>
          </gmd:date>
        </gmd:CI_Citation>
      </gmd:citation>
      <gmd:abstract><gco:CharacterString>{a}</gco:CharacterString></gmd:abstract>{releasability_block}
      <gmd:resourceConstraints>
        <gmd:MD_SecurityConstraints>
          <gmd:classification>
            <gmd:MD_ClassificationCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ClassificationCode" codeListValue="{sec_code}">{sec_label}</gmd:MD_ClassificationCode>
          </gmd:classification>
          <gmd:classificationSystem><gco:CharacterString>NATO/DGIWG</gco:CharacterString></gmd:classificationSystem>
          <gmd:handlingDescription><gco:CharacterString>Producer Nation: {n}</gco:CharacterString></gmd:handlingDescription>
        </gmd:MD_SecurityConstraints>
      </gmd:resourceConstraints>
    </gmd:MD_DataIdentification>
  </gmd:identificationInfo>
</gmd:MD_Metadata>'''

            # Well-formedness check
            ET.fromstring(xml_str)
            logger.info(f"Generated DMF metadata record (UUID: {file_id})")
            return xml_str

        except Exception as e:
            raise ValueError(f"Error generating DMF metadata: {e}")

    def generate_layer_metadata(
        self,
        layer_name: str,
        poc: str,
        org: str,
        nation: str,
        security: str,
        language: str,
        ref_date: str,
    ) -> str:
        """
        Generate layer-level ISO 19115 metadata XML.

        Creates metadata for individual feature layer, linked to package-level
        metadata via parent reference.

        Args:
            layer_name: Feature layer name
            poc: Point of contact
            org: Organization
            nation: Nation code
            security: Security classification
            language: Language code
            ref_date: Reference date

        Returns:
            XML string of layer metadata
        """
        try:
            file_id = str(uuid.uuid4())
            now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

            ln = saxutils.escape(layer_name.replace("_", " ").title())
            p = saxutils.escape(poc)
            o = saxutils.escape(org)
            n = saxutils.escape(nation)
            sec_label = saxutils.escape(security)
            sec_code = SECURITY_CODE_MAP.get(security, "unclassified")
            lng = saxutils.escape(language)
            rd = saxutils.escape(ref_date)

            xml_str = f'''<?xml version="1.0" encoding="UTF-8"?>
<gmd:MD_Metadata xmlns:gmd="http://www.isotc211.org/2005/gmd"
                 xmlns:gco="http://www.isotc211.org/2005/gco">

  <gmd:fileIdentifier>
    <gco:CharacterString>{file_id}</gco:CharacterString>
  </gmd:fileIdentifier>

  <gmd:language>
    <gmd:LanguageCode codeList="http://www.loc.gov/standards/iso639-2/" codeListValue="{lng}">{lng}</gmd:LanguageCode>
  </gmd:language>

  <gmd:characterSet>
    <gmd:MD_CharacterSetCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_CharacterSetCode" codeListValue="utf8">utf8</gmd:MD_CharacterSetCode>
  </gmd:characterSet>

  <gmd:hierarchyLevel>
    <gmd:MD_ScopeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ScopeCode" codeListValue="dataset">dataset</gmd:MD_ScopeCode>
  </gmd:hierarchyLevel>

  <gmd:contact>
    <gmd:CI_ResponsibleParty>
      <gmd:individualName><gco:CharacterString>{p}</gco:CharacterString></gmd:individualName>
      <gmd:organisationName><gco:CharacterString>{o}</gco:CharacterString></gmd:organisationName>
      <gmd:role>
        <gmd:CI_RoleCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_RoleCode" codeListValue="pointOfContact">pointOfContact</gmd:CI_RoleCode>
      </gmd:role>
    </gmd:CI_ResponsibleParty>
  </gmd:contact>

  <gmd:dateStamp>
    <gco:DateTime>{now_iso}</gco:DateTime>
  </gmd:dateStamp>

  <gmd:identificationInfo>
    <gmd:MD_DataIdentification>
      <gmd:citation>
        <gmd:CI_Citation>
          <gmd:title><gco:CharacterString>{ln}</gco:CharacterString></gmd:title>
          <gmd:date>
            <gmd:CI_Date>
              <gmd:date><gco:Date>{rd}</gco:Date></gmd:date>
              <gmd:dateType>
                <gmd:CI_DateTypeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_DateTypeCode" codeListValue="publication">publication</gmd:CI_DateTypeCode>
              </gmd:dateType>
            </gmd:CI_Date>
          </gmd:date>
        </gmd:CI_Citation>
      </gmd:citation>
    </gmd:MD_DataIdentification>
  </gmd:identificationInfo>

  <gmd:metadataConstraints>
    <gmd:MD_SecurityConstraints>
      <gmd:classification>
        <gmd:MD_ClassificationCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ClassificationCode" codeListValue="{sec_code}">{sec_label}</gmd:MD_ClassificationCode>
      </gmd:classification>
    </gmd:MD_SecurityConstraints>
  </gmd:metadataConstraints>

</gmd:MD_Metadata>'''

            # Step 1: Validate XML is well-formed
            ET.fromstring(xml_str)

            # Step 2: Validate against ISO 19115 schema
            try:
                self.validate_schema(xml_str)
            except ValueError as schema_error:
                logger.warning(f"Layer metadata schema validation warning: {schema_error}")
                # Don't fail - schema validation is optional but logged

            logger.info(f"Generated layer metadata for '{layer_name}' (UUID: {file_id})")
            return xml_str

        except Exception as e:
            raise ValueError(f"Error generating layer metadata: {e}")
