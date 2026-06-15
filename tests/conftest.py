"""
Pytest configuration and fixtures for GeoPackage Creator tests

Provides:
- Temporary directory fixtures
- Sample geodata fixtures
- Mock GDAL operations
"""

import pytest
import tempfile
import os
import shutil
from pathlib import Path
from osgeo import ogr, osr


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    # Cleanup
    if os.path.exists(tmpdir):
        shutil.rmtree(tmpdir)


@pytest.fixture
def sample_shapefile(temp_dir):
    """Create a sample shapefile for testing."""
    # Create output shapefile path
    shapefile_path = os.path.join(temp_dir, "test_points.shp")

    # Create shapefile with WGS 84 (EPSG:4326) - DGIWG approved
    driver = ogr.GetDriverByName("ESRI Shapefile")
    ds = driver.CreateDataSource(temp_dir)

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)  # WGS 84

    layer = ds.CreateLayer("test_points", srs, ogr.wkbPoint)

    # Add field
    layer.CreateField(ogr.FieldDefn("name", ogr.OFTString))

    # Add features
    for i in range(5):
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetField("name", f"Point_{i}")

        # Create point geometry
        wkt = f"POINT({-120 + i} {40 + i})"
        geom = ogr.CreateGeometryFromWkt(wkt)
        feature.SetGeometry(geom)

        layer.CreateFeature(feature)

    ds = None
    return shapefile_path


@pytest.fixture
def sample_geodatabase(temp_dir):
    """Create a sample File Geodatabase for testing."""
    gdb_path = os.path.join(temp_dir, "test.gdb")

    try:
        # Try to use OpenFileGDB driver (newer GDAL)
        driver = ogr.GetDriverByName("OpenFileGDB")
    except:
        # Fallback to FileGDB if available
        driver = ogr.GetDriverByName("FileGDB")

    if not driver:
        pytest.skip("FileGDB/OpenFileGDB driver not available")

    ds = driver.CreateDataSource(gdb_path)

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)  # WGS 84

    # Create Roads layer
    roads_layer = ds.CreateLayer("Roads", srs, ogr.wkbLineString)
    roads_layer.CreateField(ogr.FieldDefn("road_name", ogr.OFTString))
    roads_layer.CreateField(ogr.FieldDefn("road_class", ogr.OFTString))

    # Create Buildings layer
    buildings_layer = ds.CreateLayer("Buildings", srs, ogr.wkbPolygon)
    buildings_layer.CreateField(ogr.FieldDefn("building_id", ogr.OFTInteger))
    buildings_layer.CreateField(ogr.FieldDefn("building_type", ogr.OFTString))

    # Add sample features to Roads
    for i in range(3):
        feature = ogr.Feature(roads_layer.GetLayerDefn())
        feature.SetField("road_name", f"Road_{i}")
        feature.SetField("road_class", "Primary" if i % 2 == 0 else "Secondary")

        wkt = f"LINESTRING({-120 + i} {40} {-120 + i} {41})"
        geom = ogr.CreateGeometryFromWkt(wkt)
        feature.SetGeometry(geom)

        roads_layer.CreateFeature(feature)

    # Add sample features to Buildings
    for i in range(2):
        feature = ogr.Feature(buildings_layer.GetLayerDefn())
        feature.SetField("building_id", i + 1)
        feature.SetField("building_type", "Commercial" if i == 0 else "Residential")

        wkt = f"POLYGON(({-119 + i} {40} {-119 + i + 0.1} {40} {-119 + i + 0.1} {40.1} {-119 + i} {40.1} {-119 + i} {40}))"
        geom = ogr.CreateGeometryFromWkt(wkt)
        feature.SetGeometry(geom)

        buildings_layer.CreateFeature(feature)

    ds = None
    return gdb_path


@pytest.fixture
def sample_geopackage(temp_dir, sample_shapefile):
    """Create a sample GeoPackage for testing."""
    from osgeo import gdal

    gpkg_path = os.path.join(temp_dir, "test_sample.gpkg")

    # Create GeoPackage
    driver = ogr.GetDriverByName("GPKG")
    ds = driver.CreateDataSource(gpkg_path)

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)

    # Create layer with R-Tree spatial index
    layer = ds.CreateLayer(
        "points",
        srs,
        ogr.wkbPoint,
        options=["SPATIAL_INDEX=YES"]
    )

    # Copy features from shapefile
    shp_ds = ogr.Open(sample_shapefile)
    shp_layer = shp_ds.GetLayer(0)

    for shp_feature in shp_layer:
        layer.CreateFeature(shp_feature)

    shp_ds = None
    ds = None
    return gpkg_path


@pytest.fixture
def sample_geodatabase_with_domains(temp_dir):
    """Create a GDB with domain-constrained fields.

    This fixture creates a more realistic GDB with:
    - Domain-constrained fields (enumerated values)
    - Multiple feature types
    - Real-world data patterns

    Used for testing domain field handling during conversion.
    """
    gdb_path = os.path.join(temp_dir, "test_domains.gdb")

    try:
        driver = ogr.GetDriverByName("OpenFileGDB")
    except:
        driver = ogr.GetDriverByName("FileGDB")

    if not driver:
        pytest.skip("FileGDB/OpenFileGDB driver not available")

    ds = driver.CreateDataSource(gdb_path)

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)  # WGS 84

    # Create Roads layer with domain-constrained field
    roads_layer = ds.CreateLayer("Roads", srs, ogr.wkbLineString)
    roads_layer.CreateField(ogr.FieldDefn("road_name", ogr.OFTString))
    # road_class field will have domain values: Primary, Secondary, Tertiary
    road_class_field = ogr.FieldDefn("road_class", ogr.OFTString)
    road_class_field.SetWidth(20)
    roads_layer.CreateField(road_class_field)

    # speed_limit field (numeric domain)
    speed_field = ogr.FieldDefn("speed_limit_kmh", ogr.OFTInteger)
    roads_layer.CreateField(speed_field)

    # Add features with domain values
    road_classes = ["Primary", "Secondary", "Tertiary"]
    speed_limits = [120, 80, 60]

    for i in range(3):
        feature = ogr.Feature(roads_layer.GetLayerDefn())
        feature.SetField("road_name", f"Highway_{i+1}")
        feature.SetField("road_class", road_classes[i])  # Domain value
        feature.SetField("speed_limit_kmh", speed_limits[i])  # Domain value

        wkt = f"LINESTRING({-120 + i} {40} {-120 + i} {41})"
        geom = ogr.CreateGeometryFromWkt(wkt)
        feature.SetGeometry(geom)

        roads_layer.CreateFeature(feature)

    # Create Buildings layer with subtype field
    buildings_layer = ds.CreateLayer("Buildings", srs, ogr.wkbPolygon)
    buildings_layer.CreateField(ogr.FieldDefn("building_id", ogr.OFTInteger))

    # building_type field will have subtype/domain values
    building_type_field = ogr.FieldDefn("building_type", ogr.OFTString)
    building_type_field.SetWidth(20)
    buildings_layer.CreateField(building_type_field)

    # construction_year field (domain: valid year range)
    year_field = ogr.FieldDefn("construction_year", ogr.OFTInteger)
    buildings_layer.CreateField(year_field)

    # Add building features with domain values
    building_types = ["Commercial", "Residential", "Industrial"]
    construction_years = [2020, 1985, 2010]

    for i in range(3):
        feature = ogr.Feature(buildings_layer.GetLayerDefn())
        feature.SetField("building_id", i + 100)
        feature.SetField("building_type", building_types[i])  # Domain value (subtype)
        feature.SetField("construction_year", construction_years[i])  # Domain value (range)

        wkt = f"POLYGON(({-119 + i*0.15} {40} {-119 + i*0.15 + 0.1} {40} {-119 + i*0.15 + 0.1} {40.1} {-119 + i*0.15} {40.1} {-119 + i*0.15} {40}))"
        geom = ogr.CreateGeometryFromWkt(wkt)
        feature.SetGeometry(geom)

        buildings_layer.CreateFeature(feature)

    # Add Utilities layer to test more complex domain structures
    utilities_layer = ds.CreateLayer("Utilities", srs, ogr.wkbLineString)
    utilities_layer.CreateField(ogr.FieldDefn("utility_id", ogr.OFTString))

    # utility_type field with restricted values
    utility_type_field = ogr.FieldDefn("utility_type", ogr.OFTString)
    utility_type_field.SetWidth(15)
    utilities_layer.CreateField(utility_type_field)

    # status field (domain: Active, Inactive, Planned)
    status_field = ogr.FieldDefn("status", ogr.OFTString)
    status_field.SetWidth(10)
    utilities_layer.CreateField(status_field)

    utility_types = ["Water", "Electric", "Gas"]
    statuses = ["Active", "Inactive", "Planned"]

    for i in range(3):
        feature = ogr.Feature(utilities_layer.GetLayerDefn())
        feature.SetField("utility_id", f"UTIL_{i+1:03d}")
        feature.SetField("utility_type", utility_types[i])  # Domain value
        feature.SetField("status", statuses[i])  # Domain value

        wkt = f"LINESTRING({-121 + i*0.1} {39} {-121 + i*0.1} {40})"
        geom = ogr.CreateGeometryFromWkt(wkt)
        feature.SetGeometry(geom)

        utilities_layer.CreateFeature(feature)

    ds = None
    return gdb_path


@pytest.fixture
def test_metadata():
    """Provide test metadata parameters."""
    return {
        "title": "Test Dataset",
        "abstract": "A test dataset for unit testing",
        "poc": "John Doe",
        "org": "Test Organization",
        "nation": "USA",
        "security": "UNCLASSIFIED",
        "language": "eng",
        "topic_category": "transportation",
        "ref_date": "2026-06-02",
    }
