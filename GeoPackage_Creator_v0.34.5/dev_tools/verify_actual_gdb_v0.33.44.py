#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""Convert a supplied production GDB with the EXE and independently run DGIWG."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python dev_tools\\verify_actual_gdb_v0.33.44.py C:\\path\\to\\source.gdb [path\\to\\GeoPackageCreator.exe]")
        return 2
    source = Path(sys.argv[1]).resolve()
    exe = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else ROOT / "dist" / "GeoPackageCreator.exe"
    is_file_gdb = source.is_dir() and (
        source.suffix.lower() == ".gdb" or any(source.glob("GEODATABASE_FILE_*"))
    )
    if not is_file_gdb:
        print(f"FAIL: not a File Geodatabase directory: {source}"); return 2
    if not exe.is_file():
        print(f"FAIL: executable not found: {exe}"); return 2
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "release_verification" / f"actual_gdb_{stamp}"; out_dir.mkdir(parents=True)
    output = out_dir / f"{source.stem}.gpkg"; log_path = out_dir / "verification.log"
    def run_and_log(command: list[str], label: str) -> int:
        with log_path.open("a", encoding="utf-8", buffering=1) as log:
            log.write(f"\n=== {label} ===\n$ {' '.join(command)}\n"); log.flush()
            run = subprocess.run(command, capture_output=True, text=True, timeout=1800)
            log.write(run.stdout + run.stderr + f"\nexit={run.returncode}\n"); log.flush(); os.fsync(log.fileno())
        return run.returncode
    conversion = [str(exe), "--source", str(source), "--output", str(output), "--title", source.stem, "--org", "Release Verification", "--nation", "USA", "--poc", "Release Test", "--abstract", "Real File Geodatabase release verification", "--security", "UNCLASSIFIED", "--category", "location", "--profile", "military", "--validate", "--verbose"]
    if run_and_log(conversion, "EXE conversion plus bundled validator") != 0 or not output.is_file():
        print(f"FAIL: conversion did not complete. Read {log_path}"); return 1
    with sqlite3.connect(output) as conn:
        app_id = conn.execute("PRAGMA application_id").fetchone()[0]; user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"SQLite header: application_id=0x{app_id:08X}; user_version={user_version}\n")
    validator = ROOT / "DGIWG_GeoPackage_Validator_v1.62" / "DGIWG_Validator_v1_62.py"
    if run_and_log([sys.executable, str(validator), "--offline", "--no-install", "--file", str(output), "--output-dir", str(out_dir / "validator_reports")], "Independent DGIWG validator") != 0:
        print(f"FAIL: independent DGIWG validation failed. Read {log_path}"); return 1
    if (app_id, user_version) != (0x47504B47, 10400):
        print(f"FAIL: non-conformant header. Read {log_path}"); return 1
    print(f"PASS: real GDB conversion and independent DGIWG validation complete. Log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
