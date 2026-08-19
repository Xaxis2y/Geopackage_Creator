# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
app_main.py
===========
Single entry point for the packaged Windows application.

Behaviour:

  * Run with NO command-line arguments  -> launches the Tkinter GUI.
  * Run WITH command-line arguments      -> behaves exactly like the
    `geopackage_creator.py` command-line tool (so the same frozen .exe doubles
    as the CLI, and the GUI's "run in console" feature can re-invoke it).

A few convenience flags are handled here directly:

  --gui            force the GUI even if other args are present
  --version        print the version string and exit
  -h / --help      when it is the ONLY argument, defer to the CLI's argparse
                   help so users see the full option list.

This module calls `runtime_paths.bootstrap()` BEFORE importing any `core.*`
code so that GDAL/PROJ data and the bundled DGIWG validator resolve correctly
in a frozen build.
"""

from __future__ import annotations

import sys
import runpy

# Resolve bundled resources / environment first. Must precede core imports.
try:
    import runtime_paths
except ImportError:  # frozen layouts may place it alongside the bundle root
    from packaging import runtime_paths  # type: ignore

runtime_paths.bootstrap()

APP_VERSION = "0.34.0"


def _run_gui() -> int:
    from geopackage_creator_gui import main as gui_main
    gui_main()
    return 0


def _run_cli() -> int:
    # geopackage_creator.main() parses sys.argv itself.
    from geopackage_creator import main as cli_main
    result = cli_main()
    # cli_main may return None (treat as success) or an int exit code.
    return int(result) if isinstance(result, int) else 0


def main() -> int:
    argv = sys.argv[1:]

    # The isolated metadata validator must start before any application module
    # imports GDAL.  In a frozen build this re-invokes the same executable;
    # the worker source is bundled as data under core/.
    if argv and argv[0] == "--schema-validation-worker":
        sys.argv = [sys.argv[0], *argv[1:]]
        worker = runtime_paths.resource_base() / "core" / "schema_validation_worker.py"
        runpy.run_path(str(worker), run_name="__main__")
        return 0

    # The bundled DGIWG validator imports lxml for Req 18.  Run it before
    # importing any application/GDAL module, preserving native-library
    # isolation even when the GUI or CLI asks for --validate.
    if argv and argv[0] == "--dgiwg-validator-worker":
        sys.argv = [sys.argv[0], *argv[1:]]
        worker = (
            runtime_paths.resource_base()
            / "DGIWG_GeoPackage_Validator_v1.62"
            / "DGIWG_Validator_v1_62.py"
        )
        runpy.run_path(str(worker), run_name="__main__")
        return 0

    if "--version" in argv:
        print(f"GeoPackage Creator v{APP_VERSION}")
        return 0

    # Explicit GUI request, or no arguments at all -> GUI.
    if "--gui" in argv:
        sys.argv = [sys.argv[0]]  # drop --gui so the GUI sees a clean argv
        return _run_gui()

    if not argv:
        return _run_gui()

    # Anything else is treated as a CLI invocation (including --help).
    return _run_cli()


if __name__ == "__main__":
    sys.exit(main())
