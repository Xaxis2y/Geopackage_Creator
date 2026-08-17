# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
"""
Report Generator Module for GeoPackage Creator v0.30.19

Generates comprehensive reports in HTML, PDF, and JSON formats.
Reports document the conversion process, performance metrics, and validation results.

Formats:
  - HTML: Interactive web-based report with visualizations
  - PDF: Printable report with formatted output
  - JSON: Structured data for programmatic processing

Note (v0.30.18): the version string stamped into every generated report is now
read from core.config.TOOL_VERSION instead of being hardcoded here, so it can
no longer silently drift out of sync with the tool's actual version (it had -
this module kept printing "v0.30.9" in every JSON/HTML/PDF report for several
releases after TOOL_VERSION had moved on).
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

from .config import TOOL_VERSION

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate conversion reports in multiple formats."""

    def __init__(self):
        """Initialize report generator."""
        self.report_data = {}
        self.generation_time = datetime.now()

    def add_conversion_info(self, info: Dict[str, Any]):
        """Add conversion information to report."""
        self.report_data['conversion'] = info

    def add_input_info(self, info: Dict[str, Any]):
        """Add input file information."""
        self.report_data['input'] = info

    def add_output_info(self, info: Dict[str, Any]):
        """Add output file information."""
        self.report_data['output'] = info

    def add_crs_info(self, info: Dict[str, Any]):
        """Add CRS conversion information."""
        self.report_data['crs'] = info

    def add_performance_metrics(self, metrics: Dict[str, Any]):
        """Add performance metrics."""
        self.report_data['performance'] = metrics

    def add_validation_results(self, results: Dict[str, Any]):
        """Add validation results."""
        self.report_data['validation'] = results

    def add_dgiwg_validation(self, results: Dict[str, Any]):
        """Add DGIWG validator gate results (v0.27.0, per-requirement table)."""
        self.report_data['dgiwg_validation'] = results

    def add_metadata(self, metadata: Dict[str, Any]):
        """Add metadata information."""
        self.report_data['metadata'] = metadata

    def generate_html_report(self, output_path: str) -> bool:
        """
        Generate HTML report.

        Args:
            output_path (str): Path to save HTML report

        Returns:
            bool: True if successful
        """
        try:
            html_content = self._build_html()
            Path(output_path).write_text(html_content, encoding='utf-8')
            logger.info(f"HTML report generated: {output_path}")
            return True
        except Exception as e:
            logger.error(f"Error generating HTML report: {str(e)}")
            return False

    def generate_json_report(self, output_path: str) -> bool:
        """
        Generate JSON report.

        Args:
            output_path (str): Path to save JSON report

        Returns:
            bool: True if successful
        """
        try:
            report_data = {
                'generated_at': self.generation_time.isoformat(),
                'version': TOOL_VERSION,
                'data': self.report_data
            }
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False)
            logger.info(f"JSON report generated: {output_path}")
            return True
        except Exception as e:
            logger.error(f"Error generating JSON report: {str(e)}")
            return False

    def generate_pdf_report(self, output_path: str) -> bool:
        """
        Generate PDF report (via HTML).

        Note: Requires reportlab or wkhtmltopdf.
        Falls back to HTML if PDF generation fails.

        Args:
            output_path (str): Path to save PDF report

        Returns:
            bool: True if successful
        """
        try:
            # Try using reportlab
            from reportlab.lib.pagesizes import letter, A4
            from reportlab.lib import colors
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.units import inch

            doc = SimpleDocTemplate(output_path, pagesize=A4)
            story = []

            # Title
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor=colors.HexColor('#1F4788'),
                spaceAfter=30,
                alignment=1  # Center
            )

            title = Paragraph(
                f"GeoPackage Creator - Conversion Report v{TOOL_VERSION}",
                title_style
            )
            story.append(title)

            # Generation info
            gen_style = styles['Normal']
            gen_text = f"Generated: {self.generation_time.strftime('%Y-%m-%d %H:%M:%S')}"
            story.append(Paragraph(gen_text, gen_style))
            story.append(Spacer(1, 0.3 * inch))

            # Add sections
            story.extend(self._build_pdf_sections())

            # Build PDF
            doc.build(story)
            logger.info(f"PDF report generated: {output_path}")
            return True

        except ImportError:
            logger.warning("reportlab not installed, generating HTML instead")
            html_path = output_path.replace('.pdf', '.html')
            return self.generate_html_report(html_path)

        except Exception as e:
            logger.error(f"Error generating PDF report: {str(e)}")
            return False

    def _build_html(self) -> str:
        """Build HTML report content."""
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GeoPackage Creator - Conversion Report</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 1000px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #1F4788 0%, #2E5C8A 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }}
        .header h1 {{
            font-size: 28px;
            margin-bottom: 10px;
        }}
        .header p {{
            font-size: 14px;
            opacity: 0.9;
        }}
        .content {{
            padding: 40px;
        }}
        .section {{
            margin-bottom: 40px;
        }}
        .section-title {{
            font-size: 20px;
            color: #1F4788;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }}
        @media (max-width: 768px) {{
            .info-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        .info-item {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }}
        .info-label {{
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 5px;
        }}
        .info-value {{
            font-size: 16px;
            color: #333;
            font-weight: 500;
        }}
        .status {{
            display: inline-block;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .status.success {{
            background: #d4edda;
            color: #155724;
        }}
        .status.warning {{
            background: #fff3cd;
            color: #856404;
        }}
        .status.error {{
            background: #f8d7da;
            color: #721c24;
        }}
        .table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        .table th {{
            background: #f8f9fa;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            border-bottom: 2px solid #dee2e6;
            color: #495057;
        }}
        .table td {{
            padding: 12px;
            border-bottom: 1px solid #dee2e6;
        }}
        .table tr:hover {{
            background: #f8f9fa;
        }}
        .footer {{
            background: #f8f9fa;
            padding: 20px 40px;
            text-align: center;
            border-top: 1px solid #dee2e6;
            font-size: 12px;
            color: #666;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
            margin: 20px 0;
        }}
        @media (max-width: 768px) {{
            .stats {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}
        .stat-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }}
        .stat-number {{
            font-size: 28px;
            font-weight: bold;
            margin-bottom: 5px;
        }}
        .stat-label {{
            font-size: 12px;
            opacity: 0.9;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 GeoPackage Creator</h1>
            <h2>Conversion Report v{TOOL_VERSION}</h2>
            <p>Generated: {self.generation_time.strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>

        <div class="content">
            {self._build_html_conversion_section()}
            {self._build_html_files_section()}
            {self._build_html_crs_section()}
            {self._build_html_performance_section()}
            {self._build_html_validation_section()}
            {self._build_html_dgiwg_validation_section()}
        </div>

        <div class="footer">
            <p>GeoPackage Creator v{TOOL_VERSION} | OGC & DGIWG Compliant | {self.generation_time.strftime('%Y')}</p>
        </div>
    </div>
</body>
</html>
"""
        return html

    def _build_html_conversion_section(self) -> str:
        """Build conversion info section."""
        conv = self.report_data.get('conversion', {})
        return f"""
        <div class="section">
            <div class="section-title">📋 Conversion Information</div>
            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">Mode</div>
                    <div class="info-value">{conv.get('mode', 'N/A')}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Status</div>
                    <div class="info-value">
                        <span class="status {'success' if conv.get('success') else 'error'}">
                            {'✓ Successful' if conv.get('success') else '✗ Failed'}
                        </span>
                    </div>
                </div>
                <div class="info-item">
                    <div class="info-label">Start Time</div>
                    <div class="info-value">{conv.get('start_time', 'N/A')}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Duration</div>
                    <div class="info-value">{conv.get('duration', 'N/A')} sec</div>
                </div>
            </div>
        </div>
"""

    def _build_html_files_section(self) -> str:
        """Build files section."""
        inp = self.report_data.get('input', {})
        outp = self.report_data.get('output', {})
        return f"""
        <div class="section">
            <div class="section-title">📁 Input & Output Files</div>
            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">Input File</div>
                    <div class="info-value">{inp.get('filename', 'N/A')}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Output File</div>
                    <div class="info-value">{outp.get('filename', 'N/A')}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Input Layers</div>
                    <div class="info-value">{inp.get('layers', 'N/A')}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Output Layers</div>
                    <div class="info-value">{outp.get('layers', 'N/A')}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Input Features</div>
                    <div class="info-value">{inp.get('features', 'N/A')}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Output Features</div>
                    <div class="info-value">{outp.get('features', 'N/A')}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Input Size</div>
                    <div class="info-value">{inp.get('size', 'N/A')}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Output Size</div>
                    <div class="info-value">{outp.get('size', 'N/A')}</div>
                </div>
            </div>
        </div>
"""

    def _build_html_crs_section(self) -> str:
        """Build CRS section."""
        crs = self.report_data.get('crs', {})
        return f"""
        <div class="section">
            <div class="section-title">🌍 CRS (Coordinate Reference System)</div>
            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">Source CRS</div>
                    <div class="info-value">{crs.get('source_epsg', 'N/A')}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Target CRS</div>
                    <div class="info-value">{crs.get('target_epsg', 'N/A')}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">DGIWG Approved</div>
                    <div class="info-value">
                        <span class="status {'success' if crs.get('dgiwg_approved') else 'warning'}">
                            {'✓ Yes' if crs.get('dgiwg_approved') else '⚠ No'}
                        </span>
                    </div>
                </div>
                <div class="info-item">
                    <div class="info-label">Converted</div>
                    <div class="info-value">
                        <span class="status {'success' if crs.get('converted') else 'warning'}">
                            {'✓ Yes' if crs.get('converted') else '○ No'}
                        </span>
                    </div>
                </div>
            </div>
        </div>
"""

    def _build_html_performance_section(self) -> str:
        """Build performance section."""
        perf = self.report_data.get('performance', {})
        return f"""
        <div class="section">
            <div class="section-title">⚡ Performance Metrics</div>
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-number">{perf.get('duration', 0):.2f}</div>
                    <div class="stat-label">Execution Time (sec)</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{perf.get('memory_used', 0):.0f}</div>
                    <div class="stat-label">Memory Used (MB)</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{perf.get('features_per_sec', 0):.0f}</div>
                    <div class="stat-label">Features/Second</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{perf.get('layers_processed', 0)}</div>
                    <div class="stat-label">Layers Processed</div>
                </div>
            </div>
        </div>
"""

    @staticmethod
    def _normalize_validation(val: Dict[str, Any]) -> Dict[str, bool]:
        """Map OutputValidator.validate_gpkg_structure() output to report flags.

        v0.30.6 fix: the report previously read keys ('ogc_compliant',
        'dgiwg_compliant', 'geometry_valid', 'metadata_valid') that
        validate_gpkg_structure() never emits, so the Validation Results
        section always showed failure even for a fully valid, compliant
        GeoPackage. This normaliser prefers those legacy keys when present
        (backward compatibility) and otherwise derives each flag from the
        actual structure-check keys ('compliant', 'gdal_readable',
        'dgiwg_spatial_indexes', 'user_version_ok', 'metadata_tables').
        """
        return {
            "ogc_compliant": bool(
                val.get("ogc_compliant", val.get("compliant", False))
            ),
            "dgiwg_compliant": bool(
                val.get(
                    "dgiwg_compliant",
                    val.get("dgiwg_spatial_indexes", False)
                    and val.get("user_version_ok", True),
                )
            ),
            "geometry_valid": bool(
                val.get("geometry_valid", val.get("gdal_readable", False))
            ),
            "metadata_valid": bool(
                val.get("metadata_valid", val.get("metadata_tables", False))
            ),
        }

    def _build_html_validation_section(self) -> str:
        """Build validation section."""
        raw = self.report_data.get('validation', {})
        val = self._normalize_validation(raw)
        return f"""
        <div class="section">
            <div class="section-title">✅ Validation Results</div>
            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">OGC Compliant</div>
                    <div class="info-value">
                        <span class="status {'success' if val.get('ogc_compliant') else 'error'}">
                            {'✓ Yes' if val.get('ogc_compliant') else '✗ No'}
                        </span>
                    </div>
                </div>
                <div class="info-item">
                    <div class="info-label">DGIWG Compliant</div>
                    <div class="info-value">
                        <span class="status {'success' if val.get('dgiwg_compliant') else 'error'}">
                            {'✓ Yes' if val.get('dgiwg_compliant') else '✗ No'}
                        </span>
                    </div>
                </div>
                <div class="info-item">
                    <div class="info-label">Geometry Valid</div>
                    <div class="info-value">
                        <span class="status {'success' if val.get('geometry_valid') else 'warning'}">
                            {'✓ Yes' if val.get('geometry_valid') else '⚠ Issues'}
                        </span>
                    </div>
                </div>
                <div class="info-item">
                    <div class="info-label">Metadata Valid</div>
                    <div class="info-value">
                        <span class="status {'success' if val.get('metadata_valid') else 'warning'}">
                            {'✓ Yes' if val.get('metadata_valid') else '⚠ Issues'}
                        </span>
                    </div>
                </div>
            </div>
        </div>
"""


    def _build_html_dgiwg_validation_section(self) -> str:
        """Per-requirement DGIWG validator table (v0.27.0)."""
        dv = self.report_data.get('dgiwg_validation')
        if not dv:
            return ""
        if not dv.get('available'):
            return f"""
        <div class="section">
            <div class="section-title">DGIWG Validator Gate</div>
            <p style="color:#888;">Not run: {dv.get('error', 'validator unavailable')}</p>
        </div>
"""
        badge = ('<span class="status success">CONFORMANT</span>'
                 if dv.get('conformant')
                 else '<span class="status error">NON-CONFORMANT</span>')
        summary = ", ".join(f"{k}: {v}" for k, v in sorted(dv.get('summary', {}).items()))
        rows = []
        color = {"PASS": "#27ae60", "PASS*": "#2e86c1",
                 "FAIL": "#c0392b", "SKIPPED": "#888"}
        for num in sorted(dv.get('requirements', {})):
            r = dv['requirements'][num]
            st = r.get('status', '?')
            rows.append(
                f"<tr><td>{num}</td><td>{r.get('title','')}</td>"
                f"<td>{r.get('type','')}</td>"
                f"<td style='color:{color.get(st, '#333')};font-weight:bold'>{st}</td></tr>"
            )
        return f"""
        <div class="section">
            <div class="section-title">DGIWG Validator Gate (37 Requirements)</div>
            <p>{badge} &nbsp; {summary}</p>
            <table style="width:100%;border-collapse:collapse;margin-top:10px;font-size:13px;">
                <tr style="background:#1F4788;color:white;">
                    <th style="padding:6px;text-align:left;">Req</th>
                    <th style="padding:6px;text-align:left;">Requirement</th>
                    <th style="padding:6px;text-align:left;">M/C</th>
                    <th style="padding:6px;text-align:left;">Status</th>
                </tr>
                {''.join(rows)}
            </table>
        </div>
"""

    def _build_pdf_sections(self) -> List:
        """Build PDF report sections using reportlab primitives.

        Returns a list of reportlab Flowable objects covering conversion info,
        file details, CRS, performance metrics, and validation results.
        """
        try:
            from reportlab.lib import colors
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import inch
            from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
        except ImportError:
            return []

        styles = getSampleStyleSheet()
        h2 = styles['Heading2']
        normal = styles['Normal']
        story = []

        def section(title, rows):
            story.append(Paragraph(title, h2))
            story.append(Spacer(1, 0.1 * inch))
            table_data = [[k, str(v)] for k, v in rows]
            if not table_data:
                story.append(Paragraph("No data available.", normal))
            else:
                t = Table(table_data, colWidths=[2.5 * inch, 4 * inch])
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#E8EDF5')),
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('ROWBACKGROUNDS', (0, 0), (-1, -1),
                     [colors.white, colors.HexColor('#F8F9FA')]),
                    ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#DEE2E6')),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ]))
                story.append(t)
            story.append(Spacer(1, 0.25 * inch))

        conv = self.report_data.get('conversion', {})
        section("Conversion Information", [
            ("Mode", conv.get('mode', 'N/A')),
            ("Status", "Successful" if conv.get('success') else "Failed"),
            ("Start Time", conv.get('start_time', 'N/A')),
            ("Duration (sec)", f"{conv.get('duration', 0):.2f}"),
        ])

        inp = self.report_data.get('input', {})
        outp = self.report_data.get('output', {})
        section("Input & Output Files", [
            ("Input File", inp.get('filename', 'N/A')),
            ("Input Layers", inp.get('layers', 'N/A')),
            ("Input Features", inp.get('features', 'N/A')),
            ("Output File", outp.get('filename', 'N/A')),
            ("Output Layers", outp.get('layers', 'N/A')),
            ("Output Features", outp.get('features', 'N/A')),
        ])

        crs = self.report_data.get('crs', {})
        section("CRS (Coordinate Reference System)", [
            ("Source CRS", f"EPSG:{crs.get('source_epsg', 'N/A')}"),
            ("Target CRS", f"EPSG:{crs.get('target_epsg', 'N/A')}"),
            ("DGIWG Approved", "Yes" if crs.get('dgiwg_approved') else "No"),
            ("Converted", "Yes" if crs.get('converted') else "No"),
        ])

        perf = self.report_data.get('performance', {})
        section("Performance Metrics", [
            ("Execution Time (sec)", f"{perf.get('duration', 0):.2f}"),
            ("Memory Used (MB)", f"{perf.get('memory_used', 0):.0f}"),
            ("Features / Second", f"{perf.get('features_per_sec', 0):.0f}"),
            ("Layers Processed", perf.get('layers_processed', 0)),
        ])

        val = self._normalize_validation(self.report_data.get('validation', {}))
        section("Validation Results", [
            ("OGC Compliant", "Yes" if val.get('ogc_compliant') else "No"),
            ("DGIWG Compliant", "Yes" if val.get('dgiwg_compliant') else "No"),
            ("Geometry Valid", "Yes" if val.get('geometry_valid') else "Issues"),
            ("Metadata Valid", "Yes" if val.get('metadata_valid') else "Issues"),
        ])

        return story
