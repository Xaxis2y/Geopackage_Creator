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

#### **Option A: Conda/Mamba (Recommended - Easiest)**
```bash
# If you have conda installed
conda install -c conda-forge gdal

# OR with mamba (faster)
mamba install -c conda-forge gdal
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
pip install "GDAL>=3.6.0"
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
conda install -c conda-forge gdal lxml

# Done! Run the GUI:
python geopackage_creator_gui.py
```

### **Installation Option 2: Pip + Conda (Hybrid)**
```bash
# Install GDAL via conda (handles system dependencies)
conda install -c conda-forge gdal

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
pip install "lxml>=4.9.0" "GDAL>=3.6.0"

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
conda install -c conda-forge gdal
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
