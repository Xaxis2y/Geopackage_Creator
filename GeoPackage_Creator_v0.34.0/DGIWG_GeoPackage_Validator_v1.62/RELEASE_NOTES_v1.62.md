# DGIWG GeoPackage Compliance Validator — Release Notes v1.62

Release date: 2026-08-17
Standard: DGIWG STD-DP-19-005 v1.1 (GeoPackage Profile 1.4, Edition 1.1)

## Highlights

- Standard `GPKG` application markers are accepted when the schema version is valid.
- Recursive discovery includes filenames such as `sample.gpkg.gpkg`.
- Extension checks respect actual table and data scope.
- DGIWG dynamic CRS convention identifiers are supported without false EPSG lookup failures.
- ISO 19115-3/MI metadata receives an explicit external-ATS review status.
- XML parsing is hardened against external entity and network resolution.
- Reports distinguish data non-conformance (`FAIL`) from validator faults (`ERROR`).
- The script release is distributed as a portable source folder; no compiled
  executable or build artifacts are required.

## Validation

- Local regression suite: 66/66 assertions passed.
- Real-data run: 24 GeoPackages processed with zero validator errors.

## Scope limitation

This tool provides automated conformance evidence. Final certification still
requires applicable OGC CITE/TeamEngine and metadata ATS review.
