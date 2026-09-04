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

import os
import sys
import runpy
from pathlib import Path

# Resolve bundled resources / environment first. Must precede core imports.
try:
    import runtime_paths
except ImportError:  # frozen layouts may place it alongside the bundle root
    from packaging import runtime_paths  # type: ignore

runtime_paths.bootstrap()

APP_VERSION = "0.34.4"


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


def _resolve_dgiwg_worker_script() -> Path:
    """Locate the DGIWG validator launcher this worker process should run.

    core.validation_gate.run_dgiwg_validation() resolves a validator
    directory via find_validator() (an explicit --validator-path,
    DGIWG_VALIDATOR_PATH, or a discovered sibling install) and passes it
    here through the DGIWG_VALIDATOR_WORKER_DIR env var, so a non-default
    validator install is actually honored in the frozen build rather than
    being silently replaced by whichever copy happens to be bundled.

    The launcher filename AND its containing folder are discovered by glob,
    never hardcoded: the bundled validator is upgraded in place on its own
    schedule, independent of this app's version (v1.62 -> v1.63 happened
    with no application code change), and a hardcoded
    "DGIWG_GeoPackage_Validator_v1.62/DGIWG_Validator_v1_62.py" path breaks
    --validate outright -- with runpy.run_path() raising FileNotFoundError --
    the moment that happens.
    """
    search_dirs = []
    override = os.environ.get("DGIWG_VALIDATOR_WORKER_DIR")
    if override:
        search_dirs.append(Path(override))
    search_dirs.extend(
        sorted(runtime_paths.resource_base().glob("DGIWG_GeoPackage_Validator_v1.*"))
    )

    for vdir in search_dirs:
        matches = sorted(vdir.glob("DGIWG_Validator_v1_*.py"))
        if len(matches) == 1:
            return matches[0]

    searched = ", ".join(str(d) for d in search_dirs) or "(none)"
    raise FileNotFoundError(
        "No DGIWG_Validator_v1_*.py launcher found. Searched: " + searched
    )


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
        worker = _resolve_dgiwg_worker_script()
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
