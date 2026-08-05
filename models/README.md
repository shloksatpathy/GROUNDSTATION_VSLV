# Vehicle models — 3D attitude view

Drop the vehicle's CAD model here as **`vehicle.stl`** and the dashboard's
3D attitude panel will use it instead of the built-in placeholder.

## What the loader accepts

| Format | Notes |
|---|---|
| `.stl` | Binary or ASCII. **Preferred** — this is what every CAD tool exports. |
| `.obj`  | Wavefront OBJ. Vertices and faces only; materials/textures are ignored. |

No extra Python packages are required — both formats are parsed directly.

Exporting from native CAD (STEP, SLDPRT, F3D, IPT): use *File → Export → STL*.
A **medium/coarse** tessellation is plenty. Anything past ~200k triangles only
costs frame rate; the app prints a warning when it sees a model that dense.

## Axis convention

The view expects the model's own axes to be:

```
+X  →  nose / forward
+Y  →  left
+Z  →  up
```

Units and origin do not matter — the model is automatically recentred on its
bounding box and scaled to fit the view.

If the model comes out pointing the wrong way, don't re-export it. Set a
one-time correction in `config/config.json`, in degrees, applied X then Y then Z:

```json
"attitude_model_rotation": [0, 0, 90]
```

## Other settings (`config/config.json`)

| Key | Meaning |
|---|---|
| `attitude_model_path` | Model location, relative to the app directory. Default `models/vehicle.stl`. |
| `attitude_model_size` | Longest model dimension after auto-fit. Default `2.0`. |
| `attitude_model_scale` | Explicit multiplier; overrides auto-fit when set. |
| `attitude_model_rotation` | `[rx, ry, rz]` degrees to align CAD axes to the body frame. |
| `attitude_invert` | `[roll, pitch, yaw]` booleans — flip a sign if the IMU reports the opposite handedness. |

## Attitude convention

Angles are interpreted as the standard aerospace intrinsic Z-Y-X sequence
(yaw, then pitch, then roll) on a body frame of X-forward / Y-right / Z-down.
The fixed triad in the view is X = North, Y = West, Z = Up.
