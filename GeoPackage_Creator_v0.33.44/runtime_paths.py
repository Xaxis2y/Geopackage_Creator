# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
runtime_paths.py
================
Resource-path resolution for both *source* runs and *frozen* (PyInstaller)
runs of GeoPackage Creator.

When the application is frozen with PyInstaller, bundled data files (the
`schemas/` folder, the `DGIWG_Validator_v1_55_updated/` package, etc.) are
unpacked next to the executable (one-dir build) or into a temporary
`sys._MEIPASS` folder (one-file build).  The original source code locates
those resources with `Path(__file__).parent.parent`, which is correct for a
normal `python` run but wrong once frozen.

This module centralises that logic.  Call `bootstrap()` once, as early as
possible in the process (before importing `core.*`), so that:

  * GDAL / PROJ data directories are pointed at the bundled copies.
  * The `DGIWG_VALIDATOR_PATH` environment variable is set so the existing
    auto-detect logic in `core/validation_gate.py` finds the bundled
    validator.
  * The bundle root is importable on `sys.path`.

It is safe to call `bootstrap()` in a non-frozen environment; it becomes a
near no-op and just returns the project root.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_base() -> Path:
    """Return the directory that contains bundled resources.

    * Frozen one-file build : `sys._MEIPASS` (temporary extraction dir).
    * Frozen one-dir build  : the folder that holds the executable.
    * Source run            : the project root (this file's parent's parent
                              if placed under `packaging/`, otherwise its
                              own directory).
    """
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent

    # Source run: this file lives in <root>/packaging/runtime_paths.py
    here = Path(__file__).resolve().parent
    if here.name == "packaging":
        return here.parent
    return here


def _first_existing(*candidates: Path) -> Path | None:
    for c in candidates:
        if c and c.exists():
            return c
    return None


def bootstrap() -> Path:
    """Wire up resource paths / environment. Returns the resource base dir.

    Idempotent and safe to call multiple times.
    """
    base = resource_base()

    # Make sure bundled top-level packages (core, geopackage_creator, GUI)
    # are importable.
    base_str = str(base)
    if base_str not in sys.path:
        sys.path.insert(0, base_str)

    # ---- DGIWG validator ------------------------------------------------
    # core/validation_gate.py looks at DGIWG_VALIDATOR_PATH first, so set it
    # explicitly to the bundled folder when present. Prioritize the latest
    # version (v1.58+) over older versions.
    if not os.environ.get("DGIWG_VALIDATOR_PATH"):
        validator_dir = _first_existing(
            base / "DGIWG_GeoPackage_Validator_v1.58",
            base / "DGIWG_Validator_v1_55_updated",
            *base.glob("DGIWG_Validator_v1_5*"),
            *base.glob("DGIWG_GeoPackage_Validator_v1.*"),
        )
        if validator_dir:
            os.environ["DGIWG_VALIDATOR_PATH"] = str(validator_dir)
            # the folder that CONTAINS the dgiwg_validator package also needs
            # to be importable when the validator is invoked in-process
            if str(validator_dir) not in sys.path:
                sys.path.insert(0, str(validator_dir))

    # ---- GDAL / PROJ data ----------------------------------------------
    # PyInstaller's GDAL hooks usually set these, but we reinforce them so a
    # mis-detected CRS / missing gdal-data does not silently break Req 13.
    gdal_data = _first_existing(
        base / "osgeo" / "data" / "gdal",
        base / "Library" / "share" / "gdal",
        base / "gdal-data",
        base / "share" / "gdal",
    )
    if gdal_data and not os.environ.get("GDAL_DATA"):
        os.environ["GDAL_DATA"] = str(gdal_data)

    proj_data = _first_existing(
        base / "osgeo" / "data" / "proj",
        base / "pyproj" / "proj_dir" / "share" / "proj",
        base / "Library" / "share" / "proj",
        base / "proj-data",
        base / "share" / "proj",
    )
    if proj_data and not os.environ.get("PROJ_LIB"):
        os.environ["PROJ_LIB"] = str(proj_data)
        os.environ.setdefault("PROJ_DATA", str(proj_data))

    return base
