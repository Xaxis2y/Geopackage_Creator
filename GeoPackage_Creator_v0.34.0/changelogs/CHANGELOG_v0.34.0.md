# GeoPackage Creator v0.34.0

**Release date:** 2026-08-17

## Release highlights

- Replaced the bundled DGIWG GeoPackage Validator v1.58 with v1.62.
- Runs DGIWG validation in a helper process, keeping the validator's lxml use
  isolated from the GDAL conversion process.
- Retains isolated ISO 19115 XSD validation for the same Windows native-stack
  stability reason.
- Accepts FileGDB folders without a `.gdb` suffix when they contain
  `GEODATABASE_FILE_*` markers.
- Uses the standard OGC GeoPackage header marker `GPKG` with
  `user_version=10400`.
- Updates README, Quick Start, GUI guide, and Markdown/Word user manuals.

## Verification required before publication

Run the source test suite, build the PyInstaller executable, then run the
frozen-EXE and real-FileGDB release gates. Their logs are release evidence and
are intentionally excluded from the GitHub source archive.
