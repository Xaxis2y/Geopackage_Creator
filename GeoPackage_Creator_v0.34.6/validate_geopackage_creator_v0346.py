#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""GeoPackage Creator v0.34.6 full validation runner, version 1.2.0.

Run this from an activated dedicated Conda environment, never from base:

    conda activate geopackage
    cd C:/Users/Son/Documents/Geopackage_Creator/GeoPackage_Creator_v0.34.6_GitHub_Source_clean/GeoPackage_Creator_v0.34.6
    python validate_geopackage_creator_v0346.py

The script expects to be beside core/, SampleData.gdb, and States.gdb.  Use
--project or --samples only when using a different layout.

The script does not edit the project under test.  It writes a timestamped
evidence folder and ZIP beneath --output-root (default: validation_runs).
It exits 0 only when the technical checks pass and no release evidence is
missing, 1 when a technical check fails, and 2 when tests completed but the
release remains on HOLD for external or untested DGIWG evidence.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import os
import shutil
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


APP_VERSION = "0.34.6"
SCRIPT_VERSION = "1.2.0"
REQUIRED_MODULES = ("osgeo", "lxml", "pyproj", "PIL", "shapely", "pytest")


@dataclass
class ValidationState:
    failures: list[str] = field(default_factory=list)
    holds: list[str] = field(default_factory=list)


class ValidationRunner:
    """Run reproducible source, validator, and real-data evidence checks."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.project = args.project.resolve()
        self.samples = args.samples.resolve()
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_root = args.output_root.resolve()
        self.work = self.output_root / f"GeoPackage_Creator_v{APP_VERSION}_validation_{stamp}"
        self.evidence = self.work / "evidence"
        self.temp_dir = self.work / "temp"
        self.state = ValidationState()
        self.log_path = self.evidence / "validation.log"
        self.python = Path(sys.executable).resolve()

    def prepare(self) -> None:
        self.evidence.mkdir(parents=True, exist_ok=False)
        self.temp_dir.mkdir(parents=True, exist_ok=False)
        self.log("GeoPackage Creator v%s validation runner v%s", APP_VERSION, SCRIPT_VERSION)
        self.log("Python executable: %s", self.python)
        self.log("Project: %s", self.project)
        self.log("Samples: %s", self.samples)
        self.log("Evidence directory: %s", self.evidence)

    def log(self, message: str, *args: object) -> None:
        text = message % args if args else message
        line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {text}"
        print(line)
        with self.log_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line + "\n")

    def fail(self, message: str) -> None:
        self.state.failures.append(message)
        self.log("FAIL: %s", message)

    def hold(self, message: str) -> None:
        self.state.holds.append(message)
        self.log("HOLD: %s", message)

    def command_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["TEMP"] = str(self.temp_dir)
        env["TMP"] = str(self.temp_dir)
        return env

    def run_command(self, label: str, command: Iterable[object], cwd: Path) -> subprocess.CompletedProcess[str]:
        rendered = [str(item) for item in command]
        self.log("BEGIN %s", label)
        self.log("COMMAND: %s", subprocess.list2cmdline(rendered))
        completed = subprocess.run(
            rendered,
            cwd=str(cwd),
            env=self.command_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output_path = self.evidence / f"{label}.txt"
        output_path.write_text(completed.stdout or "", encoding="utf-8")
        if completed.stdout:
            with self.log_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(completed.stdout)
                if not completed.stdout.endswith("\n"):
                    stream.write("\n")
        self.log("END %s exit_code=%d output=%s", label, completed.returncode, output_path.name)
        return completed

    def verify_inputs(self) -> bool:
        valid = True
        if not self.project.is_dir():
            self.fail(f"Project directory does not exist: {self.project}")
            valid = False
        if not (self.project / "core" / "converter.py").is_file():
            self.fail("Project does not contain core/converter.py")
            valid = False
        if not (self.project / "tests").is_dir():
            self.fail("Project does not contain tests/")
            valid = False
        if not self.samples.is_dir():
            self.fail(f"Sample directory does not exist: {self.samples}")
            valid = False
        for name in ("SampleData.gdb", "States.gdb"):
            if not (self.samples / name).is_dir():
                self.fail(f"Required sample FileGDB is missing: {name}")
                valid = False
        return valid

    def verify_conda_environment(self) -> bool:
        env_name = os.environ.get("CONDA_DEFAULT_ENV")
        self.log("CONDA_DEFAULT_ENV=%s", env_name or "<not set>")
        if env_name and env_name.lower() == "base":
            self.fail("Refusing to run in the Conda base environment. Activate a dedicated environment first.")
            return False
        if not env_name:
            self.hold("CONDA_DEFAULT_ENV is not set. Confirm this Python belongs to a dedicated Conda environment.")

        versions: dict[str, str] = {}
        for module_name in REQUIRED_MODULES:
            try:
                module = importlib.import_module(module_name)
                versions[module_name] = str(getattr(module, "__version__", "available"))
            except Exception as exc:
                self.fail(f"Required module '{module_name}' cannot be imported: {type(exc).__name__}: {exc}")

        try:
            from osgeo import gdal

            versions["gdal"] = gdal.VersionInfo("--version")
        except Exception as exc:
            self.fail(f"GDAL runtime probe failed: {type(exc).__name__}: {exc}")

        try:
            from lxml import etree

            compiled = tuple(etree.LIBXML_COMPILED_VERSION)
            runtime = tuple(etree.LIBXML_VERSION)
            versions["libxml2_compiled"] = str(compiled)
            versions["libxml2_runtime"] = str(runtime)
            if compiled != runtime:
                self.fail(f"lxml/libxml2 ABI mismatch: compiled={compiled}, runtime={runtime}")
        except Exception as exc:
            self.fail(f"lxml/libxml2 ABI probe failed: {type(exc).__name__}: {exc}")

        (self.evidence / "environment_versions.json").write_text(
            json.dumps(versions, indent=2, sort_keys=True), encoding="utf-8"
        )
        self.log("Environment versions: %s", json.dumps(versions, sort_keys=True))
        return not self.state.failures

    def run_pytest(self) -> None:
        baseline = self.work / "pytest_basetemp"
        completed = self.run_command(
            "pytest_full_suite",
            (
                self.python,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                baseline,
            ),
            self.project,
        )
        if completed.returncode != 0:
            self.fail("Full pytest suite failed. See pytest_full_suite.txt.")

    def run_validator_self_test(self) -> None:
        source = self.project / "DGIWG_GeoPackage_Validator_v1.63"
        if not source.is_dir():
            self.fail("Bundled DGIWG_GeoPackage_Validator_v1.63 directory is missing.")
            return
        copy = self.work / "validator_self_test_copy"
        shutil.copytree(
            source,
            copy,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "reports", "local_test", "dist", "build"),
        )
        completed = self.run_command(
            "bundled_validator_self_test",
            (self.python, copy / "run_local_tests.py"),
            copy,
        )
        if completed.returncode != 0 or "ALL TESTS PASSED" not in completed.stdout:
            self.fail("Bundled validator self-test failed. See bundled_validator_self_test.txt.")
        for log_file in copy.glob("local_test_log_*.txt"):
            shutil.copy2(log_file, self.evidence / log_file.name)

    def run_real_gdb_audit(self) -> Path | None:
        tool = self.project / "dev_tools" / "dgiwg_gdb_audit_v2.2.py"
        if not tool.is_file():
            self.fail("Real-FileGDB audit tool is missing: dev_tools/dgiwg_gdb_audit_v2.2.py")
            return None
        audit_work = self.work / "real_gdb_audit"
        completed = self.run_command(
            "real_gdb_audit",
            (
                self.python,
                tool,
                "--project",
                self.project,
                "--samples",
                self.samples,
                "--with-validator",
                "--workdir",
                audit_work,
            ),
            self.project,
        )
        if completed.returncode != 0:
            self.fail("Real-FileGDB audit failed. See real_gdb_audit.txt.")
            return None
        for path in sorted((audit_work / "logs").glob("*")):
            if path.is_file():
                shutil.copy2(path, self.evidence / path.name)
        reports = sorted((audit_work / "logs").glob("dgiwg_audit_*.json"))
        if not reports:
            self.fail("Real-FileGDB audit did not write its JSON evidence file.")
            return None
        report = reports[-1]
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
            statuses: dict[str, int] = {}
            for item in payload.get("results", []):
                status = str(item.get("status", "UNKNOWN"))
                statuses[status] = statuses.get(status, 0) + 1
            self.log("Independent real-FileGDB audit statuses: %s", statuses)
            if statuses.get("FAIL", 0):
                self.fail(f"Independent real-FileGDB audit reported {statuses['FAIL']} FAIL result(s).")
            validator_failures: list[str] = []
            for item in payload.get("results", []):
                if item.get("check") != "bundled_validator":
                    continue
                detail = item.get("detail", {})
                fail_count = int(detail.get("summary", {}).get("FAIL", 0) or 0)
                if fail_count:
                    validator_failures.append(f"{item.get('case', 'unknown')}={fail_count}")
            if validator_failures:
                self.fail(
                    "Bundled validator reported DGIWG FAIL requirement(s) for real conversion(s): "
                    + ", ".join(validator_failures)
                )
        except Exception as exc:
            self.fail(f"Could not parse real-FileGDB audit JSON: {type(exc).__name__}: {exc}")
        return audit_work

    def run_full_coverage_validator(self, audit_work: Path | None) -> None:
        if audit_work is None:
            return
        input_gpkg = audit_work / "S1_SampleData.gpkg"
        launcher = self.project / "DGIWG_GeoPackage_Validator_v1.63" / "DGIWG_Validator_v1_63.py"
        if not input_gpkg.is_file():
            self.fail("Expected SampleData audit GeoPackage was not created.")
            return
        if not launcher.is_file():
            self.fail("Bundled DGIWG validator launcher is missing.")
            return
        report_dir = self.work / "full_coverage_validator_reports"
        completed = self.run_command(
            "full_coverage_validator",
            (
                self.python,
                launcher,
                "--no-install",
                "--offline",
                "--quiet",
                "--output-dir",
                report_dir,
                input_gpkg,
            ),
            self.project,
        )
        if completed.returncode != 0:
            self.fail("Bundled validator did not complete. See full_coverage_validator.txt.")
            return
        json_reports = sorted(report_dir.glob("*_DGIWG_Report.json"))
        if not json_reports:
            self.fail("Bundled validator did not write a JSON report.")
            return
        report = json_reports[-1]
        shutil.copy2(report, self.evidence / report.name)
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
            counts = payload.get("counts", {})
            verdict = str(payload.get("verdict", "UNKNOWN"))
            self.log("Bundled validator verdict: %s", verdict)
            self.log("Bundled validator counts: %s", json.dumps(counts, sort_keys=True))
            requirements = payload.get("requirements", {})
            for req_num in ("1", "2", "6", "24", "26"):
                result = requirements.get(req_num, {})
                self.log(
                    "Requirement %s: status=%s reason=%s detail=%s",
                    req_num,
                    result.get("status"),
                    result.get("reason"),
                    str(result.get("detail", "")).replace("\n", " ")[:500],
                )

            failed_requirements = [
                str(number)
                for number, result in requirements.items()
                if result.get("status") == "FAIL"
            ]
            if failed_requirements:
                self.fail(
                    "Bundled validator reported DGIWG FAIL requirement(s): "
                    + ", ".join(sorted(failed_requirements, key=int))
                )

            missing_evidence = [
                str(number)
                for number, result in requirements.items()
                if result.get("status") == "PASS*" and result.get("reason") == "EVIDENCE_MISSING"
            ]
            if missing_evidence:
                self.hold(
                    "Automated DGIWG evidence remains incomplete for requirement(s): "
                    + ", ".join(sorted(missing_evidence, key=int))
                )
            for req_num in ("1", "2"):
                if requirements.get(req_num, {}).get("status") == "SKIPPED":
                    self.hold(
                        f"DGIWG requirement {req_num} requires OGC CITE/TeamEngine evidence outside this local runner."
                    )
            if requirements.get("6", {}).get("status") == "SKIPPED":
                self.hold("DGIWG requirement 6 needs the intended product profile decision.")
        except Exception as exc:
            self.fail(f"Could not parse bundled validator JSON: {type(exc).__name__}: {exc}")

    def test_optional_executable(self) -> None:
        if self.args.exe is None:
            self.hold("No built GeoPackageCreator.exe was supplied, so frozen Windows runtime validation is not evidenced.")
            return
        executable = self.args.exe.resolve()
        if not executable.is_file():
            self.fail(f"Requested executable does not exist: {executable}")
            return
        for label, extra_args in (("frozen_exe_version", ("--version",)), ("frozen_exe_help", ("--help",))):
            completed = self.run_command(label, (executable, *extra_args), executable.parent)
            if completed.returncode != 0:
                self.fail(f"Frozen executable command failed: {label}")

    def package_evidence(self) -> Path:
        archive_base = self.output_root / f"{self.work.name}_evidence"
        self.log("Creating evidence ZIP beside the evidence directory.")
        archive = Path(shutil.make_archive(str(archive_base), "zip", root_dir=self.evidence))
        print(f"Evidence ZIP: {archive}")
        return archive

    def finish(self) -> int:
        self.log("Technical failures: %d", len(self.state.failures))
        self.log("Release holds: %d", len(self.state.holds))
        for message in self.state.failures:
            self.log("FAILURE SUMMARY: %s", message)
        for message in self.state.holds:
            self.log("HOLD SUMMARY: %s", message)
        if self.state.failures:
            self.log("FINAL VERDICT: TECHNICAL TEST FAILURE")
            return 1
        if self.state.holds:
            self.log("FINAL VERDICT: TESTS COMPLETED - RELEASE HOLD")
            return 2
        self.log("FINAL VERDICT: TECHNICAL EVIDENCE COMPLETE")
        return 0

    def execute(self) -> int:
        self.prepare()
        if not self.verify_inputs() or not self.verify_conda_environment():
            exit_code = self.finish()
            self.package_evidence()
            return exit_code
        self.run_pytest()
        self.run_validator_self_test()
        audit_work = self.run_real_gdb_audit()
        self.run_full_coverage_validator(audit_work)
        self.test_optional_executable()
        exit_code = self.finish()
        self.package_evidence()
        return exit_code


def parse_arguments() -> argparse.Namespace:
    script_directory = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Run reproducible GeoPackage Creator v0.34.6 validation evidence checks."
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=script_directory,
        help="Project root. Defaults to the folder containing this script.",
    )
    parser.add_argument(
        "--samples",
        type=Path,
        default=script_directory,
        help="Folder containing SampleData.gdb and States.gdb. Defaults to this script's folder.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=script_directory / "validation_runs",
        help="Parent directory for timestamped logs and the evidence ZIP. Defaults to validation_runs here.",
    )
    parser.add_argument(
        "--exe",
        type=Path,
        default=None,
        help="Optional built GeoPackageCreator.exe for --version/--help smoke checks.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    try:
        return ValidationRunner(args).execute()
    except KeyboardInterrupt:
        print("Validation interrupted by user.")
        return 130
    except Exception:
        print("Validation runner crashed. Traceback follows:")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
