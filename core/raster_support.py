"""
Raster / Tile Support Foundations (v0.27.0)

DGIWG GeoPackage conformance for raster content is defined by requirements
7-8, 11-12, 16-17, 25-31 and 33-37 of the DGIWG GeoPackage Profile (tile
matrix rules, zoom factors, gridded elevation coverages per DGIWG 250).
This tool currently converts VECTOR data only; this module provides the
constants, CRS policy hooks and validation helpers that full raster support
will build on. See ROADMAP_RASTER.md for the implementation plan.

Status: FOUNDATIONS ONLY - conversion entry points raise NotImplementedError.
"""

from typing import Dict, List, Optional, Tuple

from .config import (
    DGIWG_CRS_RASTER_TILES,
    DGIWG_CRS_GRIDDED_2D,
    DGIWG_CRS_GRIDDED_3D,
    DGIWG_TILE_MATRIX,
    DGIWG_ZOOM_LEVEL_FACTOR,
)


class RasterNotImplementedError(NotImplementedError):
    """Raised by raster conversion entry points until raster support lands."""


def validate_tile_crs(epsg_code: int) -> bool:
    """True when *epsg_code* is DGIWG-approved for raster tiles (Req 7)."""
    return epsg_code in DGIWG_CRS_RASTER_TILES


def validate_gridded_crs(epsg_code: int, is_3d: bool = False) -> bool:
    """True when *epsg_code* is DGIWG-approved for gridded coverages
    (Req 11 for 2D, Req 12 for 3D)."""
    allowed = DGIWG_CRS_GRIDDED_3D if is_3d else DGIWG_CRS_GRIDDED_2D
    return epsg_code in allowed


def validate_tile_dimensions(width: int, height: int) -> bool:
    """True when tile dimensions match the DGIWG mandate (Req 25: 256x256)."""
    return (
        width == DGIWG_TILE_MATRIX["tile_width"]
        and height == DGIWG_TILE_MATRIX["tile_height"]
    )


def validate_zoom_levels(pixel_sizes: List[float]) -> Tuple[bool, List[str]]:
    """Check that consecutive zoom levels differ by the DGIWG factor (Req 27).

    Args:
        pixel_sizes: pixel sizes ordered from lowest to highest zoom level.

    Returns:
        (ok, issues) - issues lists human-readable violations.
    """
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


def convert_raster(
    source_raster: str,
    output_geopackage: str,
    target_epsg: Optional[int] = None,
    **kwargs,
) -> Dict:
    """Planned entry point for DGIWG raster tile conversion (NOT IMPLEMENTED).

    Will create a tile pyramid table (256x256 tiles, zoom factor 2, approved
    tile CRS) via gdal.Translate/BuildOverviews. See ROADMAP_RASTER.md.
    """
    raise RasterNotImplementedError(
        "Raster tile conversion is not implemented yet (planned for v0.28). "
        "See ROADMAP_RASTER.md for the implementation plan."
    )
