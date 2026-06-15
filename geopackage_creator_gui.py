#!/usr/bin/env python3
"""
GeoPackage Creator v0.29.0 - Enhanced GUI

Features:
- CRS Automatic Conversion (3 modes)
- Automatic Report Generation (HTML/JSON/PDF)
- Performance Metrics
- Real-time Progress Logging
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
import threading
import logging
import os
import sys
import subprocess
import tempfile
from datetime import datetime
import webbrowser
import json

from core.converter import GeoPackageConverter


class _GuiLogHandler(logging.Handler):
    """Routes log records from the core modules into the GUI log window.

    Uses the GUI's thread-safe log() so progress (per-layer, per-feature,
    elapsed time) appears live even though conversion runs in a worker thread.
    """

    def __init__(self, log_func):
        super().__init__(level=logging.INFO)
        self.log_func = log_func

    def emit(self, record):
        try:
            self.log_func(record.getMessage())
        except Exception:
            pass


class GeoPackageCreatorGUI:
    """Enhanced GUI application for GeoPackage Creator v0.29.0."""

    def __init__(self, root):
        """Initialize the GUI."""
        self.root = root
        self.root.title("GeoPackage Creator v0.29.0")
        self.root.geometry("1000x900")
        self.root.resizable(True, True)

        # Configure style
        style = ttk.Style()
        style.theme_use('clam')

        # Setup logging
        self.setup_logging()

        # Create UI
        self.create_widgets()

        # State variables
        self.conversion_thread = None
        self.is_converting = False
        self.last_conversion_result = None

    def setup_logging(self):
        """Setup logging handler for GUI."""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers = []
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(console_handler)

    def create_widgets(self):
        """Create GUI widgets with all sections."""
        # Main container with scrollbar
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(7, weight=1)

        # ===== FILE SELECTION SECTION =====
        self.create_file_selection_section(main_frame)

        # ===== METADATA SECTION =====
        self.create_metadata_section(main_frame)

        # ===== OPTIONAL METADATA SECTION =====
        self.create_optional_metadata_section(main_frame)

        # ===== CRS CONVERSION SECTION (NEW) =====
        self.create_crs_conversion_section(main_frame)

        # ===== REPORT GENERATION SECTION (NEW) =====
        self.create_report_generation_section(main_frame)

        # ===== PROGRESS / LOG SECTION =====
        self.create_progress_section(main_frame)

        # ===== BUTTON SECTION =====
        self.create_button_section(main_frame)

    def create_file_selection_section(self, parent):
        """Create file selection section."""
        file_frame = ttk.LabelFrame(parent, text="File Selection", padding="10")
        file_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        file_frame.columnconfigure(1, weight=1)

        # Source GDB
        ttk.Label(file_frame, text="Source .gdb:").grid(row=0, column=0, sticky=tk.W)
        self.source_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.source_var, state='readonly').grid(
            row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 5)
        )
        ttk.Button(file_frame, text="Browse...", command=self.browse_source).grid(row=0, column=2, padx=5)

        # Output GeoPackage
        ttk.Label(file_frame, text="Output .gpkg:").grid(row=1, column=0, sticky=tk.W, pady=(10, 0))
        self.output_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.output_var).grid(
            row=1, column=1, sticky=(tk.W, tk.E), padx=(5, 5), pady=(10, 0)
        )
        ttk.Button(file_frame, text="Browse...", command=self.browse_output).grid(row=1, column=2, padx=5, pady=(10, 0))

    def create_metadata_section(self, parent):
        """Create required metadata section."""
        metadata_frame = ttk.LabelFrame(parent, text="Metadata (Required)", padding="10")
        metadata_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=10)
        metadata_frame.columnconfigure(1, weight=1)

        # Title
        ttk.Label(metadata_frame, text="Title:").grid(row=0, column=0, sticky=tk.W)
        self.title_var = tk.StringVar()
        ttk.Entry(metadata_frame, textvariable=self.title_var).grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)

        # Organization
        ttk.Label(metadata_frame, text="Organization:").grid(row=1, column=0, sticky=tk.W, pady=(10, 0))
        self.org_var = tk.StringVar(value="MCE")
        ttk.Entry(metadata_frame, textvariable=self.org_var).grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=(10, 0))

        # Nation Code
        ttk.Label(metadata_frame, text="Nation Code (ISO 3166-1):").grid(row=2, column=0, sticky=tk.W, pady=(10, 0))
        self.nation_var = tk.StringVar(value="CAN")
        ttk.Entry(metadata_frame, textvariable=self.nation_var).grid(row=2, column=1, sticky=(tk.W, tk.E), padx=5, pady=(10, 0))

        # Point of Contact
        ttk.Label(metadata_frame, text="Point of Contact:").grid(row=3, column=0, sticky=tk.W, pady=(10, 0))
        self.poc_var = tk.StringVar()
        ttk.Entry(metadata_frame, textvariable=self.poc_var).grid(row=3, column=1, sticky=(tk.W, tk.E), padx=5, pady=(10, 0))

        # Abstract
        ttk.Label(metadata_frame, text="Abstract:").grid(row=4, column=0, sticky=(tk.W, tk.N), pady=(10, 0))
        abstract_entry = tk.Text(metadata_frame, height=3, width=40)
        abstract_entry.grid(row=4, column=1, sticky=(tk.W, tk.E), padx=5, pady=(10, 0))
        self.abstract_text = abstract_entry

    def create_optional_metadata_section(self, parent):
        """Create optional metadata section."""
        optional_frame = ttk.LabelFrame(parent, text="Optional Metadata", padding="10")
        optional_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=10)
        optional_frame.columnconfigure(1, weight=1)
        optional_frame.columnconfigure(3, weight=1)

        # Security Level
        ttk.Label(optional_frame, text="Security Level:").grid(row=0, column=0, sticky=tk.W)
        self.security_var = tk.StringVar(value="UNCLASSIFIED")
        ttk.Combobox(optional_frame, textvariable=self.security_var,
                    values=["UNCLASSIFIED", "CONFIDENTIAL", "SECRET", "TOP SECRET"],
                    state='readonly').grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)

        # Language Code
        ttk.Label(optional_frame, text="Language Code:").grid(row=0, column=2, sticky=tk.W, padx=(10, 0))
        self.language_var = tk.StringVar(value="eng")
        ttk.Entry(optional_frame, textvariable=self.language_var, width=10).grid(row=0, column=3, sticky=tk.W, padx=5)

        # Topic Category
        ttk.Label(optional_frame, text="Topic Category:").grid(row=1, column=0, sticky=tk.W, pady=(10, 0))
        self.topic_var = tk.StringVar(value="geoscientificInformation")
        ttk.Combobox(optional_frame, textvariable=self.topic_var,
                    values=["geoscientificInformation", "transportation", "boundaries",
                           "imageryBaseMapsEarthCover", "structure", "planningCadastre"],
                    state='readonly').grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=(10, 0))

        # Profile
        ttk.Label(optional_frame, text="Profile:").grid(row=1, column=2, sticky=tk.W, padx=(10, 0), pady=(10, 0))
        self.profile_var = tk.StringVar(value="default")
        ttk.Combobox(optional_frame, textvariable=self.profile_var,
                    values=["default", "military", "civilian", "high_security"],
                    state='readonly').grid(row=1, column=3, sticky=tk.W, padx=5, pady=(10, 0))

    def create_crs_conversion_section(self, parent):
        """Create CRS conversion options section (v0.24+)."""
        crs_frame = ttk.LabelFrame(parent, text="CRS Conversion (v0.24+)", padding="10")
        crs_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=10)
        crs_frame.columnconfigure(1, weight=1)

        # CRS Mode Selection
        ttk.Label(crs_frame, text="Conversion Mode:").grid(row=0, column=0, sticky=tk.W)
        self.crs_mode_var = tk.StringVar(value="none")

        mode_frame = ttk.Frame(crs_frame)
        mode_frame.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)

        ttk.Radiobutton(mode_frame, text="None (No conversion)", variable=self.crs_mode_var,
                       value="none").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(mode_frame, text="Mode A (Auto-convert)", variable=self.crs_mode_var,
                       value="a").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(mode_frame, text="Mode B (Multi-version)", variable=self.crs_mode_var,
                       value="b").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(mode_frame, text="Mode C (Custom)", variable=self.crs_mode_var,
                       value="c").pack(side=tk.LEFT, padx=5)

        # Target EPSG for Mode C
        ttk.Label(crs_frame, text="Target EPSG (Mode C):").grid(row=1, column=0, sticky=tk.W, pady=(10, 0))
        self.target_epsg_var = tk.StringVar(value="4326")
        epsg_combo = ttk.Combobox(crs_frame, textvariable=self.target_epsg_var,
                                 values=["4326", "3857", "32633", "32634", "32635"],
                                 width=20, state='normal')
        epsg_combo.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=(10, 0))

        # CRS Info Label
        ttk.Label(crs_frame, text="Mode A: Auto-convert non-DGIWG CRS to WGS84\n"
                                 "Mode B: Generate multiple versions (WGS84, WebMercator, UTM)\n"
                                 "Mode C: Convert to user-specified EPSG code",
                 foreground="gray", font=("", 8)).grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))

    def create_report_generation_section(self, parent):
        """Create report generation options section (v0.24+)."""
        report_frame = ttk.LabelFrame(parent, text="Report Generation (v0.24+)", padding="10")
        report_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=10)
        report_frame.columnconfigure(1, weight=1)

        # Report Options
        ttk.Label(report_frame, text="Generate Reports:").grid(row=0, column=0, sticky=tk.W)

        self.report_html_var = tk.BooleanVar(value=True)
        self.report_json_var = tk.BooleanVar(value=True)
        self.report_pdf_var = tk.BooleanVar(value=False)

        report_options = ttk.Frame(report_frame)
        report_options.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)

        ttk.Checkbutton(report_options, text="HTML (Visual)", variable=self.report_html_var).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(report_options, text="JSON (Data)", variable=self.report_json_var).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(report_options, text="PDF (Print)", variable=self.report_pdf_var).pack(side=tk.LEFT, padx=5)

        # Report Info
        ttk.Label(report_frame, text="Reports will be saved in the same directory as output .gpkg file",
                 foreground="gray", font=("", 8)).grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))

    def create_progress_section(self, parent):
        """Create progress/log section."""
        progress_frame = ttk.LabelFrame(parent, text="Progress / Log", padding="10")
        progress_frame.grid(row=7, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        progress_frame.columnconfigure(0, weight=1)
        progress_frame.rowconfigure(1, weight=1)

        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100, mode='indeterminate')
        self.progress_bar.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        # Log text area
        self.log_text = scrolledtext.ScrolledText(progress_frame, height=10, width=80, state='disabled', font=('Courier', 9))
        self.log_text.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

    def create_button_section(self, parent):
        """Create button section."""
        button_frame = ttk.Frame(parent)
        button_frame.grid(row=8, column=0, sticky=(tk.W, tk.E), pady=(10, 0))

        self.convert_button = ttk.Button(button_frame, text="Convert to GeoPackage", command=self.start_conversion)
        self.convert_button.pack(side=tk.LEFT, padx=5)

        self.console_button = ttk.Button(button_frame, text="Convert in Console Window", command=self.convert_in_console)
        self.console_button.pack(side=tk.LEFT, padx=5)

        ttk.Button(button_frame, text="Clear Log", command=self.clear_log).pack(side=tk.LEFT, padx=5)

        self.results_button = ttk.Button(button_frame, text="View Results", command=self.view_results, state='disabled')
        self.results_button.pack(side=tk.LEFT, padx=5)

        ttk.Button(button_frame, text="Exit", command=self.root.quit).pack(side=tk.RIGHT, padx=5)

    def browse_source(self):
        """Browse for source .gdb folder."""
        folder = filedialog.askdirectory(title="Select source .gdb folder", initialdir=str(Path.home() / "Documents"))
        if folder:
            if not folder.endswith('.gdb'):
                messagebox.showwarning("Warning", "Selected folder does not end with '.gdb'.\nPlease select a proper geodatabase folder.")
                return
            self.source_var.set(folder)
            self.log(f"Selected source: {folder}")

    def browse_output(self):
        """Browse for output .gpkg file location."""
        file = filedialog.asksaveasfilename(title="Save GeoPackage as", defaultextension=".gpkg",
                                           filetypes=[("GeoPackage", "*.gpkg"), ("All Files", "*.*")])
        if file:
            self.output_var.set(file)
            self.log(f"Output path set to: {file}")

    def log(self, message):
        """Add a message to the log area (thread-safe).

        Tkinter is not thread-safe: every widget call must run on the thread
        that owns the root window. The conversion runs in a worker thread, so
        we marshal the actual UI mutation onto the main loop via after().
        """
        self.root.after(0, self._append_log, message)

    def _append_log(self, message):
        """Append a line to the log. MUST run on the main thread."""
        self.log_text.config(state='normal')
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')

    def _ui(self, func, *args, **kwargs):
        """Run a UI callable on the main thread (safe from any thread)."""
        self.root.after(0, lambda: func(*args, **kwargs))

    def clear_log(self):
        """Clear log text area."""
        self.log_text.config(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state='disabled')

    def validate_inputs(self):
        """Validate all required inputs."""
        errors = []

        if not self.source_var.get():
            errors.append("Source .gdb folder is required")
        elif not Path(self.source_var.get()).exists():
            errors.append(f"Source folder not found: {self.source_var.get()}")

        if not self.output_var.get():
            errors.append("Output .gpkg path is required")
        elif not Path(self.output_var.get()).parent.exists():
            errors.append(f"Output directory does not exist: {Path(self.output_var.get()).parent}")

        if not self.title_var.get():
            errors.append("Title is required")

        if not self.org_var.get():
            errors.append("Organization is required")

        if not self.nation_var.get():
            errors.append("Nation code is required")

        if not self.poc_var.get():
            errors.append("Point of Contact is required")

        abstract = self.abstract_text.get(1.0, tk.END).strip()
        if not abstract:
            errors.append("Abstract is required")

        if self.crs_mode_var.get() == 'c' and not self.target_epsg_var.get():
            errors.append("Target EPSG code required for Mode C")

        if errors:
            messagebox.showerror("Validation Error", "\n".join(errors))
            return False

        return True

    def start_conversion(self):
        """Start conversion in a separate thread."""
        if not self.validate_inputs():
            return

        if self.is_converting:
            messagebox.showwarning("Warning", "Conversion already in progress")
            return

        self.is_converting = True
        self.convert_button.config(state='disabled')
        self.results_button.config(state='disabled')
        self.clear_log()
        self.progress_bar.start(10)
        self.log("Starting conversion...")
        self.log("=" * 60)

        # IMPORTANT: read every Tk widget/variable HERE, on the main thread.
        # Tcl is single-threaded; reading widgets from the worker thread can
        # deadlock the whole interpreter (frozen UI, no CPU). The worker gets
        # only plain Python values via this dict.
        crs_mode = None if self.crs_mode_var.get() == 'none' else self.crs_mode_var.get()
        crs_target_epsg = None
        if crs_mode == 'c':
            try:
                crs_target_epsg = int(self.target_epsg_var.get())
            except ValueError:
                crs_target_epsg = None

        params = {
            'profile': self.profile_var.get(),
            'source': self.source_var.get(),
            'output': self.output_var.get(),
            'title': self.title_var.get(),
            'abstract': self.abstract_text.get(1.0, tk.END).strip(),
            'poc': self.poc_var.get(),
            'org': self.org_var.get(),
            'nation': self.nation_var.get(),
            'security': self.security_var.get(),
            'language': self.language_var.get(),
            'topic_category': self.topic_var.get(),
            'crs_mode': crs_mode,
            'crs_target_epsg': crs_target_epsg,
            'report_html': self.report_html_var.get(),
            'report_json': self.report_json_var.get(),
            'report_pdf': self.report_pdf_var.get(),
        }

        self.conversion_thread = threading.Thread(
            target=self.do_conversion, args=(params,), daemon=True
        )
        self.conversion_thread.start()

    def convert_in_console(self):
        """Run the conversion in a separate console window with live progress.

        This launches the command-line tool (geopackage_creator.py) in a new
        console using the SAME Python that is running this GUI (so it already
        has GDAL/osgeo). The console streams real-time progress and stays open
        when finished, so you can clearly see the tool is working - not hung.

        Note: this path performs a standard metadata conversion. The CRS
        Conversion modes and Report options are GUI-only features; use the
        "Convert to GeoPackage" button if you need those.
        """
        if not self.validate_inputs():
            return

        def q(value):
            # Quote a value for a .bat command line; strip stray double quotes.
            return '"' + str(value).replace('"', '') + '"'

        script_dir = Path(__file__).resolve().parent
        cli_script = script_dir / "geopackage_creator.py"
        python_exe = sys.executable  # the conda Python running this GUI
        # Frozen (PyInstaller) build: sys.executable IS the app .exe, which
        # doubles as the CLI when given arguments, so there is no .py script
        # to invoke. In a normal source run we call "python geopackage_creator.py".
        frozen = getattr(sys, "frozen", False)
        launcher = [q(python_exe)] if frozen else [q(python_exe), q(str(cli_script))]

        abstract = self.abstract_text.get(1.0, tk.END).strip()

        cmd_parts = launcher + [
            "--source", q(self.source_var.get()),
            "--output", q(self.output_var.get()),
            "--title", q(self.title_var.get()),
            "--org", q(self.org_var.get()),
            "--nation", q(self.nation_var.get()),
            "--poc", q(self.poc_var.get() or "Unknown"),
            "--abstract", q(abstract or "Converted dataset"),
            "--profile", q(self.profile_var.get()),
            "--language", q(self.language_var.get() or "eng"),
            "--security", q(self.security_var.get() or "UNCLASSIFIED"),
            "--category", q(self.topic_var.get()),
            "--verbose",
        ]
        command_line = " ".join(cmd_parts)

        bat_lines = [
            "@echo off",
            "chcp 65001 >nul",
            "title GeoPackage Conversion",
            f'cd /d "{script_dir}"',
            "echo ============================================================",
            "echo  GeoPackage Conversion - live progress",
            "echo  (this window shows what the tool is doing in real time)",
            "echo ============================================================",
            "echo.",
            command_line,
            "echo.",
            "echo ============================================================",
            "echo  Conversion process finished. Review the messages above.",
            "echo ============================================================",
            "pause",
        ]

        try:
            fd, bat_path = tempfile.mkstemp(suffix="_gpkg_convert.bat")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\r\n".join(bat_lines) + "\r\n")

            # Open the .bat in its own console window.
            os.startfile(bat_path)  # noqa: F821 (Windows-only)
            self.log("Launched conversion in a separate console window.")
            self.log("Watch that window for live progress.")
        except AttributeError:
            # os.startfile is Windows-only; fall back for other platforms.
            try:
                subprocess.Popen(["bash", bat_path])
                self.log("Launched conversion in a separate process.")
            except Exception as e:
                messagebox.showerror("Error", f"Could not launch console: {e}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not launch console: {e}")

    def do_conversion(self, params):
        """Perform the actual conversion. Runs in a worker thread.

        Receives a dict of plain Python values (collected on the main thread).
        This method must NOT read or write Tk widgets directly — all UI updates
        go through self.log() / self._ui(), which marshal back to the main loop.
        """
        # Route core-module progress logs (per-layer / per-feature / elapsed)
        # into the GUI log window for the duration of the conversion.
        core_logger = logging.getLogger("core")
        gui_handler = _GuiLogHandler(self.log)
        prev_level = core_logger.level
        core_logger.setLevel(logging.INFO)
        core_logger.addHandler(gui_handler)
        try:
            self.log(f"Profile: {params['profile']}")
            self.log(f"Source: {params['source']}")
            self.log(f"Output: {params['output']}")
            self.log(f"CRS Conversion Mode: {(params['crs_mode'] or 'none').upper()}")
            self.log(f"Generate Reports: HTML={params['report_html']}, JSON={params['report_json']}, PDF={params['report_pdf']}")
            self.log("=" * 60)

            converter = GeoPackageConverter(profile=params['profile'])

            # Perform conversion
            self.log("Running conversion...")
            result = converter.convert(
                source_geodatabase=params['source'],
                output_geopackage=params['output'],
                title=params['title'],
                abstract=params['abstract'],
                poc=params['poc'],
                org=params['org'],
                nation=params['nation'],
                security=params['security'],
                language=params['language'],
                topic_category=params['topic_category'],
                ref_date=datetime.now().strftime("%Y-%m-%d"),
                crs_conversion_mode=params['crs_mode'],
                crs_target_epsg=params['crs_target_epsg'],
                generate_reports=params['report_html'] or params['report_json'] or params['report_pdf'],
            )

            # Display results
            self.log("=" * 60)
            if result['success']:
                self.log("✓ CONVERSION SUCCESSFUL!")
                self.log(f"Output: {result['output_path']}")
                self.log(f"Layers: {result['layer_count']}")
                self.log(f"Total Features: {result['total_features']}")
                self.log(f"Duration: {result['performance']['duration']:.2f} seconds")

                if result['output_files']:
                    self.log(f"\nGenerated Files:")
                    for file in result['output_files']:
                        self.log(f"  - {file}")

                if result['crs_conversion']['mode']:
                    self.log(f"\nCRS Conversion:")
                    self.log(f"  Mode: {result['crs_conversion']['mode'].upper()}")
                    self.log(f"  Source EPSG: {result['crs_conversion']['source_epsg']}")
                    self.log(f"  Target EPSG: {result['crs_conversion']['target_epsg']}")
                    self.log(f"  Status: {'✓ Success' if result['crs_conversion']['success'] else '✗ Failed'}")

                if result['reports']['html'] or result['reports']['json'] or result['reports']['pdf']:
                    self.log(f"\nGenerated Reports:")
                    if result['reports']['html']:
                        self.log(f"  HTML: {result['reports']['html']}")
                    if result['reports']['json']:
                        self.log(f"  JSON: {result['reports']['json']}")
                    if result['reports']['pdf']:
                        self.log(f"  PDF: {result['reports']['pdf']}")

                if result['layers']:
                    self.log("\nLayer Details:")
                    for layer in result['layers']:
                        self.log(f"  - {layer['name']}: {layer['feature_count']} features ({layer['geometry_type']})")

                if result['warnings']:
                    self.log("\nWarnings:")
                    for warning in result['warnings']:
                        self.log(f"  ⚠ {warning}")

                self.log(f"\nDGIWG Compliant: {result['dgiwg_compliant']}")
                self.log(f"R-Tree Indexes: {result['r_tree_indexes']}")

                self.last_conversion_result = result
                self._ui(self.results_button.config, state='normal')

                self._ui(messagebox.showinfo, "Success", f"GeoPackage created successfully!\n\nOutput: {result['output_path']}")
            else:
                self.log(f"✗ CONVERSION FAILED!")
                self.log(f"Error: {result['error']}")
                self._ui(messagebox.showerror, "Error", f"Conversion failed:\n{result['error']}")

        except Exception as e:
            self.log(f"✗ EXCEPTION: {str(e)}")
            self._ui(messagebox.showerror, "Error", f"An error occurred:\n{str(e)}")
        finally:
            core_logger.removeHandler(gui_handler)
            core_logger.setLevel(prev_level)
            self.is_converting = False
            self._ui(self.convert_button.config, state='normal')
            self._ui(self.progress_bar.stop)
            self.log("=" * 60)
            self.log("Conversion process completed")

    def view_results(self):
        """View conversion results and open reports."""
        if not self.last_conversion_result:
            messagebox.showinfo("Info", "No recent conversion results")
            return

        result = self.last_conversion_result

        results_window = tk.Toplevel(self.root)
        results_window.title("Conversion Results - v0.27.0")
        results_window.geometry("500x400")

        frame = ttk.Frame(results_window, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        results_text = scrolledtext.ScrolledText(frame, height=15, width=60, state='normal', font=('Courier', 9))
        results_text.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        results_text.insert(tk.END, "=== CONVERSION RESULTS ===\n\n")
        results_text.insert(tk.END, f"Status: {'Success' if result['success'] else 'Failed'}\n")
        results_text.insert(tk.END, f"Output: {result['output_path']}\n")
        results_text.insert(tk.END, f"Layers: {result['layer_count']}\n")
        results_text.insert(tk.END, f"Features: {result['total_features']}\n")
        results_text.insert(tk.END, f"Duration: {result['performance']['duration']:.2f}s\n\n")

        if result['crs_conversion']['mode']:
            results_text.insert(tk.END, "=== CRS CONVERSION ===\n")
            results_text.insert(tk.END, f"Mode: {result['crs_conversion']['mode'].upper()}\n")
            results_text.insert(tk.END, f"Source EPSG: {result['crs_conversion']['source_epsg']}\n")
            results_text.insert(tk.END, f"Target EPSG: {result['crs_conversion']['target_epsg']}\n\n")

        results_text.config(state='disabled')

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        if result['reports']['html']:
            ttk.Button(button_frame, text="Open HTML Report",
                      command=lambda: webbrowser.open(f"file:///{result['reports']['html']}")
                      ).pack(side=tk.LEFT, padx=5)

        if result['reports']['json']:
            ttk.Button(button_frame, text="Open JSON Report",
                      command=lambda: self.open_json_report(result['reports']['json'])
                      ).pack(side=tk.LEFT, padx=5)

        ttk.Button(button_frame, text="Close", command=results_window.destroy).pack(side=tk.RIGHT, padx=5)

    def open_json_report(self, filepath):
        """Open JSON report in text editor."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            json_window = tk.Toplevel(self.root)
            json_window.title("JSON Report")
            json_window.geometry("600x500")

            text_widget = scrolledtext.ScrolledText(json_window, font=('Courier', 9))
            text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            json_str = json.dumps(data, indent=2)
            text_widget.insert(tk.END, json_str)
            text_widget.config(state='disabled')

        except Exception as e:
            messagebox.showerror("Error", f"Failed to open JSON report: {str(e)}")


def main():
    """Main entry point."""
    root = tk.Tk()
    app = GeoPackageCreatorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
