"""
Configuration loader for the Ground Station application.

Reads config.json from the application root directory and exposes
values with sensible defaults. Cached after first load.
"""

import json
import os
import shutil
import sys

_config_cache = None
_rocket_config_cache = None

_FROZEN = getattr(sys, "frozen", False)

# Where bundled read-only resources live (config/, images/).
# Frozen: the PyInstaller extraction dir. Source: two levels up from core/.
RESOURCE_ROOT = (
    getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    if _FROZEN
    else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

# Where the app reads and writes user data (config edits, flight CSVs).
# Never RESOURCE_ROOT when frozen — a onefile bundle extracts to a temp
# directory that is deleted on exit, taking recorded flight data with it.
DATA_ROOT = (
    os.path.dirname(os.path.abspath(sys.executable)) if _FROZEN else RESOURCE_ROOT
)

# Kept for backwards compatibility with callers that imported it.
PROJECT_ROOT = RESOURCE_ROOT


def _seed_from_bundle(target, rel_path):
    """Copy a bundled config file next to the executable on first run.

    Frozen builds ship config/ inside the bundle, which is read-only in
    practice. Seeding gives the operator an editable copy that persists.
    """
    if RESOURCE_ROOT == DATA_ROOT or os.path.exists(target):
        return

    bundled = os.path.join(RESOURCE_ROOT, rel_path)
    if not os.path.exists(bundled):
        return

    try:
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.copyfile(bundled, target)
        print(f"[CONFIG] Seeded {target} from bundle.")
    except Exception as e:
        print(f"[CONFIG] Could not seed {rel_path}: {e}")


def resolve_path(path):
    """Resolve a config-declared path to where the app should read/write it.

    Relative paths resolve against DATA_ROOT, not the CWD. If the file only
    exists inside the bundle, it is seeded to DATA_ROOT first.
    """
    if os.path.isabs(path):
        return path

    target = os.path.join(DATA_ROOT, path)
    _seed_from_bundle(target, path)
    return target


def resource_path(path):
    """Resolve a strictly read-only bundled asset (icons, templates)."""
    if os.path.isabs(path):
        return path
    return os.path.join(RESOURCE_ROOT, path)


# Default values (used if config.json is missing or incomplete)
_DEFAULTS = {
    "team_id": "2024ASI-CANSAT0032",
    "baud_rate": 9600,
    "window_sec": 10,
    "vspeed_smooth_window": 3,
    "ref_lat": 26.712196,
    "ref_lon": 84.305725,
    "ref_alt": 68.0,
    "volt_divisor": 7.0,
    "flight_state_map": {
        "0": "idle",
        "1": "ascent",
        "2": "descent"
    },
    "csv_path": "data/Flight_2024ASI-CANSAT0032.csv",
    "packet_format_path": "config/packet_format.json",

    # --- 3D attitude view ---
    # Path to the vehicle CAD model (.stl binary/ASCII, or .obj). If the file
    # is missing, the view falls back to a generic placeholder vehicle.
    "attitude_model_path": "models/vehicle.stl",
    # Longest model dimension, in view units, after auto-fit.
    "attitude_model_size": 2.4,
    # Explicit scale multiplier — overrides auto-fit when set.
    "attitude_model_scale": None,
    # One-time [rx, ry, rz] degrees to align the CAD file's axes with the
    # body frame the view expects: +X nose/forward, +Y left, +Z up.
    "attitude_model_rotation": None,
    # Flip the sign of [roll, pitch, yaw] for IMUs of the opposite handedness.
    "attitude_invert": [False, False, False],

    # --- 3D trajectory view (ideal via RocketPy + live telemetry) ---
    "rocket_config_path": "config/rocket_config.json",
    # Vertical exaggeration of the shaded-relief terrain under the trajectory.
    # 1.0 is true scale, which is what you want when reading terrain clearance
    # off the plot; raise it to dramatise low relief, at the cost of the
    # ground no longer being to the same scale as the trajectory beside it.
    "terrain_exaggeration": 1.0,
    # Optional {s}/{z}/{x}/{y} tile URL draped over the relief for map context
    # (water, roads, built-up areas). Left off by default — the relief reads
    # more clearly without it. Any keyless endpoint works, e.g. the same Esri
    # canvas the 2D map uses:
    #   "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
    # Avoid CARTO's basemaps.cartocdn.com without an api_key= parameter: they
    # return tiles stamped "API KEY REQUIRED" rather than an HTTP error.
    "terrain_basemap_url": None,

    # --- 2D reference map (map tab, right pane) ---
    # Tile source for the folium map. Esri's Dark Gray Canvas needs no API
    # key and matches the dark UI. Swap in any {z}/{x}/{y} endpoint you have
    # rights to — a CARTO url must carry "?api_key=..." or its tiles come
    # back watermarked.
    "map_tile_url": (
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
    ),
    # Attribution shown in the map corner. Required by most tile providers'
    # terms — keep it in step with whatever "map_tile_url" points at.
    "map_tile_attribution": "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ"
}


def load_config(force_reload=False):
    """Load config from config.json, with defaults for missing keys.

    Returns a dict. Cached after first call unless force_reload=True.
    """
    global _config_cache

    if _config_cache is not None and not force_reload:
        return _config_cache

    config = dict(_DEFAULTS)

    # Resolved here rather than at import time so the seed-from-bundle step
    # runs after sys.frozen/_MEIPASS are known to be set.
    config_file = resolve_path(os.path.join("config", "config.json"))

    try:
        with open(config_file, "r") as f:
            user_config = json.load(f)
        config.update(user_config)
    except FileNotFoundError:
        print(f"[CONFIG] {config_file} not found, using defaults.")
    except json.JSONDecodeError as e:
        print(f"[CONFIG] JSON parse error in {config_file}: {e}, using defaults.")
    except Exception as e:
        print(f"[CONFIG] Error loading config: {e}, using defaults.")

    _config_cache = config
    return config


def load_rocket_config(force_reload=False):
    """Load the RocketPy input file pointed to by 'rocket_config_path'.

    Returns a dict, or None if the file is missing/unparseable — callers
    (rocket_sim.py) must treat None as "simulation not runnable" rather
    than crash, same as a missing CAD model falls back to a placeholder
    in the attitude view.
    """
    global _rocket_config_cache

    if _rocket_config_cache is not None and not force_reload:
        return _rocket_config_cache

    path = get("rocket_config_path", "config/rocket_config.json")
    resolved = resolve_path(path)

    try:
        with open(resolved, "r") as f:
            _rocket_config_cache = json.load(f)
    except FileNotFoundError:
        print(f"[CONFIG] {resolved} not found — rocket simulation disabled.")
        _rocket_config_cache = None
    except json.JSONDecodeError as e:
        print(f"[CONFIG] JSON parse error in {resolved}: {e} — rocket simulation disabled.")
        _rocket_config_cache = None

    return _rocket_config_cache


def get(key, default=None):
    """Get a single config value by key."""
    cfg = load_config()
    return cfg.get(key, default if default is not None else _DEFAULTS.get(key))
