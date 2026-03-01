# 🚀 CANSAT Ground Station  
Real-Time Telemetry Visualization & Processing System

---

## Overview

This project is a Python-based real-time ground station designed for a VSLV and VSAT project.  
It evolved from a basic serial telemetry viewer into a configurable, mission-aware telemetry console with:

- Dynamic packet parsing
- Real-time plotting
- GNSS geospatial visualization
- Derived telemetry computation
- Performance instrumentation
- Adaptive CSV logging

## Instruction to the contributors 

---
 **The master or the main branch must not be changed without the approval of the author** 
 
Read the whole readme file carefully 
dont rush into making changes...

Here how you start if you are a beginner (This part can be skipped): 

    1) Fork the repository 

    2) Clone the repository into your system

    3) Fetch the develop branch from the remote repository

    4) create the virtual environment and install the required library 

    5) Now you are ready to make contributions 

---

## Instructions for the users of the groundstation
---
     create a virtual environment

     Install the required libraries mentioned in the requirements.txt file 
     
     make sure any other is not using the serial port like the serial monitor in the aeduino IDE

     run the file and work on the GUI of the dashboard to run the Ground station

     make sure to use the latest python file <app(greatest_int)_Final_(cansat/Rocket.py)>
---

#  Development Timeline & Refinements

---

##  Version 1 – Basic Telemetry Viewer

### Features
- Serial communication using `pyserial`
- Hardcoded CSV packet parsing
- Real-time plotting using PyQtGraph
- Single GNSS map (Folium)
- Basic CSV logging
- Monolithic PyQt5 UI

### Limitations
- Fragile float parsing
- Static schema
- No derived telemetry
- No performance tracking
- No dynamic UI scaling

---

##  Version 2 – Dynamic Packet Format

### Major Upgrade
- Introduced `packet_format.json`
- Dynamic field loading
- Automatic JSON generation if missing
- Role-based mapping (time, altitude, pressure, etc.)
- Header detection from telemetry stream

### Impact
System transitioned to handle dynamic packet formatting
---

##  Version 3 – Robust Parsing & Error Handling

### Improvements
- Regex-based numeric extraction
- Safe float/int casting
- Handling of extra/missing fields
- Device timestamp detection
- Defensive exception handling

### Result
Improved reliability under noisy telemetry conditions.

---

##  Version 4 – Sliding Window Plotting

### Added
- `WINDOW_SEC` parameter
- Time normalization logic
- Milliseconds vs seconds detection
- Rolling buffer filtering

### Impact
- Improved plot clarity
- Reduced UI lag
- Better real-time responsiveness

---

##  Version 5 – Geospatial Enhancements

### Features Added
- Reference coordinates (REF_LAT, REF_LON)
- Dual-map layout
- Great-circle interpolation
- Haversine distance calculation
- Distance label overlay

### Evolution
Map functioning upgraded
---

##  Version 6 – Derived Telemetry (Vertical Speed)

### Implemented
- ΔAltitude / ΔTime calculation
- Moving average smoothing
- Dedicated vertical speed plot
- Auto-ranging support

### Result
System became capable of telemetry processing, not just display.

---

##  Version 7 – Mission Awareness & Status Panel

### Added
- Flight state mapping (`FLIGHT_STATE_MAP`)
- Voltage extraction
- Battery percentage calculation
- Information panel:
  - Time since power
  - Flight state
  - Power %
  - Packet count

### Impact
Shifted from telemetry viewer → mission console.

---

##  Version 8 – Performance Instrumentation

### Introduced
- Latency tracking system
- Timing blocks:
  - Serial read
  - Parsing
  - CSV writing
  - Plot update
- Rolling performance log
- Diagnostics counters

### Outcome
Enabled runtime introspection and optimization.

---

##  Version 9 – Adaptive CSV Logging

### Enhancements
- Persistent file handle
- Periodic flush strategy
- Dynamic column expansion
- CSV rewrite when schema changes

### Benefit
Robust data recording even when packet structure evolves.

---

##  Version 10 – UI & Layout Refinement (Final)

### Improvements
- Separated plots:
  - Altitude
  - Pressure
  - Temperature
  - Roll
  - Pitch
  - Yaw
  - Vertical Speed
- Dual map views
- Clean dark theme styling
- Auto-range enabled plots
- Organized grid layout
- Incremental table updates

### Final Result
A competition-ready, mission-aware CANSAT telemetry dashboard.

---

#  Architectural Evolution Summary

| Phase | Capability Level |
|--------|------------------|
| V1 | Basic serial + plotting |
| V2 | Dynamic schema parsing |
| V3 | Robust numeric handling |
| V4 | Sliding time window |
| V5 | Geodesic mapping & distance |
| V6 | Derived telemetry processing |
| V7 | Mission state & power monitoring |
| V8 | Performance instrumentation |
| V9 | Adaptive CSV logging |
| V10 | Refined UI & system stability |

---

#  Current System Capabilities

- Real-time serial telemetry ingestion
- Configurable packet format (JSON-driven)
- Sliding window time-series plotting
- Derived vertical velocity calculation
- GNSS reference distance computation
- Battery percentage monitoring
- Flight state decoding
- Performance latency tracking
- Dynamic CSV schema handling
- Dual-map geospatial visualization

---

#  Conclusion

This project evolved from a basic telemetry display tool into a configurable, real-time, mission-aware ground station system with derived telemetry analytics and geospatial intelligence.

It demonstrates progressive refinement in:

- Robustness
- Architecture
- Performance
- Mission functionality
- UI design
- Telemetry processing depth

---

**Author:** Shlok Satpathy  
**Team ID:** 2024ASI-CANSAT0032