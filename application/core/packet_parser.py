"""
Packet Parser — JSON-driven telemetry packet parser.

Supports typed field schemas ({"name": "ALTITUDE_M", "type": "float"})
and flat string lists (["altitude", "pressure"]).

Ported from GS_cansat.py with robust numeric extraction, header detection,
device timestamp detection, and extra-field handling.
"""

import json
import re
import os

from core.config import load_config


class PacketParser:

    # Robust numeric regex: handles scientific notation, leading +/-
    _num_re = re.compile(r'[+\-]?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?')

    def __init__(self, format_file=None):

        if format_file is None:
            cfg = load_config()
            format_file = cfg.get("packet_format_path", "packet_format.json")

        # Resolve path relative to this module's directory
        if not os.path.isabs(format_file):
            base_dir = os.path.dirname(os.path.abspath(__file__))
            format_file = os.path.join(base_dir, format_file)

        self.format_file = format_file
        self.delimiter = ","
        self.fields = []          # list of {"name": str, "type": str}
        self.field_names = []     # convenience: just the name strings

        self._load_format()

    # -----------------------------------
    # Load packet format from JSON
    # -----------------------------------
    def _load_format(self):

        try:
            with open(self.format_file, "r") as f:
                config = json.load(f)

            self.delimiter = config.get("delimiter", ",")
            raw_fields = config.get("fields", [])

            # Normalize fields to typed format
            self.fields = []
            for field in raw_fields:
                if isinstance(field, dict):
                    # Already typed: {"name": "X", "type": "float"}
                    self.fields.append({
                        "name": field.get("name", f"col{len(self.fields)}"),
                        "type": field.get("type", "str")
                    })
                elif isinstance(field, str):
                    # Flat string — default to float type
                    self.fields.append({"name": field, "type": "float"})
                else:
                    self.fields.append({"name": str(field), "type": "str"})

            self.field_names = [f["name"] for f in self.fields]
            print(f"[PARSER] Loaded {len(self.fields)} fields: {self.field_names}")

        except Exception as e:
            print(f"[PARSER] Error loading packet format: {e}")
            self.fields = []
            self.field_names = []

    # -----------------------------------
    # Reload format dynamically
    # -----------------------------------
    def reload(self):
        self._load_format()

    # -----------------------------------
    # Parse incoming line
    # -----------------------------------
    def parse(self, line):
        """Tolerant parse: accepts shorter/longer rows, detects headers
        and device timestamps, extracts numeric substrings for numeric fields."""

        if not line:
            return None

        try:
            parts = [p.strip() for p in line.strip().split(self.delimiter)]

            # --- Header detection ---
            if self._is_header(parts):
                self._update_fields_from_header(parts)
                return None  # header line, not data

            # --- Device timestamp prefix detection ---
            device_ts = None
            if parts and re.match(r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}', parts[0]):
                device_ts = parts.pop(0)

            # --- Parse fields ---
            packet = {}

            for i, field in enumerate(self.fields):
                name = field.get("name", f"col{i}")
                ftype = field.get("type", "str")
                raw = parts[i] if i < len(parts) else ""

                try:
                    if ftype == "float":
                        raw_clean = self._clean_numeric(raw)
                        packet[name] = float(raw_clean) if raw_clean != "" else None
                    elif ftype == "int":
                        raw_clean = self._clean_numeric(raw)
                        packet[name] = int(float(raw_clean)) if raw_clean != "" else None
                    else:
                        packet[name] = raw
                except Exception:
                    packet[name] = raw

            # --- Extra fields beyond schema ---
            if len(parts) > len(self.fields):
                for j in range(len(self.fields), len(parts)):
                    packet[f"EXTRA_{j - len(self.fields)}"] = parts[j]

            # --- Attach device timestamp if detected ---
            if device_ts is not None:
                packet["DEVICE_TIMESTAMP"] = device_ts

            return packet

        except Exception as e:
            print(f"[PARSER] Parse error: {e}")
            return None

    # -----------------------------------
    # Header detection
    # -----------------------------------
    def _is_header(self, parts):
        """Check if the incoming tokens look like a header row."""
        if not parts or not self.field_names:
            return False
        # If most tokens match known field names (case-insensitive), it's a header
        matches = sum(
            1 for p in parts
            if any(p.strip().lower() == fn.lower() for fn in self.field_names)
        )
        return matches >= len(parts) * 0.5 and matches >= 2

    def _update_fields_from_header(self, parts):
        """Re-order fields based on detected header and save."""
        new_fields = []
        for token in parts:
            token_clean = token.strip()
            match = next(
                (f for f in self.fields if f["name"].lower() == token_clean.lower()),
                None
            )
            if match:
                new_fields.append(match)
            else:
                new_fields.append({"name": token_clean, "type": "str"})

        self.fields = new_fields
        self.field_names = [f["name"] for f in self.fields]

        # Persist updated format
        try:
            with open(self.format_file, "w") as fh:
                json.dump({
                    "delimiter": self.delimiter,
                    "fields": self.fields
                }, fh, indent=2)
        except Exception as e:
            print(f"[PARSER] Could not save updated format: {e}")

    # -----------------------------------
    # Safe numeric extraction
    # -----------------------------------
    def _clean_numeric(self, raw):
        """Extract numeric substring (e.g. '85.98W' -> '85.98'), or '' if none."""
        if raw is None:
            return ""
        s = str(raw).strip()
        m = self._num_re.search(s)
        return m.group(0) if m else ""