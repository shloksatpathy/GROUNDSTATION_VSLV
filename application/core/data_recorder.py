"""
Data Recorder — Adaptive CSV logging for telemetry data.

Ported from GS_cansat.py's CSV system with:
- Persistent file handle for fast appends
- Periodic flush (every 10 packets)
- Dynamic column expansion when new fields appear
- Thread-safe writes
"""

import csv
import os
import datetime
import threading

import pandas as pd

from core.config import load_config, resolve_path


class DataRecorder:

    def __init__(self, csv_path=None, initial_columns=None):

        if csv_path is None:
            cfg = load_config()
            csv_path = cfg.get("csv_path", "data/Flight_2024ASI-CANSAT0032.csv")

        self.csv_path = resolve_path(csv_path)
        self.columns = list(initial_columns) if initial_columns else ["TIMESTAMP"]
        self.recording = False
        self.packet_count = 0

        self._csv_fh = None
        self._csv_writer = None
        self._csv_has_header = False
        self._lock = threading.Lock()

    # -----------------------------------
    # Start / Stop recording
    # -----------------------------------
    def start(self):
        """Open CSV file handle and begin recording."""
        with self._lock:
            # Close any handle left over from a previous session
            if self._csv_fh:
                try:
                    self._csv_fh.close()
                except Exception:
                    pass
                self._csv_fh = None

            parent = os.path.dirname(self.csv_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            self._csv_has_header = (
                os.path.exists(self.csv_path) and
                os.path.getsize(self.csv_path) > 0
            )

            self._csv_fh = open(self.csv_path, "a", newline="")
            self._csv_writer = csv.DictWriter(
                self._csv_fh, fieldnames=self.columns
            )

            if not self._csv_has_header:
                try:
                    self._csv_writer.writeheader()
                    self._csv_fh.flush()
                    self._csv_has_header = True
                except Exception as e:
                    print(f"[RECORDER] Header write error: {e}")

            self.recording = True
            self.packet_count = 0
            print(f"[RECORDER] Recording started → {self.csv_path}")

    def stop(self):
        """Stop recording (file handle stays open for resume)."""
        self.recording = False
        with self._lock:
            if self._csv_fh:
                try:
                    self._csv_fh.flush()
                except Exception:
                    pass
        print("[RECORDER] Recording stopped.")

    # -----------------------------------
    # Record a parsed packet
    # -----------------------------------
    def record(self, packet):
        """Append a parsed packet dict to CSV. Adds TIMESTAMP automatically."""
        if not self.recording:
            return

        with self._lock:
            if not self._csv_fh or not self._csv_writer:
                return

            # Add timestamp to a copy — the caller's packet is also used by the UI
            packet = dict(packet)
            packet.setdefault(
                "TIMESTAMP",
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            )

            # Check for new columns
            new_keys = [k for k in packet.keys() if k not in self.columns]
            if new_keys:
                new_columns = list(self.columns) + new_keys
                self._rewrite_csv_with_new_columns(new_columns)

            # Write row
            row = {c: packet.get(c, "") for c in self.columns}
            try:
                self._csv_writer.writerow(row)
                self.packet_count += 1

                # Flush every 10 packets
                if self.packet_count % 10 == 0:
                    self._csv_fh.flush()
            except Exception as e:
                print(f"[RECORDER] Write error: {e}")
                # Fallback: pandas append
                try:
                    pd.DataFrame([row], columns=self.columns).to_csv(
                        self.csv_path, mode='a', header=False, index=False
                    )
                except Exception:
                    pass

    # -----------------------------------
    # Adaptive schema expansion
    # -----------------------------------
    def _rewrite_csv_with_new_columns(self, new_columns):
        """Rewrite CSV to accommodate new columns that appeared mid-flight."""
        ordered = list(new_columns)

        try:
            if os.path.exists(self.csv_path):
                df = pd.read_csv(self.csv_path)
            else:
                df = pd.DataFrame(columns=self.columns)

            for c in ordered:
                if c not in df.columns:
                    df[c] = ""
            df = df.reindex(columns=ordered)
            df.to_csv(self.csv_path, index=False)
        except Exception:
            with open(self.csv_path, "w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=ordered)
                writer.writeheader()

        # Re-open file handle
        try:
            self._csv_fh.close()
        except Exception:
            pass

        self.columns = ordered
        self._csv_fh = open(self.csv_path, "a", newline="")
        self._csv_writer = csv.DictWriter(self._csv_fh, fieldnames=self.columns)
        self._csv_has_header = True

        print(f"[RECORDER] Schema expanded: {ordered}")

    # -----------------------------------
    # Clean shutdown
    # -----------------------------------
    def close(self):
        """Flush and close the CSV file handle."""
        with self._lock:
            self.recording = False
            if self._csv_fh:
                try:
                    self._csv_fh.flush()
                    self._csv_fh.close()
                except Exception:
                    pass
                self._csv_fh = None
                self._csv_writer = None
        print("[RECORDER] File handle closed.")
