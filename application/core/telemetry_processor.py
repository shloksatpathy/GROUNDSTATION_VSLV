"""
Telemetry Processor — Derived telemetry analytics.

Contains:
- AltitudeKalmanFilter: Kalman filter for altitude smoothing & velocity estimation
- TelemetryProcessor: Enriches raw packets with filtered altitude, vertical speed,
  flight state string, and battery percentage.

Ported from GS_cansat.py with the self.p/self.P casing bug fixed.
"""

import re
import numpy as np
from collections import deque

from core.config import load_config


# Robust numeric regex (shared)
_num_re = re.compile(r'[+\-]?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?')


class AltitudeKalmanFilter:
    """2-state Kalman filter: [altitude, velocity].

    Fixed version of the legacy altitudeKalmanFilter — the self.p vs self.P
    casing inconsistency has been corrected (all uses are now self.P).
    """

    def __init__(self, process_var=0.5, measurement_var=10):
        # State: [altitude, velocity]
        self.x = np.array([[0.0],
                           [0.0]])

        # Estimation covariance (FIXED: consistently named self.P)
        self.P = np.eye(2) * 500

        # Process noise
        self.Q_base = np.eye(2) * process_var

        # Measurement noise
        self.R = np.array([[measurement_var]])

        # Measurement matrix: we only observe altitude
        self.H = np.array([[1.0, 0.0]])

        self.initialised = False

    def update(self, measured_altitude, dt):
        """Run one predict-update cycle.

        Returns (filtered_altitude, filtered_velocity).
        """
        if not self.initialised:
            self.x[0, 0] = measured_altitude
            self.initialised = True

        # State transition matrix
        F = np.array([[1.0, dt],
                      [0.0, 1.0]])

        # Predict
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + self.Q_base

        # Update
        z = np.array([[measured_altitude]])
        y = z - (self.H @ self.x)
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)

        self.x = self.x + K @ y
        self.P = (np.eye(2) - K @ self.H) @ self.P

        return self.x[0, 0], self.x[1, 0]

    def reset(self):
        """Reset filter state."""
        self.__init__(
            process_var=self.Q_base[0, 0],
            measurement_var=self.R[0, 0]
        )


class TelemetryProcessor:
    """Enriches raw parsed packets with derived telemetry.

    Call process(packet) on each parsed packet to get an enriched copy with:
    - 'filtered_alt': Kalman-filtered altitude
    - 'filtered_vspeed': Kalman-estimated vertical velocity
    - 'smoothed_vspeed': Moving-average smoothed vertical speed
    - 'flight_state_str': Human-readable flight state
    - 'power_pct': Battery percentage estimate
    """

    def __init__(self):
        cfg = load_config()

        self.kalman = AltitudeKalmanFilter(
            process_var=0.3,
            measurement_var=15.0
        )
        self.prev_time = None

        # Vertical speed smoothing
        self.vspeed_smooth_window = cfg.get("vspeed_smooth_window", 3)
        self._vspeed_history = deque(maxlen=max(1, self.vspeed_smooth_window))

        # Flight state mapping
        state_map_raw = cfg.get("flight_state_map", {"0": "idle", "1": "ascent", "2": "descent"})
        self.flight_state_map = {int(k): v for k, v in state_map_raw.items()}

        # Voltage
        self.volt_divisor = cfg.get("volt_divisor", 7.0)

        # Role mappings (which field names to look for)
        self.alt_keys = ["ALTITUDE_M", "altitude", "ALT", "alt"]
        self.time_keys = ["TIME_SINCE_S", "time", "TIME", "time_s"]
        self.voltage_keys = ["VOLTAGE_V", "VOLTAGE", "VBAT", "V", "voltage"]
        self.state_keys = ["FLIGHT_STATE", "FLIGHT_STATE_CODE", "STATE", "MODE", "flight_state"]

    def process(self, packet):
        """Enrich a parsed packet dict with derived telemetry.

        Returns the same dict with added keys. Does not modify the original.
        """
        if not packet:
            return packet

        enriched = dict(packet)

        # --- Kalman-filtered altitude ---
        alt = self._find_numeric(packet, self.alt_keys)
        time_val = self._find_numeric(packet, self.time_keys)

        if alt is not None:
            if self.prev_time is not None and time_val is not None:
                dt = time_val - self.prev_time
                if dt <= 0:
                    dt = 0.01
            else:
                dt = 0.01

            filtered_alt, filtered_vel = self.kalman.update(alt, dt)
            enriched["filtered_alt"] = filtered_alt
            enriched["filtered_vspeed"] = filtered_vel

            # Smoothed vertical speed (moving average)
            self._vspeed_history.append(filtered_vel)
            smoothed = sum(self._vspeed_history) / len(self._vspeed_history)
            enriched["smoothed_vspeed"] = smoothed
        else:
            enriched["filtered_alt"] = None
            enriched["filtered_vspeed"] = None
            enriched["smoothed_vspeed"] = None

        if time_val is not None:
            self.prev_time = time_val

        # --- Flight state ---
        enriched["flight_state_str"] = self._derive_flight_state(packet)

        # --- Battery / Power ---
        voltage = self._find_numeric(packet, self.voltage_keys)
        if voltage is not None and self.volt_divisor and self.volt_divisor != 0:
            enriched["power_pct"] = (voltage / float(self.volt_divisor)) * 100.0
            enriched["voltage"] = voltage
        else:
            enriched["power_pct"] = None
            enriched["voltage"] = None

        return enriched

    def reset(self):
        """Reset Kalman filter and smoothing history."""
        self.kalman.reset()
        self.prev_time = None
        self._vspeed_history.clear()

    # -----------------------------------
    # Helpers
    # -----------------------------------
    def _find_numeric(self, packet, candidate_keys):
        """Look for a numeric value in the packet under any of the candidate keys."""
        for key in candidate_keys:
            if key in packet:
                v = packet[key]
                if v is None or v == "":
                    continue
                try:
                    return float(v)
                except (ValueError, TypeError):
                    m = _num_re.search(str(v))
                    if m:
                        try:
                            return float(m.group(0))
                        except Exception:
                            continue
        return None

    def _derive_flight_state(self, packet):
        """Extract flight state and map to human-readable string."""
        for key in self.state_keys:
            if key in packet:
                v = packet[key]
                if v is None or v == "":
                    continue
                try:
                    code = int(float(v))
                    return self.flight_state_map.get(code, f"code:{code}")
                except Exception:
                    sval = str(v).strip().lower()
                    for code, label in self.flight_state_map.items():
                        if label.lower() == sval:
                            return label
                    return sval
        return self.flight_state_map.get(0, "idle")
