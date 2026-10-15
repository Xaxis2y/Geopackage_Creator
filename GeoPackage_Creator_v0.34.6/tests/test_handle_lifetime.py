# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Regression tests for the v0.30.7 GeoPackage handle-lifetime crash.

WHY THIS FILE EXISTS
====================
v0.30.6 shipped with GDALHandler.close_geopackage() ending in `del ds`. `ds` is
a function PARAMETER, so that statement unbound a local name and did nothing to
the dataset. The caller's reference stayed alive, so the GeoPackage was never
actually closed. In GeoPackageConverter.convert() the caller's `out_ds` then
remained in scope for the entire rest of the conversion, during which the same
.gpkg is reopened through sqlite3 to embed metadata and finalize DGIWG
compliance - two live handles on one file. The write lock was also released
BEFORE the file was closed, so a second thread could begin writing to a
GeoPackage that GDAL still held open and buffered.

The existing suite could not catch this. tests/test_concurrency.py only
asserted that convert() reported success; nothing asserted that the file had
been RELEASED. So the defect sat behind a green-looking assertion until three
threads reached it at once and the process died with a native access violation.

Every test below is single-threaded and deterministic. They fail on v0.30.6 and
pass on v0.30.7 - no race required to reproduce.
"""

import os
import sqlite3
import sys
import threading

import pytest

from core import config
from core.gdal_handler import GDALHandler, global_conversion_lock


@pytest.fixture
def gpkg_path(temp_dir):
    return os.path.join(temp_dir, "lifetime_probe.gpkg")


class TestCloseGeopackageReleasesHandle:
    """close_geopackage() must genuinely close, not just unbind a name."""

    def test_returns_none_so_caller_can_drop_reference(self, gpkg_path):
        """The contract that makes the fix usable: out_ds = close(out_ds)."""
        with GDALHandler() as handler:
            ds = handler.create_geopackage(gpkg_path)
            returned = handler.close_geopackage(ds)
            assert returned is None, (
                "close_geopackage() must return None so callers can drop their "
                "own reference. Returning anything else re-enables the v0.30.6 "
                "bug where the caller kept the dataset alive."
            )

    def test_dataset_untracked_after_close(self, gpkg_path):
        with GDALHandler() as handler:
            ds = handler.create_geopackage(gpkg_path)
            handler.close_geopackage(ds)
            assert handler._open_datasets == [], (
                "closed dataset must be removed from the tracking list"
            )

    @pytest.mark.skipif(
        not sys.platform.startswith("win"),
        reason="Only Windows refuses to unlink a file with an open handle; on "
               "POSIX this check cannot detect the leak.",
    )
    def test_file_is_unlocked_after_close_windows(self, gpkg_path):
        """The direct v0.30.6 reproducer.

        On Windows an open GDAL handle blocks deletion. On v0.30.6 this
        os.remove() raises PermissionError because `del ds` never closed
        anything.
        """
        with GDALHandler() as handler:
            ds = handler.create_geopackage(gpkg_path)
            handler.close_geopackage(ds)

        os.remove(gpkg_path)  # must not raise
        assert not os.path.exists(gpkg_path)

    def test_sqlite_can_write_after_close(self, gpkg_path):
        """Mirrors what convert() actually does after closing the dataset.

        convert() reopens the .gpkg through sqlite3 to embed metadata and apply
        DGIWG finalization. That must happen with no GDAL handle still open.
        """
        with GDALHandler() as handler:
            ds = handler.create_geopackage(gpkg_path)
            handler.close_geopackage(ds)

        conn = sqlite3.connect(gpkg_path)
        try:
            conn.execute("PRAGMA user_version = 10400")
            conn.commit()
            got = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        assert got == 10400


class TestWriteLockLifecycle:
    """The lock must be released by its owner, after the file is closed."""

    def test_lock_released_and_reacquirable(self, gpkg_path):
        handler = GDALHandler()
        ds = handler.create_geopackage(gpkg_path)

        held = handler._held_lock
        assert held is not None, "acquire must record the lock object"
        assert handler._held_lock_owner == threading.get_ident()

        handler.close_geopackage(ds)
        assert handler._held_lock is None, "lock must be cleared on close"

        acquired = held.acquire(timeout=2)
        try:
            assert acquired, (
                "write lock was leaked - a later conversion of the same file "
                "would block until timeout"
            )
        finally:
            if acquired:
                held.release()

    def test_double_close_is_safe(self, gpkg_path):
        """A second close must not spuriously release someone else's lock."""
        handler = GDALHandler()
        ds = handler.create_geopackage(gpkg_path)
        handler.close_geopackage(ds)
        handler.close_geopackage(None)  # must not raise
        assert handler._held_lock is None

    def test_close_all_datasets_clears_state(self, temp_dir):
        """close_all_datasets() had the same `del ds` no-op, in a loop."""
        handler = GDALHandler()
        paths = [os.path.join(temp_dir, f"multi_{i}.gpkg") for i in range(2)]
        for p in paths:
            ds = handler.create_geopackage(p)
            handler.close_geopackage(ds)

        ds = handler.create_geopackage(os.path.join(temp_dir, "last.gpkg"))
        assert handler._open_datasets, "sanity: dataset should be tracked"

        handler.close_all_datasets()
        assert handler._open_datasets == []
        assert handler._held_lock is None


class TestConversionSerialization:
    """v0.30.7 serializes whole conversions process-wide by default."""

    def test_default_is_serialized(self):
        assert config.ALLOW_CONCURRENT_CONVERSIONS is False, (
            "Concurrent conversions must be opt-in. OGR gives no guarantee "
            "that two conversions may run at once in one process."
        )

    def test_convert_is_wrapped(self):
        from core.converter import GeoPackageConverter
        assert hasattr(GeoPackageConverter.convert, "__wrapped__"), (
            "convert() must be wrapped by _serialize_conversions"
        )

    def test_global_lock_is_shared_and_reentrant(self):
        a = global_conversion_lock()
        b = global_conversion_lock()
        assert a is b, "all callers must share one lock"
        assert a.acquire(timeout=1)
        try:
            # RLock: the same thread may re-enter (convert() may nest).
            assert a.acquire(timeout=1)
            a.release()
        finally:
            a.release()

    def test_opt_out_is_read_at_call_time(self, monkeypatch):
        """The flag must not be frozen by a from-import at module load."""
        import core.converter as converter_mod

        seen = {}
        real = global_conversion_lock()

        monkeypatch.setattr(converter_mod._config,
                            "ALLOW_CONCURRENT_CONVERSIONS", True)

        @converter_mod._serialize_conversions
        def probe():
            # With the opt-out active the lock must NOT be held by us.
            seen["locked"] = real._is_owned()
            return "ok"

        assert probe() == "ok"
        assert seen["locked"] is False, (
            "setting config.ALLOW_CONCURRENT_CONVERSIONS = True at runtime had "
            "no effect - the flag was captured by a from-import"
        )
