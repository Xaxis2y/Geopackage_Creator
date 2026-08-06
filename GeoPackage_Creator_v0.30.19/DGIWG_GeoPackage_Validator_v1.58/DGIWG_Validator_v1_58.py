# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
DGIWG GeoPackage Compliance Validator v1.58
Double-click this file (or run: python DGIWG_Validator_v1_58.py) to launch.
"""
import sys
import os

# Ensure the dgiwg_validator package folder next to this script is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dgiwg_validator.main import main
main()
