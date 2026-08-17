# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Main GeoPackage Converter Orchestrator

This module provides the primary public API for converting spatial data
to OGC-compliant and DGIWG-compliant GeoPackages.

The GeoPackageConverter class coordinates:
1. Input validation
2. Source data reading (GDAL)
3. GeoPackage creation
4. Metadata generation
5. DGIWG compliance verification
6. Output validation

Usage:
    from geopackage_creator.core import GeoPackageConverter

    converter = GeoPackageConverter(profile='military')
    result = converter.convert(
        source_geodatabase='input.gdb',
        output_geopackage='output.gpkg',
        title='Military Road Network',
        abstract='Vector road network for NATO operations',
        poc='John Smith',
        org='Defense Mapping Agency',
        nation='USA',
        security='CONFIDENTIAL',
        language='eng',
        topic_category='transportation',
        ref_date='2026-06-02',
    )

    if result['success']:
        print(f"GeoPackage created: {result['output_path']}")
        print(f"Layers: {result['layer_count']}")
        print(f"Features: {result['total_features']}")
    else:
        print(f"Error: {result['error']}")
"""

import functools
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

from osgeo import ogr, osr

from .config import (
    CONVERSION_PROFILES,
    METADATA_MIME_TYPE,
    ISO_METADATA_STANDARD_URI,
    DMF_STANDARD_URI,
    DGIWG_APPROVED_CRS,
    DGIWG_CRS_VECTOR_2D,
    GPKG_APPLICATION_ID_DGIWG,
)
# v0.30.7: imported as a MODULE, not `from .config import
# ALLOW_CONCURRENT_CONVERSIONS`. A from-import binds the value once at import
# time, so the documented opt-out (`config.ALLOW_CONCURRENT_CONVERSIONS = True`)
# would have had no effect on an already-imported converter.
from . import config as _config
from .gdal_handler import (
    GDALHandler,
    global_conversion_lock,
    _flush_and_close_dataset,
)
from .metadata_handler import MetadataHandler
from .validators import (
    InputValidator,
    OutputValidator,
    CRSValidator,
    ValidationError,
)
from .crs_converter import CRSConverter
from .report_generator import ReportGenerator
from .raster_support import convert_raster as _convert_raster


# Configure logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def _serialize_conversions(func):
    """Run the wrapped conversion under the process-wide GDAL lock.

    v0.30.7. A conversion is not just the GDAL dataset write - it continues
    through sqlite3 metadata embedding, DGIWG finalization and validation, all
    against the same file. OGR gives no guarantee that two of those sequences
    may run concurrently in one process, and when the guarantee is absent the
    failure mode is a native access violation rather than an exception.

    Serializing costs the shipped GUI and CLI nothing: neither ever starts more
    than one conversion at a time. Callers who have verified their own GDAL
    build and workload can opt out at runtime, and own the result:

        from core import config
        config.ALLOW_CONCURRENT_CONVERSIONS = True
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Read through the module every call, so the flag can be flipped at
        # runtime rather than only before the first import of this module.
        if getattr(_config, "ALLOW_CONCURRENT_CONVERSIONS", False):
            return func(*args, **kwargs)
        with global_conversion_lock():
            return func(*args, **kwargs)
    return wrapper



# ---------------------------------------------------------------------------
# Raster detection helper
# ---------------------------------------------------------------------------
_RASTER_EXTENSIONS = {
    ".tif", ".tiff", ".geotiff",
    ".img", ".vrt", ".nc", ".hdf", ".h5",
    ".ecw", ".jp2", ".j2k",
    ".dem", ".asc", ".bil", ".bip", ".bsq",
    ".sid", ".png", ".jpg", ".jpeg",
}

def _is_raster_source(source_path: str) -> bool:
    """Return True when *source_path* looks like a raster (not a vector) file.

    Detection is extension-first (fast), then GDAL-Open fallback:
    - If gdal.Open() succeeds and ogr.Open() fails → raster.
    - If both succeed → treat as vector (most overlap cases).
    - If the path is a directory (.gdb) → always vector.
    """
    from pathlib import Path as _Path
    from osgeo import gdal as _gdal, ogr as _ogr

    p = _Path(source_path)
    if p.is_dir():
        return False  # .gdb and similar are always vector

    ext = p.suffix.lower()
    if ext in _RASTER_EXTENSIONS:
        # Quick extension hit — confirm via GDAL open.
        # UseExceptions() is active: wrap so a missing/unreadable file
        # returns False rather than raising.
        try:
            ds = _gdal.Open(source_path)
            if ds is not None:
                ds = None
                return True
        except Exception:
            return False

    # Fallback: try ogr; if it raises/fails but gdal succeeds → raster.
    # UseExceptions() means both opens can raise — treat any exception
    # from ogr as "not vector" and try gdal next.
    try:
        vec_ds = _ogr.Open(source_path)
        if vec_ds is not None:
            vec_ds = None
            return False  # readable as vector
    except Exception:
        pass  # not a vector — fall through to raster check

    try:
        ras_ds = _gdal.Open(source_path)
        if ras_ds is not None:
            ras_ds = None
            return True
    except Exception:
        pass

    return False


class GeoPackageConverter:
    """
    Main converter class orchestrating GeoPackage creation.

    Coordinates all modules (GDAL, validators, metadata) to produce
    OGC 1.4 and DGIWG-compliant GeoPackages from various source formats.

    Attributes:
        profile (str): Conversion profile name (default, military, civilian, etc.)
        gdal_handler (GDALHandler): GDAL/OGR operations
        input_validator (InputValidator): Input validation
        output_validator (OutputValidator): Output validation
    """

    def __init__(self, profile: str = "default"):
        """
        Initialize GeoPackageConverter.

        Args:
            profile: Conversion profile name. Must be one of:
                - 'default': Standard settings
                - 'military': Military/DGIWG profile
                - 'civilian': Civilian GIS profile
                - 'high_security': Enhanced security constraints

        Raises:
            ValueError: If profile not recognized
        """
        if profile not in CONVERSION_PROFILES:
            raise ValueError(
                f"Unknown profile: {profile}. "
                f"Available: {', '.join(CONVERSION_PROFILES.keys())}"
            )

        self.profile = profile
        self.profile_config = CONVERSION_PROFILES[profile]
        self.gdal_handler = GDALHandler()
        self.input_validator = InputValidator()
        self.output_validator = OutputValidator()
        self.crs_converter = CRSConverter()
        self.report_generator = ReportGenerator()
        self.metadata_handler = MetadataHandler()

        logger.info(f"Initialized converter with profile: {profile}")

    # ------------------------------------------------------------------
    # Public introspection helpers
    #
    # v0.30.6 fix: these three methods were unintentionally dropped from
    # converter.py during the v0.30.1 hot-fix that removed an unterminated
    # triple-quoted docstring (the whole method block was deleted along with
    # the broken docstring). They are part of the public API and are exercised
    # by tests/test_converter.py, so their absence broke five unit tests with
    # AttributeError. They are restored here unchanged in behaviour.
    # ------------------------------------------------------------------
    @staticmethod
    def list_available_profiles() -> List[str]:
        """Return the names of all built-in conversion profiles.

        Returns:
            List of profile name strings, e.g.
            ['default', 'military', 'civilian', 'high_security'].
        """
        return list(CONVERSION_PROFILES.keys())

    def get_active_profile_config(self) -> Dict[str, Any]:
        """Return the active profile name and its configuration.

        Returns:
            Dict of the form::

                {"profile": <active profile name>,
                 "config": {<profile defaults>}}

            where ``config`` holds the security_level, language,
            topic_category and spatial_index defaults for the active profile.
        """
        return {
            "profile": self.profile,
            "config": dict(self.profile_config),
        }

    @staticmethod
    def get_supported_input_formats() -> List[str]:
        """Return the vector input formats the installed GDAL/OGR can read.

        The list is derived from the OGR driver registry at runtime, so it
        reflects the capabilities of the actual GDAL build in use. Typical
        entries include 'ESRI Shapefile', 'GeoJSON', 'GPKG', and
        'OpenFileGDB' / 'FileGDB'.

        Returns:
            Sorted list of unique OGR driver names.
        """
        formats = set()
        try:
            driver_count = ogr.GetDriverCount()
            for i in range(driver_count):
                driver = ogr.GetDriver(i)
                if driver is not None:
                    name = driver.GetName()
                    if name:
                        formats.add(name)
        except Exception as exc:  # pragma: no cover - depends on GDAL build
            logger.warning(f"Could not enumerate OGR drivers: {exc}")
        return sorted(formats)

    @_serialize_conversions
    def convert(
        self,
        source_geodatabase: str,
        output_geopackage: str,
        title: str,
        abstract: str,
        poc: str,
        org: str,
        nation: str,
        security: Optional[str] = None,
        language: Optional[str] = None,
        topic_category: Optional[str] = None,
        ref_date: Optional[str] = None,
        data_quality: Optional[str] = None,
        lineage: Optional[str] = None,
        crs_conversion_mode: Optional[str] = None,
        crs_target_epsg: Optional[int] = None,
        generate_reports: bool = True,
        strict_crs_validation: bool = False,
        dgiwg_reproject: bool = True,
        dgiwg_target_epsg: int = 4326,
        releasability: Optional[str] = None,
        run_dgiwg_validation: bool = False,
        dgiwg_validator_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convert spatial data to OGC/DGIWG-compliant GeoPackage.

        This is the main entry point. It orchestrates the entire conversion workflow:
        1. Validate all inputs
        2. Validate source file
        3. Validate output path
        4. Read source data via GDAL
        5. Validate input CRS against DGIWG whitelist
        6. Create GeoPackage
        7. Copy layers with DGIWG options
        8. Generate and embed metadata
        9. Validate output compliance
        10. Return results

        Args:
            source_geodatabase: Path to source .gdb, .shp, .geojson, etc.
            output_geopackage: Path for output .gpkg file
            title: Dataset title (ISO 19115)
            abstract: Dataset description
            poc: Point of contact (individual name)
            org: Organization/agency name
            nation: ISO 3166-1 alpha-3 country code (e.g., 'USA', 'GBR')
            security: Security classification (UNCLASSIFIED, CONFIDENTIAL, SECRET, etc.)
                Defaults to profile setting if not provided
            language: ISO 639-2 language code (e.g., 'eng', 'fra')
                Defaults to profile setting if not provided
            topic_category: ISO 19115 topic category
                Defaults to profile setting if not provided
            ref_date: Reference/publication date (YYYY-MM-DD format)
                Defaults to today if not provided
            data_quality: Quality statement (optional)
            lineage: Data lineage/source information (optional)
            strict_crs_validation: If True, abort conversion when a layer has a
                non-DGIWG-approved CRS instead of just warning (default: False)
            crs_conversion_mode: CRS conversion mode ('a', 'b', 'c', or None)
                'a': Auto-convert non-DGIWG CRS to WGS84
                'b': Generate multiple versions (WGS84, WebMercator, UTM)
                'c': Convert to user-specified EPSG code
                None: No conversion (default)
            crs_target_epsg: Target EPSG code for mode 'c' (e.g., 32633)
            generate_reports: Generate HTML/JSON/PDF reports (default: True)

        Returns:
            Dict with conversion results:
            {
                'success': bool,
                'output_path': str (if successful),
                'output_files': [str] (multiple files if crs_conversion_mode='b'),
                'layer_count': int,
                'total_features': int,
                'layers': [...],
                'dgiwg_compliant': bool,
                'r_tree_indexes': bool,
                'crs_conversion': {'mode': str, 'source': int, 'target': int, 'success': bool},
                'reports': {'html': str, 'json': str, 'pdf': str},
                'performance': {'duration': float, 'memory': float},
                'warnings': [str],
                'error': str (if unsuccessful),
            }
        """
        result = {
            "success": False,
            "warnings": [],
            "error": None,
            "output_path": None,
            "output_files": [],
            "layer_count": 0,
            "total_features": 0,
            "layers": [],
            "dgiwg_compliant": False,
            "r_tree_indexes": False,
            "crs_conversion": {
                "mode": crs_conversion_mode,
                "source_epsg": None,
                "target_epsg": None,
                "success": False,
            },
            "reports": {
                "html": None,
                "json": None,
                "pdf": None,
            },
            "performance": {
                "start_time": datetime.now().isoformat(),
                "duration": 0,
                "memory_used": 0,
            },
        }

        conversion_start_time = time.time()

        try:
            # Step 1: Apply profile defaults
            logger.info(f"Applying profile defaults: {self.profile}")
            security = security or self.profile_config.get("security_level")
            language = language or self.profile_config.get("language")
            topic_category = topic_category or self.profile_config.get("topic_category")
            ref_date = ref_date or datetime.now().strftime("%Y-%m-%d")

            # Step 2: Validate all inputs
            logger.info("Validating inputs...")
            self.input_validator.validate_security_level(security)
            self.input_validator.validate_language_code(language)
            # QUALITY-10: normalise to canonical ISO 639-2 lowercase so the
            # generated XML passes the Req 18 ISO-639-2 pattern check.
            language = self.input_validator.normalise_language_code(language)
            self.input_validator.validate_nation_code(nation)
            self.input_validator.validate_topic_category(topic_category)
            self.input_validator.validate_source_file(source_geodatabase)
            self.input_validator.validate_output_path(output_geopackage)

            # Step 2b: Detect raster vs vector and branch early
            if _is_raster_source(source_geodatabase):
                logger.info(f"Detected raster source: {source_geodatabase}")
                raster_result = _convert_raster(
                    source_raster=source_geodatabase,
                    output_geopackage=output_geopackage,
                    tile_format="PNG",
                )
                result["success"] = raster_result["success"]
                result["output_path"] = raster_result["output_path"]
                result["output_files"] = [raster_result["output_path"]]
                result["warnings"].extend(raster_result.get("warnings", []))
                result["layer_count"] = raster_result.get("zoom_levels", 0)
                result["performance"]["duration"] = raster_result.get("elapsed_seconds", 0)
                if not raster_result["success"]:
                    result["error"] = raster_result.get("error", "Raster conversion failed")
                return result

            # Step 3: Read source data (vector path)
            logger.info(f"Reading source data: {source_geodatabase}")
            source_info = self.gdal_handler.read_source_data(source_geodatabase)
            logger.info(
                f"Source has {source_info['layer_count']} layer(s), "
                f"driver: {source_info['driver']}"
            )

            # Step 4: Validate CRS for all layers against DGIWG requirements
            logger.info("Validating CRS against DGIWG whitelist...")
            source_ds = ogr.Open(source_geodatabase)
            if source_ds is None:  # v0.30.20: see gdal_handler.create_geopackage()
                raise ValidationError(f"Cannot open source file: {source_geodatabase}")

            try:
                for layer_info in source_info["layers"]:
                    try:
                        # BUG-4: SRS refs in source_info come from the first
                        # (now-closed) datasource opened inside read_source_data.
                        # Re-derive the SRS from the freshly opened source_ds so
                        # we never dereference a stale GDAL pointer.
                        live_layer = source_ds.GetLayerByName(layer_info["name"])
                        srs = live_layer.GetSpatialRef() if live_layer else layer_info.get("srs")
                        CRSValidator.validate_crs_dgiwg(srs)
                        logger.info(f"  ✓ Layer '{layer_info['name']}': EPSG:{layer_info['epsg']} (DGIWG-approved)")
                    except ValidationError as e:
                        if strict_crs_validation:
                            raise ValidationError(
                                f"CRS validation failed (strict mode) for layer "
                                f"'{layer_info['name']}': {e}"
                            )
                        result["warnings"].append(str(e))
                        logger.warning(f"  ✗ {e}")

                # Steps 5-7: Create GeoPackage and copy layers within context manager.
                # This ensures write locks are properly acquired and released.
                with GDALHandler() as handler:
                    # Step 5: Create GeoPackage
                    logger.info(f"Creating GeoPackage: {output_geopackage}")
                    out_ds = handler.create_geopackage(output_geopackage)

                    # Step 5b: Determine a DGIWG-approved target CRS.
                    # v0.27.0: the output of this tool is 2D vector layers
                    # (geometries are flattened to 2D on copy), and DGIWG Req 9
                    # allows ONLY EPSG:4326 for 2D vector data. The reprojection
                    # trigger therefore uses the vector_2d policy - NOT the union
                    # of all DGIWG CRS. A source layer in e.g. EPSG:3857 or a UTM
                    # zone (valid for tiles/gridded only) is also reprojected.
                    target_srs = None
                    if dgiwg_reproject:
                        source_epsgs = {
                            l.get("epsg") for l in source_info["layers"]
                            if l.get("epsg")
                        }
                        non_approved = sorted(
                            e for e in source_epsgs
                            if e not in DGIWG_CRS_VECTOR_2D
                        )
                        if non_approved:
                            target_srs = osr.SpatialReference()
                            target_srs.ImportFromEPSG(dgiwg_target_epsg)
                            target_srs.SetAxisMappingStrategy(
                                osr.OAMS_TRADITIONAL_GIS_ORDER
                            )
                            result["crs_conversion"]["source_epsg"] = (
                                non_approved[0] if len(non_approved) == 1
                                else None
                            )
                            result["crs_conversion"]["target_epsg"] = dgiwg_target_epsg
                            result["crs_conversion"]["success"] = True
                            logger.info(
                                f"Reprojecting non-DGIWG CRS {non_approved} to "
                                f"DGIWG-approved EPSG:{dgiwg_target_epsg}"
                            )

                    # Step 6: Copy layers
                    logger.info(f"Copying {source_info['layer_count']} layer(s)...")
                    layers_created = []
                    total_features = 0

                    for source_layer_info in source_info["layers"]:
                        source_layer = source_ds.GetLayer(source_layer_info["name"])
                        if not source_layer:
                            result["warnings"].append(
                                f"Could not find layer: {source_layer_info['name']}"
                            )
                            continue

                        try:
                            out_layer = handler.copy_layer_to_geopackage(
                                source_layer=source_layer,
                                output_ds=out_ds,
                                output_layer_name=source_layer_info["name"],
                                target_crs=target_srs,
                            )

                            layer_stats = handler.get_layer_stats(out_layer)
                            layers_created.append(layer_stats)
                            total_features += layer_stats["feature_count"]

                            skipped = layer_stats.get("skipped_features", 0)
                            if skipped:
                                result["warnings"].append(
                                    f"Layer '{source_layer_info['name']}': "
                                    f"{skipped} feature(s) skipped due to "
                                    f"geometry/field errors."
                                )

                            logger.info(
                                f"  ✓ Layer '{source_layer_info['name']}': "
                                f"{layer_stats['feature_count']} features"
                                + (f" ({skipped} skipped)" if skipped else "")
                            )

                        except Exception as e:
                            result["warnings"].append(
                                f"Error copying layer '{source_layer_info['name']}': {e}"
                            )
                            logger.warning(f"  ✗ {e}")

                    if not layers_created:
                        raise ValidationError("No layers were successfully copied")

                    # Step 7: Close GeoPackage to flush changes
                    #
                    # v0.30.7 (CRASH FIX): the return value MUST be assigned
                    # back over out_ds. close_geopackage() closes the dataset
                    # and returns None; without this assignment the local
                    # reference kept the GeoPackage open for the whole rest of
                    # this method, while the steps below reopen the very same
                    # file through sqlite3 to embed metadata and finalize DGIWG
                    # compliance. Two live handles on one file, with the write
                    # lock already released, is what produced the native access
                    # violation under concurrency.
                    logger.info("Finalizing GeoPackage...")
                    out_ds = handler.close_geopackage(out_ds)

                # Context manager has exited — write lock released.
            finally:
                # W-5 fix: always close source_ds to avoid resource leak
                source_ds = None

            # Step 7b: Generate and embed ISO 19115 metadata (DGIWG-mandatory).
            # v0.26 fix (BUG-6): metadata was generated but never written into
            # the GeoPackage. It is now embedded via the OGC metadata extension
            # (gpkg_metadata / gpkg_metadata_reference + gpkg_extensions rows).
            logger.info("Generating ISO 19115 metadata...")
            package_xml = self.metadata_handler.generate_package_metadata(
                title=title,
                abstract=abstract,
                poc=poc,
                org=org,
                nation=nation,
                security=security,
                language=language,
                topic_category=topic_category,
                ref_date=ref_date,
                data_quality=data_quality,
                lineage=lineage,
                releasability=releasability,
            )

            # v0.27.0: DGIWG Metadata Foundation (DMF) record (Req 18).
            # A dedicated gpkg_metadata row with the DMF standard URI is the
            # only way Req 18 fully PASSes; the ISO 19139 row alone yields
            # PASS* ("no DMF row found").
            logger.info("Generating DGIWG DMF metadata record...")
            dmf_xml = self.metadata_handler.generate_dmf_metadata(
                title=title,
                abstract=abstract,
                org=org,
                nation=nation,
                security=security,
                language=language,
                ref_date=ref_date,
                releasability=releasability,
            )
            try:
                self.metadata_handler.validate_schema(package_xml)
            except ValueError as e:
                result["warnings"].append(
                    f"Metadata XSD validation warning: {e}"
                )

            layer_metadata = {}
            for layer_stats in layers_created:
                layer_metadata[layer_stats["name"]] = (
                    self.metadata_handler.generate_layer_metadata(
                        layer_name=layer_stats["name"],
                        poc=poc,
                        org=org,
                        nation=nation,
                        security=security,
                        language=language,
                        ref_date=ref_date,
                    )
                )

            logger.info("Embedding metadata into GeoPackage...")
            result["metadata_embedded"] = self._embed_metadata(
                output_geopackage, package_xml, layer_metadata,
                dmf_xml=dmf_xml,
            )

            # Step 7c: Finalize DGIWG compliance at the SQLite level.
            # This guarantees the output satisfies DGIWG Req 3 (mandatory
            # extensions + GeoPackage version marker) and Req 13 (WKT2 CRS
            # definitions) regardless of the exact GDAL build behaviour:
            #   * sets application_id to the OGC-standard 'GPKG' marker
            #   * ensures the gpkg_spatial_ref_sys.definition_12_063 (WKT2)
            #     column exists and holds authoritative WKT2 for every
            #     approved CRS (correct axis order + datum names)
            #   * registers the gpkg_crs_wkt extension
            #   * drops orphan, non-approved CRS rows left unreferenced after
            #     reprojection
            logger.info("Finalizing DGIWG compliance (application_id, WKT2, gpkg_crs_wkt)...")
            try:
                finalize_info = self._finalize_dgiwg_compliance(output_geopackage)
                result["dgiwg_finalized"] = finalize_info
            except Exception as e:
                logger.warning(f"DGIWG finalization warning: {e}")
                result["warnings"].append(f"DGIWG finalization warning: {e}")

            # Step 8: Validate output
            logger.info("Validating output compliance...")
            validation_results = self.output_validator.validate_gpkg_structure(
                output_geopackage
            )

            # Step 9: Update result
            result["output_path"] = str(output_geopackage)
            result["layer_count"] = len(layers_created)
            result["total_features"] = total_features
            result["layers"] = layers_created
            result["dgiwg_compliant"] = validation_results.get("compliant", False)
            result["r_tree_indexes"] = validation_results.get("dgiwg_spatial_indexes", False)

            # Step 11: CRS Conversion
            if crs_conversion_mode:
                logger.info(f"Starting CRS conversion (Mode {crs_conversion_mode.upper()})...")
                output_dir = str(Path(output_geopackage).parent)

                try:
                    # Detect source CRS
                    crs_info = self.crs_converter.detect_crs(source_geodatabase)
                    result["crs_conversion"]["source_epsg"] = crs_info['epsg']

                    if crs_conversion_mode.lower() == 'a':
                        # Mode A: Auto-convert
                        conv_result = self.crs_converter.convert_crs_mode_a(
                            source_geodatabase, output_dir, crs_info
                        )
                        result["crs_conversion"]["target_epsg"] = conv_result.get('target_epsg')
                        result["crs_conversion"]["success"] = conv_result.get('success')
                        if conv_result.get('converted'):
                            result["output_files"].append(conv_result.get('output_file'))

                    elif crs_conversion_mode.lower() == 'b':
                        # Mode B: Multi-version
                        conv_result = self.crs_converter.convert_crs_mode_b(
                            source_geodatabase, output_dir, crs_info['epsg']
                        )
                        result["crs_conversion"]["success"] = conv_result.get('success')
                        for output_file in conv_result.get('output_files', []):
                            if output_file.get('success'):
                                result["output_files"].append(output_file.get('path'))

                    elif crs_conversion_mode.lower() == 'c':
                        # Mode C: User-specified
                        if crs_target_epsg:
                            conv_result = self.crs_converter.convert_crs_mode_c(
                                source_geodatabase, output_dir,
                                crs_info['epsg'], crs_target_epsg
                            )
                            result["crs_conversion"]["target_epsg"] = crs_target_epsg
                            result["crs_conversion"]["success"] = conv_result.get('success')
                            if conv_result.get('success'):
                                result["output_files"].append(conv_result.get('output_file'))

                    # COMPLIANCE-9: CRS-converted GeoPackages produced by
                    # _perform_conversion are raw GDAL output — they lack the
                    # GP14 application_id, WKT2 definitions, and DGIWG metadata.
                    # Apply the same finalization step to every side-output file.
                    for side_file in result.get("output_files", []):
                        if side_file and side_file != str(output_geopackage):
                            try:
                                self._finalize_dgiwg_compliance(side_file)
                                logger.info(
                                    f"DGIWG finalization applied to CRS output: {side_file}"
                                )
                            except Exception as fin_err:
                                logger.warning(
                                    f"DGIWG finalization skipped for {side_file}: {fin_err}"
                                )

                except Exception as e:
                    logger.warning(f"CRS conversion failed: {str(e)}")
                    result["warnings"].append(f"CRS conversion failed: {str(e)}")

            # Step 11b (v0.27.0): Optional DGIWG self-certification gate.
            # Runs the external DGIWG GeoPackage Validator (if installed) so
            # every conversion can ship with a per-requirement PASS/FAIL table.
            if run_dgiwg_validation:
                logger.info("Running DGIWG validator gate (37 requirements)...")
                from .validation_gate import run_dgiwg_validation as _run_gate
                result["dgiwg_validation"] = _run_gate(
                    output_geopackage, validator_path=dgiwg_validator_path
                )
                if result["dgiwg_validation"].get("available"):
                    if not result["dgiwg_validation"].get("conformant"):
                        result["warnings"].append(
                            "DGIWG validator reports mandatory requirement "
                            "FAILURE(s) - see dgiwg_validation in the report"
                        )
                else:
                    result["warnings"].append(
                        result["dgiwg_validation"].get("error",
                                                       "DGIWG validator unavailable")
                    )

            # v0.29.0 fix: set success BEFORE report generation so the report
            # records the true outcome. All substantive work (conversion,
            # metadata, finalization, CRS conversion, DGIWG validation gate) is
            # complete by this point; only report writing (wrapped in its own
            # try/except) and duration bookkeeping remain. Previously this flag
            # was set at the very end of convert(), AFTER reports were already
            # written, so every *_report.json captured the stale initial False.
            result["success"] = True

            # Step 12: Generate Reports
            if generate_reports:
                logger.info("Generating conversion reports...")
                try:
                    # Prepare report data
                    self.report_generator.add_conversion_info({
                        'mode': crs_conversion_mode or 'standard',
                        'success': result['success'],
                        'start_time': result['performance']['start_time'],
                        'duration': time.time() - conversion_start_time,
                    })

                    self.report_generator.add_input_info({
                        'filename': Path(source_geodatabase).name,
                        'path': source_geodatabase,
                        'layers': len(source_info.get('layers', [])),
                        'features': sum([l.get('feature_count', 0) for l in source_info.get('layers', [])]),
                    })

                    self.report_generator.add_output_info({
                        'filename': Path(output_geopackage).name,
                        'path': output_geopackage,
                        'layers': len(layers_created),
                        'features': total_features,
                    })

                    self.report_generator.add_crs_info(result['crs_conversion'])
                    self.report_generator.add_validation_results(validation_results)
                    if result.get("dgiwg_validation"):
                        self.report_generator.add_dgiwg_validation(
                            result["dgiwg_validation"]
                        )

                    self.report_generator.add_performance_metrics({
                        'duration': time.time() - conversion_start_time,
                        'memory_used': 0,  # Can be enhanced with psutil
                        'features_per_sec': int(total_features / max(time.time() - conversion_start_time, 0.001)),
                        'layers_processed': len(layers_created),
                    })

                    # Generate reports
                    output_base = str(Path(output_geopackage).with_suffix(''))

                    html_path = f"{output_base}_report.html"
                    if self.report_generator.generate_html_report(html_path):
                        result["reports"]["html"] = html_path
                        logger.info(f"HTML report: {html_path}")

                    json_path = f"{output_base}_report.json"
                    if self.report_generator.generate_json_report(json_path):
                        result["reports"]["json"] = json_path
                        logger.info(f"JSON report: {json_path}")

                    pdf_path = f"{output_base}_report.pdf"
                    if self.report_generator.generate_pdf_report(pdf_path):
                        result["reports"]["pdf"] = pdf_path
                        logger.info(f"PDF report: {pdf_path}")

                except Exception as e:
                    logger.warning(f"Report generation failed: {str(e)}")
                    result["warnings"].append(f"Report generation failed: {str(e)}")

            result["performance"]["duration"] = round(
                time.time() - conversion_start_time, 2
            )

            # v0.29.0: result["success"] is set above, immediately before the
            # report-generation block, so the reports record the true outcome.
            logger.info(
                f"Conversion completed successfully in "
                f"{result['performance']['duration']}s"
            )
            return result

        except ValidationError as e:
            result["error"] = str(e)
            result["performance"]["duration"] = round(
                time.time() - conversion_start_time, 2
            )
            logger.error(f"Validation error: {e}")
            return result

        except Exception as e:
            result["error"] = f"Unexpected error: {e}"
            result["performance"]["duration"] = round(
                time.time() - conversion_start_time, 2
            )
            logger.exception("Unexpected error during conversion")
            return result

    def _embed_metadata(
        self,
        gpkg_path: str,
        package_xml: str,
        layer_metadata: Dict[str, str],
        dmf_xml: Optional[str] = None,
    ) -> int:
        """
        Embed ISO 19115 metadata into the GeoPackage using the OGC
        GeoPackage Metadata Extension (gpkg_metadata / gpkg_metadata_reference).

        Creates the extension tables if missing, registers the extension in
        gpkg_extensions, writes one package-level (geopackage-scope) record,
        and one table-scope record per layer linked to the package record
        via md_parent_id.

        Args:
            gpkg_path: Path to the GeoPackage file
            package_xml: Package-level ISO 19115 metadata XML
            layer_metadata: Mapping of layer name -> layer-level metadata XML

        Returns:
            Number of metadata records embedded

        Raises:
            ValidationError: If metadata cannot be written
        """
        try:
            conn = sqlite3.connect(str(gpkg_path))
            try:
                cur = conn.cursor()

                # Extension tables per OGC GeoPackage 1.4 spec (Annex F.8)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS gpkg_metadata (
                        id INTEGER CONSTRAINT m_pk PRIMARY KEY ASC NOT NULL,
                        md_scope TEXT NOT NULL DEFAULT 'dataset',
                        md_standard_uri TEXT NOT NULL,
                        mime_type TEXT NOT NULL DEFAULT 'text/xml',
                        metadata TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS gpkg_metadata_reference (
                        reference_scope TEXT NOT NULL,
                        table_name TEXT,
                        column_name TEXT,
                        row_id_value INTEGER,
                        timestamp DATETIME NOT NULL DEFAULT
                            (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                        md_file_id INTEGER NOT NULL,
                        md_parent_id INTEGER,
                        CONSTRAINT crmr_mfi_fk FOREIGN KEY (md_file_id)
                            REFERENCES gpkg_metadata(id),
                        CONSTRAINT crmr_mpi_fk FOREIGN KEY (md_parent_id)
                            REFERENCES gpkg_metadata(id)
                    )
                    """
                )

                # Register extension (one row per extension table)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS gpkg_extensions (
                        table_name TEXT,
                        column_name TEXT,
                        extension_name TEXT NOT NULL,
                        definition TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        CONSTRAINT ge_tce UNIQUE (table_name, column_name,
                                                  extension_name)
                    )
                    """
                )
                extension_def = (
                    "http://www.geopackage.org/spec/#extension_metadata"
                )
                # COMPLIANCE-2: OGC GeoPackage 1.4 Annex F.8 requires the
                # gpkg_metadata extension row to have table_name = NULL
                # (package-wide scope).  Using the table names as table_name
                # produces table-scoped rows that fail strict OGC validators.
                cur.execute(
                    """
                    INSERT INTO gpkg_extensions
                        (table_name, column_name, extension_name,
                         definition, scope)
                    SELECT NULL, NULL, 'gpkg_metadata', ?, 'read-write'
                    WHERE NOT EXISTS (
                        SELECT 1 FROM gpkg_extensions
                        WHERE table_name IS NULL
                          AND extension_name = 'gpkg_metadata'
                    )
                    """,
                    (extension_def,),
                )

                # DGIWG validator compatibility: GDAL registers the CRS WKT
                # extension under the newer name 'gpkg_crs_wkt_1_1'. Some
                # validators look for the legacy name 'gpkg_crs_wkt'. If the
                # WKT2 column exists but only the new name is registered, add
                # the legacy row too (idempotent).
                has_wkt2_col = any(
                    r[1] == "definition_12_063"
                    for r in cur.execute(
                        "PRAGMA table_info(gpkg_spatial_ref_sys)"
                    ).fetchall()
                )
                if has_wkt2_col:
                    cur.execute(
                        """
                        INSERT INTO gpkg_extensions
                            (table_name, column_name, extension_name,
                             definition, scope)
                        SELECT 'gpkg_spatial_ref_sys', 'definition_12_063',
                               'gpkg_crs_wkt',
                               'http://www.geopackage.org/spec/#extension_crs_wkt',
                               'read-write'
                        WHERE NOT EXISTS (
                            SELECT 1 FROM gpkg_extensions
                            WHERE extension_name = 'gpkg_crs_wkt'
                        )
                        """
                    )

                # v0.27.0: DGIWG DMF record (Req 18) - geopackage scope.
                # Written FIRST so it is the primary geopackage-scope record.
                embedded = 0
                if dmf_xml:
                    cur.execute(
                        """
                        INSERT INTO gpkg_metadata
                            (md_scope, md_standard_uri, mime_type, metadata)
                        VALUES ('dataset', ?, ?, ?)
                        """,
                        (DMF_STANDARD_URI, METADATA_MIME_TYPE, dmf_xml),
                    )
                    dmf_md_id = cur.lastrowid
                    cur.execute(
                        """
                        INSERT INTO gpkg_metadata_reference
                            (reference_scope, table_name, column_name,
                             row_id_value, md_file_id, md_parent_id)
                        VALUES ('geopackage', NULL, NULL, NULL, ?, NULL)
                        """,
                        (dmf_md_id,),
                    )
                    embedded += 1

                # Package-level metadata (geopackage scope)
                cur.execute(
                    """
                    INSERT INTO gpkg_metadata
                        (md_scope, md_standard_uri, mime_type, metadata)
                    VALUES ('dataset', ?, ?, ?)
                    """,
                    (ISO_METADATA_STANDARD_URI, METADATA_MIME_TYPE,
                     package_xml),
                )
                package_md_id = cur.lastrowid
                cur.execute(
                    """
                    INSERT INTO gpkg_metadata_reference
                        (reference_scope, table_name, column_name,
                         row_id_value, md_file_id, md_parent_id)
                    VALUES ('geopackage', NULL, NULL, NULL, ?, NULL)
                    """,
                    (package_md_id,),
                )
                embedded += 1

                # Layer-level metadata (table scope, linked to package record)
                for layer_name, layer_xml in layer_metadata.items():
                    cur.execute(
                        """
                        INSERT INTO gpkg_metadata
                            (md_scope, md_standard_uri, mime_type, metadata)
                        VALUES ('featureType', ?, ?, ?)
                        """,
                        (ISO_METADATA_STANDARD_URI, METADATA_MIME_TYPE,
                         layer_xml),
                    )
                    layer_md_id = cur.lastrowid
                    cur.execute(
                        """
                        INSERT INTO gpkg_metadata_reference
                            (reference_scope, table_name, column_name,
                             row_id_value, md_file_id, md_parent_id)
                        VALUES ('table', ?, NULL, NULL, ?, ?)
                        """,
                        (layer_name, layer_md_id, package_md_id),
                    )
                    embedded += 1

                conn.commit()
                logger.info(f"Embedded {embedded} metadata record(s)")
                return embedded
            finally:
                conn.close()

        except sqlite3.Error as e:
            raise ValidationError(f"Failed to embed metadata: {e}")

    @staticmethod
    def _wkt2_for_epsg(epsg: int) -> Optional[str]:
        """Return an authoritative WKT2:2015 string for an EPSG code.

        WKT2_2015 (ISO 19162:2015) is used intentionally over WKT2_2019.
        WKT2_2019 represents EPSG:4326 with an ENSEMBLE["World Geodetic System
        1984 ensemble",...] node; the DGIWG Req 13 offline validator extracts
        the ensemble name and compares it against the expected datum name
        "World Geodetic System 1984" — they do not match, causing a hard FAIL.
        WKT2_2015 uses a DATUM["World Geodetic System 1984",...] node instead,
        which passes the offline check and is still fully WKT2-compliant.

        Preference order:
          1. pyproj  - WKT2_2015 via to_wkt(version="WKT2_2015")
          2. GDAL osr - ExportToWkt(FORMAT=WKT2_2015)
        Returns None if neither can produce a string.
        """
        try:
            from pyproj import CRS as _PyCRS  # type: ignore
            return _PyCRS.from_epsg(epsg).to_wkt(version="WKT2_2015")
        except Exception:
            pass
        try:
            srs = osr.SpatialReference()
            if srs.ImportFromEPSG(int(epsg)) == 0:
                wkt2 = srs.ExportToWkt(["FORMAT=WKT2_2015"])
                if wkt2:
                    return wkt2
                wkt = srs.ExportToWkt()
                return wkt or None
        except Exception:
            pass
        return None

    @staticmethod
    def _fix_bbox_from_rtree(cur: "sqlite3.Cursor") -> list:
        """Update gpkg_contents bounding boxes from the actual RTree index values.

        DGIWG Req 24 requires the declared bbox in gpkg_contents to exactly
        enclose the RTree aggregate envelope. GDAL may write a slightly
        imprecise bbox at layer-creation time; this corrects it.

        Returns list of table names whose bbox was updated.
        """
        updated = []
        try:
            tables = cur.execute(
                "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
            ).fetchall()
        except Exception:
            return updated

        for (table_name,) in tables:
            try:
                # BUG-3: Escape any double-quotes in the identifier so layer
                # names containing special characters don't break the SQL.
                safe_tbl = table_name.replace('"', '""')
                rtree = f'rtree_{safe_tbl}_geom'
                row = cur.execute(
                    f'SELECT MIN(minx), MIN(miny), MAX(maxx), MAX(maxy) '
                    f'FROM "{rtree}"'
                ).fetchone()
                if row and row[0] is not None:
                    cur.execute(
                        "UPDATE gpkg_contents "
                        "SET min_x=?, min_y=?, max_x=?, max_y=? "
                        "WHERE table_name=?",
                        (row[0], row[1], row[2], row[3], table_name),
                    )
                    updated.append(table_name)
            except Exception:
                pass  # RTree may not exist for empty layers

        return updated

    @staticmethod
    def _strip_z_from_2d_layers(gpkg_path: str) -> list:
        """Re-open the GPKG and strip Z from any geometry that still carries a
        Z flag in layers declared as z=0 (Z prohibited) in gpkg_geometry_columns.

        DGIWG Req 24 requires consistency between the declared geometry type
        (z=0 → Z prohibited) and the actual geometry binary header Z-flag.
        GDAL's FlattenTo2D() during copy handles most cases, but the GPKG
        geometry binary envelope header can still carry a Z indicator; this
        pass guarantees full consistency.

        Returns list of (layer_name, feature_count_fixed) tuples.
        """
        fixed = []
        try:
            ds = ogr.Open(gpkg_path, update=1)
            if ds is None:  # v0.30.20: see gdal_handler.create_geopackage()
                return fixed

            try:
                # Identify layers declared as 2D (z=0 in gpkg_geometry_columns)
                conn = sqlite3.connect(gpkg_path)
                try:
                    two_d_layers = conn.execute(
                        "SELECT table_name FROM gpkg_geometry_columns WHERE z = 0"
                    ).fetchall()
                    two_d_names = {r[0] for r in two_d_layers}
                finally:
                    conn.close()

                for layer_name in two_d_names:
                    layer = ds.GetLayerByName(layer_name)
                    if not layer:
                        continue

                    # Quick probe: check if any geometry is actually 3D
                    layer.ResetReading()
                    needs_fix = False
                    for feat in layer:
                        geom = feat.GetGeometryRef()
                        if geom and geom.Is3D():
                            needs_fix = True
                            break
                    layer.ResetReading()

                    if not needs_fix:
                        continue

                    # Rewrite all 3D geometries as 2D in a single transaction
                    count = 0
                    layer.StartTransaction()
                    try:
                        for feat in layer:
                            geom = feat.GetGeometryRef()
                            if geom and geom.Is3D():
                                g = geom.Clone()
                                g.FlattenTo2D()
                                feat.SetGeometry(g)
                                layer.SetFeature(feat)
                                count += 1
                        layer.CommitTransaction()
                    except Exception:
                        layer.RollbackTransaction()
                        raise

                    if count > 0:
                        fixed.append((layer_name, count))
                        logger.info(
                            f"  Z-strip '{layer_name}': {count} feature(s) flattened to 2D"
                        )
            finally:
                # v0.30.9: was `del ds`. Here `ds` is a genuine local holding
                # the only reference, so the delete did release the dataset -
                # unlike the two `del ds` statements fixed in v0.30.7, which
                # acted on a loop variable and a parameter and closed nothing.
                # It is made explicit anyway: this is the last writer before
                # DGIWG finalization reopens the same file through sqlite3, so
                # the flush must be deterministic rather than refcount-timed,
                # and the pattern should not read as one of the broken ones.
                _flush_and_close_dataset(ds)
                ds = None

        except Exception as e:
            logger.warning(f"Z-strip pass warning: {e}")

        return fixed

    def _finalize_dgiwg_compliance(self, gpkg_path: str) -> Dict[str, Any]:
        """Post-process the SQLite GeoPackage so it satisfies DGIWG Req 3, 13 & 24.

        Operates directly on the GeoPackage with sqlite3 (no GDAL handle), so it
        is robust to differences between GDAL builds. Idempotent.

        v0.28.0 additions (Req 24):
          - Recalculates gpkg_contents bbox from RTree aggregate extents
          - Strips residual Z flags from geometries in 2D-declared layers

        Returns a small dict summarising what was changed (for the result/report).
        """
        info = {
            "application_id_set": False,
            "wkt2_column_added": False,
            "wkt2_written_for": [],
            "crs_wkt_extension_registered": False,
            "orphan_crs_removed": [],
            "bbox_fixed_layers": [],
            "z_stripped_layers": [],
        }
        conn = sqlite3.connect(str(gpkg_path))
        try:
            cur = conn.cursor()

            # 1) Ensure the WKT2 column (definition_12_063) exists.
            srs_cols = [
                r[1] for r in
                cur.execute("PRAGMA table_info(gpkg_spatial_ref_sys)").fetchall()
            ]
            if "definition_12_063" not in srs_cols:
                cur.execute(
                    "ALTER TABLE gpkg_spatial_ref_sys "
                    "ADD COLUMN definition_12_063 TEXT"
                )
                info["wkt2_column_added"] = True

            # 2) Collect CRS actually referenced by data, so we never delete a
            #    CRS that is still in use.
            used_srs = set()
            for tbl, col in (("gpkg_contents", "srs_id"),
                                         ("gpkg_geometry_columns", "srs_id")):
                try:
                    # BUG-3: tbl/col are hardcoded OGC table names — safe, but
                    # use quoted form for consistency and future-proofing.
                    used_srs |= {
                        r[0] for r in
                        cur.execute(
                            f'SELECT "{col}" FROM "{tbl}"'
                        ).fetchall()
                        if r[0] is not None
                    }
                except sqlite3.Error:
                    pass

            # 3) Remove orphan, non-approved CRS rows (e.g. the original source
            #    CRS left behind after reprojection). Only rows referenced by
            #    no table are removed.
            for (sid,) in cur.execute(
                "SELECT srs_id FROM gpkg_spatial_ref_sys WHERE srs_id > 0"
            ).fetchall():
                if sid not in DGIWG_APPROVED_CRS and sid not in used_srs:
                    cur.execute(
                        "DELETE FROM gpkg_spatial_ref_sys WHERE srs_id = ?",
                        (sid,),
                    )
                    info["orphan_crs_removed"].append(sid)

            # 4) Write authoritative WKT2 for every approved CRS still present.
            wrote_any = False
            for (sid,) in cur.execute(
                "SELECT srs_id FROM gpkg_spatial_ref_sys WHERE srs_id > 0"
            ).fetchall():
                if sid in DGIWG_APPROVED_CRS:
                    wkt2 = self._wkt2_for_epsg(sid)
                    if wkt2:
                        cur.execute(
                            "UPDATE gpkg_spatial_ref_sys "
                            "SET definition_12_063 = ?, "
                            "    description = COALESCE(NULLIF(description, ''), ?) "
                            "WHERE srs_id = ?",
                            (wkt2, f"EPSG:{sid}", sid),
                        )
                        wrote_any = True
                        info["wkt2_written_for"].append(sid)

            # 5) Register the gpkg_crs_wkt extension (idempotent).
            if wrote_any:
                already = cur.execute(
                    "SELECT 1 FROM gpkg_extensions "
                    "WHERE extension_name = 'gpkg_crs_wkt'"
                ).fetchone()
                if not already:
                    cur.execute(
                        "INSERT INTO gpkg_extensions "
                        "(table_name, column_name, extension_name, "
                        " definition, scope) "
                        "VALUES ('gpkg_spatial_ref_sys', 'definition_12_063', "
                        "'gpkg_crs_wkt', "
                        "'http://www.geopackage.org/spec/#extension_crs_wkt', "
                        "'read-write')"
                    )
                info["crs_wkt_extension_registered"] = True

            conn.commit()

            # 5b) Req 24: fix gpkg_contents bbox from RTree aggregate extents.
            # _fix_bbox_from_rtree was defined in v0.28.0 but was never wired
            # into this finalization pass — the info dict had the slot but the
            # helper was dead code.  Call it now.
            try:
                bbox_fixed = self._fix_bbox_from_rtree(cur)
                info["bbox_fixed_layers"] = bbox_fixed
                if bbox_fixed:
                    conn.commit()
                    logger.info(f"  Req 24 bbox fixed for: {bbox_fixed}")
            except Exception as _bbox_err:
                logger.warning(f"  Req 24 bbox fix skipped: {_bbox_err}")

            # 6) Make sure no WAL sidecar is required at delivery (DGIWG Req 3
            #    flags journal_mode=WAL). Checkpoint and revert to rollback
            #    journalling if needed.
            try:
                mode = cur.execute("PRAGMA journal_mode").fetchone()[0]
                if str(mode).lower() == "wal":
                    cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    cur.execute("PRAGMA journal_mode = DELETE")
            except sqlite3.Error:
                pass

            # 7) Set the OGC-standard 'GPKG' application_id and user_version
            # (10400) so the file self-declares as GeoPackage 1.4.
            try:
                cur.execute(
                    f"PRAGMA application_id = {GPKG_APPLICATION_ID_DGIWG}"
                )
                cur.execute("PRAGMA user_version = 10400")
                conn.commit()
                info["application_id_set"] = True
            except sqlite3.Error as e:
                logger.warning(f"Could not set application_id/user_version: {e}")

            # Req 24: strip residual Z flags from geometries in 2D-declared layers.
            # Must run after conn is committed and closed because
            # _strip_z_from_2d_layers opens its own GDAL update handle which
            # would deadlock against an open sqlite3 write connection.
            conn.close()
            conn = None  # prevent double-close in finally
            try:
                z_fixed = self._strip_z_from_2d_layers(gpkg_path)
                info["z_stripped_layers"] = z_fixed
                if z_fixed:
                    logger.info(f"  Req 24 Z-stripped layers: {z_fixed}")
            except Exception as _z_err:
                logger.warning(f"  Req 24 Z-strip skipped: {_z_err}")

            return info

        except Exception as e:
            logger.warning(f"DGIWG finalization error for {gpkg_path}: {e}")
            return {"error": str(e)}
        finally:
            if conn is not None:
                conn.close()
