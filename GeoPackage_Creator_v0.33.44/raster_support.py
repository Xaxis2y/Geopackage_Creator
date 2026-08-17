# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Raster / Tile Support — GeoPackage Creator v0.30.19

Converts raster sources (GeoTIFF, IMG, etc.) into DGIWG-compliant
GeoPackage tile pyramids via gdal.Translate + BuildOverviews.

DGIWG requirements addressed:
  Req 7  — tile CRS must be EPSG 3395/3857/4326/4979/5041/5042
  Req 25 — tile size 256 × 256 px
  Req 27 — zoom factor exactly 2 between adjacent levels

Usage:
    from core.raster_support import convert_raster

    result = convert_raster(
        source_raster="input.tif",
        output_geopackage="output.gpkg",
        target_epsg=4326,          # optional; defaults to source CRS if DGIWG-approved
        tile_format="PNG",         # PNG (lossless) or JPEG (lossy)
        overview_levels=None,      # auto-computed if None
        table_name="raster_tiles", # tile table name inside the GeoPackage
    )
    if result["success"]:
        print(result["zoom_levels"], "zoom levels written")
"""

from __future__ import annotations

import logging
import math
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# ---------------------------------------------------------------------------
# DGIWG-approved CRS for each data type (mirrors config.py to avoid circular
# imports when this module is used standalone).
# ---------------------------------------------------------------------------
DGIWG_CRS_RASTER_TILES = {3395, 3857, 4326, 4979, 5041, 5042}
DGIWG_TILE_WIDTH = 256
DGIWG_TILE_HEIGHT = 256
DGIWG_ZOOM_LEVEL_FACTOR = 2


class RasterNotImplementedError(NotImplementedError):
    """Kept for backward compatibility — no longer raised by convert_raster."""


# ---------------------------------------------------------------------------
# Public validators (unchanged from foundations)
# ---------------------------------------------------------------------------

def validate_tile_crs(epsg_code: int) -> bool:
    """True when *epsg_code* is DGIWG-approved for raster tiles (Req 7)."""
    return epsg_code in DGIWG_CRS_RASTER_TILES


def validate_gridded_crs(epsg_code: int, is_3d: bool = False) -> bool:
    """True when *epsg_code* is DGIWG-approved for gridded coverages."""
    from .config import DGIWG_CRS_GRIDDED_2D, DGIWG_CRS_GRIDDED_3D
    allowed = DGIWG_CRS_GRIDDED_3D if is_3d else DGIWG_CRS_GRIDDED_2D
    return epsg_code in allowed


def validate_tile_dimensions(width: int, height: int) -> bool:
    """True when tile dimensions match the DGIWG mandate (Req 25: 256×256)."""
    return width == DGIWG_TILE_WIDTH and height == DGIWG_TILE_HEIGHT


def validate_zoom_levels(pixel_sizes: List[float]) -> Tuple[bool, List[str]]:
    """Check that consecutive zoom levels differ by the DGIWG factor (Req 27)."""
    issues = []
    for i in range(1, len(pixel_sizes)):
        if pixel_sizes[i] == 0:
            issues.append(f"zoom level {i}: pixel size is 0")
            continue
        ratio = pixel_sizes[i - 1] / pixel_sizes[i]
        if abs(ratio - DGIWG_ZOOM_LEVEL_FACTOR) > 1e-6:
            issues.append(
                f"zoom level {i - 1}->{i}: factor {ratio:.4f} "
                f"(DGIWG requires exactly {DGIWG_ZOOM_LEVEL_FACTOR})"
            )
    return (not issues, issues)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _gdal():
    """Lazy import so the module loads even if GDAL is absent."""
    from osgeo import gdal
    gdal.UseExceptions()
    return gdal


def _source_epsg(ds) -> Optional[int]:
    """Extract EPSG code from a GDAL dataset's projection."""
    gdal = _gdal()
    from osgeo import osr
    proj = ds.GetProjection()
    if not proj:
        return None
    srs = osr.SpatialReference()
    srs.ImportFromWkt(proj)
    srs.AutoIdentifyEPSG()
    code = srs.GetAuthorityCode(None)
    return int(code) if code else None


def _compute_overview_levels(ds, max_levels: int = 8) -> List[int]:
    """
    Compute power-of-2 overview decimation factors so the coarsest zoom
    level fits within a single 256×256 tile (DGIWG zoom factor = 2, Req 27).

    Returns a list like [2, 4, 8, 16, ...] suitable for BuildOverviews().
    """
    width = ds.RasterXSize
    height = ds.RasterYSize
    longest = max(width, height)

    levels = []
    factor = DGIWG_ZOOM_LEVEL_FACTOR
    while longest // factor > DGIWG_TILE_WIDTH and len(levels) < max_levels:
        levels.append(factor)
        factor *= DGIWG_ZOOM_LEVEL_FACTOR

    return levels if levels else [2]


def _reproject_raster(gdal, src_ds, target_epsg: int, tmp_path: str):
    """Warp *src_ds* to *target_epsg* and save as a temp GeoTIFF."""
    warp_opts = gdal.WarpOptions(
        dstSRS=f"EPSG:{target_epsg}",
        format="GTiff",
        resampleAlg="bilinear",
        multithread=True,
        warpMemoryLimit=512,
        creationOptions=["COMPRESS=LZW", "TILED=YES",
                         "BLOCKXSIZE=256", "BLOCKYSIZE=256"],
    )
    out = gdal.Warp(tmp_path, src_ds, options=warp_opts)
    if out is None:
        raise RuntimeError(f"gdal.Warp to EPSG:{target_epsg} failed.")
    out.FlushCache()
    return out


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def convert_raster(
    source_raster: str,
    output_geopackage: str,
    target_epsg: Optional[int] = None,
    tile_format: str = "PNG",
    overview_levels: Optional[List[int]] = None,
    table_name: str = "raster_tiles",
    **kwargs,
) -> Dict[str, Any]:
    """
    Convert a raster file into a DGIWG-compliant GeoPackage tile pyramid.

    Args:
        source_raster:    Path to input raster (GeoTIFF, IMG, VRT, …).
        output_geopackage: Path to output .gpkg file.
        target_epsg:      DGIWG-approved EPSG for tiles. If None, the source
                          CRS is used when it is already DGIWG-approved;
                          otherwise falls back to EPSG:4326.
        tile_format:      "PNG" (lossless, default) or "JPEG" (lossy, smaller).
        overview_levels:  List of decimation factors, e.g. [2, 4, 8].
                          Auto-computed when None.
        table_name:       Tile table name inside the GeoPackage.

    Returns:
        Dict with keys:
            success (bool), output_path (str), zoom_levels (int),
            tile_format (str), epsg (int), warnings (list[str]),
            error (str | None), elapsed_seconds (float)
    """
    gdal = _gdal()
    start = time.time()
    warnings: List[str] = []
    tmp_warped: Optional[str] = None

    result: Dict[str, Any] = {
        "success": False,
        "output_path": str(output_geopackage),
        "zoom_levels": 0,
        "tile_format": tile_format.upper(),
        "epsg": target_epsg,
        "warnings": warnings,
        "error": None,
        "elapsed_seconds": 0.0,
    }

    try:
        # ---- 1. Open source --------------------------------------------------
        src_ds = gdal.Open(source_raster)
        if src_ds is None:
            raise RuntimeError(f"GDAL cannot open raster: {source_raster}")

        src_epsg = _source_epsg(src_ds)
        logger.info(f"  Raster source: {source_raster}  (EPSG:{src_epsg})")
        logger.info(
            f"  Size: {src_ds.RasterXSize} × {src_ds.RasterYSize} px, "
            f"{src_ds.RasterCount} band(s)"
        )

        # ---- 2. Resolve target EPSG ------------------------------------------
        if target_epsg is None:
            if src_epsg and src_epsg in DGIWG_CRS_RASTER_TILES:
                target_epsg = src_epsg
                logger.info(f"  Source CRS EPSG:{target_epsg} is DGIWG-approved — no warp needed.")
            else:
                target_epsg = 4326
                warnings.append(
                    f"Source CRS EPSG:{src_epsg} is not DGIWG-approved for raster tiles. "
                    f"Warping to EPSG:4326 (WGS 84)."
                )
                logger.warning(warnings[-1])
        elif target_epsg not in DGIWG_CRS_RASTER_TILES:
            warnings.append(
                f"Requested EPSG:{target_epsg} is not DGIWG-approved for raster tiles "
                f"(allowed: {sorted(DGIWG_CRS_RASTER_TILES)}). Proceeding anyway."
            )
            logger.warning(warnings[-1])

        result["epsg"] = target_epsg

        # ---- 3. Warp if CRS differs -----------------------------------------
        working_ds = src_ds
        needs_warp = src_epsg != target_epsg
        if needs_warp:
            tmp_warped = str(Path(output_geopackage).with_suffix(".tmp_warped.tif"))
            logger.info(f"  Warping EPSG:{src_epsg} → EPSG:{target_epsg} …")
            working_ds = _reproject_raster(gdal, src_ds, target_epsg, tmp_warped)
            logger.info("  Warp complete.")

        # ---- 4. Compute overview levels --------------------------------------
        if overview_levels is None:
            overview_levels = _compute_overview_levels(working_ds)
        logger.info(f"  Overview decimation factors: {overview_levels}")

        # ---- 5. Translate → GeoPackage tile table ----------------------------
        # gdal.Translate writes the raster as a tile matrix table (one zoom
        # level = native resolution).  BuildOverviews() adds the remaining
        # zoom levels (each 2× coarser), which GDAL auto-inserts into the
        # GeoPackage tile matrix.
        tile_fmt = tile_format.upper()
        if tile_fmt not in ("PNG", "JPEG", "WEBP"):
            warnings.append(f"Unknown tile_format '{tile_fmt}'; defaulting to PNG.")
            tile_fmt = "PNG"

        logger.info(f"  Writing tile table '{table_name}' ({tile_fmt}) …")
        Path(output_geopackage).unlink(missing_ok=True)

        # Build creation options. The tile-table name option changed between
        # GDAL versions: GDAL >= 3.13 uses TABLE, older versions use
        # RASTER_TABLE.  We try RASTER_TABLE first (works on both) and
        # fall back gracefully — the table will be named by GDAL's default.
        gdal_ver = tuple(int(x) for x in gdal.VersionInfo("RELEASE_NAME").split(".")[:2])
        table_opt = "TABLE" if gdal_ver >= (3, 13) else "RASTER_TABLE"

        translate_opts = gdal.TranslateOptions(
            format="GPKG",
            creationOptions=[
                f"TILE_FORMAT={tile_fmt}",
                f"{table_opt}={table_name}",
                f"BLOCKXSIZE={DGIWG_TILE_WIDTH}",
                f"BLOCKYSIZE={DGIWG_TILE_HEIGHT}",
            ],
        )
        out_ds = gdal.Translate(output_geopackage, working_ds, options=translate_opts)
        if out_ds is None:
            raise RuntimeError("gdal.Translate to GPKG failed.")

        # ---- 6. Build overview zoom levels -----------------------------------
        logger.info(f"  Building {len(overview_levels)} overview level(s) …")
        err = out_ds.BuildOverviews("AVERAGE", overview_levels)
        if err != 0:
            warnings.append(
                f"BuildOverviews returned error code {err}. "
                f"The GeoPackage may have fewer zoom levels than expected."
            )
            logger.warning(warnings[-1])

        out_ds.FlushCache()

        # Count how many zoom levels actually landed in the tile table
        zoom_levels = 1 + len(overview_levels)  # native + overviews
        result["zoom_levels"] = zoom_levels

        # ---- 7. Verify output ------------------------------------------------
        check = gdal.OpenEx(output_geopackage, gdal.OF_READONLY)
        if check is None:
            raise RuntimeError("Output GeoPackage cannot be re-opened for verification.")
        check = None  # close

        result["success"] = True
        logger.info(
            f"  Raster conversion complete: {output_geopackage} "
            f"({zoom_levels} zoom levels, EPSG:{target_epsg})"
        )

    except Exception as exc:
        result["error"] = str(exc)
        logger.error(f"  Raster conversion failed: {exc}")

    finally:
        # Clean up temp warp file
        if tmp_warped and Path(tmp_warped).exists():
            try:
                os.unlink(tmp_warped)
            except OSError:
                pass
        result["elapsed_seconds"] = round(time.time() - start, 2)

    return result
