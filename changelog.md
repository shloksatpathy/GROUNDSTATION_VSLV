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




## [v2.0.1] - Additon of kalman filter for the altitude and the vertical speed plots estimation
### added 
- Kalman filter for the estimation of the vertical speed and altitude 


### Impact
- No big spikes in the altitude plot 
- smooth curve for the vertical speed plot with minimised noise 



---

# 🚀 Upcoming (Planned)

## [v2.1.0] – Architecture Refactor
- Separate modules:
  - SerialManager
  - PacketParser
  - TelemetryProcessor
  - PlotManager
  - MapManager
  - DataRecorder
- Threaded serial reading

## [v2.2.0] – Advanced Telemetry
- Kalman filtering
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