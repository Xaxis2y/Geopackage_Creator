# CHANGELOG — GeoPackage Creator v0.27.0 (2026-06-11)

Concept-level review release: aligns the tool with the DGIWG GeoPackage
Profile's actual per-data-type rules and adds DMF metadata, a validator
gate, NATO security markings and raster foundations.

## 1. Per-data-type DGIWG CRS policy (BREAKING behaviour fix)

The old flat `DGIWG_APPROVED_CRS` list (4326, 3857, UTM north only) was
wrong in both directions: DGIWG allows ONLY EPSG:4326 for 2D vector data
(Req 9) — 3857/UTM are tile & gridded CRS — and the southern UTM zones
(32701-32760), UPS (5041/5042), World Mercator (3395), 4979 and 9518 were
missing entirely.

- `core/config.py`: new `DGIWG_CRS_POLICY` with per-type sets
  (`vector_2d`={4326}, `vector_3d`={4979, 9518},
  `raster_tiles`={3395, 3857, 4326, 4979, 5041, 5042},
  `gridded_2d`=tiles+UTM N/S, `gridded_3d`={4979, 9518}).
  `DGIWG_APPROVED_CRS` is now the union (kept for the SQLite finalize step).
- `core/validators.py`: `validate_epsg_code()` / `validate_crs_dgiwg()`
  take a `data_type` argument (default `vector_2d`).
- `core/converter.py`: reprojection now triggers for ANY source CRS other
  than EPSG:4326 (previously a 3857/UTM source was left untouched and
  failed validator Req 9).

## 2. DGIWG Metadata Foundation (DMF) record — Req 18 full PASS

- `core/config.py`: `DMF_STANDARD_URI` fixed to `https://dgiwg.org/std/dmf/2.0`
  (was the obsolete 2014 schema URI, and was never written into the file).
- `core/metadata_handler.py`: new `generate_dmf_metadata()` producing a
  DMF 2.0 record (UUID fileIdentifier, ISO 639-2 language, utf8 charset,
  dataset scope, contact org + role, ISO 8601 dateStamp, identificationInfo
  with citation/abstract/security constraints/releasability).
- `core/converter.py`: `_embed_metadata()` writes the DMF row (geopackage
  scope) ahead of the ISO 19139 row. Verified against the real validator:
  Req 18 = PASS (was PASS* ceiling before), Req 19 = PASS, Req 21 = PASS.

## 3. DGIWG validator gate (`--validate`)

- New `core/validation_gate.py`: locates the external
  `DGIWG_Validator_v1_5x` (explicit path, `DGIWG_VALIDATOR_PATH` env var, or
  auto-detect) and runs all 37 requirement checks offline.
- `convert(..., run_dgiwg_validation=True, dgiwg_validator_path=...)`;
  CLI flags `--validate` / `--validator-path`.
- `core/report_generator.py`: per-requirement PASS / PASS* / FAIL / SKIPPED
  table in the HTML report (`add_dgiwg_validation`), included in JSON output;
  CLI prints the CONFORMANT / NON-CONFORMANT verdict.

## 4. NATO security markings + releasability

- `core/config.py`: `NATO_SECURITY_MARKINGS` (NATO UNCLASSIFIED ... COSMIC
  TOP SECRET) accepted by validation and mapped to ISO classification codes.
- `convert(..., releasability="NATO")` / CLI `--releasability`; written to
  both the ISO handlingDescription and the DMF legal constraints.

## 5. Raster foundations (full support planned v0.28)

- `core/raster_support.py`: tile/gridded CRS checks, 256x256 tile and
  zoom-factor-2 validation helpers; `convert_raster()` stub.
- `DGIWG_ZOOM_LEVEL_FACTOR` constant; `ROADMAP_RASTER.md` implementation plan.

## 6. Housekeeping

- `schemas/iso19115-1.xsd` renamed to `schemas/iso19139-gmd.xsd` (the
  content always validated the 2005 `gmd` encoding; the old name was
  misleading). Loader falls back to the legacy filename.
- README: documented WHY `application_id` is `GP12` while `user_version`
  is 10400 (OGC/DGIWG validator conflict) so it is not "fixed" by accident.
- All version strings bumped to 0.27.0.

## Compatibility

- `convert()` remains backward compatible (new arguments are optional).
- Code that imported `DGIWG_APPROVED_CRS` still works; it now contains MORE
  codes (union of all data types). Use `DGIWG_CRS_POLICY` for per-type checks.
