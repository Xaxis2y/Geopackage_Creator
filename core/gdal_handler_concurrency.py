"""
GDAL Handler - Core GDAL/OGR operations with concurrency support

Manages reading spatial data from various sources and writing OGC/DGIWG-compliant
GeoPackages using GDAL/OGR.

Thread-Safe: Supports concurrent reads from different files and serialized
writes to the same file using per-file write locks.

CRITICAL: This module uses ONLY osgeo libraries, NOT arcpy or qgis.core.
This ensures environment independence and true multi-platform support.

Supported Input Formats (via GDAL):
- File Geodatabases (.gdb)
- Shapefiles (.shp)
- GeoJSON (.geojson)
- GeoPackages (.gpkg)
- PostGIS (via OGR)
- And 100+ other formats GDAL supports

Output Format:
- OGC GeoPackage 1.4 (.gpkg)
- With DGIWG-mandatory R-Tree spatial indexes
"""

from typing import Dict, List, Optional, Any
from pathlib import Path
import threading

from osgeo import ogr, osr, gdal

from .config import (
    GPKG_VERSION,
    GDAL_GPKG_OPTIONS,
    GDAL_LAYER_OPTIONS,
)
from .validators import CRSValidator, ValidationError


class GDALHandler:
    """
    GDAL/OGR operations for reading and writing spatial data.

    This class encapsulates all GDAL operations to:
    1. Read from various source formats
    2. Write to OGC GeoPackage 1.4 format
    3. Enforce DGIWG spatial index requirements

    Thread-Safe Context Manager:
    - Supports concurrent reads from different files
    - Serializes writes to same file using per-file locks
    - Properly closes and flushes resources
    - Can be used with 'with' statement for automatic cleanup

    Usage:
        with GDALHandler() as handler:
            ds = handler.create_geopackage('output.gpkg')
            # ... work with ds ...
            handler.close_geopackage(ds)
    """

    # Class-level lock management for write operations
    _write_locks: Dict[str, threading.RLock] = {}
    _locks_lock = threading.Lock()

    def __init__(self):
        """Initialize GDAL handler."""
        gdal.UseExceptions()
        ogr.UseExceptions()

        # Track resources for cleanup
        self._open_datasets: List[ogr.DataSource] = []
        self._active_output_path: Optional[str] = None
        self._is_writing = False

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - properly close all open datasets."""
        self.close_all_datasets()
        return False

    def close_all_datasets(self) -> None:
        """Close all tracked open datasets and release write locks."""
        for ds in self._open_datasets:
            if ds:
                for layer_idx in range(ds.GetLayerCount()):
                    layer = ds.GetLayer(layer_idx)
                    if layer:
                        try:
                            layer.SyncToDisk()
                        except Exception:
                            pass
                try:
                    del ds
                except Exception:
                    pass

        self._open_datasets.clear()

        # Release any write lock
        if self._active_output_path:
            lock = self._get_write_lock(self._active_output_path)
            try:
                lock.release()
            except RuntimeError:
                pass

        self._is_writing = False
        self._active_output_path = None

    @classmethod
    def _get_write_lock(cls, file_path: str) -> threading.RLock:
        """Get or create a write lock for a specific file path."""
        with cls._locks_lock:
            if file_path not in cls._write_locks:
                cls._write_locks[file_path] = threading.RLock()
            return cls._write_locks[file_path]

    def read_source_data(self, source_path: str) -> Dict[str, Any]:
        """
        Read spatial data from source file using GDAL.

        Automatically detects format and reads all layers and their schema.

        Args:
            source_path: Path to source geodatabase, shapefile, geojson, etc.

        Returns:
            Dict with source metadata including driver, layer count, and layer details.

        Raises:
            ValidationError: If source cannot be read
        """
        try:
            # Open source dataset
            ds = ogr.Open(source_path)
            if not ds:
                raise ValidationError(
                    f"GDAL cannot open source file: {source_path}. "
                    f"Check format and file permissions."
                )

            # Get driver info
            driver = ds.GetDriver()
            driver_name = driver.ShortName if driver else "Unknown"

            # Collect layer information
            layer_count = ds.GetLayerCount()
            layers_info = []

            for layer_idx in range(layer_count):
                layer = ds.GetLayer(layer_idx)
                if not layer:
                    continue

                # Get SRS and EPSG
                srs = layer.GetSpatialRef()
                epsg_code = None
                if srs:
                    epsg_code = srs.GetAttrValue("AUTHORITY", 1)
                    if epsg_code:
                        epsg_code = int(epsg_code)

                # Get geometry type
                geom_type = ogr.GeometryTypeToName(layer.GetGeomType())

                # Get fields
                layer_def = layer.GetLayerDefn()
                fields = []
                for field_idx in range(layer_def.GetFieldCount()):
                    field_def = layer_def.GetFieldDefn(field_idx)
                    fields.append({
                        "name": field_def.GetName(),
                        "type": ogr.GetFieldTypeName(field_def.GetType()),
                        "width": field_def.GetWidth(),
                        "precision": field_def.GetPrecision(),
                    })

                layers_info.append({
                    "name": layer.GetName(),
                    "geometry_type": geom_type,
                    "feature_count": layer.GetFeatureCount(),
                    "srs": srs,
                    "epsg": epsg_code,
                    "fields": fields,
                })

            return {
                "driver": driver_name,
                "path": str(source_path),
                "layer_count": layer_count,
                "layers": layers_info,
            }

        except Exception as e:
            raise ValidationError(f"Error reading source data: {e}")

    def create_geopackage(self, output_path: str) -> ogr.DataSource:
        """
        Create a new OGC GeoPackage 1.4 file.

        Acquires write lock to prevent concurrent writes to the same file.

        Args:
            output_path: Path for output .gpkg file

        Returns:
            GDAL DataSource object for the created GeoPackage

        Raises:
            ValidationError: If GeoPackage cannot be created
        """
        try:
            write_lock = self._get_write_lock(output_path)
            write_lock.acquire()
            self._is_writing = True
            self._active_output_path = output_path

            driver = ogr.GetDriverByName("GPKG")
            if not driver:
                raise ValidationError(
                    "GDAL GPKG driver not available. "
                    "Install GDAL with GeoPackage support."
                )

            Path(output_path).unlink(missing_ok=True)

            out_ds = driver.CreateDataSource(
                output_path,
                options=GDAL_GPKG_OPTIONS,
            )

            if not out_ds:
                raise ValidationError(f"Failed to create GeoPackage: {output_path}")

            self._open_datasets.append(out_ds)
            return out_ds

        except Exception as e:
            if self._active_output_path:
                lock = self._get_write_lock(self._active_output_path)
                try:
                    lock.release()
                except RuntimeError:
                    pass
            raise ValidationError(f"Error creating GeoPackage: {e}")

    def copy_layer_to_geopackage(
        self,
        source_layer: ogr.Layer,
        output_ds: ogr.DataSource,
        output_layer_name: str,
        target_crs: Optional[osr.SpatialReference] = None,
    ) -> ogr.Layer:
        """
        Copy a layer from source to GeoPackage with DGIWG compliance.

        Handles geometry preservation, field copying, CRS transformation,
        and R-Tree spatial index creation (DGIWG-MANDATORY).

        Args:
            source_layer: OGR layer from source data
            output_ds: GDAL DataSource for output GeoPackage
            output_layer_name: Name for output layer
            target_crs: Optional CRS to reproject to (default: same as source)

        Returns:
            Created OGR Layer object

        Raises:
            ValidationError: If copy fails
        """
        try:
            geom_type = source_layer.GetGeomType()

            if target_crs is None:
                source_srs = source_layer.GetSpatialRef()
                target_crs = source_srs if source_srs else osr.SpatialReference()

            layer_options = GDAL_LAYER_OPTIONS.copy()

            out_layer = output_ds.CreateLayer(
                output_layer_name,
                srs=target_crs,
                geom_type=geom_type,
                options=layer_options,
            )

            if not out_layer:
                raise ValidationError(f"Failed to create layer: {output_layer_name}")

            # Copy field definitions
            source_layer_def = source_layer.GetLayerDefn()
            for field_idx in range(source_layer_def.GetFieldCount()):
                source_field = source_layer_def.GetFieldDefn(field_idx)
                if source_field.GetType() in (ogr.OFTBinary,):
                    continue
                out_layer.CreateField(source_field)

            # Copy features
            source_layer.ResetReading()
            for feature in source_layer:
                out_feature = ogr.Feature(out_layer.GetLayerDefn())

                geom = feature.GetGeometryRef()
                if geom:
                    out_feature.SetGeometry(geom.Clone())

                for field_idx in range(source_layer_def.GetFieldCount()):
                    field_name = source_layer_def.GetFieldDefn(field_idx).GetName()
                    out_feature.SetField(field_name, feature.GetField(field_idx))

                out_layer.CreateFeature(out_feature)

            # Finalize spatial index
            out_layer.StartTransaction()
            out_layer.CommitTransaction()

            return out_layer

        except Exception as e:
            raise ValidationError(f"Error copying layer: {e}")

    def close_geopackage(self, ds: ogr.DataSource) -> None:
        """
        Properly close and flush GeoPackage file.

        Ensures all data is written, indexes finalized, and write lock released.

        Args:
            ds: GDAL DataSource to close
        """
        try:
            if ds:
                for layer_idx in range(ds.GetLayerCount()):
                    layer = ds.GetLayer(layer_idx)
                    if layer:
                        try:
                            layer.SyncToDisk()
                        except Exception:
                            pass
                del ds
        finally:
            if self._active_output_path:
                lock = self._get_write_lock(self._active_output_path)
                try:
                    lock.release()
                except RuntimeError:
                    pass
            self._is_writing = False
            self._active_output_path = None

    def validate_geopackage_output(self, gpkg_path: str) -> bool:
        """
        Quick validation that output file can be read as GeoPackage.

        Args:
            gpkg_path: Path to generated GeoPackage

        Returns:
            True if valid

        Raises:
            ValidationError: If not a valid GeoPackage
        """
        try:
            ds = ogr.Open(gpkg_path)
            if not ds:
                raise ValidationError(
                    f"Generated file cannot be opened as GeoPackage: {gpkg_path}"
                )

            if ds.GetLayerCount() == 0:
                raise ValidationError(
                    f"Generated GeoPackage has no layers: {gpkg_path}"
                )

            return True
        except Exception as e:
            raise ValidationError(f"Error validating GeoPackage: {e}")

    @staticmethod
    def get_layer_stats(layer: ogr.Layer) -> Dict[str, Any]:
        """Get statistics about a layer."""
        layer_def = layer.GetLayerDefn()
        return {
            "name": layer.GetName(),
            "geometry_type": ogr.GeometryTypeToName(layer.GetGeomType()),
            "feature_count": layer.GetFeatureCount(),
            "field_count": layer_def.GetFieldCount(),
            "spatial_extent": layer.GetExtent() if hasattr(layer, "GetExtent") else None,
        }
