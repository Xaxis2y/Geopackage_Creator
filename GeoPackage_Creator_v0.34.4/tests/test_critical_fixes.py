# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Critical Fixes Test Suite

Tests for:
- Fix #1: Mixed Geometry Type Detection (OGC Compliance)
- Fix #2: Lock Timeout Implementation (Operational Safety)
- Fix #3: DGIWG CRS Validation (Defense Compliance)

These are blocking issues that prevent 9.8/10 compliance.
"""

import pytest
import os
import time
import threading
from osgeo import ogr, osr

from core import GDALHandler
from core.validators import CRSValidator, ValidationError
from core.config import DGIWG_APPROVED_CRS


# ============================================================================
# FIX #1: Geometry Type Detection Tests
# ============================================================================

class TestGeometryTypeDetection:
    """Test geometry type detection (OGC Requirement 31)."""

    def test_pure_polygon_layer(self, temp_dir):
        """Pure polygon layer → returns 'Polygon'"""
        handler = GDALHandler()

        # Create test GDB with pure polygon layer
        driver = ogr.GetDriverByName("Memory")
        ds = driver.CreateDataSource("test")

        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)

        layer = ds.CreateLayer("test_polygons", srs, ogr.wkbPolygon)

        # Add 3 polygon features
        for i in range(3):
            feature = ogr.Feature(layer.GetLayerDefn())
            wkt = f"POLYGON(({i} {i}, {i+1} {i}, {i+1} {i+1}, {i} {i+1}, {i} {i}))"
            geom = ogr.CreateGeometryFromWkt(wkt)
            feature.SetGeometry(geom)
            layer.CreateFeature(feature)

        # Test detection
        detected_type = handler._detect_geometry_type(layer)
        assert detected_type == "Polygon", f"Expected 'Polygon', got '{detected_type}'"

        ds = None

    def test_pure_multipolygon_layer(self, temp_dir):
        """Pure multipolygon layer → returns 'MultiPolygon'"""
        handler = GDALHandler()

        driver = ogr.GetDriverByName("Memory")
        ds = driver.CreateDataSource("test")

        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)

        layer = ds.CreateLayer("test_multipolygons", srs, ogr.wkbMultiPolygon)

        # Add 2 multipolygon features
        for i in range(2):
            feature = ogr.Feature(layer.GetLayerDefn())
            wkt = (f"MULTIPOLYGON("
                   f"(({i} {i}, {i+0.5} {i}, {i+0.5} {i+0.5}, {i} {i+0.5}, {i} {i})),"
                   f"(({i+0.6} {i+0.6}, {i+1} {i+0.6}, {i+1} {i+1}, {i+0.6} {i+1}, {i+0.6} {i+0.6}))"
                   f")")
            geom = ogr.CreateGeometryFromWkt(wkt)
            feature.SetGeometry(geom)
            layer.CreateFeature(feature)

        detected_type = handler._detect_geometry_type(layer)
        assert detected_type == "MultiPolygon", f"Expected 'MultiPolygon', got '{detected_type}'"

        ds = None

    def test_mixed_polygon_multipolygon(self, temp_dir):
        """CRITICAL: Mixed POLYGON+MULTIPOLYGON → 'GEOMETRY' (OGC Req 31)"""
        handler = GDALHandler()

        driver = ogr.GetDriverByName("Memory")
        ds = driver.CreateDataSource("test")

        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)

        # Create layer as generic geometry (since we'll add mixed types)
        layer = ds.CreateLayer("mixed_geoms", srs, ogr.wkbUnknown)

        # Add a polygon feature
        polygon_feat = ogr.Feature(layer.GetLayerDefn())
        polygon_wkt = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
        polygon_geom = ogr.CreateGeometryFromWkt(polygon_wkt)
        polygon_feat.SetGeometry(polygon_geom)
        layer.CreateFeature(polygon_feat)

        # Add a multipolygon feature
        multi_feat = ogr.Feature(layer.GetLayerDefn())
        multi_wkt = (
            "MULTIPOLYGON("
            "((0.5 0.5, 0.7 0.5, 0.7 0.7, 0.5 0.7, 0.5 0.5)),"
            "((1.5 1.5, 1.7 1.5, 1.7 1.7, 1.5 1.7, 1.5 1.5))"
            ")"
        )
        multi_geom = ogr.CreateGeometryFromWkt(multi_wkt)
        multi_feat.SetGeometry(multi_geom)
        layer.CreateFeature(multi_feat)

        # MUST return GEOMETRY, not POLYGON (OGC requirement)
        detected_type = handler._detect_geometry_type(layer)
        assert detected_type == "GEOMETRY", (
            f"Mixed POLYGON+MULTIPOLYGON must return 'GEOMETRY' (OGC Req 31), "
            f"got '{detected_type}'"
        )

        ds = None

    def test_mixed_linestring_multilinestring(self):
        """Mixed LINESTRING+MULTILINESTRING → 'GEOMETRY'"""
        handler = GDALHandler()

        driver = ogr.GetDriverByName("Memory")
        ds = driver.CreateDataSource("test")

        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)

        layer = ds.CreateLayer("mixed_lines", srs, ogr.wkbUnknown)

        # Add linestring
        line_feat = ogr.Feature(layer.GetLayerDefn())
        line_geom = ogr.CreateGeometryFromWkt("LINESTRING(0 0, 1 1, 2 0)")
        line_feat.SetGeometry(line_geom)
        layer.CreateFeature(line_feat)

        # Add multilinestring
        multi_feat = ogr.Feature(layer.GetLayerDefn())
        multi_geom = ogr.CreateGeometryFromWkt(
            "MULTILINESTRING((0 0, 1 1), (2 2, 3 3))"
        )
        multi_feat.SetGeometry(multi_geom)
        layer.CreateFeature(multi_feat)

        detected_type = handler._detect_geometry_type(layer)
        assert detected_type == "GEOMETRY"

        ds = None

    def test_null_geometries_ignored(self):
        """NULL geometries are skipped in detection"""
        handler = GDALHandler()

        driver = ogr.GetDriverByName("Memory")
        ds = driver.CreateDataSource("test")

        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)

        layer = ds.CreateLayer("test_nulls", srs, ogr.wkbUnknown)

        # Add feature with NULL geometry
        null_feat = ogr.Feature(layer.GetLayerDefn())
        null_feat.SetGeometry(None)
        layer.CreateFeature(null_feat)

        # Add polygon feature
        poly_feat = ogr.Feature(layer.GetLayerDefn())
        poly_geom = ogr.CreateGeometryFromWkt("POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))")
        poly_feat.SetGeometry(poly_geom)
        layer.CreateFeature(poly_feat)

        # Should detect Polygon (NULL ignored)
        detected_type = handler._detect_geometry_type(layer)
        assert detected_type == "Polygon"

        ds = None

    def test_empty_layer(self):
        """Empty layer (no features) → 'GEOMETRY'"""
        handler = GDALHandler()

        driver = ogr.GetDriverByName("Memory")
        ds = driver.CreateDataSource("test")

        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)

        layer = ds.CreateLayer("empty", srs, ogr.wkbPoint)
        # No features added

        detected_type = handler._detect_geometry_type(layer)
        assert detected_type == "GEOMETRY"

        ds = None


# ============================================================================
# FIX #2: Lock Timeout Tests
# ============================================================================

class TestLockTimeout:
    """Test lock timeout prevents indefinite hangs."""

    def test_create_geopackage_with_timeout(self, temp_dir):
        """create_geopackage accepts timeout parameter"""
        output_path = os.path.join(temp_dir, "test_timeout.gpkg")

        handler = GDALHandler()
        ds = handler.create_geopackage(output_path, lock_timeout=5.0)

        assert ds is not None
        handler.close_geopackage(ds)
        assert os.path.exists(output_path)

    def test_lock_timeout_prevents_indefinite_wait(self, temp_dir):
        """Lock timeout raises TimeoutError when another THREAD holds the lock.

        v0.30.6: rewritten to hold the per-file write lock from a *background
        thread*. The previous version created two handlers on the SAME thread;
        because the write lock is a reentrant RLock, the same thread re-acquired
        it immediately (no timeout) and then hit a Windows file-in-use error
        instead of the intended TimeoutError.
        """
        output_path = os.path.join(temp_dir, "test_lock.gpkg")

        lock = GDALHandler._get_write_lock(output_path)
        acquired = threading.Event()
        release = threading.Event()

        def hold_lock():
            lock.acquire()
            acquired.set()
            release.wait(timeout=10)
            lock.release()

        holder = threading.Thread(target=hold_lock, daemon=True)
        holder.start()
        assert acquired.wait(timeout=5), "background thread never acquired the lock"

        try:
            handler = GDALHandler()
            # The lock is held by another thread, so this must time out.
            with pytest.raises(TimeoutError):
                handler.create_geopackage(output_path, lock_timeout=0.1)
        finally:
            release.set()
            holder.join(timeout=5)

        # v0.30.9: the two lines that used to sit here -
        #     handler1.close_geopackage(ds1)
        # - were leftovers from the pre-v0.30.6 version of this test, which
        # created handler1/ds1 on the same thread. The v0.30.6 rewrite replaced
        # that setup with the background-thread holder above but did not remove
        # the trailing cleanup, leaving two undefined names. The test therefore
        # raised NameError and FAILED even when the timeout behaviour it checks
        # was working correctly. There is nothing to clean up: no handler in
        # this test ever successfully created a dataset.

    def test_lock_released_on_error(self, temp_dir):
        """Lock is released even if operation fails"""
        output_path = os.path.join(temp_dir, "test_error.gpkg")

        handler1 = GDALHandler()
        ds1 = handler1.create_geopackage(output_path, lock_timeout=30.0)

        # v0.30.9: use the v0.30.7 idiom - close_geopackage() returns None, so
        # assigning it back drops the caller's reference in one step.
        #
        # The v0.30.6 comment that used to sit here said the file "stays locked
        # until the last Python reference is dropped (GDAL closes the dataset on
        # garbage collection)". That was a description of the BUG, not of
        # correct behaviour: close_geopackage() ended in `del ds`, which unbound
        # a parameter and closed nothing, so release really was left to the GC.
        # Since v0.30.7 the dataset is flushed and explicitly closed, so this is
        # deterministic and the manual `ds1 = None` dance is no longer load-
        # bearing - it is now just the documented way to use the return value.
        ds1 = handler1.close_geopackage(ds1)
        assert ds1 is None

        # Now lock should be free, another handler should be able to use it
        handler2 = GDALHandler()
        ds2 = handler2.create_geopackage(output_path, lock_timeout=5.0)

        assert ds2 is not None
        ds2 = handler2.close_geopackage(ds2)
        assert ds2 is None

    def test_default_timeout_value(self, temp_dir):
        """Default timeout is 30 seconds"""
        output_path = os.path.join(temp_dir, "test_default.gpkg")

        handler = GDALHandler()

        # Should not raise - using default 30s timeout
        ds = handler.create_geopackage(output_path)

        assert ds is not None
        handler.close_geopackage(ds)


# ============================================================================
# FIX #3: CRS Validation Tests
# ============================================================================

class TestCRSValidation:
    """Test DGIWG CRS validation (Fix #3)."""

    def test_wgs84_approved(self):
        """WGS 84 (EPSG:4326) is DGIWG-approved"""
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)

        # Should not raise
        assert CRSValidator.validate_crs_dgiwg(srs) is True

    def test_web_mercator_approved(self):
        """Web Mercator (EPSG:3857) is DGIWG-approved for tiles.

        v0.30.6: since v0.27.0 the CRS policy is per-data-type. EPSG:3857 is
        NOT allowed for 2D vector layers (Req 9 = 4326 only) but IS allowed for
        raster tiles. Validate against the union ('any') / raster_tiles here.
        """
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(3857)

        assert CRSValidator.validate_crs_dgiwg(srs, data_type="any") is True
        assert CRSValidator.validate_crs_dgiwg(
            srs, data_type="raster_tiles") is True

    def test_utm_zone_approved(self):
        """UTM zones (32633, etc.) are DGIWG-approved for gridded data.

        v0.30.6: UTM is not permitted for 2D vector (Req 9) but is permitted
        for gridded coverages; validate against the union ('any') here.
        """
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(32633)  # UTM Zone 33N

        assert CRSValidator.validate_crs_dgiwg(srs, data_type="any") is True

    def test_invalid_crs_rejected(self):
        """Unknown CRS is rejected with clear error"""
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(2154)  # French Lambert 93 (not approved)

        with pytest.raises(ValidationError) as exc_info:
            CRSValidator.validate_crs_dgiwg(srs)

        assert "DGIWG-approved" in str(exc_info.value)

    def test_no_epsg_code_rejected(self):
        """CRS without EPSG code is rejected"""
        srs = osr.SpatialReference()

        # Create SRS without EPSG code
        srs.SetFromUserInput('+proj=merc')  # Mercator but no EPSG

        with pytest.raises(ValidationError) as exc_info:
            CRSValidator.validate_crs_dgiwg(srs)

        # v0.30.6: GDAL 3.13 may attach a datum authority (EPSG:6326) to a bare
        # proj4 string, so the rejection message can be either "Cannot determine
        # EPSG code" or "EPSG:6326 is not DGIWG-approved". Both mention "EPSG".
        assert "EPSG" in str(exc_info.value)

    def test_null_srs_rejected(self):
        """NULL spatial reference is rejected"""
        with pytest.raises(ValidationError) as exc_info:
            CRSValidator.validate_crs_dgiwg(None)

        assert "no spatial reference" in str(exc_info.value).lower()

    def test_all_utm_zones_approved(self):
        """All 60 UTM zones are approved (union / gridded data types).

        v0.30.6: per-data-type policy - UTM is validated against the union
        ('any'), not the 2D-vector policy (which is 4326-only per Req 9).
        """
        # Test first, middle, and last UTM zones
        test_zones = [32601, 32630, 32660]  # Zones 1, 30, 60

        for zone_code in test_zones:
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(zone_code)

            assert CRSValidator.validate_crs_dgiwg(
                srs, data_type="any") is True

    def test_epsg_code_extraction(self):
        """EPSG code is correctly extracted"""
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)

        epsg = srs.GetAttrValue("AUTHORITY", 1)
        assert epsg == "4326"

    def test_crs_validation_error_messages(self):
        """Error messages are helpful and clear"""
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(2154)  # Invalid CRS

        try:
            CRSValidator.validate_crs_dgiwg(srs)
            assert False, "Should have raised ValidationError"
        except ValidationError as e:
            error_msg = str(e)
            # Should mention what's wrong and what's allowed
            assert "2154" in error_msg or "not DGIWG-approved" in error_msg


# ============================================================================
# Integration Tests
# ============================================================================

class TestCriticalFixesIntegration:
    """Integration tests for all critical fixes working together."""

    def test_geometry_detection_with_crs_validation(self, temp_dir):
        """Geometry detection works with CRS validation"""
        handler = GDALHandler()

        # Create test layer with WGS84 (approved)
        driver = ogr.GetDriverByName("Memory")
        ds = driver.CreateDataSource("test")

        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)

        layer = ds.CreateLayer("test", srs, ogr.wkbUnknown)

        # Add mixed geometries
        polygon_feat = ogr.Feature(layer.GetLayerDefn())
        polygon_feat.SetGeometry(ogr.CreateGeometryFromWkt(
            "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
        ))
        layer.CreateFeature(polygon_feat)

        multipolygon_feat = ogr.Feature(layer.GetLayerDefn())
        multipolygon_feat.SetGeometry(ogr.CreateGeometryFromWkt(
            "MULTIPOLYGON(((2 2, 3 2, 3 3, 2 3, 2 2)))"
        ))
        layer.CreateFeature(multipolygon_feat)

        # Verify geometry detection
        geom_type = handler._detect_geometry_type(layer)
        assert geom_type == "GEOMETRY"

        # Verify CRS validation
        assert CRSValidator.validate_crs_dgiwg(srs) is True

        ds = None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
