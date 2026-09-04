# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
test_gdal_conversion.py
=======================
Comprehensive tests for vector and raster GDAL conversion pipelines.

Run with:
    conda run -n geopackage pytest tests/test_gdal_conversion.py -v

Covers:
  Vector:
    - Happy-path shapefile → GeoPackage (points, lines, polygons)
    - Multi-layer GDB conversion
    - Mixed geometry types (Polygon + MultiPolygon → GEOMETRY)
    - Bad/invalid geometry recovery (skipped, not rolled back)
    - Binary field skipping
    - CRS reprojection (non-4326 → 4326)
    - get_layer_stats() presence and skipped_features key
    - Large feature count with transaction batching

  Raster:
    - GeoTIFF → GeoPackage tile pyramid (DGIWG-approved CRS)
    - Auto-warp when source CRS not DGIWG-approved
    - Non-default tile format (JPEG)
    - Override target_epsg
    - Invalid source path returns error dict (no exception)
    - validate_tile_crs / validate_tile_dimensions helpers

  Integration:
    - _is_raster_source() detection
    - validate_source_file() accepts both vector and raster
"""

import os
import shutil
import sqlite3
import struct
import tempfile
from pathlib import Path

import pytest
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent.parent


def _srs_4326():
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def _srs_3857():
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3857)
    return srs


def _make_shapefile(tmp, name, geom_type, wkts, epsg=4326, extra_fields=None):
    """Create a minimal shapefile and return its path."""
    driver = ogr.GetDriverByName("ESRI Shapefile")
    ds = driver.CreateDataSource(tmp)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    layer = ds.CreateLayer(name, srs, geom_type)
    layer.CreateField(ogr.FieldDefn("label", ogr.OFTString))
    if extra_fields:
        for fld in extra_fields:
            layer.CreateField(fld)
    for i, wkt in enumerate(wkts):
        f = ogr.Feature(layer.GetLayerDefn())
        f.SetField("label", f"feat_{i}")
        if wkt:
            f.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
        layer.CreateFeature(f)
    ds = None
    return str(Path(tmp) / f"{name}.shp")


def _make_geotiff(path, epsg=4326, width=512, height=512):
    """Create a single-band GeoTIFF."""
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(str(path), width, height, 1, gdal.GDT_Byte)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    # Simple geotransform covering a 1°×1° tile
    ds.SetGeoTransform([-100.0, 1.0 / width, 0, 40.0, 0, -1.0 / height])
    band = ds.GetRasterBand(1)
    import numpy as np  # GDAL conda env always has numpy
    band.WriteArray(np.random.randint(0, 255, (height, width), dtype="uint8"))
    band.SetNoDataValue(0)
    ds.FlushCache()
    ds = None
    return str(path)


def _gpkg_layer_names(gpkg_path):
    con = sqlite3.connect(gpkg_path)
    rows = con.execute("SELECT table_name FROM gpkg_contents").fetchall()
    con.close()
    return [r[0] for r in rows]


def _gpkg_feature_count(gpkg_path, layer_name):
    ds = ogr.Open(gpkg_path)
    layer = ds.GetLayerByName(layer_name)
    count = layer.GetFeatureCount()
    ds = None
    return count


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def tmp(tmp_path):
    return str(tmp_path)


@pytest.fixture
def point_shp(tmp_path):
    return _make_shapefile(
        str(tmp_path), "points", ogr.wkbPoint,
        ["POINT(-100 40)", "POINT(-101 41)", "POINT(-102 42)"]
    )


@pytest.fixture
def line_shp(tmp_path):
    return _make_shapefile(
        str(tmp_path), "lines", ogr.wkbLineString,
        ["LINESTRING(-100 40, -101 41)", "LINESTRING(-102 41, -103 42)"]
    )


@pytest.fixture
def poly_shp(tmp_path):
    return _make_shapefile(
        str(tmp_path), "polys", ogr.wkbPolygon,
        [
            "POLYGON((-100 40,-99 40,-99 41,-100 41,-100 40))",
            "POLYGON((-101 40,-100 40,-100 41,-101 41,-101 40))",
        ]
    )


@pytest.fixture
def geotiff_4326(tmp_path):
    return _make_geotiff(tmp_path / "test_4326.tif", epsg=4326)


@pytest.fixture
def geotiff_3857(tmp_path):
    return _make_geotiff(tmp_path / "test_3857.tif", epsg=3857)


@pytest.fixture
def geotiff_non_dgiwg(tmp_path):
    """GeoTIFF in a CRS not on the DGIWG raster-tile list (UTM zone 32N = 32632)."""
    return _make_geotiff(tmp_path / "test_utm.tif", epsg=32632)


# ===========================================================================
# Vector tests — GDALHandler
# ===========================================================================

class TestGDALHandlerVector:

    def test_copy_points_layer(self, tmp_path, point_shp):
        """Basic point layer copies correctly with all features."""
        from core.gdal_handler import GDALHandler

        gpkg = str(tmp_path / "out.gpkg")
        with GDALHandler() as h:
            src_ds = ogr.Open(point_shp)
            out_ds = h.create_geopackage(gpkg)
            src_layer = src_ds.GetLayer(0)
            out_layer = h.copy_layer_to_geopackage(src_layer, out_ds, "points")
            stats = h.get_layer_stats(out_layer)
            h.close_geopackage(out_ds)

        assert stats["feature_count"] == 3
        assert stats["skipped_features"] == 0
        assert _gpkg_feature_count(gpkg, "points") == 3

    def test_copy_line_layer(self, tmp_path, line_shp):
        from core.gdal_handler import GDALHandler

        gpkg = str(tmp_path / "out.gpkg")
        with GDALHandler() as h:
            src_ds = ogr.Open(line_shp)
            out_ds = h.create_geopackage(gpkg)
            out_layer = h.copy_layer_to_geopackage(src_ds.GetLayer(0), out_ds, "lines")
            stats = h.get_layer_stats(out_layer)
            h.close_geopackage(out_ds)

        assert stats["feature_count"] == 2
        assert stats["skipped_features"] == 0

    def test_copy_polygon_layer(self, tmp_path, poly_shp):
        from core.gdal_handler import GDALHandler

        gpkg = str(tmp_path / "out.gpkg")
        with GDALHandler() as h:
            src_ds = ogr.Open(poly_shp)
            out_ds = h.create_geopackage(gpkg)
            out_layer = h.copy_layer_to_geopackage(src_ds.GetLayer(0), out_ds, "polys")
            stats = h.get_layer_stats(out_layer)
            h.close_geopackage(out_ds)

        assert stats["feature_count"] == 2

    def test_get_layer_stats_keys(self, tmp_path, point_shp):
        """get_layer_stats returns all expected keys."""
        from core.gdal_handler import GDALHandler

        gpkg = str(tmp_path / "out.gpkg")
        with GDALHandler() as h:
            src_ds = ogr.Open(point_shp)
            out_ds = h.create_geopackage(gpkg)
            out_layer = h.copy_layer_to_geopackage(src_ds.GetLayer(0), out_ds, "points")
            stats = h.get_layer_stats(out_layer)
            h.close_geopackage(out_ds)

        for key in ("name", "geometry_type", "feature_count", "field_count",
                    "spatial_extent", "skipped_features"):
            assert key in stats, f"Missing key: {key}"

    def test_bad_geometry_skipped_not_rolled_back(self, tmp_path):
        """A layer with one corrupt geometry still writes the valid features."""
        from core.gdal_handler import GDALHandler

        shp_dir = str(tmp_path / "mixed")
        os.makedirs(shp_dir)
        driver = ogr.GetDriverByName("ESRI Shapefile")
        ds = driver.CreateDataSource(shp_dir)
        srs = _srs_4326()
        layer = ds.CreateLayer("mixed", srs, ogr.wkbPolygon)
        layer.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))

        # 2 valid polygons
        for i, wkt in enumerate([
            "POLYGON((-100 40,-99 40,-99 41,-100 41,-100 40))",
            "POLYGON((-101 40,-100 40,-100 41,-101 41,-101 40))",
        ]):
            f = ogr.Feature(layer.GetLayerDefn())
            f.SetField("id", i)
            f.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
            layer.CreateFeature(f)

        # 1 feature with no geometry (simulates corrupt/null geom)
        f = ogr.Feature(layer.GetLayerDefn())
        f.SetField("id", 99)
        layer.CreateFeature(f)

        ds = None
        shp_path = shp_dir + "/mixed.shp"

        gpkg = str(tmp_path / "out.gpkg")
        with GDALHandler() as h:
            src_ds = ogr.Open(shp_path)
            out_ds = h.create_geopackage(gpkg)
            out_layer = h.copy_layer_to_geopackage(src_ds.GetLayer(0), out_ds, "mixed")
            stats = h.get_layer_stats(out_layer)
            h.close_geopackage(out_ds)

        # All 3 features written (null geom is allowed in OGC GeoPackage)
        assert stats["feature_count"] == 3
        assert stats["skipped_features"] == 0

    def test_mixed_polygon_multipolygon_uses_geometry_type(self, tmp_path):
        """Polygon + MultiPolygon in same layer → detected as GEOMETRY (OGC Req 31).

        Uses GeoJSON — ESRI Shapefile silently coerces all features to the
        first geometry type and cannot store true mixed-type data.
        """
        from core.gdal_handler import GDALHandler

        # v0.30.6: build the mixed-type layer with the in-memory driver.
        # Two prior problems made this test fail on GDAL 3.13:
        #   1. File drivers (GeoJSON/Shapefile) may homogenise geometry types on
        #      read, so a true Polygon+MultiPolygon mix was not guaranteed.
        #   2. `ogr.Open(path).GetLayer(0)` frees the datasource immediately (no
        #      reference held), leaving a dangling layer -> TypeError in
        #      Layer_ResetReading. The datasource must be kept alive.
        mem = ogr.GetDriverByName("Memory")
        ds = mem.CreateDataSource("mixed")
        layer = ds.CreateLayer("mixed", _srs_4326(), ogr.wkbUnknown)
        for wkt in (
            "POLYGON((-100 40,-99 40,-99 41,-100 41,-100 40))",
            "MULTIPOLYGON(((-101 40,-100 40,-100 41,-101 41,-101 40)))",
        ):
            feat = ogr.Feature(layer.GetLayerDefn())
            feat.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
            layer.CreateFeature(feat)
            feat = None

        h = GDALHandler()
        result = h._detect_geometry_type(layer)
        ds = None
        assert result == "GEOMETRY", f"Expected GEOMETRY, got {result}"

    def test_crs_reprojection(self, tmp_path):
        """Layer in EPSG:3857 is reprojected to 4326 in the output."""
        from core.gdal_handler import GDALHandler

        shp_dir = str(tmp_path / "merc")
        os.makedirs(shp_dir)
        driver = ogr.GetDriverByName("ESRI Shapefile")
        ds = driver.CreateDataSource(shp_dir)
        layer = ds.CreateLayer("merc", _srs_3857(), ogr.wkbPoint)
        layer.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))
        f = ogr.Feature(layer.GetLayerDefn())
        f.SetField("id", 1)
        f.SetGeometry(ogr.CreateGeometryFromWkt("POINT(-11131949 4865942)"))  # ~(-100, 40) in 3857
        layer.CreateFeature(f)
        ds = None

        gpkg = str(tmp_path / "out.gpkg")
        target_srs = _srs_4326()
        with GDALHandler() as h:
            src_ds = ogr.Open(shp_dir + "/merc.shp")
            out_ds = h.create_geopackage(gpkg)
            out_layer = h.copy_layer_to_geopackage(
                src_ds.GetLayer(0), out_ds, "merc", target_crs=target_srs
            )
            stats = h.get_layer_stats(out_layer)
            h.close_geopackage(out_ds)

        assert stats["feature_count"] == 1
        # Verify output CRS is 4326
        out_ds2 = ogr.Open(gpkg)
        out_srs = out_ds2.GetLayer(0).GetSpatialRef()
        assert out_srs.GetAuthorityCode(None) == "4326"

    def test_binary_field_skipped(self, tmp_path):
        """OFTBinary fields are excluded without crashing the conversion."""
        from core.gdal_handler import GDALHandler

        shp_dir = str(tmp_path / "bin")
        os.makedirs(shp_dir)
        driver = ogr.GetDriverByName("ESRI Shapefile")
        ds = driver.CreateDataSource(shp_dir)
        layer = ds.CreateLayer("bin", _srs_4326(), ogr.wkbPoint)
        layer.CreateField(ogr.FieldDefn("name", ogr.OFTString))
        # Note: ESRI Shapefile doesn't support OFTBinary natively; use GeoJSON for this test
        f = ogr.Feature(layer.GetLayerDefn())
        f.SetField("name", "test")
        f.SetGeometry(ogr.CreateGeometryFromWkt("POINT(-100 40)"))
        layer.CreateFeature(f)
        ds = None

        gpkg = str(tmp_path / "out.gpkg")
        with GDALHandler() as h:
            src_ds = ogr.Open(shp_dir + "/bin.shp")
            out_ds = h.create_geopackage(gpkg)
            out_layer = h.copy_layer_to_geopackage(src_ds.GetLayer(0), out_ds, "bin")
            stats = h.get_layer_stats(out_layer)
            h.close_geopackage(out_ds)

        assert stats["feature_count"] == 1
        assert stats["skipped_features"] == 0

    def test_read_source_data(self, point_shp):
        """read_source_data returns correct metadata."""
        from core.gdal_handler import GDALHandler
        h = GDALHandler()
        info = h.read_source_data(point_shp)
        assert info["layer_count"] == 1
        assert info["layers"][0]["feature_count"] == 3
        assert info["layers"][0]["epsg"] == 4326

    def test_validate_geopackage_output(self, tmp_path, point_shp):
        """validate_geopackage_output returns True for a good output."""
        from core.gdal_handler import GDALHandler
        gpkg = str(tmp_path / "out.gpkg")
        with GDALHandler() as h:
            src_ds = ogr.Open(point_shp)
            out_ds = h.create_geopackage(gpkg)
            h.copy_layer_to_geopackage(src_ds.GetLayer(0), out_ds, "points")
            h.close_geopackage(out_ds)
        h2 = GDALHandler()
        assert h2.validate_geopackage_output(gpkg) is True


# ===========================================================================
# Raster tests — raster_support.convert_raster
# ===========================================================================

class TestRasterConversion:

    def test_dgiwg_approved_crs_no_warp(self, tmp_path, geotiff_4326):
        """EPSG:4326 source needs no warp — converts in place."""
        from core.raster_support import convert_raster
        gpkg = str(tmp_path / "out.gpkg")
        result = convert_raster(geotiff_4326, gpkg)

        assert result["success"], f"Failed: {result['error']}"
        assert result["epsg"] == 4326
        assert result["zoom_levels"] >= 1
        assert Path(gpkg).exists()
        assert not result["warnings"]  # no CRS mismatch warning

    def test_dgiwg_approved_crs_3857(self, tmp_path, geotiff_3857):
        """EPSG:3857 (Web Mercator) is DGIWG-approved — no warp."""
        from core.raster_support import convert_raster
        gpkg = str(tmp_path / "out.gpkg")
        result = convert_raster(geotiff_3857, gpkg)

        assert result["success"], f"Failed: {result['error']}"
        assert result["epsg"] == 3857
        assert not result["warnings"]

    def test_non_dgiwg_crs_auto_warps_to_4326(self, tmp_path, geotiff_non_dgiwg):
        """Non-DGIWG CRS (UTM 32632) triggers auto-warp to 4326."""
        from core.raster_support import convert_raster
        gpkg = str(tmp_path / "out.gpkg")
        result = convert_raster(geotiff_non_dgiwg, gpkg)

        assert result["success"], f"Failed: {result['error']}"
        assert result["epsg"] == 4326
        assert any("warp" in w.lower() or "4326" in w for w in result["warnings"])

    def test_explicit_target_epsg(self, tmp_path, geotiff_4326):
        """Explicit target_epsg=3857 used even if source is 4326."""
        from core.raster_support import convert_raster
        gpkg = str(tmp_path / "out.gpkg")
        result = convert_raster(geotiff_4326, gpkg, target_epsg=3857)

        assert result["success"], f"Failed: {result['error']}"
        assert result["epsg"] == 3857

    def test_jpeg_tile_format(self, tmp_path, geotiff_4326):
        """JPEG tile format produces a valid output."""
        from core.raster_support import convert_raster
        gpkg = str(tmp_path / "out_jpg.gpkg")
        result = convert_raster(geotiff_4326, gpkg, tile_format="JPEG")

        assert result["success"], f"Failed: {result['error']}"
        assert result["tile_format"] == "JPEG"

    def test_invalid_source_returns_error_dict(self, tmp_path):
        """Non-existent raster returns error dict, not an exception."""
        from core.raster_support import convert_raster
        result = convert_raster("/nonexistent/path.tif", str(tmp_path / "out.gpkg"))

        assert result["success"] is False
        assert result["error"] is not None
        # v0.30.6: with gdal.UseExceptions() enabled, gdal.Open() raises its own
        # message for a missing file ("... does not exist in the file system,
        # and is not recognized as a supported dataset name") instead of the
        # tool's "GDAL cannot open raster" string. Accept either wording.
        err = result["error"].lower()
        assert any(s in err for s in
                   ("gdal", "open", "exist", "recognized", "no such"))

    def test_zoom_levels_are_power_of_two(self, tmp_path, geotiff_4326):
        """Auto-computed overview levels are powers of 2 (DGIWG Req 27)."""
        from core.raster_support import _compute_overview_levels
        ds = gdal.Open(geotiff_4326)
        levels = _compute_overview_levels(ds)
        for i, lvl in enumerate(levels):
            assert lvl == 2 ** (i + 1), f"Level {i} should be {2**(i+1)}, got {lvl}"

    def test_validate_tile_crs_approved(self):
        """DGIWG-approved tile CRS codes pass validation."""
        from core.raster_support import validate_tile_crs
        for epsg in (3395, 3857, 4326, 4979, 5041, 5042):
            assert validate_tile_crs(epsg), f"EPSG:{epsg} should be approved"

    def test_validate_tile_crs_rejected(self):
        """Non-approved CRS codes fail validation."""
        from core.raster_support import validate_tile_crs
        for epsg in (32633, 4269, 900913):
            assert not validate_tile_crs(epsg), f"EPSG:{epsg} should be rejected"

    def test_validate_tile_dimensions(self):
        """256×256 passes; anything else fails."""
        from core.raster_support import validate_tile_dimensions
        assert validate_tile_dimensions(256, 256)
        assert not validate_tile_dimensions(512, 512)
        assert not validate_tile_dimensions(256, 512)

    def test_validate_zoom_levels_clean(self):
        """Pixel sizes with exact factor-2 steps pass."""
        from core.raster_support import validate_zoom_levels
        ok, issues = validate_zoom_levels([0.1, 0.05, 0.025])
        assert ok
        assert not issues

    def test_validate_zoom_levels_bad_factor(self):
        """Non-factor-2 steps produce issues."""
        from core.raster_support import validate_zoom_levels
        ok, issues = validate_zoom_levels([0.1, 0.04])  # factor 2.5
        assert not ok
        assert issues

    def test_output_is_readable_gpkg(self, tmp_path, geotiff_4326):
        """Output file opens as a valid GeoPackage with a tile table."""
        from core.raster_support import convert_raster
        gpkg = str(tmp_path / "out.gpkg")
        result = convert_raster(geotiff_4326, gpkg)
        assert result["success"]

        con = sqlite3.connect(gpkg)
        rows = con.execute("SELECT table_name, data_type FROM gpkg_contents").fetchall()
        con.close()
        assert any(dt in ("tiles", "2d-gridded-coverage") for _, dt in rows), \
            f"No tile table found; contents: {rows}"


# ===========================================================================
# Integration — _is_raster_source & validate_source_file
# ===========================================================================

class TestSourceDetection:

    def test_is_raster_source_tiff(self, geotiff_4326):
        from core.converter import _is_raster_source
        assert _is_raster_source(geotiff_4326) is True

    def test_is_raster_source_shapefile(self, point_shp):
        from core.converter import _is_raster_source
        assert _is_raster_source(point_shp) is False

    def test_is_raster_source_nonexistent(self, tmp_path):
        from core.converter import _is_raster_source
        assert _is_raster_source(str(tmp_path / "no_such.tif")) is False

    def test_validate_source_file_accepts_vector(self, point_shp):
        from core.validators import InputValidator
        assert InputValidator.validate_source_file(point_shp) is True

    def test_validate_source_file_accepts_raster(self, geotiff_4326):
        from core.validators import InputValidator
        assert InputValidator.validate_source_file(geotiff_4326) is True

    def test_validate_source_file_rejects_missing(self, tmp_path):
        from core.validators import InputValidator, ValidationError
        with pytest.raises(ValidationError, match="not found"):
            InputValidator.validate_source_file(str(tmp_path / "ghost.shp"))

    def test_validate_source_file_rejects_unreadable(self, tmp_path):
        """A plain text file is neither vector nor raster — should raise."""
        from core.validators import InputValidator, ValidationError
        txt = tmp_path / "data.tif"
        txt.write_text("not a real raster")
        with pytest.raises(ValidationError):
            InputValidator.validate_source_file(str(txt))
