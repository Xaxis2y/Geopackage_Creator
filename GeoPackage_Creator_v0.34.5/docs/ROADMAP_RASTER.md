# Raster / Tile Support Roadmap (target: v0.28)

The DGIWG GeoPackage Profile dedicates roughly half of its 37 requirements to
raster tiles and gridded (elevation) coverages: Req 7-8, 11-12, 16-17, 25-31,
33-37. GeoPackage Creator v0.27.0 converts vector data only, but ships the
foundations raster support will build on.

## Shipped in v0.27.0 (foundations)

- Per-data-type CRS policy in `core/config.py`:
  `DGIWG_CRS_RASTER_TILES` (Req 7), `DGIWG_CRS_GRIDDED_2D` (Req 11, includes
  UTM north 32601-32660 AND south 32701-32760 + UPS 5041/5042),
  `DGIWG_CRS_GRIDDED_3D` (Req 12).
- `DGIWG_TILE_MATRIX` (256x256, Req 25) and `DGIWG_ZOOM_LEVEL_FACTOR` (2, Req 27).
- `core/raster_support.py`: validation helpers
  (`validate_tile_crs`, `validate_gridded_crs`, `validate_tile_dimensions`,
  `validate_zoom_levels`) and the planned `convert_raster()` entry point
  (currently raises `RasterNotImplementedError`).

## Planned for v0.28

1. **Tile pyramid creation** - `gdal.Translate` to GPKG tiles
   (`TILE_FORMAT=PNG_JPEG`, `BLOCKSIZE=256`) + `BuildOverviews` with factor-2
   levels; reproject to an approved tile CRS first (default EPSG:4326,
   EPSG:5041/5042 for polar data).
2. **gpkg_tile_matrix / gpkg_tile_matrix_set conformance** - exact bbox per
   CRS (validator CRS_EXTENT), matrix_width/height consistency (Req 25-30).
3. **Tile layer metadata** - DMF + ISO records per tile table (Req 31).
4. **Gridded elevation (DGIWG 250)** - gpkg_2d_gridded_coverage_ancestry
   extension, float32 elevation, field name "Height" rules (Req 33-37).
5. **GUI/CLI** - `--raster` input mode; profile-driven tile format choice.
6. Re-run the DGIWG validator gate on raster outputs; Req 7/8/11/12/25-31
   move from SKIPPED to PASS.

## Design constraints to respect

- Keep vector and raster finalization sharing `_finalize_dgiwg_compliance`
  (application_id, WKT2, extension registration are common).
- The gpkg_crs_wkt_1_1 extension becomes relevant when gridded data is added
  (see HANDOFF_NOTES_2026-06-10.md open item).
