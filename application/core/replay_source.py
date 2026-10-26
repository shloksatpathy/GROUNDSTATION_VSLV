import csv
import datetime
import os
import time

from PyQt5.QtCore import QObject, QTimer, pyqtSignal


class ReplaySource(QObject):
    """Stands in for SerialManager: plays a CSV file back as telemetry lines.

    Rows are re-emitted in the parser's field order, so both simulation files
    and recorded flight CSVs (TIMESTAMP + derived columns) replay correctly.
    Recorded files replay at their real TIMESTAMP spacing; files without one
    replay at interval_ms (the simulation's 10 Hz).
    """
    line_received = pyqtSignal(str)

    def __init__(self, csv_path, parser, interval_ms=100):
        super().__init__()
        self.csv_path = csv_path
        self.parser = parser
        self.interval_ms = interval_ms
        self.rows = []
        self.index = 0

        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._emit_next)

    def available_ports(self):
        return [os.path.basename(self.csv_path)]

    def connect(self, port, baudrate=None):
        """Start (or restart) playback from the first row, with no initial wait."""
        with open(self.csv_path, newline="") as fh:
            self.rows = list(csv.DictReader(fh))
        self.index = 0
        # Rows are scheduled against the playback start so timer latency never accumulates
        self.next_at = time.monotonic()
        self._emit_next()

    def disconnect(self):
        self.timer.stop()

    def write(self, data):
        pass

    def _emit_next(self):
        row = self.rows[self.index]
        self.index += 1
        self.line_received.emit(
            self.parser.delimiter.join(row.get(name) or "" for name in self.parser.field_names)
        )
        if self.index < len(self.rows):
            self.next_at += self._delay_ms(row, self.rows[self.index]) / 1000
            self.timer.start(max(0, int((self.next_at - time.monotonic()) * 1000)))

    def _delay_ms(self, row, next_row):
        if not row.get("TIMESTAMP") or not next_row.get("TIMESTAMP"):
            return self.interval_ms
        fmt = "%Y-%m-%d %H:%M:%S.%f"
        delta = (datetime.datetime.strptime(next_row["TIMESTAMP"], fmt)
                 - datetime.datetime.strptime(row["TIMESTAMP"], fmt))
        return max(0, int(delta.total_seconds() * 1000))
