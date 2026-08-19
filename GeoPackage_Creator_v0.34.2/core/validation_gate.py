# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
DGIWG Validation Gate (v0.27.0)

Optional post-conversion self-certification: runs the external DGIWG
GeoPackage Validator (currently v1.62) against the freshly created
GeoPackage and returns a per-requirement PASS / PASS* / FAIL / SKIPPED table
covering all 37 DGIWG GeoPackage Profile requirements.

The validator is NOT bundled with this tool (it is maintained separately).
This module locates it at runtime:

1. An explicit ``validator_path`` argument (CLI: --validator-path)
2. The ``DGIWG_VALIDATOR_PATH`` environment variable
3. Well-known sibling locations relative to this installation
   (e.g. DGIWG_GeoPackage_Validator_v1.62)

If the validator cannot be found, validation is skipped gracefully and the
conversion result records why.
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def find_validator(validator_path: Optional[str] = None) -> Optional[Path]:
    """Locate a directory containing the ``dgiwg_validator`` package.

    Args:
        validator_path: Optional explicit path to the validator directory
            (the folder that CONTAINS the ``dgiwg_validator`` package).

    Returns:
        Path to the directory to add to sys.path, or None if not found.
    """
    candidates = []

    if validator_path:
        candidates.append(Path(validator_path))

    env = os.environ.get("DGIWG_VALIDATOR_PATH")
    if env:
        candidates.append(Path(env))

    # Well-known locations relative to this installation
    here = Path(__file__).resolve().parent.parent  # tool root
    for base in (here, here.parent, here.parent.parent):
        try:
            # Search for both old naming (DGIWG_Validator_v1_5x) and new
            # naming (DGIWG_GeoPackage_Validator_v1.x) patterns
            for hit in base.glob("**/DGIWG_Validator_v1_5*"):
                if hit.is_dir():
                    candidates.append(hit)
            for hit in base.glob("**/DGIWG_GeoPackage_Validator_v1.*"):
                if hit.is_dir():
                    candidates.append(hit)
        except OSError:
            continue

    for cand in candidates:
        if (cand / "dgiwg_validator" / "checks.py").exists():
            return cand
        if (cand / "checks.py").exists() and cand.name == "dgiwg_validator":
            return cand.parent

    return None


def run_dgiwg_validation(
    gpkg_path: str,
    validator_path: Optional[str] = None,
    offline: bool = True,
) -> Dict[str, Any]:
    """Run the external DGIWG validator against a GeoPackage.

    Args:
        gpkg_path: Path to the GeoPackage to validate.
        validator_path: Optional explicit validator location.
        offline: When True (default) the validator's internet checks are
            disabled so validation works on air-gapped networks.

    Returns:
        Dict with keys:
            available (bool)  - validator found and ran
            validator_dir     - where it was found (str or None)
            summary           - counts per status (PASS / PASS* / FAIL / SKIPPED)
            conformant (bool) - True when no mandatory requirement FAILed
            requirements      - {req_num: {"title", "type", "status", "detail"}}
            error             - error message when available is False
    """
    out: Dict[str, Any] = {
        "available": False,
        "validator_dir": None,
        "summary": {},
        "conformant": None,
        "requirements": {},
        "error": None,
    }

    vdir = find_validator(validator_path)
    if vdir is None:
        out["error"] = (
            "DGIWG validator not found. Set --validator-path or the "
            "DGIWG_VALIDATOR_PATH environment variable to the folder "
            "containing the 'dgiwg_validator' package."
        )
        logger.warning(out["error"])
        return out

    try:
        # The validator's Req 18 imports lxml.  Keep it out of this process:
        # conversion has already imported GDAL, and mixing the two native XML
        # stacks caused Windows interpreter-shutdown crashes in prior releases.
        launcher = vdir / "DGIWG_Validator_v1_62.py"
        if not launcher.is_file():
            raise FileNotFoundError(f"Validator launcher not found: {launcher}")

        with tempfile.TemporaryDirectory(prefix="gpkg_dgiwg_") as report_dir:
            if getattr(sys, "frozen", False):
                command = [sys.executable, "--dgiwg-validator-worker"]
            else:
                command = [sys.executable, str(launcher)]
            command.extend(["--no-install", "--quiet", "--output-dir", report_dir])
            if offline:
                command.append("--offline")
            command.append(str(gpkg_path))
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1800,
            )
            reports = list(Path(report_dir).glob("*_DGIWG_Report*.json"))
            if not reports:
                raise RuntimeError(
                    "Validator did not create a JSON report "
                    f"(exit={completed.returncode}): {completed.stderr[-1000:]}"
                )
            payload = json.loads(reports[0].read_text(encoding="utf-8"))

        summary = {str(k): int(v) for k, v in payload.get("counts", {}).items()}
        mandatory_fail = False
        for raw_num, info in payload.get("requirements", {}).items():
            try:
                req_num = int(raw_num)
            except (TypeError, ValueError):
                continue
            req_type = str(info.get("compliance", "?"))
            status = str(info.get("status", "?"))
            if status == "FAIL" and req_type == "M":
                mandatory_fail = True
            out["requirements"][req_num] = {
                "title": str(info.get("name", "?")),
                "type": req_type,
                "status": status,
                "detail": str(info.get("detail", ""))[:2000],
            }

        out["summary"] = summary
        out["conformant"] = not mandatory_fail
        out["available"] = True
        out["validator_dir"] = str(vdir)
        return out

    except Exception as e:
        out["error"] = f"Validator runtime error: {e}"
        logger.error(out["error"])
        return out
