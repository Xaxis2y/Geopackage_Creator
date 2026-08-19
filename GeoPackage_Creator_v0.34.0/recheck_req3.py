"""Read-only Req 3 regression check for a folder of GeoPackages."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dgiwg_validator.checks import check_req
from dgiwg_validator.utils import open_gpkg


def main(folder: str) -> int:
    files = sorted(Path(folder).glob("*.gpkg"))
    failures = []
    for path in files:
        try:
            conn = open_gpkg(str(path))
            try:
                status, detail = check_req(conn.cursor(), 3)
            finally:
                conn.close()
        except Exception as exc:
            status, detail = "ERROR", str(exc)
        marker_issue = any(
            "application_id" in line
            and ("requires" in line.lower() or "unrecognised" in line.lower()
                 or "not a valid" in line.lower())
            for line in detail.splitlines()
        )
        print(f"{status:7} {path.name}" + ("  [application_id issue]" if marker_issue else ""))
        if marker_issue:
            failures.append(path.name)
    print(f"\nChecked {len(files)} files; application_id conformance violations: {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
