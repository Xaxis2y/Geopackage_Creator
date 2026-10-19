# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Regression tests for the v0.34.5 DGIWG fixes.

Covers: geometry-less tables -> 'attributes', BLOB preservation, EPSG
detection (ESRI-only CRS), per-layer reprojection, full DMF rows for the
package and every table, Table 16 srs values, exact bounding boxes, curve
linearization, type coercion and the stricter compliance flag.
"""

import os
import sqlite3

import pytest
from osgeo import ogr, osr

from core import GeoPackageConverter
from core.config import DMF_STANDARD_URI, DGIWG_4326_SRS_NAME
from core.validators import resolve_epsg

ogr.UseExceptions()
osr.UseExceptions()

ARGS = dict(
    title="T", abstract="A", poc="P", org="O", nation="USA",
    security="UNCLASSIFIED", language="eng", topic_category="boundaries",
    ref_date="2026-06-02", generate_reports=False,
)


def _srs(epsg=None, wkt=None):
    s = osr.SpatialReference()
    if epsg:
        s.ImportFromEPSG(epsg)
    else:
        s.ImportFromWkt(wkt)
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


def _make_source(path, layers):
    """layers: list of (name, srs|None, geom_type, [wkt...], blob|None)."""
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    for name, srs, gtype, wkts, blob in layers:
        lyr = ds.CreateLayer(name, srs=srs, geom_type=gtype)
        lyr.CreateField(ogr.FieldDefn("name", ogr.OFTString))
        if blob is not None:
            lyr.CreateField(ogr.FieldDefn("DATA", ogr.OFTBinary))
        for i, wkt in enumerate(wkts):
            f = ogr.Feature(lyr.GetLayerDefn())
            f.SetField("name", f"f{i}")
            if blob is not None:
                f.SetFieldBinaryFromHexString("DATA", blob.hex())
            if wkt:
                f.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
            lyr.CreateFeature(f)
    ds = None
    return path


def _convert(src, out, **kw):
    r = GeoPackageConverter().convert(source_geodatabase=src,
                                      output_geopackage=out, **ARGS, **kw)
    assert r["success"], r.get("error")
    return r


@pytest.fixture
def out(temp_dir):
    return os.path.join(temp_dir, "out.gpkg")


class TestAttributeTablesAndBlobs:
    def test_geometryless_table_becomes_attributes_with_blob(self, temp_dir, out):
        blob = b"\x89PNG\r\n" + bytes(range(200))
        src = _make_source(os.path.join(temp_dir, "s.gpkg"), [
            ("pts", _srs(4326), ogr.wkbPoint, ["POINT(1 2)"], None),
            ("pts__ATTACH", None, ogr.wkbNone, [None, None], blob),
        ])
        _convert(src, out)
        c = sqlite3.connect(out)
        types = dict(c.execute("SELECT table_name, data_type FROM gpkg_contents"))
        assert types["pts__ATTACH"] == "attributes"
        assert c.execute(
            "SELECT COUNT(*) FROM gpkg_geometry_columns WHERE table_name=?",
            ("pts__ATTACH",)).fetchone()[0] == 0
        assert c.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'rtree_pts__ATTACH%'"
        ).fetchone()[0] == 0
        rows = c.execute('SELECT DATA FROM "pts__ATTACH"').fetchall()
        assert len(rows) == 2 and all(bytes(r[0]) == blob for r in rows)


class TestCrsHandling:
    def test_resolve_epsg_root_authority_only(self):
        assert resolve_epsg(_srs(32633)) == 32633
        assert resolve_epsg(_srs(4326)) == 4326
        assert resolve_epsg(None) is None

    def test_resolve_epsg_esri_wkt_matches(self):
        esri = ('GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
                'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
                'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]')
        assert resolve_epsg(_srs(wkt=esri)) == 4326

    def test_non_4326_layer_is_reprojected_and_srs_clean(self, temp_dir, out):
        src = _make_source(os.path.join(temp_dir, "s.gpkg"), [
            ("utm", _srs(32633), ogr.wkbPoint, ["POINT(500000 5000000)"], None),
        ])
        r = _convert(src, out)
        c = sqlite3.connect(out)
        assert c.execute("SELECT srs_id FROM gpkg_geometry_columns").fetchone()[0] == 4326
        assert r["crs_conversion"]["target_epsg"] == 4326
        ods = ogr.Open(out)
        feat = ods.GetLayer(0).GetNextFeature()
        x, y = feat.GetGeometryRef().GetPoint_2D()
        assert 14.9 < x < 15.1 and 45.0 < y < 45.2

    def test_esri_only_crs_layer_gets_clean_epsg_4326(self, temp_dir, out):
        esri = ('GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
                'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
                'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]')
        src = _make_source(os.path.join(temp_dir, "s.gpkg"), [
            ("esri", _srs(wkt=esri), ogr.wkbPoint, ["POINT(10 20)"], None),
        ])
        _convert(src, out)
        c = sqlite3.connect(out)
        assert c.execute("SELECT srs_id FROM gpkg_geometry_columns").fetchone()[0] == 4326
        assert c.execute(
            "SELECT organization FROM gpkg_spatial_ref_sys WHERE srs_id=4326"
        ).fetchone()[0] == "EPSG"

    def test_table16_values(self, temp_dir, out):
        src = _make_source(os.path.join(temp_dir, "s.gpkg"), [
            ("p", _srs(4326), ogr.wkbPoint, ["POINT(1 1)"], None)])
        _convert(src, out)
        name, desc = sqlite3.connect(out).execute(
            "SELECT srs_name, description FROM gpkg_spatial_ref_sys "
            "WHERE srs_id=4326").fetchone()
        assert name == DGIWG_4326_SRS_NAME
        assert desc.startswith("Horizontal component of 3D system.")


class TestGeometryHandling:
    def test_curves_are_linearized(self, temp_dir, out):
        src = os.path.join(temp_dir, "s.gpkg")
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(src)
        lyr = ds.CreateLayer("c", srs=_srs(4326), geom_type=ogr.wkbCurvePolygon)
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetGeometry(ogr.CreateGeometryFromWkt(
            "CURVEPOLYGON(CIRCULARSTRING(0 0,1 1,2 0,1 -1,0 0))"))
        lyr.CreateFeature(f)
        ds = None
        r = _convert(src, out)
        ods = ogr.Open(out)
        feat = ods.GetLayer(0).GetNextFeature()
        g = feat.GetGeometryRef()
        assert g.GetGeometryName() == "POLYGON"
        assert not g.HasCurveGeometry(True)
        assert any("curves" in w for w in r["warnings"])

    def test_type_scanned_beyond_first_500_features(self, temp_dir, out):
        wkts = ["POINT(0 0)"] * 600 + ["LINESTRING(0 0,1 1)"]
        src = os.path.join(temp_dir, "s.gpkg")
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(src)
        lyr = ds.CreateLayer("m", srs=_srs(4326), geom_type=ogr.wkbUnknown)
        for w in wkts:
            f = ogr.Feature(lyr.GetLayerDefn())
            f.SetGeometry(ogr.CreateGeometryFromWkt(w))
            lyr.CreateFeature(f)
        ds = None
        _convert(src, out)
        decl = sqlite3.connect(out).execute(
            "SELECT geometry_type_name FROM gpkg_geometry_columns").fetchone()[0]
        assert decl.upper() == "GEOMETRY"

    def test_z_dropped_with_warning(self, temp_dir, out):
        src = _make_source(os.path.join(temp_dir, "s.gpkg"), [
            ("z", _srs(4326), ogr.wkbPoint25D, ["POINT Z (1 2 30)"], None)])
        r = _convert(src, out)
        assert any("Z/M" in w for w in r["warnings"])

    def test_gpkg_contents_bbox_encloses_float32_rtree(self, temp_dir, out):
        src = _make_source(os.path.join(temp_dir, "s.gpkg"), [
            ("b", _srs(4326), ogr.wkbPoint,
             ["POINT(-75.7000001234567 45.4000007654321)",
              "POINT(-75.6600001234567 45.4100007654321)"], None)])
        _convert(src, out)
        row = sqlite3.connect(out).execute(
            "SELECT min_x,min_y,max_x,max_y FROM gpkg_contents "
            "WHERE table_name='b'").fetchone()
        expected = (-75.7000001234567, 45.4000007654321,
                    -75.6600001234567, 45.4100007654321)
        assert row[0] <= expected[0]
        assert row[1] <= expected[1]
        assert row[2] >= expected[2]
        assert row[3] >= expected[3]


class TestDmfRows:
    def test_package_and_every_table_have_full_dmf_rows(self, temp_dir, out):
        src = _make_source(os.path.join(temp_dir, "s.gpkg"), [
            ("a", _srs(4326), ogr.wkbPoint, ["POINT(1 1)"], None),
            ("t", None, ogr.wkbNone, [None], None)])
        _convert(src, out)
        c = sqlite3.connect(out)
        rows = c.execute(
            "SELECT m.md_standard_uri, r.reference_scope, r.table_name, "
            "r.md_parent_id, m.metadata FROM gpkg_metadata m "
            "JOIN gpkg_metadata_reference r ON r.md_file_id = m.id").fetchall()
        assert {r[0] for r in rows} == {DMF_STANDARD_URI}  # no ISO rows
        roots = [r for r in rows if r[1] == "geopackage"]
        assert len(roots) == 1
        assert {r[2] for r in rows if r[1] == "table"} == {"a", "t"}
        for r in rows:
            assert "metadataStandardName" in r[4]
            assert "<gmd:purpose>" in r[4] and "distributionFormat" in r[4]

    def test_compliance_flag_requires_dmf_and_rtree(self, temp_dir, out):
        src = _make_source(os.path.join(temp_dir, "s.gpkg"), [
            ("a", _srs(4326), ogr.wkbPoint, ["POINT(1 1)"], None)])
        r = _convert(src, out)
        assert r["dgiwg_compliant"] is True
        c = sqlite3.connect(out)
        c.execute("DELETE FROM gpkg_metadata_reference")
        c.commit()
        c.close()
        from core.validators import OutputValidator
        assert OutputValidator.validate_gpkg_structure(out)["compliant"] is False


class TestValidationGate:
    def test_utf8_env_forced(self, monkeypatch, temp_dir):
        from core import validation_gate
        seen = {}

        class _Done:
            returncode = 0
            stderr = ""

        def fake_run(cmd, **kw):
            seen.update(kw["env"])
            return _Done()

        monkeypatch.setattr(validation_gate.subprocess, "run", fake_run)
        monkeypatch.setattr(validation_gate, "find_validator",
                            lambda p=None: __import__("pathlib").Path(temp_dir))
        monkeypatch.setattr(validation_gate, "_find_validator_launcher",
                            lambda v: os.path.join(temp_dir, "x.py"))
        validation_gate.run_dgiwg_validation(os.path.join(temp_dir, "o.gpkg"))
        assert seen.get("PYTHONUTF8") == "1"
        assert seen.get("PYTHONIOENCODING") == "utf-8"
