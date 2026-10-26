import csv
import os

from PyQt5.QtCore import QObject, QTimer, pyqtSignal


class ReplaySource(QObject):
    """Stands in for SerialManager: plays a CSV file back as telemetry lines.

    Rows are re-emitted in the parser's field order, so both simulation files
    and recorded flight CSVs (TIMESTAMP + derived columns) replay correctly.
    """
    line_received = pyqtSignal(str)

    def __init__(self, csv_path, parser, interval_ms=1000):
        super().__init__()
        self.csv_path = csv_path
        self.parser = parser
        self.rows = []
        self.index = 0

        self.timer = QTimer()
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self._emit_next)

    def available_ports(self):
        return [os.path.basename(self.csv_path)]

    def connect(self, port, baudrate=None):
        """Start (or restart) playback from the first row."""
        with open(self.csv_path, newline="") as fh:
            self.rows = list(csv.DictReader(fh))
        self.index = 0
        self.timer.start()

    def disconnect(self):
        self.timer.stop()

    def write(self, data):
        pass

    def _emit_next(self):
        if self.index >= len(self.rows):
            self.timer.stop()
            return
        row = self.rows[self.index]
        self.index += 1
        self.line_received.emit(
            self.parser.delimiter.join(row.get(name) or "" for name in self.parser.field_names)
        )
