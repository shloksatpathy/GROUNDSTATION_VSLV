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
    "volt_divisor": 7.0,
    "flight_state_map": {
        "0": "idle",
        "1": "ascent",
        "2": "descent"
    },
    "csv_path": "data/Flight_2024ASI-CANSAT0032.csv",
    "packet_format_path": "config/packet_format.json"
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


def get(key, default=None):
    """Get a single config value by key."""
    cfg = load_config()
    return cfg.get(key, default if default is not None else _DEFAULTS.get(key))
