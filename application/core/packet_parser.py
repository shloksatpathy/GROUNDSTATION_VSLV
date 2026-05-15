import json
import re
import os


class PacketParser:

    def __init__(self, format_file="packet_format.json"):

        # Resolve path relative to this module's directory
        if not os.path.isabs(format_file):
            base_dir = os.path.dirname(os.path.abspath(__file__))
            format_file = os.path.join(base_dir, format_file)

        self.format_file = format_file
        self.delimiter = ","
        self.fields = []

        self._load_format()

        # regex to extract numbers safely
        self._num_re = re.compile(r"-?\d+\.?\d*")

    # -----------------------------------
    # Load packet format from JSON
    # -----------------------------------
    def _load_format(self):

        try:
            with open(self.format_file, "r") as f:
                config = json.load(f)

            self.delimiter = config.get("delimiter", ",")
            self.fields = config.get("fields", [])

            print("Packet format loaded:", self.fields)

        except Exception as e:
            print("Error loading packet format:", e)
            self.fields = []

    # -----------------------------------
    # Reload format dynamically
    # -----------------------------------
    def reload(self):
        self._load_format()

    # -----------------------------------
    # Parse incoming line
    # -----------------------------------
    def parse(self, line):

        if not line:
            return None

        try:
            parts = line.strip().split(self.delimiter)

            # Handle incomplete packet
            if len(parts) < len(self.fields):
                print("Incomplete packet:", parts)
                return None

            packet = {}

            for i, field in enumerate(self.fields):

                raw_val = parts[i]

                value = self._safe_convert(raw_val)

                packet[field] = value

            return packet

        except Exception as e:
            print("Parse error:", e)
            return None

    # -----------------------------------
    # Safe number conversion
    # -----------------------------------
    def _safe_convert(self, value):

        if value is None:
            return None

        try:
            match = self._num_re.search(str(value))

            if match:
                return float(match.group(0))

            return None

        except Exception:
            return None