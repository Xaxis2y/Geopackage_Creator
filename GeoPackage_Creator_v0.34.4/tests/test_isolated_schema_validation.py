# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Regression tests for the GDAL/lxml process-isolation fix (v0.33.44)."""

import ast
from pathlib import Path

import pytest

from core.metadata_handler import MetadataHandler


def test_metadata_process_does_not_import_lxml():
    """GDAL's process must never load lxml/libxml2 through this module."""
    source = Path(__file__).resolve().parents[1] / "core" / "metadata_handler.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imports_lxml = any(
        (
            isinstance(node, ast.Import)
            and any(alias.name == "lxml" or alias.name.startswith("lxml.") for alias in node.names)
        )
        or (
            isinstance(node, ast.ImportFrom)
            and ((node.module or "") == "lxml" or (node.module or "").startswith("lxml."))
        )
        for node in ast.walk(tree)
    )
    assert not imports_lxml


def test_isolated_helper_accepts_valid_metadata():
    handler = MetadataHandler()
    xml = handler.generate_package_metadata(
        title="Isolation test", abstract="Schema validation subprocess test",
        poc="Test User", org="Test Organization", nation="USA",
        security="UNCLASSIFIED", language="eng", topic_category="location",
        ref_date="2026-08-17",
    )
    assert handler.validate_schema(xml) is True


def test_isolated_helper_rejects_invalid_xml():
    handler = MetadataHandler()
    with pytest.raises(ValueError, match="Invalid XML syntax"):
        handler.validate_schema("<broken></different>")
