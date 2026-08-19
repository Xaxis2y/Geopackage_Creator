# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
CRS Conversion Module for GeoPackage Creator v0.34.0

Handles automatic CRS detection, validation, and conversion using GDAL.
Supports three conversion modes:
  - Mode A: Automatic conversion (non-DGIWG CRS → WGS84)
  - Mode B: Multi-version generation (WGS84, Web Mercator, UTM)
  - Mode C: User-specified CRS conversion

Standards:
  - OGC GeoPackage 1.4
  - DGIWG GeoPackage Profile 1.1
"""

import logging
from pathlib import Path
from datetime import datetime
from osgeo import ogr, osr
import shutil
import time

from .config import DGIWG_APPROVED_CRS as _DGIWG_APPROVED_CRS_INT

logger = logging.getLogger(__name__)

# DGIWG Approved CRS — derived from config.py (single source of truth).
# Contains all 62 approved codes: WGS84, Web Mercator, and all 60 NATO UTM zones (32601-32660).
DGIWG_APPROVED_CRS = {f"EPSG:{code}" for code in _DGIWG_APPROVED_CRS_INT}

# Multi-version target CRS
MULTI_VERSION_CRS = [
    {'epsg': 4326, 'name': 'WGS84'},
    {'epsg': 3857, 'name': 'WebMercator'},
    {'epsg': 32633, 'name': 'UTM_33N'},
]


class CRSConverter:
    """Handle CRS detection, validation, and conversion."""

    def __init__(self):
        """Initialize CRS converter."""
        self.conversion_log = []
        self.start_time = None

    def detect_crs(self, input_file):
        """
        Detect CRS from input file.

        Args:
            input_file (str): Path to source file (GDB, Shapefile, GeoJSON)

        Returns:
            dict: {
                'epsg': int,
                'wkt': str,
                'authority_code': str,
                'is_geographic': bool,
                'is_dgiwg_approved': bool
            }
        """
        ds = None
        try:
            ds = ogr.Open(input_file)
            if ds is None:  # v0.30.20: see gdal_handler.create_geopackage()
                raise IOError(f"Cannot open: {input_file}")

            layer = ds.GetLayer(0)
            if not layer:
                raise IOError(f"No layers found: {input_file}")

            srs = layer.GetSpatialRef()
            if not srs:
                # Default to WGS84 if no CRS defined
                logger.warning(f"No CRS defined in {input_file}, defaulting to WGS84")
                srs = osr.SpatialReference()
                srs.ImportFromEPSG(4326)

            # Get EPSG code
            epsg_code = None
            authority_code = srs.GetAuthorityCode(None)
            if authority_code:
                epsg_code = int(authority_code)

            result = {
                'epsg': epsg_code,
                'wkt': srs.ExportToWkt(),
                'authority_code': f"EPSG:{epsg_code}" if epsg_code else "Unknown",
                'is_geographic': srs.IsGeographic(),
                'is_dgiwg_approved': self._is_dgiwg_approved(epsg_code),
                'name': srs.GetAttrValue('PROJCS' if srs.IsProjected() else 'GEOGCS', 0)
            }

            logger.info(f"Detected CRS: EPSG:{epsg_code} ({result['name']})")
            return result

        except Exception as e:
            logger.error(f"Error detecting CRS: {str(e)}")
            raise
        finally:
            ds = None  # BUG-14: always release datasource handle

    def validate_crs_support(self, epsg_code):
        """
        Validate if GDAL supports the CRS.

        Args:
            epsg_code (int): EPSG code

        Returns:
            bool: True if supported, False otherwise
        """
        try:
            srs = osr.SpatialReference()
            result = srs.ImportFromEPSG(epsg_code)
            return result == 0
        except Exception:  # BUG-15: bare except: replaced with except Exception:
            return False

    def _is_dgiwg_approved(self, epsg_code):
        """Check if CRS is in DGIWG whitelist."""
        if epsg_code:
            return f"EPSG:{epsg_code}" in DGIWG_APPROVED_CRS
        return False

    def convert_crs_mode_a(self, input_file, output_dir, source_crs_info):
        """
        Mode A: Automatic conversion.

        If CRS is not DGIWG-approved, automatically convert to WGS84.

        Args:
            input_file (str): Source file path
            output_dir (str): Output directory
            source_crs_info (dict): CRS info from detect_crs()

        Returns:
            dict: {
                'success': bool,
                'output_file': str,
                'converted': bool,
                'source_epsg': int,
                'target_epsg': int,
                'conversion_time': float,
                'message': str
            }
        """
        self.start_time = time.time()
        result = {
            'success': False,
            'output_file': None,
            'converted': False,
            'source_epsg': source_crs_info['epsg'],
            'target_epsg': None,
            'conversion_time': 0,
            'message': ''
        }

        try:
            source_epsg = source_crs_info['epsg']

            # If already DGIWG-approved, no conversion needed
            if source_crs_info['is_dgiwg_approved']:
                result['success'] = True   # BUG-9: was missing — no-op is still a success
                result['converted'] = False
                result['output_file'] = input_file
                result['target_epsg'] = source_epsg
                result['message'] = f"CRS EPSG:{source_epsg} is DGIWG-approved, no conversion needed"
                logger.info(result['message'])
                return result

            # Convert to WGS84
            target_epsg = 4326
            output_file = self._get_output_filename(input_file, output_dir, f"_WGS84")

            self._perform_conversion(input_file, output_file, source_epsg, target_epsg)

            result['success'] = True
            result['converted'] = True
            result['output_file'] = output_file
            result['target_epsg'] = target_epsg
            result['conversion_time'] = time.time() - self.start_time
            result['message'] = f"Converted EPSG:{source_epsg} → EPSG:{target_epsg}"

            logger.info(result['message'])
            return result

        except Exception as e:
            result['message'] = f"Error in Mode A conversion: {str(e)}"
            logger.error(result['message'])
            return result

    def convert_crs_mode_b(self, input_file, output_dir, source_epsg):
        """
        Mode B: Multi-version generation.

        Generate multiple versions in different CRS (WGS84, Web Mercator, UTM).

        Args:
            input_file (str): Source file path
            output_dir (str): Output directory
            source_epsg (int): Source EPSG code

        Returns:
            dict: {
                'success': bool,
                'output_files': [{'epsg': int, 'path': str, 'success': bool}],
                'conversion_time': float,
                'total_files': int,
                'successful': int,
                'failed': int
            }
        """
        self.start_time = time.time()
        result = {
            'success': False,
            'output_files': [],
            'conversion_time': 0,
            'total_files': len(MULTI_VERSION_CRS),
            'successful': 0,
            'failed': 0
        }

        try:
            for target_crs in MULTI_VERSION_CRS:
                target_epsg = target_crs['epsg']
                target_name = target_crs['name']

                try:
                    output_file = self._get_output_filename(
                        input_file, output_dir, f"_{target_name}"
                    )

                    if source_epsg == target_epsg:
                        # Skip if same CRS
                        shutil.copy(input_file, output_file)
                        logger.info(f"Copied (same CRS): {target_name}")
                    else:
                        self._perform_conversion(
                            input_file, output_file, source_epsg, target_epsg
                        )
                        logger.info(f"Converted: {target_name} (EPSG:{target_epsg})")

                    result['output_files'].append({
                        'epsg': target_epsg,
                        'name': target_name,
                        'path': output_file,
                        'success': True
                    })
                    result['successful'] += 1

                except Exception as e:
                    logger.error(f"Error converting to {target_name}: {str(e)}")
                    result['output_files'].append({
                        'epsg': target_epsg,
                        'name': target_name,
                        'path': None,
                        'success': False,
                        'error': str(e)
                    })
                    result['failed'] += 1

            result['success'] = result['successful'] > 0
            result['conversion_time'] = time.time() - self.start_time

            return result

        except Exception as e:
            logger.error(f"Error in Mode B: {str(e)}")
            return result

    def convert_crs_mode_c(self, input_file, output_dir, source_epsg, target_epsg):
        """
        Mode C: User-specified CRS conversion.

        Convert to user-selected target CRS.

        Args:
            input_file (str): Source file path
            output_dir (str): Output directory
            source_epsg (int): Source EPSG code
            target_epsg (int): Target EPSG code

        Returns:
            dict: {
                'success': bool,
                'output_file': str,
                'source_epsg': int,
                'target_epsg': int,
                'conversion_time': float,
                'message': str
            }
        """
        self.start_time = time.time()
        result = {
            'success': False,
            'output_file': None,
            'source_epsg': source_epsg,
            'target_epsg': target_epsg,
            'conversion_time': 0,
            'message': ''
        }

        try:
            # Validate target CRS support
            if not self.validate_crs_support(target_epsg):
                result['message'] = f"Target EPSG:{target_epsg} not supported by GDAL"
                logger.error(result['message'])
                return result

            # Check if conversion needed
            if source_epsg == target_epsg:
                result['success'] = True
                result['output_file'] = input_file
                result['message'] = "Source and target CRS are identical"
                logger.info(result['message'])
                return result

            # Perform conversion
            target_name = f"EPSG{target_epsg}"
            output_file = self._get_output_filename(input_file, output_dir, f"_{target_name}")

            self._perform_conversion(input_file, output_file, source_epsg, target_epsg)

            result['success'] = True
            result['output_file'] = output_file
            result['conversion_time'] = time.time() - self.start_time
            result['message'] = f"Converted EPSG:{source_epsg} → EPSG:{target_epsg}"

            logger.info(result['message'])
            return result

        except Exception as e:
            result['message'] = f"Error in Mode C: {str(e)}"
            logger.error(result['message'])
            return result

    def _perform_conversion(self, input_file, output_file, source_epsg, target_epsg):
        """
        Perform actual CRS conversion using GDAL.

        Args:
            input_file (str): Source file
            output_file (str): Output file
            source_epsg (int): Source EPSG
            target_epsg (int): Target EPSG
        """
        # Open source dataset
        input_ds = ogr.Open(input_file)
        if not input_ds:
            raise IOError(f"Cannot open input: {input_file}")

        # Create target SRS
        target_srs = osr.SpatialReference()
        target_srs.ImportFromEPSG(target_epsg)
        target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

        # Create output GeoPackage dataset
        output_driver = ogr.GetDriverByName('GPKG')
        if not output_driver:
            raise IOError("GDAL GPKG driver not available. Install GDAL with GeoPackage support.")

        output_ds = output_driver.CreateDataSource(output_file)
        if not output_ds:
            raise IOError(f"Cannot create output GeoPackage: {output_file}")

        try:
            # BUG-5: Loop over ALL layers, not just layer 0.
            layer_count = input_ds.GetLayerCount()
            for layer_idx in range(layer_count):
                input_layer = input_ds.GetLayer(layer_idx)
                if not input_layer:
                    continue

                source_srs = input_layer.GetSpatialRef()
                if not source_srs:
                    # Default to WGS84 but warn
                    logger.warning(
                        f"Layer '{input_layer.GetName()}' has no CRS; "
                        f"assuming EPSG:{source_epsg} for transformation."
                    )
                    source_srs = osr.SpatialReference()
                    source_srs.ImportFromEPSG(source_epsg)
                source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

                # Create coordinate transformation
                coord_trans = osr.CoordinateTransformation(source_srs, target_srs)

                # Create output layer
                output_layer = output_ds.CreateLayer(
                    input_layer.GetName(),
                    srs=target_srs,
                    geom_type=input_layer.GetGeomType(),
                    options=["SPATIAL_INDEX=YES"],
                )
                if not output_layer:
                    logger.warning(f"Could not create output layer for '{input_layer.GetName()}'; skipping.")
                    continue

                # Copy field definitions
                input_layer_def = input_layer.GetLayerDefn()
                for i in range(input_layer_def.GetFieldCount()):
                    field_def = input_layer_def.GetFieldDefn(i)
                    output_layer.CreateField(field_def)

                # BUG-16: Wrap feature copy in a single transaction.
                # Without this, each CreateFeature() is its own SQLite
                # commit — orders of magnitude slower on large layers.
                input_layer.ResetReading()
                output_layer.StartTransaction()
                try:
                    input_feature = input_layer.GetNextFeature()
                    while input_feature:
                        output_feature = ogr.Feature(output_layer.GetLayerDefn())

                        # Copy attributes
                        for i in range(input_layer_def.GetFieldCount()):
                            output_feature.SetField(i, input_feature.GetField(i))

                        # Transform geometry
                        geom = input_feature.GetGeometryRef()
                        if geom:
                            geom_clone = geom.Clone()
                            geom_clone.Transform(coord_trans)
                            output_feature.SetGeometry(geom_clone)

                        output_layer.CreateFeature(output_feature)
                        output_feature = None
                        input_feature = input_layer.GetNextFeature()

                    output_layer.CommitTransaction()
                except Exception:
                    output_layer.RollbackTransaction()
                    raise

                logger.info(
                    f"CRS-converted layer '{input_layer.GetName()}' "
                    f"(EPSG:{source_epsg} → EPSG:{target_epsg})"
                )

        finally:
            # BUG-TRUNC: always release both datasource handles so file
            # locks are freed even when an exception occurs mid-conversion.
            input_ds = None
            output_ds = None

    def _get_output_filename(self, input_file, output_dir, suffix):
        """Generate output .gpkg filename in *output_dir* with *suffix* appended.

        Args:
            input_file (str): Source file path (used to derive the stem name).
            output_dir (str): Directory for the output file.
            suffix (str): Suffix to append before the .gpkg extension
                (e.g. '_WGS84', '_WebMercator').

        Returns:
            str: Absolute path to the target .gpkg file.
        """
        stem = Path(input_file).stem
        return str(Path(output_dir) / f"{stem}{suffix}.gpkg")
