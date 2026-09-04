# DGIWG GeoPackage Compliance Validator — Release Notes v1.63

**Release date:** 2026-09-03
**Standard:** DGIWG STD-DP-19-005 v1.1 (GeoPackage Profile 1.4, Edition 1.1)
**License:** GPL-2.0-or-later — © 2026 Eui Soo SON

---

## Summary

v1.63 is primarily a **consistency and housekeeping release** — it contains **no changes to
requirement-checking behavior**. `checks.py`, `constants.py`, `forensics.py`, `main.py`, `net.py`,
and `utils.py` are byte-for-byte unchanged from v1.62, and no verdict, requirement scoring, or
coverage-gap logic is affected. Two files, `html_report.py` and `rollup.py`, did change — see §5 —
but only in the static footer text they emit, not in any check they run.

What prompted this release: the project folder had accumulated files stamped with three different
version numbers at once. `dgiwg_validator/__init__.__version__` and `VERSION.txt` had already been
bumped to **1.62**, but the launcher script's own docstring, the README, QUICKSTART.html,
BUILD_EXE_QUICKSTART.html, the PyInstaller spec, both build batch files, `environment.yml`, and the
User Manual's header/title page/cover metadata were never updated to match — some still said
**v1.61**, and the manual's title page specifically still said **Version 1.59** while its document
header said **v1.59** and its embedded document properties said **v1.60**. A duplicate old launcher
(`DGIWG_Validator_v1_61.py`) was also still sitting in the folder alongside the new one. v1.63 fixes
all of this and re-establishes `dgiwg_validator.__version__` as the single place a version number is
decided, matching what `package_release.py` has always assumed.

---

## 1. Version references brought back in sync

Every file that stamps a "current version" identifier was updated to v1.63:

| File | What was wrong | Fix |
|---|---|---|
| `DGIWG_Validator_v1_62.py` | Docstring said "v1.61" (copy-paste leftover) | Replaced by new `DGIWG_Validator_v1_63.py` with a correct docstring |
| `dgiwg_validator/__init__.py` | `__version__ = "1.62"`; usage lines named v1.62 launcher/zipapp | Bumped to `"1.63"`; usage lines updated |
| `DGIWG_Validator.spec` | `APP_NAME`/`ENTRY_FILE` still targeted `..._v1_61.py`/`.exe` | Retargeted to `..._v1_63` |
| `01_create_environment.bat`, `02_build_exe.bat` | Header comments and `.exe`/launcher filenames said v1.61 | Updated to v1.63 throughout |
| `environment.yml` | Header comment said v1.61 | Updated to v1.63 |
| `README.md` | Version banner, launcher filenames, manual filename, staged/zip output paths, project-structure tree all said v1.61 | Updated to v1.63; see below for what was deliberately **not** changed |
| `QUICKSTART.html` | Title, version badge, `cd` path, manual filename, footer tagline said v1.61 | Updated to v1.63 |
| `BUILD_EXE_QUICKSTART.html` | Title, subtitle, `cd` path, footer tagline said v1.61 | Updated to v1.63 |
| `DGIWG_GeoPackage_Validator_User_Manual_v1.6x.docx` | Filename said v1.62; title page said "Version 1.59"; document header said "v1.59"; document properties (title/comments) said "v1.60"; body text (CLI examples, project-tree diagram, self-test section heading, release-asset checklist, packaging output path, closing tagline) said v1.61 | New `..._v1.63.docx`, every one of those fields corrected |

## 2. What was deliberately left alone

Sentences that document **when a feature was introduced** — not the current version — were not
touched, so the changelog history stays accurate:

- QUICKSTART.html's "The Coverage lines (new in v1.61)…" and "Every PASS* now carries one of three
  reasons (v1.61)…" and "v1.61 replaced the old two-tier … split…"
- The manual's entire "2. What's New in v1.61" section and its narrative about what changed between
  v1.59/v1.60/v1.61
- Every inline `# v1.60 fix:` / `# v1.61:` code comment in `dgiwg_validator/*.py` — these document
  which release introduced or fixed a specific check and are historical annotations, not version
  stamps
- `README.md`'s per-version changelog entries for v1.59–v1.61 (only their **file citations** were
  updated to point at the new `_superseded_pre_v1.63/` location, since those files moved)

## 3. Self-test suite version drift, found and fixed

Running `run_local_tests.py` against the cleaned-up folder failed six assertions outright: it still
hardcoded `EXPECTED_VERSION = "1.61"` (checking the package version, the launcher filename, the
manual filename, `VERSION.txt`, the JSON `schema_version`, and `--version` output all against
"1.61"). This single constant is now `"1.63"`. Separately, the suite actually runs **84** assertions
today, not the 62 that `README.md`, `01_create_environment.bat`, and `BUILD_EXE_QUICKSTART.html`
still quoted — the suite has grown since whichever release that number was last accurate for, and no
one had updated the docs to match. All three files now say 84. With both fixed, `run_local_tests.py`
reports `RESULT: 84/84 assertions passed`.

## 4. Folder cleanup

- **Archived, not deleted**, into `_superseded_pre_v1.63/`: `DGIWG_Validator_v1_61.py`,
  `DGIWG_Validator_v1_62.py`, `DGIWG_GeoPackage_Validator_User_Manual_v1.62.docx`,
  `RELEASE_NOTES_v1.60.md`, `RELEASE_NOTES_v1.61.md`. `package_release.py` already excludes any
  directory whose name starts with `_superseded` or `_to_delete` from the release archive, so this
  matches the project's existing convention (see its v1.59/v1.60 changelog comments) and requires no
  packaging-script change.
- **Deleted** (transient, regenerated on every run, no lasting value): `build_exe_log_*.txt`,
  `env_setup_log_*.txt`, `local_test_log_*.txt`, and LibreOffice's own temporary lock/conversion
  files left behind while this release's manual was being proofread.

## 5. Report/document attribution removed

The HTML per-file report footer, the HTML rollup report footer, and QUICKSTART.html's own footer
all carried a two-line personal/organizational attribution block — a name and military rank, a
personal email address, and an organization/unit name and its abbreviation.

At the author's request this was removed everywhere (`dgiwg_validator/html_report.py`,
`dgiwg_validator/rollup.py`, `QUICKSTART.html`, and the manual's title page, "11. Support" section,
and page footer) and replaced with just:

```
SPDX-License-Identifier: GPL-2.0-or-later
Copyright (c) 2026 Eui Soo SON
```

This is a genuine content change to `html_report.py` and `rollup.py` — the two modules that generate
the per-file and rollup HTML reports every run produces — not just documentation. It changes what
text appears in generated reports; it does not change any requirement check, scoring logic, or
verdict.

## 6. Packaging fix: PyInstaller's `build\` folder was never excluded

While rebuilding the release after the above, `package_release.py`'s `EXCLUDE_DIRS` turned out not
to include `build` — only `dist` was excluded. A local standalone-.exe build leaves a `build\`
folder (PyInstaller's intermediate cache, ~50 MB) sitting in the project root, and the previous
version of the script would have copied every byte of it into the staged folder and zipped it
straight into the release archive alongside the real 26 files. Fixed by adding `"build"` to
`EXCLUDE_DIRS`; see the `v1.63 changes:` note at the top of `package_release.py` itself.

## 7. Verification performed

- Re-extracted every paragraph, table cell, header, footer, and document-property field of the new
  manual with `python-docx` and grepped for stray `1.59`/`1.60`/`1.61`/`1.62` version stamps; the
  only remaining matches are the intentional historical references listed in §2.
- Rendered the new manual to PDF (LibreOffice `--convert-to pdf`) and visually reviewed the title
  page, the project-tree/CLI-example pages, and the packaging-output page to confirm the edits didn't
  disturb formatting, headers, footers, or page numbering.
- Re-ran `python package_release.py` against the cleaned-up folder; the manifest check (which aborts
  the build if any required release asset is missing) passed, and `dist\DGIWG_GeoPackage_Validator_v1.63.zip`
  was produced.

---

*`checks.py`, `constants.py`, `forensics.py`, `main.py`, `net.py`, and `utils.py` — the modules that
decide PASS/FAIL/PASS* and the verdict — did not change in this release. `html_report.py` and
`rollup.py` changed only in the footer text they emit (§5); no check logic in either file was
touched. For the actual behavioral history, see the v1.61 and v1.60 release notes, now under
`_superseded_pre_v1.63/`.*
