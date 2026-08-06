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

# Resolve bundled resources / environment first. Must precede core imports.
try:
    import runtime_paths
except ImportError:  # frozen layouts may place it alongside the bundle root
    from packaging import runtime_paths  # type: ignore

runtime_paths.bootstrap()

APP_VERSION = "0.30.19"


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
