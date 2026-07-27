# File Structure Reorganization Summary

## Changes Made

### 1. **Directory Structure Reorganization**

Created three new top-level directories to organize project files:

- **`config/`** - Application configuration files
  - Moved: `config.json`
  - Moved: `packet_format.json`

- **`data/`** - Flight telemetry data and logs
  - Moved: `Flight_2026ASI-CANSAT0064.csv`

- **`legacy/`** - Archived/deprecated scripts
  - Moved: `GS_cansat.py`
  - Moved: `GS_noplots.py`
  - Moved: `GS_vslv.py`
  - Moved: `test.py`
  - Added: `README.md` (explanation of archived scripts)

### 2. **New Entry Point**

Created `run.py` - A clean entry point to launch the application:
```bash
python run.py
```

### 3. **Updated Configuration Loading**

Modified path resolution in:
- `application/core/config.py`
  - Now resolves to `config/config.json` at project root
  - Default paths updated to use `config/` and `data/` directories

- `application/core/packet_parser.py`
  - Fixed relative path resolution to work from project root
  - Now correctly finds `config/packet_format.json`

- `application/ui/packet_editor_tab.py`
  - Updated path resolution for `config/packet_format.json`

- `application/main.py`
  - Updated icon path to work from project root

### 4. **Documentation**

Added:
- **`STRUCTURE.md`** - Complete project structure documentation
- **`legacy/README.md`** - Explanation of archived scripts

## Benefits

✅ **Better Organization**: Clear separation of concerns
- Source code: `application/`
- Configuration: `config/`
- Data: `data/`
- Archived code: `legacy/`
- UI assets: `images/`

✅ **Easier Maintenance**: Non-code files separated from source

✅ **Clear Entry Point**: `run.py` launches the application from any directory

✅ **Path Consistency**: All relative paths resolve from project root

✅ **Documentation**: Clear guide on project structure and legacy code

## How to Run

```bash
cd /home/shlok/Desktop/GROUNDSTATION_VSLV
python run.py
```

## Files NOT Changed

- `requirements.txt` - No changes needed
- `readme.md` - Can optionally reference STRUCTURE.md
- `changelog.md` - Remains as-is
- `application/` modules - Functionality unchanged, only path handling updated
- `.venv/` - Virtual environment remains untouched
