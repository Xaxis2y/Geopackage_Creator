# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Concurrency and thread-safety tests for GeoPackage Creator

Tests that verify:
- Single writer pattern works correctly
- Context manager properly acquires/releases locks
- Multiple threads can write to different .gpkg files simultaneously
- Concurrent writes to same file are handled gracefully
- Resources are properly cleaned up even on errors

IMPORTANT (v0.30.6): GDAL/OGR does not support opening the SAME source file
concurrently from multiple threads in one process. On GDAL 3.13 this was
observed to cause a hard native crash - "Windows fatal exception: access
violation" - which kills the entire pytest process (not a catchable Python
exception). Every test below that spawns multiple threads therefore gives
each thread its OWN copy of the source file via _copy_shapefile_for_thread().
This mirrors real-world usage: a real deployment converting N files
concurrently would have N distinct source files, never N threads reading one
shared file.
"""

import pytest
import threading
import time
import os
import shutil
from pathlib import Path
from core import GeoPackageConverter
from core.gdal_handler import GDALHandler


# v0.30.10: every test in this module drives native code (GDAL/OGR, libxml2)
# from more than one thread, so every one of them can in principle die with a
# Windows access violation rather than a test failure - which kills the whole
# pytest process and discards the results of every other test in the run.
#
# The marker lets this module be run in its own process:
#
#   pytest tests/ -v -m "not concurrency"   # 301 tests, crash-proof
#   pytest tests/ -v -m concurrency         # this module, isolated
#
# See pytest.ini and run_tests_v0.30.10.bat. A plain `pytest tests/` still
# runs everything - the marker selects, it does not skip.
pytestmark = pytest.mark.concurrency


def _copy_shapefile_for_thread(sample_shapefile: str, temp_dir: str, index: int) -> str:
    """Return a path to a private, per-thread copy of *sample_shapefile*.

    v0.30.6: extracted into a shared helper after a shared-source-file read
    from multiple threads caused a native access-violation crash in GDAL 3.13
    (see module docstring). Every concurrency test that spawns threads must
    call this once per thread and pass the RETURNED path to convert(), never
    the original sample_shapefile path.
    """
    base = os.path.splitext(sample_shapefile)[0]
    thread_dir = os.path.join(temp_dir, f"src_{index}")
    os.makedirs(thread_dir, exist_ok=True)
    local_shp = os.path.join(thread_dir, "points.shp")
    local_base = os.path.splitext(local_shp)[0]
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        if os.path.exists(base + ext):
            shutil.copy(base + ext, local_base + ext)
    return local_shp


class TestContextManager:
    """Test context manager functionality for resource management."""

    def test_context_manager_basic(self, sample_shapefile, temp_dir):
        """Test that context manager properly opens and closes."""
        output_path = os.path.join(temp_dir, "context_test.gpkg")

        with GDALHandler() as handler:
            # Should have no open datasets initially
            assert len(handler._open_datasets) == 0

            # Create geopackage
            ds = handler.create_geopackage(output_path)
            assert ds is not None
            assert len(handler._open_datasets) == 1

        # After exiting context, datasets should be closed
        # The output file should exist
        assert os.path.exists(output_path)

    def test_context_manager_exception_cleanup(self, sample_shapefile, temp_dir):
        """Test that datasets are closed even if exception occurs."""
        output_path = os.path.join(temp_dir, "exception_cleanup.gpkg")

        try:
            with GDALHandler() as handler:
                ds = handler.create_geopackage(output_path)
                assert len(handler._open_datasets) == 1
                # Simulate exception
                raise ValueError("Test exception")
        except ValueError:
            pass

        # File should still exist and be valid
        assert os.path.exists(output_path)

    def test_context_manager_write_lock_released(self, sample_shapefile, temp_dir):
        """Test that write lock is released when context exits."""
        output_path = os.path.join(temp_dir, "lock_test.gpkg")

        # First context: acquire lock
        with GDALHandler() as handler1:
            ds = handler1.create_geopackage(output_path)
            handler1.close_geopackage(ds)

        # Second context: should be able to acquire lock again
        # If lock wasn't released, this would hang or fail
        with GDALHandler() as handler2:
            # Just opening should work if lock was released
            source = handler2.read_source_data(sample_shapefile)
            assert source is not None


class TestConcurrentWrites:
    """Test concurrent write scenarios."""

    def test_concurrent_writes_different_files(self, sample_shapefile, temp_dir):
        """Test that multiple threads can write different .gpkg files concurrently."""
        output_paths = [
            os.path.join(temp_dir, f"concurrent_{i}.gpkg")
            for i in range(3)
        ]
        results = {}
        errors = {}

        def convert_file(index):
            """Convert in separate thread."""
            try:
                # v0.30.6: each thread gets its own copy of the source file -
                # see module docstring / _copy_shapefile_for_thread(). Reading
                # the SAME shapefile from concurrent threads crashed the whole
                # process with a native access violation on GDAL 3.13.
                local_shp = _copy_shapefile_for_thread(
                    sample_shapefile, temp_dir, index
                )
                converter = GeoPackageConverter(profile='military')
                result = converter.convert(
                    source_geodatabase=local_shp,
                    output_geopackage=output_paths[index],
                    title=f"Concurrent Test {index}",
                    abstract="Test concurrent writes",
                    poc="Test User",
                    org="Test Org",
                    nation="USA",
                    security="UNCLASSIFIED",
                )
                results[index] = result
            except Exception as e:
                errors[index] = str(e)

        # Start 3 threads
        threads = []
        for i in range(3):
            t = threading.Thread(target=convert_file, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join(timeout=30)

        # All should succeed
        for i in range(3):
            assert i not in errors, f"Thread {i} error: {errors.get(i)}"
            assert results[i]['success'], f"Thread {i} failed: {results[i]['error']}"
            assert os.path.exists(output_paths[i])

    def test_concurrent_writes_same_file_serialized(self, sample_shapefile, temp_dir):
        """Test that concurrent writes to same file are properly serialized."""
        output_path = os.path.join(temp_dir, "same_file_test.gpkg")
        order = []
        lock = threading.Lock()

        def convert_file(index):
            """Convert to same file from separate thread."""
            try:
                # v0.30.6: each thread reads its OWN copy of the source file
                # (see module docstring). All three threads still target the
                # SAME output .gpkg, which is what this test actually exercises
                # (the per-file write lock serializing concurrent writers).
                local_shp = _copy_shapefile_for_thread(
                    sample_shapefile, temp_dir, index
                )

                # Small delay to ensure overlapping timing
                time.sleep(0.1 * index)

                converter = GeoPackageConverter(profile='military')
                result = converter.convert(
                    source_geodatabase=local_shp,
                    output_geopackage=output_path,
                    title=f"Write {index}",
                    abstract=f"Thread {index}",
                    poc="Test User",
                    org="Test Org",
                    nation="USA",
                )

                with lock:
                    order.append((index, 'success' if result['success'] else 'failed'))

            except Exception as e:
                with lock:
                    order.append((index, f'error: {str(e)}'))

        # Start threads with staggered timing
        threads = []
        for i in range(3):
            t = threading.Thread(target=convert_file, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all
        for t in threads:
            t.join(timeout=30)

        # File should exist (last write wins)
        assert os.path.exists(output_path)

        # All operations should complete (not hang)
        assert len(order) == 3


class TestResourceCleanup:
    """Test that resources are properly cleaned up."""

    def test_no_resource_leaks_on_success(self, sample_shapefile, temp_dir):
        """Test that no resources leak on successful conversion."""
        output_path = os.path.join(temp_dir, "no_leak_success.gpkg")

        converter = GeoPackageConverter(profile='military')
        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage=output_path,
            title="No Leak Test",
            abstract="Testing resource cleanup",
            poc="Test User",
            org="Test Org",
            nation="USA",
        )

        assert result['success']

        # File should be valid and readable after context exits
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 0

    def test_lock_not_held_after_conversion(self, sample_shapefile, temp_dir):
        """Test that write lock is not held after conversion completes."""
        output_path = os.path.join(temp_dir, "lock_release.gpkg")

        converter = GeoPackageConverter(profile='military')
        result = converter.convert(
            source_geodatabase=sample_shapefile,
            output_geopackage=output_path,
            title="Lock Release Test",
            abstract="Verify lock is released",
            poc="Test User",
            org="Test Org",
            nation="USA",
        )

        assert result['success']

        # Should be able to open the file immediately after
        # without blocking on the write lock
        import time
        start = time.time()

        # Try to acquire the same lock
        lock = GDALHandler._get_write_lock(output_path)
        acquired = lock.acquire(timeout=1.0)

        elapsed = time.time() - start

        # Should acquire quickly (not blocked)
        assert acquired, "Could not acquire write lock - may still be held"
        assert elapsed < 0.5, f"Lock acquisition took {elapsed}s, may have been blocked"

        # Release the lock we just acquired
        try:
            lock.release()
        except RuntimeError:
            pass

    def test_multiple_sequential_conversions_same_file(
        self, sample_shapefile, temp_dir
    ):
        """Test sequential conversions to same file don't cause issues."""
        output_path = os.path.join(temp_dir, "sequential.gpkg")

        converter = GeoPackageConverter(profile='military')

        # Do 3 sequential conversions
        for i in range(3):
            # Remove file between runs
            if os.path.exists(output_path):
                os.remove(output_path)

            result = converter.convert(
                source_geodatabase=sample_shapefile,
                output_geopackage=output_path,
                title=f"Sequential {i}",
                abstract=f"Run {i}",
                poc="Test User",
                org="Test Org",
                nation="USA",
            )

            assert result['success'], f"Run {i} failed: {result['error']}"
            assert os.path.exists(output_path)


class TestGDALHandlerConcurrency:
    """Direct tests of GDALHandler concurrency features."""

    def test_write_lock_exists_for_file(self, temp_dir):
        """Test that write locks are created per file."""
        path1 = os.path.join(temp_dir, "file1.gpkg")
        path2 = os.path.join(temp_dir, "file2.gpkg")

        lock1 = GDALHandler._get_write_lock(path1)
        lock2 = GDALHandler._get_write_lock(path2)

        # Different files should have different locks
        assert lock1 is not lock2

        # Same file should return same lock
        lock1_again = GDALHandler._get_write_lock(path1)
        assert lock1 is lock1_again

    def test_handler_tracks_open_datasets(self, sample_shapefile, temp_dir):
        """Test that handler properly tracks open datasets."""
        output_path = os.path.join(temp_dir, "track_datasets.gpkg")

        handler = GDALHandler()

        # Initially empty
        assert len(handler._open_datasets) == 0

        # Create geopackage
        ds = handler.create_geopackage(output_path)
        assert len(handler._open_datasets) == 1

        # Close it
        handler.close_geopackage(ds)

        # Cleanup
        handler.close_all_datasets()
        assert len(handler._open_datasets) == 0

    def test_context_manager_tracks_writes(self, sample_shapefile, temp_dir):
        """Test that context manager properly tracks write state."""
        output_path = os.path.join(temp_dir, "write_state.gpkg")

        with GDALHandler() as handler:
            assert not handler._is_writing
            ds = handler.create_geopackage(output_path)
            assert handler._is_writing
            assert handler._active_output_path == output_path
            handler.close_geopackage(ds)
            assert not handler._is_writing
            assert handler._active_output_path is None


class TestStressScenarios:
    """Stress tests for concurrency under load."""

    def test_many_concurrent_threads(self, sample_shapefile, temp_dir):
        """Test with more threads than typical."""
        num_threads = 5
        output_paths = [
            os.path.join(temp_dir, f"stress_{i}.gpkg")
            for i in range(num_threads)
        ]
        results = {}

        def convert_file(index):
            # v0.30.6: give each thread its OWN copy of the source shapefile -
            # see module docstring / _copy_shapefile_for_thread(). This test's
            # real purpose is concurrent WRITES to different GeoPackages, so
            # isolating the read side removes both the crash hazard and any
            # Windows file-sharing flakiness. The error is also captured so
            # any genuine failure is diagnosable.
            local_shp = _copy_shapefile_for_thread(sample_shapefile, temp_dir, index)

            converter = GeoPackageConverter(profile='military')
            result = converter.convert(
                source_geodatabase=local_shp,
                output_geopackage=output_paths[index],
                title=f"Stress {index}",
                abstract="Stress test",
                poc="Test",
                org="Test",
                nation="USA",
            )
            results[index] = (result['success'], result.get('error'))

        threads = []
        start = time.time()

        for i in range(num_threads):
            t = threading.Thread(target=convert_file, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=60)

        elapsed = time.time() - start

        # All should succeed
        for i in range(num_threads):
            ok, err = results.get(i, (False, "thread did not record a result"))
            assert ok, f"Thread {i} failed: {err}"

        print(f"Completed {num_threads} concurrent conversions in {elapsed:.2f}s")
