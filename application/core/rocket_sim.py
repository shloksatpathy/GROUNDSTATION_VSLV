"""
RocketPy-backed "ideal" trajectory simulation.

rocketpy is an optional, heavy dependency (numpy/scipy/matplotlib stack) —
a ground-station laptop without it installed must still run the rest of the
app. The import is deferred/guarded the same way ui/attitude_3d.py guards
its pyqtgraph.opengl import.

Trajectory extraction reads rocketpy's Flight.solution_array directly
(verified against rocketpy==1.13.0): columns are
[t, x, y, z, vx, vy, vz, e0, e1, e2, e3, w1, w2, w3], with x = East and
y = North (meters, origin at the launch rail base) and z = altitude ABOVE
SEA LEVEL, not above the pad — z at t=0 equals Environment.elevation. Every
altitude this module returns is normalized to AGL (height above the pad)
so callers never have to think about the ASL/AGL distinction.
"""

import traceback

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from core.config import load_rocket_config, resolve_path

try:
    from rocketpy import Environment, SolidMotor, Rocket, Flight
    ROCKETPY_AVAILABLE = True
    ROCKETPY_IMPORT_ERROR = None
except Exception as e:                                      # pragma: no cover
    Environment = SolidMotor = Rocket = Flight = None
    ROCKETPY_AVAILABLE = False
    ROCKETPY_IMPORT_ERROR = e


class RocketSimError(Exception):
    """Raised for any user-facing simulation failure (missing config, bad
    parameters, solver failure) — the message is shown directly in the UI."""


def run_simulation():
    """Build Environment/Motor/Rocket/Flight from rocket_config.json and run it.

    Returns a dict:
        t              — np.ndarray, seconds since liftoff
        x, y, z        — np.ndarray, local East/North/Up meters, origin at
                          the pad (z is AGL, already elevation-corrected)
        apogee_agl     — float, meters above the pad
        max_speed      — float, m/s

    Raises RocketSimError with a user-facing message on any failure.
    """
    if not ROCKETPY_AVAILABLE:
        raise RocketSimError(f"rocketpy is not installed ({ROCKETPY_IMPORT_ERROR}).")

    cfg = load_rocket_config()
    if cfg is None:
        raise RocketSimError("config/rocket_config.json is missing or invalid.")

    try:
        env_cfg = cfg["environment"]
        env = Environment(
            latitude=env_cfg["latitude"],
            longitude=env_cfg["longitude"],
            elevation=env_cfg["elevation"],
        )
        if env_cfg.get("atmosphere_type") == "forecast":
            env.set_atmospheric_model(
                type="Forecast", file=env_cfg.get("forecast_file", "GFS")
            )
        else:
            env.set_atmospheric_model(type="standard_atmosphere")

        motor_cfg = dict(cfg["motor"])
        thrust_path = resolve_path(motor_cfg.pop("thrust_source"))
        motor = SolidMotor(thrust_source=thrust_path, **motor_cfg)

        rocket_cfg = cfg["rocket"]
        rocket = Rocket(
            radius=rocket_cfg["radius"],
            mass=rocket_cfg["mass"],
            inertia=rocket_cfg["inertia"],
            power_off_drag=rocket_cfg["power_off_drag"],
            power_on_drag=rocket_cfg["power_on_drag"],
            center_of_mass_without_motor=rocket_cfg["center_of_mass_without_motor"],
            coordinate_system_orientation=rocket_cfg["coordinate_system_orientation"],
        )
        rocket.add_motor(motor, position=rocket_cfg["motor_position"])
        rocket.set_rail_buttons(**rocket_cfg["rail_buttons"])
        rocket.add_nose(**rocket_cfg["nose"])

        fins = rocket_cfg["fins"]
        rocket.add_trapezoidal_fins(
            n=fins["n"],
            root_chord=fins["root_chord"],
            tip_chord=fins["tip_chord"],
            span=fins["span"],
            position=fins["position"],
        )
        if rocket_cfg.get("tail"):
            rocket.add_tail(**rocket_cfg["tail"])

        flight_cfg = cfg["flight"]
        flight = Flight(
            rocket=rocket,
            environment=env,
            rail_length=flight_cfg["rail_length"],
            inclination=flight_cfg["inclination"],
            heading=flight_cfg["heading"],
        )

        return _extract_trajectory(flight)

    except RocketSimError:
        raise
    except Exception as e:
        traceback.print_exc()
        raise RocketSimError(f"Simulation failed: {e}")


def _extract_trajectory(flight):
    """Pull (t, x, y, z-AGL) sample arrays and summary stats out of a solved Flight."""
    sol = np.asarray(flight.solution_array)
    t, x, y, z_asl = sol[:, 0], sol[:, 1], sol[:, 2], sol[:, 3]

    elevation = float(flight.env.elevation)
    z = z_asl - elevation

    return {
        "t": t,
        "x": x,
        "y": y,
        "z": z,
        "apogee_agl": float(flight.apogee) - elevation,
        "max_speed": float(flight.max_speed),
    }


class RocketSimThread(QThread):
    """Runs run_simulation() off the GUI thread.

    Mirrors core/serial_manager.SerialReaderThread's shape: a QThread that
    emits a signal with the result instead of returning one, since a
    RocketPy solve takes a few seconds and must not block the UI.
    """
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(str)

    def run(self):
        try:
            result = run_simulation()
            self.finished_ok.emit(result)
        except RocketSimError as e:
            self.finished_err.emit(str(e))
        except Exception as e:                               # pragma: no cover
            traceback.print_exc()
            self.finished_err.emit(f"Unexpected error: {e}")
