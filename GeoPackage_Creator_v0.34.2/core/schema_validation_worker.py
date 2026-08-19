#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Isolated ISO 19139 XSD validator; executed directly, never via ``core``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from lxml import etree


def _reply(ok: bool, error: str = "") -> int:
    sys.stdout.write(json.dumps({"ok": ok, "error": error}) + "\n")
    sys.stdout.flush()
    return 0


def _parser():
    return etree.XMLParser(no_network=True, resolve_entities=False, huge_tree=False)


def main() -> int:
    if len(sys.argv) != 2:
        return _reply(False, "validator requires one schema-path argument")
    schema_path = Path(sys.argv[1])
    if not schema_path.is_file():
        return _reply(False, f"schema file not found: {schema_path}")
    try:
        schema = etree.XMLSchema(etree.parse(str(schema_path), _parser()))
        document = etree.fromstring(sys.stdin.buffer.read(), _parser())
        if schema.validate(document):
            return _reply(True)
        details = "\n".join(
            f"  Line {entry.line}: {entry.message}" for entry in schema.error_log
        )
        return _reply(False, f"ISO 19115 schema validation failed:\n{details}")
    except etree.XMLSyntaxError as exc:
        return _reply(False, f"Invalid XML syntax: {exc}")
    except Exception as exc:
        return _reply(False, f"Schema validation error: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
