# 🚀 VSSSIC Ground Station

**Real-time telemetry, mapping, and flight-simulation console for CanSat / VSLV / VSAT missions.**

A modular PyQt5 desktop application that ingests a live serial telemetry stream,
parses it against a configurable packet schema, filters and enriches it, and
presents it as live plots, a 3D attitude view, 2D/3D maps, and an adaptive CSV
log — with an optional RocketPy-backed "ideal trajectory" to fly against.

<sub>Team ID `2024ASI-CANSAT0032` · Version `2.1.0` · Python ≥ 3.8</sub>

![Telemetry dashboard](images/WhatsApp%20Image%202026-03-04%20at%207.24.46%20AM.jpeg)

---

## Table of contents

- [Highlights](#highlights)
- [The four tabs](#the-four-tabs)
- [Quick start (from source)](#quick-start-from-source)
- [Telemetry input format](#telemetry-input-format)
- [Configuration](#configuration)
- [Data logging](#data-logging)
- [3D attitude model](#3d-attitude-model)
- [Trajectory simulation (RocketPy)](#trajectory-simulation-rocketpy)
- [Building a standalone executable](#building-a-standalone-executable)
- [Project layout](#project-layout)
- [Architecture notes](#architecture-notes)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Credits](#credits)

---

## Highlights

| Area | What it does |
|---|---|
| **Serial ingestion** | Background reader thread, auto port discovery, selectable baud, command TX back to the vehicle. |
| **Configurable parsing** | Packet schema in JSON — typed or flat fields, delimiter, header auto-detection, device-timestamp prefixes, tolerant of missing/extra columns. Editable live from the UI. |
| **Derived telemetry** | 2-state Kalman filter for altitude + vertical speed, moving-average smoothing, flight-state decoding, battery % from a voltage divider. |
| **Live plots** | Altitude, pressure, temperature, roll, pitch, yaw, vertical speed — sliding time window, auto-ranged, dark themed. |
| **3D attitude** | Vehicle CAD model + body/reference triads driven by live roll/pitch/yaw. Falls back to a numeric readout if OpenGL is unavailable. |
| **Mapping** | Manual or telemetry-driven position, geodesic (great-circle) line to a reference point, Haversine range readout, configurable dark tile provider. |
| **3D trajectory** | Live GNSS + altimeter trace and the RocketPy "ideal" trajectory in one local ENU scene, over shaded-relief terrain that reloads as you pan and zoom. |
| **Adaptive logging** | Persistent CSV handle, periodic flush, automatic column expansion mid-flight, `TIMESTAMP` injection. |
| **Resilience** | Optional heavy dependencies (`rocketpy`, OpenGL, tile imagery) degrade gracefully — a driver or network problem on the field laptop never takes the dashboard down. |
| **Packaging** | One-file PyInstaller build with the mission icon embedded; seeds an editable `config/` and `data/` beside the executable on first run. |

---

## The four tabs

### 1. Telemetry Dashboard
- **Serial panel** — COM port dropdown (auto-refreshed), baud selector, Connect / Disconnect, live connection status.
- **Recording** — Start / Stop writes every parsed packet to CSV. Starting a recording resets the Kalman filter, buffers, packet count, attitude view, and map trace.
- **Command TX** — type a command (e.g. `START`) and send it up the same serial link; the last sent command is shown.
- **Plots** — seven live plots on a sliding `window_sec` window at ~20 FPS.
- **Info panel** — time since power, decoded flight state, battery %, packet count.
- **3D attitude view** — orientation from the latest roll/pitch/yaw, orbit/zoom with the mouse, "Reset View" to recentre.
- **Data table** — the last 10 packets with every field, columns added dynamically as new fields appear.

### 2. Map & Tracking
- **Manual fix row** — type lat / lon / alt and either **Plot Position** (treat as a fix) or **Set as Reference** (move the origin both maps are drawn around). "Ignore telemetry" keeps a manually plotted point from being overwritten by the next packet.
- **3D trajectory pane** — live trace + RocketPy ideal trajectory in a local East/North/Up frame, origin at the pad, drawn over Terrarium-encoded elevation tiles with a baked hillshade. Terrain re-fetches as the camera moves.
- **2D reference pane** — Folium map with a reference marker, GNSS marker, curved geodesic polyline, and a midpoint distance label (metres below 1 km, kilometres above).

### 3. Simulation Setup
- Raw JSON editor for `config/rocket_config.json` (the RocketPy input).
- **Reload from File**, **Save** (validates JSON, invalidates the cached config), **Save & Run Simulation** (solves off-thread and plots the result on the Map tab; reports apogee AGL and max speed).
- Cleanly disabled with an explanation when `rocketpy` is not installed.

### 4. Packet Format
- Edit `config/packet_format.json` — delimiter and field list — and apply it to the **live** parsing pipeline without restarting.

---

## Quick start (from source)

```bash
git clone <this-repo> GROUNDSTATION_VSLV
cd GROUNDSTATION_VSLV

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt

python run.py
```

`run.py` is the entry point — it wires up high-DPI scaling and the dark theme
before creating the Qt application, then launches the four-tab window.

> **Serial port in use?** Close the Arduino IDE Serial Monitor (or any other
> program holding the port) before connecting.

### Dependencies

Core: `PyQt5`, `PyQtWebEngine`, `pyqtgraph`, `PyOpenGL`, `pyserial`, `folium`,
`pandas`, `numpy`, `requests`, `Pillow`.

Optional: `rocketpy==1.13.0` — powers the ideal-trajectory simulation. It pulls
in the SciPy / matplotlib / netCDF4 stack, so it is heavy; the app runs fine
without it and the simulation controls simply stay disabled. The pin is
deliberate — `core/rocket_sim.py` reads `Flight.solution_array` by column
position, which is a version-sensitive RocketPy internal.

---

## Telemetry input format

The vehicle sends one delimited line per packet over serial. The schema lives
in `config/packet_format.json`:

```json
{
  "delimiter": ",",
  "fields": ["altitude", "pressure", "temperature", "roll", "pitch", "yaw", "lat", "lon"]
}
```

- **Flat list** — each name defaults to a `float` field.
- **Typed list** — `{"name": "ALTITUDE_M", "type": "float"}` with `type` one of `float`, `int`, `str`.
- **Header rows** — if an incoming line's tokens mostly match known field names, it is treated as a header: the field order is updated and persisted back to the JSON file.
- **Device timestamps** — a leading `YYYY-MM-DD HH:MM:SS` token is split off as `DEVICE_TIMESTAMP`.
- **Robustness** — shorter rows leave missing fields `None`; extra columns are kept as `EXTRA_0`, `EXTRA_1`, …; numeric fields extract the number out of noisy values (`"85.98W"` → `85.98`).

The processor probes common aliases for each role, so field names like
`altitude`/`ALT`/`ALTITUDE_M`, `roll`/`ROLL_DEG`, `lat`/`GNSS_LAT`,
`VOLTAGE_V`/`VBAT`, `FLIGHT_STATE`/`MODE` all work without extra wiring.

---

## Configuration

`config/config.json` is merged over built-in defaults and cached at startup.

| Key | Meaning | Default |
|---|---|---|
| `team_id` | Mission / team identifier | `2024ASI-CANSAT0032` |
| `baud_rate` | Default serial baud | `9600` |
| `window_sec` | Sliding plot window, seconds | `10` |
| `vspeed_smooth_window` | Vertical-speed moving-average length | `3` |
| `ref_lat`, `ref_lon`, `ref_alt` | Reference point / launch site (lat, lon, metres) | `26.712196, 84.305725, 68.0` |
| `volt_divisor` | `power_% = voltage / volt_divisor × 100` | `7.0` |
| `flight_state_map` | Numeric code → human-readable state | `{"0":"idle","1":"ascent","2":"descent"}` |
| `csv_path` | Flight log path | `data/Flight_<team_id>.csv` |
| `packet_format_path` | Packet schema location | `config/packet_format.json` |
| `attitude_model_path` | Vehicle CAD model for the 3D view | `models/vehicle.stl` |
| `attitude_model_size` | Longest model dimension after auto-fit | `2.4` |
| `attitude_model_scale` | Explicit scale multiplier (overrides auto-fit) | `null` |
| `attitude_model_rotation` | One-time `[rx, ry, rz]°` CAD-axis alignment | `null` |
| `attitude_invert` | Per-axis `[roll, pitch, yaw]` sign flip | `[false, false, false]` |
| `rocket_config_path` | RocketPy input file | `config/rocket_config.json` |
| `terrain_exaggeration` | Vertical exaggeration of the 3D relief (`1.0` = true scale) | `1.0` |
| `terrain_basemap_url` | Optional `{z}/{x}/{y}` imagery draped over the relief | `null` |
| `map_tile_url` | Tile source for the 2D map | Esri Dark Gray Canvas |
| `map_tile_attribution` | Attribution string for `map_tile_url` | Esri |

> **Tile providers:** the defaults use Esri's keyless Dark Gray Canvas. If you
> swap in a CARTO endpoint it must carry `?api_key=…` or the tiles come back
> watermarked.

---

## Data logging

`Start Recording` opens `csv_path` and appends one row per packet:

- **Persistent handle** with a flush every 10 packets — fast, and crash-tolerant.
- **`TIMESTAMP`** (wall clock, millisecond precision) is added automatically.
- **Adaptive schema** — if a new field appears mid-flight, the CSV is rewritten with the extra column and recording continues.
- Stopping a recording keeps the file handle open so a later restart appends; the handle is flushed and closed cleanly on exit.

CSV files are git-ignored.

---

## 3D attitude model

Drop the vehicle's CAD model at `models/vehicle.stl` (binary or ASCII STL, or
`.obj`). Until then a generic placeholder vehicle is shown. No extra packages
are needed — both formats are parsed directly.

Expected model axes: **+X → nose/forward, +Y → left, +Z → up**. Origin and
units don't matter (the mesh is recentred and auto-fit). If it points the wrong
way, set `attitude_model_rotation` in `config/config.json` rather than
re-exporting. See [`models/README.md`](models/README.md) for the full axis and
attitude conventions.

---

## Trajectory simulation (RocketPy)

`config/rocket_config.json` describes the environment, motor, airframe, and
launch conditions. **The values shipped are plausible placeholders** — replace
them with real numbers from your CAD and motor datasheet before trusting the
predicted trajectory. Motor thrust curves live in `config/motors/`; see
[`config/motors/README.md`](config/motors/README.md) for the format and how to
wire in a real motor.

Run it from the **Simulation Setup** tab. The solve runs on a background thread
and the result is drawn on the **Map & Tracking** tab's 3D pane as the "ideal"
trajectory, in the same local ENU frame as the live trace, with apogee and max
speed reported. Altitudes are normalised to AGL (height above the pad).

---

## Building a standalone executable

Produces a single self-contained binary — no Python or dependencies needed on
the target machine.

```bash
pip install pyinstaller

./build.sh          # Linux / macOS
build.bat           # Windows
pyinstaller build.spec   # any OS, manual
```

Output: `dist/VSSSIC_Ground_Station` (`.exe` on Windows), with
`images/vsssic-logo-1.ico` embedded and the console kept attached so a
failed launch isn't silent.

**Runtime files:** on first launch the executable seeds an editable `config/`
(from the bundled defaults) and a `data/` directory *next to itself* — not
inside the bundle, which a one-file build unpacks to a temp dir that is deleted
on exit. Place the executable in a writable directory.

Cross-platform builds must be made **on** the target platform. See
[`BUILD_INSTRUCTIONS.md`](BUILD_INSTRUCTIONS.md) and
[`QUICK_START.md`](QUICK_START.md) for details.

---

## Project layout

```
GROUNDSTATION_VSLV/
├── run.py                     # Entry point — python run.py
├── application/
│   ├── main.py                # QMainWindow, tabs, dark theme, window fitting
│   ├── core/
│   │   ├── config.py          # Cached JSON config + frozen-build path resolution
│   │   ├── serial_manager.py  # Threaded serial reader, port discovery, TX
│   │   ├── packet_parser.py   # Schema-driven parsing, header/timestamp detection
│   │   ├── telemetry_processor.py  # Kalman filter, vspeed, flight state, battery %
│   │   ├── data_buffer.py     # In-memory rolling buffers for plotting
│   │   ├── data_recorder.py   # Adaptive CSV logging
│   │   └── rocket_sim.py      # RocketPy integration (optional, guarded import)
│   └── ui/
│       ├── dashboard_tab.py   # Serial + recording + plots + info + table
│       ├── map_tab.py         # Manual fix, geodesic 2D map, 3D trajectory host
│       ├── trajectory_3d.py   # 3D ENU scene, shaded-relief terrain, live/ideal traces
│       ├── attitude_3d.py     # 3D orientation view
│       ├── mesh_loader.py     # Dependency-free STL/OBJ loader
│       ├── simulation_tab.py  # rocket_config.json editor + run controls
│       ├── packet_editor_tab.py  # Live packet-schema editor
│       └── plots.py           # PyQtGraph plot widgets
├── config/                    # config.json, packet_format.json, rocket_config.json, motors/
├── models/                    # vehicle.stl (+ conventions README)
├── images/                    # Icon and screenshots
├── legacy/                    # Original monolithic scripts, reference only
├── build.spec / build.sh / build.bat / setup.py
├── requirements.txt
└── changelog.md
```

Full description in [`STRUCTURE.md`](STRUCTURE.md).

---

## Architecture notes

- **Single shared parser** — the dashboard and the Packet Format editor hold the same `PacketParser`, so a schema edit takes effect on the live pipeline immediately.
- **Single simulation thread owner** — the Simulation Setup tab reuses the Map tab's `Trajectory3DView` rather than spawning a second `RocketSimThread`.
- **Graceful degradation** — `pyqtgraph.opengl`, `rocketpy`, and `requests`/`Pillow` are all guarded imports. Missing OpenGL → numeric-only 3D panels; missing RocketPy → disabled simulation; no network → trajectory over a blank background.
- **Frozen vs source paths** — `core/config.py` resolves read-only resources from the bundle but reads/writes user data (config edits, CSVs) beside the executable.
- **Two entry points in step** — `run.py` and `application/main.py` share `set_application_attributes()` and `apply_dark_theme()` so high-DPI and theme setup can't drift.

The full version-by-version history is in [`changelog.md`](changelog.md).

---

## Roadmap

- Anomaly detection on the live stream
- Telemetry replay mode (re-play a recorded CSV through the pipeline)

---

## Contributing

- **`master` is protected — do not push to it without the author's approval.**
- Fork, branch from `develop`, work in a virtual environment, open a PR.
- Keep new code consistent with the surrounding style (module docstrings that explain *why*, guarded imports for optional dependencies).

---

## Credits

**Author:** Shlok Satpathy
**Team:** VSSSIC · Team ID `2024ASI-CANSAT0032`

Built with PyQt5, PyQtGraph, Folium, and RocketPy.
