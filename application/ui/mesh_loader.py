"""
Mesh loading for the 3D attitude view.

Reads STL (binary + ASCII) and Wavefront OBJ into plain numpy arrays, so the
ground station gains a 3D model view without pulling in numpy-stl/trimesh.

Everything here returns the same pair:
    vertices (Nv, 3) float32, faces (Nf, 3) int32
"""

import os
import struct

import numpy as np


class MeshLoadError(Exception):
    """Raised when a model file exists but cannot be interpreted."""


# -----------------------------------
# Public API
# -----------------------------------
def load_mesh(path):
    """Load an STL or OBJ file into (vertices, faces)."""
    ext = os.path.splitext(path)[1].lower()

    if ext == ".stl":
        return _load_stl(path)
    if ext == ".obj":
        return _load_obj(path)

    raise MeshLoadError(
        f"Unsupported model format '{ext}'. Export the CAD file to .stl "
        f"(binary or ASCII) or .obj."
    )


def normalize_mesh(verts, target_size=2.0, align_rotation=None, scale=None):
    """Centre a mesh on its origin and size it to fit the view.

    CAD exports arrive in arbitrary units (mm is typical) and are rarely
    centred on the vehicle's centre of mass, so the raw coordinates would put
    the model kilometres off-screen. This recentres on the bounding-box centre
    and scales the longest dimension to `target_size`.

    align_rotation: (rx, ry, rz) degrees applied *once* at load time to bring
        the CAD file's own axes onto the body frame the view expects
        (+X nose/forward, +Y left, +Z up).
    scale: explicit multiplier that overrides the automatic fit.
    """
    verts = np.asarray(verts, dtype=np.float32)
    if verts.size == 0:
        return verts

    if align_rotation is not None:
        verts = verts @ _euler_matrix_xyz(align_rotation).T.astype(np.float32)

    lo = verts.min(axis=0)
    hi = verts.max(axis=0)
    verts = verts - (lo + hi) / 2.0

    if scale is not None:
        factor = float(scale)
    else:
        extent = float(np.max(hi - lo))
        factor = (target_size / extent) if extent > 0 else 1.0

    return (verts * factor).astype(np.float32)


# -----------------------------------
# STL
# -----------------------------------
def _load_stl(path):
    with open(path, "rb") as f:
        header = f.read(84)
        if len(header) < 84:
            raise MeshLoadError(f"{os.path.basename(path)} is too small to be an STL.")

        tri_count = struct.unpack("<I", header[80:84])[0]
        body = f.read()

    # A binary STL is exactly 84 + 50*N bytes. Testing the size rather than the
    # leading "solid" keyword matters: plenty of CAD exporters write "solid"
    # into the binary header too.
    if len(body) == tri_count * 50:
        return _parse_binary_stl(body, tri_count)

    return _parse_ascii_stl(path)


def _parse_binary_stl(body, tri_count):
    dtype = np.dtype([
        ("normal", "<f4", (3,)),
        ("verts", "<f4", (3, 3)),
        ("attr", "<u2"),
    ])
    tris = np.frombuffer(body, dtype=dtype, count=tri_count)

    verts = tris["verts"].reshape(-1, 3).astype(np.float32)
    faces = np.arange(tri_count * 3, dtype=np.int32).reshape(-1, 3)
    return _weld(verts, faces)


def _parse_ascii_stl(path):
    verts = []
    with open(path, "r", errors="ignore") as f:
        for line in f:
            parts = line.split()
            if len(parts) == 4 and parts[0] == "vertex":
                verts.append((float(parts[1]), float(parts[2]), float(parts[3])))

    if len(verts) < 3:
        raise MeshLoadError(f"No triangles found in {os.path.basename(path)}.")
    if len(verts) % 3 != 0:
        verts = verts[: len(verts) - (len(verts) % 3)]

    v = np.array(verts, dtype=np.float32)
    faces = np.arange(len(v), dtype=np.int32).reshape(-1, 3)
    return _weld(v, faces)


# -----------------------------------
# OBJ
# -----------------------------------
def _load_obj(path):
    verts = []
    faces = []

    with open(path, "r", errors="ignore") as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue

            if parts[0] == "v" and len(parts) >= 4:
                verts.append((float(parts[1]), float(parts[2]), float(parts[3])))

            elif parts[0] == "f" and len(parts) >= 4:
                # "f v/vt/vn" — only the vertex index matters here.
                idx = []
                for token in parts[1:]:
                    raw = token.split("/")[0]
                    if not raw:
                        continue
                    i = int(raw)
                    # OBJ indices are 1-based, and negative means "from the end".
                    idx.append(i - 1 if i > 0 else len(verts) + i)

                # Fan-triangulate polygons of any size.
                for k in range(1, len(idx) - 1):
                    faces.append((idx[0], idx[k], idx[k + 1]))

    if not verts or not faces:
        raise MeshLoadError(f"No geometry found in {os.path.basename(path)}.")

    return np.array(verts, dtype=np.float32), np.array(faces, dtype=np.int32)


# -----------------------------------
# Helpers
# -----------------------------------
def _weld(verts, faces):
    """Merge duplicate vertices so smooth shading has shared normals.

    STL stores every triangle independently, which leaves each vertex
    duplicated ~6 times and makes the model render faceted and slow.
    """
    try:
        unique, inverse = np.unique(verts, axis=0, return_inverse=True)
    except Exception:
        return verts, faces

    return unique.astype(np.float32), inverse.reshape(-1)[faces].astype(np.int32)


def _euler_matrix_xyz(angles_deg):
    """Rotation matrix for X-then-Y-then-Z extrinsic rotations, in degrees."""
    rx, ry, rz = (np.radians(float(a)) for a in angles_deg)

    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)

    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])

    return mz @ my @ mx


# -----------------------------------
# Placeholder model
# -----------------------------------
def build_placeholder_mesh():
    """A simple launch-vehicle mesh used until a CAD model is supplied.

    Built in the view's body frame: +X nose/forward, +Y left, +Z up.
    """
    verts = []
    faces = []

    def add(v, f):
        offset = sum(len(chunk) for chunk in verts)
        verts.append(np.asarray(v, dtype=np.float32))
        faces.append(np.asarray(f, dtype=np.int32) + offset)

    seg = 24
    radius = 0.16
    tail_x, shoulder_x, nose_x = -0.55, 0.45, 1.0

    ang = np.linspace(0.0, 2.0 * np.pi, seg, endpoint=False)
    ring_y = radius * np.cos(ang)
    ring_z = radius * np.sin(ang)

    def ring(x):
        return np.stack([np.full(seg, x), ring_y, ring_z], axis=1)

    # --- Body tube ---
    tube = np.vstack([ring(tail_x), ring(shoulder_x)])
    tube_faces = []
    for i in range(seg):
        j = (i + 1) % seg
        tube_faces.append((i, j, seg + j))
        tube_faces.append((i, seg + j, seg + i))
    add(tube, tube_faces)

    # --- Nose cone ---
    cone = np.vstack([ring(shoulder_x), [[nose_x, 0.0, 0.0]]])
    add(cone, [(i, (i + 1) % seg, seg) for i in range(seg)])

    # --- Tail cap ---
    cap = np.vstack([ring(tail_x), [[tail_x, 0.0, 0.0]]])
    add(cap, [((i + 1) % seg, i, seg) for i in range(seg)])

    # --- Three fins, 120 deg apart ---
    for k in range(3):
        theta = np.radians(120.0 * k)
        c, s = np.cos(theta), np.sin(theta)

        # Fin profile in the X-radial plane, given a small thickness so it
        # catches the light from both sides instead of rendering flat black.
        profile = np.array([
            [tail_x, radius * 0.9],
            [tail_x - 0.18, radius + 0.30],
            [tail_x + 0.30, radius + 0.30],
            [tail_x + 0.42, radius * 0.9],
        ], dtype=np.float32)

        half = 0.015
        fin = []
        for side in (-half, half):
            for x, r in profile:
                fin.append([x, r * c - side * s, r * s + side * c])

        fin_faces = [
            (0, 1, 2), (0, 2, 3),           # near face
            (4, 6, 5), (4, 7, 6),           # far face
            (0, 4, 5), (0, 5, 1),           # edges
            (1, 5, 6), (1, 6, 2),
            (2, 6, 7), (2, 7, 3),
            (3, 7, 4), (3, 4, 0),
        ]
        add(fin, fin_faces)

    return np.vstack(verts).astype(np.float32), np.vstack(faces).astype(np.int32)
