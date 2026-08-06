# GeoPackage Creator - Installation Guide

## Quick Start (One-Click Installation)

### Option 1: PowerShell Script (Recommended)
```powershell
# Right-click PowerShell → "Run as Administrator"
# Then run:
.\install_dependencies.ps1
```

### Option 2: Batch File
```cmd
# Right-click Command Prompt → "Run as Administrator"
# Then run:
install_dependencies.bat
```

---

## All Required Dependencies

### **Core Package**
- **Python 3.7+**

### **Python Packages**

| Package | Version | Purpose | Installation |
|---------|---------|---------|--------------|
| `lxml` | ≥4.9.0 | XML validation (ISO 19115) | Simple pip install |
| `GDAL` (osgeo) | ≥3.6.0 | Geographic data processing | **See options below** |

### **System Requirements**
- Windows, Linux, or macOS
- Python 3.7 or higher
- ~500 MB disk space for GDAL

---

## Manual Installation Commands

### Step 1: Install lxml (Simple)
```bash
pip install --upgrade pip
pip install "lxml>=4.9.0"
```

### Step 2: Install GDAL (Choose ONE option)

> ### ⚠ Pin GDAL to 3.13.2 — do not install "latest"
>
> **Required:** `gdal=3.13.2` — the build this release was tested against.
>
> No GDAL version is currently known to be broken. The pin exists so
> releases are reproducible and so a passing test run means something — not
> because the previous pin (3.13.1) was found to be bad.
>
> Every command below now pins the version explicitly. Omitting it is how this
> project drifted from GDAL 3.13.1 to 3.13.2 between the v0.30.6 build and its
> release test — which made a bug in our own code (a GeoPackage left open while
> the same file was reopened through `sqlite3`, fixed in v0.30.7) look like a
> GDAL regression. Verify with:
>
> ```bash
> python -c "from osgeo import gdal; print(gdal.__version__)"   # -> 3.13.2
> ```
>
> **v0.30.13 — install lxml and GDAL together, from the same command.** A
> *separate* access violation (2026-08-04/05) was bisected to an ABI mismatch
> between the installed lxml build and the libxml2 conda resolves at runtime
> — see `core/metadata_handler.py` ("LIBXML2 ABI FAIL-FAST GUARD") and
> `CHANGELOG_v0.30.13.md`. It reproduced under GDAL 3.13.1 and does not
> depend on the GDAL patch version — installing lxml separately via pip
> *after* GDAL already exists in a conda environment is the likeliest way to
> hit it, because pip's lxml wheel bundles its own libxml2 rather than using
> the one GDAL resolved. Verify both agree:
>
> ```bash
> python -c "from lxml import etree; print(etree.LIBXML_COMPILED_VERSION, etree.LIBXML_VERSION)"
> ```
>
> The two tuples printed must be identical. If they are not, the tool will
> now refuse to run rather than crash silently (see
> `core.config.ALLOW_LIBXML_ABI_MISMATCH`).

#### **Option A: Conda/Mamba (Recommended - Easiest)**
```bash
# If you have conda installed
conda install -c conda-forge gdal=3.13.2

# OR with mamba (faster)
mamba install -c conda-forge gdal=3.13.2
```

#### **Option B: OSGeo4W (Windows Native - Recommended)**
1. Download from: https://trac.osgeo.org/osgeo4w/
2. Run installer
3. Select "GDAL" in package list
4. Install to default location: `C:\OSGeo4W`
5. Python automatically finds it

#### **Option C: System Package Manager**

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install gdal-bin python3-gdal libgdal-dev
pip install GDAL==$(gdal-config --version)
```

**macOS (Homebrew):**
```bash
brew install gdal
pip install "GDAL==3.13.2"
```

#### **Option D: Pre-built Wheels (Windows)**
1. Visit: https://www.lfd.uci.edu/~gohlke/pythonlibs/
2. Find GDAL wheel matching your Python version (e.g., `GDAL‑3.7.0‑cp311‑cp311‑win_amd64.whl`)
3. Download and install:
   ```bash
   pip install GDAL‑3.7.0‑cp311‑cp311‑win_amd64.whl
   ```

---

## Full Installation (All Options)

### **Installation Option 1: Conda Environment (Recommended)**
```bash
# Create fresh conda environment
conda create -n geopackage python=3.11
conda activate geopackage

# Install all dependencies
conda install -c conda-forge gdal=3.13.2 lxml

# Done! Run the GUI:
python geopackage_creator_gui.py
```

### **Installation Option 2: Pip + Conda (Hybrid)**
```bash
# Install GDAL via conda (handles system dependencies)
conda install -c conda-forge gdal=3.13.2

# Install other packages via pip
pip install "lxml>=4.9.0"

# Run the GUI:
python geopackage_creator_gui.py
```

### **Installation Option 3: Pip Only (Advanced)**
```bash
# Upgrade pip first
python -m pip install --upgrade pip

# Install all packages
pip install "lxml>=4.9.0" "GDAL==3.13.2"

# Run the GUI:
python geopackage_creator_gui.py
```

### **Installation Option 4: Docker (No Local Install)**
```dockerfile
FROM osgeo/gdal:latest
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "geopackage_creator_gui.py"]
```

---

## Verify Installation

### Check if GDAL is installed:
```bash
python -c "from osgeo import ogr; print('GDAL OK')"
```

### Check if lxml is installed:
```bash
python -c "from lxml import etree; print('lxml OK')"
```

### Check Python version:
```bash
python --version
```

### Expected output:
```
GDAL OK
lxml OK
Python 3.x.x
```

---

## Troubleshooting

### Error: `ModuleNotFoundError: No module named 'osgeo'`
**Solution:** GDAL not installed. Use one of the installation options above.

### Error: `ImportError: DLL load failed while importing _gdal`
**Possible solutions:**
1. Use conda (handles dependencies better)
2. Use OSGeo4W
3. Check if Visual C++ Redistributables are installed: https://support.microsoft.com/en-us/help/2977003

### Error: `pip install GDAL` fails
**Reason:** GDAL requires system libraries not available via pip on all systems.
**Solution:** Use conda or OSGeo4W instead.

### GDAL installs but import still fails
**Solution:** Reinstall with conda:
```bash
conda remove gdal
conda install -c conda-forge gdal=3.13.2
```

### Python version mismatch
**Solution:** Ensure Python version matches installed wheels:
```bash
python --version  # Check your version
# Then download matching wheel from pythonlibs
```

---

## Run the Application

Once all dependencies are installed:

```bash
python geopackage_creator_gui.py
```

Or on Linux/macOS:
```bash
python3 geopackage_creator_gui.py
```

---

## Platform-Specific Notes

### **Windows**
- **Recommended:** Use OSGeo4W or conda
- Batch script: `install_dependencies.bat`
- PowerShell script: `install_dependencies.ps1`

### **macOS**
- **Recommended:** Use Homebrew or conda
- Command: `brew install gdal`

### **Linux**
- **Recommended:** Use system package manager
- Ubuntu: `sudo apt-get install gdal-bin python3-gdal`

---

## Additional Resources

- GDAL Documentation: https://gdal.org/
- OSGeo4W: https://trac.osgeo.org/osgeo4w/
- Conda Forge: https://conda-forge.org/
- Python wheels: https://www.lfd.uci.edu/~gohlke/pythonlibs/

---

## Need Help?

If installation still fails:
1. Check your Python version: `python --version`
2. Try conda (most reliable for GDAL)
3. Verify internet connection for downloads
4. Check disk space availability
5. Ensure you have admin rights for system-level installs
