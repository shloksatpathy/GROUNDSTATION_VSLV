"""
Configuration loader for the Ground Station application.

Reads config.json from the application root directory and exposes
values with sensible defaults. Cached after first load.
"""

import json
import os

_config_cache = None
_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config",
    "config.json"
)

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

    try:
        with open(_CONFIG_FILE, "r") as f:
            user_config = json.load(f)
        config.update(user_config)
    except FileNotFoundError:
        print(f"[CONFIG] {_CONFIG_FILE} not found, using defaults.")
    except json.JSONDecodeError as e:
        print(f"[CONFIG] JSON parse error in {_CONFIG_FILE}: {e}, using defaults.")
    except Exception as e:
        print(f"[CONFIG] Error loading config: {e}, using defaults.")

    _config_cache = config
    return config


def get(key, default=None):
    """Get a single config value by key."""
    cfg = load_config()
    return cfg.get(key, default if default is not None else _DEFAULTS.get(key))
