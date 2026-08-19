# v1.62 hardening changes

This working release strengthens the validator's operational trust boundary.

- A validator exception now yields `ERROR`, never a false `FAIL`.
- Any `ERROR` gives `VALIDATION ERROR — REVIEW REQUIRED`.
- A run with skipped requirements can no longer emit the unqualified verdict
  `CONFORMANT`; it emits `AUTOMATED CHECKS CONFORMANT — EXTERNAL REVIEW REQUIRED`.
- JSON reports include a `validation_scope` object, explicitly stating that the
  tool does not establish final certification.
- XML schema parsing disables entity resolution, DTD loading, and network
  access to prevent metadata XML from causing XXE/SSRF behaviour.
- Req 7 now handles GeoPackages without the optional `definition_12_063` CRS
  column, rather than treating that valid schema variant as a validator error.
- Req 3 now accepts the standard GeoPackage 1.2+ `GPKG` application marker
  when `PRAGMA user_version` confirms the required schema version.
- `pyproject.toml` and `requirements.txt` provide reproducible installation;
  `run_anaconda_validation.bat` provides a UTF-8, end-to-end local validation log.

## Final-delivery rule

Do not declare a dataset fully DGIWG conformant solely from this tool.  Attach
the HTML/JSON report, run the relevant OGC CITE/TeamEngine tests for Req 1–2,
and document the product-profile decision for Req 6.

