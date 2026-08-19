# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Runtime configuration for the DGIWG validator (v1.59).

v1.57 fix (#9): CLI flags were previously smuggled between modules by setting
attributes on Python's ``builtins`` module (``builtins._DGIWG_OFFLINE`` etc.)
under half a dozen different local aliases.  That was global mutable state
that was hard to trace and impossible to isolate in unit tests.

All runtime flags now live in this one module.  ``main()`` writes them once
after argument parsing; every other module reads them via normal attribute
access (``config.OFFLINE``, ``config.SAMPLE_SIZE``, ...).

Defaults below are the values used when the package is imported as a library
without going through ``main()``.
"""

# --offline : disable all internet checks (EPSG API, OGC TMS, URI reachability)
OFFLINE: bool = False

# --quiet : suppress per-file progress banners
QUIET: bool = False

# --fail-fast : stop batch processing after first file with any FAIL
FAIL_FAST: bool = False

# --sample-size N : geometry/tile BLOBs sampled per table (Req 24 / Req 26).
# None = flag not given; each check then uses its own default
# (Req 24 geometry sampling: 25, Req 26 tile BLOB sampling: 5).
SAMPLE_SIZE = None  # type: int | None

# --json : retained for CLI compatibility; JSON is always written since v1.53
EMIT_JSON: bool = True


def reset() -> None:
    """Restore all flags to their defaults (useful for tests)."""
    global OFFLINE, QUIET, FAIL_FAST, SAMPLE_SIZE, EMIT_JSON
    OFFLINE = False
    QUIET = False
    FAIL_FAST = False
    SAMPLE_SIZE = None
    EMIT_JSON = True
