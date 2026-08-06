# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
GDB Domain and Subtype Handling Tests

Tests that verify:
- Domain-constrained fields are converted correctly
- Domain values are preserved during conversion
- Subtype fields are handled properly
- Domain constraints are maintained in output
- Multiple domain types work correctly
"""

import pytest
import os
from osgeo import ogr


class TestGDBDomainFixture:
    """Test the GDB with domains fixture itself."""

    def test_gdb_with_domains_created(self, sample_geodatabase_with_domains):
        """Test that GDB fixture is created successfully."""
        assert sample_geodatabase_with_domains is not None
        assert os.path.exists(sample_geodatabase_with_domains)
        assert sample_geodatabase_with_domains.endswith(".gdb")

    def test_gdb_has_required_layers(self, sample_geodatabase_with_domains):
        """Test that GDB has all expected layers."""
        ds = ogr.Open(sample_geodatabase_with_domains)
        assert ds is not None

        layer_count = ds.GetLayerCount()
        assert layer_count >= 3, "GDB should have at least Roads, Buildings, and Utilities layers"

        layer_names = [ds.GetLayer(i).GetName() for i in range(layer_count)]
        assert "Roads" in layer_names
        assert "Buildings" in layer_names
        assert "Utilities" in layer_names

        ds = None

    def test_roads_layer_has_domain_fields(self, sample_geodatabase_with_domains):
        """Test that Roads layer has domain-constrained fields."""
        ds = ogr.Open(sample_geodatabase_with_domains)
        roads_layer = ds.GetLayerByName("Roads")

        assert roads_layer is not None
        # v0.30.15: OpenFileGDB's write driver does not preserve the
        # single-part/multi-part distinction - a layer created here as
        # wkbLineString reads back as wkbMultiLineString (observed under
        # GDAL 3.13.2 on a real Windows/conda-forge build via
        # run_prerelease_check_v0.30.13.py). Not treated as a product
        # defect or version regression: the shipped tool only ever READS
        # .gdb inputs and never writes one, so this write-then-read-back
        # path only exists to synthesize test input in this fixture, not
        # something a real user's GDB ever goes through. Accept either
        # variant; the point of this test is the field list below, not
        # geometry-type strictness.
        assert roads_layer.GetGeomType() in (ogr.wkbLineString, ogr.wkbMultiLineString), (
            f"Expected LineString or MultiLineString, got {roads_layer.GetGeomType()}"
        )

        # Check for expected fields
        layer_def = roads_layer.GetLayerDefn()
        field_names = [layer_def.GetFieldDefn(i).GetName() for i in range(layer_def.GetFieldCount())]

        assert "road_name" in field_names
        assert "road_class" in field_names  # Domain field
        assert "speed_limit_kmh" in field_names  # Domain field

        ds = None

    def test_roads_features_have_domain_values(self, sample_geodatabase_with_domains):
        """Test that Roads features have valid domain values."""
        ds = ogr.Open(sample_geodatabase_with_domains)
        roads_layer = ds.GetLayerByName("Roads")

        valid_road_classes = ["Primary", "Secondary", "Tertiary"]
        valid_speeds = [120, 80, 60]

        feature_count = 0
        for feature in roads_layer:
            road_class = feature.GetField("road_class")
            speed_limit = feature.GetField("speed_limit_kmh")

            # Verify domain values
            assert road_class in valid_road_classes, f"Invalid road_class: {road_class}"
            assert speed_limit in valid_speeds, f"Invalid speed_limit: {speed_limit}"

            feature_count += 1

        assert feature_count == 3, f"Expected 3 road features, got {feature_count}"
        ds = None

    def test_buildings_layer_has_subtype_fields(self, sample_geodatabase_with_domains):
        """Test that Buildings layer has subtype fields."""
        ds = ogr.Open(sample_geodatabase_with_domains)
        buildings_layer = ds.GetLayerByName("Buildings")

        assert buildings_layer is not None
        # v0.30.15: see the matching note in test_roads_layer_has_domain_fields
        # above - OpenFileGDB's write driver promotes single-part geometries
        # to their Multi- equivalent on read-back; this is a characteristic
        # of the format/driver, not a product or test regression.
        assert buildings_layer.GetGeomType() in (ogr.wkbPolygon, ogr.wkbMultiPolygon), (
            f"Expected Polygon or MultiPolygon, got {buildings_layer.GetGeomType()}"
        )

        layer_def = buildings_layer.GetLayerDefn()
        field_names = [layer_def.GetFieldDefn(i).GetName() for i in range(layer_def.GetFieldCount())]

        assert "building_id" in field_names
        assert "building_type" in field_names  # Subtype field
        assert "construction_year" in field_names  # Domain field

        ds = None

    def test_buildings_features_have_domain_values(self, sample_geodatabase_with_domains):
        """Test that Buildings features have valid domain values."""
        ds = ogr.Open(sample_geodatabase_with_domains)
        buildings_layer = ds.GetLayerByName("Buildings")

        valid_types = ["Commercial", "Residential", "Industrial"]
        valid_years = [2020, 1985, 2010]

        feature_count = 0
        for feature in buildings_layer:
            building_type = feature.GetField("building_type")
            year = feature.GetField("construction_year")

            # Verify domain values
            assert building_type in valid_types, f"Invalid building_type: {building_type}"
            assert year in valid_years, f"Invalid year: {year}"

            feature_count += 1

        assert feature_count == 3, f"Expected 3 building features, got {feature_count}"
        ds = None

    def test_utilities_layer_exists(self, sample_geodatabase_with_domains):
        """Test that Utilities layer exists with domain fields."""
        ds = ogr.Open(sample_geodatabase_with_domains)
        utilities_layer = ds.GetLayerByName("Utilities")

        assert utilities_layer is not None
        # v0.30.15: see the matching note in test_roads_layer_has_domain_fields
        # above.
        assert utilities_layer.GetGeomType() in (ogr.wkbLineString, ogr.wkbMultiLineString), (
            f"Expected LineString or MultiLineString, got {utilities_layer.GetGeomType()}"
        )

        layer_def = utilities_layer.GetLayerDefn()
        field_names = [layer_def.GetFieldDefn(i).GetName() for i in range(layer_def.GetFieldCount())]

        assert "utility_id" in field_names
        assert "utility_type" in field_names  # Domain field
        assert "status" in field_names  # Domain field

        ds = None


class TestDomainFieldConversion:
    """Test domain field handling during conversion."""

    def test_domain_fields_preserved_in_conversion(self, sample_geodatabase_with_domains, temp_dir):
        """Test that domain fields are preserved after conversion to GeoPackage."""
        from core import GeoPackageConverter

        output_gpkg = os.path.join(temp_dir, "converted_domains.gpkg")

        converter = GeoPackageConverter(profile='military')
        result = converter.convert(
            source_geodatabase=sample_geodatabase_with_domains,
            output_geopackage=output_gpkg,
            title="GDB with Domains",
            abstract="Testing domain field conversion",
            poc="Test User",
            org="Test Org",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="transportation",
            ref_date="2026-06-03",
        )

        assert result['success'], f"Conversion failed: {result.get('error')}"
        assert os.path.exists(output_gpkg)
        assert result['layer_count'] >= 3

    def test_domain_values_preserved(self, sample_geodatabase_with_domains, temp_dir):
        """Test that actual domain values are preserved during conversion."""
        from core import GeoPackageConverter

        output_gpkg = os.path.join(temp_dir, "domain_values.gpkg")

        converter = GeoPackageConverter(profile='military')
        result = converter.convert(
            source_geodatabase=sample_geodatabase_with_domains,
            output_geopackage=output_gpkg,
            title="Domain Values Test",
            abstract="Verify domain values preserved",
            poc="User",
            org="Org",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="location",
            ref_date="2026-06-03",
        )

        assert result['success']

        # Check that values are preserved in output
        gpkg_ds = ogr.Open(output_gpkg)
        roads_layer = gpkg_ds.GetLayerByName("Roads")

        if roads_layer:
            valid_classes = ["Primary", "Secondary", "Tertiary"]
            for feature in roads_layer:
                road_class = feature.GetField("road_class")
                if road_class:
                    assert road_class in valid_classes, f"Domain value not preserved: {road_class}"

        gpkg_ds = None

    def test_multiple_domain_types(self, sample_geodatabase_with_domains, temp_dir):
        """Test that multiple domain types are handled correctly."""
        from core import GeoPackageConverter

        output_gpkg = os.path.join(temp_dir, "multi_domains.gpkg")

        converter = GeoPackageConverter(profile='military')
        result = converter.convert(
            source_geodatabase=sample_geodatabase_with_domains,
            output_geopackage=output_gpkg,
            title="Multiple Domains",
            abstract="Test multiple domain types",
            poc="User",
            org="Org",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="utilities",
            ref_date="2026-06-03",
        )

        assert result['success']

        # Verify all layers converted
        gpkg_ds = ogr.Open(output_gpkg)
        layer_count = gpkg_ds.GetLayerCount()
        assert layer_count >= 3, "Should have at least 3 layers"

        gpkg_ds = None


class TestSubtypeHandling:
    """Test subtype field handling."""

    def test_subtype_field_preserved(self, sample_geodatabase_with_domains, temp_dir):
        """Test that subtype fields are properly handled."""
        from core import GeoPackageConverter

        output_gpkg = os.path.join(temp_dir, "subtypes.gpkg")

        converter = GeoPackageConverter(profile='military')
        result = converter.convert(
            source_geodatabase=sample_geodatabase_with_domains,
            output_geopackage=output_gpkg,
            title="Subtype Test",
            abstract="Testing subtype fields",
            poc="User",
            org="Org",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="structure",
            ref_date="2026-06-03",
        )

        assert result['success']

        # Check that building_type (subtype) is present
        gpkg_ds = ogr.Open(output_gpkg)
        buildings = gpkg_ds.GetLayerByName("Buildings")

        if buildings:
            layer_def = buildings.GetLayerDefn()
            field_names = [layer_def.GetFieldDefn(i).GetName() for i in range(layer_def.GetFieldCount())]
            assert "building_type" in field_names, "Subtype field should be preserved"

        gpkg_ds = None

    def test_subtype_values_preserved(self, sample_geodatabase_with_domains, temp_dir):
        """Test that subtype values are preserved during conversion."""
        from core import GeoPackageConverter

        output_gpkg = os.path.join(temp_dir, "subtype_values.gpkg")

        converter = GeoPackageConverter(profile='military')
        result = converter.convert(
            source_geodatabase=sample_geodatabase_with_domains,
            output_geopackage=output_gpkg,
            title="Subtype Values",
            abstract="Verify subtype values",
            poc="User",
            org="Org",
            nation="USA",
            security="UNCLASSIFIED",
            language="eng",
            topic_category="structure",
            ref_date="2026-06-03",
        )

        assert result['success']

        gpkg_ds = ogr.Open(output_gpkg)
        buildings = gpkg_ds.GetLayerByName("Buildings")

        if buildings:
            valid_types = ["Commercial", "Residential", "Industrial"]
            for feature in buildings:
                btype = feature.GetField("building_type")
                if btype:
                    assert btype in valid_types, f"Subtype value not preserved: {btype}"

        gpkg_ds = None


class TestDomainFieldDataTypes:
    """Test different domain field data types."""

    def test_string_domains(self, sample_geodatabase_with_domains):
        """Test string-type domain fields."""
        ds = ogr.Open(sample_geodatabase_with_domains)
        roads = ds.GetLayerByName("Roads")

        layer_def = roads.GetLayerDefn()
        road_class_field = layer_def.GetFieldDefn(layer_def.GetFieldIndex("road_class"))

        assert road_class_field.GetType() == ogr.OFTString

        ds = None

    def test_integer_domains(self, sample_geodatabase_with_domains):
        """Test integer-type domain fields."""
        ds = ogr.Open(sample_geodatabase_with_domains)
        roads = ds.GetLayerByName("Roads")

        layer_def = roads.GetLayerDefn()
        speed_field = layer_def.GetFieldDefn(layer_def.GetFieldIndex("speed_limit_kmh"))

        assert speed_field.GetType() == ogr.OFTInteger

        ds = None

    def test_mixed_domain_types(self, sample_geodatabase_with_domains):
        """Test that layers with mixed domain types work correctly."""
        ds = ogr.Open(sample_geodatabase_with_domains)
        buildings = ds.GetLayerByName("Buildings")

        layer_def = buildings.GetLayerDefn()

        # building_type should be string
        btype_field = layer_def.GetFieldDefn(layer_def.GetFieldIndex("building_type"))
        assert btype_field.GetType() == ogr.OFTString

        # construction_year should be integer
        year_field = layer_def.GetFieldDefn(layer_def.GetFieldIndex("construction_year"))
        assert year_field.GetType() == ogr.OFTInteger

        ds = None


class TestDomainFieldDefaults:
    """Test default value handling in domain fields."""

    def test_domain_default_values(self, sample_geodatabase_with_domains):
        """Test that domain fields can have default values."""
        ds = ogr.Open(sample_geodatabase_with_domains)
        roads = ds.GetLayerByName("Roads")

        # Verify all features have domain values set (no NULL)
        layer_def = roads.GetLayerDefn()
        road_class_idx = layer_def.GetFieldIndex("road_class")

        for feature in roads:
            value = feature.GetField(road_class_idx)
            assert value is not None, "Domain field should have value (no NULL)"

        ds = None


class TestDomainConstraintEnforcement:
    """Test that domain constraints are properly enforced."""

    def test_only_valid_domain_values(self, sample_geodatabase_with_domains):
        """Test that only valid domain values exist in features."""
        ds = ogr.Open(sample_geodatabase_with_domains)

        # Define valid domain values
        road_class_values = {"Primary", "Secondary", "Tertiary"}
        building_type_values = {"Commercial", "Residential", "Industrial"}
        utility_type_values = {"Water", "Electric", "Gas"}
        status_values = {"Active", "Inactive", "Planned"}

        # Check Roads layer
        roads = ds.GetLayerByName("Roads")
        for feature in roads:
            rc = feature.GetField("road_class")
            if rc:
                assert rc in road_class_values, f"Invalid road_class: {rc}"

        # Check Buildings layer
        buildings = ds.GetLayerByName("Buildings")
        for feature in buildings:
            bt = feature.GetField("building_type")
            if bt:
                assert bt in building_type_values, f"Invalid building_type: {bt}"

        # Check Utilities layer
        utilities = ds.GetLayerByName("Utilities")
        for feature in utilities:
            ut = feature.GetField("utility_type")
            st = feature.GetField("status")
            if ut:
                assert ut in utility_type_values, f"Invalid utility_type: {ut}"
            if st:
                assert st in status_values, f"Invalid status: {st}"

        ds = None
