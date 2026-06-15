"""
DGIWG GeoPackage Compliance Validator v1.56
Double-click this file (or run: python DGIWG_Validator_v1_56.py) to launch.
"""
import sys
import os

# Ensure the dgiwg_validator package folder next to this script is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dgiwg_validator.main import main
main()
