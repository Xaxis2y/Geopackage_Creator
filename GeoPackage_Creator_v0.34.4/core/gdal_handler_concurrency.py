# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
DEPRECATED SHIM — core.gdal_handler_concurrency

This module used to contain a second, independent 395-line copy of
``GDALHandler``. Nothing imported it. It is retained only as a forwarding shim
so that any code (or any future refactor) that reaches for this name gets the
maintained implementation instead of a stale fork.

Why the duplicate was removed (v0.30.9)
=======================================
The copy carried, verbatim, both of the defects fixed in v0.30.7:

1. ``close_all_datasets()`` ended each loop iteration with ``del ds``. ``ds`` is
   the loop variable, so that unbound a name and closed nothing; the next
   iteration simply rebound it.

2. ``close_geopackage(ds)`` ended with ``del ds`` on a PARAMETER — closing
   nothing, because the caller still held the reference — and then released the
   per-file write lock in a ``finally`` block regardless of whether this thread
   owned it. The GeoPackage therefore stayed open and unflushed while the write
   lock was free for another writer to take.

That second one is the exact cause of the ``Windows fatal exception: access
violation`` that killed the v0.30.6 release test. Leaving a second copy of it
in the tree — under a filename that reads like *the* concurrency
implementation — was an invitation to reintroduce the crash by importing the
more relevant-sounding module.

There is one canonical GDALHandler. It lives in ``core.gdal_handler``, which
serializes conversions process-wide and closes datasets deterministically.

Importing this module emits a DeprecationWarning and forwards the public names.
Update imports to::

    from core.gdal_handler import GDALHandler
"""

import warnings

from .gdal_handler import (  # noqa: F401  (re-exported for compatibility)
    GDALHandler,
    global_conversion_lock,
)

warnings.warn(
    "core.gdal_handler_concurrency is deprecated and now forwards to "
    "core.gdal_handler. It previously held a duplicate GDALHandler that still "
    "contained the v0.30.7 handle-lifetime crash. Import core.gdal_handler "
    "directly.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["GDALHandler", "global_conversion_lock"]
