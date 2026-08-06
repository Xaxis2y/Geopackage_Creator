#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
GeoPackage Creator - Main Entry Point

A simple, straightforward way to convert geospatial data to OGC/DGIWG-compliant GeoPackages.

Quick Start:
    python geopackage_creator.py \
        --source input.gdb \
        --output output.gpkg \
        --title "My Dataset" \
        --org "My Organization" \
        --nation "USA"

Or use as a Python module:
    from geopackage_creator import GeoPackageConverter
    converter = GeoPackageConverter(profile='military')
    result = converter.convert(...)
"""

import argparse
import sys
import logging
from pathlib import Path

# Import the converter
from core.converter import GeoPackageConverter


def setup_logging(verbose=False):
    """Configure logging output."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def validate_arguments(args):
    """Validate command-line arguments."""
    errors = []

    # Check source file exists
    if not Path(args.source).exists():
        errors.append(f"Source file not found: {args.source}")

    # Check parent directory of output exists
    output_dir = Path(args.output).parent
    if not output_dir.exists():
        errors.append(f"Output directory does not exist: {output_dir}")

    # Check required metadata
    if not args.title:
        errors.append("Title is required (--title)")
    if not args.org:
        errors.append("Organization is required (--org)")
    if not args.nation:
        errors.append("Nation code is required (--nation)")

    if errors:
        for error in errors:
            print(f"✗ {error}", file=sys.stderr)
        return False

    return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Convert geospatial data to OGC/DGIWG-compliant GeoPackages',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Convert File Geodatabase
  python geopackage_creator.py \\
    --source buildings.gdb \\
    --output buildings.gpkg \\
    --title "Building Footprints" \\
    --org "City Planning" \\
    --nation "USA"

  # Convert with military profile
  python geopackage_creator.py \\
    --source roads.shp \\
    --output roads.gpkg \\
    --title "Road Network" \\
    --profile military \\
    --org "Defense Mapping" \\
    --nation "USA" \\
    --security CONFIDENTIAL

  # Convert with all metadata
  python geopackage_creator.py \\
    --source data.geojson \\
    --output data.gpkg \\
    --title "My Dataset" \\
    --abstract "Full description of the data" \\
    --poc "John Smith" \\
    --org "Organization Name" \\
    --nation "USA" \\
    --security UNCLASSIFIED \\
    --language eng \\
    --category transportation \\
    --ref-date 2026-06-03
        '''
    )

    # Required arguments
    parser.add_argument(
        '--source', '-s',
        required=True,
        help='Source file: .gdb, .shp, .geojson, or PostGIS connection string'
    )
    parser.add_argument(
        '--output', '-o',
        required=True,
        help='Output GeoPackage file (.gpkg)'
    )
    parser.add_argument(
        '--title', '-t',
        required=True,
        help='Dataset title for metadata'
    )
    parser.add_argument(
        '--org',
        required=True,
        help='Organization name'
    )
    parser.add_argument(
        '--nation',
        required=True,
        help='ISO 3166-1 alpha-3 country code (e.g., USA, GBR, DEU)'
    )

    # Optional metadata
    parser.add_argument(
        '--abstract', '-a',
        help='Dataset abstract/description'
    )
    parser.add_argument(
        '--poc', '-p',
        help='Point of contact (person name)'
    )
    parser.add_argument(
        '--security',
        choices=['UNCLASSIFIED', 'RESTRICTED', 'CONFIDENTIAL', 'SECRET',
                 'TOP SECRET', 'NATO UNCLASSIFIED', 'NATO RESTRICTED',
                 'NATO CONFIDENTIAL', 'NATO SECRET', 'COSMIC TOP SECRET'],
        help='Security classification level - national or NATO marking '
             '(use quotes for multi-word values, e.g. "NATO SECRET")'
    )
    parser.add_argument(
        '--releasability',
        help='Releasability statement written into the metadata, '
             'e.g. "NATO" or "USA, GBR, CAN" (v0.27.0)'
    )
    parser.add_argument(
        '--language',
        default='eng',
        help='ISO 639-2 language code (default: eng)'
    )
    parser.add_argument(
        '--category',
        help='ISO 19115 topic category'
    )
    parser.add_argument(
        '--ref-date',
        help='Reference date (YYYY-MM-DD format). Defaults to today.'
    )

    # Conversion options
    parser.add_argument(
        '--profile',
        choices=['default', 'military', 'civilian', 'high_security'],
        default='default',
        help='Conversion profile (default: default)'
    )

    # DGIWG validation gate (v0.27.0)
    parser.add_argument(
        '--validate',
        action='store_true',
        help='After conversion, run the external DGIWG GeoPackage Validator '
             '(all 37 requirements) and include the results in the reports'
    )
    parser.add_argument(
        '--validator-path',
        help='Folder containing the dgiwg_validator package '
             '(default: DGIWG_VALIDATOR_PATH env var or auto-detect)'
    )

    # Output options
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output (debug logging)'
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Minimal output'
    )

    # Parse arguments
    args = parser.parse_args()

    # Setup logging
    if not args.quiet:
        setup_logging(verbose=args.verbose)

    logger = logging.getLogger(__name__)

    # Validate arguments
    if not validate_arguments(args):
        sys.exit(1)

    # Create converter
    logger.info(f"Initializing GeoPackageConverter with profile: {args.profile}")
    converter = GeoPackageConverter(profile=args.profile)

    # Prepare conversion parameters
    conversion_params = {
        'source_geodatabase': args.source,
        'output_geopackage': args.output,
        'title': args.title,
        'abstract': args.abstract or f"Converted from {Path(args.source).name}",
        'poc': args.poc or "Unknown",
        'org': args.org,
        'nation': args.nation,
    }

    # Add optional parameters if provided
    if args.security:
        conversion_params['security'] = args.security
    if args.language:
        conversion_params['language'] = args.language
    if args.category:
        conversion_params['topic_category'] = args.category
    if args.ref_date:
        conversion_params['ref_date'] = args.ref_date
    if args.releasability:
        conversion_params['releasability'] = args.releasability
    if args.validate:
        conversion_params['run_dgiwg_validation'] = True
        if args.validator_path:
            conversion_params['dgiwg_validator_path'] = args.validator_path

    # Perform conversion
    try:
        logger.info(f"Converting: {args.source} → {args.output}")
        result = converter.convert(**conversion_params)

        if result['success']:
            print("\n" + "="*60)
            print("✓ CONVERSION SUCCESSFUL")
            print("="*60)
            print(f"Output:           {result['output_path']}")
            print(f"Layers:           {result['layer_count']}")
            print(f"Total Features:   {result['total_features']}")
            print(f"DGIWG Compliant:  {result['dgiwg_compliant']}")
            print(f"R-Tree Indexes:   {result['r_tree_indexes']}")

            dv = result.get('dgiwg_validation')
            if dv:
                if dv.get('available'):
                    verdict = 'CONFORMANT' if dv.get('conformant') else 'NON-CONFORMANT'
                    summary = ', '.join(f"{k}={v}" for k, v in sorted(dv.get('summary', {}).items()))
                    print(f"Validator Gate:   {verdict} ({summary})")
                else:
                    print(f"Validator Gate:   skipped - {dv.get('error')}")

            if result['warnings']:
                print("\nWarnings:")
                for warning in result['warnings']:
                    print(f"  ⚠ {warning}")

            if result['layers']:
                print("\nLayers Created:")
                for layer in result['layers']:
                    print(f"  • {layer['name']}: {layer['feature_count']} features ({layer['geometry_type']})")

            print("="*60 + "\n")
            sys.exit(0)
        else:
            print("\n" + "="*60)
            print("✗ CONVERSION FAILED")
            print("="*60)
            print(f"Error: {result['error']}")

            if result['warnings']:
                print("\nWarnings:")
                for warning in result['warnings']:
                    print(f"  ⚠ {warning}")

            print("="*60 + "\n")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"\n✗ Error: {e}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
