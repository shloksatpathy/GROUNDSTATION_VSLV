# 📜 CHANGELOG  
CANSAT Ground Station – Telemetry & Mission Console  
Team ID: 2024ASI-CANSAT0032  

All notable changes to this project are documented in this file.

The format is inspired by semantic versioning principles.  
Versions represent architectural evolution stages.

---

## [v1.0.0] – Initial Telemetry Viewer
### Added
- Serial communication using `pyserial`
- Hardcoded CSV packet parsing
- Real-time plotting using PyQtGraph
- Single GNSS map (Folium)
- Basic CSV logging
- PyQt5-based UI

### Notes
- Monolithic architecture
- Static packet structure
- Minimal error handling

---

## [v1.1.0] – Dynamic Packet Format System
### Added
- `packet_format.json` configuration file
- Automatic JSON generation if missing
- Dynamic field loading from JSON
- Role-based field mapping system
- Header detection in incoming telemetry

### Changed
- Replaced hardcoded parsing logic with configurable schema

### Impact
- Improved flexibility
- Packet structure can change without code modification

---

## [v1.2.0] – Robust Parsing & Error Handling
### Added
- Regex-based numeric extraction (`_clean_numeric`)
- Safe float/int casting
- Handling of extra and missing packet fields
- Device timestamp prefix detection

### Fixed
- Float conversion crashes
- Parsing errors due to unit strings

### Impact
- Improved reliability under noisy telemetry conditions

---

## [v1.3.0] – Sliding Window & Time Normalization
### Added
- `WINDOW_SEC` time window parameter
- Millisecond vs second detection logic
- Time normalization to mission start
- Rolling buffer filtering

### Improved
- Plot readability
- UI responsiveness

---

## [v1.4.0] – Geospatial Enhancements
### Added
- Reference coordinates (REF_LAT, REF_LON)
- Dual-map interface
- Great-circle interpolation (`great_circle_points`)
- Haversine distance calculation (`haversine_m`)
- Distance overlay label

### Impact
- Transition from simple GNSS viewer to mission-relative mapping system

---

## [v1.5.0] – Derived Telemetry: Vertical Speed
### Added
- Vertical velocity calculation (Δalt / Δt)
- Moving average smoothing window (`VSPEED_SMOOTH_WINDOW`)
- Dedicated vertical speed plot
- Auto-range scaling

### Impact
- Introduced telemetry processing layer
- Improved mission situational awareness

---

## [v1.6.0] – Flight State & Power Monitoring
### Added
- `FLIGHT_STATE_MAP`
- Numeric-to-string state mapping
- Voltage extraction logic
- Battery percentage estimation (`VOLT_DIVISOR`)
- Information panel (time, state, power, packet count)

### Impact
- System evolved into mission console
- Improved operator awareness

---

## [v1.7.0] – Performance Instrumentation
### Added
- Latency measurement system (`time_block`, `time_block_end`)
- Rolling performance log
- Diagnostics counters:
  - Raw lines
  - Parsed packets
  - Dropped packets
  - TX packet tracking

### Impact
- Enabled runtime performance monitoring
- Improved debugging capability

---

## [v1.8.0] – Adaptive CSV Logging
### Added
- Persistent CSV file handle
- Periodic flush strategy
- Dynamic column expansion
- CSV rewrite when schema changes

### Improved
- Data integrity
- Logging reliability during schema evolution

---

## [v1.9.0] – UI & Plot Refinement
### Added
- Separated plots for:
  - Altitude
  - Pressure
  - Temperature
  - Roll
  - Pitch
  - Yaw
  - Vertical Speed
- Auto-range enabled plots
- Improved grid layout
- Dark theme styling
- Incremental table update system

### Impact
- Cleaner UI
- Improved real-time visualization clarity

---

## [v2.0.0] – Final Integrated CANSAT Console
### Integrated
- Dynamic schema parsing
- Sliding time window
- Derived telemetry
- Dual geodesic maps
- Flight state mapping
- Power monitoring
- Performance instrumentation
- Adaptive CSV system

### System Characteristics
- Robust under noisy telemetry
- Mission-aware
- Configurable
- Real-time responsive
- Competition-ready




## [v2.1.0] – Modular Architecture, Kalman Filtering & 3D Attitude

The monolithic console from v2.0.0 was broken apart into discrete modules, the
altitude/vertical-speed estimation moved onto a Kalman filter, a 3D attitude
view was added, and the whole thing is now shipped as a standalone executable.

### Added — Architecture
- `application/core/` split into single-responsibility modules:
  - `serial_manager.py` – port discovery, connection lifecycle, threaded reads
  - `packet_parser.py` – schema-driven parsing from `config/packet_format.json`
  - `telemetry_processor.py` – derived telemetry and filtering pipeline
  - `data_buffer.py` – in-memory rolling buffers for plotting
  - `data_recorder.py` – adaptive CSV logging into `data/`
  - `config.py` – configuration loading with defaults
- `application/ui/` split into `dashboard_tab.py`, `map_tab.py`,
  `packet_editor_tab.py` and `plots.py`
- In-app Packet Format Editor for changing the telemetry schema without
  restarting or hand-editing JSON
- Legacy monolithic scripts archived under `legacy/` for reference

### Added — Telemetry
- Kalman filter driving the altitude and vertical-speed estimates

### Added — 3D Attitude View
- 3D orientation panel below the dashboard info panel, driven by the live
  roll/pitch/yaw telemetry (`application/ui/attitude_3d.py`)
- Fixed reference triad (X=North, Y=West, Z=Up) plus a body triad attached to
  the vehicle, orbit/zoom with the mouse, "Reset View" to recentre
- Dependency-free STL (binary + ASCII) and OBJ loader
  (`application/ui/mesh_loader.py`) — drop the CAD model at `models/vehicle.stl`
- `attitude_*` keys in `config/config.json` for model path, scale, CAD-axis
  alignment and per-axis sign inversion
- Placeholder vehicle model shown until a CAD file is supplied

### Added — Packaging
- PyInstaller single-file build (`build.spec`, `build.sh`, `build.bat`)
  producing `VSSSIC_Ground_Station[.exe]` with the VSVL icon embedded
- On first launch the executable seeds an editable `config/` and a `data/`
  directory beside itself, so settings and flight logs survive restarts
- `BUILD_INSTRUCTIONS.md` and `STRUCTURE.md` documenting the build and layout

### Changed
- Configuration and packet schema moved to a top-level `config/` directory
- Entry point is now `run.py` at the project root

### Impact
- Modules can be tested and changed in isolation instead of editing one file
- No large spikes in the altitude plot; vertical speed reads as a smooth curve
  with noise suppressed
- Vehicle orientation is readable at a glance instead of being inferred from
  three separate angle plots
- The 3D view falls back to a numeric-only readout if OpenGL is unavailable, so
  a driver problem on the field laptop cannot take down the dashboard
- Operators no longer need Python or dependencies installed to run the station

---

# 🚀 Upcoming (Planned)

## [v2.2.0] – Advanced Telemetry
- Anomaly detection
- Telemetry replay mode

---

# 📌 Summary

The project evolved from a basic telemetry display tool into a configurable, real-time, mission-aware ground station system with:

- Derived telemetry analytics
- Geospatial intelligence
- Performance monitoring
- Adaptive data logging

This changelog documents the architectural and functional progression across development stages.