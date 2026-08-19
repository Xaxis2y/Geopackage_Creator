# DGIWG GeoPackage Compliance Validator — Release Notes v1.59

Release date: 2026-08-13
Standard: DGIWG STD-DP-19-005 v1.1 (GeoPackage Profile 1.4, Edition 1.1)
Previous: v1.58 (pre-release)

v1.59 is the first **full release** of the 1.5x line. It closes every open item
left in `REVIEW_FINDINGS_v1.58.md`, updates all documentation, and adds a
quick-start page.

---

## 1. Behavioural changes — read before comparing output against v1.58

These change what the tool *reports*, not only how it words it.

### 1.1 Req 4 — CONFORMANT is now reachable (`checks.py`)

Req 4 (Optional Extensions) returned `PASS*` in every case, including when a
GeoPackage registered no optional extensions at all. Because the `CONFORMANT`
verdict requires zero `PASS*`, that one behaviour made the top verdict
**unreachable for every file ever tested**. Req 4 now distinguishes:

| Situation | v1.58 | v1.59 |
|---|---|---|
| No optional extension registered | `PASS*` | **`PASS`** |
| No `gpkg_extensions` table at all | `PASS*` | **`PASS`** |
| One or more registered | `PASS*` | `PASS*` + list + confirmation prompt |

Optional extensions still cannot produce `FAIL` — true by definition, unchanged.

> **Note for you, not a defect:** Req 20, 23, 28, 29, 31 and 32 are still capped
> at `PASS*` by their own design, so a real-world file will normally still land
> on `LIKELY CONFORMANT`. Req 4 was the only *unconditional* blocker, which is
> what the v1.58 review flagged. If you want `CONFORMANT` to be practically
> achievable as well, the caps on 20/23/28/29 are the next decision — tell me
> and I'll work through them.

### 1.2 Req 18 — the silent XSD gap is closed (`checks.py`, `utils.py`)

Req 18's deepest stage is XSD structural validation of DMF metadata against the
bundled schema — it catches wrong element order and missing mandatory children
that field-level checks cannot see. That stage requires `lxml`, and when `lxml`
was absent it was skipped **silently**.

The consequence: the same GeoPackage could report `PASS` on one workstation and
`FAIL` on another, with nothing in either report to explain the difference.

Now:

- Req 18 always states the XSD outcome in its detail text — `ENABLED`, or
  `SKIPPED` with the reason and the `pip install lxml` fix.
- A metadata document that passed only the field-level checks reports `PASS*`,
  not `PASS`. A partial check should not read as a full one.
- `lxml` was added to the startup optional-library probe. It was being used by
  the code but was not in the probe list, so a missing `lxml` was invisible
  before the run as well as after it.

### 1.3 `--quiet` is now actually quiet (`html_report.py`, `rollup.py`)

`"HTML report written:"`, `"Rollup HTML written:"` and `"Rollup CSV  written:"`
printed unconditionally, so `--quiet` still emitted one extra line per file plus
three per batch. All three now honour the flag. `--quiet` delivers exactly one
summary line per file — which is what makes it usable piped into a QA log.

---

## 2. Robustness fixes

| # | Fix | Why it mattered |
|---|---|---|
| 1 | `_manual_checks()` now returns uniform 4-tuples | Success paths returned 3-tuples, error paths 4-tuples. Consumers indexed defensively (`manual[3] if len(manual) > 3`), so any future `a, b, c = manual` unpack was a latent `ValueError` that only fired on the error path. |
| 2 | Result-dict consumers select rows by key **type** | Four sites filtered internal keys with a hardcoded blocklist of `__dunder__` names. Adding a fifth internal key and forgetting one site would call `v["status"]` on a plain string → `TypeError: string indices must be integers`, taking down report rendering. Requirement keys are always `int`; that is now the test. |
| 3 | Dead imports removed | `_http_get` / `_http_head` were imported by `checks.py` and never called. |
| 4 | `--help` examples corrected | Every example invoked `dgiwg_validator.py` — a filename that **does not exist** in the distribution. Now shows the versioned launcher and the module form, and covers `--quiet`, `--recursive`, `--output-dir`, `--fail-fast`. |

---

## 3. Reporting

**Conformance-scope banner (new).** The verdict line says CONFORMANT / LIKELY
CONFORMANT / NON-CONFORMANT, and readers reasonably take that as the whole
answer. It is not — Req 1, 2 and 6 are never executed. That caveat previously
lived only in the page footer, below everything else. It now sits directly under
the verdict, in both the per-file report and the roll-up, where the verdict is
actually read.

---

## 4. Documentation

- **`QUICKSTART.html` (new)** — one self-contained page: what the tool does,
  Anaconda setup, three ways to run it, how to read a verdict, the flags worth
  knowing, and a troubleshooting table. Prints cleanly.
- **User Manual → v1.59** (was v1.56, three versions stale). Rewritten
  throughout. New: complete option reference, exit codes, cascade advisory,
  source-software forensics, self-test and release-build procedures, expanded
  limitations. The requirement table is now generated *from
  `constants.py` itself*, so it can never drift from the code again — the v1.56
  manual still carried the pre-1.1 Req 1/2/15 names that v1.58 corrected.
- `build_manual.js` regenerates the manual and reads the requirement table from
  the package at build time. Maintainer tool; excluded from the release zip.

---

## 5. Packaging

- Archive is now `DGIWG_GeoPackage_Validator_v1.59.zip` — the `_pre` suffix is
  gone. `VERSION.txt` reads `(release)`.
- **Manifest check:** `package_release.py` verifies 16 required assets before it
  writes anything, and aborts if one is missing. A release can no longer ship
  without the manual, the quick-start page or the launcher.
- Superseded user manuals are excluded from the staged folder — only the current
  version ships.
- Launcher renamed `DGIWG_Validator_v1_58.py` → `DGIWG_Validator_v1_59.py`.

---

## 6. Testing

`run_local_tests.py` went from **40 to 62 assertions**, all passing. New
regression coverage, one test per change above:

- version stamp consistency across package / `VERSION.txt` / launcher filename /
  JSON `schema_version` / `--version`
- Req 4 returning `PASS` when no optional extension is registered
- `--quiet` emitting no report-written chatter while still printing the per-file
  summary line
- every manual-check entry being a uniform 4-tuple — verified by an actual
  4-way unpack, not just a length check
- the conformance-scope banner in per-file and roll-up HTML
- Req 18 stating the XSD outcome, matched against whether `lxml` is installed
- `lxml` present in the optional-library probe
- release assets present, and `QUICKSTART.html` carrying the right version

Expectation tables now adapt to `lxml` the same way they already adapted to
`shapely`, `Pillow` and `pyproj`, so the suite passes with or without it.

---

## 7. How to verify locally (Anaconda Prompt)

Never install into `base` — always use a dedicated environment:

```
conda create -n dgiwg python=3.11 -y
conda activate dgiwg
pip install shapely Pillow pyproj lxml
cd C:\Users\Son\Documents\DGIWG\DGIWG_GeoPackage_Validator_v1.58
python run_local_tests.py
```

Expected final lines:

```
RESULT: 62/62 assertions passed
ALL TESTS PASSED
```

A step-by-step log `local_test_log_<timestamp>.txt` is written next to the
script whether the run passes or fails. **Send that log back either way** — it
records the generated test data, the exact command lines, the full validator
output, and expected-versus-actual for every assertion.

Then build the archive:

```
python package_release.py
```

Output: `dist\DGIWG_GeoPackage_Validator_v1.59.zip`

---

## 8. Files changed

| File | Change |
|---|---|
| `dgiwg_validator/__init__.py` | `__version__ = "1.59"` |
| `dgiwg_validator/checks.py` | Req 4 semantics, Req 18 XSD reporting, 4-tuple normalisation, dead imports removed |
| `dgiwg_validator/utils.py` | `lxml` added to probe, `score_results()` key-type filtering |
| `dgiwg_validator/html_report.py` | scope banner, `--quiet` honoured, key-type filtering |
| `dgiwg_validator/rollup.py` | scope banner, `--quiet` honoured, key-type filtering |
| `dgiwg_validator/main.py` | corrected `--help` examples |
| `dgiwg_validator/config.py`, `constants.py`, `forensics.py`, `net.py` | version stamp only |
| `DGIWG_Validator_v1_59.py` | renamed from `_v1_58.py` |
| `VERSION.txt` | 1.59 (release) |
| `run_local_tests.py` | 40 → 62 assertions |
| `package_release.py` | manifest check, release naming, manual exclusion |
| `QUICKSTART.html` | **new** |
| `DGIWG_GeoPackage_Validator_User_Manual_v1.59.docx` | **new** (replaces v1.56) |
| `build_manual.js` | **new** — maintainer tool |
| `RELEASE_NOTES_v1.59.md` | **new** — this file |

---

*GPL-2.0-or-later — © 2026 Eui Soo SON*
*MCE/T&E — Mapping and Charting Establishment / Geomatics Engineering Trials & Evaluation Support Section (GETESS)*
