# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
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
import logging
import time

from osgeo import ogr, osr, gdal

from .config import (
    GPKG_VERSION,
    GDAL_GPKG_OPTIONS,
    GDAL_LAYER_OPTIONS,
)
from .validators import CRSValidator, ValidationError

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# v0.30.7: process-global GDAL setup, done ONCE at import.
#
# UseExceptions() flips a PROCESS-GLOBAL flag inside the GDAL/OGR Python
# bindings and swaps the installed CPL error handler. Calling it from
# GDALHandler.__init__ meant every thread that constructed a handler mutated
# that global while other threads were already executing inside GDAL. Doing it
# once, at import, removes the race entirely.
# ---------------------------------------------------------------------------
gdal.UseExceptions()
ogr.UseExceptions()


# ---------------------------------------------------------------------------
# v0.30.7: process-wide conversion lock.
#
# GDAL/OGR makes NO guarantee that two threads may create and populate two
# different datasets at the same time. Thread-safety is per-driver and, for
# most OGR drivers, simply absent - shared driver registrars, shared CPL error
# state and (for GPKG) a shared SQLite layer all sit underneath. Running two
# conversions concurrently is therefore undefined behaviour, and undefined
# behaviour in a C library surfaces as an access violation, not an exception.
#
# The shipped GUI and CLI never run more than one conversion at a time, so
# serializing costs them nothing. Callers who have verified their GDAL build is
# safe for their workload can opt out via config.ALLOW_CONCURRENT_CONVERSIONS.
# ---------------------------------------------------------------------------
_GLOBAL_CONVERSION_LOCK = threading.RLock()


def global_conversion_lock() -> threading.RLock:
    """Return the process-wide conversion lock (see module notes)."""
    return _GLOBAL_CONVERSION_LOCK


def _flush_and_close_dataset(ds) -> None:
    """Flush every layer, then genuinely close *ds*.

    v0.30.7. `del ds` on a local name or a function parameter does NOT close a
    GDAL dataset - it only drops one reference. If the caller still holds the
    same object (which converter.convert() did, for the whole remainder of the
    conversion), the file stays open, buffered and unflushed while later steps
    reopen it through sqlite3. Two live handles on one GeoPackage is how the
    concurrency crash and the file corruption both start.

    GDAL >= 3.7 exposes an explicit Close(); older builds only release on
    refcount drop, so we flush defensively first and let the caller drop its
    reference (close_geopackage returns None for exactly this reason).
    """
    # v0.30.20: `is None` - see create_geopackage() for why a truth test on a
    # dataset handle is unsafe on GDAL <= 3.12 bindings (ogr.DataSource has
    # __len__ but no __bool__, so a 0-layer dataset is falsy).
    if ds is None:
        return

    try:
        for layer_idx in range(ds.GetLayerCount()):
            layer = ds.GetLayer(layer_idx)
            if layer:
                try:
                    layer.SyncToDisk()
                except Exception:
                    logger.debug("SyncToDisk failed for layer %s", layer_idx,
                                 exc_info=True)
    except Exception:
        logger.debug("Could not enumerate layers while closing", exc_info=True)

    try:
        ds.FlushCache()
    except Exception:
        logger.debug("FlushCache failed", exc_info=True)

    # GDAL >= 3.7. Without this the file is only released when the last Python
    # reference disappears, which is not something this module can guarantee.
    close = getattr(ds, "Close", None)
    if callable(close):
        try:
            close()
        except Exception:
            logger.debug("Dataset.Close() failed", exc_info=True)


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
        """Initialize GDAL handler.

        v0.30.7: UseExceptions() is no longer called here - it is process-global
        state and is now applied once at module import. See the module header.
        """
        # Track resources for cleanup
        self._open_datasets: List[ogr.DataSource] = []
        self._active_output_path: Optional[str] = None
        self._is_writing = False

        # v0.30.7: the write lock this handler actually acquired, plus the id of
        # the thread that acquired it. Previously the release path re-derived
        # the lock from _active_output_path and called release() inside a bare
        # `except RuntimeError: pass`. That silently swallowed two distinct
        # failures: releasing a lock this thread never owned, and releasing a
        # lock belonging to a *previous* output path when acquire() itself had
        # raised before _active_output_path was updated. Tracking the lock
        # object and its owner makes both cases detectable.
        self._held_lock: Optional[threading.RLock] = None
        self._held_lock_owner: Optional[int] = None

    def _release_write_lock(self) -> None:
        """Release the write lock this handler holds, if it holds one.

        v0.30.7: replaces four copies of the same swallow-everything release
        block. Only the acquiring thread may release an RLock; anything else is
        a bug worth logging rather than hiding.
        """
        lock = self._held_lock
        if lock is None:
            self._is_writing = False
            self._active_output_path = None
            return

        current = threading.get_ident()
        if self._held_lock_owner != current:
            logger.error(
                "Write lock for %s was acquired by thread %s but release was "
                "attempted from thread %s - refusing to release. This is a bug; "
                "the lock will be leaked rather than corrupting another "
                "thread's write.",
                self._active_output_path, self._held_lock_owner, current,
            )
            return

        try:
            lock.release()
        except RuntimeError:
            logger.error(
                "Write lock for %s could not be released (not held). "
                "This indicates unbalanced acquire/release in the caller.",
                self._active_output_path,
            )
        finally:
            self._held_lock = None
            self._held_lock_owner = None
            self._is_writing = False
            self._active_output_path = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - properly close all open datasets."""
        self.close_all_datasets()
        return False

    def close_all_datasets(self) -> None:
        """Close all tracked open datasets and release write locks.

        v0.30.7: the previous implementation ended each iteration with
        `del ds`, which unbinds the *loop variable* and does nothing to the
        dataset - the next iteration simply rebinds it. Datasets were released
        only incidentally, when _open_datasets.clear() dropped the last
        reference, and only if no other reference survived elsewhere. Now each
        dataset is flushed and explicitly closed.
        """
        for ds in self._open_datasets:
            if ds:
                _flush_and_close_dataset(ds)

        self._open_datasets.clear()
        self._release_write_lock()

    @classmethod
    def _get_write_lock(cls, file_path: str) -> threading.RLock:
        """Get or create a write lock for a specific file path."""
        with cls._locks_lock:
            if file_path not in cls._write_locks:
                cls._write_locks[file_path] = threading.RLock()
            return cls._write_locks[file_path]

    def _detect_geometry_type(self, layer: ogr.Layer, max_samples: int = 500) -> str:
        """
        Detect actual geometry types present in layer (OGC Requirement 31).

        Samples first N features to identify all geometry types in the layer.
        If mixed types detected (e.g., POLYGON + MULTIPOLYGON), returns "GEOMETRY"
        to comply with OGC GeoPackage requirement that prevents having both
        single and multi geometry types in the same layer.

        Args:
            layer: Source OGR layer to analyze
            max_samples: Number of features to sample (default 100)

        Returns:
            OGC geometry type name: "Point", "LineString", "Polygon",
                                   "MultiPoint", "MultiLineString", "MultiPolygon",
                                   or "GEOMETRY" if mixed types detected
        """
        geometry_types = set()

        # Sample features to detect geometry types
        layer.ResetReading()
        for i, feature in enumerate(layer):
            if i >= max_samples:
                break

            geom = feature.GetGeometryRef()
            if geom:
                geom_type = geom.GetGeometryName()  # e.g., "POLYGON", "MULTIPOLYGON"
                geometry_types.add(geom_type)

            feature = None  # Cleanup

        # Reset for next read
        layer.ResetReading()

        if not geometry_types:
            # No geometries found - use GEOMETRY
            return "GEOMETRY"

        # Normalize GDAL type names to OGC names
        type_mapping = {
            "POINT": "Point",
            "MULTIPOINT": "MultiPoint",
            "LINESTRING": "LineString",
            "MULTILINESTRING": "MultiLineString",
            "POLYGON": "Polygon",
            "MULTIPOLYGON": "MultiPolygon",
            "GEOMETRYCOLLECTION": "GeometryCollection",
        }

        normalized_types = {type_mapping.get(t, "GEOMETRY") for t in geometry_types}

        # OGC Requirement 31: Cannot mix POLYGON and MULTIPOLYGON in same layer
        # Must use GEOMETRY instead (same for LineString/MultiLineString, Point/MultiPoint)
        if "Polygon" in normalized_types and "MultiPolygon" in normalized_types:
            return "GEOMETRY"

        if "LineString" in normalized_types and "MultiLineString" in normalized_types:
            return "GEOMETRY"

        if "Point" in normalized_types and "MultiPoint" in normalized_types:
            return "GEOMETRY"

        # Multiple unrelated geometry types → use GEOMETRY
        if len(normalized_types) > 1:
            return "GEOMETRY"

        # Single pure type
        return normalized_types.pop() if normalized_types else "GEOMETRY"

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
            if ds is None:
                raise ValidationError(
                    f"GDAL cannot open source file: {source_path}. "
                    f"Check format and file permissions."
                )

            # Get driver info
            #
            # v0.30.20: use GetName(), not the ShortName attribute. On the
            # pinned GDAL 3.13.2 `ds.GetDriver()` returns a gdal.Driver, which
            # does expose ShortName, so this worked. On GDAL <= 3.12 bindings
            # the same call returns an ogr.Driver, which has NO ShortName
            # attribute at all - raising AttributeError that the enclosing
            # handler then reported as a misleading "Error reading source
            # data". GetName() is present on both, so this is version-neutral.
            driver = ds.GetDriver()
            driver_name = driver.GetName() if driver is not None else "Unknown"

            # Collect layer information
            layer_count = ds.GetLayerCount()
            layers_info = []

            for layer_idx in range(layer_count):
                layer = ds.GetLayer(layer_idx)
                if not layer:
                    continue

                # Get SRS and EPSG.
                # BUG-17: Clone the SRS so the stored object is independent of
                # the DataSource lifetime.  When ds goes out of scope at the end
                # of this method the underlying GDAL dataset is freed; any SRS
                # obtained via GetSpatialRef() without cloning would then point
                # at freed memory, causing crashes or silent wrong values.
                srs = layer.GetSpatialRef()
                if srs:
                    srs = srs.Clone()
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

    def create_geopackage(self, output_path: str, lock_timeout: float = 30.0) -> ogr.DataSource:
        """
        Create a new OGC GeoPackage 1.4 file.

        Acquires write lock to prevent concurrent writes to the same file.
        Uses timeout to prevent indefinite waiting if another process hangs.

        Args:
            output_path: Path for output .gpkg file
            lock_timeout: Maximum seconds to wait for write lock (default 30.0)

        Returns:
            GDAL DataSource object for the created GeoPackage

        Raises:
            ValidationError: If GeoPackage cannot be created or lock timeout occurs
        """
        try:
            write_lock = self._get_write_lock(output_path)

            # CRITICAL FIX #2: Use timeout to prevent indefinite wait
            acquired = write_lock.acquire(timeout=lock_timeout)
            if not acquired:
                raise TimeoutError(
                    f"Could not acquire write lock for {output_path} "
                    f"within {lock_timeout}s. Another process may be writing to this file."
                )

            # v0.30.7: record the lock object and owning thread as soon as the
            # acquire succeeds, so the release path can verify ownership
            # instead of re-deriving the lock from a path that may since have
            # changed.
            self._held_lock = write_lock
            self._held_lock_owner = threading.get_ident()
            self._is_writing = True
            self._active_output_path = output_path

            driver = ogr.GetDriverByName("GPKG")
            if driver is None:
                raise ValidationError(
                    "GDAL GPKG driver not available. "
                    "Install GDAL with GeoPackage support."
                )

            Path(output_path).unlink(missing_ok=True)

            out_ds = driver.CreateDataSource(
                output_path,
                options=GDAL_GPKG_OPTIONS,
            )

            # v0.30.20: `is None`, not a truth test. On GDAL >= 3.13 this call
            # returns a gdal.Dataset, which defines __bool__ -> True, so either
            # form works. On older bindings (<= 3.12) it returns an
            # ogr.DataSource, which defines __len__ (= GetLayerCount()) and NO
            # __bool__ - so Python falls back to __len__ and a freshly created,
            # still-empty GeoPackage evaluates FALSY. `if not out_ds` therefore
            # raised "Failed to create GeoPackage" on complete success under
            # those bindings. Identical behaviour on the pinned 3.13.2; this is
            # purely defensive so the tool degrades sanely if a user's
            # environment resolves an older GDAL.
            if out_ds is None:
                raise ValidationError(f"Failed to create GeoPackage: {output_path}")

            self._open_datasets.append(out_ds)
            return out_ds

        except TimeoutError:
            # v0.30.20: lock contention must stay distinguishable from a real
            # creation failure. The bare `except Exception` below used to catch
            # the TimeoutError raised above and re-raise it as ValidationError,
            # so a caller could not tell "another thread holds the write lock,
            # retry later" apart from "this output path is broken". TimeoutError
            # is an OSError subclass, so it was swallowed silently.
            self._release_write_lock()
            raise
        except Exception as e:
            # v0.30.7: release only the lock this call actually acquired. The
            # old code re-derived a lock from _active_output_path, which on an
            # acquire timeout still held the PREVIOUS path - releasing another
            # conversion's lock.
            self._release_write_lock()
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

        Detects actual geometry types in source layer and handles mixed types
        per OGC Requirement 31 (POLYGON + MULTIPOLYGON → GEOMETRY).

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
            # CRITICAL FIX #1: Detect actual geometry type (handles mixed types)
            detected_geom_type_name = self._detect_geometry_type(source_layer)
            source_layer_def = source_layer.GetLayerDefn()

            # Map geometry type name back to OGR type constant
            geom_type_map = {
                "Point": ogr.wkbPoint,
                "LineString": ogr.wkbLineString,
                "Polygon": ogr.wkbPolygon,
                "MultiPoint": ogr.wkbMultiPoint,
                "MultiLineString": ogr.wkbMultiLineString,
                "MultiPolygon": ogr.wkbMultiPolygon,
                "GEOMETRY": ogr.wkbUnknown,
            }

            geom_type = geom_type_map.get(detected_geom_type_name, ogr.wkbUnknown)

            # Determine target CRS and whether a coordinate transform is needed.
            source_srs = source_layer.GetSpatialRef()
            transform = None
            if target_crs is None:
                # No reprojection requested - keep the source CRS unchanged.
                target_crs = source_srs if source_srs else osr.SpatialReference()
            elif source_srs and not source_srs.IsSame(target_crs):
                # Reproject from the source CRS to the requested target CRS.
                # Force traditional (lon, lat) / (easting, northing) axis order
                # so the GeoPackage stores x=lon, y=lat as the format requires.
                try:
                    source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                    target_crs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                except Exception:
                    pass
                transform = osr.CoordinateTransformation(source_srs, target_crs)

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
            for field_idx in range(source_layer_def.GetFieldCount()):
                source_field = source_layer_def.GetFieldDefn(field_idx)
                if source_field.GetType() in (ogr.OFTBinary,):
                    continue
                out_layer.CreateField(source_field)

            # Copy features inside a SINGLE transaction.
            # Without this, the GPKG driver auto-commits every CreateFeature()
            # as its own disk-syncing SQLite transaction. For large layers
            # (tens/hundreds of thousands of features) that is orders of
            # magnitude slower and looks like the app has hung. Wrapping the
            # whole loop in one transaction keeps it fast.
            #
            # We also log elapsed time and periodic progress so a large layer
            # never looks "frozen" - you can see features streaming in.
            total = source_layer.GetFeatureCount()
            field_count = source_layer_def.GetFieldCount()

            # BUG-8: Build copyable_fields from non-binary source fields ONLY.
            # Binary fields (OFTBinary) are skipped during CreateField above, so
            # they do not exist in the output layer definition. Calling
            # SetField() with a name that doesn't exist raises RuntimeError
            # when UseExceptions() is active, rolling back the entire layer.
            # Store (source_field_index, field_name) tuples so we can copy
            # by position from the source without touching skipped fields.
            copyable_fields = [
                (i, source_layer_def.GetFieldDefn(i).GetName())
                for i in range(field_count)
                if source_layer_def.GetFieldDefn(i).GetType() != ogr.OFTBinary
            ]
            log_every = max(5000, total // 10) if total > 0 else 5000

            logger.info(
                f"    Copying layer '{output_layer_name}': "
                f"{total} feature(s)..."
            )
            layer_start = time.time()

            # ----------------------------------------------------------------
            # Fault-tolerant feature copy
            # Each feature is written inside its own mini-transaction so that
            # one corrupt/invalid geometry cannot roll back an entire layer.
            # Bad features are skipped and counted; the caller receives the
            # skip count so it can surface a warning without treating the
            # whole conversion as a failure.
            # ----------------------------------------------------------------
            source_layer.ResetReading()
            out_layer.StartTransaction()
            try:
                copied = 0
                skipped = 0
                for feature in source_layer:
                    try:
                        out_feature = ogr.Feature(out_layer.GetLayerDefn())

                        geom = feature.GetGeometryRef()
                        if geom:
                            g = geom.Clone()

                            # Attempt geometry repair before writing.
                            # MakeValid() (GDAL >= 3.1) fixes self-intersections,
                            # unclosed rings, and other topology errors that would
                            # otherwise cause OGR to silently drop the geometry or
                            # raise on the SQLite INSERT.
                            if not g.IsValid():
                                try:
                                    fixed = g.MakeValid()
                                    if fixed and not fixed.IsEmpty():
                                        g = fixed
                                    else:
                                        logger.warning(
                                            f"    [{output_layer_name}] feature "
                                            f"fid={feature.GetFID()}: geometry "
                                            f"invalid and MakeValid() returned "
                                            f"empty — writing original."
                                        )
                                except Exception as _mv_err:
                                    logger.debug(
                                        f"    [{output_layer_name}] MakeValid() "
                                        f"unavailable or failed: {_mv_err}"
                                    )

                            # DGIWG 2D vector prohibits Z/M — flatten.
                            g.FlattenTo2D()

                            # Reproject to DGIWG-approved CRS if requested.
                            if transform is not None:
                                g.Transform(transform)

                            out_feature.SetGeometry(g)

                        for src_idx, fname in copyable_fields:
                            out_feature.SetField(fname, feature.GetField(src_idx))

                        out_layer.CreateFeature(out_feature)
                        copied += 1

                    except Exception as feat_err:
                        skipped += 1
                        logger.warning(
                            f"    [{output_layer_name}] skipping feature "
                            f"fid={feature.GetFID() if feature else '?'}: "
                            f"{feat_err}"
                        )

                    if (copied + skipped) % log_every == 0:
                        elapsed = time.time() - layer_start
                        rate = copied / elapsed if elapsed > 0 else 0
                        logger.info(
                            f"      ... {copied}/{total} features written, "
                            f"{skipped} skipped "
                            f"({elapsed:.1f}s, {rate:.0f} feat/s)"
                        )

                out_layer.CommitTransaction()
            except Exception:
                out_layer.RollbackTransaction()
                raise

            elapsed = time.time() - layer_start
            skip_msg = f", {skipped} skipped" if skipped else ""
            logger.info(
                f"    Finished '{output_layer_name}': {copied} feature(s) "
                f"in {elapsed:.1f}s{skip_msg}"
            )
            if skipped:
                logger.warning(
                    f"    [{output_layer_name}] {skipped} feature(s) were "
                    f"skipped due to geometry/field errors — see WARNING lines above."
                )

            # Store skip count on the layer object so the converter can
            # surface it in the result dict.
            try:
                out_layer._skipped_features = skipped
            except Exception:
                pass

            return out_layer

        except Exception as e:
            raise ValidationError(f"Error copying layer: {e}")

    def close_geopackage(self, ds: ogr.DataSource) -> None:
        """
        Properly close and flush GeoPackage file, then release the write lock.

        Ensures all data is written, indexes finalized, and write lock released.

        v0.30.7 (CRASH FIX): this method used to end with `del ds`. `ds` is a
        parameter, so that unbound the local name and nothing else - the
        caller's reference stayed alive and the GeoPackage stayed OPEN. In
        converter.convert() the caller's `out_ds` then remained in scope for the
        entire rest of the conversion, during which the same .gpkg is reopened
        through sqlite3 to embed metadata and apply DGIWG finalization. So the
        file was being written through a second handle while GDAL still had it
        open and buffered - and the write lock had ALREADY been released here,
        so a second thread was free to start its own conversion at the same
        time. That is the access-violation path.

        The method now genuinely closes the dataset and RETURNS None so the
        caller can drop its own reference:

            out_ds = handler.close_geopackage(out_ds)

        Args:
            ds: GDAL DataSource to close

        Returns:
            None - always. Assign it over your reference.
        """
        try:
            # v0.30.20: `is not None`. Under GDAL <= 3.12 bindings a 0-layer
            # dataset is falsy, so this branch was skipped entirely on exactly
            # the handle this method exists to close - leaking the GDAL handle
            # AND leaving the write lock held, which is the failure mode the
            # v0.30.7 notes above describe.
            if ds is not None:
                # BUG-6: Remove from tracking list BEFORE closing so that the
                # __exit__ / close_all_datasets path never double-frees it.
                try:
                    self._open_datasets.remove(ds)
                except ValueError:
                    pass
                _flush_and_close_dataset(ds)
        finally:
            # Order matters: the dataset is fully closed above BEFORE the lock
            # is dropped, so no other writer can open the file while GDAL still
            # holds it.
            self._release_write_lock()

        return None

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
        # BUG-18: use try/finally so the datasource handle is always released.
        # v0.30.6 fix: the finally clause and the general-exception wrapper were
        # missing (the method ended at "except ValidationError: raise"), so a
        # non-GeoPackage input raised a raw GDAL exception instead of a friendly
        # ValidationError and the ds handle was never explicitly released. Both
        # are restored below, matching the intent stated in the comment.
        ds = None
        try:
            ds = ogr.Open(gpkg_path)
            if ds is None:  # v0.30.20: see create_geopackage()
                raise ValidationError(
                    f"Generated file cannot be opened as GeoPackage: {gpkg_path}"
                )

            if ds.GetLayerCount() == 0:
                raise ValidationError(
                    f"Generated GeoPackage has no layers: {gpkg_path}"
                )

            return True
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"Error validating GeoPackage: {e}")
        finally:
            # Always release the datasource handle (frees the file lock).
            ds = None

    @staticmethod
    def get_layer_stats(layer: ogr.Layer) -> Dict[str, Any]:
        """
        Return basic statistics for a layer.

        Includes the skipped-feature count set by copy_layer_to_geopackage()
        so that the converter can surface warnings when features were dropped.

        Args:
            layer: OGR layer (may be from the output GeoPackage)

        Returns:
            Dict with name, geometry_type, feature_count, field_count,
            spatial_extent, and skipped_features.
        """
        layer_def = layer.GetLayerDefn()
        skipped = getattr(layer, "_skipped_features", 0)
        return {
            "name": layer.GetName(),
            "geometry_type": ogr.GeometryTypeToName(layer.GetGeomType()),
            "feature_count": layer.GetFeatureCount(),
            "field_count": layer_def.GetFieldCount(),
            "spatial_extent": layer.GetExtent() if hasattr(layer, "GetExtent") else None,
            "skipped_features": skipped,
        }
