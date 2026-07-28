# VSSSIC Ground Station V3 - Build & Packaging Guide

## Overview
The VSSSIC Ground Station V3 is a PyQt5-based modular telemetry ground station. This guide covers how to build and package the application into a standalone executable with the VSVL icon.

## Prerequisites
- Python 3.8 or higher
- Virtual environment with dependencies installed (see setup below)

## Quick Start

### 1. Setup Python Environment
```bash
# Create virtual environment (if not already created)
python3 -m venv .venv

# Activate virtual environment
# On Linux/Mac:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install PyInstaller (required for building standalone executable)
pip install pyinstaller
```

### 2. Build the Application

#### Linux/Mac
```bash
chmod +x build.sh
./build.sh
```

#### Windows
```bash
build.bat
```

#### Manual Build (Any OS)
```bash
pyinstaller build.spec
```

### 3. Run the Packaged Application

#### Linux/Mac
```bash
./dist/VSSSIC_Ground_Station/VSSSIC_Ground_Station
```

#### Windows
```bash
.\dist\VSSSIC_Ground_Station\VSSSIC_Ground_Station.exe
```

## Build Output
The build process creates:
- **dist/VSSSIC_Ground_Station/** - Complete application bundle with all dependencies
- **build/** - Build artifacts (intermediate files)
- **VSSSIC_Ground_Station.spec** - PyInstaller specification (auto-generated if modified)

## Application Features
- **Telemetry Dashboard** - Real-time telemetry data visualization
- **Map & Tracking** - GNSS tracking with folium maps
- **Packet Format Editor** - Configure and edit telemetry packet formats
- **Serial Communication** - Connection management for serial devices

## Icon Configuration
The application uses the VSVL icon located at `images/vsssic-logo-1.ico`:
- Application window icon
- Taskbar icon (when packaged)
- Desktop shortcut icon (when installed)

## Troubleshooting

### PyInstaller Not Found
```bash
pip install pyinstaller --upgrade
```

### Application Won't Start
- Ensure all dependencies are installed: `pip install -r requirements.txt`
- Check that Python version is 3.8 or higher: `python3 --version`
- Run the development version: `python3 run.py`

### Icon Not Showing
- Verify `images/vsssic-logo-1.ico` exists
- Check that the build spec includes the icon path correctly
- Rebuild the application after checking icon file

## Development Mode
To run the application in development mode without packaging:
```bash
# Activate virtual environment
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Run directly
python3 run.py
```

## Distribution
After building, distribute the `dist/VSSSIC_Ground_Station` folder to end users. They don't need Python or dependencies installed - the application is completely standalone.

## Additional Resources
- **PyInstaller Documentation**: https://pyinstaller.org/
- **PyQt5 Documentation**: https://www.riverbankcomputing.com/static/Docs/PyQt5/
- **Project Structure**: See application/ directory for module organization

## Build Specifications
See `build.spec` for detailed build configuration including:
- Hidden imports for PyQt5 modules
- Data file inclusion (icon, application modules)
- Executable optimization settings
- Icon embedding configuration
