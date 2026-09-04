# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Tests for ISO 19115 metadata embedding (v0.26, BUG-6 fix).

Verifies that GeoPackageConverter._embed_metadata() writes the OGC
GeoPackage Metadata Extension tables (gpkg_metadata,
gpkg_metadata_reference), registers the extension in gpkg_extensions,
and links layer-level records to the package-level record.

These tests use plain SQLite files and do not require real spatial data.
"""

import sqlite3

import pytest

from core import GeoPackageConverter
from core.config import METADATA_MIME_TYPE, ISO_METADATA_STANDARD_URI


PACKAGE_XML = '<?xml version="1.0"?><gmd:MD_Metadata xmlns:gmd="http://www.isotc211.org/2005/gmd"/>'
LAYER_XML = '<?xml version="1.0"?><gmd:MD_Metadata xmlns:gmd="http://www.isotc211.org/2005/gmd"/>'


@pytest.fixture
def gpkg_file(tmp_path):
    """Create a minimal SQLite file standing in for a GeoPackage."""
    path = tmp_path / "test.gpkg"
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE gpkg_extensions (
            table_name TEXT,
            column_name TEXT,
            extension_name TEXT NOT NULL,
            definition TEXT NOT NULL,
            scope TEXT NOT NULL,
            CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name)
        )
        """
    )
    conn.commit()
    conn.close()
    return str(path)


class TestEmbedMetadata:
    """Test the _embed_metadata() implementation."""

    def test_embeds_package_and_layer_records(self, gpkg_file):
        converter = GeoPackageConverter()
        count = converter._embed_metadata(
            gpkg_file, PACKAGE_XML, {"roads": LAYER_XML, "buildings": LAYER_XML}
        )
        assert count == 3  # 1 package + 2 layers

        conn = sqlite3.connect(gpkg_file)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM gpkg_metadata")
        assert cur.fetchone()[0] == 3
        cur.execute("SELECT COUNT(*) FROM gpkg_metadata_reference")
        assert cur.fetchone()[0] == 3
        conn.close()

    def test_package_record_has_geopackage_scope(self, gpkg_file):
        converter = GeoPackageConverter()
        converter._embed_metadata(gpkg_file, PACKAGE_XML, {})

        conn = sqlite3.connect(gpkg_file)
        cur = conn.cursor()
        cur.execute(
            "SELECT reference_scope, table_name, md_parent_id "
            "FROM gpkg_metadata_reference"
        )
        scope, table_name, parent = cur.fetchone()
        assert scope == "geopackage"
        assert table_name is None
        assert parent is None
        conn.close()

    def test_layer_records_linked_to_package(self, gpkg_file):
        converter = GeoPackageConverter()
        converter._embed_metadata(gpkg_file, PACKAGE_XML, {"roads": LAYER_XML})

        conn = sqlite3.connect(gpkg_file)
        cur = conn.cursor()
        cur.execute(
            "SELECT table_name, md_parent_id FROM gpkg_metadata_reference "
            "WHERE reference_scope = 'table'"
        )
        table_name, parent = cur.fetchone()
        assert table_name == "roads"
        assert parent is not None
        conn.close()

    def test_extension_registered(self, gpkg_file):
        converter = GeoPackageConverter()
        converter._embed_metadata(gpkg_file, PACKAGE_XML, {})

        conn = sqlite3.connect(gpkg_file)
        cur = conn.cursor()
        # v0.30.6: OGC GeoPackage 1.4 Annex F.8 requires the gpkg_metadata
        # extension to be registered as a SINGLE package-wide row with
        # table_name = NULL (COMPLIANCE-2), not one row per extension table.
        cur.execute(
            "SELECT table_name, scope FROM gpkg_extensions "
            "WHERE extension_name = 'gpkg_metadata'"
        )
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0] is None            # table_name NULL (package-wide)
        assert rows[0][1] == "read-write"    # scope
        conn.close()

    def test_standard_uri_and_mime_type(self, gpkg_file):
        converter = GeoPackageConverter()
        converter._embed_metadata(gpkg_file, PACKAGE_XML, {})

        conn = sqlite3.connect(gpkg_file)
        cur = conn.cursor()
        cur.execute("SELECT md_standard_uri, mime_type FROM gpkg_metadata")
        uri, mime = cur.fetchone()
        assert uri == ISO_METADATA_STANDARD_URI
        assert mime == METADATA_MIME_TYPE
        conn.close()

    def test_idempotent_extension_registration(self, gpkg_file):
        """Embedding twice must not duplicate gpkg_extensions rows."""
        converter = GeoPackageConverter()
        converter._embed_metadata(gpkg_file, PACKAGE_XML, {})
        converter._embed_metadata(gpkg_file, PACKAGE_XML, {})

        conn = sqlite3.connect(gpkg_file)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM gpkg_extensions "
            "WHERE extension_name = 'gpkg_metadata'"
        )
        # v0.30.6: a single package-wide (table_name NULL) row, registered
        # idempotently via WHERE NOT EXISTS - embedding twice keeps it at 1.
        assert cur.fetchone()[0] == 1
        conn.close()

    def test_metadata_xml_stored_verbatim(self, gpkg_file):
        converter = GeoPackageConverter()
        converter._embed_metadata(gpkg_file, PACKAGE_XML, {})

        conn = sqlite3.connect(gpkg_file)
        cur = conn.cursor()
        cur.execute("SELECT metadata FROM gpkg_metadata")
        assert cur.fetchone()[0] == PACKAGE_XML
        conn.close()
