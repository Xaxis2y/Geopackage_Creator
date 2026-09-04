# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Unit tests for core/validation_gate.py

This module had NO test coverage before v0.34.3 despite carrying the
subprocess-isolation fix that was the whole point of v0.34.0 (the DGIWG
validator's Req 18 imports lxml, and running it in the same interpreter as
GDAL was causing Windows interpreter-shutdown crashes). These tests don't
require a real DGIWG validator or a real GeoPackage: they mock
subprocess.run and feed it a synthetic JSON report, so they exercise the
actual logic in this module (launcher discovery, command construction,
frozen-vs-source branching, report parsing, mandatory-FAIL detection)
without depending on an external validator install.

Tests verify:
- find_validator() / _find_validator_launcher() path discovery
- run_dgiwg_validation() command construction (source vs. frozen build)
- run_dgiwg_validation() JSON report parsing and conformance logic
- run_dgiwg_validation() error handling (validator missing, launcher
  missing, no report produced)
"""

import json
import sys
import types
from pathlib import Path

import pytest

from core import validation_gate as vg


def _make_validator_dir(base: Path, launcher_name: str = "DGIWG_Validator_v1_99.py") -> Path:
    """Build a minimal fake validator install: dgiwg_validator/checks.py
    (what find_validator() looks for) plus a launcher script (what
    _find_validator_launcher() looks for)."""
    vdir = base / "DGIWG_GeoPackage_Validator_v1.99"
    (vdir / "dgiwg_validator").mkdir(parents=True)
    (vdir / "dgiwg_validator" / "checks.py").write_text("", encoding="utf-8")
    if launcher_name:
        (vdir / launcher_name).write_text("", encoding="utf-8")
    return vdir


def _fake_subprocess_run(report_payload):
    """Return a fake subprocess.run() that writes *report_payload* as the
    JSON report the real validator would produce, into whatever
    --output-dir the caller passed, and hands back the (command, kwargs)
    it was called with for assertions."""
    calls = []

    def _run(command, **kwargs):
        calls.append((command, kwargs))
        output_dir = Path(command[command.index("--output-dir") + 1])
        report_file = output_dir / "sample_DGIWG_Report.json"
        report_file.write_text(json.dumps(report_payload), encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    _run.calls = calls
    return _run


SAMPLE_REPORT = {
    "counts": {"PASS": 2, "FAIL": 1, "SKIPPED": 1},
    "requirements": {
        "1": {"name": "Req 1", "compliance": "M", "status": "PASS", "detail": ""},
        "18": {"name": "Req 18 (lxml)", "compliance": "M", "status": "FAIL", "detail": "boom"},
        "30": {"name": "Req 30", "compliance": "O", "status": "SKIPPED", "detail": ""},
        "not_a_number": {"name": "internet check", "status": "SKIPPED"},
    },
}

SAMPLE_REPORT_ALL_PASS = {
    "counts": {"PASS": 2, "SKIPPED": 1},
    "requirements": {
        "1": {"name": "Req 1", "compliance": "M", "status": "PASS", "detail": ""},
        "30": {"name": "Req 30", "compliance": "O", "status": "SKIPPED", "detail": ""},
    },
}


class TestFindValidatorLauncher:
    """Test _find_validator_launcher() (v0.34.3).

    Replaces a hardcoded 'DGIWG_Validator_v1_62.py' filename that broke
    outright the moment the bundled validator was upgraded in place to
    v1.63 with no application code change.
    """

    def test_single_match_is_returned(self, tmp_path):
        vdir = _make_validator_dir(tmp_path, launcher_name="DGIWG_Validator_v1_63.py")

        result = vg._find_validator_launcher(vdir)

        assert result == vdir / "DGIWG_Validator_v1_63.py"

    def test_no_match_raises_file_not_found(self, tmp_path):
        vdir = _make_validator_dir(tmp_path, launcher_name=None)

        with pytest.raises(FileNotFoundError):
            vg._find_validator_launcher(vdir)

    def test_multiple_matches_raise_file_not_found(self, tmp_path):
        vdir = _make_validator_dir(tmp_path, launcher_name="DGIWG_Validator_v1_62.py")
        (vdir / "DGIWG_Validator_v1_63.py").write_text("", encoding="utf-8")

        with pytest.raises(FileNotFoundError):
            vg._find_validator_launcher(vdir)


class TestFindValidator:
    """Test find_validator() path discovery."""

    def test_explicit_validator_path_is_used_when_valid(self, tmp_path):
        vdir = _make_validator_dir(tmp_path)

        result = vg.find_validator(str(vdir))

        assert result == vdir

    def test_returns_none_when_nothing_resolves(self, monkeypatch, tmp_path):
        # Force every candidate (explicit path, env var, sibling search) to
        # miss. find_validator()'s sibling search walks up to TWO parent
        # directories from __file__ and globs **recursively** -- pointing
        # it at tmp_path directly is NOT isolated enough, because
        # tmp_path.parent is pytest's shared per-SESSION tmp root
        # (pytest-of-<user>/pytest-<N>/), and other tests' tmp_path
        # directories (pytest keeps the last few around, not just the
        # current one) live right there. This bit us for real: this test
        # intermittently failed by finding a sibling test's leftover
        # "DGIWG_GeoPackage_Validator_v1.99" fixture directory through that
        # recursive glob. Nesting three levels under THIS test's own
        # tmp_path keeps every candidate directory private to this test.
        monkeypatch.delenv("DGIWG_VALIDATOR_PATH", raising=False)
        isolated = tmp_path / "a" / "b" / "c"
        isolated.mkdir(parents=True)
        monkeypatch.setattr(vg, "__file__", str(isolated / "validation_gate.py"))

        result = vg.find_validator(str(tmp_path / "does_not_exist"))

        assert result is None


class TestRunDgiwgValidation:
    """Test run_dgiwg_validation()'s subprocess orchestration and report
    parsing -- the code path that replaced the old in-process `from
    dgiwg_validator import checks` call in v0.34.0 to stop mixing GDAL and
    lxml's native XML stacks in one interpreter."""

    def test_validator_not_found_reports_unavailable(self, monkeypatch):
        monkeypatch.setattr(vg, "find_validator", lambda *a, **kw: None)

        result = vg.run_dgiwg_validation("/some/output.gpkg")

        assert result["available"] is False
        assert result["error"]
        assert result["conformant"] is None

    def test_missing_launcher_is_reported_as_error_not_a_crash(self, monkeypatch, tmp_path):
        vdir = _make_validator_dir(tmp_path, launcher_name=None)
        monkeypatch.setattr(vg, "find_validator", lambda *a, **kw: vdir)

        result = vg.run_dgiwg_validation("/some/output.gpkg")

        assert result["available"] is False
        assert "launcher" in result["error"].lower()

    def test_mandatory_fail_makes_result_non_conformant(self, monkeypatch, tmp_path):
        vdir = _make_validator_dir(tmp_path)
        monkeypatch.setattr(vg, "find_validator", lambda *a, **kw: vdir)
        monkeypatch.setattr(vg.subprocess, "run", _fake_subprocess_run(SAMPLE_REPORT))
        monkeypatch.setattr(sys, "frozen", False, raising=False)

        result = vg.run_dgiwg_validation("/some/output.gpkg")

        assert result["available"] is True
        assert result["conformant"] is False  # Req 18 is Mandatory + FAIL
        assert result["summary"] == {"PASS": 2, "FAIL": 1, "SKIPPED": 1}
        assert result["requirements"][18]["status"] == "FAIL"
        assert result["requirements"][18]["type"] == "M"
        assert result["requirements"][1]["status"] == "PASS"
        # The non-integer "__internet__"-style key must be skipped, not
        # crash the loop or appear in the parsed requirements.
        assert all(isinstance(k, int) for k in result["requirements"])

    def test_all_pass_is_conformant(self, monkeypatch, tmp_path):
        vdir = _make_validator_dir(tmp_path)
        monkeypatch.setattr(vg, "find_validator", lambda *a, **kw: vdir)
        monkeypatch.setattr(vg.subprocess, "run", _fake_subprocess_run(SAMPLE_REPORT_ALL_PASS))
        monkeypatch.setattr(sys, "frozen", False, raising=False)

        result = vg.run_dgiwg_validation("/some/output.gpkg")

        assert result["available"] is True
        assert result["conformant"] is True

    def test_no_report_produced_is_a_reported_error(self, monkeypatch, tmp_path):
        vdir = _make_validator_dir(tmp_path)
        monkeypatch.setattr(vg, "find_validator", lambda *a, **kw: vdir)

        def _run_without_writing_report(command, **kwargs):
            return types.SimpleNamespace(returncode=1, stdout="", stderr="validator crashed")

        monkeypatch.setattr(vg.subprocess, "run", _run_without_writing_report)

        result = vg.run_dgiwg_validation("/some/output.gpkg")

        assert result["available"] is False
        assert "did not create a json report" in result["error"].lower()

    def test_source_run_invokes_launcher_script_directly(self, monkeypatch, tmp_path):
        vdir = _make_validator_dir(tmp_path)
        monkeypatch.setattr(vg, "find_validator", lambda *a, **kw: vdir)
        fake_run = _fake_subprocess_run(SAMPLE_REPORT_ALL_PASS)
        monkeypatch.setattr(vg.subprocess, "run", fake_run)
        monkeypatch.setattr(sys, "frozen", False, raising=False)

        vg.run_dgiwg_validation("/some/output.gpkg", offline=True)

        (command, kwargs) = fake_run.calls[0]
        assert command[0] == sys.executable
        assert command[1] == str(vdir / "DGIWG_Validator_v1_99.py")
        assert "--offline" in command
        assert command[-1] == "/some/output.gpkg"
        # Source runs don't need the worker-dir override -- the launcher
        # path is already explicit on the command line.
        assert "DGIWG_VALIDATOR_WORKER_DIR" not in kwargs.get("env", {})

    def test_frozen_run_reinvokes_self_and_passes_worker_dir(self, monkeypatch, tmp_path):
        """v0.34.3: the frozen build must tell the --dgiwg-validator-worker
        subprocess which validator directory find_validator() actually
        resolved (via an env var), instead of letting app_main.py silently
        fall back to whichever copy happens to be bundled -- otherwise an
        explicit --validator-path / DGIWG_VALIDATOR_PATH override is
        honored when run from source but silently ignored once packaged."""
        vdir = _make_validator_dir(tmp_path)
        monkeypatch.setattr(vg, "find_validator", lambda *a, **kw: vdir)
        fake_run = _fake_subprocess_run(SAMPLE_REPORT_ALL_PASS)
        monkeypatch.setattr(vg.subprocess, "run", fake_run)
        monkeypatch.setattr(sys, "frozen", True, raising=False)

        vg.run_dgiwg_validation("/some/output.gpkg")

        (command, kwargs) = fake_run.calls[0]
        assert command[0] == sys.executable
        assert command[1] == "--dgiwg-validator-worker"
        assert kwargs["env"]["DGIWG_VALIDATOR_WORKER_DIR"] == str(vdir)
