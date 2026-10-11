# Project Structure

This document describes the organization of the VSSSIC Ground Station V3 application.

## Directory Layout

```
GROUNDSTATION_VSLV/
├── application/              # Main modular application
│   ├── main.py              # Window chrome + host station (run from project root via run.py)
│   ├── launcher.py          # Startup: host-or-monitor choice, then launch
│   ├── monitor_main.py      # Read-only monitor window (monitor.py starts here directly)
│   ├── core/                # Core functionality modules
│   │   ├── config.py        # Configuration loader
│   │   ├── data_buffer.py   # Telemetry data buffering
│   │   ├── data_recorder.py # CSV logging system
│   │   ├── packet_parser.py # Telemetry packet parsing
│   │   ├── relay.py         # UDP relay: host server, monitor client, LAN discovery
│   │   ├── serial_manager.py # Serial communication
│   │   └── telemetry_processor.py # Data processing pipeline
│   └── ui/                  # PyQt5 UI components
│       ├── attitude_3d.py   # 3D orientation view (roll/pitch/yaw)
│       ├── dashboard_tab.py # Main telemetry dashboard
│       ├── map_tab.py       # Map & tracking UI
│       ├── mesh_loader.py   # STL/OBJ model loading for the 3D view
│       ├── mode_dialog.py   # Startup host-or-monitor chooser
│       ├── monitor_join_dialog.py # Monitor startup: pick station, enter code
│       ├── packet_editor_tab.py # Packet format editor
│       ├── relay_tab.py     # Monitor Settings: access + data-display controls
│       └── plots.py         # Plotting utilities
│
├── config/                  # Configuration files
│   ├── config.json          # Application configuration
│   └── packet_format.json   # Telemetry packet schema definition
│
├── data/                    # Flight data and logs
│   └── Flight_*.csv         # CSV telemetry logs
│
├── images/                  # UI assets and images
│   ├── vsssic-logo-1.ico   # Application icon
│   └── *.png, *.jpeg       # Screenshots and graphics
│
├── models/                  # Vehicle CAD models for the 3D attitude view
│   ├── vehicle.stl          # Your model (STL binary/ASCII, or .obj)
│   └── README.md            # Axis convention and export instructions
│
├── legacy/                  # Archived/deprecated scripts
│   ├── GS_cansat.py        # Original monolithic ground station
│   ├── GS_noplots.py       # Variant without plotting
│   ├── GS_vslv.py          # Variant for VSLV team
│   └── test.py             # Legacy test scripts
│
├── run.py                   # Project entry point (launches main app)
├── requirements.txt         # Python dependencies
├── readme.md               # Project overview
├── changelog.md            # Version history
└── STRUCTURE.md            # This file
```

## Quick Start

To run the application:
```bash
python run.py
```

## Key Components

### Core Modules (`application/core/`)
- **config.py**: Loads configuration from `config/config.json` with sensible defaults
- **packet_parser.py**: Parses telemetry packets using schema from `config/packet_format.json`
- **data_recorder.py**: Logs incoming telemetry to CSV in `data/`
- **serial_manager.py**: Manages serial communication with hardware
- **telemetry_processor.py**: Processes and buffers incoming data
- **data_buffer.py**: Maintains in-memory buffers for plotting and analysis

### UI Components (`application/ui/`)
- **dashboard_tab.py**: Real-time telemetry display, live plots, and statistics
- **map_tab.py**: Leaflet/folium map with GPS tracking
- **packet_editor_tab.py**: Edit packet format schema on-the-fly
- **plots.py**: PyQtGraph plotting utilities

## Configuration

Edit `config/config.json` to customize:
- Team ID and baud rate
- Reference GPS coordinates
- Flight state definitions
- Paths to data files and packet schemas

The packet telemetry format is defined in `config/packet_format.json`.

## Legacy Scripts

Old monolithic ground station scripts are archived in `legacy/` for reference only.
The modern application is located in the `application/` directory.

## File Paths

All relative paths in the application are resolved from the project root:
- Configuration files: `config/`
- Flight data logs: `data/`
- UI assets: `images/`

This ensures the application works correctly when run from `python run.py` in the project root.
