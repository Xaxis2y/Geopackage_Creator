# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
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

Module version: v0.30.10


THREAD SAFETY (v0.30.10 - CRASH FIX)
------------------------------------
Everything in this module that touches lxml is serialized through one
process-wide re-entrant lock, `_LXML_LOCK`, and the compiled XSD is built
exactly once into a module-level singleton.

Why. The v0.30.9 test run died with a hard "Windows fatal exception: access
violation" inside `validate_schema()` at the `etree.fromstring()` call. The
faulting thread had already finished all of its GDAL work - the GeoPackage was
closed at converter.py:574 - and the other two worker threads were parked at
converter.py:109 waiting on the global conversion lock. GDAL serialization was
therefore working exactly as designed, and the crash was NOT a GDAL crash. It
was libxml2.

The hole was in this file. `MetadataHandler.__init__` called
`_load_iso19115_schema()`, which ran `etree.parse()` followed by
`etree.XMLSchema()` on every single instantiation. `GeoPackageConverter.__init__`
(converter.py:217) constructs a `MetadataHandler`, and the converter is
constructed INSIDE each worker thread - before `convert()` is called, so
outside the `_serialize_conversions` lock that protects everything else. Three
threads therefore compiled the XSD simultaneously.

Compiling an XML Schema is the single least thread-safe thing in libxml2.
`xmlSchemaParse()` populates and interns into shared string dictionaries, wires
up the global structured-error handler and resolves imports/includes through
shared caches. Two of those running at once corrupts the heap. Heap corruption
does not fault where it happens - it faults at the next allocation from the
same arena, which here was the `etree.fromstring()` a few hundred microseconds
later, in whichever thread got there first. That is precisely the shape of the
reported traceback.

The fix has three parts:

1. `_get_shared_schema()` compiles the XSD once, under `_LXML_LOCK`, and every
   `MetadataHandler` reuses that one object. The race window is closed rather
   than narrowed, because the second and third callers never enter
   `etree.XMLSchema()` at all. It is also a straight performance win: the XSD
   was previously re-parsed for every converter ever built.

2. `validate_schema()` holds `_LXML_LOCK` across the whole parse-validate-read
   -error_log sequence. An `lxml` `XMLSchema` object is explicitly documented as
   NOT safe for concurrent `.validate()` calls, and `schema.error_log` is
   mutable state living ON that shared object - two threads validating at once
   would interleave their error lists even if libxml2 did not fault. Holding
   the lock across all three steps makes the reported errors belong to the
   document that was just validated.

3. Parsing is done with an explicit, hardened parser (`no_network=True`,
   `resolve_entities=False`) rather than lxml's implicit default parser. This
   removes one more piece of shared mutable state from the picture and, for a
   tool that validates metadata for defense customers, closes XXE and
   billion-laughs as a side effect.

The stdlib `xml.etree.ElementTree.fromstring()` well-formedness checks are left
unlocked on purpose. Those run on expat, each call builds its own independent
parser, and they share nothing with libxml2.

Cost of serializing. Schema validation of a ~4 KB metadata document is on the
order of a millisecond; a conversion is seconds to minutes. The lock is
uncontended in the shipped GUI and CLI, which never run two conversions at
once, and is noise even in the 3-thread test.


LIBXML2 ABI FAIL-FAST GUARD (v0.30.13 - ROOT CAUSE CONFIRMED)
--------------------------------------------------------------
v0.30.10 fixed a real thread-safety hole, but the 2026-08-04 access violation
kept reproducing afterward - including single-threaded, with no race
involved. `diagnose_crash_v0.30.11.py` and `diagnose_crash_v0.30.12.py`
bisected the actual cause with two subprocess-isolated experiments:

    heavy_no_lxml     the full GDALHandler + sqlite3-embedding + DGIWG
                      finalization pipeline, with lxml touched ZERO times
                      anywhere in the process              -> clean 5/5

    gdal_then_schema  ~20 lines, no project code: compile the bundled XSD via
                      `etree.XMLSchema()`, perform ONE GDAL vector write via
                      plain osgeo calls, then make any further lxml call
                                                              -> CRASHED 5/5,
                      identical Windows access violation every time, at the
                      first lxml call after the write

Same machine, same GDAL build, only variable was whether lxml compiled a
schema before a GDAL write happened in the same process. That is dispositive:
the fault requires lxml, and does not require anything specific to this
project's conversion pipeline beyond "a GDAL write happened."

The environment's `dll_map` fingerprint explains why:

    LIBXML_COMPILED_VERSION : (2, 14, 6)   <- what this lxml build expects
    LIBXML_VERSION (runtime): (2, 15, 3)   <- the libxml2.dll actually loaded

Exactly one libxml2 image is mapped into the process - GDAL and lxml share
it, they are not fighting over two separate copies. But lxml's compiled
extension was built against 2.14.6's internal structure layouts, and the DLL
resolved at runtime is 2.15.3. Windows does not enforce ABI compatibility at
load time the way a strict soname check would; the mismatched DLL loads and
runs right up until something dereferences a structure whose layout changed,
which is what a GDAL write reliably provokes.

GDAL's own version was independently ruled out as the variable - this
reproduced under GDAL 3.13.1, and the project has since moved its tested pin
to 3.13.2 (see core/config.py GDAL_TESTED_VERSION) purely as a support
decision. It is NOT a fix for this crash; the libxml2 ABI mismatch is
orthogonal to which GDAL patch version is installed, and would reproduce
under either.

Because this is an environment defect the code cannot repair, the correct
in-process behaviour is to refuse the dangerous operation loudly rather than
let it corrupt memory silently. `_verify_libxml2_abi()` runs immediately
before the ONE operation proven to set up the fault - compiling the XSD - and
raises `RuntimeError` with the exact remediation steps unless
`config.ALLOW_LIBXML_ABI_MISMATCH` has been explicitly set `True` by someone
who has verified their specific combination is safe. A clear exception before
any conversion starts is a strictly better failure mode than an opaque native
crash minutes in, or during interpreter shutdown with no Python traceback at
all - which is what every user of this tool got until this version.
"""

import uuid
import logging
import threading
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


__version__ = "0.30.13"


# ---------------------------------------------------------------------------
# Process-wide lxml serialization (v0.30.10 - see module docstring)
# ---------------------------------------------------------------------------
#
# Re-entrant, because `generate_package_metadata()` calls `validate_schema()`
# and a future caller may reasonably want to hold the lock across several
# validations without deadlocking itself.
_LXML_LOCK = threading.RLock()

# The one compiled XSD for the whole process. `_SCHEMA_LOADED` is a separate
# flag rather than a `None` check on `_SHARED_SCHEMA`, because "no schema file
# on disk" is a legitimate, cacheable outcome that must resolve to None exactly
# once instead of re-walking the filesystem on every MetadataHandler built.
_SHARED_SCHEMA: Optional[etree.XMLSchema] = None
_SCHEMA_LOADED: bool = False
_SCHEMA_SOURCE_PATH: Optional[Path] = None


def lxml_lock() -> threading.RLock:
    """Return the process-wide lxml lock.

    Exposed so that callers who reach into lxml directly - a custom validator,
    a report generator that pretty-prints an XML tree - can serialize against
    this module rather than racing it. Anything in this process that calls into
    libxml2 from more than one thread should hold this.

    Returns:
        The module-level `threading.RLock` guarding all libxml2 access.
    """
    return _LXML_LOCK


def _build_hardened_parser() -> etree.XMLParser:
    """Return a fresh, hardened lxml parser.

    Built per call rather than cached: an `XMLParser` carries mutable state
    (its own error log, and the tree it is currently building), so a shared one
    is another thread-safety hazard of exactly the kind this release removes.
    Construction is cheap relative to the parse that follows.

    Hardening:
        no_network=True        - never fetch a DTD or schema over the wire
        resolve_entities=False - no entity expansion, which closes both XXE
                                 (file:// disclosure) and the billion-laughs
                                 expansion DoS
        huge_tree=False        - keep libxml2's depth/size guards armed

    Returns:
        A new `etree.XMLParser` instance.
    """
    return etree.XMLParser(
        no_network=True,
        resolve_entities=False,
        huge_tree=False,
    )


def _verify_libxml2_abi() -> None:
    """Raise if lxml was compiled against a different libxml2 than it loaded.

    v0.30.13. Confirmed root cause of the 2026-08-04/05 access violations -
    see the module docstring's "LIBXML2 ABI FAIL-FAST GUARD" section for the
    full evidence trail (dev_tools/diagnose_crash_v0.30.11.py / _v0.30.12.py,
    changelogs/CHANGELOG_v0.30.13.md). In summary: `heavy_no_lxml` (full conversion
    pipeline, lxml touched zero times) ran clean 5/5; `gdal_then_schema`
    (~20 lines, no project code: compile an XSD via lxml, do one GDAL vector
    write, touch lxml again) crashed 5/5 with an identical access violation.
    Same machine, same GDAL build - only variable was lxml involvement.

    Deliberately NOT cached the way the compiled schema is. A tuple
    comparison costs nothing, and caching a "checked" flag independently of
    `_SCHEMA_LOADED` would let a caller who retries after catching the
    `RuntimeError` slip through on the second attempt - defeating the guard
    on exactly the retry path most likely to happen in practice.

    Raises:
        RuntimeError: if the compiled and runtime libxml2 versions differ and
            `config.ALLOW_LIBXML_ABI_MISMATCH` is not `True`.
    """
    try:
        compiled = etree.LIBXML_COMPILED_VERSION
        runtime = etree.LIBXML_VERSION
    except AttributeError:
        # Old lxml build without these attributes - nothing to compare, and
        # no evidence that build carries this defect. Let it proceed.
        return

    if compiled == runtime:
        return

    message = (
        "lxml/libxml2 ABI mismatch: lxml was compiled against libxml2 "
        f"{compiled} but the libxml2 loaded at runtime is {runtime}. This "
        "exact combination is a confirmed cause of a Windows access "
        "violation in this tool (see dev_tools/diagnose_crash_v0.30.12.log "
        "and changelogs/CHANGELOG_v0.30.13.md): compiling this XSD via lxml followed by a "
        "GDAL vector write and any further lxml call crashed 5/5 times in "
        "testing, with no project code involved. Every GeoPackage conversion "
        "this tool performs follows exactly that sequence.\n"
        "\n"
        "Fix the environment (recommended - lets conda's solver pick a "
        "mutually consistent set, rather than layering another install on "
        "top of a drifted one):\n"
        "  conda deactivate\n"
        "  conda env remove -n geopackage\n"
        "  conda env create -f environment.yml\n"
        "  conda activate geopackage\n"
        "\n"
        "Then confirm the two versions agree:\n"
        "  python -c \"from lxml import etree; "
        "print(etree.LIBXML_COMPILED_VERSION, etree.LIBXML_VERSION)\"\n"
        "\n"
        "If you have independently verified this specific combination is "
        "safe on your build, set core.config.ALLOW_LIBXML_ABI_MISMATCH = "
        "True to downgrade this to a logged warning."
    )

    # Imported locally (not at module load) so the module read through it
    # every call, matching converter._serialize_conversions's own reasoning:
    # the flag can be flipped at runtime rather than only before first import.
    from . import config as _config

    if getattr(_config, "ALLOW_LIBXML_ABI_MISMATCH", False):
        logger.warning(
            "%s Continuing because config.ALLOW_LIBXML_ABI_MISMATCH is True.",
            message,
        )
        return

    raise RuntimeError(message)


def _locate_schema_file() -> Optional[Path]:
    """Return the path of the bundled ISO 19139 XSD, or None if absent.

    v0.27.0 housekeeping: the bundled schema validates the ISO 19139 (2005
    'gmd') ENCODING of ISO 19115 metadata, so it is named iso19139-gmd.xsd.
    The legacy filename is still accepted as a fallback.

    Returns:
        Path to the schema file, or None when neither name exists.
    """
    schema_dir = Path(__file__).parent.parent / "schemas"

    schema_path = schema_dir / "iso19139-gmd.xsd"
    if schema_path.exists():
        return schema_path

    legacy_path = schema_dir / "iso19115-1.xsd"
    if legacy_path.exists():
        return legacy_path

    return None


def _get_shared_schema() -> Optional[etree.XMLSchema]:
    """Return the process-wide compiled ISO 19115/19139 schema.

    Compiles the XSD on first call and caches it. Every subsequent call - from
    any thread - returns the same object without re-entering libxml2's schema
    parser, which is the operation that corrupted the heap in v0.30.9.

    Double-checked under `_LXML_LOCK`: the fast path reads the flag without
    locking, and the slow path re-tests it after acquiring, so two threads
    arriving together still compile exactly once.

    A failure to load is cached too. If the schema file is missing or invalid,
    the answer is None forever rather than a fresh warning and a fresh
    filesystem walk per MetadataHandler.

    Returns:
        The shared `etree.XMLSchema`, or None when no usable schema was found.
    """
    global _SHARED_SCHEMA, _SCHEMA_LOADED, _SCHEMA_SOURCE_PATH

    # Fast path - already resolved, no lock needed. Reading a bool and an
    # object reference is atomic under the GIL.
    if _SCHEMA_LOADED:
        return _SHARED_SCHEMA

    with _LXML_LOCK:
        # Re-test: another thread may have compiled it while we waited.
        if _SCHEMA_LOADED:
            return _SHARED_SCHEMA

        schema_path = _locate_schema_file()

        if schema_path is None:
            logger.warning(
                "ISO 19115 schema not found in "
                f"{Path(__file__).parent.parent / 'schemas'} - "
                "XSD validation will be skipped"
            )
            _SHARED_SCHEMA = None
            _SCHEMA_SOURCE_PATH = None
            _SCHEMA_LOADED = True
            return None

        # v0.30.13: gate the ONE operation proven to trigger the libxml2 ABI
        # crash (see module docstring), immediately before it happens, inside
        # the same lock so no other thread can slip a compile in ahead of the
        # check. Deliberately OUTSIDE the try/except below - a RuntimeError
        # here must stop the process, not get caught, logged as a generic
        # "schema failed to load", and downgraded to "validation skipped".
        # That silent downgrade is the exact failure mode this guard exists
        # to replace with a clear, actionable exception.
        _verify_libxml2_abi()

        try:
            # Parse schema document with the hardened parser, then compile.
            # Both steps are inside the lock: xmlSchemaParse() is the unsafe
            # one, but the document it consumes is interned into the same
            # shared dictionaries, so neither may overlap with another thread.
            schema_doc = etree.parse(str(schema_path), _build_hardened_parser())
            schema = etree.XMLSchema(schema_doc)

            _SHARED_SCHEMA = schema
            _SCHEMA_SOURCE_PATH = schema_path
            _SCHEMA_LOADED = True

            logger.info(f"Loaded ISO 19115 schema from {schema_path} (shared)")
            return _SHARED_SCHEMA

        except Exception as e:
            # Cache the failure. Retrying a broken XSD once per handler only
            # buys repeated log noise and repeated trips through the schema
            # parser, which is the code path being avoided.
            logger.warning(f"Error loading ISO 19115 schema: {e}")
            _SHARED_SCHEMA = None
            _SCHEMA_SOURCE_PATH = None
            _SCHEMA_LOADED = True
            return None


def reset_schema_cache() -> None:
    """Drop the cached schema so the next call recompiles it.

    Test-support hook. Nothing in the shipped GUI or CLI needs this - the
    schema is immutable and lives for the process. It exists so a test can
    swap the file in schemas/ and observe the new one, and so a test that
    deliberately corrupts the schema cannot leak that state into later tests.

    Not safe to call while another thread is inside `validate_schema()`; call
    it from single-threaded test setup or teardown only.
    """
    global _SHARED_SCHEMA, _SCHEMA_LOADED, _SCHEMA_SOURCE_PATH

    with _LXML_LOCK:
        _SHARED_SCHEMA = None
        _SCHEMA_LOADED = False
        _SCHEMA_SOURCE_PATH = None
        logger.debug("ISO 19115 schema cache reset")


def get_schema_source_path() -> Optional[Path]:
    """Return the path the shared schema was compiled from.

    Returns:
        The `Path` of the loaded XSD, or None if no schema is loaded.
    """
    return _SCHEMA_SOURCE_PATH


class MetadataHandler:
    """
    Generates ISO 19115 / DGIWG-compliant metadata with XSD validation.

    Handles creation of metadata XML documents for embedding in
    GeoPackage files. Ensures compliance with both OGC standards
    and DGIWG defense requirements through XSD schema validation.

    Instances are cheap: as of v0.30.10 the compiled XSD is a process-wide
    singleton, so constructing a handler no longer parses a schema. Instances
    are also safe to create and use from multiple threads - all libxml2 work is
    serialized on the module lock.

    Attributes:
        schema: The shared ISO 19115 XSD schema used for validation, or None
            when no schema is bundled. Read-only in practice; it is the same
            object on every handler in the process.
        namespace_map: XML namespace mappings
    """

    def __init__(self):
        """Initialize metadata handler and bind the shared XSD schema.

        Raises:
            RuntimeError: v0.30.13 - if this is the first MetadataHandler
                built in the process and lxml's compiled libxml2 ABI does not
                match the libxml2 loaded at runtime. See
                `_verify_libxml2_abi()` and the module docstring for why this
                combination is a confirmed crash, not a theoretical one.
        """
        self.namespace_map = {
            "gmd": "http://www.isotc211.org/2005/gmd",
            "gco": "http://www.isotc211.org/2005/gco",
            "gml": "http://www.opengis.net/gml/3.2",
            "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        }
        # v0.30.10: bind the process-wide compiled schema instead of building
        # a private one. See the module docstring for why building one here
        # crashed the v0.30.9 concurrency test.
        self.schema = _get_shared_schema()

    def _load_iso19115_schema(self) -> Optional[etree.XMLSchema]:
        """
        Load ISO 19115 XSD schema for metadata validation.

        Retained for backward compatibility. As of v0.30.10 this delegates to
        the process-wide cache rather than compiling a private schema, so
        calling it from several threads is safe and returns the same object.

        Returns:
            lxml XMLSchema object, or None if schema file not found
        """
        return _get_shared_schema()

    def validate_schema(self, metadata_xml_string: str) -> bool:
        """
        Validate metadata XML against ISO 19115 XSD schema.

        Performs full XSD schema validation to ensure DGIWG compliance.
        Checks required fields, element types, and structure.

        v0.30.10: the parse, the validate and the error_log read all happen
        under one acquisition of the module lock. `error_log` is state on the
        shared schema object, so reading it outside the lock that produced it
        could report another thread's errors - or fault, since libxml2 is
        rebuilding that list concurrently.

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
        schema = self.schema
        if not schema:
            logger.warning("No XSD schema available for validation")
            return True  # Skip validation if schema not loaded

        # Encode outside the lock - pure Python string work, no libxml2.
        try:
            xml_bytes = metadata_xml_string.encode("utf-8")
        except (AttributeError, UnicodeEncodeError) as e:
            raise ValueError(f"Invalid XML input: {e}")

        with _LXML_LOCK:
            try:
                # Parse XML string with a hardened, per-call parser
                doc = etree.fromstring(xml_bytes, _build_hardened_parser())

                # Validate against schema
                if not schema.validate(doc):
                    errors = schema.error_log
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
            except ValueError:
                # Already the message we want - do not double-wrap it as
                # "Schema validation error: ISO 19115 schema validation
                # failed: ..." the way the pre-v0.30.10 ordering did.
                raise
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

  <!-- Data quality -->
  <!-- COMPLIANCE-7: ISO 19139 XSD sequence requires dataQualityInfo BEFORE
       metadataConstraints at the MD_Metadata level. -->
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
      {f'<gmd:lineage><gmd:LI_Lineage><gmd:statement><gco:CharacterString>{saxutils.escape(lineage)}</gco:CharacterString></gmd:statement></gmd:LI_Lineage></gmd:lineage>' if lineage else ''}
    </gmd:DQ_DataQuality>
  </gmd:dataQualityInfo>

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

</gmd:MD_Metadata>'''

            # Step 1: Validate XML is well-formed (basic check)
            # stdlib expat - independent parser per call, no libxml2 state.
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

            # Well-formedness check (stdlib expat, no libxml2 state)
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
      <!-- COMPLIANCE-10: gmd:abstract is mandatory (minOccurs=1) in
           MD_DataIdentification per ISO 19139 XSD. Use a generated value
           derived from the layer name when no explicit abstract is given. -->
      <gmd:abstract><gco:CharacterString>Feature layer: {ln}</gco:CharacterString></gmd:abstract>
      <gmd:language>
        <gmd:LanguageCode codeList="http://www.loc.gov/standards/iso639-2/" codeListValue="{lng}">{lng}</gmd:LanguageCode>
      </gmd:language>
    </gmd:MD_DataIdentification>
  </gmd:identificationInfo>

  <!-- COMPLIANCE-8: dataQualityInfo must precede metadataConstraints per
       ISO 19139 XSD sequence.  Layer metadata has no quality report so an
       empty DQ_DataQuality element is omitted; constraints come last. -->
  <gmd:metadataConstraints>
    <gmd:MD_SecurityConstraints>
      <gmd:classification>
        <gmd:MD_ClassificationCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ClassificationCode" codeListValue="{sec_code}">{sec_label}</gmd:MD_ClassificationCode>
      </gmd:classification>
    </gmd:MD_SecurityConstraints>
  </gmd:metadataConstraints>

</gmd:MD_Metadata>'''

            # Step 1: Validate XML is well-formed (stdlib expat)
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
