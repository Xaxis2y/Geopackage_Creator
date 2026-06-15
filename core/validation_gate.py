"""
DGIWG Validation Gate (v0.27.0)

Optional post-conversion self-certification: runs the external DGIWG
GeoPackage Validator (DGIWG_Validator_v1_5x) against the freshly created
GeoPackage and returns a per-requirement PASS / PASS* / FAIL / SKIPPED table
covering all 37 DGIWG GeoPackage Profile requirements.

The validator is NOT bundled with this tool (it is maintained separately).
This module locates it at runtime:

1. An explicit ``validator_path`` argument (CLI: --validator-path)
2. The ``DGIWG_VALIDATOR_PATH`` environment variable
3. Well-known sibling locations relative to this installation
   (e.g. ../GeoPackage_Creator_v0.26.0/DGIWG_Validator_v1_56_updated)

If the validator cannot be found, validation is skipped gracefully and the
conversion result records why.
"""

import logging
import os
import sqlite3
import sys
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
            for hit in base.glob("**/DGIWG_Validator_v1_5*"):
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

    sys.path.insert(0, str(vdir))
    try:
        import builtins
        if offline:
            builtins._DGIWG_OFFLINE = True

        from dgiwg_validator import checks as _checks
        from dgiwg_validator.constants import REQUIREMENTS as _REQS

        conn = sqlite3.connect(gpkg_path)
        try:
            results = _checks.run_all_checks(conn)
        finally:
            conn.close()

        summary: Dict[str, int] = {}
        mandatory_fail = False
        for req_num, info in results.items():
            if not isinstance(req_num, int):
                continue  # skip __internet__ etc.
            title, uri, req_type = _REQS.get(req_num, ("?", "?", "?"))
            status = str(info.get("status", "?"))
            summary[status] = summary.get(status, 0) + 1
            if status == "FAIL" and req_type == "M":
                mandatory_fail = True
            out["requirements"][req_num] = {
                "title": title,
                "type": req_type,
                "status": status,
                "detail": str(info.get("detail", ""))[:2000],
            }

        out["available"] = True
        out["validator_dir"] = str(vdir)
        out["summary"] = summary
        out["conformant"] = not mandatory_fail
        logger.info(
            f"DGIWG validation: {summary} "
            f"({'CONFORMANT' if out['conformant'] else 'NON-CONFORMANT'})"
        )
        return out

    except Exception as e:  # pragma: no cover - defensive
        out["error"] = f"DGIWG validation failed to run: {e}"
        logger.warning(out["error"])
        return out
    finally:
        try:
            sys.path.remove(str(vdir))
        except ValueError:
            pass
